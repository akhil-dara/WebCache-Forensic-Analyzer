"""StatChip: Dashboard's five headline figures -- one big coloured number
over a small muted label. Clickable, like every other drill-through
surface in this project (see records_view.py's own module docstring): a
summary figure with nowhere to click reads as though it is the whole
truth.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from webcache.widgets.stat_chip import StatChip


@pytest.fixture
def chip(qtbot):
    c = StatChip("Total Records", accent="primary")
    qtbot.addWidget(c)
    c.resize(160, 70)
    c.show()
    return c


def test_starts_with_an_em_dash_not_a_fabricated_zero(qtbot):
    """A chip built before any figure is known must not read as though it
    already knows the figure is zero -- see the Dashboard's own
    NOT-DETERMINABLE discipline (provenance.CONTAINER_NOT_DETERMINABLE)."""
    c = StatChip("Total Records")
    qtbot.addWidget(c)
    assert c.value() == "—"


def test_set_value_updates_the_displayed_value(chip):
    chip.set_value("12,345")
    assert chip.value() == "12,345"


def test_set_value_sets_a_tooltip_when_given_one(chip):
    chip.set_value("12,345", tooltip="Live records only.")
    assert chip.toolTip() == "Live records only."


def test_clicking_emits_clicked(chip, qtbot):
    with qtbot.waitSignal(chip.clicked, timeout=1000):
        QTest.mouseClick(chip, Qt.LeftButton)


def test_uses_a_pointing_hand_cursor(chip):
    assert chip.cursor().shape() == Qt.PointingHandCursor


def test_refresh_theme_does_not_raise(chip):
    chip.refresh_theme()


# --- right-click Copy, left-click still drills through ---

def test_right_click_copies_the_displayed_figure(chip, qtbot):
    """The value/label QLabels stay DECORATIVE (a mouse-selectable child
    would swallow the drill-through click -- see their own comment in
    stat_chip.py), so the figure is copyable through a right-click menu
    instead, over the SAME displayed text set_value() shows on screen."""
    chip.set_value("1,033")
    menu = chip.build_context_menu()
    copy_action = next(a for a in menu.actions() if "copy" in a.text().lower())
    copy_action.trigger()
    assert QGuiApplication.clipboard().text() == "1,033"


def test_left_click_still_drills_through_after_the_context_menu_exists(chip, qtbot):
    with qtbot.waitSignal(chip.clicked, timeout=1000):
        QTest.mouseClick(chip, Qt.LeftButton)


def test_no_engine_import():
    import webcache.widgets.stat_chip as mod
    assert "engine" not in mod.__dict__
