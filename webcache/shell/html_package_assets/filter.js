// The column filter popup (operator, operands, the value list or date
// tree) and Search all views. Every filter it sets is a SegmentModel
// filter: the same rules as the app's RecordFilter (model.js), never a
// second set. The popup follows widgets/filter_popup.py: values and the
// condition combine with AND, a reopened popup shows what is in force,
// and nothing ticked means nothing, never everything.

var VALUE_ROW_PX = 22;
var VALUE_BOX_PX = 300;
var NO_OPERAND = ["is blank", "is not blank", "is yes", "is no"];
var OP_LABELS = {"is yes": "Is Yes", "is no": "Is No"};
// record_filter.sort_labels: the popup's two sort buttons, worded by kind.
var SORT_FAMILY = {num: "num", count: "num", size: "num", offset: "num", bar: "num",
                   time: "time", time_local: "time"};
var SORT_LABELS = {num: ["Sort smallest first", "Sort largest first"],
                   time: ["Sort oldest first", "Sort newest first"]};
function sortLabels(col) { return SORT_LABELS[SORT_FAMILY[col.kind]] || ["Sort A to Z", "Sort Z to A"]; }
API.sortLabels = sortLabels;
var KWIC_RADIUS = 40;            // search_loader.KWIC_RADIUS
var SNIPPETS_PER_SEGMENT = 3;
var ELLIPSIS = "\u2026";
// search_loader._printable: control and format characters read as a space.
var UNPRINTABLE_RE = /[\u0000-\u001f\u007f-\u009f\u00ad\u061c\u180e\u200b-\u200f\u2028-\u202e\u2060-\u2064\u2066-\u206f\ufeff]/g;

function virtualRows(items, drawRow) {
  // A screenful (plus a margin) in the DOM at a time: every value is
  // listed, none is ever dropped (record_filter's value_counts: "no cap").
  // A value wraps to its whole length, so rows have their
  // own heights: estimated first, then measured as they are drawn, in the
  // same height tree the grid uses.
  var box = el("div", "values"), inner = el("div");
  inner.style.position = "relative";
  box.appendChild(inner);
  var list = {node: box, items: items, tree: null, of: null};
  function estimate(item) {
    var text = (item && (item.text !== undefined ? item.text : item.label)) || "";
    return VALUE_ROW_PX * Math.max(1, Math.ceil(String(text).length / 42));
  }
  list.render = function () {
    clear(inner);
    var all = list.items;
    if (list.of !== all) {
      var est = new Float64Array(all.length);
      for (var e = 0; e < all.length; e++) est[e] = estimate(all[e]);
      list.tree = new Fenwick(est);
      list.of = all;
    }
    var tree = list.tree, changed = false;
    if (!all.length) { inner.style.height = "0px"; return; }
    // A list built before its popup is in the page has no width to wrap in,
    // so nothing can be measured yet: draw on estimates, then again once
    // the popup has been placed.
    if (!box.isConnected) requestAnimationFrame(function () { if (box.isConnected) list.render(); });
    var first = Math.max(0, tree.find(box.scrollTop) - 2);
    var bottom = box.scrollTop + VALUE_BOX_PX;
    for (var i = first; i < all.length && (i === first || tree.prefix(i) < bottom + 2 * VALUE_ROW_PX); i++) {
      var row = drawRow(all[i]);
      row.style.position = "absolute";
      row.style.top = tree.prefix(i) + "px";
      inner.appendChild(row);
      var h = Math.max(VALUE_ROW_PX, row.offsetHeight);
      if (h !== tree.v[i]) { tree.set(i, h); changed = true; }
    }
    inner.style.height = tree.total() + "px";
    if (changed) {
      // Heights measured on this pass moved the rows below them: place again.
      var rows = inner.childNodes;
      for (var k = 0; k < rows.length; k++) rows[k].style.top = tree.prefix(first + k) + "px";
    }
  };
  box.addEventListener("scroll", function () { list.render(); });
  return list;
}

function valueRow(text, n, box, depth, twist) {
  var label = el("label");
  label.title = text;
  if (depth) label.style.paddingLeft = (4 + depth * 16) + "px";
  label.appendChild(box);
  if (twist) label.appendChild(twist);
  label.appendChild(el("span", "v", text));
  label.appendChild(el("span", "note", fmtCount(n)));
  return label;
}

function valueList(counts, checked, col) {
  // A flat list: one row per distinct value, ticked when allowed.
  var shown = counts.slice();
  var list = virtualRows(shown, function (item) {
    var cb = el("input");
    cb.type = "checkbox";
    cb.checked = checked.has(item.id);
    cb.addEventListener("change", function () {
      if (cb.checked) checked.add(item.id); else checked.delete(item.id);
      if (list.onchange) list.onchange();
    });
    return valueRow(item.label, item.n, cb, 0, null);
  });
  list.render();
  list.filter = function (text) {
    // filter_popup._apply_value_search: what the value SHOWS (plus a
    // number's plain digits), never its count and never "(blank)".
    var t = String(text).trim().toLowerCase();
    shown = t ? counts.filter(function (x) { return searchText(x.v, col).toLowerCase().indexOf(t) >= 0; })
              : counts.slice();
    list.items = shown;
    list.node.scrollTop = 0;
    list.render();
    return shown.length;
  };
  list.setAll = function (on) {
    // The values shown, so a search then Select all ticks what is in view.
    shown.forEach(function (x) { if (on) checked.add(x.id); else checked.delete(x.id); });
    list.render();
  };
  list.anyChecked = function () { return checked.size > 0; };
  list.chosen = function () {
    // Everything ticked is not a filter. Nothing ticked IS one.
    return checked.size === counts.length ? null : new Set(checked);
  };
  return list;
}

function pad2(n) { return (n < 10 ? "0" : "") + n; }

function dateTree(counts, active, col) {
  // filter_popup._populate_dates: year > month > day, each with a row
  // count. The day is the one the grid SHOWS: a datetime's own fields, so
  // a UTC column groups by UTC and a local column by each record's own
  // clock. A day carries every stored value on it, so what is chosen is
  // still the stored values and filtering is unchanged.
  var years = {}, roots = [], others = [];
  counts.forEach(function (x) {
    var dt = typeof x.v === "string" && x.v.charAt(0) === TAG_DT ? parseTaggedDt(x.v) : null;
    if (!dt) { others.push(x); return; }
    var y = years[dt.y] || (years[dt.y] = {});
    var m = y[dt.mo] || (y[dt.mo] = {});
    (m[dt.d] || (m[dt.d] = [])).push(x);
  });
  function leaf(label, values, depth) {
    var on = !active || values.some(function (x) { return active.has(x.id); });
    var hay = values.map(function (x) { return searchText(x.v, col).toLowerCase(); });
    return {label: label, n: values.reduce(function (s, x) { return s + x.n; }, 0), depth: depth,
            ids: values.map(function (x) { return x.id; }), on: on, hit: true, hay: hay};
  }
  function branch(label, children, depth) {
    return {label: label, n: children.reduce(function (s, x) { return s + x.n; }, 0), depth: depth,
            children: children, open: false, hit: true};
  }
  function numeric(o) { return Object.keys(o).map(Number).sort(function (a, b) { return a - b; }); }
  numeric(years).forEach(function (y) {
    var months = numeric(years[y]).map(function (mo) {
      var mLabel = String(y) + "-" + pad2(mo);
      var days = numeric(years[y][mo]).map(function (d) {
        return leaf(mLabel + "-" + pad2(d), years[y][mo][d], 2);
      });
      return branch(mLabel, days, 1);
    });
    roots.push(branch(String(y), months, 0));
  });
  others.forEach(function (x) { roots.push(leaf(x.label, [x], 0)); });
  var filtering = false;

  function leaves(node, out) {
    if (!node.children) out.push(node);
    else node.children.forEach(function (c) { leaves(c, out); });
    return out;
  }
  var allLeaves = [];
  roots.forEach(function (r) { leaves(r, allLeaves); });
  function stateOf(node) {
    var ls = leaves(node, []), on = ls.filter(function (l) { return l.on; }).length;
    return on === ls.length ? "on" : on ? "some" : "off";
  }
  function flatten() {
    var out = [];
    (function walk(nodes) {
      nodes.forEach(function (node) {
        if (!node.hit) return;
        out.push(node);
        if (node.children && (node.open || filtering)) walk(node.children);
      });
    })(roots);
    return out;
  }
  var list = virtualRows(flatten(), function (node) {
    var cb = el("input");
    cb.type = "checkbox";
    var state = node.children ? stateOf(node) : (node.on ? "on" : "off");
    cb.checked = state === "on";
    cb.indeterminate = state === "some";
    cb.addEventListener("change", function () {
      var turnOn = state !== "on";
      leaves(node, []).forEach(function (l) { l.on = turnOn; });
      list.render();
      if (list.onchange) list.onchange();
    });
    var twist = null;
    if (node.children) {
      twist = el("button", "twist", node.open || filtering ? "\u25be" : "\u25b8");
      twist.type = "button";
      twist.setAttribute("aria-label", (node.open ? "Collapse " : "Expand ") + node.label);
      twist.addEventListener("click", function (ev) {
        ev.preventDefault();
        node.open = !node.open;
        list.items = flatten();
        list.render();
      });
    } else if (node.depth) {
      twist = el("i", "twist-space");
    }
    return valueRow(node.label, node.n, cb, node.depth, twist);
  });
  list.render();
  list.filter = function (text) {
    // filter_popup._search_dates: a day stays when the needle is in its
    // date or in any of its values' displayed text; empty months and
    // years are hidden.
    var t = String(text).trim().toLowerCase();
    filtering = !!t;
    var shown = 0;
    allLeaves.forEach(function (l) {
      l.hit = !t || l.label.toLowerCase().indexOf(t) >= 0 || l.hay.some(function (h) { return h.indexOf(t) >= 0; });
      if (l.hit) shown++;
    });
    (function settle(nodes) {
      nodes.forEach(function (n) {
        if (!n.children) return;
        settle(n.children);
        n.hit = n.children.some(function (c) { return c.hit; });
      });
    })(roots);
    list.items = flatten();
    list.node.scrollTop = 0;
    list.render();
    return shown;
  };
  list.setAll = function (on) {
    allLeaves.forEach(function (l) { if (l.hit) l.on = on; });
    list.render();
  };
  list.anyChecked = function () { return allLeaves.some(function (l) { return l.on; }); };
  list.chosen = function () {
    var picked = new Set(), every = true;
    allLeaves.forEach(function (l) {
      if (l.on) l.ids.forEach(function (id) { picked.add(id); }); else every = false;
    });
    return every ? null : picked;
  };
  return list;
}

function dtText(dt) {
  return dt.y + "-" + pad2(dt.mo) + "-" + pad2(dt.d) + " " + pad2(dt.h) + ":" + pad2(dt.mi) + ":" + pad2(dt.s);
}

function refocusFunnel(c) {
  // The heading was rebuilt by the filter just applied: the keyboard goes
  // back to this column's funnel, as it would had nothing been redrawn.
  var funnel = document.querySelector('#wc-grid thead .funnel[data-col="' + c + '"]');
  giveFocusBack(funnel);
}

RENDERERS.filterPopup = function (anchor, grid, c) {
  var model = grid.model, col = grid.seg.cols[c];
  var counts = model.valueCounts(c);
  var ops = opsFor(col, counts);
  var existing = model.conditions[c] || null;
  var active = model.values[c] || null;
  var isTime = col.kind === "time" || col.kind === "time_local";
  openPopover(anchor, function (node, close) {
    var title = el("div", "ptitle");
    title.appendChild(el("strong", null, col.l));
    title.appendChild(copyButton(col.l, "Copy column name"));
    var closeTop = el("button", null, "Close");
    closeTop.addEventListener("click", close);
    title.appendChild(closeTop);
    node.appendChild(title);

    // Excel's drop-down sorts as well as filters, as a heading click would.
    var sorts = el("div", "bar"), labels = sortLabels(col);
    [false, true].forEach(function (desc) {
      var b = el("button", null, labels[desc ? 1 : 0]);
      b.addEventListener("click", function () {
        model.setSort(c, desc);
        grid.st.sel = -1;
        close();
        grid.rebuild();
        refocusFunnel(c);
      });
      sorts.appendChild(b);
    });
    node.appendChild(sorts);

    var find = el("input");
    find.type = "search";
    find.placeholder = "Search values\u2026";
    find.setAttribute("aria-label", "Find a value");
    node.appendChild(find);
    var picks = el("div", "bar"), all = el("button", null, "Select all"), none = el("button", null, "Select none");
    picks.appendChild(all);
    picks.appendChild(none);
    picks.appendChild(el("span", "note", fmtCount(counts.length) + " distinct " +
      plural(counts.length, "value", "values") + (isTime ? ", by year, month and day" : "")));
    node.appendChild(picks);
    var list = isTime ? dateTree(counts, active, col)
                      : valueList(counts, new Set(active ? Array.from(active) : counts.map(function (x) { return x.id; })), col);
    node.appendChild(list.node);
    var status = el("div", "note status");
    node.appendChild(status);
    var lastSearch = "";
    function sayStatus(shown) {
      if (lastSearch.trim() && !shown) status.textContent = "No values match \"" + lastSearch + "\".";
      else if (!list.anyChecked()) status.textContent = "No values selected: Apply would match no rows.";
      else status.textContent = "";
    }
    list.onchange = function () { sayStatus(1); };
    find.addEventListener("input", function () { lastSearch = find.value; sayStatus(list.filter(find.value)); });
    all.addEventListener("click", function () { list.setAll(true); sayStatus(1); });
    none.addEventListener("click", function () { list.setAll(false); sayStatus(1); });
    sayStatus(1);

    // filter_popup.FilterPopup: two condition rows joined by And/Or, as
    // Excel's Custom AutoFilter; either row filled alone is the condition.
    function conditionRow(seed, suffix) {
      var row = el("div", "bar"), select = el("select");
      select.setAttribute("aria-label", "Operator" + suffix);
      var noCond = el("option", null, "(no condition)");
      noCond.value = "";
      select.appendChild(noCond);
      ops.forEach(function (op) {
        var o = el("option", null, OP_LABELS[op] || op);
        o.value = op;
        if (seed && seed.op === op) o.selected = true;
        select.appendChild(o);
      });
      var a = el("input"), b = el("input");
      a.type = b.type = "text";
      a.setAttribute("aria-label", "Operand" + suffix);
      b.setAttribute("aria-label", "Second operand" + suffix);
      a.placeholder = b.placeholder = OPERAND_PLACEHOLDERS[col.kind] || "text";
      if (seed) {
        a.value = seed.a === null ? "" : String(seed.a);
        b.value = seed.b === null ? "" : String(seed.b);
      }
      [select, a, b].forEach(function (n) { row.appendChild(n); });
      node.appendChild(row);
      return {select: select, a: a, b: b};
    }
    node.appendChild(el("div", "note", "Show rows where:"));
    var joined = existing instanceof JoinedCondition;
    var rows = [conditionRow(joined ? existing.first : existing, "")];
    var joinRow = el("div", "bar"), joinSelect = el("select");
    joinSelect.setAttribute("aria-label", "Join");
    ["And", "Or"].forEach(function (word) {
      var o = el("option", null, word);
      o.value = word.toLowerCase();
      if (joined && existing.join === o.value) o.selected = true;
      joinSelect.appendChild(o);
    });
    joinRow.appendChild(joinSelect);
    node.appendChild(joinRow);
    rows.push(conditionRow(joined ? existing.second : null, " 2"));
    var anchorNote = el("div", "note");
    var hint = el("div", "note", isTime
      ? "A date with no zone is read on this column's own clock, as in the app."
      : "Text operators match what is shown, ignoring case. Regular expressions use JavaScript syntax.");
    var err = el("div", "err");
    err.setAttribute("role", "alert");
    function sync() {
      var anchored = false;
      rows.forEach(function (row) {
        var op = row.select.value;
        row.a.hidden = !op || NO_OPERAND.indexOf(op) >= 0;
        row.b.hidden = op !== "between";
        if (op === "in the last N days") anchored = true;
      });
      anchorNote.hidden = !anchored;
      if (!anchorNote.hidden) {
        // filter_popup._anchor_preview_text: never today's date.
        var newest = model.newest(c);
        anchorNote.textContent = newest
          ? "Anchored to the newest " + col.l + " in this column: " + dtText(newest) + " (not today's date)."
          : "No dated value found in " + col.l + " -- \"in the last N days\" will match nothing until one is.";
      }
    }
    rows.forEach(function (row) { row.select.addEventListener("change", sync); });
    sync();
    [anchorNote, hint, err].forEach(function (n) { node.appendChild(n); });

    var actions = el("div", "bar");
    var apply = el("button", "on", "Apply"), clearColumn = el("button", null, "Clear this column"), cancel = el("button", null, "Cancel");
    function rowCondition(row) {
      var op = row.select.value, av = row.a.value.trim(), bv = row.b.value.trim();
      if (!op || (NO_OPERAND.indexOf(op) < 0 && !av)) return null;
      return new Condition(op, NO_OPERAND.indexOf(op) >= 0 ? null : av, op === "between" ? bv : null);
    }
    function doApply() {
      var oneSided = rows.some(function (row) {
        return row.select.value === "between" && row.a.value.trim() && !row.b.value.trim();
      });
      if (oneSided) { err.textContent = "\"between\" needs a second value too."; return; }
      var first = rowCondition(rows[0]), second = rowCondition(rows[1]);
      var cond = first && second ? new JoinedCondition(first, joinSelect.value, second) : first || second;
      if (cond && cond.error) {
        var regex = rows.some(function (row) { return row.select.value === "matches regex"; });
        err.textContent = (regex ? "Invalid regex: " : "Invalid filter: ") + cond.error;
        return;
      }
      model.setCondition(c, cond);
      model.setValues(c, list.chosen());
      close();
      CURRENT.refresh();
      refocusFunnel(c);
    }
    apply.addEventListener("click", doApply);
    rows.forEach(function (row) {
      [row.a, row.b].forEach(function (input) {
        input.addEventListener("keydown", function (ev) { if (ev.key === "Enter") doApply(); });
      });
    });
    clearColumn.addEventListener("click", function () {
      model.setCondition(c, null);
      model.setValues(c, null);
      close();
      CURRENT.refresh();
      refocusFunnel(c);
    });
    cancel.addEventListener("click", close);
    [apply, clearColumn, cancel].forEach(function (n) { actions.appendChild(n); });
    node.appendChild(actions);
    setTimeout(function () { find.focus(); }, 0);
  });
};

RENDERERS.originPopup = function (anchor, grid) {
  // records_table._open_origin_menu: each origin with its count, ticked
  // while shown. Untick one to hide those rows.
  var model = grid.model, counts = model.originCounts(), active = model.origins;
  openPopover(anchor, function (node, close) {
    var title = el("div", "ptitle");
    title.appendChild(el("strong", null, ORIGIN_HEADING));
    var closeTop = el("button", null, "Close");
    closeTop.addEventListener("click", close);
    title.appendChild(closeTop);
    node.appendChild(title);
    var list = el("div", "values short"), boxes = [];
    counts.forEach(function (x) {
      var box = el("input");
      box.type = "checkbox";
      box.checked = !active || active.has(x.w);
      boxes.push([x.w, box]);
      list.appendChild(valueRow(x.w, x.n, box));
    });
    node.appendChild(list);
    function refocus() {
      giveFocusBack(document.querySelector("#wc-grid thead th.origin .ofunnel"));
    }
    var actions = el("div", "bar");
    var apply = el("button", "on", "Apply"), clear = el("button", null, "Clear this column"), cancel = el("button", null, "Cancel");
    apply.addEventListener("click", function () {
      var kept = new Set(boxes.filter(function (b) { return b[1].checked; }).map(function (b) { return b[0]; }));
      model.setOrigins(kept.size === boxes.length ? null : kept);
      close();
      CURRENT.refresh();
      refocus();
    });
    clear.addEventListener("click", function () {
      model.setOrigins(null);
      close();
      CURRENT.refresh();
      refocus();
    });
    cancel.addEventListener("click", close);
    [apply, clear, cancel].forEach(function (n) { actions.appendChild(n); });
    node.appendChild(actions);
  });
};

// --- Search all views ----------------------------------------------------------

function plainLine(text) { return text.replace(UNPRINTABLE_RE, " "); }

function foldFind(text, needle) {
  // search_loader._fold_find: folded per character, so the match maps
  // back to the characters it came from.
  var folded = "", owner = [];
  for (var i = 0; i < text.length; i++) {
    var f = text.charAt(i).toLowerCase();
    folded += f;
    for (var k = 0; k < f.length; k++) owner.push(i);
  }
  var at = folded.indexOf(needle);
  if (at < 0) return null;
  return [owner[at], owner[at + needle.length - 1] + 1];
}

function snippet(label, text, needle) {
  // search_loader.keyword_context, drawn as nodes: text before, the match
  // in a <mark>, text after. Every piece is a text node.
  var line = el("div", "snip");
  line.appendChild(document.createTextNode(label + ": "));
  var span = foldFind(text, needle);
  if (!span) {
    line.appendChild(document.createTextNode(plainLine(text.slice(0, 2 * KWIC_RADIUS)) +
      (text.length > 2 * KWIC_RADIUS ? ELLIPSIS : "")));
    return line;
  }
  var from = Math.max(0, span[0] - KWIC_RADIUS), to = Math.min(text.length, span[1] + KWIC_RADIUS);
  line.appendChild(document.createTextNode((from ? ELLIPSIS : "") + plainLine(text.slice(from, span[0]))));
  line.appendChild(el("mark", null, plainLine(text.slice(span[0], span[1]))));
  line.appendChild(document.createTextNode(plainLine(text.slice(span[1], to)) + (to < text.length ? ELLIPSIS : "")));
  return line;
}

function evidenceHit(fields, needle) {
  // search_loader.recovered_hits: only the fields read from the carved
  // bytes (recovered_search.SEARCHED_FIELDS); a stub's key matches WHOLE.
  for (var i = 0; i < fields.length; i++) {
    var text = fields[i][1].toLowerCase();
    if (fields[i][2] ? text === needle : text.indexOf(needle) >= 0) return fields[i];
  }
  return null;
}

function rowSnippet(seg, r, needle) {
  var row = seg.rows[r];
  for (var c = 0; c < seg.cols.length; c++) {
    var parts = searchText(row[c], seg.cols[c]).split(SEP);
    for (var p = 0; p < parts.length; p++) {
      if (parts[p].toLowerCase().indexOf(needle) >= 0) return snippet(seg.cols[c].l, parts[p], needle);
    }
  }
  return null;
}

function searchSegment(view, seg, needle) {
  var hay = null, ev = seg.ev, n = 0, snips = [];
  for (var r = 0; r < seg.rows.length; r++) {
    var fieldHit = null, hit;
    if (ev && ev[r] >= 0) {
      fieldHit = evidenceHit(DATA.ev[ev[r]], needle);
      hit = !!fieldHit;
    } else {
      if (!hay) hay = segmentState(view, seg).model.haystack();
      hit = hay[r].indexOf(needle) >= 0;
    }
    if (!hit) continue;
    n++;
    if (snips.length < SNIPPETS_PER_SEGMENT) {
      var s = fieldHit ? snippet(fieldHit[0], fieldHit[1], needle) : rowSnippet(seg, r, needle);
      if (s) snips.push(s);
    }
  }
  return {n: n, snips: snips};
}

RENDERERS.search = function (main, text) {
  var typed = String(text || "").trim(), needle = typed.toLowerCase();
  var page = el("div", "page");
  main.appendChild(page);
  page.appendChild(el("h1", null, "Search all views"));
  var box = el("input", "filter");
  box.type = "search";
  box.id = "wc-search";
  box.value = typed;
  box.setAttribute("aria-label", "Search all views");
  box.addEventListener("keydown", function (ev) { if (ev.key === "Enter") go("search", box.value); });
  page.appendChild(box);
  page.appendChild(el("p", "note", "Every segment of every view is searched the way its own filter box matches: " +
    "every column, as shown, ignoring case. A recovered record is searched only in the fields read from its " +
    "carved bytes, as the app's Search does, never in a label this tool wrote. The browser's own Find (Ctrl+F) " +
    "sees only the rows on screen."));
  if (!needle) return;
  var results = el("div", "results"), total = 0;
  DATA.views.forEach(function (view) {
    view.segments.forEach(function (seg) {
      var found = searchSegment(view, seg, needle);
      if (!found.n) return;
      total += found.n;
      var hit = el("div", "hit");
      var b = el("button", null, view.label + " \u203a " + seg.label + " \u2014 " + fmtCount(found.n) + " " +
        plural(found.n, "row", "rows"));
      b.addEventListener("click", function () { go("view:" + view.key, {segment: seg.key, text: typed}); });
      hit.appendChild(b);
      found.snips.forEach(function (s) { hit.appendChild(s); });
      if (found.n > found.snips.length) {
        hit.appendChild(el("div", "note", "The first " + fmtCount(found.snips.length) + " of " + fmtCount(found.n) +
          " matching rows. Open the segment to see every one."));
      }
      results.appendChild(hit);
    });
  });
  page.appendChild(el("p", "count", total
    ? fmtCount(total) + " matching " + plural(total, "row", "rows") + " across the views below. Opening one sets " +
      "that view's own filter box, which reads every column as shown, so a segment of recovered records can show " +
      "more rows there than are counted here."
    : "No row in any view contains \u201c" + typed + "\u201d. A word's absence here is not evidence that the thing never happened."));
  page.appendChild(results);
};
