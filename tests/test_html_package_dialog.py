"""The record dialog."""
from webcache.engine import forensic_engine
from webcache.shell import detail_fields
from webcache.shell.html_package import PackageColumn
from webcache.shell.record_kinds import K_COOKIE, K_PERIOD, K_TOMBSTONE
from webcache.views.records_view import member_record_columns

from tests import _package_fixtures as fx

DIALOG_TEXT = "document.querySelectorAll('.dialog')[%d].textContent"


def _open_row(browser, tmp_path, rows, **kw):
    browser.open(fx.write(tmp_path, fx.snapshot(
        views=[fx.history_view([fx.segment(rows=rows, **kw)])])))
    browser.evaluate("WC.openRecord('history', 'history', 0)")


def test_a_live_record_shows_who_it_is_and_every_canonical_field(browser,
                                                                 tmp_path):
    row = fx.history_row(2)
    _open_row(browser, tmp_path, [row])
    assert browser.evaluate("document.querySelector('.dialog h2').textContent"
                            ) == detail_fields.identity_of(row)
    text = browser.evaluate(DIALOG_TEXT % 0)
    assert detail_fields.origin_line(row) in text
    assert "In History \u203a History" in text
    for _key, header, _group in forensic_engine.ENTRY_FIELDS:
        # A time's parts sit under its own name with short labels
        # ("UTC", "RFC3339", "FILETIME").
        base, _sep, rest = header.partition(" (")
        timed = base in ("AccessedTime", "ModifiedTime", "CreationTime",
                         "ExpiryTime", "SyncTime", "PostCheckTime")
        shown = (rest.rstrip(")") + ": ") if (rest and timed) else header
        assert shown in text, header
    assert browser.evaluate("document.querySelectorAll('a').length") == 0


def test_each_time_sits_beside_its_stored_filetime(browser, tmp_path):
    _open_row(browser, tmp_path, [fx.history_row(2)])
    line = browser.evaluate(
        "(function () { var k = Array.from(document.querySelectorAll("
        "'.dialog .kv .k')).filter(function (n) { return n.textContent ==="
        " 'AccessedTime'; })[0]; return k.nextElementSibling.textContent; })()")
    # each part names only what differs from the field's
    # own name, and never breaks inside its label.
    assert "UTC: " in line and "RFC3339: " in line
    assert "FILETIME: %d" % (133500000000000000 + 2 * 10_000_000) in line
    assert "AccessedTime (UTC)" not in line
    assert browser.evaluate(
        "(function () { var k = Array.from(document.querySelectorAll("
        "'.dialog .kv .k')).filter(function (n) { return n.textContent ==="
        " 'AccessedTime'; })[0]; return Array.from(k.nextElementSibling"
        ".querySelectorAll('.part')).every(function (s) {"
        " return getComputedStyle(s).whiteSpace === 'nowrap'; }); })()")


def test_a_carved_record_leads_with_where_it_was_carved_from(browser,
                                                             tmp_path):
    _open_row(browser, tmp_path, [fx.history_row(4, carved=True)])
    strip = browser.evaluate("Array.from(document.querySelectorAll("
                             "'.dialog .strip span')).map(function (s) {"
                             " return s.textContent; })")
    assert "Carved from: WebCacheV01.dat" in strip
    assert "Offset: 0x%08X" % (0x3B0523 + 4) in strip
    assert "Method: unallocated" in strip and "Confidence: high" in strip


def test_a_cookie_shows_its_own_complete_field_set(browser, tmp_path):
    cookie = {"Name": "sid", "Domain": "example.test", "Value": "v1",
              "Expires_raw": 133500000000000000}
    row = {"Name": "sid", "Domain": "example.test", "Origin": "Live record",
           "_kind": K_COOKIE, "_record": cookie}
    cols = [PackageColumn("Name", "Cookie"), PackageColumn("Domain", "Domain")]
    _open_row(browser, tmp_path, [row], columns=cols)
    text = browser.evaluate(DIALOG_TEXT % 0)
    assert "Expires_raw" in text and "133500000000000000" in text
    assert "Canonical record" not in text


def test_an_aggregate_lists_its_members_and_each_opens_its_own_dialog(
        browser, tmp_path):
    members = [fx.entry(1), fx.entry(2, RecoverySource="log")]
    row = {"Period": "2026-02-17", "Records": 2, "_kind": K_PERIOD,
           "_members": members}
    cols = [PackageColumn("Period", "Period"),
            PackageColumn("Records", "Records", kind="num")]
    snap = fx.snapshot(
        views=[fx.history_view([fx.segment("day_utc", "By day", rows=[row],
                                           columns=cols)])],
        member_columns=[PackageColumn.from_column(c)
                        for c in member_record_columns()])
    browser.open(fx.write(tmp_path, snap))
    browser.evaluate("WC.openRecord('history', 'day_utc', 0)")
    assert "Members \u2014 2 records" in browser.evaluate(DIALOG_TEXT % 0)
    assert browser.evaluate(
        "document.querySelectorAll('.dialog table.members tr').length") == 3
    browser.evaluate("document.querySelector('.dialog table.members button')"
                     ".click()")
    assert browser.evaluate("document.querySelectorAll('.dialog').length") == 2
    assert browser.evaluate(
        "document.querySelectorAll('.dialog')[1].querySelector('h2')"
        ".textContent") == detail_fields.identity_of(
        detail_fields.row_for_record(members[0]))


def test_copy_all_gives_the_dialog_as_text(browser, tmp_path):
    _open_row(browser, tmp_path, [fx.history_row(2)])
    browser.evaluate("Array.from(document.querySelectorAll('.dialog button'))"
                     ".filter(function (b) { return b.textContent ==="
                     " 'Copy all (tab-separated)'; })[0].click()")
    browser.evaluate("new Promise(function (ok) { setTimeout(ok, 1500); })",
                     await_promise=True)
    assert browser.evaluate("document.getElementById('wc-toast') !== null")


def test_a_stub_and_a_carved_record_are_named_for_what_they_are(browser,
                                                                tmp_path):
    stub = {"Key": "UrlHash 111", "Origin": "Carved (deleted/unflushed)",
            "Source": "WebCacheV01.dat", "Method": "key", "Confidence": "exact",
            "_kind": K_TOMBSTONE,
            "_record": {"Table": "Containers", "Source": "WebCacheV01.dat"}}
    cols = [PackageColumn("Key", "Key")]
    browser.open(fx.write(tmp_path, fx.snapshot(views=[fx.history_view([
        fx.segment(rows=[stub, fx.history_row(4, carved=True)],
                   columns=cols)])])))
    chip = ("(function () { var c = document.querySelector("
            "'.dialog .chip-kind'); return c && c.textContent; })()")
    browser.evaluate("WC.openRecord('history', 'history', 0)")
    assert browser.evaluate(chip) == "DELETED-RECORD STUB"
    assert "UrlHash 111" in browser.evaluate(
        "document.querySelector('.dialog h2').textContent")
    browser.evaluate("document.querySelector('.modal').remove()")
    browser.evaluate("WC.openRecord('history', 'history', 1)")
    assert browser.evaluate(chip) == "CARVED RECORD"


def test_the_dialog_is_never_taller_than_the_viewport_and_its_body_scrolls(
        browser, tmp_path):
    _open_row(browser, tmp_path, [fx.history_row(2)])
    box = browser.evaluate(
        "(function () { var d = document.querySelector('.dialog'),"
        " b = d.querySelector('.dbody'); return [d.getBoundingClientRect()"
        ".height <= innerHeight, b.scrollHeight > b.clientHeight]; })()")
    assert box == [True, True]


# --- ----------------------------------------------------------

#: Splits no short word: every heading, every button and every cell whose
#: words are short must be at least as wide as its longest word. Measured in
#: the page, at the production viewport.
_WORD_FIT = """(function () {
  var bad = [];
  Array.from(document.querySelectorAll('.dialog table.members th, '
    + '.dialog table.members button, .dialog table.members td')).forEach(
    function (cell) {
      var text = cell.textContent.trim();
      if (!text) return;
      var words = text.split(/\\s+/).filter(function (w) {
        return w.length <= 14; });
      var box = document.createElement('span');
      box.style.cssText = 'position:absolute;visibility:hidden;'
        + 'white-space:nowrap;font:inherit;';
      var style = getComputedStyle(cell);
      box.style.font = style.font;
      document.body.appendChild(box);
      var widest = 0;
      words.forEach(function (w) {
        box.textContent = w;
        widest = Math.max(widest, box.getBoundingClientRect().width);
      });
      document.body.removeChild(box);
      var room = cell.clientWidth - parseFloat(style.paddingLeft)
        - parseFloat(style.paddingRight);
      if (widest > room + 0.5) bad.push([cell.tagName, text.length]);
    });
  return bad;
})()"""


def _aggregate_page(browser, tmp_path):
    members = [fx.entry(1), fx.entry(2, RecoverySource="log")]
    row = {"Period": "2026-02-17", "Records": 2, "_kind": K_PERIOD,
           "_members": members}
    cols = [PackageColumn("Period", "Period"),
            PackageColumn("Records", "Records", kind="num")]
    snap = fx.snapshot(
        views=[fx.history_view([fx.segment("day_utc", "By day", rows=[row],
                                           columns=cols)])],
        member_columns=[PackageColumn.from_column(c)
                        for c in member_record_columns()])
    browser.call("Emulation.setDeviceMetricsOverride", width=1536, height=816,
                 deviceScaleFactor=1, mobile=False)
    browser.open(fx.write(tmp_path, snap))
    browser.evaluate("WC.openRecord('history', 'day_utc', 0)")


def test_no_member_heading_or_button_breaks_inside_a_word(browser, tmp_path):
    _aggregate_page(browser, tmp_path)
    assert browser.evaluate(_WORD_FIT) == []


def _value_of(browser, header):
    return browser.evaluate(
        "(function () { var k = Array.from(document.querySelectorAll("
        "'.dialog .kv .k')).filter(function (n) { return n.textContent === %r;"
        " })[0]; return k ? k.nextElementSibling.textContent : null; })()"
        % header)


def _absent_cases():
    from webcache import provenance
    live = fx.history_row(2)
    live["_record"]["Title"] = ""
    carved = fx.history_row(4, carved=True)
    stub = {"Key": "UrlHash 1", "Origin": provenance.CARVED_ORIGIN,
            "Source": "WebCacheV01.dat", "_kind": K_TOMBSTONE,
            "_record": {"Table": "Containers", "Source": "WebCacheV01.dat"}}
    return {"live": live, "carved": carved, "stub": stub}


def test_a_blank_canonical_value_says_what_the_apps_dialog_says(browser,
                                                                tmp_path):
    from webcache import provenance
    seen = {"states": set(), "fields": 0}
    for name, row in _absent_cases().items():
        _open_row(browser, tmp_path, [row],
                  columns=[PackageColumn("Origin", "Origin")])
        headers = {k: h for k, h, _g in forensic_engine.ENTRY_FIELDS}
        said = {f.key: f.absence for g in detail_fields.fields_for(row)
                for f in g.fields if f.absence and f.key in headers}
        time_keys = {"AccessedTime", "ModifiedTime", "CreationTime",
                     "ExpiryTime", "SyncTime", "PostCheckTime"}
        for key, header in headers.items():
            if key in time_keys or key.endswith(("_rfc", "_raw")):
                continue
            if _value_of(browser, header) != "(empty)":
                continue
            # Still "(empty)" in the page: the app must say exactly that.
            assert said.get(key) == provenance.ABSENCE_EMPTY, (name, key)
        for key, token in said.items():
            if key in time_keys:
                text = browser.evaluate(DIALOG_TEXT % 0)
                short = headers[key].partition(" (")[2].rstrip(")") or headers[key]
                assert "%s: %s" % (short, token) in text, (name, key)
            else:
                assert _value_of(browser, headers[key]) == token, (name, key)
            seen["states"].add(token)
            seen["fields"] += 1
        browser.evaluate("document.querySelector('.modal').remove()")
    assert provenance.ABSENCE_NOT_RECOVERED in seen["states"]
    assert provenance.ABSENCE_EMPTY in seen["states"]


def test_a_field_the_app_does_not_show_reads_not_applicable(browser,
                                                            tmp_path):
    from webcache import provenance
    row = fx.history_row(2)
    emitted = {f.key for g in detail_fields.fields_for(row) for f in g.fields}
    headers = {k: h for k, h, _g in forensic_engine.ENTRY_FIELDS}
    full = forensic_engine.canonical_record_row(row["_record"])
    key = next(k for k in headers
               if k not in emitted and full.get(k) in (None, "")
               and not k.endswith(("_rfc", "_raw"))
               and k not in {"AccessedTime", "ModifiedTime", "CreationTime",
                             "ExpiryTime", "SyncTime", "PostCheckTime"})
    _open_row(browser, tmp_path, [row])
    assert _value_of(browser, headers[key]) == provenance.ABSENCE_NOT_APPLICABLE


def test_each_head_states_what_kind_of_record_it_is(browser, tmp_path):
    cases = _absent_cases()
    cookie = {"Name": "n", "Domain": "example.test", "Origin": "Live record",
              "_kind": K_COOKIE, "_record": {"Name": "n"}}
    rows = [cases["live"], cases["carved"], cases["stub"], cookie]
    cols = [PackageColumn("Origin", "Origin")]
    browser.open(fx.write(tmp_path, fx.snapshot(views=[fx.history_view([
        fx.segment(rows=rows, columns=cols)])])))
    kinds = browser.evaluate(
        "(function () { var D = WC.data(), s = D.views[0].segments[0];"
        " return s.hd.map(function (h) { return D.heads[h].k; }); })()")
    assert kinds == ["live", "carved", "stub", "other"]


def test_a_chip_follows_the_kind_never_the_words(browser, tmp_path):
    """A live cookie whose NAME reads like a stub title is still a cookie, and
    a stub with no source file is still a stub."""
    cookie = {"Name": "Deleted row \u2014 key 9", "Domain": "example.test",
              "Origin": "Live record", "_kind": K_COOKIE,
              "_record": {"Name": "Deleted row \u2014 key 9"}}
    bare = {"Key": "UrlHash 1", "Origin": "Carved (deleted/unflushed)",
            "_kind": K_TOMBSTONE, "_record": {"Table": "Containers"}}
    cols = [PackageColumn("Origin", "Origin")]
    browser.open(fx.write(tmp_path, fx.snapshot(views=[fx.history_view([
        fx.segment(rows=[cookie, bare], columns=cols)])])))
    chip = ("(function () { var c = document.querySelector("
            "'.dialog .chip-kind'); return c && c.textContent; })()")
    browser.evaluate("WC.openRecord('history', 'history', 0)")
    assert browser.evaluate(chip) is None
    browser.evaluate("document.querySelector('.modal').remove()")
    browser.evaluate("WC.openRecord('history', 'history', 1)")
    assert browser.evaluate(chip) == "DELETED-RECORD STUB"



def test_copy_gives_what_is_shown_and_copy_stored_gives_what_is_stored(
        browser, tmp_path):
    """"Copy" on a field copies the value as shown; where
    the stored value differs, "Copy stored" copies that."""
    _open_row(browser, tmp_path, [fx.history_row(2, VisitCount=1234)])
    browser.evaluate(
        "window.__copied = []; navigator.clipboard.writeText = function (t) {"
        " window.__copied.push(t); return Promise.resolve(); }")
    browser.evaluate(
        "(function () { var k = Array.from(document.querySelectorAll("
        "'.dialog .kv .k')).filter(function (n) { return n.textContent ==="
        " 'Visits'; })[0]; var buttons = k.nextElementSibling"
        ".nextElementSibling.querySelectorAll('button');"
        " buttons[0].click(); buttons[1].click(); })()")
    browser.evaluate("new Promise(function (ok) { setTimeout(ok, 200); })",
                     await_promise=True)
    assert browser.evaluate("window.__copied") == ["1,234", "1234"]


def test_a_place_names_its_members_as_position_fixes(browser, tmp_path):
    """"Members — 68 records" over a place: they are position fixes, each
    shown by the record it was read out of."""
    from webcache import provenance
    from webcache.shell.record_kinds import K_HISTORY, K_PLACE
    entries = [fx.entry(1), fx.entry(2)]
    fixes = [{"Coords": "1.0, 2.0", "_kind": K_HISTORY, "_record": e,
              "Origin": provenance.LIVE_ORIGIN} for e in entries]
    row = {"Coords": "1.000, 2.000", "Fixes": 2, "_kind": K_PLACE,
           "_record": None, "_members": fixes}
    cols = [PackageColumn("Coords", "Coords"),
            PackageColumn("Fixes", "Fixes", kind="num")]
    snap = fx.snapshot(
        views=[fx.history_view([fx.segment("places", "Places", rows=[row],
                                           columns=cols)])],
        member_columns=[PackageColumn.from_column(c)
                        for c in member_record_columns()])
    browser.open(fx.write(tmp_path, snap))
    browser.evaluate("WC.openRecord('history', 'places', 0)")
    text = browser.evaluate(DIALOG_TEXT % 0)
    assert "Members — 2 position fixes" in text, text
    assert "each shown by the record it was read from" in text, text
    assert "RecordSource" not in text, text


def test_an_appended_column_is_named_for_people(browser, tmp_path):
    """The export's appended RecordSource column reached the dialog by its
    internal name, and as "(empty)" on every live record."""
    _open_row(browser, tmp_path, [fx.history_row(2)])
    assert "RecordSource" not in browser.evaluate(DIALOG_TEXT % 0)
