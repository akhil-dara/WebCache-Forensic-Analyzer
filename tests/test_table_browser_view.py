"""TableBrowserView: the master/detail pair -- a filterable, grouped list
of tables on the left, the selected table's own rows, paginated and
rendered exactly as stored, on the right.

table_browser_loader.py's own tests already prove the shaping; this file
proves only what the widget itself does with a shaped page: builds the
grouped list, drives get_table_rows_raw() through Prev/Next without ever
asking for more than one page's worth of rows, shows column names/type/
row count/cache directory, and renders each cell's raw text.

The stub SUBCLASSES WebCacheParser without calling its __init__ (no real
ESE database on this machine for CI to open) so raw_type_name()/
raw_rendering() are the REAL methods -- see test_table_browser_loader.py's
own docstring for why that matters here too.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from webcache.engine.ese_parser import WebCacheParser
from webcache.views.browser import TableBrowserView


class _StubParser(WebCacheParser):
    def __init__(self, row_count=5):
        self.containers_meta = [
            {"ContainerId": 2, "TableName": "Container_2",
             "Directory": r"C:\case\History.IE5"},
        ]
        self._rows = [[i, "value-%d" % i] for i in range(row_count)]

    def get_tables_grouped(self):
        return {
            "History": [{"name": "Container_2", "display_name": "Container_2",
                        "type": "History", "count": len(self._rows)}],
            "Cookie Entries": [{"name": "CookieEntryEx_1",
                                "display_name": "CookieEntryEx_1",
                                "type": "Cookie Entries", "count": 0}],
        }

    def get_table_rows_raw(self, table_name, limit=500, offset=0):
        if table_name == "Container_2":
            return ["Id", "Value"], self._rows[offset:offset + limit]
        return ["Domain"], []

    def get_table_row_count(self, table_name):
        return len(self._rows) if table_name == "Container_2" else 0

    def get_table_display_name(self, table_name):
        return table_name

    def get_table_type(self, table_name):
        return "History" if table_name == "Container_2" else "Cookie Entries"


def _leaf_items(view):
    return [view.table_list.item(i) for i in range(view.table_list.count())
            if view.table_list.item(i).data(Qt.UserRole) is not None]


# --- before any parser ---------------------------------------------------

def test_before_any_parser_the_table_list_is_empty(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    assert v.table_list.count() == 0
    assert "no evidence" in v._info_label.text().lower()


# --- populating the grouped list -----------------------------------------

def test_set_parser_populates_the_grouped_table_list(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser())
    names = {item.data(Qt.UserRole) for item in _leaf_items(v)}
    assert names == {"Container_2", "CookieEntryEx_1"}


def test_group_header_rows_are_not_selectable(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser())
    headers = [v.table_list.item(i) for i in range(v.table_list.count())
              if v.table_list.item(i).data(Qt.UserRole) is None]
    assert headers, "expected at least one group-header row"
    for h in headers:
        assert not (h.flags() & Qt.ItemIsSelectable)


# --- selecting a table loads its first page -------------------------------

def test_clicking_a_table_loads_its_first_page(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    item = next(i for i in _leaf_items(v) if i.data(Qt.UserRole) == "Container_2")
    v.table_list.setCurrentItem(item)
    assert v.grid.columnCount() == 2
    assert v.grid.rowCount() == 2
    assert v.grid.horizontalHeaderItem(0).text() == "Id"
    assert v.grid.horizontalHeaderItem(1).text() == "Value"


def test_the_info_bar_shows_type_and_row_count(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    v.select_table("Container_2")
    text = v._info_label.text()
    assert "History" in text
    assert "5" in text


def test_cell_values_are_the_raw_rendering(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=2))
    v.select_table("Container_2")
    assert v.grid.item(0, 0).text() == "0"
    assert v.grid.item(0, 1).text() == "value-0"


def test_a_large_filetime_shaped_integer_cell_is_never_reinterpreted(qtbot):
    class _FiletimeParser(_StubParser):
        def __init__(self):
            super().__init__(row_count=0)
            self._rows = [[133535904000000000, "x"]]

    v = TableBrowserView(page_size=10)
    qtbot.addWidget(v)
    v.set_parser(_FiletimeParser())
    v.select_table("Container_2")
    assert v.grid.item(0, 0).text() == "133535904000000000"


def test_a_binary_cell_marks_that_it_has_more_to_view(qtbot):
    """The only route to the blob viewer here is the
    right-click "View these bytes (hex and strings)..." action, and
    nothing in the grid marked which cells offer it -- every cell's
    tooltip said only "stored as: <type>", the identical shape whether or
    not right-clicking did anything more than any other cell. A binary
    cell renders as truncated hex whose own comment (ese_parser.
    raw_rendering) says "the record dialog holds all of it", but this grid
    has no record dialog -- the tooltip is the one place left to say so."""
    class _BytesParser(_StubParser):
        def __init__(self):
            super().__init__(row_count=0)
            self._rows = [[b"\x01\x02\x03\x04", "text-value"]]

    v = TableBrowserView(page_size=10)
    qtbot.addWidget(v)
    v.set_parser(_BytesParser())
    v.select_table("Container_2")
    bytes_item = v.grid.item(0, 0)
    text_item = v.grid.item(0, 1)
    assert "right-click" in bytes_item.toolTip().lower()
    assert "right-click" not in text_item.toolTip().lower()


# --- cache directory -------------------------------------------------------

def test_cache_directory_is_shown_for_a_container_table(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.show()
    qtbot.waitExposed(v)
    v.set_parser(_StubParser())
    v.select_table("Container_2")
    assert v._directory_label.isVisible()
    assert r"C:\case\History.IE5" in v._directory_label.text()


def test_cache_directory_is_hidden_for_a_non_container_table(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser())
    v.select_table("CookieEntryEx_1")
    assert not v._directory_label.isVisible()


# --- pagination -------------------------------------------------------------

def test_next_and_previous_move_the_page(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    v.select_table("Container_2")
    assert v.grid.item(0, 0).text() == "0"
    assert not v.prev_button.isEnabled()
    assert v.next_button.isEnabled()

    v.next_button.click()
    assert v.grid.item(0, 0).text() == "2"
    assert v.prev_button.isEnabled()
    assert v.next_button.isEnabled()

    v.next_button.click()  # rows 4..4 (last, partial page)
    assert v.grid.item(0, 0).text() == "4"
    assert v.grid.rowCount() == 1
    assert not v.next_button.isEnabled()

    v.prev_button.click()
    assert v.grid.item(0, 0).text() == "2"


def test_the_page_label_states_the_visible_row_range(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    v.select_table("Container_2")
    assert "1" in v._page_label.text()
    assert "2" in v._page_label.text()
    assert "5" in v._page_label.text()


def test_selecting_a_different_table_resets_to_the_first_page(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    v.select_table("Container_2")
    v.next_button.click()
    assert v.grid.item(0, 0).text() == "2"

    v.select_table("CookieEntryEx_1")
    v.select_table("Container_2")
    assert v.grid.item(0, 0).text() == "0"


# --- filtering the table list -----------------------------------------------

def test_typing_in_the_filter_box_hides_non_matching_leaf_rows(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser())
    v.filter_box.setText("cookie")
    leaves = {item.data(Qt.UserRole): item.isHidden() for item in _leaf_items(v)}
    assert leaves["CookieEntryEx_1"] is False
    assert leaves["Container_2"] is True


def test_clearing_the_filter_shows_every_table_again(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser())
    v.filter_box.setText("cookie")
    v.filter_box.setText("")
    assert all(not item.isHidden() for item in _leaf_items(v))


# --- the drill target: select_table() ---------------------------------------

def test_select_table_loads_the_named_table_and_selects_it_in_the_list(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    v.select_table("Container_2")
    assert v.grid.rowCount() == 2
    current = v.table_list.currentItem()
    assert current is not None and current.data(Qt.UserRole) == "Container_2"


def test_select_table_clears_an_active_filter_that_would_hide_the_target(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    v.filter_box.setText("cookie")  # would hide Container_2
    v.select_table("Container_2")
    item = next(i for i in _leaf_items(v) if i.data(Qt.UserRole) == "Container_2")
    assert not item.isHidden()
    assert v.grid.rowCount() == 2


def test_select_table_on_an_unknown_table_shows_a_clear_message_not_a_crash(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser())
    v.select_table("Container_999")  # no such table in this exhibit
    assert "container_999" in v._info_label.text().lower()
    assert v.grid.rowCount() == 0


def test_select_table_before_any_parser_does_not_crash(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.select_table("Container_2")  # must not raise


# --- resetting on a fresh exhibit -------------------------------------------

def test_set_parser_none_clears_the_list_and_the_detail_pane(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    v.select_table("Container_2")
    v.set_parser(None)
    assert v.table_list.count() == 0
    assert v.grid.rowCount() == 0
    assert "no evidence" in v._info_label.text().lower()


def test_opening_a_new_exhibit_does_not_carry_over_the_old_selection(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    v.select_table("Container_2")
    v.set_parser(_StubParser(row_count=5))
    # A fresh exhibit must not silently keep showing a PREVIOUS exhibit's
    # table selection -- the same "reset, don't inherit" discipline
    # RecordsView._switch_segment already applies to filters.
    assert v.grid.rowCount() == 0


# --- header / caveat / theme -------------------------------------------------

def test_header_and_caveat_are_reachable(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    assert v.header is not None
    v.set_caveat("Raw ESE tables exactly as stored, with no interpretation applied.")
    assert v.caveat is not None


def test_refresh_theme_preserves_the_current_table_and_page(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    v.select_table("Container_2")
    v.next_button.click()
    assert v.grid.item(0, 0).text() == "2"

    v.refresh_theme()

    assert v.grid.item(0, 0).text() == "2"


# --- copy affordances: this grid is the only place raw stored fields are ---
# visible, and this project's own "Copy, never Open" rule means these
# paths belonging to the examined machine must have a copy path -- before
# this, none existed at all: no Ctrl+C, no right-click, nothing. Mirrors
# RecordsTable's own Ctrl+C/context-menu copy paths (records_table.py) as
# closely as this grid's shape allows -- there is no RecordTableModel or
# carved marker behind it (this view's whole point is "no interpretation
# applied"), so there is no Origin-guarantee column to append the way that
# table's copy does.

def test_the_grid_has_a_custom_context_menu_wired(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    assert v.grid.contextMenuPolicy() == Qt.CustomContextMenu


def test_ctrl_c_copies_a_full_row_selection_as_tsv_with_its_header(qtbot):
    """A single selected CELL already copies its own text on plain
    Ctrl+C -- that much is QTableWidget's own native default behaviour,
    present even with no code in this file at all (verified directly
    against a bare QTableWidget). It does NOT extend to a multi-cell
    selection -- also verified directly: selecting a full row and
    pressing Ctrl+C on an unmodified QTableWidget leaves the clipboard
    untouched -- so a full-row selection is what actually proves this
    view's OWN Ctrl+C handling exists, matching RecordsTable's own
    always-header-row shape (records_table.py's identical test)."""
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=2))
    v.select_table("Container_2")
    for c in range(2):
        v.grid.item(0, c).setSelected(True)
    QGuiApplication.clipboard().setText("unrelated-sentinel")
    QTest.keyClick(v.grid, Qt.Key_C, Qt.ControlModifier)
    lines = QGuiApplication.clipboard().text().splitlines()
    assert lines[0] == "Id\tValue"
    assert lines[1] == "0\tvalue-0"


def test_copy_selection_as_tsv_covers_a_full_row_with_its_header(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=2))
    v.select_table("Container_2")
    for c in range(2):
        v.grid.item(0, c).setSelected(True)
    tsv = v.copy_grid_selection_as_tsv()
    lines = tsv.splitlines()
    assert lines[0] == "Id\tValue"
    assert lines[1] == "0\tvalue-0"


def test_copy_selection_as_tsv_is_empty_with_nothing_selected(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=2))
    v.select_table("Container_2")
    assert v.copy_grid_selection_as_tsv() == ""


def test_context_menu_offers_copy_cell_row_and_column(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=2))
    v.select_table("Container_2")
    ix = v.grid.model().index(0, 1)
    menu = v._build_grid_context_menu(ix)
    # The three copy entries, in this order, still the tail of the menu.
    # Asserted as a tail rather than the whole list: the row view is
    # offered above them (test_the_context_menu_offers_the_whole_row_
    # first), and pinning the entire menu here would make every later
    # entry look like a regression in a test about copying.
    texts = [a.text() for a in menu.actions()]
    assert texts[-3:] == ["Copy cell", "Copy row", "Copy column"]


def test_context_menu_copy_cell_puts_the_raw_value_on_the_clipboard(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=2))
    v.select_table("Container_2")
    ix = v.grid.model().index(0, 1)
    menu = v._build_grid_context_menu(ix)
    next(a for a in menu.actions() if a.text() == "Copy cell").trigger()
    assert QGuiApplication.clipboard().text() == "value-0"


def test_context_menu_copy_row_puts_every_column_on_the_clipboard(qtbot):
    v = TableBrowserView(page_size=2)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=2))
    v.select_table("Container_2")
    ix = v.grid.model().index(0, 0)
    menu = v._build_grid_context_menu(ix)
    next(a for a in menu.actions() if a.text() == "Copy row").trigger()
    assert QGuiApplication.clipboard().text() == "0\tvalue-0"


def test_context_menu_copy_column_puts_every_row_on_the_clipboard(qtbot):
    v = TableBrowserView(page_size=10)
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=3))
    v.select_table("Container_2")
    ix = v.grid.model().index(0, 1)
    menu = v._build_grid_context_menu(ix)
    next(a for a in menu.actions() if a.text() == "Copy column").trigger()
    assert QGuiApplication.clipboard().text() == "value-0\nvalue-1\nvalue-2"


# --- opening one row, the way the rest of the application opens a record --
#
# A capability with no route to it is indistinguishable from one that does
# not exist -- recovery_loader's own docstring says so about signals built
# and never wired. The row view is reached the way every record surface
# here is reached: Enter, a double-click, and the context menu, plus a
# button that SAYS so, because the two keyboard routes are invisible.
#
# QTest.mouseDClick is inert in this environment -- verified: it never
# fires doubleClicked, even on a stock QTableView -- so the double-click
# route is driven through the signal the grid actually emits.


def _loaded(qtbot, row_count=5):
    view = TableBrowserView()
    qtbot.addWidget(view)
    view.set_parser(_StubParser(row_count=row_count))
    view.select_table("Container_2")
    return view


def _asked(view):
    seen = []
    view.rowRequested.connect(seen.append)
    return seen


def test_enter_on_a_grid_row_asks_for_that_row(qtbot):
    view = _loaded(qtbot)
    seen = _asked(view)
    view.grid.setCurrentCell(2, 0)
    QTest.keyClick(view.grid, Qt.Key_Return)
    assert len(seen) == 1
    assert seen[0]["row_number"] == 3


def test_a_double_click_asks_for_that_row(qtbot):
    view = _loaded(qtbot)
    seen = _asked(view)
    view.grid.itemDoubleClicked.emit(view.grid.item(1, 1))
    assert len(seen) == 1
    assert seen[0]["row_number"] == 2


def test_the_context_menu_offers_the_whole_row_first(qtbot):
    view = _loaded(qtbot)
    seen = _asked(view)
    menu = view._build_grid_context_menu(view.grid.model().index(1, 0))
    first = menu.actions()[0]
    assert "row" in first.text().lower()
    first.trigger()
    assert len(seen) == 1 and seen[0]["row_number"] == 2


def test_a_visible_button_says_the_row_view_is_there(qtbot):
    """Both keyboard routes are invisible, and this application has been
    bitten by that before: per-field copy existed three ways in the record
    dialog with no affordance for any of it, and the examiner reported it
    as missing entirely."""
    view = _loaded(qtbot)
    seen = _asked(view)
    assert view.view_row_button.isEnabled() is False
    view.grid.setCurrentCell(0, 0)
    assert view.view_row_button.isEnabled() is True
    view.view_row_button.click()
    assert len(seen) == 1 and seen[0]["row_number"] == 1


def test_the_payload_carries_the_columns_and_the_rows_own_cells(qtbot):
    view = _loaded(qtbot)
    seen = _asked(view)
    view.open_row(0)
    payload = seen[0]
    assert payload["columns"] == ["Id", "Value"]
    assert payload["cells"] == view._page_rows[0]
    assert payload["table"] == "Container_2"
    assert payload["row_count"] == 5


def test_the_row_number_is_the_tables_own_not_the_pages(qtbot):
    """An examiner reading "row 3" against a table of 5,000 means the
    third row of the TABLE. On page two, the third row on screen is not
    that, and a dialog that said so would be wrong in a way nothing on
    screen would contradict."""
    view = TableBrowserView(page_size=2)
    qtbot.addWidget(view)
    view.set_parser(_StubParser(row_count=5))
    view.select_table("Container_2")
    view._go_next_page()
    seen = _asked(view)
    view.open_row(0)
    assert seen[0]["row_number"] == 3


def test_asking_for_a_row_that_is_not_on_this_page_asks_for_nothing(qtbot):
    view = _loaded(qtbot)
    seen = _asked(view)
    assert view.open_row(99) is False
    assert seen == []


def test_a_grid_cell_says_how_to_see_the_whole_row(qtbot):
    """The tooltip is where a truncated cell has to say where the rest of
    it is -- the same job it already does for a binary cell's bytes."""
    view = _loaded(qtbot)
    assert "row" in view.grid.item(0, 0).toolTip().lower()


# --- empty tables, and where to start -------------------------------------

def test_an_empty_table_reads_as_empty(qtbot):
    """On a real exhibit about half of 83 tables hold no rows, and they
    looked exactly like the ones that do."""
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    items = {i.data(Qt.UserRole): i for i in _leaf_items(v)}
    empty, full = items["CookieEntryEx_1"], items["Container_2"]
    assert empty.foreground().color() != full.foreground().color()
    assert "no rows" in empty.toolTip().lower()


def test_hide_empty_tables_leaves_only_tables_with_rows(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    assert not v.hide_empty_box.isChecked()       # complete by default
    v.hide_empty_box.setChecked(True)
    shown = [i.data(Qt.UserRole) for i in _leaf_items(v) if not i.isHidden()]
    assert shown == ["Container_2"]
    v.hide_empty_box.setChecked(False)
    assert all(not i.isHidden() for i in _leaf_items(v))


def test_the_starting_screen_points_at_the_tables_with_rows(qtbot):
    """A tiny line over a blank pane said only "select a table"."""
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=5))
    text = v._info_label.text()
    assert "1 of 2 tables hold rows" in text, text
    assert "Container_2 (5)" in text, text
    assert "1 of 2 hold rows" in v.list_summary.text(), v.list_summary.text()
