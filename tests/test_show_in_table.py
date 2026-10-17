"""From any record to its raw database row."""
import threading

from PySide6.QtCore import Qt

from webcache.engine.ese_parser import WebCacheParser
from webcache.shell import row_locator
from webcache.shell.main_window import MainWindow
from webcache.shell.record_detail import RecordDetailDialog
from webcache.shell.record_kinds import K_HISTORY, K_TOMBSTONE
from webcache.views.browser import TableBrowserView
from webcache.widgets.column_spec import Column
from webcache.widgets.records_table import RecordsTable
from tests.test_detail_fields import carved_struct_row, cookie_row, history_row
from tests.test_table_browser_view import _StubParser


# --- the engine: find a row by key, counted the way pages are counted ------

class _Node:
    def __init__(self, data):
        self.data = data
        self.key = b""


class _Rec:
    def __init__(self, data=b"\x00" * 8, **cols):
        self._node = _Node(data)
        self._cols = cols

    def get(self, name):
        return self._cols.get(name)


class _Table:
    def __init__(self, name, recs):
        self.name = name
        self._recs = recs

    def records(self):
        return iter(self._recs)


class _Db:
    def __init__(self, tables):
        self._tables = {t.name: t for t in tables}

    def table(self, name):
        return self._tables[name]


class _EngineParser(WebCacheParser):
    def __init__(self, tables):
        self.db = _Db(tables)
        self.table_names = [t.name for t in tables]


def test_find_row_ordinal_counts_exactly_like_the_pager():
    """A stub (a 1-byte leaf node) is skipped by live_records, so it must
    not shift the ordinal either."""
    table = _Table("Container_4", [
        _Rec(EntryId=10), _Rec(data=b"\x00"), _Rec(EntryId=11),
        _Rec(EntryId=12)])
    parser = _EngineParser([table])
    assert parser.find_row_ordinal("Container_4", {"EntryId": 12}) == 2
    assert parser.find_row_ordinal("Container_4", {"EntryId": 99}) is None
    assert parser.find_row_ordinal("Nope", {"EntryId": 10}) is None


def test_a_key_of_zero_never_matches_a_row_missing_that_column():
    """_safe_int(None) is 0: a row with no EntryId must not be taken for
    the row whose EntryId IS 0."""
    table = _Table("Container_4", [_Rec(Other=1), _Rec(EntryId=0)])
    parser = _EngineParser([table])
    assert parser.find_row_ordinal("Container_4", {"EntryId": 0}) == 1
    lone = _Table("Container_5", [_Rec(Other=1)])
    assert _EngineParser([lone]).find_row_ordinal(
        "Container_5", {"EntryId": 0}) is None


def test_the_ordinal_names_the_same_row_the_pager_shows():
    table = _Table("Container_4", [_Rec(EntryId=i) for i in range(7)]
                   + [_Rec(data=b"\x00")] + [_Rec(EntryId=i) for i in range(7, 12)])
    table.columns = [type("C", (), {"name": "EntryId"})()]
    parser = _EngineParser([table])
    ordinal = parser.find_row_ordinal("Container_4", {"EntryId": 9})
    assert ordinal == 9
    # The page get_table_rows_raw serves at that offset starts with it.
    _cols, rows = parser.get_table_rows_raw("Container_4", limit=1,
                                            offset=ordinal)
    assert rows == [[9]]


# --- the locator ------------------------------------------------------------

def test_a_live_container_record_is_found_by_entryid():
    ref = row_locator.source_row(history_row())
    assert ref.kind == row_locator.LIVE
    assert ref.table == "Container_4"
    assert ref.key == {"EntryId": 12}
    assert row_locator.action_label(ref) == "Show in database table"


def test_a_cookie_is_found_in_its_own_table():
    row = cookie_row()
    ref = row_locator.source_row(row)
    assert ref.kind == row_locator.LIVE
    assert ref.table == row["_record"]["Table"]
    assert ref.key == {"EntryId": row["_record"]["EntryId"]}


def test_a_carved_record_points_at_its_bytes():
    ref = row_locator.source_row(carved_struct_row())
    assert ref.kind == row_locator.CARVED
    assert row_locator.action_label(ref) == "Show bytes at the carve offset"


def _stub_row():
    return {"Origin": "Carved (deleted/unflushed)", "_kind": K_TOMBSTONE,
            "_record": {"Table": "Container_4",
                        "KeyColumns": ("UrlHash", "EntryId"),
                        "KeyValues": (5, 3)}}


def test_a_deleted_stub_names_its_table_and_key():
    ref = row_locator.source_row(_stub_row())
    assert ref.kind == row_locator.DELETED
    assert row_locator.action_label(ref) == (
        "Show table Container_4 (row deleted; key UrlHash 5, EntryId 3)")


def test_an_aggregate_has_no_row():
    assert row_locator.source_row({"_kind": "domain", "_record": None}) is None


# --- the browser lands on the right page and row ------------------------------

def test_show_row_opens_the_page_holding_the_row_and_selects_it(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=450))
    assert v.show_row("Container_2", 437)
    assert v._offset == 400
    assert v.grid.currentRow() == 37
    assert v.grid.item(37, 0).text() == "437"
    assert {ix.row() for ix in v.grid.selectedIndexes()} == {37}


def test_row_numbers_count_through_the_table_not_the_page(qtbot):
    """The header, the note ("Row 438") and the pager ("Rows 401-450")
    must name the same number; a header restarting at 1 said 38."""
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=450))
    def number(row):
        return str(v.grid.model().headerData(row, Qt.Vertical))

    v.select_table("Container_2")
    assert number(0) == "1"
    assert v.show_row("Container_2", 437)
    assert number(v.grid.currentRow()) == "438"
    assert number(0) == "401"


def test_show_row_renders_a_page_fetched_elsewhere_without_rereading(qtbot):
    """The off-thread locate brings its page with it; the GUI thread must
    not walk the table a second time to reach the same offset."""
    from webcache.shell import table_browser_loader
    parser = _StubParser(row_count=450)
    page = table_browser_loader.table_page(parser, "Container_2",
                                           offset=400, limit=200)
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(parser)
    asked = []
    original = parser.get_table_rows_raw
    parser.get_table_rows_raw = lambda t, limit=500, offset=0: (
        asked.append(offset), original(t, limit=limit, offset=offset))[1]
    assert v.show_row("Container_2", 437, page=page)
    assert 400 not in asked
    assert v.grid.currentRow() == 37


def test_a_note_is_cleared_when_another_table_is_picked(qtbot):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=450))
    v.select_table("Container_2")
    v.set_note("The row no longer exists.")
    assert not v._note_label.isHidden()
    v.select_table("CookieEntryEx_1")
    assert v._note_label.isHidden()


# --- the grid menu and the dialog action --------------------------------------

def test_the_grid_menu_offers_show_in_database_table(qtbot):
    t = RecordsTable()
    qtbot.addWidget(t)
    row = history_row()
    t.set_records([Column("CleanUrl", "Address", 300, kind="url")], [row])
    menu = t._build_context_menu(t.model().index(0, 0))
    action = next(a for a in menu.actions()
                  if a.text() == "Show in database table")
    with qtbot.waitSignal(t.showInTableRequested) as got:
        action.trigger()
    assert got.args[0] is t.model().row_at(0)


def test_the_grid_menu_offers_the_carve_offset_for_a_carved_row(qtbot):
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records([Column("CleanUrl", "Address", 300, kind="url")],
                  [carved_struct_row()])
    labels = [a.text() for a in
              t._build_context_menu(t.model().index(0, 0)).actions()]
    assert "Show bytes at the carve offset" in labels


def test_the_dialog_action_row_carries_the_source_action(qtbot):
    dlg = RecordDetailDialog(history_row())
    try:
        assert not dlg.source_button.isHidden()
        assert dlg.source_button.full_text() == "Show in database table"
        with qtbot.waitSignal(dlg.showInTableRequested) as got:
            dlg.source_button.click()
        assert got.args[0] is dlg.row
    finally:
        dlg.close()


def test_the_carved_dialog_action_reveals_its_bytes(qtbot):
    dlg = RecordDetailDialog(carved_struct_row())
    try:
        assert dlg.source_button.full_text() == "Show bytes at the carve offset"
        revealed = []
        dlg.reveal_bytes = lambda tab=None: revealed.append(tab)
        dlg.source_button.click()
        # it names the carve tab rather than taking whichever is first.
        assert revealed == ["Bytes at the carve offset"]
    finally:
        dlg.close()


def test_a_carved_action_with_no_bytes_to_show_says_so(qtbot):
    dlg = RecordDetailDialog(carved_struct_row())    # no exhibit open
    try:
        assert dlg.blob_region is None
        dlg.source_button.click()
        assert "No bytes at the carve offset" in dlg.status_label.text()
    finally:
        dlg.close()


# --- end to end through the main window ----------------------------------------

class _LocatingStub(_StubParser):
    def find_row_ordinal(self, table_name, key):
        return 437 if table_name == "Container_2" else None


def _live_row():
    record = {"ContainerId": 2, "EntryId": 437, "Url": "https://example.test/"}
    return {"CleanUrl": "https://example.test/", "Origin": "Live record",
            "_record": record, "_kind": K_HISTORY}


def test_show_in_database_table_lands_on_the_right_row(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w._parser = _LocatingStub(row_count=450)
    # As a load does it (MainWindow._replay_view_state / evidence load).
    w._ensure_view_built("browser").set_parser(w._parser)
    w.show_in_database_table(_live_row())
    browser = w._ensure_view_built("browser")
    assert w.current_key == "browser"
    assert browser._current_table == "Container_2"
    assert browser.grid.currentRow() == 37
    assert "Row 438" in browser._note_label.text()


def test_a_row_that_is_not_there_says_so(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w._parser = _LocatingStub(row_count=450)
    # As a load does it (MainWindow._replay_view_state / evidence load).
    w._ensure_view_built("browser").set_parser(w._parser)
    row = _live_row()
    row["_record"]["ContainerId"] = 9
    w.show_in_database_table(row)
    browser = w._ensure_view_built("browser")
    assert "No row with key EntryId 437" in browser._note_label.text()


def test_a_deleted_stub_opens_its_table_unselected_with_a_note(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w._parser = _LocatingStub(row_count=450)
    # As a load does it (MainWindow._replay_view_state / evidence load).
    w._ensure_view_built("browser").set_parser(w._parser)
    row = _stub_row()
    row["_record"]["Table"] = "Container_2"
    w.show_in_database_table(row)
    browser = w._ensure_view_built("browser")
    assert browser._current_table == "Container_2"
    assert browser.grid.selectedIndexes() == []
    assert browser.grid.verticalScrollBar().value() == 0
    assert "no longer exists" in browser._note_label.text()


def test_a_large_table_is_located_off_the_gui_thread(qtbot, monkeypatch):
    """Measured ~15 us a record: a 100k-row table is ~1.5 s of walking,
    which must not be spent on the GUI thread."""
    from webcache.shell import row_locate_runner
    located_on = []

    class _Big(_LocatingStub):
        db_path = "C:/case/WebCacheV01.dat"

        def find_row_ordinal(self, table_name, key):
            located_on.append(threading.get_ident())
            return super().find_row_ordinal(table_name, key)

    monkeypatch.setattr(row_locate_runner, "SYNC_MAX_ROWS", 100)
    monkeypatch.setattr(row_locate_runner, "open_parser",
                        lambda db_path, known_hashes=None: _Big(row_count=450))
    w = MainWindow()
    qtbot.addWidget(w)
    w._parser = _Big(row_count=450)
    # As a load does it (MainWindow._replay_view_state / evidence load).
    w._ensure_view_built("browser").set_parser(w._parser)
    w.show_in_database_table(_live_row())
    browser = w._ensure_view_built("browser")
    assert w.current_key == "browser"
    assert "Locating" in browser._note_label.text()
    qtbot.waitUntil(lambda: browser.grid.currentRow() == 37, timeout=5000)
    assert located_on and threading.get_ident() not in located_on
    assert browser._note_label.text() == (
        "Row 438 of this table (key EntryId 437) is selected.")


# --- the locate worker never outlives the question it answers -----------------

from PySide6.QtCore import QObject, Signal  # noqa: E402


class _FakeRunner(QObject):
    """Stands in for RowLocateRunner: records start/cancel, and lets a
    test deliver a (late) answer by hand."""
    located = Signal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.started = []
        self.cancelled = 0

    def start(self, request, db_path, known_hashes, page_size, clock=None):
        self.started.append(request)

    def cancel(self):
        self.cancelled += 1


class _BigStub(_LocatingStub):
    db_path = "C:/case/WebCacheV01.dat"


def _locating_window(qtbot, monkeypatch):
    from webcache.shell import row_locate_runner
    runners = []

    def make(parent=None):
        runners.append(_FakeRunner(parent))
        return runners[-1]

    monkeypatch.setattr(row_locate_runner, "SYNC_MAX_ROWS", 100)
    monkeypatch.setattr(row_locate_runner, "RowLocateRunner", make)
    w = MainWindow()
    qtbot.addWidget(w)
    w._parser = _BigStub(row_count=450)
    w._ensure_view_built("browser").set_parser(w._parser)
    w.show_in_database_table(_live_row())
    assert len(runners) == 1 and runners[0].started
    return w, runners


def _late_answer(runner):
    from webcache.shell import table_browser_loader
    page = table_browser_loader.table_page(_BigStub(row_count=450),
                                           "Container_2", offset=400)
    runner.located.emit(runner.started[-1], 437, page)


def test_a_new_exhibit_cancels_the_locate_and_its_answer_never_lands(
        qtbot, monkeypatch):
    from tests.test_search_wiring import _open_through_the_dialog
    w, runners = _locating_window(qtbot, monkeypatch)
    _open_through_the_dialog(w, monkeypatch, "C:/case/Other/WebCacheV01.dat")
    assert runners[0].cancelled
    assert getattr(w, "_row_locate_request", None) is None
    browser = w._ensure_view_built("browser")
    _late_answer(runners[0])
    assert browser.grid.selectedIndexes() == []


def test_navigating_away_cancels_the_locate(qtbot, monkeypatch):
    w, runners = _locating_window(qtbot, monkeypatch)
    w.go_to("history")
    assert runners[0].cancelled
    browser = w._ensure_view_built("browser")
    _late_answer(runners[0])
    assert browser._offset == 0
    assert browser.grid.selectedIndexes() == []


def test_a_later_request_cancels_the_running_locate(qtbot, monkeypatch):
    w, runners = _locating_window(qtbot, monkeypatch)
    stub = _stub_row()
    stub["_record"]["Table"] = "Container_2"
    w.show_in_database_table(stub)
    assert runners[0].cancelled


def test_paging_during_a_locate_is_not_overridden_by_its_answer(
        qtbot, monkeypatch):
    w, runners = _locating_window(qtbot, monkeypatch)
    browser = w._ensure_view_built("browser")
    browser._go_next_page()
    assert browser._offset == 200
    _late_answer(runners[0])
    assert browser._offset == 200
    assert browser.grid.selectedIndexes() == []
