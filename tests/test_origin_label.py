"""The leading column says Live or Carved, in words, on every row."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetricsF

from webcache.widgets.record_model import (ORIGIN_HEADING, ORIGIN_LABEL_CARVED,
                                            ORIGIN_LABEL_LIVE, ROLE_IS_CARVED)
from webcache.widgets.records_table import (CARVED_EDGE_PX, SECTION_QSS_PAD_X,
                                             RecordsTable)
from tests.fixtures import FIXTURE_COLUMNS, make_rows


@pytest.fixture
def table(qtbot):
    t = RecordsTable()
    t.set_records(list(FIXTURE_COLUMNS), make_rows(200))
    qtbot.addWidget(t)
    t.resize(1600, 700)
    t.show()
    qtbot.waitExposed(t)
    return t


def test_every_row_says_live_or_carved_in_words(table):
    model = table.model()
    seen = set()
    for r in range(model.rowCount()):
        carved = bool(model.data(model.index(r, 0), ROLE_IS_CARVED))
        label = model.headerData(r, Qt.Vertical, Qt.DisplayRole)
        assert label == (ORIGIN_LABEL_CARVED if carved else ORIGIN_LABEL_LIVE)
        seen.add(label)
    assert seen == {ORIGIN_LABEL_LIVE, ORIGIN_LABEL_CARVED}


def test_the_header_role_answers_carved_directly(table):
    model = table.model()
    for r in range(20):
        assert (model.headerData(r, Qt.Vertical, ROLE_IS_CARVED)
                == bool(model.data(model.index(r, 0), ROLE_IS_CARVED)))


def test_the_column_fits_its_widest_label_and_its_heading(table):
    """Measured in the font the QSS PAINTS (600 weight) plus the QSS
    section padding (9px each side) and border (1px) -- the two things
    the old 'advance(C) + 16' floor never counted."""
    header = table.verticalHeader()
    fm = QFontMetricsF(header.painted_font())
    widest = max(fm.horizontalAdvance(t) for t in
                 (ORIGIN_LABEL_LIVE, ORIGIN_LABEL_CARVED, ORIGIN_HEADING))
    assert header.width() >= widest + 2 * SECTION_QSS_PAD_X + 1 + CARVED_EDGE_PX


def test_the_corner_carries_the_heading(table):
    assert table.corner_button is not None
    assert ORIGIN_HEADING in table.corner_button.toolTip()
    assert table.corner_button.accessibleName() == ORIGIN_HEADING


def test_the_label_survives_a_sort_and_hiding_every_column(table):
    model = table.model()
    model.sort_by("VisitCount", True)
    for c in range(model.columnCount()):
        table.setColumnHidden(c, True)
    for r in range(model.rowCount()):
        carved = bool(model.data(model.index(r, 0), ROLE_IS_CARVED))
        assert model.headerData(r, Qt.Vertical, Qt.DisplayRole) == (
            ORIGIN_LABEL_CARVED if carved else ORIGIN_LABEL_LIVE)
