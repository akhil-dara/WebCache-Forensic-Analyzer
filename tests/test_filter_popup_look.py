"""The filter popup reads as part of the application."""
import os
import re

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox

from webcache.shell import theme
from webcache.widgets.column_spec import Column
from webcache.widgets.filter_popup import FilterPopup
from webcache.widgets.record_model import RecordTableModel


def _luminance(hex_colour):
    c = QColor(hex_colour)

    def channel(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(c.red()) + 0.7152 * channel(c.green())
            + 0.0722 * channel(c.blue()))


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _rule(css, selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, "no QSS rule for %s" % selector
    props = {}
    for part in match.group(1).split(";"):
        if ":" in part:
            name, value = part.split(":", 1)
            props[name.strip()] = value.strip()
    return props


@pytest.mark.parametrize("name", ["dark", "light"])
@pytest.mark.parametrize("state", ["hover", "selected"])
def test_hovered_and_selected_values_keep_full_contrast_text(name, state):
    css = theme._STYLESHEET % theme.PALETTES[name]
    rule = _rule(css, "QDialog#filterPopup QListView#valueList::item:%s" % state)
    assert _contrast(rule["color"], rule["background"]) >= 4.5


@pytest.mark.parametrize("name", ["dark", "light"])
def test_the_operator_combo_has_an_enabled_style_in_both_themes(name):
    css = theme._STYLESHEET % theme.PALETTES[name]
    rule = _rule(css, "QComboBox")
    assert _contrast(rule["color"], rule["background"]) >= 4.5
    _rule(css, "QComboBox:disabled")
    view = _rule(css, "QComboBox QAbstractItemView")
    assert _contrast(view["color"], view["background"]) >= 4.5


@pytest.fixture
def popup(qtbot):
    col = Column("Domain", "Domain", 200, kind="domain")
    model = RecordTableModel([col], [{"Domain": "a.test"}, {"Domain": "b.test"}])
    p = FilterPopup(model, col)
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    return p


def test_the_popup_has_no_native_title_bar(popup):
    assert popup.windowFlags() & Qt.FramelessWindowHint
    assert popup.objectName() == "filterPopup"


def test_the_title_row_holds_the_label_and_a_compact_copy_button(popup):
    """The header carried "Copy column name" and "Close" as full buttons,
    squeezing the column's own title ("Last visit (UTC)" was crammed in a
    narrow popup); Close repeated Cancel and Esc. Now: the title, and a
    copy icon that still says what it does."""
    row = popup.title_row
    assert row.objectName() == "filterTitle"
    assert row.label.text() == "Domain"
    assert popup.copy_name_button.parent() is row
    assert popup.copy_name_button.text() == ""
    assert popup.copy_name_button.toolTip() == "Copy column name"
    assert popup.copy_name_button.accessibleName() == "Copy column name"
    from PySide6.QtWidgets import QPushButton
    assert not [b for b in popup.findChildren(QPushButton)
                if b.text() == "Close"]


def test_cancel_closes_it(popup, qtbot):
    from PySide6.QtWidgets import QDialogButtonBox
    popup.button_box.button(QDialogButtonBox.Cancel).click()
    qtbot.waitUntil(lambda: not popup.isVisible(), timeout=2000)


def test_the_second_condition_appears_once_the_first_is_set(popup, qtbot):
    """"And" and a second "(no condition)" were always on screen, before
    there was a first condition to join anything to."""
    assert not popup.join_box.isVisible()
    assert not popup.operator_box_2.isVisible()
    popup.operator_box.setCurrentText("contains")
    assert popup.join_box.isVisible() and popup.operator_box_2.isVisible()
    popup.operator_box.setCurrentIndex(0)          # back to no condition
    assert not popup.join_box.isVisible()



def test_escape_closes_it(popup, qtbot):
    QTest.keyClick(popup, Qt.Key_Escape)
    qtbot.waitUntil(lambda: not popup.isVisible(), timeout=2000)


def _mouse(kind, widget, local):
    return QMouseEvent(kind, QPointF(local), QPointF(widget.mapToGlobal(local)),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def test_it_moves_when_its_title_row_is_dragged(popup):
    row = popup.title_row
    before = popup.pos()
    QApplication.sendEvent(row, _mouse(QEvent.MouseButtonPress, row, QPoint(10, 10)))
    QApplication.sendEvent(row, _mouse(QEvent.MouseMove, row, QPoint(70, 50)))
    QApplication.sendEvent(row, _mouse(QEvent.MouseButtonRelease, row, QPoint(70, 50)))
    assert popup.pos() == before + QPoint(60, 40)


# --- combo arrow, value-list indicator, drag clamp ---------

def _distinct_colors(image, rect):
    return {image.pixel(x, y)
            for x in range(rect.left(), rect.right() + 1)
            for y in range(rect.top(), rect.bottom() + 1)}


@pytest.mark.parametrize("name", ["dark", "light"])
def test_the_combo_drop_down_shows_a_nonempty_arrow(qapp, qtbot, name):
    """A plain box with no arrow reads as a text field, not a menu. Renders a real QComboBox under the app's actual
    stylesheet and looks at the pixels in the drop-down's own rectangle --
    a bare bordered box (the pre-fix look) paints that region as a single
    flat colour; an arrow glyph does not."""
    theme.apply(qapp, name)
    box = QComboBox()
    box.addItems(["one", "two", "three"])
    box.resize(160, 30)
    qtbot.addWidget(box)
    box.show()
    qtbot.waitExposed(box)
    image = box.grab().toImage()
    arrow_rect = QRect(box.width() - 18, 4, 14, box.height() - 8)
    colors = _distinct_colors(image, arrow_rect)
    assert len(colors) > 1, (
        "the drop-down region painted as a single flat colour (%s theme) "
        "-- no arrow glyph" % name)


@pytest.mark.parametrize("name", ["dark", "light"])
def test_the_combo_arrow_image_the_qss_points_at_exists_on_disk(qapp, name):
    theme.apply(qapp, name)
    css = qapp.styleSheet()
    rule = _rule(css, "QComboBox::down-arrow")
    match = re.search(r"url\(([^)]+)\)", rule["image"])
    assert match, "QComboBox::down-arrow has no image url()"
    assert os.path.exists(match.group(1)), (
        "the QSS points at an arrow image that does not exist on disk")


@pytest.mark.parametrize("name", ["dark", "light"])
def test_the_value_list_indicator_is_an_empty_box_when_unticked(name):
    css = theme._STYLESHEET % theme.PALETTES[name]
    unchecked = _rule(css, "QListView#valueList::indicator")
    checked = _rule(css, "QListView#valueList::indicator:checked")
    assert "border" in unchecked
    assert unchecked.get("background") != checked.get("background"), (
        "unticked and ticked indicators share a background -- not "
        "distinguishable at a glance")


def test_dragging_the_title_row_is_clamped_to_the_screen(popup):
    row = popup.title_row
    screen = popup.window().screen()
    assert screen is not None
    avail = screen.availableGeometry()
    QApplication.sendEvent(row, _mouse(QEvent.MouseButtonPress, row, QPoint(10, 10)))
    # Drag far past any real screen in both directions.
    huge = QPoint(avail.width() + 5000, avail.height() + 5000)
    QApplication.sendEvent(row, _mouse(QEvent.MouseMove, row, huge))
    QApplication.sendEvent(row, _mouse(QEvent.MouseButtonRelease, row, huge))
    pos = popup.pos()
    assert avail.left() <= pos.x() <= avail.x() + avail.width() - popup.width()
    assert avail.top() <= pos.y() <= avail.y() + avail.height() - popup.height()
