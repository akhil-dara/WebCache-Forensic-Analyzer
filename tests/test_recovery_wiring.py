"""The wiring for Evidence > Recover deleted records. recovery_engine.py
carves deleted records, and an engine nothing outside it calls would be a
defect. These tests assert the
CONNECTIONS end to end, in the style test_wiring.py already established
for the evidence-load path, deliberately in a way that fails if any one of
them is missing:

- Evidence > Recover deleted records is disabled until an exhibit is open,
  and reaches a real RecoveryLoader with the CURRENT parser -- not a menu
  item that looks live and does nothing.
- The button on the Deleted Records view reaches the identical code path
  as the menu action, not a second, divergent one.
- A completed scan really lands carved rows in HistoryView.table.model()
  MERGED with the live rows already there, really lands the full recovered
  set in the Deleted Records view, and the count line really states the
  live/recovered split -- not a static caveat any more.
- Before any scan, the count line still says live-only, and now also says
  how to get the rest.
- The busy indicator (shared with the evidence load -- see main_window.py's
  own comment on why one pair, not two) really shows during a scan and
  hides on every exit path, and Cancel genuinely stops it: no rows land,
  and a late result from an already-cancelled scan cannot land them either.
- Opening a NEW exhibit while a recovery scan for the OLD one is still in
  flight really cancels and disconnects it, so a late result can never
  attribute carved rows to the wrong exhibit -- the same race
  _cancel_pending_load already closes for the loader itself, proved here
  for the second worker type.
"""
import hashlib

import pytest
from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtWidgets import QDialog, QFileDialog

from webcache.provenance import EvidenceSet
from webcache.shell.main_window import MainWindow
from webcache.views.recovery import NOT_SCANNED_NOTE

from tests.fixtures import make_rows


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def _history_view(win):
    return win._ensure_view_built("history")


def _recovery_view(win):
    return win._ensure_view_built("recovery")


class _FakeParser:
    """A stand-in for WebCacheParser -- _start_recovery only needs this to
    be non-None and to be the exact object handed to RecoveryLoader.start,
    so identity (not real ESE attributes) is what these tests check."""

    def __init__(self, name):
        self.name = name
        self.db = None
        self.db_path = "C:/case/%s.dat" % name
        self.containers_meta = []
        self.container_type_map = {}
        self.all_entries = []


class _FakeConsentDialog:
    recover_deleted = False
    instances = []

    def __init__(self, path, parent=None):
        self.path = path
        fake_hash = hashlib.sha256(path.encode("utf-8")).hexdigest()
        self.evidence_set = EvidenceSet([path], {path: 1}, {path: fake_hash})
        _FakeConsentDialog.instances.append(self)

    def exec(self):
        return QDialog.Accepted

    def deleteLater(self):
        pass


class _DeferredFakeLoader(QObject):
    """Mirrors test_wiring.py's own _DeferredFakeLoader -- .load() does not
    emit synchronously, so a test can control exactly when an evidence load
    completes relative to a recovery scan in flight for a PREVIOUS load."""
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    instances = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cancelled = False
        _DeferredFakeLoader.instances.append(self)

    def load(self, db_path, known_hashes=None):
        pass

    def cancel(self):
        self.cancelled = True

    def finish_now(self, result):
        self.loaded.emit(result)


class _DeferredFakeRecoveryLoader(QObject):
    """A stand-in for RecoveryLoader whose .start() does not emit
    synchronously -- lets a test control exactly when a scan "completes"
    relative to other actions (a Cancel click, a new Open Evidence)."""
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    instances = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parser = None
        self.cancelled = False
        _DeferredFakeRecoveryLoader.instances.append(self)

    def start(self, parser):
        self.parser = parser

    def cancel(self):
        self.cancelled = True

    def finish_now(self, engine):
        self.loaded.emit(engine)

    def fail_now(self, message):
        self.failed.emit(message)


class _FakeEngine:
    """A stand-in for recovery_loader's row-building input -- MainWindow
    calls carved_history_rows(engine)/deleted_records_rows(engine) on
    whatever loader.loaded hands it, so this only needs to satisfy those
    two functions' real contract (see test_recovery_loader.py for that
    contract's own tests): .structured_records and .all_artifacts()."""

    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = structured_records or []
        self._artifacts = artifacts or []

    def all_artifacts(self):
        return self._artifacts


def _history_carved_record(url="https://example.com/deleted"):
    return {
        "Url": url, "CleanUrl": url, "ContainerType": "History",
        "SPS_PageTitle": "", "ModifiedTime_raw": 0, "AccessedTime_raw": 0,
        "CreationTime_raw": 0, "SPS_LastVisitLocal_raw": None,
        "SPS_VisitCount": None, "AccessCount": 1, "Flags": 0,
        "Source": "WebCacheV01.dat", "Offset": 1024, "Page": 3,
        "RecoverySource": "Structured record reconstruction",
        "Confidence": "high",
    }


@pytest.fixture(autouse=True)
def _reset_fakes():
    _FakeConsentDialog.instances = []
    _DeferredFakeLoader.instances = []
    _DeferredFakeRecoveryLoader.instances = []
    yield


def _open_exhibit(win, monkeypatch, path, rows=None, parser=None):
    """Drives a full, synchronous Open Evidence for `path` through the real
    open_evidence_action, using a synchronous fake loader -- exactly what
    test_wiring.py's own _FakeLoader-based tests do -- landing `rows` (with
    `parser`, non-None when a test needs recovery to be reachable) in
    HistoryView for real."""
    from webcache.shell import main_window as mw

    class _SyncLoader(QObject):
        progress = Signal(str)
        loaded = Signal(object)
        failed = Signal(str)

        def load(self, db_path, known_hashes=None):
            self.loaded.emit({"rows": rows or [], "parser": parser})

        def cancel(self):
            pass

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr(mw, "OpenEvidenceDialog", _FakeConsentDialog)
    monkeypatch.setattr(mw, "EvidenceLoader", _SyncLoader)
    win.open_evidence_action.trigger()


# --- the action: disabled with nothing open, enabled once a parser exists -

def test_recover_action_exists_on_the_evidence_menu(win):
    action = win.recover_action
    assert action is not None
    assert action in win.menu_for_evidence().actions()


def test_recover_action_is_disabled_before_any_exhibit_is_open(win):
    assert not win.recover_action.isEnabled()


def test_recover_action_is_disabled_when_the_load_carried_no_parser(
        win, monkeypatch, tmp_path):
    """Many existing tests (and a real failed/degenerate load) hand
    _on_evidence_loaded a result with parser: None -- recovery genuinely
    cannot run without one, so the action must stay disabled rather than
    reach RecoveryLoader.start(None)."""
    path = str(tmp_path / "exhibit.dat")
    _open_exhibit(win, monkeypatch, path, rows=make_rows(5), parser=None)
    assert not win.recover_action.isEnabled()


def test_recover_action_is_enabled_once_a_real_parser_is_loaded(
        win, monkeypatch, tmp_path):
    path = str(tmp_path / "exhibit.dat")
    _open_exhibit(win, monkeypatch, path, rows=make_rows(5),
                 parser=_FakeParser("exhibit"))
    assert win.recover_action.isEnabled()


# --- before any scan: live-only, and now says how to get the rest ---------

def test_history_count_line_still_says_live_only_before_a_scan(
        win, monkeypatch, tmp_path):
    path = str(tmp_path / "exhibit.dat")
    _open_exhibit(win, monkeypatch, path, rows=make_rows(5),
                 parser=_FakeParser("exhibit"))
    assert "not yet recovered" in _history_view(win).line_text().lower()


def test_the_note_now_says_how_to_get_the_rest(win, monkeypatch, tmp_path):
    """The note tells the examiner how to get the rest. Pinned against the real note text
    reaching the screen, not just the module constant in isolation."""
    path = str(tmp_path / "exhibit.dat")
    _open_exhibit(win, monkeypatch, path, rows=make_rows(5),
                 parser=_FakeParser("exhibit"))
    text = _history_view(win).line_text().lower()
    assert "recover deleted records" in text


def test_deleted_records_view_says_no_scan_has_run_before_one_does(
        win, monkeypatch, tmp_path):
    path = str(tmp_path / "exhibit.dat")
    _open_exhibit(win, monkeypatch, path, rows=make_rows(5),
                 parser=_FakeParser("exhibit"))
    assert "no scan has run yet" in _recovery_view(win).count_label.text().lower()


# --- starting a scan: menu action and the view's own button, same path ----

def test_recover_action_reaches_recoveryloader_with_the_current_parser(
        win, monkeypatch, tmp_path):
    from webcache.shell import main_window as mw
    monkeypatch.setattr(mw, "RecoveryLoader", _DeferredFakeRecoveryLoader)
    path = str(tmp_path / "exhibit.dat")
    parser = _FakeParser("exhibit")
    _open_exhibit(win, monkeypatch, path, rows=make_rows(5), parser=parser)

    win.recover_action.trigger()

    assert len(_DeferredFakeRecoveryLoader.instances) == 1
    assert _DeferredFakeRecoveryLoader.instances[-1].parser is parser


def test_the_deleted_records_views_own_button_reaches_the_same_path(
        win, monkeypatch, tmp_path):
    from webcache.shell import main_window as mw
    monkeypatch.setattr(mw, "RecoveryLoader", _DeferredFakeRecoveryLoader)
    path = str(tmp_path / "exhibit.dat")
    parser = _FakeParser("exhibit")
    _open_exhibit(win, monkeypatch, path, rows=make_rows(5), parser=parser)

    _recovery_view(win).recoverRequested.emit()

    assert len(_DeferredFakeRecoveryLoader.instances) == 1
    assert _DeferredFakeRecoveryLoader.instances[-1].parser is parser


def test_recover_action_does_nothing_without_an_open_exhibit(win, monkeypatch):
    from webcache.shell import main_window as mw
    monkeypatch.setattr(mw, "RecoveryLoader", _DeferredFakeRecoveryLoader)
    win.recover_action.trigger()  # disabled -- and even if forced, must no-op
    win._start_recovery()
    assert _DeferredFakeRecoveryLoader.instances == []


# --- action disabled while running, re-enabled on every exit path ---------

def _start_scan(win, monkeypatch, tmp_path, name="exhibit.dat"):
    from webcache.shell import main_window as mw
    monkeypatch.setattr(mw, "RecoveryLoader", _DeferredFakeRecoveryLoader)
    path = str(tmp_path / name)
    parser = _FakeParser(name)
    _open_exhibit(win, monkeypatch, path, rows=make_rows(5), parser=parser)
    win.recover_action.trigger()
    return _DeferredFakeRecoveryLoader.instances[-1]


def test_recover_action_is_disabled_the_moment_a_scan_starts(win, monkeypatch, tmp_path):
    _start_scan(win, monkeypatch, tmp_path)
    assert not win.recover_action.isEnabled()


def test_recover_button_on_the_view_is_also_disabled_while_scanning(
        win, monkeypatch, tmp_path):
    _start_scan(win, monkeypatch, tmp_path)
    assert not _recovery_view(win).recover_button.isEnabled()


def test_recover_action_is_reenabled_after_a_successful_scan(win, monkeypatch, tmp_path):
    loader = _start_scan(win, monkeypatch, tmp_path)
    loader.finish_now(_FakeEngine())
    assert win.recover_action.isEnabled()


def test_recover_action_is_reenabled_after_a_failed_scan(win, monkeypatch, tmp_path):
    loader = _start_scan(win, monkeypatch, tmp_path)
    loader.fail_now("page 4021 is corrupt")
    assert win.recover_action.isEnabled()


def test_recover_action_is_reenabled_after_cancel(win, monkeypatch, tmp_path):
    _start_scan(win, monkeypatch, tmp_path)
    win._load_cancel_button.click()
    assert win.recover_action.isEnabled()


# --- busy indicator: shared with the evidence load, shown/hidden correctly

def test_busy_indicator_shows_while_a_scan_is_in_flight(win, monkeypatch, tmp_path):
    _start_scan(win, monkeypatch, tmp_path)
    assert win._load_progress.isVisible()
    assert win._load_cancel_button.isVisible()


def test_busy_indicator_is_indeterminate_during_a_scan_too(win, monkeypatch, tmp_path):
    _start_scan(win, monkeypatch, tmp_path)
    assert win._load_progress.minimum() == 0
    assert win._load_progress.maximum() == 0


def test_busy_indicator_hides_after_a_successful_scan(win, monkeypatch, tmp_path):
    loader = _start_scan(win, monkeypatch, tmp_path)
    loader.finish_now(_FakeEngine())
    assert not win._load_progress.isVisible()
    assert not win._load_cancel_button.isVisible()


def test_busy_indicator_hides_after_a_failed_scan(win, monkeypatch, tmp_path):
    loader = _start_scan(win, monkeypatch, tmp_path)
    loader.fail_now("boom")
    assert not win._load_progress.isVisible()
    assert not win._load_cancel_button.isVisible()


def test_recovery_progress_signal_reaches_the_status_bar(win, monkeypatch, tmp_path):
    loader = _start_scan(win, monkeypatch, tmp_path)
    loader.progress.emit("Recovering deleted records: 4,200 candidate record(s) scanned…")
    assert "4,200" in win.status_message()


def test_cancel_button_cancels_the_recovery_loader_not_the_evidence_loader(
        win, monkeypatch, tmp_path):
    """The shared Cancel button must route to whichever operation is
    ACTUALLY using it -- proved by starting a recovery scan (no evidence
    load in flight) and confirming the click reaches the recovery loader's
    own cancel(), not a no-op or a crash from touching a nonexistent
    evidence loader."""
    loader = _start_scan(win, monkeypatch, tmp_path)
    assert loader.cancelled is False
    win._load_cancel_button.click()
    assert loader.cancelled is True


def test_cancel_leaves_the_app_clean_and_usable(win, monkeypatch, tmp_path):
    _start_scan(win, monkeypatch, tmp_path)
    win._load_cancel_button.click()

    assert win.recover_action.isEnabled()
    assert not win._load_progress.isVisible()
    assert not win._load_cancel_button.isVisible()
    assert "cancelled" in win.status_message().lower()
    assert _recovery_view(win).recover_button.isEnabled()


# --- THE CANCEL-DISCARD RULE: a late result after Cancel never lands ------

def test_a_result_that_races_in_after_cancel_never_populates_the_screen(
        win, monkeypatch, tmp_path):
    """RecoveryLoader.cancel() is best-effort (see its own docstring, and
    EvidenceLoader.cancel's identical caveat) -- a worker that raced past
    its last interruption check can still finish and emit `loaded` AFTER
    Cancel was clicked. This proves _cancel_pending_recovery's disconnect
    is what actually stops that from reaching History or the Deleted
    Records view, not merely hiding the busy widgets."""
    history = _history_view(win)
    loader = _start_scan(win, monkeypatch, tmp_path)
    original_model = history.table.model()
    win._load_cancel_button.click()

    loader.finish_now(_FakeEngine(structured_records=[_history_carved_record()]))

    assert history.table.model() is original_model, (
        "a result that raced in after Cancel reached History anyway")
    assert "cancelled" in win.status_message().lower(), (
        "the late result's own status text overwrote the cancellation "
        "message the examiner had already been shown")


# --- a completed scan: merge into History, populate Deleted Records -------

def test_a_completed_scan_merges_carved_rows_into_history(win, monkeypatch, tmp_path):
    live_rows = make_rows(5)
    loader = _start_scan(win, monkeypatch, tmp_path)
    # Overwrite the live rows this scan is scoped to, so the merge below is
    # checked against a known baseline rather than whatever make_rows(5)
    # happened to produce inside _start_scan.
    win._live_history_rows = live_rows

    loader.finish_now(_FakeEngine(structured_records=[
        _history_carved_record("https://example.com/deleted-1"),
        _history_carved_record("https://example.com/deleted-2"),
    ]))

    history = _history_view(win)
    assert history.table.model().rowCount() == len(live_rows) + 2
    urls = {history.table.model().row_at(i)["CleanUrl"]
           for i in range(history.table.model().rowCount())}
    assert "https://example.com/deleted-1" in urls
    assert "https://example.com/deleted-2" in urls


def test_the_count_line_states_the_live_and_recovered_split(win, monkeypatch, tmp_path):
    """Something like '1,234 records (1,180 live, 54 recovered)'."""
    loader = _start_scan(win, monkeypatch, tmp_path)
    win._live_history_rows = make_rows(3)

    loader.finish_now(_FakeEngine(structured_records=[_history_carved_record()]))

    text = _history_view(win).line_text().lower()
    assert "3" in text and "live" in text
    assert "1" in text and "recovered" in text


def test_a_completed_scan_populates_the_deleted_records_view(win, monkeypatch, tmp_path):
    loader = _start_scan(win, monkeypatch, tmp_path)
    win._live_history_rows = make_rows(3)

    loader.finish_now(_FakeEngine(
        structured_records=[_history_carved_record()],
        artifacts=[{"Url": "Visited: bob@https://msn.com/y",
                   "CleanUrl": "https://msn.com/y", "ContainerType": "",
                   "NearbyFiletime": None, "Source": "V01.log",
                   "Offset": 55, "Page": None,
                   "RecoverySource": "Transaction log", "Confidence": "low"}]))

    recovery = _recovery_view(win)
    assert recovery.table.model() is not None
    assert recovery.table.model().rowCount() == 2


def test_the_deleted_records_count_line_states_the_merge_shortfall(
        win, monkeypatch, tmp_path):
    """The History view merges only carved records
    whose ContainerType == "History" -- by definition excluding every
    other recovered row, real container or none at all. An examiner
    reading "3 records" here must be able to tell that only 1 of them
    reached History, not wonder where the other 2 went."""
    loader = _start_scan(win, monkeypatch, tmp_path)
    win._live_history_rows = make_rows(3)

    loader.finish_now(_FakeEngine(
        structured_records=[
            _history_carved_record(),
            dict(_history_carved_record("https://example.com/other-container"),
                ContainerType="Cookies"),
        ],
        artifacts=[{"Url": "Visited: bob@https://msn.com/y",
                   "CleanUrl": "https://msn.com/y", "ContainerType": "",
                   "NearbyFiletime": None, "Source": "V01.log",
                   "Offset": 55, "Page": None,
                   "RecoverySource": "Transaction log", "Confidence": "low"}]))

    text = _recovery_view(win).count_label.text().lower()
    assert "3" in text  # the total recovered
    assert "1" in text  # merged into History
    assert "2" in text  # did not
    assert "history" in text


def test_a_failed_scan_leaves_history_showing_live_only(win, monkeypatch, tmp_path):
    """A failed scan must never touch History at all -- it still shows
    exactly the live rows the load itself produced (_start_scan's own
    _open_exhibit call, 5 of them), with the live-only note untouched."""
    loader = _start_scan(win, monkeypatch, tmp_path)
    loader.fail_now("page 4021 is corrupt")

    history = _history_view(win)
    assert history.table.model().rowCount() == 5
    assert "not yet recovered" in history.line_text().lower()
    assert "corrupt" in win.status_message().lower()


# --- the race: a NEW exhibit must cancel and disconnect an in-flight scan -

def test_opening_a_new_exhibit_cancels_a_pending_recovery_scan(win, monkeypatch, tmp_path):
    loader = _start_scan(win, monkeypatch, tmp_path, name="exhibit_a.dat")
    assert loader.cancelled is False

    _open_exhibit(win, monkeypatch, str(tmp_path / "exhibit_b.dat"),
                 rows=make_rows(9), parser=_FakeParser("exhibit_b"))

    assert loader.cancelled is True


def test_a_scan_that_finishes_late_for_the_old_exhibit_never_reaches_the_new_ones_history(
        win, monkeypatch, tmp_path):
    """THE test: exhibit A is opened, a recovery scan starts for it, then
    exhibit B is opened (superseding A) before A's scan reports back.
    A's carved rows must never land on B's History table:
    _cancel_pending_load() closes a race where a superseded loader
    overwrote a newer exhibit's rows, and a second worker type introduces
    the same hazard.
    """
    loader_a = _start_scan(win, monkeypatch, tmp_path, name="exhibit_a.dat")
    rows_b = make_rows(9)

    _open_exhibit(win, monkeypatch, str(tmp_path / "exhibit_b.dat"),
                 rows=rows_b, parser=_FakeParser("exhibit_b"))
    history = _history_view(win)
    assert history.table.model().rowCount() == 9

    # A's scan finishes LATE, after B is already on screen. Best-effort
    # cancellation (see RecoveryLoader.cancel's docstring) cannot itself
    # guarantee this never fires -- the disconnect in
    # _cancel_pending_recovery is what must stop it from landing anyway.
    loader_a.finish_now(_FakeEngine(structured_records=[
        _history_carved_record("https://example.com/should-never-appear")]))

    assert history.table.model().rowCount() == 9, (
        "exhibit A's carved rows landed on exhibit B's History table")
    urls = {history.table.model().row_at(i)["CleanUrl"]
           for i in range(history.table.model().rowCount())}
    assert "https://example.com/should-never-appear" not in urls


def test_a_superseded_recovery_scan_is_disconnected_not_just_cancelled(
        win, monkeypatch, tmp_path):
    """The mechanism behind the test above, isolated -- mirrors
    test_wiring.py's own
    test_a_superseded_load_is_cancelled_and_disconnected for the loader."""
    loader_a = _start_scan(win, monkeypatch, tmp_path, name="exhibit_a.dat")

    _open_exhibit(win, monkeypatch, str(tmp_path / "exhibit_b.dat"),
                 rows=make_rows(2), parser=_FakeParser("exhibit_b"))

    received = []
    loader_a.loaded.connect(received.append)  # a fresh probe connection
    loader_a.finish_now(_FakeEngine(structured_records=[_history_carved_record()]))
    assert received  # our own probe fired...

    history = _history_view(win)
    assert history.table.model().rowCount() == 2, (
        "MainWindow's own loaded-signal connection to the superseded "
        "recovery loader was still live")


def test_opening_a_new_exhibit_resets_the_stuck_recovering_button(
        win, monkeypatch, tmp_path):
    """A recovery scan for exhibit A still in flight when exhibit B opens
    is cancelled and disconnected (see the tests above), but that alone
    only touches the LOADER'S wiring -- nothing about it tells the Deleted
    Records view's own button to stop reading "Recovering…". Without
    resetting it explicitly on every successful load, that button would
    stay disabled and mislabelled for the rest of the session even though
    recover_action itself (and everything else about exhibit B) is back to
    normal."""
    _start_scan(win, monkeypatch, tmp_path, name="exhibit_a.dat")
    recovery_view = _recovery_view(win)
    assert not recovery_view.recover_button.isEnabled()

    _open_exhibit(win, monkeypatch, str(tmp_path / "exhibit_b.dat"),
                 rows=make_rows(2), parser=_FakeParser("exhibit_b"))

    assert recovery_view.recover_button.isEnabled()
    assert recovery_view.recover_button.text() == "Recover deleted records…"
