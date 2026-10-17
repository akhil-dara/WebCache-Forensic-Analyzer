"""The offline report finds what an examiner types, as the app does: "tax
docs" finds an address stored as "Tax%20docs", in the filter box and in a
condition, and "does not contain" excludes it. Every expectation comes from
the app's own RecordFilter on the same rows."""
from webcache.widgets.record_filter import Condition, RecordFilter

from tests import _package_fixtures as fx

ENCODED = "file:///F:/Case%20files/Tax%20docs/Form%2016.pdf"
PLAIN = "https://example.test/page"


def _rows():
    rows = [fx.history_row(1), fx.history_row(2), fx.history_row(3)]
    rows[0]["CleanUrl"] = ENCODED
    rows[1]["CleanUrl"] = PLAIN
    return rows


def _app_count(rows, text=None, cond=None):
    f = RecordFilter(rows, fx.history_columns())
    if text is not None:
        f.set_text(text)
    if cond is not None:
        f.set_condition("CleanUrl", cond)
    return f.visible_count


def _open(browser, tmp_path, rows):
    snap = fx.snapshot(views=[fx.history_view([fx.segment(rows=rows)])])
    browser.open(fx.write(tmp_path, snap))
    browser.evaluate("WC.openSegment('history', 'history')")


def _count(browser):
    return browser.evaluate("document.getElementById('wc-count').textContent")


def _type(browser, text):
    browser.evaluate(
        "(function () { var box = document.querySelector('input[placeholder^=\"Filter this view\"]');"
        " box.value = %r; box.dispatchEvent(new Event('input')); })()" % text)
    browser.evaluate("new Promise(function (ok) { setTimeout(ok, 400); })",
                     await_promise=True)


def test_the_report_filter_box_finds_the_words_an_examiner_types(browser, tmp_path):
    rows = _rows()
    assert _app_count(rows, text="tax docs") == 1
    _open(browser, tmp_path, rows)
    _type(browser, "tax docs")
    assert _count(browser).startswith("1 of 3 records"), _count(browser)


def test_the_report_finds_a_pasted_windows_path(browser, tmp_path):
    rows = _rows()
    typed = "F:\\Case files\\Tax docs"
    assert _app_count(rows, text=typed) == 1
    _open(browser, tmp_path, rows)
    _type(browser, typed)
    assert _count(browser).startswith("1 of 3 records"), _count(browser)


def _condition(browser, op, operand):
    """Through the Address funnel's popup, as an examiner would."""
    browser.evaluate("document.querySelectorAll('#wc-grid th .funnel')[0].click()")
    browser.evaluate("new Promise(function (ok) { setTimeout(ok, 50); })",
                     await_promise=True)
    browser.evaluate(
        "(function () { var p = document.querySelector('.popup');"
        " var s = p.querySelector('select'); s.value = %r;"
        " s.dispatchEvent(new Event('change'));"
        " p.querySelector('input[aria-label=\"Operand\"]').value = %r;"
        " Array.from(p.querySelectorAll('button')).filter(function (b)"
        " { return b.textContent === 'Apply'; })[0].click(); })()"
        % (op, operand))
    browser.evaluate("new Promise(function (ok) { setTimeout(ok, 100); })",
                     await_promise=True)


def test_the_report_conditions_read_both_spellings(browser, tmp_path):
    rows = _rows()
    keep = _app_count(rows, cond=Condition("contains", "tax docs"))
    drop = _app_count(rows, cond=Condition("does not contain", "tax docs"))
    assert (keep, drop) == (1, 2)
    _open(browser, tmp_path, rows)
    _condition(browser, "contains", "tax docs")
    assert _count(browser).startswith("%d of 3 records" % keep), _count(browser)
    _open(browser, tmp_path, rows)
    _condition(browser, "does not contain", "tax docs")
    assert _count(browser).startswith("%d of 3 records" % drop), _count(browser)
