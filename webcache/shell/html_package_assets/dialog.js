// The record dialog. First who the record is, what it is, and where a
// carved one came from. Then this view's own columns. Then every
// canonical field -- each time beside its stored FILETIME -- or a non-URL
// record's own fields. Then an aggregate's members, each of which opens
// its own dialog. Nothing here is a link; everything has Copy.
// A row's header is DATA.heads[seg.hd[r]]; a member's is DATA.heads[rec.mh].

var MEMBER_PAGE = 500;
var TIME_FIELDS = [
  ["CreationTime", "CreationTime_rfc", "CreationTime_raw"],
  ["ModifiedTime", "ModifiedTime_rfc", "ModifiedTime_raw", "ModifiedTimeLocal"],
  ["AccessedTime", "AccessedTime_rfc", "AccessedTime_raw"],
  ["ExpiryTime", "ExpiryTime_rfc", "ExpiryTime_raw"],
  ["SyncTime", "SyncTime_rfc", "SyncTime_raw"],
  ["PostCheckTime", "PostCheckTime_raw"],
  ["SPS_LastVisitLocal", "SPS_LastVisitLocal_raw"]
];
var FIELD_AT = null;

function fieldAt() {
  if (!FIELD_AT) {
    FIELD_AT = {};
    DATA.fields.forEach(function (f, i) { FIELD_AT[f[0]] = i; });
  }
  return FIELD_AT;
}

function KV(lines) {
  this.node = el("div", "kv");
  this.lines = lines;
}
KV.prototype.add = function (label, shown, stored) {
  var blank = isBlank(shown), value = blank ? "" : String(shown);
  var copied = isBlank(stored) ? value : String(stored);
  this.node.appendChild(el("div", "k", label));
  var v = el("div", "v" + (blank ? " blank" : ""), blank ? "(empty)" : value);
  if (!isBlank(stored) && String(stored) !== value) v.appendChild(el("span", "stored", "stored: " + stored));
  this.node.appendChild(v);
  var c = el("div");
  // "Copy" copies what is shown; where the stored value
  // differs, "Copy stored" copies that. "Copy all" keeps the stored value.
  if (!blank) {
    c.appendChild(copyButton(value));
    if (copied !== value) c.appendChild(copyButton(copied, "Copy stored"));
  }
  this.node.appendChild(c);
  this.lines.push(label + "\t" + (blank ? "" : copied));
};
KV.prototype.addParts = function (label, parts) {
  this.node.appendChild(el("div", "k", label));
  var v = el("div", "v"), copied = [];
  parts.forEach(function (p, i) {
    if (i) v.appendChild(document.createTextNode("   │   "));
    // a part names only what differs from the field's own
    // name ("AccessedTime (UTC)" under AccessedTime reads "UTC"), and a
    // part never breaks inside its label; "Copy" keeps the full names.
    var short = p[0];
    if (short.indexOf(label) === 0) short = short.slice(label.length).trim().replace(/^\((.*)\)$/, "$1") || p[0];
    var part = el("span", "part");
    part.appendChild(document.createTextNode(short + ": "));
    part.appendChild(el("span", isBlank(p[1]) ? "blank" : "", isBlank(p[1]) ? "(empty)" : p[1]));
    v.appendChild(part);
    copied.push(p[0] + ": " + (isBlank(p[1]) ? "" : p[1]));
  });
  this.node.appendChild(v);
  var c = el("div");
  c.appendChild(copyButton(copied.join("\n")));
  this.node.appendChild(c);
  this.lines.push(label + "\t" + copied.join("; "));
};

// The app's dialog puts a chip above a recovered record's title: a stub
// (the b-tree key survived, no row bytes) is not "carved", and says so.
// What a record is comes from the head's kind (set when the island is
// built), never from the words of its title or strip.
var CHIPS = {stub: "DELETED-RECORD STUB", carved: "CARVED RECORD"};

function kindChip(head, hd) {
  var text = hd ? CHIPS[hd.k] : "";
  if (!text) return "";
  head.insertBefore(el("span", "chip-kind", text), head.firstChild);
  return text;
}

function headLines(head, hd, fallback, lines) {
  if (!hd) { if (fallback) head.appendChild(el("div", "note", fallback)); return; }
  if (hd.o) { head.appendChild(el("div", "note", hd.o)); lines.push(hd.o); }
  if (hd.t) { head.appendChild(el("div", "note", hd.t)); lines.push(hd.t); }
  if (hd.p && hd.p.length) {
    var strip = el("div", "strip");
    hd.p.forEach(function (fact) {
      strip.appendChild(el("span", null, fact[0] + ": " + fact[1]));
      lines.push(fact[0] + "\t" + fact[1]);
    });
    head.appendChild(strip);
  }
}

// A blank canonical cell says what the app's own dialog says for it: the
// island carries that word (rec.a) for every field the dialog words; a
// field the dialog does not show at all reads DATA.na.
function absent(rec, i) { return (rec.a && rec.a[i]) || DATA.na; }

function canonicalSection(body, rec, lines) {
  var at = fieldAt(), cells = rec.c, used = {};
  body.appendChild(el("h3", null, "Canonical record — all " + DATA.fields.length +
    " fields every export carries; each time beside its stored FILETIME"));
  var when = new KV(lines);
  TIME_FIELDS.forEach(function (keys) {
    var head = keys[0], first = at[head];
    var parts = keys.filter(function (k) { return Object.prototype.hasOwnProperty.call(at, k); })
      .map(function (k) {
        used[k] = true;
        var i = at[k], v = pyText(cells[i]);
        // A time's RFC 3339 and FILETIME parts share its UTC part's absence.
        if (isBlank(v)) v = absent(rec, k === head || first === undefined ? i : first);
        return [DATA.fields[i][1], v];
      });
    if (parts.length) when.addParts(keys[0], parts);
  });
  body.appendChild(when.node);
  var group = null, kv = null;
  DATA.fields.forEach(function (f, i) {
    if (used[f[0]]) return;
    if (f[2] !== group) {
      group = f[2];
      body.appendChild(el("h3", null, group));
      kv = new KV(lines);
      body.appendChild(kv.node);
    }
    var v = pyText(cells[i]);
    kv.add(f[1], isBlank(v) ? absent(rec, i) : v);
  });
}

function ownSection(body, rec, lines) {
  body.appendChild(el("h3", null, "This record's own fields — every key it carries"));
  var kv = new KV(lines);
  Object.keys(rec.own).forEach(function (key) { kv.add(key, pyText(rec.own[key])); });
  body.appendChild(kv.node);
}

function membersSection(body, ids, noun) {
  var cols = DATA.member_cols || [];
  // A place's members are position fixes, each shown by its record.
  body.appendChild(el("h3", null, "Members — " + fmtCount(ids.length) + " " +
    (noun ? plural(ids.length, noun[0], noun[1]) + ", each shown by the record it was read from"
          : plural(ids.length, "record", "records"))));
  var table = el("table", "plain members"), head = el("tr");
  head.appendChild(el("th", null, ""));
  cols.forEach(function (c) { head.appendChild(el("th", null, c.l)); });
  table.appendChild(head);
  body.appendChild(table);
  var more = el("button", null, ""), shown = 0;
  function memberRow(i) {
    var rec = DATA.records[i], tr = el("tr"), td = el("td"), open = el("button", null, "Open");
    open.addEventListener("click", function () { openMember(i); });
    td.appendChild(open);
    tr.appendChild(td);
    cols.forEach(function (c, k) { tr.appendChild(el("td", c.kind === "url" ? "url" : null, displayText(rec.m ? rec.m[k] : null, c))); });
    return tr;
  }
  function nextPage() {
    var stop = Math.min(ids.length, shown + MEMBER_PAGE);
    for (; shown < stop; shown++) table.appendChild(memberRow(ids[shown]));
    var left = ids.length - shown;
    more.hidden = left <= 0;
    more.textContent = "Show the next " + fmtCount(Math.min(MEMBER_PAGE, left)) + " (" + fmtCount(left) + " not yet listed)";
  }
  more.addEventListener("click", nextPage);
  body.appendChild(more);
  nextPage();
}

function copyAllButton(lines) {
  var b = el("button", null, "Copy all (tab-separated)");
  b.addEventListener("click", function () { copyText(lines.join("\n")); });
  return b;
}

function openRecordDialog(view, seg, r) {
  var index = seg.rec[r], rec = index >= 0 ? DATA.records[index] : null, row = seg.rows[r];
  var hd = seg.hd && seg.hd[r] >= 0 ? DATA.heads[seg.hd[r]] : null;
  var title = hd && hd.i ? hd.i
    : (seg.cols.length ? seg.cols[0].l + ": " + displayText(row[0], seg.cols[0]) : seg.label);
  var lines = [title];
  openModal(title, function (body, head) {
    var chip = kindChip(head, hd);
    if (chip) lines.splice(1, 0, chip);
    headLines(head, hd, seg.origins[seg.org[r]], lines);
    body.appendChild(el("h3", null, "In " + view.label + " › " + seg.label));
    var here = new KV(lines);
    seg.cols.forEach(function (col, c) { here.add(col.l, displayText(row[c], col), pyText(row[c])); });
    // The export's appended columns, named for people; the source file is
    // said only where there is one (a live record has none).
    (seg["export"].appended || []).forEach(function (name, k) {
      var value = row[seg.n + k];
      if (name === "RecordSource") {
        if (value === null || value === undefined || value === "") return;
        name = "Carved from";
      }
      here.add(name, pyText(value));
    });
    body.appendChild(here.node);
    if (rec && rec.c) canonicalSection(body, rec, lines);
    if (rec && rec.own) ownSection(body, rec, lines);
    if (seg.mem && seg.mem[r]) membersSection(body, seg.mem[r], seg.mn);
  }, [copyAllButton(lines)]);
}

function openMember(index) {
  var rec = DATA.records[index];
  var hd = rec.mh !== undefined && rec.mh >= 0 ? DATA.heads[rec.mh] : null;
  var title = hd && hd.i ? hd.i : "Member record", lines = [title];
  openModal(title, function (body, head) {
    var chip = kindChip(head, hd);
    if (chip) lines.splice(1, 0, chip);
    headLines(head, hd, "", lines);
    if (rec.m) {
      body.appendChild(el("h3", null, "As a member row"));
      var kv = new KV(lines);
      (DATA.member_cols || []).forEach(function (c, k) { kv.add(c.l, displayText(rec.m[k], c), pyText(rec.m[k])); });
      body.appendChild(kv.node);
    }
    if (rec.c) canonicalSection(body, rec, lines);
    if (rec.own) ownSection(body, rec, lines);
  }, [copyAllButton(lines)]);
}

RENDERERS.record = openRecordDialog;
API.openRecord = function (viewKey, segKey, r) {
  var found = findSegment(viewKey, segKey);
  openRecordDialog(found.view, found.seg, r);
};
API.openMember = function (index) { openMember(index); };
