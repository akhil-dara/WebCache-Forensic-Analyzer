"""The page's CSV is the app's view CSV, byte for byte, and its provenance
note says what the app's sidecar says."""
from webcache.shell import export_formats
from webcache.shell.html_package import PackageColumn
from webcache.shell.record_kinds import K_COOKIE

from tests import _package_fixtures as fx


def _rows():
    rows = ([fx.history_row(i) for i in range(1, 4)]
            + [fx.history_row(i, carved=True) for i in (7, 8)])
    rows[0]["CleanUrl"] = '=HYPERLINK("https://example.test")'
    rows[1]["CleanUrl"] = 'https://example.test/a,b\n"quoted"'
    rows[2]["_record"]["UrlHash"] = 2 ** 60
    return rows


def _open(browser, tmp_path, rows, columns=None):
    browser.clear_downloads()
    browser.open(fx.write(tmp_path, fx.snapshot(views=[fx.history_view(
        [fx.segment(rows=rows, columns=columns)])])))


def _export(browser, name):
    browser.evaluate("WC.exportCsv('history', 'history')", await_promise=True)
    return browser.wait_download(name)


def test_the_csv_is_the_apps_view_csv_byte_for_byte(browser, tmp_path):
    rows = _rows()
    _open(browser, tmp_path, rows)
    page = _export(browser, "webcache_history.csv")
    app = tmp_path / "app.csv"
    export_formats.write_view_csv(rows, fx.history_columns(), str(app), {})
    assert open(page, "rb").read() == app.read_bytes()


def test_a_cookie_csv_carries_each_cookies_own_fields(browser, tmp_path):
    cookies = [{"Name": "sid", "Domain": "example.test", "Value": "=1+1",
                "Expires_raw": 2 ** 60},
               {"Name": "pref", "Domain": "example.test", "Path": "/"}]
    rows = [{"Name": c["Name"], "Domain": c["Domain"], "Origin": "Live record",
             "_kind": K_COOKIE, "_record": c} for c in cookies]
    cols = [PackageColumn("Name", "Cookie"), PackageColumn("Domain", "Domain")]
    _open(browser, tmp_path, rows, columns=cols)
    page = _export(browser, "webcache_history.csv")
    app = tmp_path / "app.csv"
    export_formats.write_view_csv(rows, cols, str(app), {})
    assert open(page, "rb").read() == app.read_bytes()


def test_a_filtered_export_holds_the_rows_shown_in_the_order_shown(browser,
                                                                  tmp_path):
    rows = _rows()
    _open(browser, tmp_path, rows)
    browser.evaluate("(function () { var m = WC.model('history', 'history');"
                     " m.setText('example.test/page'); m.setSort(2, true); })()")
    page = _export(browser, "webcache_history_filtered.csv")
    shown = sorted((r for r in rows if "example.test/page" in r["CleanUrl"]),
                   key=lambda r: r["VisitCount"], reverse=True)
    app = tmp_path / "app.csv"
    export_formats.write_view_csv(shown, fx.history_columns(), str(app), {})
    assert open(page, "rb").read() == app.read_bytes()


def test_the_provenance_note_says_what_the_apps_sidecar_says(browser,
                                                             tmp_path):
    rows = _rows()
    _open(browser, tmp_path, rows)
    _export(browser, "webcache_history.csv")
    browser.evaluate("Array.from(document.querySelectorAll('#wc-toast button'))"
                     ".filter(function (b) { return b.textContent ==="
                     " 'Save provenance note'; })[0].click()")
    note = browser.wait_download("webcache_history.csv.provenance.txt")
    app = tmp_path / "app.csv"
    scope = {"view": "history", "view_label": "History",
             "hidden_columns": ["Offset"], "rows_in_view": 5,
             "rows_in_record_set": 5, "is_subset": False, "live_rows": 3,
             "carved_rows": 2, "recovery_scan_run": True, "unit": "rows"}
    scope["rows_in_file"] = export_formats.write_view_csv(
        rows, fx.history_columns(), str(app), scope)
    side = export_formats.write_view_provenance(
        str(app), {"exported_utc": "x",
                   "evidence": {"C:/case/WebCacheV01.dat": "ab" * 32}},
        scope, scope["formula_values"])

    def lines(path):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return [line for line in fh.read().split("\n")
                    if not line.startswith(("Written (UTC):", "  Name    :"))]
    page_lines = lines(note)
    cut = page_lines.index("SOURCE")
    assert page_lines[:cut - 1] + [""] == lines(side)
    assert open(note, "rb").read()[:3] == b"\xef\xbb\xbf"


def test_a_sorted_export_breaks_ties_in_the_apps_order(browser, tmp_path):
    """Default sort, a funnel condition, then a sort with ties: the page's
    rows come out in the order the app's grid shows them."""
    import datetime

    from webcache.widgets.record_filter import Condition, RecordFilter
    rows = [fx.history_row(i, VisitCount=i % 3) for i in range(1, 13)]
    rows += [fx.history_row(i, VisitCount=i % 3, AccessedUtc=datetime.datetime(
        2026, 2, 18, 9, 0, i, tzinfo=fx.UTC)) for i in range(13, 16)]
    columns = fx.history_columns()
    browser.clear_downloads()
    browser.open(fx.write(tmp_path, fx.snapshot(views=[fx.history_view(
        [fx.segment(rows=rows, default_sort=("AccessedUtc", True))])])))
    browser.evaluate("(function () { var m = WC.model('history', 'history');"
                     " m.setCondition(1, WC.condition('on', '2026-02-17'));"
                     " m.setSort(2, true); })()")
    page = _export(browser, "webcache_history_filtered.csv")
    app = RecordFilter(rows, columns)
    app.sort("AccessedUtc", True)
    app.set_condition("AccessedUtc", Condition("on", "2026-02-17"))
    app.sort("VisitCount", True)
    expected = tmp_path / "app.csv"
    export_formats.write_view_csv(app.visible(), columns, str(expected), {})
    assert open(page, "rb").read() == expected.read_bytes()
