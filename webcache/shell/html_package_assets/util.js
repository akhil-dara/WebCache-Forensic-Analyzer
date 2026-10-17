// Shared helpers and copies of the app's display rules. Evidence
// reaches the DOM ONLY through textContent (el()), document.title or an
// element's title; nothing in this page builds markup from a string, and
// tests/test_html_package_page.py fails the build if anything tries.

var TAG_DT = "\u0001";      // html_package.TAG_DATETIME
var TAG_BIG = "\u0002";     // html_package.TAG_BIGINT
var TAG_FLOAT = "\u0003";   // html_package.TAG_FLOAT
var SEP = "\u0000";         // column_spec.SEARCH_SEP
var LINE_CAP = 6;           // records_table.ROW_LINE_CAP
var MORE_MARKER = "\u25be +%s more lines";          // records_table.MORE_MARKER
var CARVED_ORIGIN = "Carved (deleted/unflushed)";   // provenance.CARVED_ORIGIN
var LIVE_CELL = "Live record";                      // export_formats._LIVE_CELL
var API = {};

function el(tag, cls, text) {
  var node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function isBlank(v) {
  return v === null || v === undefined || v === "";
}

function groupDigits(digits) {
  var sign = "";
  if (digits.charAt(0) === "-") { sign = "-"; digits = digits.slice(1); }
  var out = "";
  while (digits.length > 3) {
    out = "," + digits.slice(-3) + out;
    digits = digits.slice(0, -3);
  }
  return sign + digits + out;
}

function groupFloat(text) {
  // Python's "{:,}".format(float): the integer part grouped, the rest kept.
  if (/[eEni]/.test(text)) return text;
  var dot = text.indexOf(".");
  return dot < 0 ? groupDigits(text) : groupDigits(text.slice(0, dot)) + text.slice(dot);
}

function fmtCount(n) { return groupDigits(String(n)); }

function plural(n, one, many) { return n === 1 ? one : many; }

function hexOffset(digits) {
  // Python "0x%08X" % value: the sign counts toward the width.
  var negative = digits.charAt(0) === "-";
  var hex = BigInt(negative ? digits.slice(1) : digits).toString(16).toUpperCase();
  var width = negative ? 7 : 8;
  while (hex.length < width) hex = "0" + hex;
  return "0x" + (negative ? "-" : "") + hex;
}

function pyText(v) {
  // Exactly what the app's CSV writes for this stored cell.
  if (isBlank(v)) return "";
  if (typeof v === "number") return String(v);
  var tag = v.charAt(0);
  if (tag === TAG_DT || tag === TAG_BIG || tag === TAG_FLOAT) return v.slice(1);
  return v;
}

function displayText(v, col) {
  // column_spec.display_text, on the stored cell.
  if (isBlank(v)) return "";
  var kind = col ? col.kind : null;
  var numeric = !!(col && col.num);
  if (typeof v === "number") {
    if (kind === "offset") return hexOffset(String(v));
    return numeric ? groupDigits(String(v)) : String(v);
  }
  var tag = v.charAt(0);
  if (tag === TAG_DT) return v.slice(1, 20);
  if (tag === TAG_BIG) {
    var digits = v.slice(1);
    if (kind === "offset") return hexOffset(digits);
    return numeric ? groupDigits(digits) : digits;
  }
  if (tag === TAG_FLOAT) {
    var f = v.slice(1);
    return numeric ? groupFloat(f) : f;
  }
  return v;
}

function percentDecode(text) {
  // urllib.parse.unquote: %XX runs decoded as UTF-8, a bad byte as U+FFFD.
  return text.replace(/(?:%[0-9A-Fa-f]{2})+/g, function (run) {
    var bytes = run.match(/%[0-9A-Fa-f]{2}/g).map(function (h) { return parseInt(h.slice(1), 16); });
    return new TextDecoder("utf-8").decode(new Uint8Array(bytes));
  });
}

function otherSpellings(text) {
  // webcache/spellings.other_spellings: decoded (a '+' read as a space only
  // in the query), and a file: URL's Windows path. Never `text` itself.
  if (typeof text !== "string" || !text) return [];
  var isFile = text.slice(0, 5).toLowerCase() === "file:";
  if (text.indexOf("%") < 0 && text.indexOf("+") < 0 && !isFile) return [];
  var out = [];
  var q = text.indexOf("?");
  var head = q < 0 ? text : text.slice(0, q), query = q < 0 ? "" : text.slice(q + 1);
  if (/%[0-9A-Fa-f]{2}/.test(text) || query.indexOf("+") >= 0) {
    var decoded = percentDecode(head) + (q < 0 ? "" : "?" + percentDecode(query.replace(/\+/g, " ")));
    if (decoded !== text) out.push(decoded);
  }
  if (isFile) {
    var rest = text.slice(5).split("?")[0].split("#")[0], path = null;
    if (rest.slice(0, 3) === "///") path = rest.slice(3);
    else if (rest.slice(0, 2) === "//") path = "//" + rest.slice(2);
    if (path !== null) {
      path = percentDecode(path).replace(/\//g, "\\");
      if (path !== text && out.indexOf(path) < 0) out.push(path);
    }
  }
  return out;
}

function searchText(v, col) {
  // column_spec.searchable_text: what is shown, plus a number's plain digits,
  // plus a value's other spellings (decoded, Windows path).
  var text = displayText(v, col);
  if (col && col.num && col.kind !== "offset" && !isBlank(v)) {
    if (typeof v === "number") return text + SEP + String(v);
    var tag = v.charAt(0);
    if (tag === TAG_BIG || tag === TAG_FLOAT) return text + SEP + v.slice(1);
  }
  var others = otherSpellings(text);
  return others.length ? [text].concat(others).join(SEP) : text;
}

function wallSeconds(y, mo, d, h, mi, s) {
  var t = new Date(0);
  t.setUTCFullYear(y, mo - 1, d);
  t.setUTCHours(h, mi, s, 0);
  return t.getTime() / 1000;
}

function makeDt(y, mo, d, h, mi, s, us, offset) {
  var wall = wallSeconds(y, mo, d, h, mi, s) + us / 1e6;
  return {y: y, mo: mo, d: d, h: h, mi: mi, s: s, us: us, wall: wall,
          offset: offset, instant: wall - (offset || 0)};
}

var TAGGED_DT_RE = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:([+-])(\d{2}):(\d{2})(?::(\d{2}))?)?$/;

function parseTaggedDt(v) {
  // str(datetime): "YYYY-MM-DD HH:MM:SS[.ffffff][+HH:MM]". Naive: offset null.
  var m = TAGGED_DT_RE.exec(v.slice(1));
  if (!m) return null;
  var us = m[7] ? Number((m[7] + "00000").slice(0, 6)) : 0;
  var offset = null;
  if (m[8]) offset = (m[8] === "-" ? -1 : 1) * (Number(m[9]) * 3600 + Number(m[10]) * 60 + Number(m[11] || 0));
  return makeDt(+m[1], +m[2], +m[3], +m[4], +m[5], +m[6], us, offset);
}

function sortKey(v, col) {
  // record_filter._sort_key: [rank, number, text]; blanks rank 3, last.
  if (isBlank(v)) return [3, 0, ""];
  if (typeof v === "number") return [1, v, ""];
  if (col && col.kind === "flag" && (v === "Yes" || v === "No")) return [1, v === "Yes" ? 1 : 0, ""];
  var tag = v.charAt(0);
  if (tag === TAG_BIG || tag === TAG_FLOAT) return [1, Number(v.slice(1)), ""];
  if (tag === TAG_DT) {
    var dt = parseTaggedDt(v);
    return dt ? [2, dt.instant, ""] : [2, 0, naturalKey(v.slice(1))];
  }
  return [2, 0, naturalKey(v)];
}

function naturalKey(text) {
  // record_filter.natural_key, exactly: each digit run as its 4-digit
  // length then its digits without leading zeros, so "file2" sorts before
  // "file10"; the lower-cased text after a NUL breaks ties.
  var lower = String(text).toLowerCase();
  return lower.replace(/\d+/g, function (d) {
    var digits = d.replace(/^0+/, "") || "0";
    var len = String(digits.length);
    while (len.length < 4) len = "0" + len;
    return "0" + len + digits;
  }) + "\u0000" + lower;
}

function cmpKey(a, b) {
  if (a[1] !== b[1]) return a[1] < b[1] ? -1 : 1;
  if (a[2] !== b[2]) return a[2] < b[2] ? -1 : 1;
  return 0;
}

function baseName(path) {
  var parts = String(path || "").split(/[\\/]/);
  return parts[parts.length - 1];
}

function loadSetting(key, fallback) {
  try { var v = window.localStorage.getItem(key); return v === null ? fallback : v; }
  catch (e) { return fallback; }
}

function saveSetting(key, value) {
  try { window.localStorage.setItem(key, value); } catch (e) { /* refused: it is a preference only */ }
}

var TOAST_TIMER = null;

function toast(text, extra) {
  var old = document.getElementById("wc-toast");
  if (old) old.parentNode.removeChild(old);
  var box = el("div", "toast");
  box.id = "wc-toast";
  box.setAttribute("role", "status");
  box.appendChild(el("span", null, text));
  function dismiss() { if (box.parentNode) box.parentNode.removeChild(box); }
  if (extra) {
    box.appendChild(extra);
    // Once its one action is used, the toast has said all it has to say.
    extra.addEventListener("click", function () { setTimeout(dismiss, 0); });
  }
  var close = el("button", null, "\u2715");
  close.title = "Dismiss";
  close.addEventListener("click", dismiss);
  box.appendChild(close);
  // Over an open dialog it sits at the top, never over the dialog's buttons
  // 
  if (MODALS.length) box.classList.add("over-modal");
  document.body.appendChild(box);
  if (TOAST_TIMER) clearTimeout(TOAST_TIMER);
  TOAST_TIMER = setTimeout(dismiss, extra ? 20000 : 4000);
}

function copyFallback(text) {
  var area = el("textarea");
  area.value = text;
  document.body.appendChild(area);
  area.select();
  var ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  document.body.removeChild(area);
  toast(ok ? "Copied " + fmtCount(text.length) + " characters."
           : "This browser refused to copy. Select the text and press Ctrl+C.");
}

function copyText(text) {
  text = isBlank(text) ? "" : String(text);
  if (navigator.clipboard && window.isSecureContext) {
    // A clipboard request can stay pending (no focus, a permission prompt):
    // after a second the fallback answers instead, so a click always says
    // whether it copied.
    var settled = false;
    navigator.clipboard.writeText(text).then(function () {
      if (settled) return;
      settled = true;
      toast("Copied " + fmtCount(text.length) + " characters.");
    }, function () {
      if (settled) return;
      settled = true;
      copyFallback(text);
    });
    setTimeout(function () { if (!settled) { settled = true; copyFallback(text); } }, 1000);
    return;
  }
  copyFallback(text);
}

function copyButton(value, label) {
  var b = el("button", "copy", label || "Copy");
  b.title = "Copy this value. Nothing is opened.";
  b.addEventListener("click", function (ev) {
    ev.stopPropagation();
    copyText(typeof value === "function" ? value() : value);
  });
  return b;
}

function saveBlob(name, blob) {
  // The ONE anchor this page ever creates: detached, a blob: URL, never in
  // the document. Nothing else in the page links anywhere.
  var a = document.createElement("a");
  a.download = name;
  a.href = URL.createObjectURL(blob);
  a.click();
  setTimeout(function () { URL.revokeObjectURL(a.href); }, 60000);
}

function safeFileName(text) {
  return String(text).replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "") || "export";
}

var MODALS = [];
var FOCUSABLE = 'button, input, select, [tabindex]:not([tabindex="-1"])';

function focusables(box) {
  return Array.prototype.filter.call(box.querySelectorAll(FOCUSABLE), function (n) {
    return !n.disabled && !n.hidden && n.offsetParent !== null;
  });
}

function giveFocusBack(node) {
  // To the control that opened a dialog or popup; when that control was
  // rebuilt meanwhile, to the grid, so the arrow keys keep working.
  var target = node && node.isConnected ? node : document.getElementById("wc-grid");
  if (target && typeof target.focus === "function") target.focus();
}

function openModal(title, build, buttons) {
  var opener = document.activeElement;
  var shade = el("div", "modal");
  var box = el("div", "dialog");
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  var head = el("div", "dhead"), body = el("div", "dbody"), foot = el("div", "dfoot");
  head.appendChild(el("h2", null, title));
  box.appendChild(head); box.appendChild(body); box.appendChild(foot);
  shade.appendChild(box);
  function close() {
    if (!shade.parentNode) return;
    shade.parentNode.removeChild(shade);
    var at = MODALS.indexOf(close);
    if (at >= 0) MODALS.splice(at, 1);
    // Stacked dialogs hand the keyboard back one level at a time.
    giveFocusBack(opener);
  }
  shade.addEventListener("keydown", function (ev) {
    // Tab and Shift+Tab go round this dialog's own controls, never out to
    // the page behind the shade.
    if (ev.key !== "Tab") return;
    var all = focusables(box);
    if (!all.length) { ev.preventDefault(); return; }
    var first = all[0], last = all[all.length - 1], at = all.indexOf(document.activeElement);
    if (ev.shiftKey && (at <= 0)) { ev.preventDefault(); last.focus(); }
    else if (!ev.shiftKey && (at < 0 || at === all.length - 1)) { ev.preventDefault(); first.focus(); }
  });
  (buttons || []).forEach(function (b) { foot.appendChild(b); });
  var closeButton = el("button", null, "Close");
  closeButton.addEventListener("click", close);
  foot.appendChild(closeButton);
  shade.addEventListener("mousedown", function (ev) { if (ev.target === shade) close(); });
  MODALS.push(close);
  document.body.appendChild(shade);
  build(body, head, close);
  closeButton.focus();
  return {close: close, body: body, head: head};
}

function showWhole(title, text) {
  text = isBlank(text) ? "" : String(text);
  var lines = text ? text.split("\n").length : 0;
  openModal(title, function (body, head) {
    head.appendChild(el("div", "note", fmtCount(text.length) + " characters, " + fmtCount(lines) +
      " " + plural(lines, "line", "lines") + ". The whole value, as stored."));
    body.appendChild(el("pre", "whole", text));
  }, [copyButton(text, "Copy value")]);
}

var POPOVER = null;

function closePopover() {
  if (!POPOVER) return;
  var p = POPOVER;
  POPOVER = null;
  document.removeEventListener("mousedown", p.outside, true);
  var inside = p.node.contains(document.activeElement);
  if (p.node.parentNode) p.node.parentNode.removeChild(p.node);
  // Back to the button that opened it, when the keyboard was inside it.
  if (inside || document.activeElement === document.body) giveFocusBack(p.anchor);
}

function openPopover(anchor, build) {
  closePopover();
  var node = el("div", "popup");
  node.setAttribute("role", "dialog");
  document.body.appendChild(node);
  build(node, closePopover);
  var r = anchor.getBoundingClientRect();
  node.style.left = Math.max(8, Math.min(r.left, window.innerWidth - node.offsetWidth - 8)) + "px";
  var top = r.bottom + 4;
  if (top + node.offsetHeight > window.innerHeight - 8) top = Math.max(8, r.top - node.offsetHeight - 4);
  node.style.top = top + "px";
  var outside = function (ev) { if (!node.contains(ev.target) && ev.target !== anchor) closePopover(); };
  document.addEventListener("mousedown", outside, true);
  POPOVER = {node: node, outside: outside, anchor: anchor};
  return node;
}

function isTyping(target) {
  return !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT");
}

document.addEventListener("keydown", function (ev) {
  if (ev.key === "Escape") {
    if (POPOVER) { closePopover(); ev.preventDefault(); return; }
    if (MODALS.length) { MODALS[MODALS.length - 1](); ev.preventDefault(); }
    return;
  }
  if (ev.key === "/" && !isTyping(ev.target) && !MODALS.length) {
    var box = document.getElementById("wc-filter");
    if (box) { ev.preventDefault(); box.focus(); }
  }
});

API.displayText = displayText;
API.searchText = searchText;
API.sortKey = sortKey;
API.pyText = pyText;
