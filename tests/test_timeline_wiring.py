"""The wiring for Timeline: the nav key "timeline" builds a real view with
a real count, opening evidence fills all four grains, a recovery scan
re-buckets them with carved records folded in, and the pane's own export
reaches a writer.

THE BADGE COUNTS RECORDS, NOT ROWS. The row count changes with the grain,
and a badge that changes when you press a button is a badge that means
nothing. It uses the same key_timestamp predicate the buckets do, so badge
and view cannot drift -- the earlier badge used `AccessedTime or ModifiedTime`
and omitted CreationTime, so it under-counted against its own view.

Mirrors test_headers_wiring.py's shape and its synchronous export runner,
so the record export is proved by OPENING THE FILE.
"""
import csv

import pytest
from PySide6.QtCore import QItemSelectionModel, QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog

from webcache.provenance import EvidenceSet
from webcache.shell import timeline_loader
from webcache.shell.export_runner import ExportWorker
from webcache.shell.main_window import MainWindow, _NO_COUNT_KEYS
from webcache.views.timeline import TimelineView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"
_FT_BASE = 133546220420000000          # 2024-03-11 09:14:02 UTC
_DAY = 24 * 60 * 60 * 10_000_000


def _entry(entry_id=1, day=0, **overrides):
    base = {"ContainerType": "History", "ContainerId": 3, "EntryId": entry_id,
            "ContainerName": "History",
            "Url": "https://example%d.test/a" % entry_id,
            "CleanUrl": "https://example%d.test/a" % entry_id,
            "ModifiedTime_raw": _FT_BASE + day * _DAY}
    base.update(overrides)
    return base


class _FakeParser:
    db_path = _EVIDENCE_PATH
    source_hashes = {"WebCacheV01.dat": "0" * 64}

    def __init__(self, entries=()):
        self.all_entries = list(entries)
        self.db = None
        self.containers_meta = []
        self.container_type_map = {}


class _StubEngine:
    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = list(structured_records or [])
        self._artifacts = list(artifacts or [])

    def all_artifacts(self):
        return self._artifacts


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
def _reset_jobs():
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
def exhibit(tmp_path):
    d = tmp_path / "exhibit"
    d.mkdir()
    return d


@pytest.fixture
def outbox(tmp_path):
    d = tmp_path / "exports"
    d.mkdir()
    return d


def _view(win):
    return win._ensure_view_built("timeline")


def _nav_count(win):
    text = win.sidebar._rows["timeline"].count_label.text()
    return int(text.replace(",", "")) if text.strip("-–") else None


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                       {_EVIDENCE_PATH: "a" * 64})


def _timeline_token(win):
    """Identity of the last delivered build result, or None.

    _on_timeline_built assigns self._timeline_results as its FIRST act
    after setting the badge, so a change of identity here is proof that
    the queued `built` signal has actually been delivered and handled on
    the GUI thread -- not merely that the worker thread stopped.
    """
    return id(getattr(win, "_timeline_results", None))


#: The token a window that has never delivered a build result has.
_SINCE_NEW = id(None)


def _still_running(worker):
    """isRunning(), but a worker whose C++ half is gone counts as finished.

    TimelineBuilder connects `finished -> deleteLater` (timeline_builder.py),
    and QTest.qWait pumps the event loop -- which is exactly what processes
    that deferred delete. So polling `worker.isRunning()` in a qWait loop
    races the worker's own destruction, and when it lost it raised

        RuntimeError: libshiboken: Internal C++ object
        (TimelineBuildWorker) already deleted.

    from inside the wait helper, failing whichever timeline test happened to
    be running. Three of four full-suite runs hit it, on four different
    tests. The production side already knows about this -- see
    TimelineBuilder.cancel's "Already gone -- self-deleted via finished ->
    deleteLater" -- so this brings the helper up to the same awareness
    rather than changing any behaviour.
    """
    try:
        return worker.isRunning()
    except RuntimeError:
        return False


def _wait_for_timeline(win, since=None, timeout_ms=10_000):
    """Pump the REAL Qt event loop until the background Timeline build has
    finished AND its result has been handled on this thread.

    The build stopped being synchronous when it moved off the GUI thread,
    so a test that reads the view straight after triggering one reads
    whatever was there before. Waiting for `worker.isRunning()` to go
    False is necessary and NOT sufficient: the `built` signal is queued
    across threads, so the worker can be finished while the handler has
    not run.

    This waited for the worker and then pumped a FIXED QTest.qWait(10)
    for that gap, which is an arbitrary timeout standing in for a
    condition -- it held on an idle machine and failed under a loaded
    full-suite run, where the test passed in isolation and failed in the
    suite. `since` is the _timeline_token captured BEFORE the build was
    triggered; waiting until the token changes waits for the thing that
    actually has to have happened.

    Callers that pass no token still get the worker wait, which is what
    every pre-existing caller relied on.
    """
    builder = win._timeline_builder
    if builder is None or builder._worker is None:
        return
    worker = builder._worker
    elapsed = 0
    step = 10
    while _still_running(worker) and elapsed < timeout_ms:
        QTest.qWait(step)
        elapsed += step
    assert not _still_running(worker), "timed out waiting for the timeline build"
    if since is None:
        QTest.qWait(10)
        return
    while _timeline_token(win) == since and elapsed < timeout_ms:
        QTest.qWait(step)
        elapsed += step
    assert _timeline_token(win) != since, (
        "the timeline worker finished but its queued `built` signal was "
        "never handled on the GUI thread within %d ms" % timeout_ms)


def _open(win, entries):
    since = _timeline_token(win)
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser(entries)},
                            _fake_evidence_set())
    _wait_for_timeline(win, since)


def _recover(win, engine):
    since = _timeline_token(win)
    win._on_recovery_loaded(engine)
    _wait_for_timeline(win, since)


def _open_through_the_dialog(win, monkeypatch, path, entries):
    from webcache.shell import main_window as mw

    class _SyncLoader(QObject):
        progress = Signal(str)
        loaded = Signal(object)
        failed = Signal(str)

        def load(self, db_path, known_hashes=None):
            self.loaded.emit({"rows": [], "parser": _FakeParser(entries)})

        def cancel(self):
            pass

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr(mw, "OpenEvidenceDialog", _FakeConsentDialog)
    monkeypatch.setattr(mw, "EvidenceLoader", _SyncLoader)
    monkeypatch.setattr(mw, "ExportRunner", _SyncExportRunner)
    since = _timeline_token(win)
    win.open_evidence_action.trigger()
    _wait_for_timeline(win, since)


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


# --- a real view with a real count ----------------------------------------

def test_timeline_is_a_real_view_not_a_placeholder(win):
    assert isinstance(_view(win), TimelineView)


def test_timeline_no_longer_claims_it_has_no_number_to_show(win):
    assert "timeline" not in _NO_COUNT_KEYS


def test_the_view_is_reachable(win):
    win.go_to("timeline")
    assert win.current_key == "timeline"


# --- opening evidence -----------------------------------------------------

def test_opening_evidence_starts_a_background_build_not_a_synchronous_one(
        win):
    """The four grains used to be built synchronously, on the
    GUI thread, inside _on_evidence_loaded -- measured at up to 100 s of
    fully blocked GUI for a large exhibit. _on_evidence_loaded must now
    return having only STARTED a TimelineBuilder; the real rows land once
    its `built` signal is processed by the event loop, not before."""
    win._on_evidence_loaded(
        {"rows": [], "parser": _FakeParser([_entry(1), _entry(2, day=1)])},
        _fake_evidence_set())
    assert win._timeline_builder is not None
    view = _view(win)
    assert view._segment_rows["day"] == [], (
        "the grid must not be filled synchronously any more")
    _wait_for_timeline(win, _SINCE_NEW)
    assert len(view._segment_rows["day"]) == 2


def test_the_view_says_it_is_building_until_the_worker_lands(win):
    """A blank grid with no explanation reads as a failed load. Since the
    build is no longer instantaneous, an examiner who looks at the
    screen before it finishes must see an honest "in progress" message,
    not the ordinary "nothing in this exhibit can be placed in time"
    wording -- which would be false the moment the exhibit has data
    that will populate the timeline the instant the build finishes."""
    win._on_evidence_loaded(
        {"rows": [], "parser": _FakeParser([_entry(1)])},
        _fake_evidence_set())
    view = _view(win)
    assert view.table.showing_genuine_empty_state() is True
    assert "build" in view.table.empty_state_text().lower()
    _wait_for_timeline(win, _SINCE_NEW)


def test_opening_evidence_fills_every_grain(win):
    _open(win, [_entry(1, day=0), _entry(2, day=0), _entry(3, day=40)])
    view = _view(win)
    counts = {}
    for grain, _label, _plural in timeline_loader.GRAINS:
        counts[grain] = len(view._segment_rows[grain])
    assert counts["day"] == 2
    assert counts["month"] == 2
    assert counts["minute"] == 2
    assert all(v > 0 for v in counts.values()), counts


def test_the_badge_counts_dated_records_not_table_rows(win):
    """Three records fall into two day buckets and one month bucket. The
    badge must read three at every grain, because it counts records."""
    _open(win, [_entry(1, day=0), _entry(2, day=0), _entry(3, day=40)])
    view = _view(win)
    assert _nav_count(win) == 3
    view._switch_segment("month")
    assert _nav_count(win) == 3


def test_a_creation_time_only_record_reaches_the_badge_and_the_buckets(win):
    """THE BADGE BUG. A badge reading `AccessedTime or ModifiedTime` that
    omits CreationTime under-counts against its own view."""
    entry = _entry(1)
    entry["ModifiedTime_raw"] = 0
    entry["CreationTime_raw"] = _FT_BASE
    _open(win, [entry])
    assert _nav_count(win) == 1
    assert len(_view(win)._segment_rows["day"]) == 1


def test_a_record_with_no_time_is_excluded_and_the_count_line_says_so(win):
    dated = _entry(1)
    undated = _entry(2)
    undated["ModifiedTime_raw"] = 0
    _open(win, [dated, undated])
    assert _nav_count(win) == 1
    text = _view(win).line_text()
    assert "1 of 2 records" in text
    assert "not on this timeline" in text


def test_before_a_scan_the_count_line_says_nobody_has_looked(win):
    _open(win, [_entry(1)])
    text = _view(win).line_text()
    assert "no recovery scan has run" in text


def test_the_view_is_given_the_inputs_its_pane_builds_records_from(win):
    """Without them the pane cannot say which of a period's members were
    recovered, and every carved record would read as live."""
    _open(win, [_entry(1)])
    view = _view(win)
    assert view._inputs is not None
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    assert len(view.pane.visible_rows()) == 1


# --- after a recovery scan ------------------------------------------------

def test_a_recovery_scan_folds_carved_records_into_every_grain(win):
    _open(win, [_entry(1)])
    carved = _entry(2, day=1)
    _recover(win, _StubEngine([carved]))
    view = _view(win)
    assert _nav_count(win) == 2
    assert len(view._segment_rows["day"]) == 2
    assert sum(r["Carved"] for r in view._segment_rows["month"]) == 1


def test_after_a_scan_the_count_line_states_the_recovered_number(win):
    _open(win, [_entry(1)])
    _recover(win, _StubEngine([_entry(2, day=1)]))
    text = _view(win).line_text()
    assert "1 recovered" in text
    assert "no recovery scan has run" not in text


def test_a_carved_record_reaches_the_pane_labelled_as_recovered(win):
    from webcache.provenance import CARVED_ORIGIN

    _open(win, [_entry(1)])
    _recover(win, _StubEngine([_entry(2)]))
    view = _view(win)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    origins = {r["Origin"] for r in view.pane.visible_rows()}
    assert origins == {"Live record", CARVED_ORIGIN}


# --- the two exports ------------------------------------------------------

def test_the_view_export_writes_the_period_rows(win, monkeypatch, exhibit,
                                                outbox):
    _open_through_the_dialog(win, monkeypatch, str(exhibit / "e.dat"),
                             [_entry(1), _entry(2, day=3)])
    out = str(outbox / "timeline.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view = _view(win)
    promised = int(view.export_button.text().split("(")[1].rstrip(")"))
    view.export_button.click()
    header, *body = _read(out)
    assert len(body) == promised == 2
    for label in ("Period", "Relative volume", "Empty days before"):
        assert label in header, header


def test_the_pane_export_writes_the_records_in_one_period(win, monkeypatch,
                                                          exhibit, outbox):
    _open_through_the_dialog(win, monkeypatch, str(exhibit / "e.dat"),
                             [_entry(1), _entry(2)])
    view = _view(win)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    out = str(outbox / "period_records.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    promised = int(view.pane.export_button.text().split("(")[1].rstrip(")"))
    view.pane.export_button.click()
    header, *body = _read(out)
    assert len(body) == promised == 2
    assert "Address" in header


def test_the_record_export_carries_the_live_carved_distinction(win, monkeypatch,
                                                               exhibit, outbox):
    """The earlier version's every-event CSV omitted Origin, so the one distinction that
    is never hideable on screen was absent from the file that left the
    building."""
    _open_through_the_dialog(win, monkeypatch, str(exhibit / "e.dat"),
                             [_entry(1)])
    view = _view(win)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    out = str(outbox / "origin.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view.pane.export_button.click()
    header, *body = _read(out)
    assert "Source record" in header
    assert body[0][header.index("Source record")] == "Live record"


def test_the_record_export_sidecar_names_the_unit_and_the_period(
        win, monkeypatch, exhibit, outbox):
    """Two things on this screen are called a timeline. The file that
    leaves the building has to say which one it is."""
    _open_through_the_dialog(win, monkeypatch, str(exhibit / "e.dat"),
                             [_entry(1)])
    view = _view(win)
    model = view.table.model()
    period = model.row_at(0)["Period"]
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    out = str(outbox / "sidecar.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view.pane.export_button.click()
    job = _SyncExportRunner.jobs[-1]
    assert job.scope["unit"] == "records in one period"
    assert period in str(job.scope.get("period"))


def test_a_stale_pane_button_label_refuses_the_export(win, monkeypatch,
                                                      exhibit, outbox):
    """The button's number is a promise; writing a file with a different
    count than the examiner was shown is worse than writing nothing."""
    _open_through_the_dialog(win, monkeypatch, str(exhibit / "e.dat"),
                             [_entry(1), _entry(2)])
    view = _view(win)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    view.pane.export_button.setText("Export these records (99)")
    out = str(outbox / "never.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view.pane.export_button.click()
    assert _SyncExportRunner.jobs == []
    assert "export not started" in win.status_message().lower()


def test_the_pane_export_tells_a_filtered_pane_from_no_selection(
        win, monkeypatch, exhibit, outbox):
    """pane.visible_rows() is empty both when no period is
    selected AND when a period IS selected but the pane's own filter
    removed every one of its rows. Those are two different states and
    must not share one message."""
    _open_through_the_dialog(win, monkeypatch, str(exhibit / "e.dat"),
                             [_entry(1), _entry(2)])
    view = _view(win)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    assert view.pane.visible_rows()

    view.pane.table.model().set_values("ContainerType", {"NoSuchType"})
    assert view.pane.visible_rows() == []

    out = str(outbox / "never.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view.pane.export_button.click()

    assert _SyncExportRunner.jobs == []
    msg = win.status_message().lower()
    assert "select a period" not in msg, msg
    assert "filter" in msg, msg


def test_the_record_export_goes_through_the_one_chokepoint(win, monkeypatch,
                                                           exhibit, outbox):
    _open_through_the_dialog(win, monkeypatch, str(exhibit / "e.dat"),
                             [_entry(1)])
    view = _view(win)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    out = str(outbox / "chokepoint.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view.pane.export_button.click()
    assert [j.key for j in _SyncExportRunner.jobs] == ["view_csv"]


# --- the pane's records are as openable as any other ----------------------

def test_a_record_reached_through_a_period_opens_in_the_detail_dialog(win):
    _open(win, [_entry(1)])
    view = _view(win)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    view.pane.table.open_record(0)
    assert win._detail_dialogs
    for dialog in list(win._detail_dialogs):
        dialog.close()


def test_the_container_cell_in_the_pane_lands_on_that_container(win):
    _open(win, [_entry(1)])
    view = _view(win)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    by_key = {c.key: c for c in view.PERIOD_RECORD_COLUMNS}
    by_key["ContainerName"].on_click(view.pane.visible_rows()[0])
    assert win.current_key == "browser"


def test_the_status_line_counts_periods_as_periods(win, monkeypatch, exhibit,
                                                  outbox):
    """Seen on a real exhibit: "Exported 26 records in one period from 26
    of 112 records" -- 112 was the number of PERIODS listed, and "26 of"
    repeated the file's own count. The sentence was written for header
    pairs (pairs from records) and reused for a unit it does not fit."""
    _open_through_the_dialog(win, monkeypatch, str(exhibit / "e.dat"),
                             [_entry(1), _entry(2)])
    view = _view(win)
    model = view.table.model()
    period = model.row_at(0)["Period"]
    periods = model.rowCount()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    out = str(outbox / "status.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view.pane.export_button.click()
    said = win.status_message()
    assert str(period) in said
    assert "1 of %d period" % periods in said
    assert " of %d records" % periods not in said
