"""Every "Export view (N)" button, end to end.

This is the defect the whole unit exists to close: seven views carried a
prominent Export button whose entire behaviour was `lambda:
self.go_to("export")` -- it navigated to a placeholder. A control that
looks alive and is not.

So the assertions here are deliberately end-to-end rather than about
connections: click the real button, let the real writer run, then OPEN THE
FILE and count its rows. The number on the button is a promise, and the
only way to prove a promise is to check what was delivered.
"""
import csv
import os

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog

from webcache.provenance import CARVED_ORIGIN, EvidenceSet
from webcache.shell import export_formats as F
from webcache.shell.export_runner import ExportWorker
from webcache.shell.main_window import MainWindow
from webcache.views.export import ExportView

from tests.fixtures import make_rows


#: Every view that carries an "Export view (N)" button today. RecoveryView
#: is in the list because the carved records are
#: the rows RECOVERED_FIELDS was written for, and they were the one record
#: set in the application with no export affordance at all.
EXPORTING_VIEWS = ("history", "downloads", "cookies", "containers",
                   "domains", "indicators", "recovery")


@pytest.fixture
def exhibit(tmp_path):
    """The evidence directory, kept SEPARATE from where exports go.

    The first draft of this file put both under one tmp_path and every
    export was refused -- correctly. Nothing an export writes may land in
    the evidence folder, and a test that writes beside the exhibit is
    testing the wrong thing even when the assertion it makes is right.
    """
    d = tmp_path / "exhibit"
    d.mkdir()
    return d


@pytest.fixture
def outbox(tmp_path):
    """Where every export in this file is written. Never the exhibit's
    own directory."""
    d = tmp_path / "exports"
    d.mkdir()
    return d


@pytest.fixture
def win(qtbot, monkeypatch, tmp_path):
    # Case files are app-local and keyed by evidence SHA-256; a test must
    # never write one into the real cases/ directory beside the source.
    from webcache import paths
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    monkeypatch.setattr(paths, "cases_dir", lambda: case_dir)
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    return w


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


class _FakeParser:
    db_path = "C:/case/exhibit.dat"
    source_hashes = {"WebCacheV01.dat": "0" * 64}

    def __init__(self, entries=()):
        self.all_entries = list(entries)
        self.db = None
        self.containers_meta = []
        self.container_type_map = {}


class _SyncExportRunner(QObject):
    """Runs the REAL ExportWorker synchronously, so these tests exercise
    the real writer without depending on the scheduler."""
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


def _open_exhibit(win, monkeypatch, path, rows=None, parser=None):
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
    monkeypatch.setattr(mw, "ExportRunner", _SyncExportRunner)
    win.open_evidence_action.trigger()


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


# --- the page itself is real now -----------------------------------------

def test_the_export_destination_is_a_real_view_not_a_placeholder(win):
    assert isinstance(win._ensure_view_built("export"), ExportView)


def test_the_export_menu_is_no_longer_empty(win):
    labels = [a.text() for a in win.menu_for_export().actions() if a.text()]
    assert any("Export & Report" in t for t in labels)
    assert any("Export this view" in t for t in labels)
    assert any("bundle" in t.lower() for t in labels)


def test_export_this_view_is_disabled_on_a_view_with_no_table(win):
    win.go_to("export")
    assert not win.export_this_view_action.isEnabled()


def test_export_this_view_is_enabled_on_a_record_view(win, monkeypatch,
                                                      exhibit):
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(4), parser=_FakeParser())
    win.go_to("history")
    assert win.export_this_view_action.isEnabled()


# --- no view still navigates instead of exporting ------------------------

def test_no_view_still_answers_its_export_button_by_navigating(win):
    """The exact defect: `lambda: self.go_to("export")` on seven views."""
    import inspect
    from webcache.shell import main_window as mw
    src = inspect.getsource(mw.MainWindow.__init__)
    assert 'self.go_to("export")' not in src, (
        "an Export button that navigates to a page is not an export")


def test_every_record_view_carries_an_export_button(win):
    for key in EXPORTING_VIEWS:
        view = win._ensure_view_built(key)
        assert hasattr(view, "export_button"), key
        assert hasattr(view, "exportRequested"), key


def test_the_recovery_view_finally_has_one(win, monkeypatch, tmp_path):
    view = win._ensure_view_built("recovery")
    view.set_records([{"CleanUrl": "a", "Origin": CARVED_ORIGIN}])
    assert "Export view (1)" == view.export_button.text()


# --- the number on the button is the number in the file ------------------

def _export_the_view(win, monkeypatch, key, out_path):
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out_path, "")))
    view = win._ensure_view_built(key)
    view.export_button.click()
    return view


def test_the_integer_on_the_button_equals_the_rows_in_the_file(
        win, monkeypatch, exhibit, outbox):
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(37), parser=_FakeParser())
    out = str(outbox / "history.csv")
    view = win._ensure_view_built("history")
    promised = int(view.export_button.text().split("(")[1].rstrip(")").replace(",", ""))
    _export_the_view(win, monkeypatch, "history", out)
    body = _read(out)
    assert promised == 37
    assert len(body) - 1 == promised, (
        "the button said %s rows; the file holds %s" % (promised, len(body) - 1))


def test_a_filtered_export_writes_exactly_what_was_on_screen(
        win, monkeypatch, exhibit, outbox):
    rows = make_rows(50)
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"), rows=rows,
                  parser=_FakeParser())
    view = win._ensure_view_built("history")
    view.filter_box.setText(rows[0]["Domain"])
    view._apply_text()
    shown = view.table.model().rowCount()
    assert 0 < shown < 50, "the fixture must actually narrow for this to mean anything"
    promised = int(view.export_button.text().split("(")[1].rstrip(")").replace(",", ""))
    assert promised == shown
    out = str(outbox / "history.csv")
    _export_the_view(win, monkeypatch, "history", out)
    assert len(_read(out)) - 1 == shown


def test_a_sidecar_sits_beside_every_per_view_csv(win, monkeypatch, exhibit,
                                                  outbox):
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(6), parser=_FakeParser())
    out = str(outbox / "history.csv")
    _export_the_view(win, monkeypatch, "history", out)
    assert os.path.exists(out + ".provenance.txt")


def test_the_sidecar_states_the_filter_that_produced_the_file(
        win, monkeypatch, exhibit, outbox):
    rows = make_rows(50)
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"), rows=rows,
                  parser=_FakeParser())
    view = win._ensure_view_built("history")
    view.filter_box.setText(rows[0]["Domain"])
    view._apply_text()
    out = str(outbox / "history.csv")
    _export_the_view(win, monkeypatch, "history", out)
    text = open(out + ".provenance.txt", encoding="utf-8").read()
    assert "THIS IS A FILTERED SUBSET, NOT THE WHOLE VIEW" in text
    assert rows[0]["Domain"] in text
    assert "Re-run with filters cleared" in text


def test_the_suggested_filename_marks_a_filtered_export(
        win, monkeypatch, exhibit):
    rows = make_rows(50)
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"), rows=rows,
                  parser=_FakeParser())
    view = win._ensure_view_built("history")
    view.filter_box.setText(rows[0]["Domain"])
    view._apply_text()
    seen = {}

    def _capture(parent, title, start, *a, **k):
        seen["start"] = start
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_capture))
    view.export_button.click()
    # The marker sits before the export's UTC time (export_target.
    # suggest_name): <case>_<view>_FILTERED_<YYYYmmdd-HHMMSSZ>.csv.
    import re
    assert re.search(r"_FILTERED_\d{8}-\d{6}Z\.csv$", seen["start"])


def test_a_carved_row_stays_distinguishable_in_a_view_csv(
        win, monkeypatch, outbox):
    view = win._ensure_view_built("recovery")
    view.set_records([{"CleanUrl": "a", "Origin": CARVED_ORIGIN,
                       "Source": "V01.log"}])
    from webcache.shell import main_window as mw
    monkeypatch.setattr(mw, "ExportRunner", _SyncExportRunner)
    out = str(outbox / "recovery.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view.export_button.click()
    header, row = _read(out)
    # Recovery already declares its own Origin column, and
    # its own Source column too (label "File"), so
    # neither "Origin" nor "RecordSource" is appended after them -- each
    # would hold the same cell a second time. The carved row is still
    # distinguishable, in the view's own columns.
    assert "Origin" not in header and "RecordSource" not in header
    assert row[header.index("Origin detail")] == CARVED_ORIGIN
    assert row[header.index("File")] == "V01.log"


# --- a column the view already declares is not appended a second time --

def test_a_view_with_its_own_origin_column_is_not_given_a_second_one(
        win, monkeypatch, exhibit, outbox):
    """APPENDED_COLUMNS ("Origin",
    "RecordSource") was appended unconditionally, including to views that
    already declare their own "Origin" column -- History, Recovery,
    Headers. Verified on the real exhibit: the History CSV header
    contained "Origin" twice. Every record-set row is already stamped
    Origin="Live record"/CARVED_ORIGIN by evidence_loader.py /
    recovery_loader.py -- exactly what the appended column would also
    say -- so the view's own column already carries it; a second one is
    pure duplication, not new information.
    """
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(20), parser=_FakeParser())
    out = str(outbox / "history.csv")
    _export_the_view(win, monkeypatch, "history", out)
    header = _read(out)[0]
    # History declares Origin under the label
    # "Origin detail" and Source as "Carved from": decided by KEY, neither
    # an "Origin" nor a "RecordSource" is appended after them.
    assert header.count("Origin detail") == 1, header
    assert "Origin" not in header and "RecordSource" not in header, header


def test_the_sidecars_column_list_names_every_column_the_file_has(
        win, monkeypatch, exhibit, outbox):
    """scope_from_view set scope["columns"]
    to the view's OWN declared labels only, never the appended ones --
    so the sidecar's "Columns in file" line named 12 columns for a file
    that actually had 14. The two must always agree; a provenance
    document that undercounts its own file's columns is not
    trustworthy about anything else it states either."""
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(20), parser=_FakeParser())
    out = str(outbox / "history.csv")
    _export_the_view(win, monkeypatch, "history", out)
    header = _read(out)[0]
    text = open(out + ".provenance.txt", encoding="utf-8").read()
    line = next(l for l in text.splitlines() if "Columns in file" in l)
    named = [c.strip() for c in line.split(":", 1)[1].split(",")]
    assert named == header, (
        "sidecar names %r, file header is %r" % (named, header))


# --- the self-consistency guard must be able to fire -------------

def test_a_stale_button_label_refuses_the_export(win, monkeypatch, exhibit,
                                                 outbox):
    """The guard compared
    `len(model.filter.visible())` against `model.rowCount()` --
    RecordModel.rowCount() is DEFINED as len(that same list) (see
    record_model.py), so the two could never disagree; the branch was
    dead. The real promise is the button's own text, set by
    RecordsView._update_count() the last time the row set changed -- if
    the model's rows change after that (a recovery merge landing between
    the label update and the click) the button's number and the model's
    CURRENT number can genuinely disagree. Forcing the label stale
    reproduces exactly that, independent of the model itself.
    """
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(20), parser=_FakeParser())
    view = win._ensure_view_built("history")
    view.export_button.setText("Export view (999)")
    out = str(outbox / "history.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view.export_button.click()
    assert not os.path.exists(out), (
        "a stale button label must refuse the write, not silently export "
        "a different count than the one promised")
    message = win.status_message()
    assert "999" in message and "20" in message


# --- the evidence folder is refused, in a dialog, not a status line ------

def test_choosing_the_evidence_folder_refuses_and_writes_nothing(
        win, monkeypatch, exhibit):
    exhibit_dir = exhibit
    dat = exhibit_dir / "WebCacheV01.dat"
    dat.write_bytes(b"x")
    parser = _FakeParser()
    parser.db_path = str(dat)
    _open_exhibit(win, monkeypatch, str(dat), rows=make_rows(3), parser=parser)
    target = str(exhibit_dir / "history.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (target, "")))
    outcomes = []
    from webcache.shell import main_window as mw

    class _FakeSafeFolderDialog:
        CHOSE_SAFE, CHOSE_ELSEWHERE, CANCELLED = 1, 2, 3

        def __init__(self, parent, reason, safe_path):
            outcomes.append((reason, safe_path))

        def exec(self):
            return 0

        def outcome(self):
            return self.CANCELLED

        def path(self):
            return ""

        def deleteLater(self):
            pass

    monkeypatch.setattr(mw, "SafeFolderDialog", _FakeSafeFolderDialog)
    win._ensure_view_built("history").export_button.click()
    assert outcomes, "a refusal must be a dialog, not a status line"
    assert "evidence" in outcomes[0][0].lower()
    assert not os.path.exists(target)
    assert "cancelled" in win.status_message().lower()


# --- the case file --------------------------------------------------------

def test_a_case_file_is_opened_app_local_and_keyed_by_the_evidence_hash(
        win, monkeypatch, exhibit):
    from webcache import paths
    path = str(exhibit / "e.dat")
    _open_exhibit(win, monkeypatch, path, rows=make_rows(3),
                  parser=_FakeParser())
    assert win._case is not None
    stored = os.path.dirname(win._case.path)
    assert os.path.normcase(stored) == os.path.normcase(str(paths.cases_dir()))
    assert os.path.dirname(path) not in stored, (
        "a case file never lands beside the exhibit")


def test_case_metadata_typed_on_the_page_reaches_the_case_file(
        win, monkeypatch, exhibit):
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(3), parser=_FakeParser())
    view = win._ensure_view_built("export")
    assert view.examiner_field.isEnabled()
    view.examiner_field.setText("A. Examiner")
    view.flush_case_meta()
    assert win._case.get_meta("examiner") == "A. Examiner"


def test_the_case_fields_are_disabled_with_no_evidence_open(win):
    view = win._ensure_view_built("export")
    assert not view.examiner_field.isEnabled()
    assert "SHA-256" in view.case_note_label.text()


# --- the page reflects the loaded exhibit --------------------------------

def test_loading_an_exhibit_makes_the_formats_available(
        win, monkeypatch, exhibit):
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(3), parser=_FakeParser(make_rows(3)))
    view = win._ensure_view_built("export")
    assert view.cards["csv"].available is True
    assert view.cards["loc_csv"].available is False


def test_the_coverage_line_says_not_yet_recovered_before_a_scan(
        win, monkeypatch, exhibit):
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(3), parser=_FakeParser(make_rows(3)))
    view = win._ensure_view_built("export")
    assert "deleted records not yet recovered" in view.coverage_text


def test_a_format_card_click_writes_a_real_file(win, monkeypatch, exhibit,
                                                outbox):
    entries = [{"Url": "http://example.test/a", "ContainerType": "History",
                "EntryId": 1, "ContainerId": 3}]
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(1), parser=_FakeParser(entries))
    out = str(outbox / "all.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view = win._ensure_view_built("export")
    view.cards["csv"].button.click()
    assert os.path.exists(out)
    assert os.path.exists(out + ".metadata.json")


def test_only_one_export_can_be_in_flight(win, monkeypatch, exhibit, outbox):
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(3), parser=_FakeParser())
    win._busy_for = "load"
    out = str(outbox / "history.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._ensure_view_built("history").export_button.click()
    assert not os.path.exists(out)


# --- [5] the concurrent-export guard must run BEFORE the chooser, and ----
# cover every entry point, not just the one card that is actually
# writing. Verified against a real MainWindow: with an xlsx export
# running, the CSV card's own button, the bundle button and HistoryView's
# own "Export view" button all stayed clickable.

def test_a_card_click_refuses_before_the_chooser_opens_when_busy(
        win, monkeypatch, exhibit, outbox):
    """The old guard lived only inside _start_export -- AFTER
    _choose_export_path had already driven the chooser, so an examiner
    picked a destination and only THEN got told no. Proven by call
    count: the chooser must never open at all.
    """
    entries = [{"Url": "http://example.test/a", "ContainerType": "History",
                "EntryId": 1, "ContainerId": 3}]
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(1), parser=_FakeParser(entries))
    win._busy_for = "load"
    calls = []

    def _fake_chooser(*_a, **_k):
        calls.append(1)
        return (str(outbox / "x.csv"), "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(_fake_chooser))
    win._ensure_view_built("export").cards["csv"].button.click()
    assert calls == [], (
        "the destination chooser must never open while another "
        "operation is already busy")


def test_every_export_entry_point_goes_unavailable_while_one_runs(
        win, monkeypatch, exhibit, outbox):
    from webcache.shell import main_window as mw
    entries = [{"Url": "http://example.test/a", "ContainerType": "History",
                "EntryId": 1, "ContainerId": 3}]
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(1), parser=_FakeParser(entries))
    monkeypatch.setattr(mw, "ExportRunner", _ControllableExportRunner)
    out = str(outbox / "all.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    export_view = win._ensure_view_built("export")
    export_view.cards["csv"].button.click()
    assert win._busy_for == "export"

    assert not export_view.cards["json"].button.isEnabled(), (
        "a sibling format card must go unavailable too, not just the "
        "one that is actually writing")
    assert not export_view.bundle_button.isEnabled()
    history_view = win._ensure_view_built("history")
    assert not history_view.export_button.isEnabled(), (
        "HistoryView's own Export view button must reflect that an "
        "export is already running")

    # And restored the moment the export ends.
    _ControllableExportRunner.instances[-1].written.emit([out])
    assert export_view.cards["json"].button.isEnabled()
    assert export_view.bundle_button.isEnabled()
    assert history_view.export_button.isEnabled()


def test_cancel_routes_to_the_export_when_that_is_what_is_busy(
        win, monkeypatch, exhibit):
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(3), parser=_FakeParser())
    win._busy_for = "export"
    win._export_runner = _SyncExportRunner()
    win._cancel_current_busy_operation()
    assert "export" in win.status_message().lower()
    assert win._busy_for is None


# --- [1] cancel must disconnect and forget the runner, like every other --
# busy operation already does (_cancel_pending_load, _cancel_pending_
# recovery) -- see export_runner.py's own module docstring on why a
# single-format write has no interruption point: the worker thread keeps
# running and WILL eventually emit written/failed regardless of this
# click, so a still-connected, still-remembered runner is exactly what
# lets that late signal land on a screen that has already moved on.

class _ControllableExportRunner(QObject):
    """A fake ExportRunner whose completion fires ON COMMAND, not
    immediately -- unlike _SyncExportRunner above, which runs the real
    writer synchronously inside start() and so can never model "Cancel
    clicked while the write is still in flight" at all."""
    progress = Signal(str)
    written = Signal(list)
    failed = Signal(str)
    instances = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.job = None
        self.cancel_called = False
        _ControllableExportRunner.instances.append(self)

    def start(self, job):
        self.job = job

    def cancel(self):
        self.cancel_called = True


@pytest.fixture(autouse=True)
def _reset_controllable_runners():
    _ControllableExportRunner.instances = []
    yield


def test_cancelling_an_export_disconnects_and_forgets_the_runner(
        win, monkeypatch, exhibit, outbox):
    """[1] _cancel_current_export tore down the busy UI but never
    disconnected the runner's signals and never forgot the runner --
    unlike _cancel_current_load (see _cancel_pending_load), which does
    both. Proven two ways: the runner reference itself is gone, and a
    completion arriving AFTER cancel (exactly what an uninterruptible
    single-format write will do) can no longer reach the status bar.
    """
    from webcache.shell import main_window as mw
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(3), parser=_FakeParser())
    monkeypatch.setattr(mw, "ExportRunner", _ControllableExportRunner)
    out = str(outbox / "history.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._ensure_view_built("history").export_button.click()
    assert win._busy_for == "export"
    runner = _ControllableExportRunner.instances[-1]

    win._load_cancel_button.click()

    assert win._export_runner is None, (
        "a cancelled runner must be forgotten, not left stale for a "
        "later click -- or a later export -- to find")
    assert runner.cancel_called is True
    message_at_cancel = win.status_message()
    # The write itself cannot actually be interrupted -- simulate it
    # finishing anyway, exactly as the real worker thread would, and
    # prove the now-disconnected runner can no longer reach the screen.
    runner.written.emit([out])
    assert win.status_message() == message_at_cancel, (
        "a completion from a runner Cancel already disconnected must not "
        "be able to change the status bar")


# --- [2] the cancel message must not misstate an uninterruptible --------
# write's actual outcome. Item 1 already stops a LATE completion from
# reaching the screen; this is the separate defect that the message
# itself was wrong from the instant Cancel was clicked -- a single-format
# write is never actually interrupted (export_runner.py's own module
# docstring), so the generic "bundle manifest records what was not
# written" sentence names a manifest that format does not even write.

def test_a_single_format_cancel_does_not_claim_a_bundle_manifest(
        win, monkeypatch, exhibit, outbox):
    from webcache.shell import main_window as mw
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(3), parser=_FakeParser())
    monkeypatch.setattr(mw, "ExportRunner", _ControllableExportRunner)
    out = str(outbox / "history.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._ensure_view_built("history").export_button.click()

    win._load_cancel_button.click()

    message = win.status_message().lower()
    assert "bundle manifest" not in message, (
        "a per-view CSV export writes no bundle manifest; the cancel "
        "message must not claim one exists")
    assert "kept" in message and "finish" in message, (
        "the write cannot actually be interrupted -- the message must "
        "say the file already in progress will still complete, not that "
        "the export was stopped")


def test_a_bundle_cancel_still_names_its_own_manifest(
        win, monkeypatch, exhibit, outbox):
    """The bundle IS interruptible between members (_run_bundle checks
    stopping() before every one), so its own cancel wording -- naming the
    manifest that genuinely does record what did not run -- must stay
    exactly as it was."""
    from webcache.shell import main_window as mw
    entries = [{"Url": "http://example.test/a", "ContainerType": "History",
                "EntryId": 1, "ContainerId": 3}]
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(1), parser=_FakeParser(entries))
    monkeypatch.setattr(mw, "ExportRunner", _ControllableExportRunner)
    target = str(outbox / "bundle")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: target))
    win._ensure_view_built("export").bundle_button.click()

    win._load_cancel_button.click()

    assert "bundle manifest" in win.status_message().lower()


# --- [3] ending an export must not clobber an in-flight LOAD's UI --------
# _end_export_busy_ui's three teardown calls (stop the timer, hide the
# progress bar, hide Cancel) ran unconditionally -- only the _busy_for
# assignment was guarded on self._busy_for == "export". Nothing stops an
# examiner from starting a second Open Evidence while an export is still
# writing (_open_evidence_at cancels a pending LOAD/recovery, never an
# in-flight export), so the shared progress/Cancel pair can belong to a
# LOAD by the time the export it replaced finally finishes.

class _ControllableLoader(QObject):
    """A fake EvidenceLoader that never completes on its own -- unlike
    _SyncLoader above (used to open the FIRST exhibit in the test below),
    which emits loaded() synchronously and so can never be caught
    mid-flight."""
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)
    instances = []

    def __init__(self, parent=None):
        super().__init__(parent)
        _ControllableLoader.instances.append(self)

    def load(self, db_path, known_hashes=None):
        pass

    def cancel(self):
        pass


@pytest.fixture(autouse=True)
def _reset_controllable_loaders():
    _ControllableLoader.instances = []
    yield


def test_ending_an_export_leaves_an_in_flight_loads_progress_bar_alone(
        win, monkeypatch, exhibit, outbox, qtbot):
    """isVisible() reflects the whole ancestor chain, not just this one
    setVisible() call -- win must actually be shown, exactly like
    test_recovery_wiring.py's own win fixture (this file's own win
    fixture never calls show(), since nothing else here reads
    isVisible())."""
    win.show()
    qtbot.waitExposed(win)
    from webcache.shell import main_window as mw
    entries = [{"Url": "http://example.test/a", "ContainerType": "History",
                "EntryId": 1, "ContainerId": 3}]
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(1), parser=_FakeParser(entries))

    # Start an export and leave it running (the fake runner never
    # completes on its own).
    monkeypatch.setattr(mw, "ExportRunner", _ControllableExportRunner)
    out = str(outbox / "all.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._ensure_view_built("export").cards["csv"].button.click()
    assert win._busy_for == "export"
    export_runner = _ControllableExportRunner.instances[-1]

    # Now begin a SECOND Open Evidence while that export is still
    # writing. Nothing in _open_evidence_at refuses this -- it only ever
    # cancels a pending LOAD or recovery scan, never an in-flight export.
    monkeypatch.setattr(mw, "EvidenceLoader", _ControllableLoader)
    win.open_evidence_action.setEnabled(True)
    win.open_evidence_action.trigger()
    assert win._busy_for == "load", (
        "the fixture must actually get a load in flight for this to "
        "mean anything")
    assert win._load_progress.isVisible()
    assert win._load_cancel_button.isVisible()

    # The export this load interrupted now finishes, off in the
    # background, exactly as export_runner.py's own module docstring
    # says an uninterruptible single-format write eventually will.
    export_runner.written.emit([out])

    assert win._busy_for == "load", (
        "the export ending must not steal the busy state back from the "
        "load that superseded it")
    assert win._load_progress.isVisible(), (
        "the export's own teardown hid the LOAD's progress bar")
    assert win._load_cancel_button.isVisible(), (
        "the export's own teardown hid the LOAD's Cancel button, leaving "
        "no way to cancel a load that is still running")
    assert win._load_status_timer.isActive(), (
        "the export's own teardown stopped the LOAD's elapsed-time timer")


def test_the_field_count_footnote_is_live_not_transcribed(win):
    view = win._ensure_view_built("export")
    assert str(F.CANONICAL_FIELD_COUNT) in view.footnote_label.text()


# --- what the verification run on a real exhibit caught -------------------

def test_the_job_never_carries_the_dashboards_stats_dict(
        win, monkeypatch, exhibit, outbox):
    """Found by exporting a real exhibit and reading the manifest:
    the old capped HTML report (06_report.html, since replaced by the
    offline package) failed with KeyError 'total_entries'.

    dashboard_data.compute_dashboard_stats() and
    ForensicEngine.get_statistics() are two different dicts answering two
    different questions -- the dashboard's says total_records, the
    engine's says total_entries/container_types/top_domains. Handing the
    first to a writer expecting the second does not fail loudly for every
    format: the HTML report raised, and the workbook's Summary sheet and
    the PDF's statistics section would simply have come out EMPTY, which
    is the worse outcome because it still produces a document.
    """
    entries = [{"Url": "http://example.test/a", "ContainerType": "History",
                "EntryId": 1, "ContainerId": 3}]
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(1), parser=_FakeParser(entries))
    # A stand-in parser cannot produce dashboard stats, so this stands in
    # for the real load that can -- the shape is what matters.
    win._dashboard_live_stats = {"total_records": 610, "history": 46,
                                 "top_domains": [], "date_range": None}
    out = str(outbox / "all.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._ensure_view_built("export").cards["csv"].button.click()
    job = _SyncExportRunner.jobs[-1]
    assert "total_records" not in (job.stats or {}), (
        "that is the dashboard's dict, not the engine's")
    assert job.stats is None or "container_types" in job.stats


def test_the_bundle_writes_the_html_report_like_every_other_member(
        win, monkeypatch, exhibit, outbox):
    import json
    entries = [{"Url": "http://example.test/a", "ContainerType": "History",
                "EntryId": 1, "ContainerId": 3}]
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(1), parser=_FakeParser(entries))
    target = str(outbox / "bundle")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: target))
    win._ensure_view_built("export").bundle_button.click()
    manifest = json.load(open(os.path.join(target, F.MANIFEST_NAME),
                              encoding="utf-8"))
    html = [i for i in manifest["formats"] if i["file"].endswith(".html")]
    assert html and html[0]["status"] == "written", html


def test_the_bundle_status_line_names_the_folder_not_the_manifest(
        win, monkeypatch, exhibit, outbox):
    """The first verification run reported "Exported to 00_MANIFEST.json -
    provenance sidecar beside it". A bundle is a folder of files and the
    line has to say so; the manifest is one member, not the deliverable."""
    entries = [{"Url": "http://example.test/a", "ContainerType": "History",
                "EntryId": 1, "ContainerId": 3}]
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(1), parser=_FakeParser(entries))
    target = str(outbox / "bundle2")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: target))
    win._ensure_view_built("export").bundle_button.click()
    status = win.status_message()
    assert status.startswith("Bundle written"), status
    assert "MANIFEST" not in status
    assert os.path.basename(target) in status


def test_no_case_file_is_written_into_the_source_tree(win, monkeypatch,
                                                      exhibit):
    """The hygiene rule, asserted where a case file is actually opened.

    It began life in test_paths.py, which is the wrong home for it: that
    module tests the REAL paths.cases_dir (that it exists and sits under
    app_dir) and is therefore the one module conftest's redirect
    deliberately excludes. This module is where a CaseDb is opened for a
    fake exhibit, so this is where "and it did not land in the checkout"
    is a statement about something that happened.
    """
    import pathlib

    from webcache import paths

    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(2), parser=_FakeParser())
    assert win._case is not None
    source_cases = (pathlib.Path(paths.__file__).resolve().parent.parent
                    / "cases")
    written = pathlib.Path(win._case.path).resolve().parent
    assert written != source_cases.resolve(), (
        "the suite is writing case files into the checkout")


def test_the_excel_filter_writes_a_workbook_even_under_the_suggested_csv_name(
        win, monkeypatch, outbox):
    """The chooser suggests "....csv". An examiner who
    picks the Excel filter and keeps the name got a CSV: the selected
    filter was discarded and the suffix alone decided the format."""
    csv_name = str(outbox / "history.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(
        lambda *a, **k: (csv_name, "Excel workbook (*.xlsx)")))
    jobs = []
    monkeypatch.setattr(win, "_start_export",
                        lambda job, card_key=None: jobs.append(job))
    view = win._ensure_view_built("history")
    view.set_records(make_rows(3))
    view.export_button.click()
    assert [j.key for j in jobs] == ["view_xlsx"]
    assert jobs[0].path == str(outbox / "history.xlsx")


def test_the_csv_filter_keeps_the_csv_name(win, monkeypatch, outbox):
    csv_name = str(outbox / "history.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(
        lambda *a, **k: (csv_name, "CSV (*.csv)")))
    jobs = []
    monkeypatch.setattr(win, "_start_export",
                        lambda job, card_key=None: jobs.append(job))
    view = win._ensure_view_built("history")
    view.set_records(make_rows(3))
    view.export_button.click()
    assert [(j.key, j.path) for j in jobs] == [("view_csv", csv_name)]


@pytest.mark.parametrize("segment, named", [("file_access", "_File-access_"),
                                            ("downloads", "_Downloads_")])
def test_the_suggested_filename_names_the_segment_it_holds(
        win, monkeypatch, exhibit, segment, named):
    """File Access holds two record sets; the file is named after the one
    on screen, never after the view's internal key."""
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(5), parser=_FakeParser())
    view = win._ensure_view_built("downloads")
    view._switch_segment(segment)
    view.set_records_for(segment, [{"CleanUrl": "file:///C:/a.txt"}])
    seen = {}

    def _capture(parent, title, start, *a, **k):
        seen["start"] = start
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_capture))
    view.export_button.click()
    name = os.path.basename(seen["start"])
    assert named in name, name
    assert "_downloads_" not in name, name
