// The workbook writer: a copy of forensic_engine.xlsx_cell_parts and
// write_simple_xlsx, a minimal zip, and the XLSX exporter. No third-party
// code. The zip is deflated by the browser's own CompressionStream
// ("deflate-raw"), and stored uncompressed -- still a valid workbook --
// where that does not exist. The http://schemas.openxmlformats.org/ strings
// below are XML namespace NAMES, never fetched (and the CSP refuses every
// fetch). Every string cell is an inline string, so nothing in the file is
// ever a formula, and every piece of evidence text is XML-escaped.

var XLSX_MAX_COL_WIDTH = 80;       // forensic_engine.XLSX_MAX_COL_WIDTH
var XLSX_WIDTH_SAMPLE_ROWS = 200;  // forensic_engine.XLSX_WIDTH_SAMPLE_ROWS
var EXCEL_CELL_LIMIT = 32000;
var EXCEL_DT_CELL = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?$/;
var NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
var NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
var NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships";
var NS_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types";
var CT_SHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml";
var SHEET_FORBIDDEN = /[\[\]:*?\/\\]/g;   // forensic_engine._XLSX_SHEET_FORBIDDEN
var STYLE_BOLD = 1, STYLE_DATE = 2, STYLE_DATE_MS = 3;
var XML_HEAD = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n";
var STYLES = XML_HEAD +
  "<styleSheet xmlns=\"" + NS_MAIN + "\">" +
  "<numFmts count=\"2\"><numFmt numFmtId=\"164\" formatCode=\"yyyy-mm-dd hh:mm:ss\"/>" +
  "<numFmt numFmtId=\"165\" formatCode=\"yyyy-mm-dd hh:mm:ss.000\"/></numFmts>" +
  "<fonts count=\"2\"><font><sz val=\"11\"/><name val=\"Calibri\"/></font>" +
  "<font><b/><sz val=\"11\"/><name val=\"Calibri\"/></font></fonts>" +
  "<fills count=\"2\"><fill><patternFill patternType=\"none\"/></fill>" +
  "<fill><patternFill patternType=\"gray125\"/></fill></fills>" +
  "<borders count=\"1\"><border><left/><right/><top/><bottom/><diagonal/></border></borders>" +
  "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>" +
  "<cellXfs count=\"4\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/>" +
  "<xf numFmtId=\"0\" fontId=\"1\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyFont=\"1\"/>" +
  "<xf numFmtId=\"164\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyNumberFormat=\"1\"/>" +
  "<xf numFmtId=\"165\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyNumberFormat=\"1\"/></cellXfs>" +
  "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles></styleSheet>";

function isHighSurrogate(c) { return c >= 0xD800 && c <= 0xDBFF; }
function isLowSurrogate(c) { return c >= 0xDC00 && c <= 0xDFFF; }

function cpLength(s) {
  // Python len(): code points, not UTF-16 units.
  var n = s.length;
  for (var i = 0; i < s.length - 1; i++) {
    if (isHighSurrogate(s.charCodeAt(i)) && isLowSurrogate(s.charCodeAt(i + 1))) { n--; i++; }
  }
  return n;
}

function cpSlice(s, n) {
  // Python s[:n], counted in code points.
  var units = 0, seen = 0;
  while (seen < n && units < s.length) {
    units += (isHighSurrogate(s.charCodeAt(units)) && units + 1 < s.length &&
              isLowSurrogate(s.charCodeAt(units + 1))) ? 2 : 1;
    seen++;
  }
  return s.slice(0, units);
}

function pad(n, width) {
  var s = String(n);
  while (s.length < width) s = "0" + s;
  return s;
}

function textCell(text) {
  var length = cpLength(text);
  if (length > EXCEL_CELL_LIMIT) {
    text = cpSlice(text, EXCEL_CELL_LIMIT) + "…[TRUNCATED BY EXCEL: " + fmtCount(length) +
      " characters total, " + fmtCount(length - EXCEL_CELL_LIMIT) + " not shown. The complete value is in the CSV " +
      "and JSON exports and in the app's blob viewer.]";
  }
  return {t: "s", v: text, style: 0, len: length};
}

function validDateTime(y, mo, d, h, mi, s) {
  if (y < 1 || y > 9999 || mo < 1 || mo > 12 || d < 1 || h > 23 || mi > 59 || s > 59) return false;
  var probe = new Date(0);
  probe.setUTCFullYear(y, mo - 1, d);
  return probe.getUTCMonth() === mo - 1 && probe.getUTCDate() === d;
}

function pyStrip(s) {
  // str.strip(): Python's whitespace, which also takes \x1c-\x1f and \x85.
  return s.replace(/^[\s\x1c-\x1f\x85]+|[\s\x1c-\x1f\x85]+$/g, "");
}

function xlsxCell(v, ts) {
  // forensic_engine.xlsx_cell_parts, on the stored cell. The island already
  // holds what _cell/_clean made of each value (timestamp text already in
  // excel_datetime's shape), so what is decided here is the cell's TYPE.
  if (isBlank(v)) return null;
  if (typeof v === "number") return {t: "n", v: v, style: 0, len: 0};
  var tag = v.charAt(0);
  if (tag === TAG_DT) {
    var dt = parseTaggedDt(v);
    if (dt && ts) {
      // excel_datetime_value(datetime): the wall-clock digits, zone dropped,
      // microseconds kept; its sizing length is its format's length.
      return {t: "d", v: [dt.y, dt.mo, dt.d, dt.h, dt.mi, dt.s, dt.us],
              style: dt.us ? STYLE_DATE_MS : STYLE_DATE, len: dt.us ? 23 : 19};
    }
    if (dt) {
      // _cell(datetime) outside a timestamp column: an aware value as its
      // UTC instant with "Z", a naive one with no zone; microseconds kept.
      var y = dt.y, mo = dt.mo, d = dt.d, h = dt.h, mi = dt.mi, s = dt.s;
      if (dt.offset !== null) {
        var u = new Date(Math.floor(dt.instant) * 1000);
        y = u.getUTCFullYear(); mo = u.getUTCMonth() + 1; d = u.getUTCDate();
        h = u.getUTCHours(); mi = u.getUTCMinutes(); s = u.getUTCSeconds();
      }
      return textCell(pad(y, 4) + "-" + pad(mo, 2) + "-" + pad(d, 2) + "T" + pad(h, 2) + ":" +
                      pad(mi, 2) + ":" + pad(s, 2) + (dt.us ? "." + pad(dt.us, 6) : "") +
                      (dt.offset !== null ? "Z" : ""));
    }
    return textCell(v.slice(1));
  }
  if (tag === TAG_BIG) return textCell(v.slice(1));
  if (tag === TAG_FLOAT) {
    var f = Number(v.slice(1));
    return isFinite(f) ? {t: "n", v: f, style: 0, len: 0} : textCell(v.slice(1));
  }
  if (ts) {
    var m = EXCEL_DT_CELL.exec(pyStrip(v));
    if (m && validDateTime(+m[1], +m[2], +m[3], +m[4], +m[5], +m[6])) {
      var us = m[7] ? Number((m[7] + "00000").slice(0, 6)) : 0;
      return {t: "d", v: [+m[1], +m[2], +m[3], +m[4], +m[5], +m[6], us],
              style: m[7] ? STYLE_DATE_MS : STYLE_DATE, len: cpLength(v)};
    }
  }
  return textCell(v);
}

var EXCEL_EPOCH_DAY = Math.round(wallSeconds(1899, 12, 30, 0, 0, 0) / 86400);

function excelSerial(p) {
  // openpyxl.utils.datetime.to_excel, operation for operation.
  var days = Math.round(wallSeconds(p[0], p[1], p[2], 0, 0, 0) / 86400) - EXCEL_EPOCH_DAY;
  if (days > 0 && days <= 60) days -= 1;
  return days + ((p[3] * 3600) + (p[4] * 60) + p[5] + p[6] / 1e6) / 86400;
}

function stripZeros(text) {
  return text.indexOf(".") >= 0 ? text.replace(/0+$/, "").replace(/\.$/, "") : text;
}

function numberText(x) {
  // openpyxl's safe_string: "%.16g" % value -- the digits the app's
  // workbook carries, so a reader parses the very same double, and an
  // integral value reads back as an int exactly as from the app's file.
  if (x === 0) return "0";
  var sci = x.toExponential(15).split("e"), exp = Number(sci[1]);
  if (exp < -4 || exp >= 16) {
    return stripZeros(sci[0]) + "e" + (exp < 0 ? "-" : "+") + pad(Math.abs(exp), 2);
  }
  return stripZeros(x.toFixed(15 - exp));
}

function colName(n) {
  var s = "";
  while (n > 0) { var m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

// In "u" mode a well-formed surrogate PAIR is one code point outside
// U+D800..U+DFFF, so only a LONE surrogate matches that range here.
var XML_UNSAFE = /[&<>"\r\t\n\x00-\x08\x0B\x0C\x0E-\x1F￾￿\uD800-\uDFFF]/gu;

function xmlEscape(s, attr) {
  // Every evidence string passes through here. & < > always; " and the
  // whitespace characters in an attribute; \r as a character reference
  // (lxml writes it so, and a raw \r would be read back as \n). A character
  // XML 1.0 cannot carry at all -- a control character, a lone surrogate,
  // U+FFFE/U+FFFF -- is written as the visible escape _safe_text uses,
  // never dropped: the island has already escaped the first two, and the
  // app's own writer refuses the last two outright.
  return String(s).replace(XML_UNSAFE, function (ch) {
    switch (ch) {
      case "&": return "&amp;";
      case "<": return "&lt;";
      case ">": return "&gt;";
      case "\"": return attr ? "&quot;" : ch;
      case "\r": return "&#13;";
      case "\n": return attr ? "&#10;" : ch;
      case "\t": return attr ? "&#9;" : ch;
    }
    var code = ch.charCodeAt(0);
    if (code < 0x20) return "\\x" + pad(code.toString(16).toUpperCase(), 2);
    return "\\u" + code.toString(16).toUpperCase();
  });
}

function cellXml(ref, cell) {
  if (!cell) return "";
  if (cell.t === "s") {
    return "<c r=\"" + ref + "\"" + (cell.style ? " s=\"" + cell.style + "\"" : "") +
      " t=\"inlineStr\"><is><t xml:space=\"preserve\">" + xmlEscape(cell.v, false) + "</t></is></c>";
  }
  if (cell.t === "d") {
    return "<c r=\"" + ref + "\" s=\"" + cell.style + "\" t=\"n\"><v>" + numberText(excelSerial(cell.v)) + "</v></c>";
  }
  return "<c r=\"" + ref + "\" t=\"n\"><v>" + numberText(cell.v) + "</v></c>";
}

function sheetXml(headers, rows, ts, frozen, filtered) {
  // The sheet as an array of text pieces, one per row, so no single string
  // has to hold a whole large sheet.
  var stamps = headers.map(function (h, c) { return !!ts[c]; });
  var widths = headers.map(function (h) { return cpLength(String(h)); });
  var letters = [];
  function letter(c) { return letters[c] || (letters[c] = colName(c + 1)); }
  var sample = Math.min(rows.length, XLSX_WIDTH_SAMPLE_ROWS);
  for (var r = 0; r < sample; r++) {
    for (var c = 0; c < rows[r].length && c < widths.length; c++) {
      var cell = xlsxCell(rows[r][c], stamps[c]);
      if (cell && cell.len > widths[c]) widths[c] = cell.len;
    }
  }
  var parts = [XML_HEAD + "<worksheet xmlns=\"" + NS_MAIN + "\" xmlns:r=\"" + NS_REL + "\">"];
  if (frozen) {
    parts.push("<sheetViews><sheetView workbookViewId=\"0\"><pane ySplit=\"1\" topLeftCell=\"A2\" " +
      "activePane=\"bottomLeft\" state=\"frozen\"/><selection pane=\"bottomLeft\"/></sheetView></sheetViews>");
  }
  parts.push("<sheetFormatPr defaultRowHeight=\"15\"/>");
  if (widths.length) {
    parts.push("<cols>" + widths.map(function (w, i) {
      var width = Math.min(Math.max(12, w + 2), XLSX_MAX_COL_WIDTH);
      return "<col min=\"" + (i + 1) + "\" max=\"" + (i + 1) + "\" width=\"" + width + "\" customWidth=\"1\"/>";
    }).join("") + "</cols>");
  }
  parts.push("<sheetData>");
  parts.push("<row r=\"1\">" + headers.map(function (h, c) {
    return cellXml(letter(c) + "1", {t: "s", v: String(h), style: STYLE_BOLD});
  }).join("") + "</row>");
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i], n = i + 2, line = "<row r=\"" + n + "\">";
    for (var k = 0; k < row.length; k++) line += cellXml(letter(k) + n, xlsxCell(row[k], !!stamps[k]));
    parts.push(line + "</row>");
  }
  parts.push("</sheetData>");
  if (filtered && rows.length && headers.length) {
    parts.push("<autoFilter ref=\"A1:" + colName(headers.length) + (rows.length + 1) + "\"/>");
  }
  parts.push("</worksheet>");
  return parts;
}

function workbookFiles(sheetName, headers, rows, ts, note) {
  var title = cpSlice(String(sheetName || "Sheet").replace(SHEET_FORBIDDEN, " "), 31) || "Sheet";
  var noteRows = note.replace(/\n$/, "").split("\n").map(function (line) { return [isBlank(line) ? null : line]; });
  var rels = function (items) {
    return XML_HEAD + "<Relationships xmlns=\"" + NS_PKG + "\">" + items.map(function (it) {
      return "<Relationship Id=\"" + it[0] + "\" Type=\"" + NS_REL + "/" + it[1] + "\" Target=\"" + it[2] + "\"/>";
    }).join("") + "</Relationships>";
  };
  return [
    ["[Content_Types].xml", XML_HEAD + "<Types xmlns=\"" + NS_TYPES + "\">" +
      "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>" +
      "<Default Extension=\"xml\" ContentType=\"application/xml\"/>" +
      "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>" +
      "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"" + CT_SHEET + "\"/>" +
      "<Override PartName=\"/xl/worksheets/sheet2.xml\" ContentType=\"" + CT_SHEET + "\"/>" +
      "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>" +
      "</Types>"],
    ["_rels/.rels", rels([["rId1", "officeDocument", "xl/workbook.xml"]])],
    ["xl/workbook.xml", XML_HEAD + "<workbook xmlns=\"" + NS_MAIN + "\" xmlns:r=\"" + NS_REL + "\"><sheets>" +
      "<sheet name=\"" + xmlEscape(title, true) + "\" sheetId=\"1\" r:id=\"rId1\"/>" +
      "<sheet name=\"Provenance\" sheetId=\"2\" r:id=\"rId2\"/></sheets></workbook>"],
    ["xl/_rels/workbook.xml.rels", rels([["rId1", "worksheet", "worksheets/sheet1.xml"],
                                         ["rId2", "worksheet", "worksheets/sheet2.xml"],
                                         ["rId3", "styles", "styles.xml"]])],
    ["xl/styles.xml", STYLES],
    ["xl/worksheets/sheet1.xml", sheetXml(headers, rows, ts, true, true)],
    ["xl/worksheets/sheet2.xml", sheetXml(["Provenance of sheet 1"], noteRows, [false], false, false)]
  ];
}

var CRC_TABLE = (function () {
  var table = new Uint32Array(256);
  for (var n = 0; n < 256; n++) {
    var c = n;
    for (var k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes, previous) {
  // Table-driven CRC-32 (the zip polynomial). `previous` continues a CRC
  // over a part written in several chunks.
  var c = previous === undefined ? 0xFFFFFFFF : (previous ^ 0xFFFFFFFF) >>> 0;
  for (var i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

function encodeParts(content) {
  // A part's text as UTF-8 chunks of about 4 MB each.
  var enc = new TextEncoder(), pieces = typeof content === "string" ? [content] : content;
  var chunks = [], buffer = [], size = 0;
  for (var i = 0; i < pieces.length; i++) {
    buffer.push(pieces[i]);
    size += pieces[i].length;
    if (size > (1 << 22)) { chunks.push(enc.encode(buffer.join(""))); buffer = []; size = 0; }
  }
  if (buffer.length || !chunks.length) chunks.push(enc.encode(buffer.join("")));
  return chunks;
}

function deflateRaw(chunks, store) {
  if (store || typeof CompressionStream === "undefined") return Promise.resolve(null);
  var stream;
  try { stream = new Blob(chunks).stream().pipeThrough(new CompressionStream("deflate-raw")); }
  catch (e) { return Promise.resolve(null); }
  return new Response(stream).blob().then(function (blob) { return blob; }, function () { return null; });
}

function zipFiles(files, store) {
  // A zip of `files` ([name, text or text pieces]), each entry deflated or,
  // when `store` is set or the browser cannot deflate, stored.
  var enc = new TextEncoder();
  var entries = files.map(function (f) {
    var chunks = encodeParts(f[1]), crc, size = 0;
    chunks.forEach(function (ch) { crc = crc32(ch, crc); size += ch.length; });
    return {name: enc.encode(f[0]), chunks: chunks, crc: crc, size: size};
  });
  return Promise.all(entries.map(function (e) { return deflateRaw(e.chunks, store); })).then(function (packed) {
    var parts = [], central = [], offset = 0;
    entries.forEach(function (e, i) {
      var method = packed[i] ? 8 : 0, bodySize = packed[i] ? packed[i].size : e.size;
      var local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true);
      local.setUint16(4, 20, true);
      local.setUint16(6, 0x0800, true);          // UTF-8 names
      local.setUint16(8, method, true);
      local.setUint16(10, 0, true);              // 00:00:00
      local.setUint16(12, 0x21, true);           // 1980-01-01
      local.setUint32(14, e.crc, true);
      local.setUint32(18, bodySize, true);
      local.setUint32(22, e.size, true);
      local.setUint16(26, e.name.length, true);
      local.setUint16(28, 0, true);
      parts.push(new Uint8Array(local.buffer), e.name);
      if (packed[i]) parts.push(packed[i]);
      else e.chunks.forEach(function (ch) { parts.push(ch); });
      var dir = new DataView(new ArrayBuffer(46));
      dir.setUint32(0, 0x02014b50, true);
      dir.setUint16(4, 20, true);
      dir.setUint16(6, 20, true);
      dir.setUint16(8, 0x0800, true);
      dir.setUint16(10, method, true);
      dir.setUint16(12, 0, true);
      dir.setUint16(14, 0x21, true);
      dir.setUint32(16, e.crc, true);
      dir.setUint32(20, bodySize, true);
      dir.setUint32(24, e.size, true);
      dir.setUint16(28, e.name.length, true);
      dir.setUint32(42, offset, true);
      central.push(new Uint8Array(dir.buffer), e.name);
      offset += 30 + e.name.length + bodySize;
    });
    var size = central.reduce(function (n, p) { return n + p.length; }, 0);
    var end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, entries.length, true);
    end.setUint16(10, entries.length, true);
    end.setUint32(12, size, true);
    end.setUint32(16, offset, true);
    return new Blob(parts.concat(central, [new Uint8Array(end.buffer)]),
                    {type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"});
  });
}

function xlsxExport(view, seg, st, store) {
  var positions = st.model.visible.slice();
  var rows = positions.map(function (r) { return exportCells(seg, r); });
  var name = exportName(view, seg, st.model, "xlsx");
  toast("Writing " + name + " (" + fmtCount(rows.length) + " " + plural(rows.length, "row", "rows") + ")…");
  var inside = provenanceNote(view, seg, st, {
    name: name, sha256: null, bytes: 0, rows: rows, positions: positions, written: utcNow(),
    shaReason: "a workbook cannot state its own hash; save the provenance note beside it"});
  return zipFiles(workbookFiles(view.label, seg["export"].headers, rows, seg["export"].ts, inside), !!store)
    .then(function (blob) {
      saveBlob(name, blob);
      return blob.arrayBuffer();
    }).then(function (buf) {
      var bytes = new Uint8Array(buf);
      return sha256Hex(bytes).then(function (digest) {
        offerNote(name, provenanceNote(view, seg, st, {
          name: name, sha256: digest, shaReason: "this browser offers no SHA-256 here", bytes: bytes.length,
          rows: rows, positions: positions, written: utcNow()}), rows.length);
        return name;
      });
    });
}

EXPORTERS.xlsx = function (view, seg, st) {
  return xlsxExport(view, seg, st, false).catch(function (e) {
    toast("The workbook could not be written: " + (e && e.message ? e.message : String(e)));
  });
};
API.exportXlsx = function (viewKey, segKey, store) {
  var found = findSegment(viewKey, segKey);
  return xlsxExport(found.view, found.seg, segmentState(found.view, found.seg), !!store);
};
