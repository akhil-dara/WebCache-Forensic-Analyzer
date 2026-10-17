"""Measured from painted pixels, in both themes: text the app colours
emerald stays readable, the value a keyboard user is on in the filter list
can be seen, and every keyboard-reachable editor and list shows a ring."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QDialog, QPlainTextEdit,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QLineEdit)

from webcache.shell import theme
from webcache.widgets.value_list import ValueList

THEMES = ("dark", "light")


def _lum(c):
    v = [x / 255 for x in (c.red(), c.green(), c.blue())]
    v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]


def contrast(a, b):
    a, b = _lum(QColor(a)), _lum(QColor(b))
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@pytest.fixture(params=THEMES)
def themed(request, qtbot):
    app = QApplication.instance()
    theme.apply(app, request.param)
    yield request.param
    theme.apply(app, "dark")


def test_emerald_text_meets_4_5_to_1_on_every_surface(themed):
    for surface in ("window", "base", "alt_base", "row_alt", "success_bg"):
        assert contrast(theme.color("primary_text"),
                        theme.color(surface)) >= 4.5, (themed, surface)


def test_the_outline_export_button_label_is_readable(themed, qtbot):
    button = QPushButton("Export view")
    button.setProperty("outline", True)
    qtbot.addWidget(button)
    button.resize(160, 34)
    button.show()
    qtbot.waitExposed(button)
    img = button.grab().toImage()
    bg = img.pixelColor(8, img.height() // 2)
    best = max(contrast(img.pixelColor(x, y), bg)
               for x in range(10, img.width() - 10)
               for y in range(6, img.height() - 6))
    assert best >= 4.5, (themed, bg.name(), best)


def _value_list(qtbot):
    dialog = QDialog()
    dialog.setObjectName("filterPopup")
    QVBoxLayout(dialog)
    vlist = ValueList(dialog)
    dialog.layout().addWidget(vlist)
    qtbot.addWidget(dialog)
    dialog.resize(320, 260)
    vlist.value_model.set_items(["value %d" % i for i in range(8)],
                                [1] * 8, [True] * 8)
    dialog.show()
    qtbot.waitExposed(dialog)
    vlist.setFocus()
    return dialog, vlist


def test_the_value_the_keyboard_is_on_can_be_seen(themed, qtbot):
    dialog, vlist = _value_list(qtbot)
    QTest.keyClick(vlist, Qt.Key_Down)
    QTest.keyClick(vlist, Qt.Key_Down)
    current = vlist.visualRect(vlist.currentIndex())
    other = vlist.visualRect(vlist.model().index(5, 0))
    img = vlist.viewport().grab().toImage()
    x = current.right() - 12
    on = img.pixelColor(x, current.center().y())
    off = img.pixelColor(x, other.center().y())
    # The grids' own selection floor (row_selected on base) is 1.8:1.
    assert contrast(on, off) >= 1.8, (themed, on.name(), off.name())


def _edge_changes_on_focus(widget, other):
    """The widget's top border pixel, unfocused vs focused."""
    other.setFocus()
    QApplication.processEvents()
    before = widget.grab().toImage().pixelColor(widget.width() // 2, 0)
    widget.setFocus()
    QApplication.processEvents()
    after = widget.grab().toImage().pixelColor(widget.width() // 2, 0)
    return before, after


@pytest.mark.parametrize("make", ["notes", "tree", "values"])
def test_editors_and_lists_show_where_the_keyboard_is(themed, qtbot, make):
    host = QDialog()
    host.setObjectName("filterPopup")
    QVBoxLayout(host)
    if make == "notes":
        widget = QPlainTextEdit()
    elif make == "tree":
        widget = QTreeWidget()
        QTreeWidgetItem(widget, ["2026"])
    else:
        widget = ValueList()
        widget.value_model.set_items(["a", "b"], [1, 2], [True, True])
    host.layout().addWidget(widget)
    other = QLineEdit()          # somewhere else for the keyboard to be
    host.layout().addWidget(other)
    qtbot.addWidget(host)
    host.resize(300, 200)
    host.show()
    qtbot.waitExposed(host)
    host.activateWindow()
    before, after = _edge_changes_on_focus(widget, other)
    assert after == theme.color("primary"), (themed, make, before.name(),
                                             after.name())
    assert before != after


def test_a_filled_green_button_label_is_readable(themed, qtbot):
    """Open Database, Export bundle: the one filled button style. Light
    theme measured 2.99:1 (near-white on its green)."""
    button = QPushButton("Export bundle")
    button.setProperty("accent", True)
    qtbot.addWidget(button)
    button.resize(160, 34)
    button.show()
    qtbot.waitExposed(button)
    img = button.grab().toImage()
    bg = img.pixelColor(8, img.height() // 2)
    best = max(contrast(img.pixelColor(x, y), bg)
               for x in range(10, img.width() - 10)
               for y in range(6, img.height() - 6))
    assert best >= 4.5, (themed, bg.name(), best)


def test_selected_text_in_a_field_is_readable(themed):
    """Selected text in a line edit or the notes field: the same pairing."""
    assert contrast(theme.color("on_primary"), theme.color("primary")) >= 4.5
