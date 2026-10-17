"""The report's value list names an empty cell the way the app does: a
column that says what blank means ("Carved from" on a live row) lists that,
not a bare "(blank)"."""
from webcache.shell.html_package import PackageColumn
from webcache.widgets.column_spec import Column

from tests import _package_fixtures as fx

LIVE_SOURCE = "(live record, not carved)"


def _columns():
    return [PackageColumn.from_column(c) for c in (
        Column("CleanUrl", "Address", 460, kind="url", field="CleanUrl"),
        Column("Source", "Carved from", 150, kind="text", field="Source",
               blank_text=LIVE_SOURCE),
    )]


def _labels(browser, tmp_path):
    rows = [fx.history_row(1), fx.history_row(2, carved=True)]
    snap = fx.snapshot(views=[fx.history_view(
        [fx.segment(rows=rows, columns=_columns())])])
    browser.open(fx.write(tmp_path, snap))
    browser.evaluate("WC.openSegment('history', 'history')")
    browser.evaluate("document.querySelectorAll('#wc-grid th .funnel')[1].click()")
    browser.evaluate("new Promise(function (ok) { setTimeout(ok, 50); })",
                     await_promise=True)
    return browser.evaluate(
        "Array.from(document.querySelectorAll('.popup .values label span'))"
        ".map(function (s) { return s.textContent; })")


def test_the_report_value_list_says_what_a_blank_carved_from_means(browser, tmp_path):
    labels = _labels(browser, tmp_path)
    assert LIVE_SOURCE in labels, labels
    assert "(blank)" not in labels, labels
