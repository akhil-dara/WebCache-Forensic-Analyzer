// Reads the island, lays out the page, routes between pages, and draws the
// Case summary. Later files add renderers (grid.js: view; filter.js:
// filterPopup, search; dialog.js: record). Until one is present the page
// says so, rather than drawing nothing.

var DATA = null;
var RENDERERS = {};
var NODES = {navButtons: {}};
var STATE = {page: null, theme: "dark"};

function showFatal(text) {
  var app = document.getElementById("app");
  clear(app);
  app.appendChild(el("p", "noscript", text));
}

// The island is stored packed (html_package.pack_island) and unpacked here,
// once, before anything reads it: every reader sees exactly the dict
// build_island made. "~" + base-62 index: a string in table `s`; "~*" +
// index: a copy of container `x[index]`; "~-" + base-62 count inside a list:
// that many nulls; "~~...": a string that itself starts with "~". Records'
// canonical cells and segments' rows are stored by column; a column's
// attributes equal to the defaults are left out. A key is set with
// defineProperty, so evidence naming a field "__proto__" stays a field.
var PACK_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
var COLUMN_KEYS = ["k", "l", "kind", "num", "field", "badge", "tip", "note", "opt", "w", "copies", "multi", "blank"];
var COLUMN_DEFAULTS = {kind: "text", num: false, field: null, badge: null, tip: null, note: null, opt: false,
  w: null, copies: false, multi: false, blank: null};

function unb62(text, from) {
  var n = 0;
  for (var i = from; i < text.length; i++) n = n * 62 + PACK_DIGITS.indexOf(text.charAt(i));
  return n;
}

function setKey(obj, key, value) {
  if (key === "__proto__") {
    Object.defineProperty(obj, key, {value: value, writable: true, enumerable: true, configurable: true});
  } else {
    obj[key] = value;
  }
}

function deepCopy(v) {
  if (v === null || typeof v !== "object") return v;
  if (Array.isArray(v)) return v.map(deepCopy);
  var out = {};
  Object.keys(v).forEach(function (k) { setKey(out, k, deepCopy(v[k])); });
  return out;
}

function unpackIsland(packed) {
  var strings = packed.s, shared = [];
  function text(v) {
    if (v.charCodeAt(0) !== 126) return v;
    var second = v.charAt(1);
    if (second === "~") return v.slice(1);
    if (second === "*") return deepCopy(shared[unb62(v, 2)]);
    return strings[unb62(v, 1)];
  }
  function dec(v) {
    if (typeof v === "string") return text(v);
    if (v === null || typeof v !== "object") return v;
    var out;
    if (Array.isArray(v)) {
      out = [];
      for (var i = 0; i < v.length; i++) {
        var item = v[i];
        if (typeof item === "string" && item.charCodeAt(0) === 126 && item.charAt(1) === "-") {
          for (var n = unb62(item, 2); n > 0; n--) out.push(null);
        } else {
          out.push(dec(item));
        }
      }
      return out;
    }
    out = {};
    Object.keys(v).forEach(function (k) { setKey(out, text(k), dec(v[k])); });
    return out;
  }
  function byRow(columns, count) {
    var rows = [];
    for (var r = 0; r < count; r++) {
      var row = new Array(columns.length);
      for (var c = 0; c < columns.length; c++) row[c] = columns[c][r];
      rows.push(row);
    }
    return rows;
  }
  function fullColumn(col) {
    var out = {};
    COLUMN_KEYS.forEach(function (k) {
      if (Object.prototype.hasOwnProperty.call(col, k)) out[k] = col[k];
      else out[k] = k === "l" ? out.k : COLUMN_DEFAULTS[k];
    });
    return out;
  }
  packed.x.forEach(function (item) { shared.push(dec(item)); });
  var d = packed.d, island = {};
  Object.keys(d).forEach(function (key) {
    var v = d[key];
    if (key === "records") {
      var noc = new Set(v.noc), columns = v.c.map(dec);
      var cells = byRow(columns, v.r.length - v.noc.length), at = 0;
      island.records = v.r.map(function (rest, i) {
        var record = {};
        if (!noc.has(i)) record.c = cells[at++];
        var more = dec(rest);
        Object.keys(more).forEach(function (k) { setKey(record, k, more[k]); });
        return record;
      });
    } else if (key === "views") {
      island.views = v.map(function (view) {
        var out = {};
        Object.keys(view).forEach(function (k) {
          if (k !== "segments") { out[k] = dec(view[k]); return; }
          out.segments = view.segments.map(function (seg) {
            var one = {};
            Object.keys(seg).forEach(function (name) {
              var item = seg[name];
              if (name === "rows" && item !== null && !Array.isArray(item)) {
                var cols = item.c.map(dec);
                one.rows = byRow(cols, item.n);
              } else if (name === "cols") {
                one.cols = dec(item).map(fullColumn);
              } else {
                one[name] = dec(item);
              }
            });
            return one;
          });
        });
        return out;
      });
    } else if (key === "member_cols") {
      island.member_cols = dec(v).map(fullColumn);
    } else {
      setKey(island, key, dec(v));
    }
  });
  return island;
}

function start() {
  try {
    var stored = JSON.parse(document.getElementById("wc-data").textContent);
    if (stored && stored.pack !== undefined && stored.pack !== 1) {
      showFatal("This report's data is packed in a form this page cannot read (pack " + stored.pack + ").");
      return;
    }
    DATA = stored && stored.pack === 1 ? unpackIsland(stored) : stored;
  } catch (e) {
    showFatal("This report's data could not be read: " + e.message);
    return;
  }
  if (!DATA || DATA.schema !== "webcache-offline-report/1") {
    showFatal("This file's data is not a WebCache offline report (schema: " + (DATA && DATA.schema) + ").");
    return;
  }
  applyTheme(loadSetting("wc-theme", "dark"), false);
  buildLayout();
  var first = (DATA.meta.evidence || [])[0];
  document.title = "WebCache offline report \u2014 " + (first ? baseName(first.path) : "no evidence recorded");
  go("summary");
  window.__wc_ready_ms = Math.round(performance.now());
  window.__wc_ready = true;
}

function applyTheme(name, save) {
  STATE.theme = name === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", STATE.theme);
  if (NODES.theme) NODES.theme.textContent = STATE.theme === "dark" ? "Switch to light" : "Switch to dark";
  if (save) saveSetting("wc-theme", STATE.theme);
}

function viewByKey(key) {
  for (var i = 0; i < DATA.views.length; i++) if (DATA.views[i].key === key) return DATA.views[i];
  return null;
}

function viewRowCount(view) {
  // The app sidebar's own badge, word for word, when the report carries it.
  if (!isBlank(view.badge)) return {text: view.badge, unit: view.unit || ""};
  if (view.key === "timeline") {
    var day = view.segments.filter(function (s) { return s.key === view.initial; })[0];
    if (!day || !day.mem) return null;
    var seen = new Set();
    day.mem.forEach(function (m) { (m || []).forEach(function (i) { seen.add(i); }); });
    return {n: seen.size, unit: "dated records"};
  }
  var n = 0;
  view.segments.forEach(function (s) { if (!s.clock || s.clock === "utc") n += s.rows.length; });
  return {n: n, unit: "rows across this view"};
}

function addNav(parent, key, label, count) {
  var b = el("button", "nav");
  b.appendChild(el("span", null, label));
  if (count) {
    var shown = count.text !== undefined ? count.text : fmtCount(count.n);
    var n = el("span", "n", shown);
    n.title = count.unit ? shown + " " + count.unit : shown;
    b.appendChild(n);
  }
  b.addEventListener("click", function () { go(key); });
  parent.appendChild(b);
  NODES.navButtons[key] = b;
}

function buildLayout() {
  var app = document.getElementById("app");
  clear(app);
  var top = el("header", "topbar");
  top.appendChild(el("span", "title", "WebCache offline report"));
  // The bar names the evidence; every file's full hash (database, logs,
  // checkpoint) is listed behind one button, each with its own copy
  // button, so the bar stays one line. The Case summary lists them too.
  var evidence = DATA.meta.evidence || [];
  var primary = evidence.filter(function (e) { return /\.dat$/i.test(baseName(e.path)); })[0] || evidence[0];
  if (primary) {
    var name = el("span", "fact");
    name.appendChild(document.createTextNode("Evidence "));
    name.appendChild(el("b", null, baseName(primary.path)));
    top.appendChild(name);
  }
  if (evidence.length) {
    var files = el("details", "files");
    files.appendChild(el("summary", null, "SHA-256 · " + evidence.length + " file" + (evidence.length === 1 ? "" : "s")));
    var pop = el("div", "pop");
    pop.appendChild(el("p", "note", "Every evidence file read for this report, with its SHA-256."));
    evidence.forEach(function (e) {
      var row = el("div", "file");
      row.appendChild(el("b", null, baseName(e.path)));
      row.appendChild(el("span", "mono", e.sha256));
      row.appendChild(copyButton(e.sha256, "Copy hash"));
      pop.appendChild(row);
    });
    files.appendChild(pop);
    document.addEventListener("click", function (ev) {
      if (files.open && !files.contains(ev.target)) files.open = false;
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && files.open) files.open = false;
    });
    top.appendChild(files);
  }
  if (!evidence.length) top.appendChild(el("span", "fact", "No evidence hash was recorded for this report."));
  top.appendChild(el("span", "fact", DATA.meta.tool + " " + DATA.meta.tool_version));
  top.appendChild(el("span", "fact", "Generated (UTC) " + DATA.meta.generated_utc));
  var search = el("input");
  search.type = "search";
  search.placeholder = "Search all views";
  search.setAttribute("aria-label", "Search all views");
  search.addEventListener("keydown", function (ev) { if (ev.key === "Enter") go("search", search.value); });
  top.appendChild(search);
  var theme = el("button", null, "");
  theme.addEventListener("click", function () { applyTheme(STATE.theme === "dark" ? "light" : "dark", true); });
  NODES.theme = theme;
  applyTheme(STATE.theme, false);
  top.appendChild(theme);

  var side = el("nav", "side");
  side.setAttribute("aria-label", "Views");
  side.appendChild(el("h3", null, "CASE"));
  addNav(side, "summary", "Case summary", null);
  var section = null;
  DATA.views.forEach(function (v) {
    if (v.section !== section) { section = v.section; side.appendChild(el("h3", null, section)); }
    addNav(side, "view:" + v.key, v.label, viewRowCount(v));
  });
  var main = el("main", "main");
  main.id = "wc-main";
  app.appendChild(top);
  app.appendChild(side);
  app.appendChild(main);
  NODES.main = main;
}

function renderMissing(main) {
  var page = el("div", "page");
  page.appendChild(el("p", "note", "This part of the report is not available in this build of the page."));
  main.appendChild(page);
}

function go(page, arg) {
  closePopover();
  STATE.page = page;
  Object.keys(NODES.navButtons).forEach(function (k) {
    NODES.navButtons[k].classList.toggle("on", k === page);
  });
  var main = NODES.main;
  clear(main);
  if (page === "summary") return renderSummary(main);
  if (page === "search") return (RENDERERS.search || renderMissing)(main, arg || "");
  if (page.indexOf("view:") === 0) {
    var view = viewByKey(page.slice(5));
    if (view) return (RENDERERS.view || renderMissing)(main, view, arg || null);
  }
  renderMissing(main);
}

function kvTable(rows) {
  var t = el("table", "plain");
  rows.forEach(function (r) {
    var tr = el("tr");
    var th = el("th", null, r[0]);
    if (r[2]) th.title = r[2];
    var value = isBlank(r[1]) ? "" : String(r[1]);
    var td = el("td", null, value);
    var tc = el("td");
    if (value) tc.appendChild(copyButton(value));
    tr.appendChild(th); tr.appendChild(td); tr.appendChild(tc);
    t.appendChild(tr);
  });
  return t;
}

function plainTable(headers, rows, cls) {
  var t = el("table", cls || "plain");
  var head = el("tr");
  headers.forEach(function (h) { head.appendChild(el("th", null, h)); });
  t.appendChild(head);
  rows.forEach(function (r) {
    var tr = el("tr");
    r.forEach(function (v) { tr.appendChild(el("td", null, isBlank(v) ? "" : String(v))); });
    t.appendChild(tr);
  });
  return t;
}

function originCounts(s) {
  var live = 0, carved = 0, other = 0;
  s.org.forEach(function (o) {
    var label = s.origins[o];
    if (label === LIVE_CELL) live++;
    else if (label === CARVED_ORIGIN) carved++;
    else other++;
  });
  return [live, carved, other];
}

var COUNT_HEADS = ["View", "Segment", "Rows", "Live records", "Recovered records (carves and stubs)",
                   "Not single records (aggregates, raw rows)"];

function numberCells(t) {
  Array.prototype.forEach.call(t.querySelectorAll("tr"), function (tr, i) {
    if (!i) return;
    for (var c = 2; c < tr.cells.length; c++) tr.cells[c].className = "n";
  });
  return t;
}

function countsTable() {
  // Raw tables fold into one row; a button lists them.
  var holder = el("div", "countswrap"), rows = [], raw = [], rawRows = 0;
  DATA.views.forEach(function (v) {
    v.segments.forEach(function (s) {
      if (v.key === "raw") {
        var c = originCounts(s);
        raw.push([v.label, s.label, fmtCount(s.rows.length), fmtCount(c[0]), fmtCount(c[1]), fmtCount(c[2])]);
        rawRows += s.rows.length;
        return;
      }
      var c = originCounts(s);
      rows.push([v.label, s.label, fmtCount(s.rows.length), fmtCount(c[0]), fmtCount(c[1]), fmtCount(c[2])]);
    });
  });
  if (raw.length) {
    rows.push(["Raw tables", fmtCount(raw.length) + " " + plural(raw.length, "table", "tables"),
               fmtCount(rawRows), "0", "0", fmtCount(rawRows)]);
  }
  holder.appendChild(numberCells(plainTable(COUNT_HEADS, rows, "counts")));
  if (raw.length) {
    var list = numberCells(plainTable(COUNT_HEADS, raw, "rawcounts"));
    list.hidden = true;
    var toggle = el("button", null, "Show each raw table (" + fmtCount(raw.length) + ")");
    toggle.id = "wc-raw-counts";
    toggle.addEventListener("click", function () {
      list.hidden = !list.hidden;
      toggle.textContent = (list.hidden ? "Show" : "Hide") + " each raw table (" + fmtCount(raw.length) + ")";
    });
    holder.appendChild(toggle);
    holder.appendChild(list);
  }
  return holder;
}

function renderSummary(main) {
  var page = el("div", "page");
  page.appendChild(el("h1", null, "Case summary"));
  page.appendChild(el("p", "note", "Generated (UTC) " + DATA.meta.generated_utc + " by " + DATA.meta.tool + " " +
    DATA.meta.tool_version + ". Every record below is in this one file; nothing is fetched and no link is followed."));
  page.appendChild(kvTable(DATA.summary));
  page.appendChild(el("h2", null, "Records in this report"));
  page.appendChild(countsTable());
  page.appendChild(el("h2", null, "Evidence"));
  var evidence = DATA.meta.evidence || [];
  if (!evidence.length) page.appendChild(el("p", "note", "No evidence hash was recorded for this report."));
  evidence.forEach(function (e) {
    page.appendChild(kvTable([["File", e.path], ["SHA-256", e.sha256], ["Bytes", fmtCount(e.bytes || 0)]]));
  });
  var integrity = DATA.integrity || {};
  if ((integrity.hashes || []).length) {
    page.appendChild(el("h2", null, "Source hashes"));
    page.appendChild(plainTable(["File", "Role", "SHA-256"], integrity.hashes));
  }
  if ((integrity.source || []).length) {
    page.appendChild(el("h2", null, "Source integrity"));
    page.appendChild(kvTable(integrity.source));
  }
  if ((integrity.clock || []).length) {
    page.appendChild(el("h2", null, "Clock"));
    page.appendChild(kvTable(integrity.clock));
  }
  if ((integrity.log || []).length) {
    page.appendChild(el("h2", null, "Parse decisions"));
    var list = el("ol");
    integrity.log.forEach(function (r) { list.appendChild(el("li", r[1] ? "flagged" : "", r[0])); });
    page.appendChild(list);
  }
  var c = DATA.meta["case"] || {};
  var caseRows = Object.keys(c).filter(function (k) { return !isBlank(c[k]); }).map(function (k) { return [k, c[k]]; });
  if (caseRows.length) { page.appendChild(el("h2", null, "Case")); page.appendChild(kvTable(caseRows)); }
  var opened = DATA.meta.opened || [];
  if (opened.length) {
    page.appendChild(el("h2", null, "Evidence opened"));
    page.appendChild(plainTable(["Opened (UTC)", "File", "SHA-256", "Bytes"],
      opened.map(function (r) { return [r[0], r[1], r[2], fmtCount(r[3] || 0)]; })));
  }
  if ((DATA.scope || []).length) {
    page.appendChild(el("h2", null, "What this report can and cannot show"));
    DATA.scope.forEach(function (s) { page.appendChild(el("h3", null, s[0])); page.appendChild(el("p", null, s[1])); });
  }
  if ((DATA.basis || []).length) {
    page.appendChild(el("h2", null, "Evidentiary basis badges"));
    page.appendChild(plainTable(["Badge", "Basis", "Meaning"], DATA.basis));
  }
  page.appendChild(el("h2", null, "Verifying this file"));
  page.appendChild(el("p", null, "This page cannot state its own hash. Compute the SHA-256 of this .html file and compare it " +
    "with the .sha256 file written beside it, or with its entry in the bundle's 00_MANIFEST.json. A different hash means " +
    "the file is not the one this tool wrote."));
  main.appendChild(page);
}

API.data = function () { return DATA; };
API.go = function (page, arg) { go(page, arg); };
