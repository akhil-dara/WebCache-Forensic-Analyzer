"""A segment switcher shows which segment is on
screen -- a checked button is filled differently from an unchecked one,
in both themes and after a theme toggle -- and Deleted Records' method
buttons and "High confidence only" chip follow the theme."""
import pytest
from PySide6.QtWidgets import QApplication

from webcache.shell import theme
from webcache.shell.main_window import MainWindow


def _fill(button):
    """The button's own fill, sampled inside its border, clear of text."""
    image = button.grab().toImage()
    return image.pixelColor(4, image.height() // 2).name()


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1400, 850)
    w.show()
    qtbot.waitExposed(w)
    return w


def _switchers(view):
    buttons = list(view._switcher_buttons.values())
    checked = [b for b in buttons if b.isChecked()]
    unchecked = [b for b in buttons if not b.isChecked()]
    return checked[0], unchecked[0]


@pytest.mark.parametrize("key", ["downloads", "location", "cookies",
                                 "iocs", "timeline"])
def test_the_checked_segment_is_filled_differently_in_both_themes(win, key):
    view = win._ensure_view_built(key)
    win.go_to(key)
    for _ in range(2):
        on, off = _switchers(view)
        # Focus on the UNCHECKED one: the ring must not be the only cue.
        off.setFocus()
        assert _fill(on) != _fill(off), (theme.current_name(), on.text())
        win._toggle_theme()


def test_deleted_records_buttons_and_chip_follow_the_theme(win, qtbot):
    from webcache.widgets.quick_filter_chip import QuickFilterChip
    view = win._ensure_view_built("recovery")
    win.go_to("recovery")
    if theme.current_name() != "dark":
        win._toggle_theme()
    win._toggle_theme()
    assert theme.current_name() == "light"
    checked = [b for b in view.method_buttons.values() if b.isChecked()][0]
    unchecked = [b for b in view.method_buttons.values()
                 if not b.isChecked()][0]
    assert _fill(checked) != _fill(unchecked)
    assert _fill(checked) == theme.PALETTES["light"]["success_bg"].lower()
    # The chip, unchecked, looks exactly like a chip born in this theme.
    fresh = QuickFilterChip("High confidence only")
    qtbot.addWidget(fresh)
    fresh.resize(view.chip_high_confidence.size())
    assert not view.chip_high_confidence.isChecked()
    assert _fill(view.chip_high_confidence) == _fill(fresh)


def _label_has(button, colour):
    """Whether the label (inside the border, clear of the 2 px ring) is
    drawn in `colour` anywhere."""
    from PySide6.QtGui import QColor
    want = QColor(colour)
    image = button.grab().toImage()
    for y in range(4, image.height() - 4):
        for x in range(4, image.width() - 4):
            c = image.pixelColor(x, y)
            if (abs(c.red() - want.red()) + abs(c.green() - want.green())
                    + abs(c.blue() - want.blue())) < 60:
                return True
    return False


def test_the_choice_in_force_is_told_from_focus_by_its_label(win):
    """A focused button wore a brighter ring than the checked one, so the
    ring read as the choice in force (Location's "Exact" beside the
    checked "~110 m"). The checked button's LABEL is green; a ring never
    changes a label."""
    view = win._ensure_view_built("location")
    win.go_to("location")
    # The views page, as an opened exhibit shows it: grabbing buttons that
    # were never shown measured nothing a user sees.
    win.content_stack.setCurrentIndex(1)
    QApplication.processEvents()
    assert view.grouping_buttons["110m"].isVisible()
    for _ in range(2):
        green = theme.PALETTES[theme.current_name()]["primary_text"]
        on = view.grouping_buttons["110m"]
        off = view.grouping_buttons["exact"]
        off.setFocus()
        assert on.isChecked() and not off.isChecked()
        assert _label_has(on, green), theme.current_name()
        assert not _label_has(off, green), theme.current_name()
        win._toggle_theme()


def test_a_checked_button_changes_colour_never_size():
    """Qt sizes a button from its unchecked font: a bolder or larger
    checked label clipped "Hide identical columns" and a switcher's first
    letter on screen."""
    import re
    for block in re.findall(r"QPushButton:checked\s*\{([^}]*)\}",
                            theme._STYLESHEET):
        rules = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
        assert "font" not in rules and "padding" not in rules, rules
