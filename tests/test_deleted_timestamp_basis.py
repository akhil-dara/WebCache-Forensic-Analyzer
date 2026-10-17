"""Deleted Records' one Timestamp column holds two kinds of evidence by
design (recovery.py's docstring): a structured record's own time, and a
FILETIME merely found NEAR a carved string. Method and Confidence say how
sure each row is -- but the CELL never said which kind it was, and in a
real exhibit the two sat on alternate rows in identical green.

Each cell now names its basis on hover, and the heading says the column
is mixed, so a nearby time is never read as a visit time.
"""
import datetime

from PySide6.QtCore import Qt

from tests.test_row_is_a_record import (_StubEngine, _string_artifact,
                                        _struct_record)
from webcache.shell import recovery_loader

NEAR = datetime.datetime(2026, 2, 17, 15, 56, 29,
                         tzinfo=datetime.timezone.utc)


def _rows():
    return recovery_loader.deleted_records_rows(_StubEngine(
        [_struct_record()], [_string_artifact(NearbyFiletime=NEAR)]))


def test_each_row_names_where_its_time_came_from():
    struct, string = _rows()
    assert "record's own" in struct["TimestampBasis"]
    assert "near the carved bytes" in string["TimestampBasis"]
    assert "not" in string["TimestampBasis"] and "visit" in string["TimestampBasis"]


def test_the_cell_tooltip_and_the_heading_say_so(qtbot):
    from webcache.views.recovery import RecoveryView
    from webcache.widgets.record_model import RecordTableModel
    view = RecoveryView()
    qtbot.addWidget(view)
    col = next(c for c in view.COLUMNS if c.key == "Timestamp")
    model = RecordTableModel([col], _rows())
    tips = [model.data(model.index(r, 0), Qt.ToolTipRole) for r in (0, 1)]
    assert "near the carved bytes" in tips[1]
    assert "near the carved bytes" not in tips[0]
    heading = model.headerData(0, Qt.Horizontal, Qt.ToolTipRole)
    assert "two kinds" in heading


def test_the_basis_is_a_column_an_export_writes(qtbot):
    from webcache.views.recovery import RecoveryView
    view = RecoveryView()
    qtbot.addWidget(view)
    col = next(c for c in view.COLUMNS if c.key == "TimestampBasis")
    assert col.optional, "hidden on screen; the cell's tooltip says it"
