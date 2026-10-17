// What the page writes: the rows shown, in the order shown, in the
// segment's whole export layout -- view columns, then Origin/RecordSource,
// then the canonical block from each row's record -- exactly as
// export_formats.write_view_csv writes it, byte for byte. The provenance
// note follows write_view_provenance's sections and wording, then says
// which report it came from.

var FORMULA_LEAD = /^[=+\-@]/;
var LAST_NOTE = null;

function exportCells(seg, r) {
  var out = seg.rows[r].slice(), canon = seg["export"].canon;
  if (!canon.length) return out;
  var index = seg.rec[r], rec = index >= 0 ? DATA.records[index] : null;
  for (var i = 0; i < canon.length; i++) {
    var field = canon[i][0], key = canon[i][1], v = null;
    if (rec) {
      if (field !== null) v = rec.c ? rec.c[field] : null;
      else if (rec.own && Object.prototype.hasOwnProperty.call(rec.own, key)) v = rec.own[key];
    }
    out.push(v);
  }
  return out;
}

function csvField(v) {
  var s = pyText(v);
  return /[",\r\n]/.test(s) ? "\"" + s.replace(/"/g, "\"\"") + "\"" : s;
}

function csvLine(cells) {
  // Python's csv writer quotes a row whose only field is empty.
  if (cells.length === 1 && pyText(cells[0]) === "") return "\"\"";
  return cells.map(csvField).join(",");
}

function csvText(headers, rows) {
  var out = [csvLine(headers)];
  rows.forEach(function (cells) { out.push(csvLine(cells)); });
  return "﻿" + out.join("\r\n") + "\r\n";
}

function exportName(view, seg, model, ext) {
  var parts = ["webcache", view.key];
  if (view.segments.length > 1) parts.push(seg.key);
  if (model.visible.length !== model.n) parts.push("filtered");
  return safeFileName(parts.join("_")) + "." + ext;
}

function formulaCount(rows) {
  // Text only: a negative NUMBER legitimately begins with "-".
  var n = 0;
  rows.forEach(function (cells) {
    cells.forEach(function (v) {
      if (typeof v === "string" && v.length && v.charCodeAt(0) > 3 && FORMULA_LEAD.test(v)) n++;
    });
  });
  return n;
}

function sha256Hex(bytes) {
  if (!(window.crypto && window.crypto.subtle)) return Promise.resolve(null);
  return window.crypto.subtle.digest("SHA-256", bytes).then(function (buf) {
    return Array.prototype.map.call(new Uint8Array(buf), function (b) {
      return (b < 16 ? "0" : "") + b.toString(16);
    }).join("");
  }, function () { return null; });
}

function utcNow() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function columnArithmetic(ex, total) {
  // export_formats.column_arithmetic, word for word.
  var line = fmtCount(total) + " = " + fmtCount(ex.view_column_count) + " view columns + " +
    fmtCount(ex.canonical_entry_count) + " canonical fields (of " + DATA.fields.length +
    " in the schema; " + fmtCount(ex.canonical_shown_count) + " already shown as view columns)";
  if (ex.canonical_own_count) line += " + " + fmtCount(ex.canonical_own_count) + " record fields";
  return line;
}

function chipText(m, seg) {
  // record_filter.chip_text: everything in force, in the app's order (search,
  // conditions, chips, values), joined by " + ".
  var parts = [], said = m.describe();
  var nText = m.text ? 1 : 0, nCond = Object.keys(m.conditions).length, nVal = Object.keys(m.values).length;
  if (nText) parts.push("search \"" + m.rawText + "\"");
  Object.keys(m.conditions).forEach(function (k) {
    parts.push(m.cols[+k].l + ": " + m.conditions[k].describe(m.cols[+k]));
  });
  Object.keys(m.chips).forEach(function (k) {
    var q = seg.quick[+k];
    parts.push(q.sentence || q.label);
  });
  said.slice(nText + nCond, nText + nCond + nVal).forEach(function (e) { parts.push(e.text); });
  return parts.join(" + ");
}

function provenanceNote(view, seg, st, info) {
  // export_formats.write_view_provenance, section by section.
  var ex = seg["export"], m = st.model, lines = [];
  function add(s) { lines.push(s); }
  add("WebCache Forensic Analyzer " + DATA.meta.tool_version + " — export provenance");
  add("Written (UTC): " + info.written);
  add("");
  add("FILE");
  add("  Name    : " + info.name);
  if (info.sha256) {
    add("  SHA-256 : " + info.sha256);
    add("  Bytes   : " + fmtCount(info.bytes));
  } else {
    add("  SHA-256 : not computed (" + info.shaReason + ")");
  }
  add("");
  add("EVIDENCE");
  var evidence = DATA.meta.evidence || [];
  evidence.forEach(function (e) { add("  " + e.path); add("    SHA-256 " + e.sha256); });
  if (!evidence.length) add("  (no evidence set recorded for this export)");
  add("");
  add("VIEW");
  add("  Name             : " + (view.segments.length > 1 ? view.label + " — " + seg.label : view.label));
  add("  Columns in file  : " + ex.headers.join(", "));
  add("  View columns     : " + fmtCount(ex.view_column_count));
  add("  Column total     : " + columnArithmetic(ex, ex.headers.length));
  var entry = ex.canonical_entry_count, own = ex.canonical_own_count;
  if (entry) {
    add("  Canonical fields : " + fmtCount(entry) + " (the full ENTRY_FIELDS export schema, in schema order, minus the " +
      fmtCount(ex.canonical_shown_count) + " fields this view already shows; the same fixed column set every engine " +
      "export writes. A blank cell means that record does not carry the field. Raw FILETIMEs, ids and carve " +
      "provenance included.)");
  }
  if (own) {
    add("  Record fields    : " + fmtCount(own) + " (every field these records' own source rows carry, in first-seen " +
      "order, minus any this view already shows as that same field. Cookies, HSTS pins, certificates and containers " +
      "are not URL-cache entries, so the ENTRY_FIELDS schema does not apply to them. A blank cell means that record " +
      "does not carry the field. Raw FILETIMEs and ids included.)");
  }
  if (!entry && !own) {
    add(ex.rows_are_aggregates === false
      ? "  Canonical fields : none (the rows in this view are not single parsed records, so no per-record fields apply)"
      : "  Canonical fields : none (the rows in this view are aggregates, not single records, so no per-record fields apply)");
  }
  // Hidden by hand or folded away as identical/empty (scope_from_view reads
  // isColumnHidden, which covers both in the app).
  var hidden = seg.cols.filter(function (c, i) { return !st.shown[i] || (st.auto && st.auto[i]); })
    .map(function (c) { return c.l; });
  add("  Hidden on screen but PRESENT in this file: " + (hidden.length ? hidden.join(", ") : "none"));
  add("  Rows in file       : " + fmtCount(info.rows.length));
  add("  Rows in view     : " + fmtCount(info.rows.length));
  add("  Rows in record set: " + fmtCount(m.n));
  add("");
  add("SCOPE");
  if (info.rows.length !== m.n) {
    add("  THIS IS A FILTERED SUBSET, NOT THE WHOLE VIEW.");
    if (m.rawText) add("  Search text      : " + m.rawText);
    Object.keys(m.conditions).forEach(function (k) {
      add("  Column condition : " + m.cols[+k].l + " " + m.conditions[k].describe(m.cols[+k]));
    });
    Object.keys(m.values).forEach(function (k) {
      var ids = m.values[k];
      var labels = m.valueCounts(+k).filter(function (x) { return ids.has(x.id); })
        .map(function (x) { return x.label; }).sort();
      add("  Value filter     : " + m.cols[+k].l + " = " + labels.join(", "));
    });
    var chips = chipText(m, seg);
    if (chips) add("  As shown on screen: " + chips);
    add("  Rows excluded    : " + fmtCount(Math.max(0, m.n - info.rows.length)));
    add("  Re-run with filters cleared for the whole view.");
  } else {
    add("  No filter was in force. This file is the whole view.");
  }
  add("");
  add("ORIGIN");
  var live = 0, carved = 0;
  info.positions.forEach(function (r) {
    var origin = seg.origins[seg.org[r]];
    if (origin === LIVE_CELL) live++;
    else if (origin === CARVED_ORIGIN) carved++;
  });
  add("  " + fmtCount(live) + " live, " + fmtCount(carved) + " carved in this file.");
  add("  Recovery scan run for this exhibit: " + (DATA.meta.recovery_scan_run ? "yes"
    : "NO — deleted records have not been carved, so nothing here can be read as covering them"));
  add("");
  add("TIMESTAMPS");
  add("  UTC timestamps are written as YYYY-MM-DD HH:MM:SS[.ffffff] (a date cell in XLSX); the RFC 3339 form of " +
    "each is in its *_rfc column. Any column labelled LOCAL is the examined machine's own clock as the database " +
    "stored it, not a conversion.");
  add("");
  add("TEXT ENCODING");
  add("  Binary values are written as uppercase hex. NUL, other control characters, lone surrogates and the " +
    "noncharacters U+FFFE/U+FFFF cannot be stored in CSV or XLSX, so each is written as a visible escape " +
    "(\\x00, \\x07, \\uD800, \\uFFFE) and nothing is dropped; " +
    "a literal backslash in the evidence is not escaped. NaN and infinity are written as the text nan, inf and -inf.");
  var caution = formulaCount(info.rows);
  if (caution) {
    add("");
    add("CAUTION");
    add("  " + fmtCount(caution) + " value(s) in this file begin with =, +, - or @ and Excel will evaluate them as " +
      "formulas. They were not altered: changing a stored value to make a spreadsheet behave would be evidence tampering.");
  }
  add("");
  add("SOURCE");
  add("  Exported from the offline report generated (UTC) " + DATA.meta.generated_utc + " by " + DATA.meta.tool + " " +
    DATA.meta.tool_version + ". That report's own SHA-256 is in the .sha256 file beside it or in its bundle manifest.");
  return lines.join("\n") + "\n";
}

function offerNote(name, note, count) {
  LAST_NOTE = {name: name + ".provenance.txt", text: note};
  var save = el("button", null, "Save provenance note");
  save.addEventListener("click", function () {
    saveBlob(LAST_NOTE.name, new Blob(["﻿" + LAST_NOTE.text], {type: "text/plain;charset=utf-8"}));
  });
  toast("Wrote " + name + " (" + fmtCount(count) + " " + plural(count, "row", "rows") +
    "). Its provenance note states the filters in force:", save);
}

function csvExport(view, seg, st) {
  var positions = st.model.visible.slice();
  var rows = positions.map(function (r) { return exportCells(seg, r); });
  var bytes = new TextEncoder().encode(csvText(seg["export"].headers, rows));
  var name = exportName(view, seg, st.model, "csv");
  saveBlob(name, new Blob([bytes], {type: "text/csv;charset=utf-8"}));
  return sha256Hex(bytes).then(function (digest) {
    offerNote(name, provenanceNote(view, seg, st, {
      name: name, sha256: digest, shaReason: "this browser offers no SHA-256 here", bytes: bytes.length,
      rows: rows, positions: positions, written: utcNow()}), rows.length);
    return name;
  });
}

EXPORTERS.csv = csvExport;
API.exportCsv = function (viewKey, segKey) {
  var found = findSegment(viewKey, segKey);
  return csvExport(found.view, found.seg, segmentState(found.view, found.seg));
};
