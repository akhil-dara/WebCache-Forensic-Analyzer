"""The offline report filters by origin as the app does: the Origin heading
carries a funnel, its popup lists each origin with its count, and the
choice narrows the grid, is named in the filter line and is cleared by
Clear filters."""
from tests import _package_fixtures as fx


def _open(browser, tmp_path):
    rows = ([fx.history_row(i) for i in range(1, 4)]
            + [fx.history_row(i, carved=True) for i in range(4, 6)])
    snap = fx.snapshot(views=[fx.history_view([fx.segment(rows=rows)])])
    browser.open(fx.write(tmp_path, snap))
    browser.evaluate("WC.openSegment('history', 'history')")


def _wait(browser):
    browser.evaluate("new Promise(function (ok) { setTimeout(ok, 50); })",
                     await_promise=True)


def _open_origin_popup(browser):
    assert browser.evaluate(
        "!!document.querySelector('#wc-grid thead th.origin .ofunnel')"), \
        "the Origin heading has no filter button"
    browser.evaluate(
        "document.querySelector('#wc-grid thead th.origin .ofunnel').click()")
    _wait(browser)


def _labels(browser):
    return browser.evaluate(
        "Array.from(document.querySelectorAll('.popup .values label'))"
        ".map(function (l) { return l.querySelector('span.v').textContent"
        " + ' ' + l.querySelector('span.note').textContent; })")


def _count(browser):
    return browser.evaluate("document.getElementById('wc-count').textContent")


def test_the_origin_popup_lists_each_origin_with_its_count(browser, tmp_path):
    _open(browser, tmp_path)
    _open_origin_popup(browser)
    assert _labels(browser) == ["Live 3", "Carved 2"]


def test_unticking_live_leaves_the_carved_rows_and_says_so(browser, tmp_path):
    _open(browser, tmp_path)
    _open_origin_popup(browser)
    browser.evaluate(
        "(function () { var p = document.querySelector('.popup');"
        " Array.from(p.querySelectorAll('.values label')).filter(function (l)"
        " { return l.querySelector('span.v').textContent === 'Live'; })[0]"
        ".querySelector('input').click();"
        " Array.from(p.querySelectorAll('button')).filter(function (b)"
        " { return b.textContent === 'Apply'; })[0].click(); })()")
    _wait(browser)
    assert _count(browser).startswith("2 of 5 records")
    assert "Origin: Is Carved" in browser.evaluate(
        "document.getElementById('wc-sentence').textContent")
    assert browser.evaluate(
        "document.querySelector('#wc-grid thead th.origin .ofunnel')"
        ".classList.contains('on')")
    origins = browser.evaluate(
        "Array.from(document.querySelectorAll('#wc-grid tbody th.origin'))"
        ".map(function (h) { return h.textContent; })")
    assert set(origins) == {"Carved"}, origins


def _keep_only(browser, word):
    _open_origin_popup(browser)
    browser.evaluate(
        "(function () { var p = document.querySelector('.popup');"
        " Array.from(p.querySelectorAll('.values label')).forEach(function (l)"
        " { var box = l.querySelector('input');"
        "   if ((l.querySelector('span.v').textContent === %r) !== box.checked)"
        "     box.click(); });"
        " Array.from(p.querySelectorAll('button')).filter(function (b)"
        " { return b.textContent === 'Apply'; })[0].click(); })()" % word)
    _wait(browser)


def test_clear_filters_brings_every_row_back(browser, tmp_path):
    _open(browser, tmp_path)
    _keep_only(browser, "Live")
    assert _count(browser).startswith("3 of 5 records")
    browser.evaluate(
        "Array.from(document.querySelectorAll('button')).filter(function (b)"
        " { return b.textContent === 'Clear filters'; })[0].click()")
    _wait(browser)
    assert _count(browser).startswith("5 records")


def test_the_origin_funnel_shows_the_same_glyph_as_a_column_funnel(browser, tmp_path):
    """Drawn by CSS (so the heading's text stays "Origin"); a broken escape
    once drew a control character and "bd" instead."""
    _open(browser, tmp_path)
    drawn = browser.evaluate(
        "getComputedStyle(document.querySelector('#wc-grid thead th.origin"
        " .ofunnel'), '::before').content")
    column = browser.evaluate(
        "document.querySelector('#wc-grid thead .funnel').textContent")
    assert drawn == '"%s"' % column == '"▽"', (drawn, column)
    assert browser.evaluate(
        "document.querySelector('#wc-grid thead th.origin').textContent"
        ) == "Origin"
