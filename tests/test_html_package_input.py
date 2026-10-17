"""The page driven the way a person drives it: TRUSTED mouse and key events
through the browser's own input path (DevTools Input.dispatch*), never a
synthetic dispatchEvent. A synthetic dblclick fires whether or not two real
clicks would; only real input shows what an examiner gets."""
from tests import _package_fixtures as fx

ROW = "#wc-grid tbody tr:not(.spacer)"


def _settle(browser):
    browser.evaluate("new Promise(function (ok) { requestAnimationFrame("
                     "function () { requestAnimationFrame(ok); }); })",
                     await_promise=True)


def _history(browser, tmp_path, rows=None):
    browser.open(fx.write(tmp_path, fx.snapshot(views=[fx.history_view(
        [fx.segment(rows=rows)])])))
    browser.evaluate("WC.openSegment('history', 'history')")
    _settle(browser)


def _dialogs(browser):
    return browser.evaluate("document.querySelectorAll('.modal').length")


def test_a_real_double_click_on_a_row_opens_its_record(browser, tmp_path):
    _history(browser, tmp_path)
    x, y = browser.center(ROW + ":nth-child(3)")
    browser.evaluate("document.elementFromPoint(%f, %f).closest('tr')"
                     ".__probe = 'same node'" % (x, y))
    browser.click(x, y, count=1)
    _settle(browser)
    # The first click selects the row it landed on, without replacing it:
    # Chrome fires dblclick only when both presses hit the same node.
    same = browser.evaluate("document.elementFromPoint(%f, %f).closest('tr')"
                            ".__probe || null" % (x, y))
    selected = browser.evaluate("document.elementFromPoint(%f, %f)"
                                ".closest('tr').classList.contains('sel')"
                                % (x, y))
    browser.click(x, y, count=2)
    _settle(browser)
    assert _dialogs(browser) == 1
    assert same == "same node" and selected


def test_enter_on_a_column_funnel_opens_its_filter_not_the_record(browser,
                                                                  tmp_path):
    _history(browser, tmp_path)
    browser.click(*browser.center(ROW + ":nth-child(2)"))
    browser.evaluate("document.querySelector('#wc-grid thead .funnel').focus()")
    browser.key("Enter")
    _settle(browser)
    assert _dialogs(browser) == 0
    assert browser.evaluate("document.querySelectorAll('.popup').length") == 1


def test_enter_on_a_more_lines_marker_opens_the_whole_value(browser,
                                                           tmp_path):
    long_value = "\n".join("line %d" % i for i in range(20))
    _history(browser, tmp_path, [fx.history_row(1, CleanUrl=long_value),
                                 fx.history_row(2)])
    browser.evaluate("WC.setWrap(true)")
    _settle(browser)
    browser.click(*browser.center(ROW + ":nth-child(3)"))
    browser.evaluate("document.querySelector('#wc-grid .more').focus()")
    browser.key("Enter")
    _settle(browser)
    assert browser.evaluate(
        "(document.querySelector('.dialog pre.whole') || {}).textContent"
        " || null") == long_value


def test_a_column_heading_sorts_from_the_keyboard(browser, tmp_path):
    _history(browser, tmp_path)
    browser.click(*browser.center(ROW + ":nth-child(2)"))
    visits = "Array.from(document.querySelectorAll('#wc-grid thead th'))" \
             ".filter(function (th) { return th.textContent.indexOf('Visits')" \
             " === 0; })[0]"
    browser.evaluate("(%s.querySelector('.hlabel')).focus()" % visits)
    assert browser.evaluate("document.activeElement.textContent") == "Visits"
    browser.key("Enter")
    _settle(browser)
    assert _dialogs(browser) == 0
    assert browser.evaluate("%s.getAttribute('aria-sort')" % visits) == \
        "ascending"
    browser.evaluate("(%s.querySelector('.hlabel')).focus()" % visits)
    browser.key(" ")
    _settle(browser)
    assert browser.evaluate("%s.getAttribute('aria-sort')" % visits) == \
        "descending"


FOCUSABLE = ("Array.from(document.querySelector('.dialog').querySelectorAll("
             "'button, input, select, [tabindex]:not([tabindex=\"-1\"])'))"
             ".filter(function (n) { return !n.disabled && n.offsetParent; })")


def _open_by_keyboard(browser, tmp_path):
    _history(browser, tmp_path)
    browser.click(*browser.center(ROW + ":nth-child(2)"))
    browser.key("ArrowDown")
    browser.key("Enter")
    _settle(browser)
    assert _dialogs(browser) == 1


def test_tab_stays_inside_the_record_dialog(browser, tmp_path):
    _open_by_keyboard(browser, tmp_path)
    browser.evaluate("(function () { var f = %s; f[f.length - 1].focus(); })()"
                     % FOCUSABLE)
    browser.key("Tab")
    assert browser.evaluate("document.activeElement === %s[0]" % FOCUSABLE)
    browser.key("Tab", shift=True)
    assert browser.evaluate("(function () { var f = %s;"
                            " return document.activeElement === f[f.length - 1];"
                            " })()" % FOCUSABLE)


def test_closing_the_dialog_gives_the_keyboard_back_to_the_grid(browser,
                                                                 tmp_path):
    _open_by_keyboard(browser, tmp_path)
    browser.key("Escape")
    _settle(browser)
    assert _dialogs(browser) == 0
    assert browser.evaluate("document.activeElement.id") == "wc-grid"
    selected = "+document.querySelector('#wc-grid tr.sel').dataset.pos"
    before = browser.evaluate(selected)
    browser.key("ArrowDown")
    _settle(browser)
    assert browser.evaluate(selected) == before + 1


def test_closing_a_filter_popup_gives_the_keyboard_back_to_its_funnel(
        browser, tmp_path):
    _history(browser, tmp_path)
    browser.evaluate("document.querySelector('#wc-grid thead .funnel').focus()")
    browser.key("Enter")
    _settle(browser)
    assert browser.evaluate("document.querySelectorAll('.popup').length") == 1
    browser.key("Escape")
    _settle(browser)
    assert browser.evaluate("document.activeElement.classList.contains("
                            "'funnel')")
