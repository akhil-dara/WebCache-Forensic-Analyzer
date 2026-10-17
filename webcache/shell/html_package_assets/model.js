// One segment's rows, filtered and sorted: a copy of widgets/record_filter.py
// (RecordFilter and Condition). Pure logic, no DOM. Text operators and the
// text box read what the grid SHOWS (display text), exactly as
// RecordFilter._condition_value and its haystack do; number and time
// operators read the stored value.

var TEXT_OPS = ["contains", "does not contain", "begins with", "ends with", "equals",
                "does not equal", "matches pattern", "does not match pattern",
                "is blank", "is not blank", "matches regex"];
var NUM_OPS = ["=", "!=", ">", ">=", "<", "<=", "between", "is blank"];
var TIME_OPS = ["before", "after", "on", "between", "in the last N days", "is blank"];
var FLAG_OPS = ["is yes", "is no", "is blank", "is not blank"];
var AMBIGUOUS_OPS = ["=", "!=", ">", ">=", "<", "<=", "between"];
var ALL_OPS = TEXT_OPS.concat(NUM_OPS, TIME_OPS, FLAG_OPS);
var OPS_BY_KIND = {
  text: TEXT_OPS, url: TEXT_OPS, flag: TEXT_OPS, domain: TEXT_OPS, types: TEXT_OPS,
  path: TEXT_OPS, carved: TEXT_OPS, only_carved: TEXT_OPS,
  num: NUM_OPS, count: NUM_OPS, size: NUM_OPS, offset: NUM_OPS, bar: NUM_OPS,
  time: TIME_OPS, time_local: TIME_OPS
};
var OPERAND_PLACEHOLDERS = {
  time: "YYYY-MM-DD or YYYY-MM-DD HH:MM:SS (UTC)",
  time_local: "YYYY-MM-DD or YYYY-MM-DD HH:MM:SS (local)",
  num: "a number", count: "a number", size: "bytes", offset: "a number or 0x hex", bar: "0 to 1"
};
var MULTI_SEPARATOR = ", ";   // column_spec.MULTI_SEPARATOR
var CHIP_VALUES_NAMED = 3;    // record_filter.RecordFilter.CHIP_VALUES_NAMED
var FLAG_WORDS = {"true": "Yes", "yes": "Yes", "1": "Yes", "false": "No", "no": "No", "0": "No"};
var OPERAND_RE = /^(\d{4})-?(\d{2})-?(\d{2})(?:[T ](\d{2}):?(\d{2})(?::?(\d{2})(?:[.,](\d{1,6})\d*)?)?)?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$/i;
var FLOAT_RE = /^[+-]?(?:\d(?:_?\d)*(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?$/;

function opsFor(col, counts) {
  // record_filter.operators_for: a flag column of Yes/No only offers Yes/No.
  if (col.kind === "flag") {
    var values = counts.filter(function (c) { return !isBlank(c.v); });
    if (values.length && values.every(function (c) { return c.v === "Yes" || c.v === "No"; })) return FLAG_OPS;
  }
  return OPS_BY_KIND[col.kind] || TEXT_OPS;
}

function pyFloat(a) {
  // Python float(); null where it would raise. 0x hex is read as well,
  // because the popup's offset placeholder offers it.
  if (a === null || a === undefined) return null;
  if (typeof a === "number") return a;
  var s = String(a).trim();
  if (/^[+-]?(inf|infinity)$/i.test(s)) return s.charAt(0) === "-" ? -Infinity : Infinity;
  if (/^[+-]?nan$/i.test(s)) return NaN;
  if (/^0x[0-9a-f]+$/i.test(s)) return parseInt(s, 16);
  return FLOAT_RE.test(s) ? Number(s.replace(/_/g, "")) : null;
}

function numericValue(v) {
  if (isBlank(v)) return null;
  if (typeof v === "number") return v;
  var tag = v.charAt(0);
  if (tag === TAG_BIG || tag === TAG_FLOAT) return Number(v.slice(1));
  if (tag === TAG_DT) return null;
  return pyFloat(v);
}

function parseDtText(s) {
  var m = OPERAND_RE.exec(s);
  if (!m) return null;
  var y = +m[1], mo = +m[2], d = +m[3], h = +(m[4] || 0), mi = +(m[5] || 0), sec = +(m[6] || 0);
  if (y < 1 || mo < 1 || mo > 12 || d < 1 || h > 23 || mi > 59 || sec > 59) return null;
  var probe = new Date(0);
  probe.setUTCFullYear(y, mo - 1, d);
  if (probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== d) return null;
  var us = m[7] ? Number((m[7] + "00000").slice(0, 6)) : 0;
  var offset = null;
  if (m[8]) {
    if (m[8].toUpperCase() === "Z") offset = 0;
    else {
      var digits = m[8].slice(1).replace(":", "");
      offset = (m[8].charAt(0) === "-" ? -1 : 1) *
        (Number(digits.slice(0, 2)) * 3600 + Number(digits.slice(2, 4) || 0) * 60);
    }
  }
  return makeDt(y, mo, d, h, mi, sec, us, offset);
}

function parseDtValue(v) {
  // record_filter._parse_dt / _safe_parse_dt, on a stored cell or a typed operand.
  if (isBlank(v)) return null;
  if (typeof v === "number") return Number.isInteger(v) ? parseDtText(String(v)) : null;
  var tag = v.charAt(0);
  if (tag === TAG_DT) return parseTaggedDt(v);
  if (tag === TAG_BIG) return null;
  if (tag === TAG_FLOAT) {
    var f = v.slice(1);
    return /^-?\d+\.0$/.test(f) ? parseDtText(f.slice(0, -2)) : null;
  }
  return parseDtText(v.trim());
}

function inFrame(operand, value) {
  // record_filter._in_frame: a typed date with no zone, read against a value
  // on a non-UTC clock, is a date on THAT clock.
  if (operand.offset !== null || value.offset === null || value.offset === 0) return operand;
  return makeDt(operand.y, operand.mo, operand.d, operand.h, operand.mi, operand.s, operand.us, value.offset);
}

function utcDay(dt) {
  var t = new Date(Math.floor(dt.instant) * 1000);
  return t.getUTCFullYear() + "-" + (t.getUTCMonth() + 1) + "-" + t.getUTCDate();
}

function compareOp(op, x, a) {
  switch (op) {
    case "=": return x === a;
    case "!=": return x !== a;
    case ">": return x > a;
    case ">=": return x >= a;
    case "<": return x < a;
    case "<=": return x <= a;
  }
  return false;
}

function wildcardRegex(pattern) {
  // record_filter.wildcard_regex: * any run, ? exactly one, all else
  // literal, the WHOLE value, ignoring case.
  var out = "";
  for (var i = 0; i < pattern.length; i++) {
    var ch = pattern.charAt(i);
    if (ch === "*") out += "[\\s\\S]*";
    else if (ch === "?") out += "[\\s\\S]";
    else out += ch.replace(/[.*+?^${}()|[\]\\\/-]/g, "\\$&");
  }
  return new RegExp("^(?:" + out + ")$", "i");
}

function Condition(op, a, b) {
  this.op = op;
  this.a = isBlank(a) ? null : a;
  this.b = isBlank(b) ? null : b;
  this.error = null;
  this.anchor = null;
  this.rx = null;
  this.aDt = null; this.bDt = null; this.aNum = null; this.bNum = null;
  if (op === "matches regex" && this.a !== null) {
    try { this.rx = new RegExp(String(this.a), "i"); } catch (e) { this.error = e.message; }
  } else if ((op === "matches pattern" || op === "does not match pattern") && this.a !== null) {
    this.rx = wildcardRegex(String(this.a));
  } else if (op === "before" || op === "after" || op === "on") {
    if (this.a !== null) {
      this.aDt = parseDtValue(String(this.a));
      if (!this.aDt) this.error = "unparseable date/time: " + this.a;
    }
  } else if (AMBIGUOUS_OPS.indexOf(op) >= 0) {
    var aNum = null, aDt = null, bNum = null, bDt = null;
    if (this.a !== null) {
      aNum = pyFloat(this.a);
      aDt = parseDtValue(String(this.a));
      if (aNum === null && !aDt) this.error = "not a number or a date/time: " + this.a;
    }
    if (op === "between" && this.b !== null) {
      bNum = pyFloat(this.b);
      bDt = parseDtValue(String(this.b));
      if (bNum === null && !bDt) this.error = "not a number or a date/time: " + this.b;
      else if (!this.error && this.a !== null && !((aNum !== null && bNum !== null) || (aDt && bDt)))
        this.error = "between needs both operands read the same way: " + this.a + " and " + this.b +
          " are not both numbers or both dates";
    }
    this.aNum = aNum; this.aDt = aDt; this.bNum = bNum; this.bDt = bDt;
    if (!this.error) {
      var swapNum = aNum !== null && bNum !== null && aNum > bNum;
      var swapDt = !!(aDt && bDt && aDt.instant > bDt.instant);
      if (swapNum) { this.aNum = bNum; this.bNum = aNum; }
      if (swapDt) { this.aDt = bDt; this.bDt = aDt; }
      if (swapNum || swapDt) { var t = this.a; this.a = this.b; this.b = t; }
    }
  } else if (op === "in the last N days") {
    var n = pyFloat(this.a);
    if (n === null || !isFinite(n) || n < 0 || n > 36500) this.error = "N must be a number of days, got " + this.a;
  }
  if (!this.error && ALL_OPS.indexOf(op) < 0) this.error = "unknown operator: " + op;
}

Condition.prototype.matches = function (v) {
  var op = this.op;
  if (op === "is yes") return v === "Yes";
  if (op === "is no") return v === "No";
  if (op === "is blank") return isBlank(v);
  if (op === "is not blank") return !isBlank(v);
  if (this.error) return false;
  if (op === "before" || op === "after" || op === "on") {
    if (!this.aDt) return false;
    var dt = parseDtValue(v);
    if (!dt) return false;
    var a = inFrame(this.aDt, dt);
    if (op === "before") return dt.instant < a.instant;
    if (op === "after") return dt.instant > a.instant;
    if (a !== this.aDt) return dt.y === a.y && dt.mo === a.mo && dt.d === a.d;
    return utcDay(dt) === utcDay(this.aDt);
  }
  if (op === "in the last N days") {
    if (!this.anchor || this.a === null) return false;
    var d2 = parseDtValue(v);
    if (!d2) return false;
    var start = this.anchor.instant - pyFloat(this.a) * 86400;
    return start <= d2.instant && d2.instant <= this.anchor.instant;
  }
  if (AMBIGUOUS_OPS.indexOf(op) >= 0) return this.matchAmbiguous(op, v);
  var s = pyText(v).toLowerCase(), a2 = this.a === null ? "" : String(this.a).toLowerCase();
  switch (op) {
    case "contains": return s.indexOf(a2) >= 0;
    case "does not contain": return s.indexOf(a2) < 0;
    case "begins with": return s.slice(0, a2.length) === a2;
    case "ends with": return a2.length === 0 || s.slice(s.length - a2.length) === a2;
    case "equals": return s === a2;
    case "does not equal": return s !== a2;
    case "matches regex": return !!(this.rx && this.rx.test(pyText(v)));
    case "matches pattern": return !!(this.rx && this.rx.test(pyText(v)));
    case "does not match pattern": return !(this.rx && this.rx.test(pyText(v)));
  }
  return false;
};

Condition.prototype.matchAmbiguous = function (op, v) {
  if (typeof v === "string" && v.charAt(0) === TAG_DT) {
    var dt = parseTaggedDt(v);
    if (!dt || !this.aDt) return false;
    if (op === "between") {
      if (!this.bDt) return false;
      return inFrame(this.aDt, dt).instant <= dt.instant && dt.instant <= inFrame(this.bDt, dt).instant;
    }
    return compareOp(op, dt.instant, inFrame(this.aDt, dt).instant);
  }
  var n = numericValue(v);
  if (n === null || this.aNum === null) return false;
  if (op === "between") return this.bNum !== null && this.aNum <= n && n <= this.bNum;
  return compareOp(op, n, this.aNum);
};

Condition.prototype.describe = function (col) {
  // record_filter.Condition.describe, word for word.
  var op = this.op, a = this.a;
  if (col && col.kind === "flag" && (op === "equals" || op === "does not equal") &&
      Object.prototype.hasOwnProperty.call(FLAG_WORDS, String(a).trim().toLowerCase())) {
    return (op === "equals" ? "Is " : "Is not ") + FLAG_WORDS[String(a).trim().toLowerCase()];
  }
  if (op === "is yes" || op === "is no") return "Is " + (op === "is yes" ? "Yes" : "No");
  if (op === "is blank" || op === "is not blank") return op;
  if (op === "between") return "between " + a + " and " + this.b;
  if (op === "in the last N days") return "in the last " + a + " days";
  return op + " \"" + a + "\"";
};

// record_filter.JoinedCondition: two conditions on one column, joined by
// "and" or "or" (Excel's Custom AutoFilter). Each half reads the cell as
// it would alone, so a join is matched by condMatches, never by a single
// value; op is null because no one operator describes the pair.
var JOINS = ["and", "or"];
function JoinedCondition(first, join, second) {
  if (JOINS.indexOf(join) < 0) throw new Error("a join is 'and' or 'or', not " + join);
  this.first = first;
  this.join = join;
  this.second = second;
  this.parts = [first, second];
  this.op = null;
  this.error = first.error || second.error || null;
}
JoinedCondition.prototype.matchesEach = function (valueFor) {
  return this.matchesHalves(function (half) { return half.matches(valueFor(half)); });
};
JoinedCondition.prototype.matchesHalves = function (halfMatches) {
  if (this.error) return false;
  var first = halfMatches(this.first);
  if (this.join === "and" && !first) return false;
  if (this.join === "or" && first) return true;
  return halfMatches(this.second);
};
JoinedCondition.prototype.matches = function (v) {
  return this.matchesEach(function () { return v; });
};
JoinedCondition.prototype.describe = function (col) {
  return this.first.describe(col) + " " + this.join + " " + this.second.describe(col);
};

function blankLabel(col) {
  // column_spec.blank_label: what an empty value of this column means.
  return (col && col.blank) || "(blank)";
}

function valueId(v) {
  if (isBlank(v)) return "z";
  return (typeof v === "number" ? "n" : "s") + v;
}

function condValue(v, col, cond) {
  // record_filter._condition_value: text operators read what is shown.
  return TEXT_OPS.indexOf(cond.op) >= 0 ? displayText(v, col) : v;
}

// record_filter.RecordFilter._condition_matches.
// record_filter._NEGATED_TEXT_OPS: kept only when the text does NOT match.
var NEGATED_TEXT_OPS = ["does not contain", "does not equal", "does not match pattern"];
function halfMatches(v, col, cond) {
  // record_filter._half_matches: a text operator also reads the other
  // spellings; a positive one keeps the row if ANY matches, a negated one
  // only if ALL do.
  var value = condValue(v, col, cond);
  if (TEXT_OPS.indexOf(cond.op) >= 0) {
    var others = otherSpellings(value);
    if (others.length) {
      var all = [value].concat(others);
      if (NEGATED_TEXT_OPS.indexOf(cond.op) >= 0) return all.every(function (s) { return cond.matches(s); });
      return all.some(function (s) { return cond.matches(s); });
    }
  }
  return cond.matches(value);
}
function condMatches(v, col, cond) {
  if (cond instanceof JoinedCondition) {
    return cond.matchesHalves(function (half) { return halfMatches(v, col, half); });
  }
  return halfMatches(v, col, cond);
}

function SegmentModel(seg) {
  this.seg = seg;
  this.cols = seg.cols;
  this.n = seg.rows.length;
  this.rawText = "";
  this.text = "";
  this.conditions = {};
  this.values = {};
  this.chips = {};
  // The Origin column's own filter: a Set of the words grid.originWord
  // paints (Live, Carved, Mixed, ...), or null when Origin is not filtered.
  this.origins = null;
  this.sortCol = seg.sort ? seg.sort[0] : null;
  this.sortDesc = seg.sort ? !!seg.sort[1] : false;
  this._hay = null;
  this._keys = {};
  this.colIndex = {};
  this.multi = {};
  for (var c = 0; c < this.cols.length; c++) {
    this.colIndex[this.cols[c].k] = c;
    if (this.cols[c].multi) this.multi[c] = true;
  }
  this._chipTests = (seg.quick || []).map(this._chipTest, this);
  this._order = null;
  if (this.sortCol !== null) this._sortFrom(null);
  this.visible = [];
  this.recompute();
}

SegmentModel.prototype._chipTest = function (q) {
  // A chip reads a shown column, or a row field the island carries for it
  // in seg.qv (one value per row) when the grid does not show that field.
  if (q.skipped) return null;
  if (q.twins) {
    // Applied after the other filters, over the rows they leave
    // (recompute); every row passes the per-row stage.
    if (!this.seg.tw) return null;
    var pass = function () { return true; };
    pass.twins = true;
    return pass;
  }
  var hidden = this.seg.qv && Object.prototype.hasOwnProperty.call(this.seg.qv, q.key) ? this.seg.qv[q.key] : null;
  var shown = Object.prototype.hasOwnProperty.call(this.colIndex, q.key);
  if (!shown && !hidden) return null;
  var c = shown ? this.colIndex[q.key] : -1, col = shown ? this.cols[c] : null;
  var get = shown ? function (row) { return row[c]; } : function (row, r) { return hidden[r]; };
  if (q.values) {
    var ids = new Set(q.values.map(valueId));
    return function (row, r) { return ids.has(valueId(get(row, r))); };
  }
  if (q.cond) {
    var cond = new Condition(q.cond[0], q.cond[1], q.cond[2]);
    return function (row, r) { return condMatches(get(row, r), col, cond); };
  }
  return null;
};

SegmentModel.prototype.multiValues = function (r, c) {
  // record_filter._multi_values: the loader's own pre-split list when the
  // column declared one (seg.mv), else the joined cell split on ", ". A
  // blank cell is ONE blank value, so "(blank)" stays pickable.
  var pre = this.seg.mv && this.seg.mv[String(c)];
  if (pre && pre[r] !== null && pre[r] !== undefined) return pre[r];
  var v = this.seg.rows[r][c];
  if (isBlank(v)) return [null];
  return String(pyText(v)).split(MULTI_SEPARATOR);
};

SegmentModel.prototype.haystack = function () {
  if (!this._hay) {
    var rows = this.seg.rows, cols = this.cols, hay = new Array(rows.length);
    for (var r = 0; r < rows.length; r++) {
      var parts = new Array(cols.length);
      for (var c = 0; c < cols.length; c++) parts[c] = searchText(rows[r][c], cols[c]);
      hay[r] = parts.join(SEP).toLowerCase();
    }
    this._hay = hay;
  }
  return this._hay;
};

SegmentModel.prototype.newest = function (c) {
  var best = null, rows = this.seg.rows;
  for (var r = 0; r < rows.length; r++) {
    var dt = parseDtValue(rows[r][c]);
    if (dt && (!best || dt.instant > best.instant)) best = dt;
  }
  return best;
};

SegmentModel.prototype.recompute = function () {
  // Filters walk the rows in the order the current sort put them, so a
  // filter never sorts: the sort runs once, when the sort itself changes.
  // A stable sort of a subset equals that subset of the stable sort.
  var text = this.text, hay = text ? this.haystack() : null, k;
  var conds = [];
  for (k in this.conditions) {
    var cond = this.conditions[k];
    var halves = cond.parts || [cond];
    for (var h = 0; h < halves.length; h++) {
      if (halves[h].op === "in the last N days") halves[h].anchor = this.newest(+k);
    }
    conds.push([+k, cond, this.cols[+k]]);
  }
  var vals = [];
  for (k in this.values) vals.push([+k, this.values[k], !!this.multi[+k]]);
  var chips = [];
  for (k in this.chips) if (this._chipTests[+k]) chips.push(this._chipTests[+k]);
  var rows = this.seg.rows, order = this.order(), out = [], origins = this.origins;
  var none = !hay && !conds.length && !vals.length && !chips.length && !origins;
  if (none) { this.twinsHidden = 0; this.visible = order ? order.slice() : rows.map(function (_r, i) { return i; }); return; }
  for (var p = 0; p < rows.length; p++) {
    var r = order ? order[p] : p;
    if (hay && hay[r].indexOf(text) < 0) continue;
    if (origins && !origins.has(originWord(this.seg, r))) continue;
    var row = rows[r], ok = true, i;
    for (i = 0; ok && i < vals.length; i++) {
      if (vals[i][2]) {
        // A multi-value cell passes when ANY of its values is allowed.
        var parts = this.multiValues(r, vals[i][0]), any = false;
        for (var j = 0; !any && j < parts.length; j++) any = vals[i][1].has(valueId(parts[j]));
        if (!any) ok = false;
      } else if (!vals[i][1].has(valueId(row[vals[i][0]]))) ok = false;
    }
    for (i = 0; ok && i < conds.length; i++) {
      if (!condMatches(row[conds[i][0]], conds[i][2], conds[i][1])) ok = false;
    }
    for (i = 0; ok && i < chips.length; i++) if (!chips[i](row, r)) ok = false;
    if (ok) out.push(r);
  }
  // "One row per visit": an MSHist row goes only while its History twin
  // is among the rows shown; filtered away, the MSHist row is that
  // visit's only record on screen and stays (record_chips.hide_shown_twins).
  this.twinsHidden = 0;
  if (chips.some(function (f) { return f.twins; })) {
    var tw = this.seg.tw, shown = new Set(), before = out.length;
    out.forEach(function (x) { if (tw[x][0]) shown.add(tw[x][0]); });
    out = out.filter(function (x) { return !(tw[x][1] && shown.has(tw[x][1])); });
    this.twinsHidden = before - out.length;
  }
  this.visible = out;
};

SegmentModel.prototype.order = function () {
  // Every row, in the order the sorts so far put them; null when no sort
  // is in force (loader order).
  return this.sortCol === null || this.sortCol === undefined ? null : this._order;
};

SegmentModel.prototype._sortFrom = function (prev) {
  // record_filter.RecordFilter.sort: a STABLE sort of the order shown just
  // before it (the default sort first, then loader order), so ties keep
  // that order and keep it across later filter changes. Numbers, then
  // other values, then blanks -- blanks last in BOTH directions.
  var c = this.sortCol, rows = this.seg.rows, col = this.cols[c];
  var source = this.seg.sortv && this.seg.sortv[String(c)];
  var keys = this._keys[c];
  if (!keys) {
    keys = new Array(rows.length);
    for (var r = 0; r < rows.length; r++) keys[r] = sortKey(source ? source[r] : rows[r][c], source ? null : col);
    this._keys[c] = keys;
  }
  var numeric = [], other = [], blank = [];
  for (var p = 0; p < rows.length; p++) {
    var i = prev ? prev[p] : p, group = keys[i][0];
    (group === 1 ? numeric : group === 2 ? other : blank).push(i);
  }
  var up = function (x, y) { return cmpKey(keys[x], keys[y]); };
  var down = function (x, y) { return cmpKey(keys[y], keys[x]); };
  numeric.sort(this.sortDesc ? down : up);
  other.sort(this.sortDesc ? down : up);
  this._order = numeric.concat(other, blank);
};

SegmentModel.prototype.setText = function (t) {
  this.rawText = t || "";
  this.text = this.rawText.trim().toLowerCase();
  this.recompute();
};
SegmentModel.prototype.setCondition = function (c, cond) {
  if (cond) this.conditions[c] = cond; else delete this.conditions[c];
  this.recompute();
};
SegmentModel.prototype.setValues = function (c, ids) {
  if (ids) this.values[c] = ids; else delete this.values[c];
  this.recompute();
};
SegmentModel.prototype.setSort = function (c, desc) {
  var prev = this.order();
  this.sortCol = c;
  this.sortDesc = !!desc;
  this._sortFrom(prev);
  this.recompute();
};
SegmentModel.prototype.chipUsable = function (i) { return !!this._chipTests[i]; };

SegmentModel.prototype.chipCount = function (i) {
  // How many of the segment's rows chip i keeps on its own.
  var test = this._chipTests[i], rows = this.seg.rows, n = 0;
  if (!test || test.twins) return 0;
  for (var r = 0; r < rows.length; r++) if (test(rows[r], r)) n++;
  return n;
};
SegmentModel.prototype.toggleChip = function (i) {
  if (this.chips[i]) delete this.chips[i];
  else if (this._chipTests[i]) {
    // Chips in one group are exclusive, as the app's QButtonGroup is
    // (Deleted Records' method chips): ticking one unticks the others.
    var quick = this.seg.quick || [], group = quick[i] && quick[i].group;
    if (group) {
      for (var k in this.chips) if (quick[+k] && quick[+k].group === group) delete this.chips[k];
    }
    this.chips[i] = true;
  }
  this.recompute();
};
SegmentModel.prototype.hasFilterOn = function (c) {
  return Object.prototype.hasOwnProperty.call(this.conditions, c) ||
         Object.prototype.hasOwnProperty.call(this.values, c);
};
SegmentModel.prototype.originCounts = function () {
  // record_model.origin_counts: every origin word over EVERY row, in the
  // order the words first appear, whatever is filtered now.
  var counts = {}, order = [];
  for (var r = 0; r < this.seg.rows.length; r++) {
    var w = originWord(this.seg, r);
    if (!counts[w]) { counts[w] = {w: w, n: 0}; order.push(counts[w]); }
    counts[w].n++;
  }
  return order;
};
SegmentModel.prototype.setOrigins = function (kept) {
  this.origins = kept;
  this.recompute();
};
SegmentModel.prototype.clearAll = function () {
  this.rawText = ""; this.text = "";
  this.conditions = {}; this.values = {}; this.chips = {}; this.origins = null;
  this.recompute();
};
SegmentModel.prototype.valueCounts = function (c) {
  // record_filter.value_counts: every distinct value, no cap, in sort order.
  // A multi column: every individual value, and how many rows CONTAIN it.
  var counts = {}, order = [], rows = this.seg.rows, col = this.cols[c], multi = !!this.multi[c];
  function add(v, id) {
    if (!counts[id]) { counts[id] = {id: id, v: isBlank(v) ? null : v, n: 0}; order.push(counts[id]); }
    counts[id].n++;
  }
  for (var r = 0; r < rows.length; r++) {
    if (!multi) { add(rows[r][c], valueId(rows[r][c])); continue; }
    var seen = {}, parts = this.multiValues(r, c);
    for (var p = 0; p < parts.length; p++) {
      var id = valueId(parts[p]);
      if (!seen[id]) { seen[id] = true; add(parts[p], id); }
    }
  }
  order.forEach(function (x) {
    x.label = isBlank(x.v) ? blankLabel(col) : displayText(x.v, col);
    x.key = sortKey(x.v, col);
  });
  order.sort(function (x, y) { return x.key[0] !== y.key[0] ? x.key[0] - y.key[0] : cmpKey(x.key, y.key); });
  return order;
};
SegmentModel.prototype.describe = function () {
  var self = this, out = [];
  if (this.text) {
    out.push({text: "Text contains \u201c" + this.rawText.trim() + "\u201d", isText: true,
              clear: function () { self.setText(""); }});
  }
  Object.keys(this.conditions).forEach(function (k) {
    var col = self.cols[+k];
    out.push({text: col.l + " " + self.conditions[k].describe(col),
              clear: function () { self.setCondition(+k, null); }});
  });
  Object.keys(this.values).forEach(function (k) {
    // record_filter.chip_text, in the column's label and the grid's words.
    var ids = self.values[k], label = self.cols[+k].l, text;
    var counts = self.valueCounts(+k);
    if (!ids.size) text = label + ": no values selected (matches nothing)";
    else if (ids.size <= CHIP_VALUES_NAMED) {
      var named = counts.filter(function (x) { return ids.has(x.id); }).map(function (x) { return x.label; });
      named.sort(function (a, b) { return a < b ? -1 : a > b ? 1 : 0; });
      text = label + ": Is " + named.join(" or ");
    } else text = label + ": " + ids.size + " of " + counts.length + " values";
    out.push({text: text, clear: function () { self.setValues(+k, null); }});
  });
  if (this.origins) {
    var named = this.originCounts().filter(function (x) { return self.origins.has(x.w); })
      .map(function (x) { return x.w; });
    out.push({text: named.length ? "Origin: Is " + named.join(" or ")
                                 : "Origin: none selected (matches nothing)",
              clear: function () { self.setOrigins(null); }});
  }
  Object.keys(this.chips).forEach(function (k) {
    var q = self.seg.quick[+k];
    out.push({text: q.sentence || q.label, clear: function () { self.toggleChip(+k); }});
  });
  return out;
};

API.condition = function (op, a, b) { return new Condition(op, a, b); };
API.joined = function (first, join, second) { return new JoinedCondition(first, join, second); };
