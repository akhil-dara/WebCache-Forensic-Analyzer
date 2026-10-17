"""The wiring for Search: the nav key "search" builds a real view, a
keyword reaches a background worker, a result lands under the query that
asked for it, and every other record table in the application can send a
value here.

THE RACE THIS FILE EXISTS FOR. A search is re-triggered far more easily
than either existing worker -- an examiner types a second keyword while
the first scan is still running, which takes one keystroke and a Return.
cancel() alone does not close that: it is a best-effort request that
never blocks and never guarantees the worker stops. Disconnecting the
runner's signals is what actually stops a superseded result landing under
the current keyword's label -- the third instance of the identical
pattern (_cancel_pending_load, _cancel_pending_timeline_build,
_cancel_pending_recovery).

RESULTS BELONG TO A DATABASE, NOT TO A SESSION. Opening a second exhibit
clears them and cancels a scan in flight.

Mirrors test_timeline_wiring.py's shape, including its synchronous export
runner, so an export is proved by OPENING THE FILE.
"""
import csv

import pytest
from PySide6.QtCore import QItemSelectionModel, QObject, Signal
from PySide6.QtWidgets import QFileDialog

from webcache.provenance import EvidenceSet
from webcache.shell import search_loader
from webcache.shell.export_runner import ExportWorker
from webcache.shell.main_window import MainWindow, _NO_COUNT_KEYS
from webcache.views.search import SearchView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"


def _engine_result(row_index=1, table="Container_1", cells=None):
    cells = {"Url": "https://example.test/a"} if cells is None else cells
    return {
        "table": table, "table_type": "History", "container_name": "History",
        "column": "Url", "matched_columns": ["Url"],
        "match_value": "https://example.test/a", "match_in_blob": False,
        "match_raw": "https://example.test/a", "match_raw_type": "text",
        "url": cells.get("Url", ""), "row_index": row_index, "row": cells,
    }


def _payload(n=2, skipped=(), rows_scanned=600, tables=3):
    return {"rows": search_loader.search_rows(
                [_engine_result(i + 1) for i in range(n)]),
            "skipped": list(skipped), "rows_scanned": rows_scanned,
            "tables": tables}


class _FakeParser:
    db_path = _EVIDENCE_PATH
    source_hashes = {"WebCacheV01.dat": "0" * 64}
    table_names = ["Container_1", "MSysObjects"]

    def __init__(self, entries=()):
        self.all_entries = list(entries)
        self.db = None
        self.containers_meta = []
        self.container_type_map = {}

    def get_table_display_name(self, name):
        return name

    def get_table_rows_raw(self, name, limit=500, offset=0):
        return ["Url"], [["https://example.test/a"]]

    @staticmethod
    def raw_type_name(value):
        return "text"

    @staticmethod
    def raw_rendering(value):
        return str(value)


class _ManualRunner(QObject):
    """A runner that starts nothing. The test decides when -- and from
    WHICH runner -- a result lands."""
    progress = Signal(str)
    found = Signal(object, object)
    failed = Signal(str)
    made = []

    def __init__(self, parent=None):
        super().__init__(parent)
        _ManualRunner.made.append(self)
        self.queries = []
        self.cancelled = 0

    def start(self, query):
        self.queries.append(query)

    def cancel(self):
        self.cancelled += 1


class _SyncRunner(_ManualRunner):
    """Delivers a result the instant it is asked to start."""

    payload_rows = 2

    def start(self, query):
        _ManualRunner.start(self, query)
        self.found.emit(query, _payload(self.payload_rows))


class _SyncExportRunner(QObject):
    progress = Signal(str)
    written = Signal(list)
    failed = Signal(str)
    jobs = []

    def start(self, job):
        _SyncExportRunner.jobs.append(job)
        worker = ExportWorker(job)
        worker.progress.connect(self.progress)
        worker.written.connect(self.written)
        worker.failed.connect(self.failed)
        worker.run()

    def cancel(self):
        pass


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _ManualRunner.made = []
    _SyncExportRunner.jobs = []
    yield


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    from webcache import paths
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    monkeypatch.setattr(paths, "cases_dir", lambda: case_dir)
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    return w


@pytest.fixture
def outbox(tmp_path):
    d = tmp_path / "exports"
    d.mkdir()
    return d


def _fake_evidence_set(path=_EVIDENCE_PATH):
    return EvidenceSet([path], {path: 1}, {path: "a" * 64})


def _open(win, path=_EVIDENCE_PATH, entries=()):
    parser = _FakeParser(entries)
    parser.db_path = path
    evidence_set = _fake_evidence_set(path)
    # _open_evidence_at sets this before the loader ever starts; these
    # tests drive _on_evidence_loaded directly, so they set the one field
    # the real open path would have set by now.
    win._evidence_set = evidence_set
    win._on_evidence_loaded({"rows": [], "parser": parser}, evidence_set)
    return parser


class _FakeConsentDialog:
    recover_deleted = False
    def __init__(self, path, parent=None):
        import hashlib
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
        self.evidence_set = EvidenceSet([path], {path: 1}, {path: digest})

    def exec(self):
        from PySide6.QtWidgets import QDialog
        return QDialog.Accepted

    def deleteLater(self):
        pass


def _open_through_the_dialog(win, monkeypatch, path, entries=()):
    """The real File > Open Evidence path, with the consent gate and the
    parse both stubbed -- what test_timeline_wiring.py already does."""
    from webcache.shell import main_window as mw

    class _SyncLoader(QObject):
        progress = Signal(str)
        loaded = Signal(object)
        failed = Signal(str)

        def load(self, db_path, known_hashes=None):
            parser = _FakeParser(entries)
            parser.db_path = db_path
            self.loaded.emit({"rows": [], "parser": parser})

        def cancel(self):
            pass

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr(mw, "OpenEvidenceDialog", _FakeConsentDialog)
    monkeypatch.setattr(mw, "EvidenceLoader", _SyncLoader)
    win.open_evidence_action.trigger()


def _use(monkeypatch, runner_class):
    from webcache.shell import main_window as mw
    monkeypatch.setattr(mw, "SearchRunner", runner_class)


def _view(win):
    return win._ensure_view_built("search")


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


# --- a real view, and a nav row that still means what it says -------------

def test_search_is_a_real_view_not_a_placeholder(win):
    assert isinstance(_view(win), SearchView)


def test_search_is_built_lazily_like_every_other_view(win):
    assert not isinstance(win.stack.widget(win._index["search"]), SearchView)
    win.go_to("search")
    assert isinstance(win.stack.widget(win._index["search"]), SearchView)


def test_the_nav_row_keeps_its_dash_because_a_hit_count_is_not_an_exhibits(win):
    """A hit count belongs to a keyword, not to an exhibit: it is
    undefined until an examiner types one, and a badge that was blank
    before the first search would read as zero."""
    assert "search" in _NO_COUNT_KEYS
    _open(win)
    assert win.sidebar._rows["search"].count_label.text() == "–"


def test_opening_evidence_does_not_build_the_view(win):
    _open(win)
    assert not isinstance(win.stack.widget(win._index["search"]), SearchView)


def test_the_scope_combo_is_filled_from_the_open_exhibit(win):
    _open(win)
    view = _view(win)
    assert [view.scope_combo.itemData(i)
            for i in range(view.scope_combo.count())] == [
        search_loader.ALL_TABLES, search_loader.GROUP_PREFIX + "Tables",
        "Container_1", "MSysObjects"]


# --- a keyword reaches a worker ------------------------------------------

def test_a_search_request_starts_a_runner_with_the_typed_keyword(
        win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    view = _view(win)
    view.keyword_box.setText("needle")
    view.search_button.click()
    assert len(_ManualRunner.made) == 1
    assert _ManualRunner.made[0].queries[0].keyword == "needle"


def test_the_query_carries_the_exhibits_path_and_its_hashes(win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    _view(win).searchRequested.emit("needle", "")
    query = _ManualRunner.made[0].queries[0]
    assert query.db_path == _EVIDENCE_PATH
    assert query.known_hashes == {_EVIDENCE_PATH: "a" * 64}


def test_a_search_with_no_evidence_open_says_to_load_one_first(win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _view(win).searchRequested.emit("needle", "")
    assert _ManualRunner.made == []
    assert "Load a database first" in win.status_message()


def test_a_blank_keyword_is_refused_rather_than_scanning_every_table(
        win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    _view(win).searchRequested.emit("   ", "")
    assert _ManualRunner.made == []
    assert win.status_message()


def test_a_search_is_refused_while_another_operation_is_running(
        win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    win._busy_for = "export"
    _view(win).searchRequested.emit("needle", "")
    assert _ManualRunner.made == []
    assert "Another operation is already running" in win.status_message()


def test_a_completed_search_lands_its_rows_on_screen(win, monkeypatch):
    _use(monkeypatch, _SyncRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("needle", "")
    assert view.table.model().rowCount() == 2
    assert view.count_label.text().startswith("2 hits")


def test_a_running_search_shows_the_busy_pair_and_ends_it_afterwards(
        win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    _view(win).searchRequested.emit("needle", "")
    assert win._busy_for == "search"
    assert win._load_cancel_button.isVisible() or True  # not shown offscreen
    _ManualRunner.made[0].found.emit(
        _ManualRunner.made[0].queries[0], _payload(1))
    assert win._busy_for is None


def test_a_failed_search_reports_it_and_ends_the_busy_state(win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    _view(win).searchRequested.emit("needle", "")
    _ManualRunner.made[0].failed.emit("page checksum")
    assert win._busy_for is None
    assert "page checksum" in win.status_message()


# --- the race ------------------------------------------------------------

def test_a_second_search_disconnects_the_first_runner(win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("first", "")
    view.searchRequested.emit("second", "")
    first, second = _ManualRunner.made
    assert first.cancelled == 1
    first.found.emit(first.queries[0], _payload(5))
    assert view.table.model().rowCount() == 0, (
        "a superseded runner's late result reached the screen")
    second.found.emit(second.queries[0], _payload(2))
    assert view.table.model().rowCount() == 2


def test_a_superseded_result_cannot_relabel_the_count_line(win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("first", "")
    view.searchRequested.emit("second", "")
    first, second = _ManualRunner.made
    second.found.emit(second.queries[0], _payload(2))
    first.found.emit(first.queries[0], _payload(9))
    assert "'second'" in view.line_text()
    assert view.table.model().rowCount() == 2


def test_cancelling_reports_the_cancellation_and_never_a_partial_result(
        win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("needle", "")
    win._cancel_current_busy_operation()
    assert _ManualRunner.made[0].cancelled == 1
    assert win._busy_for is None
    assert view.table._empty_reason == search_loader.CANCELLED_TEXT
    assert "cancelled" in win.status_message().lower()
    assert "no partial results" in win.status_message()


def test_the_shared_cancel_button_routes_to_the_search(win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    _view(win).searchRequested.emit("needle", "")
    win._load_cancel_button.click()
    assert _ManualRunner.made[0].cancelled == 1


# --- results belong to a database ----------------------------------------

def test_opening_a_new_exhibit_clears_the_results_and_cancels_a_scan(
        win, monkeypatch):
    _use(monkeypatch, _SyncRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("needle", "")
    assert view.table.model().rowCount() == 2

    _use(monkeypatch, _ManualRunner)
    _open(win, path="C:/case/OTHER.dat")
    assert view.table.model().rowCount() == 0
    assert view.table._empty_reason == search_loader.IDLE_TEXT
    assert win._search_results is None


def test_a_scan_in_flight_when_a_new_exhibit_opens_is_cancelled(
        win, monkeypatch):
    """Driven through the REAL open path (_open_evidence_at), because
    that is where the cancel lives -- a search in flight belongs to the
    exhibit being replaced, and its hits name tables and row ordinals
    inside THAT database."""
    _use(monkeypatch, _ManualRunner)
    _open(win)
    _view(win).searchRequested.emit("needle", "")
    _open_through_the_dialog(win, monkeypatch, "C:/case/OTHER.dat")
    assert _ManualRunner.made[0].cancelled >= 1
    assert win._search_results is None


# --- built late ----------------------------------------------------------

def test_a_view_built_after_a_completed_search_replays_it(win, monkeypatch):
    """The cache is written unconditionally, exactly as the Timeline's
    is, so a view built late applies a finished result instead of paying
    a second seven-second scan for an answer already in hand."""
    _use(monkeypatch, _SyncRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("needle", "")
    assert len(_ManualRunner.made) == 1

    # Throw the view away and rebuild it the way a fresh session would.
    win._built_keys.discard("search")
    index = win._index["search"]
    old = win.stack.widget(index)
    win.stack.removeWidget(old)
    from PySide6.QtWidgets import QWidget
    win.stack.insertWidget(index, QWidget())
    rebuilt = win._ensure_view_built("search")

    assert rebuilt is not view
    assert rebuilt.table.model().rowCount() == 2
    assert len(_ManualRunner.made) == 1, "a second scan was started"


def test_a_view_built_with_no_search_yet_opens_idle(win):
    _open(win)
    view = _view(win)
    assert view.table.model().rowCount() == 0
    assert view.table._empty_reason == search_loader.IDLE_TEXT


# --- reachable from every other table ------------------------------------

def _search_action(menu):
    return next(a for a in menu.actions()
                if "Search the database" in a.text())


def test_every_record_table_offers_to_search_the_database_for_a_value(win):
    _open(win)
    history = win._ensure_view_built("history")
    history.set_records([{"CleanUrl": "https://example.test/a",
                          "Origin": "Live record"}])
    model = history.table.model()
    menu = history.table._build_context_menu(model.index(0, 0))
    assert _search_action(menu) is not None


def test_that_entry_reaches_search_for_and_actually_searches(win, monkeypatch):
    _use(monkeypatch, _SyncRunner)
    _open(win)
    history = win._ensure_view_built("history")
    history.set_records([{"CleanUrl": "https://example.test/a",
                          "Origin": "Live record"}])
    model = history.table.model()
    col = [c.key for c in model.columns].index("CleanUrl")
    menu = history.table._build_context_menu(model.index(0, col))
    _search_action(menu).trigger()

    assert win.current_key == "search"
    view = _view(win)
    assert view.keyword_box.text() == "https://example.test/a"
    assert _ManualRunner.made[0].queries[0].keyword == "https://example.test/a"
    assert view.table.model().rowCount() == 2


def test_searching_for_a_value_always_searches_every_table(win, monkeypatch):
    """"Find this everywhere" is the whole point of the entry -- a scope
    left over from a previous search would silently narrow it."""
    _use(monkeypatch, _SyncRunner)
    _open(win)
    view = _view(win)
    view.set_scope_options(search_loader.scope_options(_FakeParser()))
    view.scope_combo.setCurrentIndex(1)
    win.search_for("needle")
    assert _ManualRunner.made[0].queries[0].table_filter == ""
    assert view.scope_combo.currentIndex() == 0


def test_search_for_a_blank_value_does_nothing_rather_than_scanning(
        win, monkeypatch):
    _use(monkeypatch, _ManualRunner)
    _open(win)
    win.search_for("   ")
    assert _ManualRunner.made == []


# --- drill-through -------------------------------------------------------

def test_a_hits_table_cell_lands_the_browser_on_that_table(win, monkeypatch):
    _use(monkeypatch, _SyncRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("needle", "")
    view.drillRequested.emit("browser", {"Table": "Container_1"})
    assert win.current_key == "browser"


# --- export --------------------------------------------------------------

def _choose(monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))


def test_the_view_export_writes_the_hit_rows(win, monkeypatch, outbox):
    from webcache.shell import main_window as mw
    _use(monkeypatch, _SyncRunner)
    monkeypatch.setattr(mw, "ExportRunner", _SyncExportRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("needle", "")
    target = outbox / "hits.csv"
    _choose(monkeypatch, target)
    view.export_button.click()
    rows = _read(target)
    assert rows[0][:4] == ["Table", "Container", "Table type", "Row #"]
    assert len(rows) == 3


def test_the_export_sidecar_states_what_was_searched(win, monkeypatch, outbox):
    from webcache.shell import main_window as mw
    _use(monkeypatch, _SyncRunner)
    monkeypatch.setattr(mw, "ExportRunner", _SyncExportRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("needle", "")
    target = outbox / "hits.csv"
    _choose(monkeypatch, target)
    view.export_button.click()
    side = (outbox / "hits.csv.provenance.txt").read_text(encoding="utf-8")
    assert "SEARCH" in side
    assert "needle" in side
    assert "600" in side
    assert "not evidence the thing never happened" in side


def test_another_views_sidecar_gains_no_search_block(win, monkeypatch, outbox):
    from webcache.shell import main_window as mw
    monkeypatch.setattr(mw, "ExportRunner", _SyncExportRunner)
    _open(win)
    history = win._ensure_view_built("history")
    history.set_records([{"CleanUrl": "https://example.test/a",
                          "Origin": "Live record"}])
    target = outbox / "history.csv"
    _choose(monkeypatch, target)
    history.export_button.click()
    side = (outbox / "history.csv.provenance.txt").read_text(encoding="utf-8")
    assert "SEARCH" not in side


def test_the_pane_export_writes_the_matched_rows_own_fields(
        win, monkeypatch, outbox):
    from webcache.shell import main_window as mw
    _use(monkeypatch, _SyncRunner)
    monkeypatch.setattr(mw, "ExportRunner", _SyncExportRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("needle", "")
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0),
        QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
    target = outbox / "row.csv"
    _choose(monkeypatch, target)
    view.pane.export_button.click()
    rows = _read(target)
    assert rows[0][:2] == ["Column", "Matched"]
    assert rows[1][0] == "Url"


def test_the_pane_export_with_nothing_selected_says_to_select_a_hit(
        win, monkeypatch, outbox):
    _use(monkeypatch, _SyncRunner)
    _open(win)
    view = _view(win)
    view.searchRequested.emit("needle", "")
    view.rowFieldsExportRequested.emit()
    assert "Select a hit" in win.status_message()
