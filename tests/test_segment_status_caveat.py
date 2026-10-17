"""The caveat on screen is the segment's own -- never the HSTS sentence
over Cookies or Certificates. It is stated once, above the grid; the
status bar no longer repeats it."""
import pytest

from webcache.shell.main_window import MainWindow


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_the_caveat_line_follows_the_segment_on_screen(win):
    view = win._ensure_view_built("cookies")
    win.go_to("cookies")
    for key in view._switcher_buttons:
        view._switcher_buttons[key].click()
        caveat = view._segments_by_key[key].caveat
        assert view.caveat._text.text() == caveat, key
        assert win.status_message() == "", key       # not repeated


def test_going_to_the_view_states_the_active_segments_caveat(win):
    view = win._ensure_view_built("cookies")
    active = view._segments_by_key[view._active_key]
    win.go_to("dashboard")
    win.go_to("cookies")
    assert view.caveat._text.text() == active.caveat
    assert win.status_message() == ""
    assert "HSTS pin" not in win.caveat_for("cookies")


def test_the_version_stands_apart_from_the_summary_and_the_edge(qtbot):
    from PySide6.QtWidgets import QLabel
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1400, 800)
    w.show()
    qtbot.waitExposed(w)
    bar = w.statusBar()
    label = next(l for l in bar.findChildren(QLabel)
                 if l.text().startswith("v") and l.text()[1:2].isdigit())
    margins = label.contentsMargins()
    assert margins.left() >= 8 and margins.right() >= 8
