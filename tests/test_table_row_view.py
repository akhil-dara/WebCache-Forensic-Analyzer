"""The Table Browser's row view: ONE raw ESE row, read vertically.

WHAT IT CLOSES. The Table Browser shows raw tables as a wide grid, and a
grid can only ever show a PREVIEW of a long value -- 48 bytes of hex, or
400 escaped characters, then a count of what it is not showing. A binary
column reads as "A0 00 00 00 ... (8,108 bytes total)" in a cell four
centimetres wide, which is neither readable nor copyable. Every other
record surface in this application opens one record vertically, as field
and value; the one view holding the values nothing has interpreted did
not.

WHAT THIS FILE PROVES AND WHAT IT DOES NOT. table_browser_loader's own
tests already prove the shaping (that a truncated cell keeps its whole
value). This file proves what the DIALOG does with a shaped row: every
column present in the table's own order, the value shown whole, the
absence of a value stated rather than left blank, and nothing prettified
on the way -- the caveat this whole view exists under.

The stub SUBCLASSES WebCacheParser without calling its __init__ (no real
ESE database exists on this machine for CI to open) so raw_type_name()/
raw_rendering() are the REAL methods -- the same reason
test_table_browser_loader.py gives for doing it that way.
"""
import pytest

from webcache.engine.ese_parser import WebCacheParser
from webcache.shell import table_browser_loader
from webcache.shell.table_row_detail import TableRowDialog


@pytest.fixture(autouse=True)
def _settings_go_somewhere_disposable(tmp_path, monkeypatch):
    """No test in this file may touch the real settings.json.

    autouse and not a matter of remembering: this dialog can persist a
    layout preference, and a draft of the record dialog's own tests wrote
    `record_detail_blob_open` straight into the checkout's settings.json
    -- found by looking, in the file, after a run. A harness has done
    worse here: an 820x360 window geometry saved by one went on to be the
    size the application opened at on the examiner's machine.
    """
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")


class _StubParser(WebCacheParser):
    """Deliberately skips WebCacheParser.__init__ -- see the module
    docstring."""

    def __init__(self, columns, rows):
        self._columns = columns
        self._rows = rows
        self.containers_meta = [
            {"ContainerId": 2, "TableName": "Container_2",
             "Directory": r"C:\case\History.IE5"}]

    def get_table_rows_raw(self, table_name, limit=200, offset=0):
        return self._columns, self._rows[offset:offset + limit]

    def get_table_row_count(self, table_name):
        return len(self._rows)

    def get_table_display_name(self, table_name):
        return table_name

    def get_table_type(self, table_name):
        return "History"

    def get_tables_grouped(self):
        return {}


BLOB = bytes(range(200))
LONG_TEXT = "https://example.invalid/" + "q" * 900


def _page(columns, rows):
    """A real loader page, so these tests run against the rendering rules
    the application actually uses rather than a hand-rolled stand-in."""
    return table_browser_loader.table_page(
        _StubParser(columns, rows), "Container_2")


def _dialog(qtbot, columns, rows, row=0, **kw):
    page = _page(columns, rows)
    dialog = TableRowDialog(page["columns"], page["rows"][row],
                            table=page["display_name"], **kw)
    qtbot.addWidget(dialog)
    return dialog


def _field_names(dialog):
    return [dialog.table.item(r, 0).text()
            for r in range(dialog.table.rowCount())]


def _value_at(dialog, row):
    return dialog.table.item(row, 1).text()


# --- every column, in the table's own order ------------------------------

def test_the_row_view_lists_every_column_of_the_row(qtbot):
    columns = ["EntryId", "Url", "AccessedTime", "ResponseHeaders"]
    dialog = _dialog(qtbot, columns,
                     [[7, "http://example.invalid/", 133535904000000000, BLOB]])
    assert _field_names(dialog) == columns


def test_the_columns_keep_the_tables_own_order_not_an_alphabetical_one(qtbot):
    """A raw table's column ORDER is part of what it is -- the row view
    must not reshuffle it into something tidier, which would silently
    disagree with the grid the examiner just came from."""
    columns = ["Zeta", "Alpha", "Middle"]
    dialog = _dialog(qtbot, columns, [["z", "a", "m"]])
    assert _field_names(dialog) == columns


def test_every_column_is_present_even_where_it_holds_nothing(qtbot):
    dialog = _dialog(qtbot, ["A", "B", "C"], [["x", None, ""]])
    assert _field_names(dialog) == ["A", "B", "C"]
    assert dialog.table.rowCount() == 3


# --- the value, in full --------------------------------------------------

def test_a_long_value_is_shown_here_in_full(qtbot):
    """The grid and this view read the same whole value;
    the grid caps what it paints, this view shows all of it."""
    page = _page(["Url"], [[LONG_TEXT]])
    assert page["rows"][0][0]["text"] == LONG_TEXT
    dialog = _dialog(qtbot, ["Url"], [[LONG_TEXT]])
    shown = _value_at(dialog, 0)
    assert shown == LONG_TEXT
    assert "characters total" not in shown


def test_the_shown_value_is_the_stored_rendering_not_a_prettified_one(qtbot):
    """The caveat this view lives under: raw ESE tables exactly as
    stored, with no interpretation applied. A FILETIME-shaped integer is
    a number here, and a NUL stays visible as an escape."""
    filetime_shaped = 133535904000000000
    dialog = _dialog(qtbot, ["When", "Host"],
                     [[filetime_shaped, "exa\x00mple.invalid"]])
    assert _value_at(dialog, 0) == str(filetime_shaped)
    assert _value_at(dialog, 1) == r"exa\x00mple.invalid"


def test_the_column_type_is_stated_beside_the_value(qtbot):
    """What the database stored, said rather than guessed at from how the
    value happens to look."""
    dialog = _dialog(qtbot, ["N", "T", "B"], [[42, "x", BLOB]])
    types = [dialog.table.item(r, 2).text()
             for r in range(dialog.table.rowCount())]
    assert types == ["integer", "text", "binary"]


# --- an absence is stated, never left blank -------------------------------

def test_a_null_column_states_that_it_holds_nothing(qtbot):
    """A blank cell in a field list reads as a tool that failed to render
    something. "Nothing is stored in this column" is a fact about the
    row and has to be said in words."""
    dialog = _dialog(qtbot, ["Missing"], [[None]])
    assert _value_at(dialog, 0).strip() != ""
    assert "null" in _value_at(dialog, 0).lower()
    assert dialog.field_at(0).is_absent


def test_a_zero_length_string_is_told_apart_from_a_null(qtbot):
    """Both are empty on screen and they are not the same fact: one is a
    column with no value at all, the other is a stored, empty string."""
    dialog = _dialog(qtbot, ["Null", "Empty"], [[None, ""]])
    assert _value_at(dialog, 0) != _value_at(dialog, 1)
    assert "empty" in _value_at(dialog, 1).lower()
    assert dialog.field_at(1).is_absent


# --- saying what is on screen ---------------------------------------------

def test_the_dialog_names_the_table_and_the_row_it_is_showing(qtbot):
    dialog = _dialog(qtbot, ["A"], [["x"]], row_number=41, row_count=1200)
    said = dialog.identity_label.full_text()
    assert "Container_2" in said
    assert "41" in said
    assert "1,200" in said


def test_the_count_line_states_the_number_of_columns(qtbot):
    dialog = _dialog(qtbot, ["A", "B", "C"], [[1, 2, 3]])
    assert "3" in dialog.count_label.text()
    assert "column" in dialog.count_label.text().lower()


def test_the_dialog_repeats_the_views_own_caveat(qtbot):
    """This surface is reached from the one view that promises no
    interpretation, and a dialog that dropped the caveat would be the
    place an examiner forgot it."""
    dialog = _dialog(qtbot, ["A"], [["x"]])
    assert "no interpretation" in dialog.caveat_label.text().lower()


# --- binary: the SAME hex viewer, never a second one ---------------------
#
# A binary cell is the reason this surface is worth building at all: in
# the grid it is truncated hex that can be neither read nor copied. The
# viewer that reads it already exists and is mounted by the record detail
# dialog; the requirement is that this row reuses it, so a column nobody
# ever wrote a decoder for still gets a hex dump and a strings list.


@pytest.fixture
def themed():
    """The application's own stylesheet, in force for the test.

    Both halves of the guard are restored on teardown -- theme.apply() is
    a deliberate no-op when its module-level `_current` and
    `_last_applied_app` already name the app and theme being asked for,
    so restoring the stylesheet alone leaves the next apply() with
    nothing to do and every later test measuring an unstyled window. That
    is a mistake this project has already paid for once.
    """
    from PySide6.QtWidgets import QApplication

    from webcache.shell import theme

    app = QApplication.instance()
    sheet, current, owner = (app.styleSheet(), theme._current,
                             theme._last_applied_app)
    theme.apply(app, "dark")
    yield app
    app.setStyleSheet(sheet)
    theme._current, theme._last_applied_app = current, owner


@pytest.fixture
def build(qtbot):
    """A dialog at the real window's size, torn down by hand.

    By hand because WA_DeleteOnClose destroys the C++ object on close and
    pytest-qt's own teardown would then call close() on a dead pointer --
    the reason the record dialog's room tests build theirs the same way.
    """
    from PySide6.QtWidgets import QWidget

    made = []

    def _build(columns, rows, row=0, w=1279, h=724, **kw):
        page = _page(columns, rows)
        parent = QWidget()
        made.append(parent)
        parent.resize(w + 260, h + 120)
        parent.show()
        dialog = TableRowDialog(page["columns"], page["rows"][row], parent,
                                table=page["display_name"], **kw)
        made.append(dialog)
        dialog.resize(w, h)
        dialog.show()
        qtbot.waitExposed(dialog)
        # Twice, with the event loop in between: the first resize lands
        # before the dialog has been laid out, so the splitter's own
        # height is still zero and every size computed from it is
        # computed from nothing.
        dialog.resize(w, h)
        qtbot.wait(20)
        return dialog

    yield _build
    for widget in reversed(made):
        try:
            widget.close()
        except RuntimeError:
            pass


def test_a_binary_column_is_shown_in_the_record_dialogs_own_hex_viewer(qtbot):
    from webcache.widgets.hex_view import BlobPane

    dialog = _dialog(qtbot, ["Id", "ResponseHeaders"], [[1, BLOB]])
    assert dialog.blob_area is not None, "a row carrying bytes has no viewer"
    panes = [dialog.blob_area.widget(i)
             for i in range(dialog.blob_area.count())]
    assert panes and all(isinstance(p, BlobPane) for p in panes)


def test_every_bytes_column_gets_its_own_tab_named_for_the_column(qtbot):
    dialog = _dialog(qtbot, ["A", "First", "B", "Second"],
                     [["x", BLOB, 2, b"\x01\x02\x03"]])
    labels = [dialog.blob_area.tabText(i)
              for i in range(dialog.blob_area.count())]
    assert len(labels) == 2
    assert labels[0].startswith("First") and "200 bytes" in labels[0]
    assert labels[1].startswith("Second") and "3 bytes" in labels[1]


def test_the_viewer_is_built_through_the_shared_helpers_not_a_second_copy(
        qtbot, monkeypatch):
    """blob_source.blobs_for_cells() and record_detail.build_blob_tabs()
    are what the rest of the application already uses to turn bytes into
    a viewer. A parallel implementation here would be one that forgets
    the export guard, or the tab tooltip, or the byte count."""
    from webcache.shell import blob_source as bs
    from webcache.shell import record_detail as rd

    calls = []
    real_sources, real_tabs = bs.blobs_for_cells, rd.build_blob_tabs
    monkeypatch.setattr(bs, "blobs_for_cells",
                        lambda *a, **k: calls.append("sources")
                        or real_sources(*a, **k))
    monkeypatch.setattr(rd, "build_blob_tabs",
                        lambda *a, **k: calls.append("tabs")
                        or real_tabs(*a, **k))
    _dialog(qtbot, ["B"], [[BLOB]])
    assert calls == ["sources", "tabs"]


def test_a_row_with_no_bytes_has_no_viewer_at_all(qtbot):
    """No empty pane, no bar saying there is nothing: a region that
    states there are no bytes is a region taking room from the columns
    to say so."""
    dialog = _dialog(qtbot, ["A", "B"], [["x", 2]])
    assert dialog.blob_area is None
    assert dialog.blob_region is None
    assert dialog._splitter.count() == 1


def test_activating_a_binary_column_opens_that_columns_own_tab(qtbot):
    dialog = _dialog(qtbot, ["First", "Text", "Second"],
                     [[BLOB, "x", b"\x09\x09"]])
    second = [i for i, f in enumerate(dialog.fields) if f.name == "Second"][0]
    assert dialog.activate_field(second) is True
    assert dialog.blob_area.currentIndex() == dialog.blob_pane_for("Second")
    assert "Second" in dialog.status_label.text()


def test_copying_a_binary_column_refuses_rather_than_copying_a_summary(qtbot):
    """"200 bytes · shown in the hex viewer below" is a sentence this
    tool composed. Copied undecorated it is indistinguishable from a
    stored value, which is the same ruling the record dialog makes for
    its own binary rows."""
    dialog = _dialog(qtbot, ["Blob"], [[BLOB]])
    assert dialog.copy_field(0) is False
    assert "hex viewer" in dialog.status_label.text().lower()


def test_the_bytes_can_be_folded_away_to_a_bar_that_still_names_them(qtbot):
    """Folded to NOTHING, a row's binary half could disappear without the
    examiner having been told it existed -- which is why the record
    dialog's BlobRegion folds to a bar rather than to zero. The same
    widget, so the same guarantee."""
    dialog = _dialog(qtbot, ["ResponseHeaders"], [[BLOB]])
    dialog.blob_region.set_expanded(False)
    assert dialog.blob_region.is_expanded() is False
    said = dialog.blob_region.toggle_button.full_text()
    assert "ResponseHeaders" in said and "200 bytes" in said
    assert dialog.toggle_blob_region() is True


def test_with_the_viewer_open_the_columns_keep_their_floor(themed, build):
    """The room lesson from the record dialog, on this surface: a viewer
    that costs 332px whether the row has three columns or thirty must not
    be allowed to squeeze the row itself down to two rows."""
    from webcache.shell import record_detail as rd

    dialog = build(["A", "B", "ResponseHeaders"], [[1, "x", BLOB]])
    dialog.blob_region.set_expanded(True, deliberate=False)
    dialog._apply_splitter_sizes(force=True)
    fields_px = dialog._splitter.sizes()[0]
    assert fields_px >= rd._FIELDS_FLOOR_PX, (
        "the columns got %dpx, under the %dpx floor"
        % (fields_px, rd._FIELDS_FLOOR_PX))


# --- copy: the accelerator that is printed is the one that runs ----------
#
# The record dialog had to learn this exact lesson: its field menu printed
# "Copy value  Ctrl+C" beside the byte-exact action while Ctrl+C ran a
# different one, so an examiner pressed the key printed next to what they
# wanted and pasted a labelled string instead. A printed accelerator that
# does something else is worse than no accelerator at all.


def _select(dialog, row):
    """Exactly this row, stated explicitly.

    setCurrentCell()'s effect on the SELECTION depends on the modifier
    keys Qt believes are held, and one leaks across test files: running
    test_record_detail_dialog.py first left Ctrl "down" as far as
    QGuiApplication was concerned, so this helper produced current=1
    with selected=[0, 1] and a copy of two columns. Verified by probing
    the selection at copy time, not inferred.
    """
    from PySide6.QtCore import QItemSelectionModel
    dialog.table.setCurrentCell(
        row, 0, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)


def test_ctrl_c_in_the_column_list_copies_that_columns_value(qtbot):
    """QTableWidget claims QKeySequence.Copy for ITSELF through Qt's
    ShortcutOverride mechanism -- verified in this project once already
    (views/browser.py's _CopyableTableWidget exists for that reason). A
    dialog-level handler is not reached while the list has focus, so the
    Ctrl+C the menu advertises must be shown to arrive, not assumed."""
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest

    dialog = _dialog(qtbot, ["Id", "Url"], [[7, "http://example.invalid/a"]])
    dialog.show()
    qtbot.waitExposed(dialog)
    _select(dialog, 1)
    QGuiApplication.clipboard().setText("PREVIOUS")
    QTest.keyClick(dialog.table, _Qt.Key_C, _Qt.ControlModifier)
    assert QGuiApplication.clipboard().text() == "http://example.invalid/a"


def test_enter_in_the_column_list_copies_that_columns_value(qtbot):
    """QAbstractItemView consumes Enter -- it means "edit this cell" to a
    view even with NoEditTriggers set -- so this route has to be taken
    before the view sees it."""
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest

    dialog = _dialog(qtbot, ["Id", "Url"], [[7, "http://example.invalid/b"]])
    dialog.show()
    qtbot.waitExposed(dialog)
    _select(dialog, 1)
    QGuiApplication.clipboard().setText("PREVIOUS")
    QTest.keyClick(dialog.table, _Qt.Key_Return)
    assert QGuiApplication.clipboard().text() == "http://example.invalid/b"


def test_the_menu_prints_the_accelerator_that_actually_runs(qtbot):
    from PySide6.QtGui import QGuiApplication

    dialog = _dialog(qtbot, ["Url"], [["http://example.invalid/c"]])
    action = dialog.build_field_menu(0).actions()[0]
    assert "Ctrl+C" in action.text()
    QGuiApplication.clipboard().setText("PREVIOUS")
    action.trigger()
    assert QGuiApplication.clipboard().text() == "http://example.invalid/c"


def test_copying_a_column_the_grid_truncated_copies_the_whole_value(qtbot):
    """The payoff. In the grid this cell copies as 400 escaped characters
    followed by this tool's own count of the rest -- an annotation dressed
    as evidence, and unusable in a report."""
    from PySide6.QtGui import QGuiApplication

    dialog = _dialog(qtbot, ["Url"], [[LONG_TEXT]])
    assert dialog.copy_field(0) is True
    copied = QGuiApplication.clipboard().text()
    assert copied == LONG_TEXT
    assert "characters total" not in copied


def test_the_copied_value_carries_no_column_name_in_front_of_it(qtbot):
    from PySide6.QtGui import QGuiApplication

    dialog = _dialog(qtbot, ["Url"], [["http://example.invalid/d"]])
    dialog.copy_field(0)
    assert QGuiApplication.clipboard().text() == "http://example.invalid/d"


def test_copy_all_columns_names_its_source_and_keeps_every_column(qtbot):
    dialog = _dialog(qtbot, ["Id", "Url", "Blob"],
                     [[7, LONG_TEXT, BLOB]], row_number=3)
    text = dialog.copy_all_text()
    assert "Container_2" in text and "row 3" in text
    for name in ("Id", "Url", "Blob"):
        assert ("%s: " % name) in text
    assert LONG_TEXT in text


def test_the_tsv_copy_cannot_be_shifted_by_a_tab_inside_a_value(qtbot):
    """A literal tab in a stored value would read as a column break and
    silently move every field after it -- the same rule records_table's
    own TSV copy already keeps."""
    dialog = _dialog(qtbot, ["A", "B"], [["one\ttwo", "x"]])
    lines = dialog.copy_tsv_text().split("\n")
    assert lines[0] == "Column\tValue\tStored as"
    assert len(lines[1].split("\t")) == 3


def test_a_multi_column_selection_copies_every_selected_column(qtbot):
    """Found by looking at what the list ALLOWS: rows are selectable in
    the ordinary extended way, so an examiner can rubber-band three
    columns, press Ctrl+C, and get one of them -- the other two dropped
    with nothing said. Silently copying less than was selected is the
    same defect class as a filter that hides evidence quietly.

    Several rows keep their column names, deliberately, and for the
    reason the record dialog gives for the identical rule: a column of
    values with nothing naming them is a paste nobody can attribute, and
    the names earn their place the moment there is more than one."""
    from PySide6.QtGui import QGuiApplication

    dialog = _dialog(qtbot, ["Id", "Url", "Flags"],
                     [[7, "http://example.invalid/e", 3]])
    dialog.table.selectRow(0)
    dialog.table.item(2, 0).setSelected(True)
    dialog.table.item(2, 1).setSelected(True)
    dialog.table.item(2, 2).setSelected(True)
    QGuiApplication.clipboard().setText("PREVIOUS")
    assert dialog.copy_selection() is True
    copied = QGuiApplication.clipboard().text()
    assert copied == "Id: 7\nFlags: 3"
    assert "2 column" in dialog.status_label.text()


def test_one_selected_column_still_copies_byte_exact_and_undecorated(qtbot):
    """The single-row case must NOT gain a label on the way. That is the
    concrete defect the record dialog was fixed for: its menu printed
    Ctrl+C beside the byte-exact action while Ctrl+C composed
    "Clean URL: https://...", and an examiner cleaned the label off by
    hand every time."""
    from PySide6.QtGui import QGuiApplication

    dialog = _dialog(qtbot, ["Id", "Url"], [[7, "http://example.invalid/f"]])
    dialog.table.selectRow(1)
    QGuiApplication.clipboard().setText("PREVIOUS")
    assert dialog.copy_selection() is True
    assert QGuiApplication.clipboard().text() == "http://example.invalid/f"


def test_a_multi_column_copy_states_an_absent_column_rather_than_dropping_it(
        qtbot):
    """A column left out of the paste reads as a column that was not
    there. What it holds -- nothing -- is itself a fact about the row."""
    from PySide6.QtGui import QGuiApplication

    dialog = _dialog(qtbot, ["Id", "Nothing"], [[7, None]])
    dialog.table.selectAll()
    dialog.copy_selection()
    copied = QGuiApplication.clipboard().text()
    assert "Id: 7" in copied
    assert "Nothing: " in copied and "null" in copied


def test_ctrl_c_copies_the_whole_selection_not_just_the_current_row(qtbot):
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest

    dialog = _dialog(qtbot, ["Id", "Url"], [[7, "http://example.invalid/g"]])
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.table.selectAll()
    QGuiApplication.clipboard().setText("PREVIOUS")
    QTest.keyClick(dialog.table, _Qt.Key_C, _Qt.ControlModifier)
    copied = QGuiApplication.clipboard().text()
    assert copied.startswith("Id: 7")
    assert "http://example.invalid/g" in copied


# --- the copy button is live the moment the dialog opens -------------------
#
# Both detail dialogs opened with their primary copy action greyed out,
# because nothing was selected yet. Seen in a screenshot of the real
# application against a real exhibit, and it is the same complaint that
# started this work: per-field copy that exists but reads as absent. A
# disabled button is a stronger claim than a hidden one -- it says the
# action is unavailable for this record.


def test_a_field_is_selected_as_soon_as_the_dialog_opens(qtbot):
    d = _dialog(qtbot, ["Id", "Value"], [[7, "x"]])
    assert d.field_at(d.table.currentRow()) is not None


def test_the_copy_button_is_usable_without_clicking_a_row_first(qtbot):
    d = _dialog(qtbot, ["Id", "Value"], [[7, "x"]])
    assert d.copy_field_button.isEnabled()


def test_filtering_down_to_other_columns_moves_the_selection_to_one(qtbot):
    """Filtering away the selected row leaves nothing selected and greys
    the button again -- the same dead end, one keystroke later."""
    d = _dialog(qtbot, ["Id", "Value"], [[7, "x"]])
    d.apply_filter("Value")
    assert d.field_at(d.table.currentRow()) is not None
    assert d.copy_field_button.isEnabled()


def test_a_live_selection_is_not_stolen_by_a_filter_that_keeps_it(qtbot):
    d = _dialog(qtbot, ["Id", "Value", "Extra"], [[7, "x", "y"]])
    names = _field_names(d)
    d.table.setCurrentCell(names.index("Value"), 0)
    d.apply_filter("")
    assert _field_names(d)[d.table.currentRow()] == "Value"
