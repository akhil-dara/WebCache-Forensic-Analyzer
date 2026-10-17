""""Read from" names WHICH column a time came from in a few words; the
full clock statement for an MSHist record is one hover away.

Found on a real exhibit's Timeline: every MSHist row's "Read from" cell
held the whole clock sentence ("...stored as LOCAL wall-clock by an
MSHist container; UTC derived with UTC+05:30, the offset the History
record of the same visit shows (INF)"), six lines tall in a 210-pixel
column, so a day's records took three screens. The sentence is a
statement about the value and stays whole in the tooltip, the record
dialog and every export; the grid shows its gist.
"""
from PySide6.QtCore import Qt

from webcache.engine import local_clock
from webcache.views.records_view import member_record_columns
from webcache.widgets.column_spec import display_text

HEAD = "ModifiedTime (visit written)"
DERIVED = "%s — %s" % (HEAD, local_clock.LOCAL_DERIVED_NOTE % (
    "UTC+05:30", local_clock.SOURCE_TWIN))
NO_ZONE = "%s — %s" % (HEAD, local_clock.LOCAL_NO_ZONE_NOTE)


def _read_from():
    return next(c for c in member_record_columns() if c.key == "KeyTimeBasis")


def test_a_derived_utc_reads_as_its_gist():
    assert display_text(DERIVED, _read_from()) == (
        "%s — LOCAL clock, UTC derived (INF)" % HEAD)


def test_no_zone_reads_as_its_gist():
    assert display_text(NO_ZONE, _read_from()) == (
        "%s — LOCAL clock, no UTC stated" % HEAD)


def test_an_ordinary_basis_is_shown_whole():
    assert display_text(HEAD, _read_from()) == HEAD


def test_the_full_statement_is_the_tooltip(qtbot):
    from webcache.widgets.record_model import RecordTableModel as RecordModel
    model = RecordModel([_read_from()], [{"KeyTimeBasis": DERIVED}])
    tip = model.data(model.index(0, 0), Qt.ToolTipRole)
    assert "the offset the History record of the same visit shows" in tip
