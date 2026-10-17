"""The two "whole value" surfaces -- the record dialog's
field table and the Table Browser's whole-row view -- are where every
grid, guard and tooltip sends an examiner for the value that did not fit.
Both wrapped with Qt's plain word wrap, which lays a run with no break
opportunity out as ONE over-long line and cuts it at the cell edge: a
URL ending in a 200-character token showed two lines and lost the rest.

They must wrap such a run like RecordsTable does (WrappingDelegate), and
the invisible break points must never reach what is copied."""
import pytest
from PySide6.QtGui import QGuiApplication

from webcache.shell.record_detail import RecordDetailDialog
from tests.test_detail_fields import history_row
from tests.test_table_row_view import _dialog as _row_dialog

#: Synthetic: a URL whose last 200 characters hold no break opportunity.
TOKEN_URL = "https://example.test/p?q=" + "Z" * 200


@pytest.fixture(autouse=True)
def _scratch_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")


def _row_showing(table, text):
    for r in range(table.rowCount()):
        item = table.item(r, 1)
        if item is not None and item.text() == text:
            return r
    raise AssertionError("no row shows the value")


def _assert_whole(table, r):
    """At least four lines: the cut row was one or two (24 px), and the
    whole run needs more at any column narrower than itself."""
    fm = table.fontMetrics()
    assert fm.horizontalAdvance(TOKEN_URL) > 2 * table.columnWidth(1), (
        "the column is too wide for this test to mean anything")
    assert table.rowHeight(r) >= 4 * fm.lineSpacing(), (
        "row %d px, line %d px" % (table.rowHeight(r), fm.lineSpacing()))


def test_the_record_dialog_wraps_a_run_with_no_break_opportunity(qtbot):
    dialog = RecordDetailDialog(history_row(CleanUrl=TOKEN_URL))
    dialog.resize(900, 700)
    dialog.show()
    qtbot.waitExposed(dialog)
    table = dialog.table
    r = _row_showing(table, TOKEN_URL)
    table.resizeRowsToContents()
    _assert_whole(table, r)
    assert dialog.copy_field(dialog._field_index(r))
    assert QGuiApplication.clipboard().text() == TOKEN_URL
    dialog.close()


def test_the_whole_row_view_wraps_a_run_with_no_break_opportunity(qtbot):
    dialog = _row_dialog(qtbot, ["EntryId", "Url"], [[7, TOKEN_URL]])
    dialog.resize(900, 700)
    dialog.show()
    qtbot.waitExposed(dialog)
    table = dialog.table
    r = _row_showing(table, TOKEN_URL)
    table.resizeRowsToContents()
    _assert_whole(table, r)
    assert dialog.copy_field(r)
    assert QGuiApplication.clipboard().text() == TOKEN_URL
