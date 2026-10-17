"""The landed row must be SEEN to be selected, in both themes.

The global QTableView selection (alt_base on base/row_alt) is ~1.1:1 --
a row an examiner is told is selected and cannot find. Measured on the
painted pixels, not on the stylesheet text: offscreen Qt draws no glyphs,
so a cell's centre is pure background.
"""
import re

import pytest
from PySide6.QtWidgets import QApplication

from webcache.shell import theme
from webcache.views.browser import TableBrowserView
from tests.test_carved_readability import _contrast_ratio
from tests.test_table_browser_view import _StubParser

VISIBLE_FLOOR = 1.5
TEXT_FLOOR = 4.5


@pytest.fixture
def themed():
    app = QApplication.instance()
    before = theme.current_name()
    yield lambda name: theme.apply(app, name)
    theme.apply(app, before)


def _landed(qtbot, row=5):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.resize(900, 600)
    v.set_parser(_StubParser(row_count=40))
    v.show()
    qtbot.waitExposed(v)
    assert v.show_row("Container_2", row)
    QApplication.processEvents()
    return v


def _cell_pixel(v, row, col=1):
    image = v.grid.viewport().grab().toImage()
    rect = v.grid.visualRect(v.grid.model().index(row, col))
    return image.pixelColor(rect.center()).name()


def _header_pixel(v, row):
    header = v.grid.verticalHeader()
    image = header.grab().toImage()
    y = header.sectionViewportPosition(row) + header.sectionSize(row) // 2
    return image.pixelColor(header.width() // 2, y).name()


@pytest.mark.parametrize("name", ["dark", "light"])
def test_the_landed_row_stands_out_from_both_row_colours(qtbot, themed, name):
    themed(name)
    v = _landed(qtbot)
    selected = _cell_pixel(v, 5)
    for neighbour in (4, 6):            # both zebra stripes
        other = _cell_pixel(v, neighbour)
        assert _contrast_ratio(selected, other) >= VISIBLE_FLOOR, (
            name, selected, other)


@pytest.mark.parametrize("name", ["dark", "light"])
def test_text_on_the_landed_row_keeps_full_contrast(qtbot, themed, name):
    themed(name)
    v = _landed(qtbot)
    selected = _cell_pixel(v, 5)
    text = theme.PALETTES[name]["text"]
    assert _contrast_ratio(selected, text) >= TEXT_FLOOR, (name, selected)
    # And the text painted on it IS the text colour: without its own
    # `color`, a selected item takes the global selection-color (the
    # window colour -- dark on dark).
    assert _selected_rule_colour(QApplication.instance().styleSheet(),
                                 "browserGrid") == text.lower(), name


def _selected_rule_colour(qss, object_name):
    """The `color` declared by the ::item:selected rule scoped to
    `object_name`, or None."""
    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", qss):
        if object_name in selector and "::item:selected" in selector:
            found = re.search(r"(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})", body)
            if found:
                return found.group(1).lower()
    return None


@pytest.mark.parametrize("name", ["dark", "light"])
def test_the_landed_rows_number_is_marked_too(qtbot, themed, name):
    themed(name)
    v = _landed(qtbot)
    assert _contrast_ratio(_header_pixel(v, 5), _header_pixel(v, 4)) \
        >= VISIBLE_FLOOR, name


def _unscoped_list_selected_colour(qss):
    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", qss):
        if selector.strip() == "QListWidget::item:selected":
            found = re.search(r"(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})", body)
            return found.group(1).lower() if found else None
    return None


@pytest.mark.parametrize("name", ["dark", "light"])
def test_the_selected_table_name_is_readable(qtbot, themed, name):
    """The table D1/D3 land on is named, selected, in the list on the
    left. With no `color` of its own a selected list item took the global
    selection-color -- the window colour, dark text on a dark row."""
    themed(name)
    palette = theme.PALETTES[name]
    colour = _unscoped_list_selected_colour(
        QApplication.instance().styleSheet())
    assert colour == palette["text"].lower(), name
    assert _contrast_ratio(colour, palette["alt_base"]) >= TEXT_FLOOR


@pytest.mark.parametrize("name", ["dark", "light"])
def test_the_column_headings_are_not_marked_by_a_row(qtbot, themed, name):
    """A landed ROW marks its row number; the column headings above it
    are not what was selected and must not light up with it."""
    themed(name)
    v = _landed(qtbot)
    header = v.grid.horizontalHeader()
    image = header.grab().toImage()
    x = header.sectionViewportPosition(1) + header.sectionSize(1) // 2
    heading = image.pixelColor(x, header.height() // 2).name()
    assert _contrast_ratio(heading, _header_pixel(v, 5)) >= VISIBLE_FLOOR, (
        name, heading)
