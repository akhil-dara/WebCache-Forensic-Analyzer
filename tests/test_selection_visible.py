"""A selected row must be FINDABLE in every grid, in both
themes, on every row colour it can sit on (base, zebra, carved tint).

Measured on painted pixels, like test_browser_selection_visible: offscreen
Qt draws no glyphs, so a cell's centre is pure background."""
import re

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication

from webcache.shell import theme
from webcache.widgets.records_table import RecordsTable
from webcache.widgets.record_model import RecordTableModel
from tests.fixtures import FIXTURE_COLUMNS, make_rows
from tests.test_carved_readability import _contrast_ratio

VISIBLE_FLOOR = 1.5
TEXT_FLOOR = 4.5
NAMES = ["dark", "light"]


@pytest.fixture
def themed():
    app = QApplication.instance()
    before = theme.current_name()
    yield lambda name: theme.apply(app, name)
    theme.apply(app, before)


def _table(qtbot):
    table = RecordsTable()
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(60))
    table.setModel(model)
    table.resize(900, 600)
    table.show()
    qtbot.addWidget(table)
    qtbot.waitExposed(table)
    return table, model


def _carved(model, row):
    return model.row_at(row)["Origin"].startswith("Carved")


def _pixel(table, row, col=1, dx=4):
    image = table.viewport().grab().toImage()
    rect = table.visualRect(table.model().index(row, col))
    x = rect.left() + dx
    return image.pixelColor(x, rect.center().y()).name()


def _select(table, row):
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.selectRow(row)
    table.setCurrentIndex(table.model().index(row, 1))
    QApplication.processEvents()


def _visible_rows(table, model, carved):
    rows = [r for r in range(model.rowCount())
            if _carved(model, r) == carved
            and table.visualRect(model.index(r, 1)).isValid()
            and table.visualRect(model.index(r, 1)).bottom()
            < table.viewport().height()]
    assert rows, "fixture shows no %s row" % ("carved" if carved else "live")
    return rows


@pytest.mark.parametrize("name", NAMES)
def test_a_selected_live_row_stands_out_from_base_and_zebra(
        qtbot, themed, name):
    themed(name)
    table, model = _table(qtbot)
    row = _visible_rows(table, model, False)[0]
    _select(table, row)
    selected = _pixel(table, row)
    p = theme.PALETTES[name]
    for other in (p["base"], p["row_alt"]):
        assert _contrast_ratio(selected, other) >= VISIBLE_FLOOR, (
            name, selected, other)


@pytest.mark.parametrize("name", NAMES)
def test_a_selected_carved_row_stands_out_from_the_carved_tint(
        qtbot, themed, name):
    themed(name)
    table, model = _table(qtbot)
    row = _visible_rows(table, model, True)[0]
    _select(table, row)
    selected = _pixel(table, row)
    p = theme.PALETTES[name]
    for other in (p["base"], p["row_alt"], p["carved_row"]):
        assert _contrast_ratio(selected, other) >= VISIBLE_FLOOR, (
            name, selected, other)


@pytest.mark.parametrize("name", NAMES)
def test_text_on_a_selected_row_keeps_full_contrast(qtbot, themed, name):
    themed(name)
    table, model = _table(qtbot)
    row = _visible_rows(table, model, True)[0]
    _select(table, row)
    selected = _pixel(table, row)
    text = theme.PALETTES[name]["text"]
    assert _contrast_ratio(selected, text) >= TEXT_FLOOR, (name, selected)
    qss = re.sub(r"/\*.*?\*/", "", QApplication.instance().styleSheet(),
                 flags=re.S)
    colour = None
    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", qss):
        if selector.strip() == "QTableView::item:selected":
            found = re.search(r"(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})", body)
            colour = found.group(1).lower() if found else None
    assert colour == text.lower(), name


@pytest.mark.parametrize("name", NAMES)
def test_the_selected_row_carries_an_accent_bar(qtbot, themed, name):
    themed(name)
    table, model = _table(qtbot)
    rows = _visible_rows(table, model, False)
    first_col = table.horizontalHeader().logicalIndex(0)
    _select(table, rows[0])
    accent = theme.PALETTES[name]["primary"].lower()
    assert _pixel(table, rows[0], first_col, dx=1).lower() == accent
    assert _pixel(table, rows[1], first_col, dx=1).lower() != accent
