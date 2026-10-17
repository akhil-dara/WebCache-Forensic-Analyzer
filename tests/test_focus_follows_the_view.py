"""Switching views moves keyboard focus into the view switched to.

It used to stay behind: Qt handed it to whatever came first in the new
page -- Location's "Exact" grouping button, Timeline's "UTC" clock --
so arrow keys never reached the grid, a stray Space flipped the grouping
or the clock, and the focus ring on an unchecked button read as the
choice in force."""
import pytest
from PySide6.QtWidgets import QApplication

from webcache.shell.main_window import MainWindow


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    w.activateWindow()
    return w


def _focus_in(widget):
    focus = QApplication.focusWidget()
    while focus is not None:
        if focus is widget:
            return True
        focus = focus.parentWidget()
    return False


@pytest.mark.parametrize("key", ["location", "timeline", "domains",
                                 "history", "cookies"])
def test_leaving_a_grid_lands_on_the_next_view_s_grid(win, key):
    win.go_to("downloads")
    win._built_widget("downloads").table.setFocus()
    win.go_to(key)
    assert QApplication.focusWidget() is win._built_widget(key).table, (
        key, QApplication.focusWidget())


def test_search_lands_on_its_keyword_box(win):
    win.go_to("history")
    win._built_widget("history").table.setFocus()
    win.go_to("search")
    assert QApplication.focusWidget() is win._built_widget("search").keyword_box


def test_focus_left_outside_the_views_stays_where_it_is(win):
    win.sidebar.open_button.setFocus()
    win.go_to("location")
    assert QApplication.focusWidget() is win.sidebar.open_button


def test_a_view_without_a_grid_does_not_keep_focus_in_the_old_one(win):
    win.go_to("history")
    old = win._built_widget("history")
    old.table.setFocus()
    win.go_to("dashboard")
    assert not _focus_in(old)


def test_an_opened_exhibit_lands_with_focus_on_the_history_grid(win):
    """The first-run page's Open button is hidden by the load; focus fell
    on a bare page container, so the first arrow key did nothing."""
    from tests.test_domains_wiring import (_FakeParser, _entry,
                                           _fake_evidence_set)
    win.content_stack.currentWidget().setFocus()
    win._on_evidence_loaded(
        {"rows": [], "parser": _FakeParser([_entry(Url="https://a.example/1")])},
        _fake_evidence_set())
    assert QApplication.focusWidget() is win._built_widget("history").table
