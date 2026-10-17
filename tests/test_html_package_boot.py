"""The offline report boots in a real browser. Needs the session `browser` fixture (tests/_browser.py)."""
import pathlib

from webcache import provenance

from tests import _package_fixtures as fx


def _open(browser, tmp_path, snap=None):
    path = fx.write(tmp_path, snap)
    browser.open(path)
    return path


def test_it_boots_with_no_error_no_csp_violation_and_no_request(
        browser, tmp_path):
    path = _open(browser, tmp_path)
    assert browser.evaluate("window.__wc_ready === true")
    assert browser.console_errors() == []
    assert browser.csp_violations() == []
    page = pathlib.Path(path).resolve().as_uri()
    assert all(url == page for url in browser.requests()), browser.requests()


def test_the_title_and_top_bar_state_evidence_tool_and_time(browser, tmp_path):
    _open(browser, tmp_path)
    assert (browser.evaluate("document.title")
            == "WebCache offline report \u2014 WebCacheV01.dat")
    top = browser.evaluate("document.querySelector('.topbar').textContent")
    assert "ab" * 32 in top
    assert provenance.TOOL_VERSION in top and fx.GENERATED in top


def test_the_case_summary_counts_live_and_carved_per_segment(browser, tmp_path):
    rows = [fx.history_row(1), fx.history_row(2, carved=True)]
    _open(browser, tmp_path, fx.snapshot(
        views=[fx.history_view([fx.segment(rows=rows)])]))
    text = browser.evaluate("document.getElementById('wc-main').textContent")
    for heading in ("Case summary", "Records in this report", "Evidence",
                    "What this report can and cannot show",
                    "Evidentiary basis badges", "Verifying this file"):
        assert heading in text, heading
    cells = browser.evaluate(
        "Array.from(document.querySelectorAll('table.counts tr')).map("
        "function (r) { return Array.from(r.cells).map("
        "function (c) { return c.textContent; }); })")
    assert ["History", "History", "2", "1", "1", "0"] in cells


def test_the_sidebar_follows_the_apps_sections(browser, tmp_path):
    _open(browser, tmp_path)
    labels = browser.evaluate(
        "Array.from(document.querySelectorAll('.side h3, .side .nav > "
        "span:first-child')).map(function (n) { return n.textContent; })")
    assert labels[:4] == ["CASE", "Case summary", "USER ACTIVITY", "History"]


def test_a_file_that_is_not_a_report_says_so(browser, tmp_path):
    from webcache.shell.html_package import render_page
    path = tmp_path / "bad.html"
    path.write_text(render_page('{"schema":"other/1"}'), encoding="utf-8",
                    newline="")
    browser.open(str(path), wait_ready=False)
    assert "is not a WebCache offline report" in browser.evaluate(
        "document.body.textContent")


def test_the_api_is_frozen_and_ports_display_text(browser, tmp_path):
    _open(browser, tmp_path)
    assert browser.evaluate("Object.isFrozen(window.WC)")
    assert browser.evaluate(
        "WC.displayText(1234567, {kind: 'num', num: true})") == "1,234,567"
    assert browser.evaluate(
        "WC.displayText(3888419, {kind: 'offset', num: true})") == "0x003B5523"


def _read_back_snapshot():
    """Every part of the island in one report: live, carved, stub and
    string-carved rows; blank, absent and token values; a column of nulls;
    a non-default column; a member list; text that starts with the
    packer's own marker; hostile markup."""
    from webcache.shell.html_package import PackageColumn, PackageView
    from webcache.shell.record_kinds import (K_CARVED_STRING, K_COOKIE,
                                             K_PERIOD, K_TOMBSTONE)
    rows = [fx.history_row(i, carved=bool(i % 3)) for i in range(1, 30)]
    rows += [fx.history_row(40, CleanUrl="~"), fx.history_row(41, CleanUrl="~~x"),
             fx.history_row(42, CleanUrl="~-3"), fx.history_row(43, CleanUrl="~*0"),
             fx.history_row(44, CleanUrl="~0"), fx.history_row(45, CleanUrl=""),
             fx.history_row(46, CleanUrl="</script><b>&amp; "),
             fx.history_row(47, carved=True, _kind=K_CARVED_STRING,
                            IsInPrivate=provenance.ABSENCE_NOT_DETERMINABLE),
             fx.history_row(48, carved=True, _kind=K_TOMBSTONE, Key="UrlHash 7")]
    rows[3]["_record"]["CacheFolder"] = "~folder"
    cookie = fx.history_row(49, _kind=K_COOKIE)
    cookie["_record"].update({"__proto__": "~polluted", "constructor": "x",
                              "~key": "~value"})
    rows.append(cookie)
    cols = fx.history_columns()
    cols[0].badge, cols[0].note, cols[0].badge_tooltip = "OBS", "a note", "tip"
    members = [fx.entry(100 + k) for k in range(4)]
    period = {"Period": "2026-02-17", "Records": 4, "_kind": K_PERIOD,
              "_members": members}
    day = fx.segment("day_utc", "By day", rows=[period], columns=[
        PackageColumn("Period", "Period"),
        PackageColumn("Records", "Records", kind="num")])
    nulls = fx.segment("nulls", "Nulls", rows=[
        {"A": None, "B": i if i % 4 else None, "_kind": "table_row"}
        for i in range(12)], columns=[PackageColumn("A"), PackageColumn("B",
                                                                    kind="num")])
    view = PackageView("history", "History", "USER ACTIVITY", "~caption",
                       [fx.segment(rows=rows, columns=cols), day, nulls])
    from webcache.views.records_view import member_record_columns
    return fx.snapshot(views=[view], member_columns=[
        PackageColumn.from_column(c) for c in member_record_columns()])


def test_the_page_reads_back_exactly_the_island_it_was_written_from(
        browser, tmp_path):
    import json
    from webcache.shell.html_package import build_island, island_json
    snap = _read_back_snapshot()
    expected = json.loads(island_json(build_island(snap, fx.GENERATED)))
    assert any("own" in r and "__proto__" in r["own"] for r in expected["records"])
    _open(browser, tmp_path, snap)
    assert json.loads(browser.evaluate("JSON.stringify(WC.data())")) == expected
    # A field named __proto__ stayed a field: nothing reached a prototype.
    assert browser.evaluate("({}).constructor === Object && !('~polluted' in {})"
                            " && Object.getPrototypeOf(WC.data().records.filter("
                            "function (r) { return r.own; })[0].own) === "
                            "Object.prototype")


def test_a_report_packed_in_an_unknown_form_says_so(browser, tmp_path):
    from webcache.shell.html_package import render_page
    path = tmp_path / "later.html"
    path.write_text(render_page('{"schema":"webcache-offline-report/1",'
                                '"pack":2,"s":[],"x":[],"d":{}}'),
                    encoding="utf-8", newline="")
    browser.open(str(path), wait_ready=False)
    assert "cannot read (pack 2)" in browser.evaluate(
        "document.getElementById('app').textContent")


def test_the_counts_table_calls_carves_and_stubs_recovered(browser, tmp_path):
    """A deleted-record stub is not carved; the counts
    table's column says what it counts, as record_counts.DEFINITION does."""
    browser.open(fx.write(tmp_path))
    heads = browser.evaluate(
        "Array.from(document.querySelectorAll('#wc-main th'))"
        ".map(function (t) { return t.textContent; })")
    assert "Recovered records (carves and stubs)" in heads
    assert "Carved records" not in heads


def test_nav_badges_say_what_the_apps_sidebar_says(browser, tmp_path):
    """The page counted its own rows (Location "12" where
    the app says "5 position fixes"); a view now carries the app's badge."""
    from webcache.shell.html_package import PackageView
    view = PackageView("location", "Location", "ANALYSIS", "Fixes.",
                       [fx.segment(key="fixes", label="Fixes")],
                       badge="5", unit="position fixes")
    browser.open(fx.write(tmp_path, fx.snapshot(views=[fx.history_view(), view])))
    badge = browser.evaluate(
        "(function () { var b = Array.from(document.querySelectorAll('nav button.nav'))"
        ".filter(function (n) { return n.textContent.indexOf('Location') === 0; })[0]"
        ".querySelector('.n'); return [b.textContent, b.title]; })()")
    assert badge == ["5", "5 position fixes"]


def test_the_counts_table_folds_raw_tables_into_one_row(browser, tmp_path):
    """Every raw table was its own counts row (285 rows on
    the 136 MB sample). They are one row, with a button that lists them."""
    from webcache.shell.html_package import PackageView
    raw = PackageView("raw", "Raw tables", "DATABASE", "Raw.",
                      [fx.segment(key="t:%d" % i, label="T%d" % i)
                       for i in range(4)], picker="list")
    browser.open(fx.write(tmp_path, fx.snapshot(views=[fx.history_view(), raw])))
    rows = browser.evaluate(
        "Array.from(document.querySelectorAll('table.counts tr'))"
        ".map(function (r) { return r.cells[0].textContent; })")
    assert rows.count("Raw tables") == 1
    assert "4 tables" in browser.evaluate(
        "document.querySelector('table.counts').textContent")
    browser.evaluate("document.getElementById('wc-raw-counts').click()")
    assert browser.evaluate(
        "document.querySelectorAll('table.rawcounts tr').length") == 5


def test_the_summary_lists_each_time_the_evidence_was_opened(browser, tmp_path):
    """"""
    snap = fx.snapshot()
    snap.meta["opened"] = [["2026-10-05T10:00:00Z", "C:/case/e.dat", "ab" * 32, 1024]]
    browser.open(fx.write(tmp_path, snap))
    text = browser.evaluate("document.getElementById('wc-main').textContent")
    assert "Evidence opened" in text and "2026-10-05T10:00:00Z" in text


def _many_files_snapshot():
    snap = fx.snapshot()
    snap.meta["evidence"] = [
        {"path": "C:/case/V01.chk", "sha256": "cd" * 32, "bytes": 8},
        {"path": "C:/case/WebCacheV01.dat", "sha256": "ab" * 32,
         "bytes": 1024},
        {"path": "C:/case/V01.log", "sha256": "ef" * 32, "bytes": 16},
    ]
    return snap


def test_the_top_bar_is_one_line_with_every_hash_one_click_away(
        browser, tmp_path):
    """Every file's hash on the bar wrapped it onto five lines. The bar
    names the evidence; every file's full hash, each with a copy button,
    is one click away (and on the Case summary)."""
    # The examiner's screen: 1920 px at 125 % scaling.
    browser.call("Emulation.setDeviceMetricsOverride", width=1536,
                 height=864, deviceScaleFactor=1, mobile=False)
    try:
        _check_one_line_bar(browser, tmp_path)
    finally:
        browser.call("Emulation.clearDeviceMetricsOverride")


def _check_one_line_bar(browser, tmp_path):
    _open(browser, tmp_path, _many_files_snapshot())
    assert browser.evaluate(
        "document.querySelector('.topbar .title').nextElementSibling"
        ".textContent") == "Evidence WebCacheV01.dat"
    files = "document.querySelector('.topbar details.files')"
    assert browser.evaluate(files + ".querySelector('summary').textContent"
                            ) == "SHA-256 · 3 files"
    hidden = browser.evaluate(
        "Array.from(%s.querySelectorAll('.mono')).every("
        "function (n) { return !n.checkVisibility(); })" % files)
    assert hidden
    listed = browser.evaluate(files + ".textContent")
    for digest in ("ab", "cd", "ef"):
        assert digest * 32 in listed
    assert browser.evaluate(
        "document.querySelector('.topbar').getBoundingClientRect().height"
    ) < 50
    browser.evaluate(files + ".querySelector('summary').click()")
    assert browser.evaluate(
        "Array.from(%s.querySelectorAll('.mono')).every("
        "function (n) { return n.checkVisibility(); })" % files)
    assert browser.evaluate(
        "%s.querySelectorAll('button.copy').length" % files) == 3


def test_one_evidence_file_is_listed_the_same_way(browser, tmp_path):
    _open(browser, tmp_path)
    assert browser.evaluate(
        "document.querySelector('.topbar details.files summary')"
        ".textContent") == "SHA-256 · 1 file"


def test_each_listed_hash_is_on_one_line(browser, tmp_path):
    browser.call("Emulation.setDeviceMetricsOverride", width=1536,
                 height=864, deviceScaleFactor=1, mobile=False)
    try:
        _open(browser, tmp_path, _many_files_snapshot())
        browser.evaluate("document.querySelector('.topbar details.files "
                         "summary').click()")
        # A grid item is one box however many lines it wraps to, so the
        # hash's height is compared with the one-line file name beside it.
        wrapped = browser.evaluate(
            "Array.from(document.querySelectorAll('.topbar details.files "
            ".file')).map(function (row) { var name = row.querySelector('b')"
            ".getBoundingClientRect().height; var hash = row.querySelector("
            "'.mono').getBoundingClientRect().height; return hash > name + 2; })")
        assert wrapped == [False, False, False]
    finally:
        browser.call("Emulation.clearDeviceMetricsOverride")
