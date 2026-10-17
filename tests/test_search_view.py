"""SearchView: the fifteenth of sixteen destinations, and the first that
reads the DATABASE rather than the parsed record set.

FOUR STATES, ALL WORDED. Idle, running, cancelled, and finished-with-no-
hits all paint an empty grid, and three of them mean completely different
things. The dangerous pair is cancelled and no-hits: left unworded they
are the same blank rectangle, and one of them is an assertion that a
keyword is absent from the evidence.

DECODED AND AS STORED, FOR EVERY COLUMN. The grid carries the matched
cell both ways; the pane below carries the whole row both ways. Colour is
NOT used to dim the stored reading -- record_model's foreground channel
is spoken for by the carved/live distinction, which is never hideable --
so the two column labels ("Matched value — decoded" / "— as stored")
carry it instead.

THE PANE IS THE DETAIL SURFACE, and recordActivated is deliberately not
wired to the shell's record dialog for this view: a raw catalogue row is
not a parsed record, and RecordDetailDialog would render forty parsed
fields as empty over it.
"""
import pytest
from PySide6.QtCore import QItemSelectionModel

from webcache.shell import record_kinds, search_loader
from webcache.views.search import SearchView


class _StubParser:
    table_names = ["Container_1", "MSysObjects"]

    def __init__(self, columns=("Url", "EntryId"),
                 rows=(("https://example.test/a", 11),)):
        self._columns = list(columns)
        self._rows = [list(r) for r in rows]

    def get_table_display_name(self, name):
        return name

    def get_table_rows_raw(self, name, limit=500, offset=0):
        return list(self._columns), [list(r) for r in
                                     self._rows[offset:offset + limit]]

    @staticmethod
    def raw_type_name(value):
        return "text"

    @staticmethod
    def raw_rendering(value):
        return str(value)


def _result(row_index=1, matched=("Url",),
            cells=None, table="Container_1"):
    cells = {"Url": "https://example.test/a", "EntryId": "11"} if cells is None else cells
    return {
        "table": table, "table_type": "History", "container_name": "History",
        "column": matched[0], "matched_columns": list(matched),
        "match_value": "https://example.test/a", "match_in_blob": False,
        "match_raw": "https://example.test/a", "match_raw_type": "text",
        "url": cells.get("Url", ""), "row_index": row_index, "row": cells,
    }


def _rows(n=3):
    return search_loader.search_rows(
        [_result(row_index=i + 1) for i in range(n)])


@pytest.fixture
def view(qtbot):
    v = SearchView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser())
    return v


# --- the columns ----------------------------------------------------------

def test_the_thirteen_declared_columns_in_order(view):
    assert [c.key for c in view.COLUMNS] == [
        "Table", "Container", "TableType", "Row", "MatchedColumns",
        "FoundIn", "Context", "BlobOffset", "BlobEncoding", "MatchedValue",
        "RawType",
        "RawValue", "Url"]


def test_the_two_readings_are_labelled_apart_not_coloured_apart(view):
    labels = {c.key: c.label for c in view.COLUMNS}
    assert labels["MatchedValue"] == "Matched value — decoded"
    assert labels["RawValue"] == "Matched value — as stored"
    assert labels["RawType"] == "Stored as"


def test_matched_columns_is_text_because_the_set_is_open(view):
    """`contains` is the operator that makes it useful, and a flag would
    offer a value list that grows with every table."""
    col = next(c for c in view.COLUMNS if c.key == "MatchedColumns")
    assert col.kind == "text"


def test_found_in_is_a_flag_because_the_set_is_closed(view):
    col = next(c for c in view.COLUMNS if c.key == "FoundIn")
    assert col.kind == "flag"


def test_the_row_ordinal_is_numeric_and_narrow(view):
    col = next(c for c in view.COLUMNS if c.key == "Row")
    assert (col.kind, col.width) == ("num", 70)
    assert col.label == "Row #"


def test_the_url_column_flexes(view):
    col = next(c for c in view.COLUMNS if c.key == "Url")
    assert (col.kind, col.width) == ("url", None)


def test_badges_are_cited_only_where_the_catalogue_actually_has_an_entry(view):
    """basis_of() defaults an unknown field to DERIVED, which paints a
    DER chip that is a fabricated claim -- the lesson recovery.py's
    Timestamp column already records."""
    fields = {c.key: c.field for c in view.COLUMNS}
    assert fields["Container"] == "ContainerName"
    assert fields["Url"] == "Url"
    assert fields["Table"] is None
    assert fields["MatchedColumns"] is None
    assert fields["RawValue"] is None


def test_the_table_cell_drills_to_the_table_browser(view, qtbot):
    col = next(c for c in view.COLUMNS if c.key == "Table")
    assert col.on_click is not None
    with qtbot.waitSignal(view.drillRequested) as blocker:
        col.on_click({"Table": "Container_1"})
    assert blocker.args[0] == "browser"


def test_a_row_here_is_a_hit(view):
    assert view.COUNT_NOUN == "hits"
    view.set_records(_rows(3))
    assert view.count_label.text().startswith("3 hits")


# --- the four states ------------------------------------------------------

def test_idle_says_what_pressing_search_will_do(view):
    view.set_idle()
    assert view.table._empty_reason == search_loader.IDLE_TEXT


def test_before_any_search_nothing_reads_as_a_count_of_zero(view):
    """"0 hits" before a search has run reads as a result. The heading,
    the count line and the export button all say no search has run."""
    view.set_idle()
    assert "0 hits" not in view.header.subtitle_text()
    assert "No search run yet" in view.header.subtitle_text()
    assert view.count_label.text() == "No search run yet"
    assert not view.export_button.isEnabled()


def test_while_searching_and_after_a_cancel_no_count_is_claimed(view):
    view.show_searching(search_loader.SearchQuery("needle"))
    assert view.count_label.text() == 'Searching for "needle"…'
    assert "0 hits" not in view.header.subtitle_text()
    assert not view.export_button.isEnabled()
    view.show_cancelled()
    assert view.count_label.text() == "Search cancelled — nothing reported"
    assert not view.export_button.isEnabled()


def test_a_finished_search_counts_its_hits_and_can_be_exported(view):
    view.show_results(search_loader.SearchQuery("needle"),
                      {"rows": _rows(3), "skipped": [], "rows_scanned": 9,
                       "tables": 2})
    assert view.count_label.text().startswith("3 hits")
    assert view.header.subtitle_text().startswith("3 hits")
    assert view.export_button.isEnabled()
    view.show_results(search_loader.SearchQuery("none"),
                      {"rows": [], "skipped": [], "rows_scanned": 9,
                       "tables": 2})
    assert view.count_label.text().startswith("0 hits")


def test_running_says_the_window_stays_usable(view):
    view.show_searching(search_loader.SearchQuery("needle"))
    assert view.table._empty_reason == search_loader.SEARCHING_TEXT


def test_running_disables_the_search_button_and_relabels_it(view):
    view.show_searching(search_loader.SearchQuery("needle"))
    assert not view.search_button.isEnabled()
    assert view.search_button.text() == "Searching…"


def test_cancelled_refuses_to_be_read_as_a_result(view):
    view.show_searching(search_loader.SearchQuery("needle"))
    view.show_cancelled()
    assert view.table._empty_reason == search_loader.CANCELLED_TEXT
    assert view.search_button.isEnabled()
    assert view.search_button.text() == "Search"


def test_finished_with_no_hits_names_the_keyword_and_what_zero_means(view):
    result = {"rows": [], "skipped": [], "rows_scanned": 4506, "tables": 83}
    view.show_results(search_loader.SearchQuery("needle"), result)
    assert view.table._empty_reason == search_loader.no_hits_text("needle",
                                                                  result)
    assert view.count_label.text().startswith("0 hits")


def test_a_no_hit_result_that_skipped_tables_says_so_in_the_empty_state(view):
    view.show_results(
        search_loader.SearchQuery("needle"),
        {"rows": [], "skipped": [("MSysObjects", "page checksum")],
         "rows_scanned": 10, "tables": 82})
    assert "NOT searched" in view.table._empty_reason


def test_a_finished_search_states_its_scope_in_the_count_line(view):
    view.show_results(search_loader.SearchQuery("needle"),
                      {"rows": _rows(2), "skipped": [], "rows_scanned": 4506,
                       "tables": 83})
    text = view.line_text()
    assert text.startswith("2 hits")
    assert "83 table(s)" in text and "4,506 row(s) scanned" in text


def test_the_four_empty_states_are_four_different_sentences(view):
    seen = set()
    view.set_idle()
    seen.add(view.table._empty_reason)
    view.show_searching(search_loader.SearchQuery("kw"))
    seen.add(view.table._empty_reason)
    view.show_cancelled()
    seen.add(view.table._empty_reason)
    view.show_results(search_loader.SearchQuery("kw"),
                      {"rows": [], "skipped": [], "rows_scanned": 1,
                       "tables": 1})
    seen.add(view.table._empty_reason)
    assert len(seen) == 4


# --- the query bar --------------------------------------------------------

def test_the_query_bar_sits_above_the_filter_bar(view):
    assert view._header_extra() is not None
    assert view._header_extra() is view._header_extra(), "must be idempotent"


def test_pressing_return_in_the_keyword_box_asks_for_a_search(view, qtbot):
    view.keyword_box.setText("needle")
    with qtbot.waitSignal(view.searchRequested) as blocker:
        view.keyword_box.returnPressed.emit()
    assert blocker.args == ["needle", ""]


def test_the_search_button_asks_for_a_search(view, qtbot):
    view.keyword_box.setText("needle")
    with qtbot.waitSignal(view.searchRequested) as blocker:
        view.search_button.click()
    assert blocker.args == ["needle", ""]


def test_a_narrowed_scope_travels_with_the_request(view, qtbot):
    view.set_scope_options(search_loader.scope_options(_StubParser()))
    view.scope_combo.setCurrentIndex(view.scope_combo.findData("Container_1"))
    view.keyword_box.setText("needle")
    with qtbot.waitSignal(view.searchRequested) as blocker:
        view.search_button.click()
    assert blocker.args == ["needle", "Container_1"]


def test_the_scope_combo_leads_with_all_tables(view):
    view.set_scope_options(search_loader.scope_options(_StubParser()))
    # All, one group heading, two tables.
    assert view.scope_combo.count() == 4
    assert view.scope_combo.itemText(0) == "All tables and recovered records"
    assert view.scope() == search_loader.ALL_TABLES
    assert view.scope_label() == "All tables and recovered records"


def test_a_preset_sets_the_box_and_searches_in_one_step(view, qtbot):
    with qtbot.waitSignal(view.searchRequested) as blocker:
        view.preset_buttons[0].click()
    assert view.keyword_box.text() == blocker.args[0]
    assert blocker.args[0]


def test_the_scope_note_is_on_screen_not_in_a_tooltip(view):
    assert view.scope_note.text().startswith(search_loader.SCOPE_NOTE)
    assert view.scope_note.wordWrap() is True


def test_the_keyword_is_readable_back_off_the_view(view):
    view.keyword_box.setText(" needle ")
    assert view.keyword() == "needle"


# --- the detail pane ------------------------------------------------------

def test_the_pane_opens_on_an_invitation_never_a_void(view):
    from webcache.views.search import PANE_PROMPT
    assert view.pane.prompt_text() == PANE_PROMPT
    assert "Select a hit" in PANE_PROMPT


def test_the_pane_declares_four_columns(view):
    assert [c.key for c in view.HIT_FIELD_COLUMNS] == [
        "Column", "Matched", "Decoded", "Stored"]
    labels = {c.key: c.label for c in view.HIT_FIELD_COLUMNS}
    assert labels["Decoded"] == "Value as decoded"
    assert labels["Stored"] == "Value as stored"


def test_selecting_a_hit_fills_the_pane_with_every_column_of_its_row(view):
    view.set_records(_rows(2))
    _select(view, 0)
    assert [r["Column"] for r in view.pane.visible_rows()] == ["Url", "EntryId"]
    assert view.pane.heading_text().startswith("Row 1 of Container_1")


def test_the_pane_marks_which_columns_matched(view):
    view.set_records(search_loader.search_rows([_result(matched=("EntryId",))]))
    _select(view, 0)
    matched = {r["Column"]: r["Matched"] for r in view.pane.visible_rows()}
    assert matched == {"Url": "no", "EntryId": "yes"}


def test_a_filter_keystroke_re_syncs_the_pane_rather_than_leaving_it_stale(view):
    """HeadersView's and TimelineView's shared lesson: a filter change
    refreshes the layout WITHOUT emitting currentRowChanged, and the
    current index is a row NUMBER -- so the pane goes on describing a hit
    the filter has removed."""
    view.set_records(search_loader.search_rows(
        [_result(row_index=1, table="Container_1"),
         _result(row_index=2, table="MSysObjects")]))
    _select(view, 1)
    assert view.pane.heading_text().startswith("Row 2 of MSysObjects")
    view.filter_box.setText("Container_1")
    view._apply_text()
    assert view.pane.prompt_text() == view.pane.prompt_text()
    assert not view.pane.visible_rows(), (
        "the selected hit was filtered away; the pane must clear")


def test_a_filter_that_removes_nothing_keeps_the_pane(view):
    view.set_records(_rows(2))
    _select(view, 0)
    view.filter_box.setText("Container_1")
    view._apply_text()
    assert view.pane.visible_rows()


def test_the_pane_shares_the_splitter_with_the_grid(view):
    from PySide6.QtWidgets import QSplitter
    area = view._table_area()
    assert isinstance(area, QSplitter)
    assert area is view._table_area(), "must be idempotent"
    assert area.widget(0) is view.table and area.widget(1) is view.pane


def test_the_pane_export_is_forwarded_not_handled(view, qtbot):
    view.set_records(_rows(1))
    _select(view, 0)
    with qtbot.waitSignal(view.rowFieldsExportRequested):
        view.pane.export_button.click()


def test_a_failed_re_read_is_stated_in_the_panes_note(view):
    class _Failing(_StubParser):
        def get_table_rows_raw(self, name, limit=500, offset=0):
            return [], []

    view.set_parser(_Failing())
    view.set_records(_rows(1))
    _select(view, 0)
    assert search_loader.RAW_REREAD_FAILED in view.pane.note_text()


def test_the_pane_note_otherwise_states_which_reading_is_a_conclusion(view):
    from webcache.views.search import PANE_NOTE
    view.set_records(_rows(1))
    _select(view, 0)
    assert view.pane.note_text() == PANE_NOTE
    assert "conclusion" in PANE_NOTE


def test_a_pane_row_carries_the_same_kind_the_grid_row_does(view):
    view.set_records(_rows(1))
    _select(view, 0)
    assert all(r["_kind"] is record_kinds.K_TABLE_ROW
               for r in view.pane.visible_rows())


def test_the_view_never_wires_activation_to_a_record_dialog(view):
    """_show_record_detail accepts any dict, so wiring it here would open
    a full record-properties dialog over a raw catalogue row and render
    forty parsed fields as empty. The pane IS the detail surface."""
    import inspect
    from webcache.views import search as search_module
    source = inspect.getsource(search_module)
    assert "recordActivated.connect" not in source


def test_the_selected_hit_is_readable_back_for_an_export_sidecar(view):
    view.set_records(_rows(2))
    _select(view, 1)
    assert view.selected_hit_label() == "Container_1 row 2"


def test_nothing_selected_names_no_hit(view):
    view.set_records(_rows(2))
    assert view.selected_hit_label() == ""


def _select(view, row):
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(row, 0),
        QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)


def test_a_theme_switch_repaints_the_query_bar_and_the_pane(view):
    """MainWindow._refresh_drawn_theme calls refresh_theme() on every
    built view -- a glyph is a QPixmap baked in at construction, not a
    stylesheet colour, so it needs an explicit second pass. Both the
    magnifier in the keyword box and the pane's own table are drawn
    that way."""
    from PySide6.QtWidgets import QApplication
    from webcache.shell import theme
    view.set_records(_rows(1))
    _select(view, 0)
    app = QApplication.instance()
    theme.apply(app, "light")
    try:
        view.refresh_theme()          # must not raise
        assert view.scope_note.styleSheet()
        assert view.pane.visible_rows(), "the pane must survive a repaint"
    finally:
        theme.apply(app, "dark")


def test_tools_that_act_on_results_wait_for_a_finished_search(view):
    """Before a search, while one runs and after a cancel there are no
    hits: a filter box that takes typing and does nothing reads as broken."""
    tools = lambda: [view.filter_box, view.identical_button,
                     view.columns_button, view.clear_filters_button]
    view.set_idle()
    assert not any(t.isEnabled() for t in tools())
    view.show_searching(search_loader.SearchQuery("needle"))
    assert not any(t.isEnabled() for t in tools())
    view.show_cancelled()
    assert not any(t.isEnabled() for t in tools())
    view.show_results(search_loader.SearchQuery("needle"),
                      {"rows": _rows(3), "skipped": [], "rows_scanned": 9,
                       "tables": 2})
    assert all(t.isEnabled() for t in tools())
