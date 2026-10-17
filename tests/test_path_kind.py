"""The `path` column kind: local file paths, for File Access's
"Local file path" / "Saved to" columns.

A path is not a URL -- File Access shows paths belonging to the EXAMINED
machine, and this project's standing rule is "Copy, never Open" (see
records_table.py's own docstring on the context menu: "Copy, never Open.
These paths belong to the examined machine."). Two things this kind must
get right:

1. Never styled as a clickable link -- record_model.RecordTableModel.data()
   keys link styling off Column.is_link (on_click set), which a path
   column never sets, so this falls out of the SAME mechanism url/domain
   columns use rather than needing kind-specific styling code of its own.
   Pinned here anyway (at the record_model level, not just column_spec's
   own constructor) so the two facts stay tied together.
2. Selectable and copyable without opening anything -- RecordsTable
   already offers this uniformly (SelectItems selection mode, Ctrl+C,
   the "Copy cell/row/column" context menu) for every column kind; this
   file proves a path column is not somehow excluded from that.
"""
import pytest

from webcache.widgets.column_spec import KINDS, Column
from webcache.widgets.record_filter import OPERATORS_BY_KIND


def test_path_is_a_valid_kind():
    assert "path" in KINDS
    assert Column("CleanUrl", kind="path").kind == "path"


def test_path_is_not_numeric():
    assert Column("CleanUrl", kind="path").numeric is False


def test_a_path_column_declares_no_on_click_and_is_not_a_link():
    """File Access never wires on_click for its path columns -- the whole
    point is that these paths must not be openable. This just pins that a
    bare Column(kind="path") -- the shape file_access.py actually builds --
    reads as not-a-link, the same as any other non-link column."""
    assert Column("CleanUrl", kind="path").is_link is False


def test_path_offers_the_same_operators_as_text():
    """A path is filtered like any other string field -- contains, begins
    with, etc. -- not like a number or a date."""
    assert OPERATORS_BY_KIND["path"] == OPERATORS_BY_KIND["text"]


# --- rendering: a path cell must not read as a link -------------------------

def test_a_path_cell_is_not_coloured_as_a_link():
    """record_model.py's ForegroundRole branch checks col.is_link BEFORE
    anything else; a path column (no on_click) must fall through to the
    same plain-text colour a Title cell gets, never the "url" link colour
    a Domain/CleanUrl-with-on_click cell gets."""
    from PySide6.QtCore import Qt

    from webcache.widgets.record_model import RecordTableModel

    columns = [Column("LocalPath", "Local file path", kind="path")]
    rows = [{"LocalPath": r"C:\Users\alice\Downloads\report.pdf"}]
    model = RecordTableModel(columns, rows)
    ix = model.index(0, 0)
    text_color = model.data(ix, Qt.ForegroundRole)

    link_columns = [Column("CleanUrl", "Address", kind="url",
                           on_click=lambda row: None)]
    link_rows = [{"CleanUrl": "https://example.com/"}]
    link_model = RecordTableModel(link_columns, link_rows)
    link_ix = link_model.index(0, 0)
    link_color = link_model.data(link_ix, Qt.ForegroundRole)

    assert text_color != link_color


# --- selection and copy: "Copy, never Open" ----------------------------------

@pytest.fixture
def path_table(qtbot):
    from webcache.widgets.records_table import RecordsTable

    columns = [Column("EntryId", "EntryId", kind="num"),
              Column("LocalPath", "Local file path", kind="path")]
    rows = [{"EntryId": 1, "LocalPath": r"C:\Users\alice\Desktop\notes.txt"},
           {"EntryId": 2, "LocalPath": r"D:\evidence\case 12\readme.md"}]
    table = RecordsTable()
    table.set_records(columns, rows)
    qtbot.addWidget(table)
    return table


def test_a_path_cell_is_selectable(path_table):
    ix = path_table.model().index(0, 1)
    flags = path_table.model().flags(ix)
    from PySide6.QtCore import Qt
    assert bool(flags & Qt.ItemIsSelectable)


def test_a_path_cell_copies_byte_exact_including_backslashes(path_table):
    ix = path_table.model().index(0, 1)
    path_table._copy_cell(ix)
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == r"C:\Users\alice\Desktop\notes.txt"


def test_a_path_column_participates_in_a_bulk_tsv_copy(path_table):
    from PySide6.QtCore import QItemSelectionModel

    path_table.selectionModel().select(
        path_table.model().index(0, 1), QItemSelectionModel.Select)
    text = path_table.copy_selection_as_tsv()
    assert r"C:\Users\alice\Desktop\notes.txt" in text


def test_activating_a_path_cell_never_calls_on_click_it_has_none(path_table):
    """Enter/double-click on a non-link cell falls through to
    recordActivated, never a link-style on_click -- proving a path column
    behaves like any other non-link column, not a special "openable" one."""
    seen = []
    path_table.recordActivated.connect(seen.append)
    path_table.activate_cell(0, 1)
    assert len(seen) == 1
    assert seen[0]["LocalPath"] == r"C:\Users\alice\Desktop\notes.txt"
