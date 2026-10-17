// One view on screen: header, segment switcher, quick chips, filter box,
// count line, and the virtualised grid. Only the rows in view, plus
// OVERSCAN either side, are ever in the DOM. Row heights are measured as
// rows are drawn (a Fenwick tree keeps their running total), so a wrapped
// row takes the height it needs and nothing is cut.

var OVERSCAN = 20;
var DEBOUNCE_MS = 180;              // record_filter.DEBOUNCE_MS
var LIVE_FILTER_MAX_ROWS = 20000;   // above this, the box waits for a pause
var SEGSTATE = {};
var CURRENT = null;
var EXPORTERS = {};
var WRAP = loadSetting("wc-wrap", "on") !== "off";
var MEASURE = null;
// records_table's leading origin column: words on every row.
var ORIGIN_HEADING = "Origin";
var ORIGIN_TIPS = {
  "Live": "A live record, read from the database's own tables.",
  "Carved": "Recovered from unallocated space or the transaction log -- not a live record.",
  "Mixed": "An aggregate: some members are live, some recovered.",
  "Recovered only": "An aggregate: every member was recovered (carved).",
  "\u2014": "Neither a record nor a population of records."
};
var ORIGIN_TINTED = {"Carved": true, "Recovered only": true};

function originWord(seg, r) {
  var o = seg.org[r];
  if (seg.ol) return seg.ol[o];
  var cell = seg.origins[o];
  return cell === CARVED_ORIGIN ? "Carved" : cell === "\u2014" ? cell : "Live";
}

function textWidth(text, weight) {
  if (!MEASURE) MEASURE = document.createElement("canvas").getContext("2d");
  MEASURE.font = (weight || "400") + " 13px " + getComputedStyle(document.body).fontFamily;
  return MEASURE.measureText(text).width;
}

function originWidth(seg) {
  // As wide as the widest word this segment can show, and its heading.
  var words = seg.ol && seg.ol.length ? seg.ol : ["Live", "Carved"];
  // The heading carries the Origin funnel beside it when filtering exists.
  var widest = textWidth(ORIGIN_HEADING, "600")
    + (RENDERERS.originPopup ? textWidth("▽", "400") + 18 : 0);
  words.forEach(function (w) { widest = Math.max(widest, textWidth(w, "600")); });
  return Math.ceil(widest) + 22;
}

function Fenwick(values) {
  var n = values.length;
  this.n = n;
  this.v = new Float64Array(values);
  this.t = new Float64Array(n + 1);
  for (var i = 1; i <= n; i++) {
    this.t[i] += values[i - 1];
    var j = i + (i & -i);
    if (j <= n) this.t[j] += this.t[i];
  }
}
Fenwick.prototype.prefix = function (i) {
  var s = 0;
  for (; i > 0; i -= i & -i) s += this.t[i];
  return s;
};
Fenwick.prototype.total = function () { return this.prefix(this.n); };
Fenwick.prototype.set = function (i, value) {
  var d = value - this.v[i];
  if (!d) return;
  this.v[i] = value;
  for (var k = i + 1; k <= this.n; k += k & -k) this.t[k] += d;
};
Fenwick.prototype.find = function (y) {
  // The index of the row containing offset y, clamped to the last row.
  var pos = 0, step = 1;
  while (step * 2 <= this.n) step *= 2;
  for (; step > 0; step >>= 1) {
    if (pos + step <= this.n && this.t[pos + step] <= y) { pos += step; y -= this.t[pos]; }
  }
  return Math.min(pos, Math.max(0, this.n - 1));
};

function headingMinWidth(col) {
  // Never squeeze a column below its own heading's longest word.
  var widest = 0;
  String(col.l).split(/\s+/).forEach(function (w) { widest = Math.max(widest, textWidth(w, "600")); });
  return Math.ceil(widest) + 40 + (col.badge ? 34 : 0);
}

// records_view.CHIP_VALUE_MAX: a longer identical value is named, not shown.
var CHIP_VALUE_MAX = 60;

function copiesNote(seg, model) {
  // history._update_count: hiding copies changes what is ON SCREEN,
  // never what is counted or exported -- said beside the count.
  var quick = seg.quick || [], on = false, i;
  for (i = 0; i < quick.length; i++) {
    if (quick[i].label === "Hide duplicate copies" && model.chips[i]) on = true;
  }
  if (!on) return "";
  var c = model.colIndex.Copies, values = c !== undefined ? null : (seg.qv && seg.qv.Copies);
  var later = 0;
  for (var r = 0; r < seg.rows.length; r++) {
    var v = c !== undefined ? seg.rows[r][c] : (values ? values[r] : null);
    if (typeof v === "string" && v.indexOf("copy ") === 0) later++;
  }
  if (!later) return "";
  return " — " + fmtCount(later) + " duplicate cop" + (later === 1 ? "y" : "ies") +
    " hidden (left out of Export view; kept in the full case exports)";
}

function twinsNote(model) {
  // history._update_count: exactly the rows "One row per visit" removed.
  var n = model.twinsHidden || 0;
  if (!n) return "";
  return " — " + fmtCount(n) + " MSHist row" + (n === 1 ? "" : "s") +
    " hidden — each is the same visit as a History row shown (left out of Export view; kept in the full case exports)";
}

function identicalColumns(seg, st) {
  // content_header.constant_columns / blank_columns over the rows ON
  // SCREEN: one identical non-blank value in every row, or nothing at all.
  // Fewer than two rows are never "identical in all".
  var vis = st.model.visible, rows = seg.rows, found = [], blank = [];
  if (vis.length < 2) return {found: found, blank: blank};
  for (var c = 0; c < seg.cols.length; c++) {
    var first = rows[vis[0]][c], id = valueId(first), same = true;
    for (var p = 1; same && p < vis.length; p++) same = valueId(rows[vis[p]][c]) === id;
    if (!same) continue;
    if (isBlank(first)) blank.push(c); else found.push(c);
  }
  return {found: found, blank: blank};
}

function identicalLine(seg, st, cols) {
  // records_view._update_constant_chip, word for word. The chip names
  // only non-optional empty columns; every empty column still folds away.
  var named = cols.blank.filter(function (c) { return !seg.cols[c].opt; });
  if (!cols.found.length && !named.length) return "";
  // A filtered column stays on screen: named as shown, never counted hidden.
  var hiding = st.hideIdentical && Object.keys(st.auto).length > 0;
  function kept(c) { return hiding && !st.auto[c]; }
  function mark(c) { return kept(c) ? " (filtered, shown)" : ""; }
  var parts = cols.found.map(function (c) {
    var col = seg.cols[c], text = displayText(seg.rows[st.model.visible[0]][c], col) || blankLabel(col);
    return (text.length <= CHIP_VALUE_MAX ? col.l + ": " + text : col.l + " (the same text; hover to read)") + mark(c);
  });
  if (named.length) parts.push("empty in every row: " + named.map(function (c) { return seg.cols[c].l + mark(c); }).join(", "));
  var count = fmtCount(st.model.visible.length), lead;
  if (hiding) {
    var nFound = cols.found.filter(function (c) { return !kept(c); }).length;
    var nBlank = named.filter(function (c) { return !kept(c); }).length;
    var total = nFound + nBlank;
    var kinds = (nFound ? [nFound + " identical"] : []).concat(nBlank ? [nBlank + " empty in every row"] : []);
    lead = total + " column" + (total === 1 ? "" : "s") + " hidden: " + kinds.join(", ") + " — in all " + count + ": ";
  } else {
    lead = "Identical in all " + count + ": ";
  }
  return lead + parts.join("; ");
}

function segmentState(view, seg) {
  var id = view.key + "/" + seg.key;
  if (!SEGSTATE[id]) {
    SEGSTATE[id] = {
      model: new SegmentModel(seg),
      widths: seg.cols.map(function (c) { return c.w || 140; }),
      shown: seg.cols.map(function (c) { return !c.opt; }),
      // "Hide identical columns", on by default as in the app; `auto` is
      // the set it hides on the rows now on screen (index -> true).
      hideIdentical: true, auto: {},
      sel: -1, scroll: 0, fitted: false
    };
  }
  return SEGSTATE[id];
}

function viewClocks(view) {
  var seen = [];
  view.segments.forEach(function (s) { if (s.clock && seen.indexOf(s.clock) < 0) seen.push(s.clock); });
  return seen;
}

function pickSegment(view, key, clock) {
  var segs = view.segments, i;
  if (key) for (i = 0; i < segs.length; i++) if (segs[i].key === key) return segs[i];
  if (view.initial) for (i = 0; i < segs.length; i++) {
    if (segs[i].key === view.initial && (!clock || segs[i].clock === clock)) return segs[i];
  }
  // A list (Raw tables) with nothing chosen opens the first table that
  // holds rows, not an empty one.
  if (view.picker === "list") for (i = 0; i < segs.length; i++) if (segs[i].rows.length) return segs[i];
  for (i = 0; i < segs.length; i++) if (!clock || segs[i].clock === clock) return segs[i];
  return segs[0];
}

function clockLabel(clock) {
  if (clock === "utc") return "UTC";
  var zone = DATA.meta.zone || {};
  return "Local" + (zone.label ? " (" + zone.label + ")" : "");
}

function segmentBar(main, view, seg, clocks) {
  var holder = el("div"), bar = el("div", "bar");
  if (clocks.length > 1) {
    // The clock is its own labelled choice, ahead of the grains
    // 
    var clockBar = el("div", "bar clock");
    clockBar.appendChild(el("span", "label", "Clock:"));
    clocks.forEach(function (clock) {
      var b = el("button", clock === seg.clock ? "on" : "", clockLabel(clock));
      b.addEventListener("click", function () {
        if (clock === seg.clock) return;
        renderView(main, view, {segment: seg.key.replace(/_(utc|local)$/, "_" + clock), clock: clock});
      });
      clockBar.appendChild(b);
    });
    holder.appendChild(clockBar);
  }
  holder.appendChild(bar);
  var segs = view.segments.filter(function (s) { return !s.clock || s.clock === seg.clock; });
  if (segs.length < 2) return holder;
  if (view.picker === "list") {
    var select = el("select");
    select.setAttribute("aria-label", view.label + ": choose a table");
    var groups = {}, order = [];
    segs.forEach(function (s) {
      var g = s.group || "Tables";
      if (!groups[g]) { groups[g] = el("optgroup"); groups[g].label = g; order.push(g); }
      var o = el("option", null, s.label + " (" + fmtCount(s.rows.length) + ")");
      o.value = s.key;
      if (s.key === seg.key) o.selected = true;
      groups[g].appendChild(o);
    });
    order.forEach(function (g) { select.appendChild(groups[g]); });
    select.addEventListener("change", function () { renderView(main, view, {segment: select.value}); });
    bar.appendChild(select);
  } else {
    segs.forEach(function (s) {
      var b = el("button", s.key === seg.key ? "on" : "", s.label + " (" + fmtCount(s.rows.length) + ")");
      b.addEventListener("click", function () { renderView(main, view, {segment: s.key}); });
      bar.appendChild(b);
    });
  }
  return holder;
}

function chipBar(seg, st, changed) {
  if (!seg.quick || !seg.quick.length) return null;
  var bar = el("div", "bar");
  seg.quick.forEach(function (q, i) {
    var b = el("button", "chip", q.label);
    b.dataset.chip = String(i);
    if (q.skipped) {
      b.disabled = true;
      b.textContent = q.label + " (not reproduced)";
      b.title = q.skipped;
    } else if (!st.model.chipUsable(i)) {
      b.disabled = true;
      b.title = "This chip filters a column this segment does not carry.";
    } else {
      if (q.counted) {
        // records_view._show_chip_counts: over the whole segment, with
        // the chip's own test, so the number never moves when a
        // neighbouring chip is ticked.
        var kept = st.model.chipCount(i), total = seg.rows.length;
        b.textContent = q.label + " · " + fmtCount(kept);
        b.title = fmtCount(kept) + " of " + fmtCount(total) + " " +
          (total === 1 ? "record" : "records") +
          " in this list. Ticked, it applies on top of the other filters.";
        if (!kept && q.none_note) b.title += " " + q.none_note;
      }
      b.addEventListener("click", function () { st.model.toggleChip(i); changed(); });
    }
    bar.appendChild(b);
  });
  chipStates(bar, st);
  return bar;
}

function chipStates(bar, st) {
  Array.prototype.forEach.call(bar.querySelectorAll("button.chip"), function (b) {
    var on = !!st.model.chips[+b.dataset.chip];
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function columnsPopover(anchor, seg, st, changed) {
  openPopover(anchor, function (node) {
    node.appendChild(el("strong", null, "Columns"));
    node.appendChild(el("div", "note", "Hiding a column is a view preference only: every export still writes it."));
    seg.cols.forEach(function (col, c) {
      var label = el("label");
      var box = el("input");
      box.type = "checkbox";
      box.checked = st.shown[c];
      box.addEventListener("change", function () { st.shown[c] = box.checked; changed(); });
      label.appendChild(box);
      label.appendChild(el("span", null, col.l + (col.opt ? " (optional)" : "")));
      node.appendChild(label);
    });
  });
}

function exportPopover(anchor, view, seg, st) {
  openPopover(anchor, function (node, close) {
    node.appendChild(el("strong", null, "Export the " + fmtCount(st.model.visible.length) + " rows shown"));
    node.appendChild(el("div", "note", "Every column of this view is written, hidden ones included, then the full " +
      "canonical record fields: the same layout as the app's own view export."));
    [["csv", "CSV"], ["xlsx", "Excel workbook (.xlsx)"]].forEach(function (pair) {
      var b = el("button", null, pair[1]);
      if (!EXPORTERS[pair[0]]) { b.disabled = true; b.title = "Not available in this build of the report."; }
      else b.addEventListener("click", function () { close(); EXPORTERS[pair[0]](view, seg, st); });
      node.appendChild(b);
    });
  });
}

function renderView(main, view, opts) {
  opts = opts || {};
  var clocks = viewClocks(view);
  var clock = opts.clock || (clocks.length ? clocks[0] : "");
  if (opts.segment && !opts.clock) clock = pickSegment(view, opts.segment, null).clock || clock;
  var seg = pickSegment(view, opts.segment, clock);
  var st = segmentState(view, seg);
  if (typeof opts.text === "string") st.model.setText(opts.text);
  clear(main);
  var head = el("div", "vhead");
  head.appendChild(el("h1", null, view.label));
  var caveat = seg.caveat || view.caption;
  if (caveat) head.appendChild(el("div", "caveat", caveat));
  if (seg.subtitle) head.appendChild(el("div", "note", seg.subtitle));
  head.appendChild(segmentBar(main, view, seg, clocks));
  var chips = chipBar(seg, st, function () { CURRENT.refresh(); });
  if (chips) head.appendChild(chips);
  var tools = el("div", "bar");
  var box = el("input", "filter");
  box.type = "search";
  box.id = "wc-filter";
  box.placeholder = "Filter this view \u2014 every column, as shown";
  box.setAttribute("aria-label", "Filter this view");
  box.value = st.model.rawText;
  var clearButton = el("button", null, "Clear filters");
  var columnsButton = el("button", null, "Columns \u25be");
  var wrapButton = el("button", WRAP ? "on" : "", "Wrap");
  wrapButton.title = "Wrap long values: at most " + LINE_CAP + " lines, then a marker that opens the whole value.";
  var identButton = el("button", st.hideIdentical ? "on" : "", "Hide identical columns");
  identButton.id = "wc-hide-identical";
  identButton.title = "Hide every column that holds one value, or nothing, in every row on screen. " +
    "Exports still write them.";
  var exportButton = el("button", null, "Export \u25be");
  [box, clearButton, columnsButton, wrapButton, identButton, exportButton].forEach(function (n) { tools.appendChild(n); });
  head.appendChild(tools);
  var count = el("div", "count");
  count.id = "wc-count";
  var sentence = el("div", "sentence");
  sentence.id = "wc-sentence";
  var identical = el("div", "note");
  identical.id = "wc-identical";
  head.appendChild(count);
  head.appendChild(identical);
  head.appendChild(sentence);
  main.appendChild(head);
  var wrap = el("div", "gridwrap");
  wrap.id = "wc-grid";
  wrap.tabIndex = 0;
  wrap.setAttribute("aria-label", seg.label + " rows");
  main.appendChild(wrap);

  function foldIdentical() {
    // Recomputed on every refresh, over the rows on screen.
    var cols = identicalColumns(seg, st);
    st.auto = {};
    // A column with a filter on it never folds away (the app's rule too).
    if (st.hideIdentical) cols.found.concat(cols.blank).forEach(function (c) {
      if (!st.model.hasFilterOn(c)) st.auto[c] = true;
    });
    identical.textContent = identicalLine(seg, st, cols);
    identical.hidden = !identical.textContent;
  }
  foldIdentical();
  var grid = new Grid(wrap, view, seg, st);
  CURRENT = {view: view, seg: seg, state: st, clock: seg.clock, grid: grid, main: main};

  function updateCount() {
    var m = st.model, shown = m.visible.length, noun = seg.noun || "records";
    var text = shown === m.n ? fmtCount(m.n) + " " + noun
                             : fmtCount(shown) + " of " + fmtCount(m.n) + " " + noun;
    count.textContent = text + (seg.note ? " \u2014 " + seg.note : "") + copiesNote(seg, m) + twinsNote(m);
    clear(sentence);
    m.describe().forEach(function (item) {
      var part = el("span", null, item.text);
      var x = el("button", null, "\u2715");
      x.title = "Remove this filter";
      x.addEventListener("click", function () {
        item.clear();
        if (item.isText) box.value = "";
        CURRENT.refresh();
      });
      part.appendChild(x);
      sentence.appendChild(part);
    });
  }
  CURRENT.refresh = function () {
    if (chips) chipStates(chips, st);
    st.sel = -1;
    foldIdentical();
    grid.rebuild();
    updateCount();
  };
  identButton.addEventListener("click", function () {
    st.hideIdentical = !st.hideIdentical;
    identButton.classList.toggle("on", st.hideIdentical);
    CURRENT.refresh();
  });

  var timer = null;
  box.addEventListener("input", function () {
    if (timer) clearTimeout(timer);
    var apply = function () { st.model.setText(box.value); CURRENT.refresh(); };
    if (st.model.n > LIVE_FILTER_MAX_ROWS) timer = setTimeout(apply, DEBOUNCE_MS); else apply();
  });
  box.addEventListener("keydown", function (ev) {
    if (ev.key === "ArrowDown") { ev.preventDefault(); wrap.focus(); grid.select(0); }
  });
  clearButton.addEventListener("click", function () { st.model.clearAll(); box.value = ""; CURRENT.refresh(); });
  columnsButton.addEventListener("click", function () { columnsPopover(columnsButton, seg, st, function () { grid.rebuild(); }); });
  wrapButton.addEventListener("click", function () {
    WRAP = !WRAP;
    saveSetting("wc-wrap", WRAP ? "on" : "off");
    wrapButton.classList.toggle("on", WRAP);
    grid.rebuild();
  });
  exportButton.addEventListener("click", function () { exportPopover(exportButton, view, seg, st); });
  updateCount();
}
RENDERERS.view = renderView;

function rowOf(node) {
  while (node && node.tagName !== "TR") node = node.parentNode;
  return node && node.dataset && node.dataset.pos !== undefined ? node : null;
}

function Grid(wrap, view, seg, st) {
  this.wrap = wrap;
  this.view = view;
  this.seg = seg;
  this.st = st;
  this.model = st.model;
  this.lh = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--lh")) || 18;
  var self = this, pending = false;
  wrap.addEventListener("scroll", function () {
    st.scroll = wrap.scrollTop;
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; self.render(); });
  });
  wrap.addEventListener("keydown", function (ev) { self.onKey(ev); });
  this.rebuild();
  wrap.scrollTop = st.scroll || 0;
  this.dirty = true;
  this.render();
}

Grid.prototype.rebuild = function () {
  var self = this, seg = this.seg, st = this.st;
  clear(this.wrap);
  this.table = null;
  this.cols = [];
  for (var c = 0; c < seg.cols.length; c++) if (st.shown[c] && !st.auto[c]) this.cols.push(c);
  if (!seg.rows.length) {
    this.wrap.appendChild(el("div", "empty", seg.empty || "No records in this exhibit."));
    this.count = 0;
    return;
  }
  if (!st.fitted) {
    seg.cols.forEach(function (col, i) { st.widths[i] = Math.max(st.widths[i], headingMinWidth(col)); });
    st.fitted = true;
  }
  var table = el("table", "grid"), colgroup = el("colgroup"), thead = el("thead"), head = el("tr");
  this.colEls = [];
  this.originW = originWidth(seg);
  var oc = el("col");
  oc.style.width = this.originW + "px";
  colgroup.appendChild(oc);
  var corner = el("th", "origin", ORIGIN_HEADING);
  corner.scope = "col";
  corner.title = ORIGIN_HEADING + " \u2014 " + Object.keys(ORIGIN_TIPS).filter(function (w) {
    return !seg.ol || seg.ol.indexOf(w) >= 0;
  }).map(function (w) { return w + ": " + ORIGIN_TIPS[w]; }).join("  ");
  if (RENDERERS.originPopup) {
    // The same funnel every column carries: records_table's Origin heading.
    // Its own class, so a column funnel is still "the Nth .funnel"; the
    // glyph is drawn by CSS, so the heading's text stays "Origin".
    var ofunnel = el("button", "ofunnel" + (this.model.origins ? " on" : ""));
    ofunnel.title = "Filter " + ORIGIN_HEADING;
    ofunnel.setAttribute("aria-label", "Filter " + ORIGIN_HEADING);
    ofunnel.addEventListener("click", function (ev) { ev.stopPropagation(); RENDERERS.originPopup(ofunnel, self); });
    corner.appendChild(ofunnel);
  }
  head.appendChild(corner);
  this.cols.forEach(function (c, i) {
    var ce = el("col");
    ce.style.width = st.widths[c] + "px";
    colgroup.appendChild(ce);
    self.colEls.push(ce);
    head.appendChild(self.header(c, i));
  });
  thead.appendChild(head);
  var tbody = el("tbody");
  this.topRow = this.spacer();
  this.bottomRow = this.spacer();
  tbody.appendChild(this.topRow);
  tbody.appendChild(this.bottomRow);
  table.appendChild(colgroup);
  table.appendChild(thead);
  table.appendChild(tbody);
  this.table = table;
  this.thead = thead;
  this.tbody = tbody;
  table.style.width = this.tableWidth() + "px";
  this.emptyNote = el("div", "empty");
  this.emptyNote.hidden = true;
  this.wrap.appendChild(table);
  this.wrap.appendChild(this.emptyNote);
  tbody.addEventListener("click", function (ev) { var tr = rowOf(ev.target); if (tr) self.select(+tr.dataset.pos); });
  tbody.addEventListener("dblclick", function (ev) { var tr = rowOf(ev.target); if (tr) self.open(+tr.dataset.pos); });
  this.reset();
};

Grid.prototype.spacer = function () {
  var tr = el("tr", "spacer"), td = el("td");
  td.colSpan = this.cols.length + 1;
  tr.appendChild(td);
  return tr;
};

Grid.prototype.tableWidth = function () {
  var w = this.originW || 0, st = this.st;
  this.cols.forEach(function (c) { w += st.widths[c]; });
  return w;
};

Grid.prototype.header = function (c, i) {
  var self = this, col = this.seg.cols[c], m = this.model;
  var th = el("th"), box = el("div", "hwrap");
  // A button, so a heading sorts from the keyboard as well (Enter, Space).
  var label = el("button", "hlabel", col.l);
  label.type = "button";
  label.dataset.col = String(c);
  label.title = "Sort by " + col.l;
  label.addEventListener("click", function () { self.sortBy(c); });
  th.setAttribute("aria-sort", m.sortCol === c ? (m.sortDesc ? "descending" : "ascending") : "none");
  box.appendChild(label);
  if (col.badge) {
    var badge = el("span", "badge", col.badge);
    badge.title = col.tip || "";
    box.appendChild(badge);
  }
  if (m.sortCol === c) box.appendChild(el("span", "sortmark", m.sortDesc ? "\u25bc" : "\u25b2"));
  if (RENDERERS.filterPopup) {
    var funnel = el("button", "funnel" + (m.hasFilterOn(c) ? " on" : ""), "\u25bd");
    funnel.title = "Filter " + col.l;
    funnel.setAttribute("aria-label", "Filter " + col.l);
    funnel.dataset.col = String(c);
    funnel.addEventListener("click", function (ev) { ev.stopPropagation(); RENDERERS.filterPopup(funnel, self, c); });
    box.appendChild(funnel);
  }
  if (col.note) th.title = col.note;
  var handle = el("span", "resize");
  handle.addEventListener("mousedown", function (ev) { self.startResize(ev, c, i); });
  box.appendChild(handle);
  th.appendChild(box);
  return th;
};

Grid.prototype.sortBy = function (c) {
  var m = this.model;
  var focused = document.activeElement && document.activeElement.classList &&
    document.activeElement.classList.contains("hlabel");
  m.setSort(c, m.sortCol === c ? !m.sortDesc : false);
  this.st.sel = -1;
  this.rebuild();
  if (focused) {
    // The heading was rebuilt: keep the keyboard on the one just used.
    var again = this.thead.querySelector('button.hlabel[data-col="' + c + '"]');
    if (again) again.focus();
  }
};

Grid.prototype.startResize = function (ev, c, i) {
  ev.preventDefault();
  ev.stopPropagation();
  var self = this, startX = ev.clientX, startW = this.st.widths[c], min = headingMinWidth(this.seg.cols[c]);
  function move(e) {
    var w = Math.max(min, startW + e.clientX - startX);
    self.st.widths[c] = w;
    self.colEls[i].style.width = w + "px";
    self.table.style.width = self.tableWidth() + "px";
  }
  function up() {
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", up);
    self.reset();
  }
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", up);
};

Grid.prototype.reset = function () {
  if (!this.table) return;
  var vis = this.model.visible, lh = this.lh, cap = WRAP ? (this.seg.cap || LINE_CAP) : 2;
  var cols = this.cols, rows = this.seg.rows, widths = this.st.widths;
  this.count = vis.length;
  var est = new Float64Array(this.count);
  for (var p = 0; p < this.count; p++) {
    var cells = rows[vis[p]], lines = 1;
    for (var i = 0; i < cols.length && lines < cap; i++) {
      var v = cells[cols[i]];
      if (typeof v === "string" && v.length > 20) {
        var per = Math.max(4, (widths[cols[i]] - 12) / 7);
        lines = Math.max(lines, Math.min(cap, Math.ceil(v.length / per)));
      }
    }
    est[p] = lines * lh + 9;
  }
  this.tree = new Fenwick(est);
  this.start = this.end = -1;
  this.emptyNote.hidden = this.count !== 0;
  clear(this.emptyNote);
  if (!this.count) {
    this.emptyNote.appendChild(el("div", null, "No rows match the filters in force."));
    var b = el("button", null, "Clear filters"), self = this;
    b.addEventListener("click", function () {
      self.model.clearAll();
      var box = document.getElementById("wc-filter");
      if (box) box.value = "";
      CURRENT.refresh();
    });
    this.emptyNote.appendChild(b);
  }
  this.dirty = true;
  this.render();
};

Grid.prototype.clearRows = function () {
  while (this.topRow.nextSibling && this.topRow.nextSibling !== this.bottomRow) {
    this.tbody.removeChild(this.topRow.nextSibling);
  }
};

Grid.prototype.setSpacers = function (above, below) {
  this.topRow.firstChild.style.height = above + "px";
  this.bottomRow.firstChild.style.height = below + "px";
};

Grid.prototype.render = function () {
  if (!this.table) return;
  // The model's visible list can change under a render already scheduled
  // (a queued frame, a scroll) before reset() has re-measured it. Drawing
  // from the stale count would read rows past the end of the new list, so
  // re-measure first; reset() draws once it has.
  if (this.model.visible.length !== this.count) { this.reset(); return; }
  if (!this.count) { this.clearRows(); this.setSpacers(0, 0); return; }
  var top = this.wrap.scrollTop, height = Math.max(1, this.wrap.clientHeight - this.thead.offsetHeight);
  var first = this.tree.find(top), last = this.tree.find(top + height);
  var start = Math.max(0, first - OVERSCAN), end = Math.min(this.count, last + OVERSCAN + 1);
  if (!this.dirty && start === this.start && end === this.end) return;
  this.dirty = false;
  this.start = start;
  this.end = end;
  this.clearRows();
  var frag = document.createDocumentFragment(), made = [];
  for (var p = start; p < end; p++) { var tr = this.row(p); made.push(tr); frag.appendChild(tr); }
  this.tbody.insertBefore(frag, this.bottomRow);
  this.capRows(made);
  for (var i = 0; i < made.length; i++) this.tree.set(start + i, made[i].offsetHeight);
  this.setSpacers(this.tree.prefix(start), Math.max(0, this.tree.total() - this.tree.prefix(end)));
  if (end < this.count && this.tree.find(top + height) + OVERSCAN >= end) {
    // Measured rows came out shorter than estimated: fill the gap now.
    var self = this;
    this.dirty = true;
    requestAnimationFrame(function () { self.render(); });
  }
};

Grid.prototype.row = function (p) {
  var r = this.model.visible[p], seg = this.seg, cells = seg.rows[r], tr = el("tr");
  tr.dataset.pos = String(p);
  var origin = seg.origins[seg.org[r]], word = originWord(seg, r);
  if (ORIGIN_TINTED[word]) tr.className = "carved";
  if (p === this.st.sel) tr.classList.add("sel");
  var oh = el("th", "origin", word);
  oh.scope = "row";
  oh.title = (ORIGIN_TIPS[word] || word) + (origin && origin !== word ? " (" + origin + ")" : "");
  tr.appendChild(oh);
  for (var i = 0; i < this.cols.length; i++) {
    var c = this.cols[i], col = seg.cols[c], td = el("td");
    var cls = "cell" + (col.num ? " num" : "") +
      (col.kind === "time" || col.kind === "time_local" || col.kind === "offset" ? " mono" : "");
    if (col.kind === "bar") td.appendChild(shareBar(cells[c], this.sharePeak(c), seg));
    else td.appendChild(el("div", cls, displayText(cells[c], col)));
    tr.appendChild(td);
  }
  return tr;
};

var GRAINS = {minute: 1, hour: 1, day: 1, month: 1};
var SHARE_TIP = "% of the busiest %u in this view. The bar's width is " +
  "square-root scaled so smaller periods stay visible — the exact " +
  "count is in the Records column.";

function shareOf(v) {
  var n = parseFloat(pyText(v));
  return isFinite(n) ? Math.max(0, Math.min(1, n)) : null;
}

function shareBar(value, peak, seg) {
  // bar_delegate.ShareBarDelegate, on the page: the width is square-root
  // scaled so a long tail stays comparable, the tooltip states the linear
  // share in words, and the peak is the busiest row ON SCREEN
  // (timeline._rescale_share_bars). The fraction itself is never printed.
  var box = el("div", "share"), share = shareOf(value);
  if (share === null) return box;
  var rel = peak > 0 ? share / peak : 0, fill = el("i");
  fill.style.width = Math.round(Math.sqrt(rel) * 100) + "%";
  // Timeline's segments are keyed "<grain>_<clock>" (package_snapshot).
  var grain = String(seg.key).split("_")[0];
  box.title = (rel * 100).toFixed(1) + SHARE_TIP.replace("%u",
    GRAINS[grain] ? grain : "period");
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", box.title);
  box.appendChild(fill);
  return box;
}

Grid.prototype.sharePeak = function (c) {
  // Once per visible set, not once per painted row: the minute grain can
  // list tens of thousands of periods.
  var vis = this.model.visible, rows = this.seg.rows, peak = 0;
  if (this._peak && this._peak.vis === vis && this._peak.c === c) return this._peak.v;
  for (var p = 0; p < vis.length; p++) {
    var s = shareOf(rows[vis[p]][c]);
    if (s !== null && s > peak) peak = s;
  }
  this._peak = {vis: vis, c: c, v: peak};
  return peak;
};

Grid.prototype.capRows = function (rows) {
  // Read every height first, then write: one layout, not one per cell.
  var lh = this.lh, cap = WRAP ? (this.seg.cap || LINE_CAP) : 2, limit = cap * lh + 1, over = [];
  for (var i = 0; i < rows.length; i++) {
    var divs = rows[i].getElementsByClassName("cell");
    for (var j = 0; j < divs.length; j++) {
      var d = divs[j], text = d.textContent;
      if (text.length < 24 && text.indexOf("\n") < 0) continue;
      var h = d.scrollHeight;
      if (h > limit) over.push([d, Math.round(h / lh), rows[i], j]);
    }
  }
  var self = this;
  over.forEach(function (item) {
    var d = item[0], hidden = item[1] - (cap - 1);
    d.style.maxHeight = ((cap - 1) * lh) + "px";
    var more = el("button", "more", MORE_MARKER.replace("%s", fmtCount(hidden)));
    var pos = +item[2].dataset.pos, c = self.cols[item[3]];
    more.addEventListener("click", function (ev) { ev.stopPropagation(); self.whole(pos, c); });
    d.parentNode.appendChild(more);
  });
};

Grid.prototype.whole = function (pos, c) {
  var r = this.model.visible[pos], col = this.seg.cols[c];
  showWhole(col.l, displayText(this.seg.rows[r][c], col));
};

Grid.prototype.onKey = function (ev) {
  // Only keys pressed on the grid itself: Enter on a heading button, a
  // funnel or a "more lines" marker belongs to that button.
  if (ev.target !== this.wrap) return;
  if (!this.count || isTyping(ev.target)) return;
  var sel = this.st.sel, page = Math.max(1, Math.floor(this.wrap.clientHeight / (this.lh + 9)));
  if (ev.key === "ArrowDown") sel = Math.min(this.count - 1, sel + 1);
  else if (ev.key === "ArrowUp") sel = Math.max(0, sel - 1);
  else if (ev.key === "PageDown") sel = Math.min(this.count - 1, sel + page);
  else if (ev.key === "PageUp") sel = Math.max(0, sel - page);
  else if (ev.key === "Home") sel = 0;
  else if (ev.key === "End") sel = this.count - 1;
  else if (ev.key === "Enter") { ev.preventDefault(); if (sel >= 0) this.open(sel); return; }
  else return;
  ev.preventDefault();
  this.select(sel);
};

Grid.prototype.select = function (pos) {
  // Selection moves a class; it never redraws the rows. Chrome fires
  // dblclick only when both presses land on the SAME node, so a first click
  // that rebuilt the row under the pointer made a double-click impossible.
  if (!this.count || pos < 0 || pos >= this.count) return;
  this.st.sel = pos;
  var old = this.tbody.querySelector("tr.sel");
  if (old) old.classList.remove("sel");
  var tr = this.tbody.querySelector('tr[data-pos="' + pos + '"]');
  if (tr) tr.classList.add("sel");
  var top = this.tree.prefix(pos), bottom = top + this.tree.v[pos];
  var room = this.wrap.clientHeight - this.thead.offsetHeight;
  // A scroll fires the scroll handler, which draws any rows newly in view;
  // row() paints .sel on the selected one.
  if (top < this.wrap.scrollTop) this.wrap.scrollTop = top;
  else if (bottom > this.wrap.scrollTop + room) this.wrap.scrollTop = bottom - room;
};

Grid.prototype.open = function (pos) {
  this.select(pos);
  var r = this.model.visible[pos], seg = this.seg;
  if (RENDERERS.record) { RENDERERS.record(this.view, seg, r); return; }
  showWhole(seg.label + " row", seg.cols.map(function (col, c) {
    return col.l + "\t" + displayText(seg.rows[r][c], col);
  }).join("\n"));
};

window.addEventListener("resize", function () {
  if (CURRENT && CURRENT.grid) { CURRENT.grid.dirty = true; CURRENT.grid.render(); }
});

function findSegment(viewKey, segKey) {
  var view = viewByKey(viewKey);
  if (!view) throw new Error("no view " + viewKey);
  var seg = view.segments.filter(function (s) { return s.key === segKey; })[0];
  if (!seg) throw new Error("no segment " + segKey + " in " + viewKey);
  return {view: view, seg: seg};
}

API.openSegment = function (viewKey, segKey, text) {
  go("view:" + viewKey, {segment: segKey, text: typeof text === "string" ? text : undefined});
};
API.model = function (viewKey, segKey) {
  var found = findSegment(viewKey, segKey);
  return segmentState(found.view, found.seg).model;
};
API.setWrap = function (on) {
  WRAP = !!on;
  saveSetting("wc-wrap", WRAP ? "on" : "off");
  if (CURRENT && CURRENT.grid) CURRENT.grid.rebuild();
};
API.visibleRows = function () { return CURRENT ? CURRENT.state.model.visible.slice() : []; };
