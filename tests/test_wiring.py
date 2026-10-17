"""The wiring itself, not the components it connects.

Every piece already has its own suite -- OpenEvidenceDialog (test_consent.py),
the parser (test_engine_imports.py and friends), History
(test_history_view.py), RecordsTable (test_records_table.py), FilterPopup
(test_filter_popup.py). None of that proves any of them talk to each other.
Before this task, `OpenEvidenceDialog` was never instantiated by the shell,
`WebCacheParser` was never called, `set_records` was never invoked with
real data, the File menu had no Open Evidence action, and `FilterPopup` had
no trigger anywhere -- the application launched, showed sixteen titles, and
could not open a file.

These tests assert the CONNECTIONS, deliberately in a way that would fail
if any one of them were missing:

- File > Open Evidence... really reaches OpenEvidenceDialog (a monkeypatched
  file dialog and a spy OpenEvidenceDialog prove construction, not just that a
  method with the right name exists).
- Declining really leaves History untouched and never reaches the loader.
- Accepting really reaches EvidenceLoader and really lands rows in
  HistoryView.table.model() -- not a copy of them.
- The evidence set really reaches the status bar, named and hashed.
- The carved-records rule: since no carve runs at open time, the row count
  the examiner actually reads really says these are live records only.
- A parse failure really surfaces a message and really leaves the window
  usable, rather than wedging it.
- A right-click on a History column heading really opens FilterPopup for
  THAT column, on the SAME model the table is showing, and applying a
  condition through it really narrows that same table -- not a detached
  copy that happens to have the right shape.
"""
import hashlib
import os

import pytest
from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QFileDialog

from webcache.provenance import EvidenceSet
from webcache.shell import main_window as main_window_module
from webcache.shell import settings
from webcache.shell.main_window import ExplainDialog, MainWindow
from webcache.widgets.filter_popup import FilterPopup

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


class _FakeConsentDialog:
    recover_deleted = False
    """A stand-in for OpenEvidenceDialog that never shows a real modal window --
    a real QDialog.exec() blocks in a nested event loop until accept()/
    reject() is called by something, which nothing in an automated test
    does, so it would hang forever. Driven exactly the way main_window.py
    is expected to drive the real one: constructed with (path, parent),
    .exec() read for Accepted/Rejected, .evidence_set read only when
    accepted, .deleteLater() called unconditionally afterwards -- the
    cancel-safe idiom.
    """
    instances = []

    def __init__(self, path, parent=None):
        self.path = path
        self.parent = parent
        self.evidence_set = None
        _FakeConsentDialog.instances.append(self)

    def exec(self):
        raise NotImplementedError

    def deleteLater(self):
        pass


class _AcceptingConsentDialog(_FakeConsentDialog):
    """The hash is DERIVED from the path, deterministically, rather than a
    single fixed literal -- so a test that opens two different exhibits in
    the same session (the exhibit-swap tests below) can tell, by reading
    the status bar alone, which one's provenance is actually showing."""
    def __init__(self, path, parent=None):
        super().__init__(path, parent)
        fake_hash = hashlib.sha256(path.encode("utf-8")).hexdigest()
        self.evidence_set = EvidenceSet([path], {path: 12345}, {path: fake_hash})

    def exec(self):
        return QDialog.Accepted


class _DecliningConsentDialog(_FakeConsentDialog):
    def exec(self):
        return QDialog.Rejected


class _FakeLoader(QObject):
    """A stand-in for EvidenceLoader. The real one parses a real
    WebCacheV01.dat on a QThread -- there is no such file in the test
    suite -- so these tests drive the identical signal contract
    (progress/loaded/failed) synchronously instead of actually threading,
    which is enough to prove MainWindow is listening on the right wires
    without needing real evidence to do it."""
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    result = None       # what .load() emits via `loaded`, when not failing
    fail_message = None  # when set, .load() emits `failed` instead
    calls = []           # every db_path .load() was called with
    hash_calls = []       # every known_hashes .load() was called with

    def load(self, db_path, known_hashes=None):
        _FakeLoader.calls.append(db_path)
        _FakeLoader.hash_calls.append(known_hashes)
        if _FakeLoader.fail_message is not None:
            self.failed.emit(_FakeLoader.fail_message)
        else:
            self.loaded.emit(_FakeLoader.result)

    def cancel(self):
        pass


class _DeferredFakeLoader(QObject):
    """A stand-in for EvidenceLoader whose `.load()` does NOT emit
    synchronously -- unlike _FakeLoader above, which is enough for every
    single-open test but cannot represent two loads genuinely overlapping
    in time. finish_now()/fail_now() let a test control exactly when each
    one's result lands, so a test can start load A, start load B, and only
    THEN let A complete -- after B already has -- to prove a superseded
    load can never overwrite a newer one."""
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    instances = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.known_hashes = None
        self.cancelled = False
        _DeferredFakeLoader.instances.append(self)

    def load(self, db_path, known_hashes=None):
        self.db_path = db_path
        self.known_hashes = known_hashes

    def cancel(self):
        self.cancelled = True

    def finish_now(self, result):
        self.loaded.emit(result)

    def fail_now(self, message):
        self.failed.emit(message)


@pytest.fixture(autouse=True)
def _reset_fakes():
    _FakeConsentDialog.instances = []
    _FakeLoader.calls = []
    _FakeLoader.hash_calls = []
    _FakeLoader.result = None
    _FakeLoader.fail_message = None
    _DeferredFakeLoader.instances = []
    yield


def _accepting_dialog_for(path):
    """A OpenEvidenceDialog spy class scoped to ONE path -- used when a test
    opens more than one exhibit and each open must be accepted for its
    OWN path, not whichever path happened to be passed to the shared
    _AcceptingConsentDialog class most recently."""
    class _Scoped(_FakeConsentDialog):
        def __init__(self, p, parent=None):
            assert p == path, "opened the wrong exhibit: expected %r, got %r" % (path, p)
            super().__init__(p, parent)
            fake_hash = hashlib.sha256(p.encode("utf-8")).hexdigest()
            self.evidence_set = EvidenceSet([p], {p: 12345}, {p: fake_hash})

        def exec(self):
            return QDialog.Accepted
    return _Scoped


# --- File > Open Evidence... exists, is enabled, and Ctrl+O reaches it -----

def test_open_evidence_action_exists_is_enabled_and_is_on_the_file_menu(win):
    action = win.open_evidence_action
    assert action is not None
    assert action.isEnabled()
    assert action in win.menu_for_file().actions()


def test_ctrl_o_triggers_the_open_evidence_action(win, qtbot, monkeypatch):
    # The shortcut reaches the REAL open_evidence() -- unlike every other
    # test in this file, nothing here monkeypatches main_window's own
    # OpenEvidenceDialog reference, only the file dialog. A native
    # QFileDialog.getOpenFileName() blocks in its own modal event loop
    # waiting for a selection; left un-patched here it would hang the
    # keyClick itself before qtbot.waitSignal's timeout ever gets a chance
    # to run, since the whole call chain below is synchronous.
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    with qtbot.waitSignal(win.open_evidence_action.triggered, timeout=1000):
        QTest.keyClick(win, Qt.Key_O, Qt.ControlModifier)


# --- triggering it reaches a real file dialog, then OpenEvidenceDialog ----------

def test_triggering_open_evidence_opens_a_consent_dialog_for_the_chosen_path(
        win, monkeypatch, tmp_path):
    fixture_path = str(tmp_path / "WebCacheV01.dat")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (fixture_path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _DecliningConsentDialog)

    win.open_evidence_action.trigger()

    assert len(_FakeConsentDialog.instances) == 1
    assert _FakeConsentDialog.instances[0].path == fixture_path


def test_cancelling_the_file_dialog_never_opens_a_consent_dialog(win, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _DecliningConsentDialog)

    win.open_evidence_action.trigger()

    assert _FakeConsentDialog.instances == []


# --- last_evidence_dir: settings.py declares it, the dialog must use it ----
# Before this, settings.py's "last_evidence_dir" default was collected and
# saved (test_theme_settings.py already proves the plain round-trip) but
# never READ by open_evidence() -- the dialog's own start-directory
# argument was a hardcoded "" -- and never WRITTEN when an exhibit was
# actually chosen, so the setting existed only on paper.

def test_open_evidence_dialog_starts_in_the_last_evidence_directory(
        win, monkeypatch, tmp_path):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    settings.save(last_evidence_dir=r"D:\case\exhibit")
    calls = []
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: calls.append((a, k)) or ("", "")))

    win.open_evidence()

    assert calls, "getOpenFileName was never called"
    args, kwargs = calls[0]
    # QFileDialog.getOpenFileName(parent, caption, dir, filter, ...) --
    # "dir" is the third positional argument.
    start_dir = args[2] if len(args) > 2 else kwargs.get("dir")
    assert start_dir == r"D:\case\exhibit"


def test_a_freshly_installed_app_opens_the_dialog_with_no_starting_directory(
        win, monkeypatch, tmp_path):
    """The obvious first-launch case: nothing chosen yet, so there is
    nothing honest to seed the dialog with -- it must fall back to Qt's
    own default (an empty string), not raise or invent a path."""
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    calls = []
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: calls.append((a, k)) or ("", "")))

    win.open_evidence()

    args, kwargs = calls[0]
    start_dir = args[2] if len(args) > 2 else kwargs.get("dir")
    assert start_dir == ""


def test_choosing_a_file_remembers_its_directory_for_next_time(
        win, monkeypatch, tmp_path):
    fixture_dir = tmp_path / "case17"
    fixture_dir.mkdir()
    fixture_path = str(fixture_dir / "WebCacheV01.dat")
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (fixture_path, "")))
    # Declining consent on purpose: the directory is what the examiner
    # BROWSED to, independent of whether they went on to accept -- the
    # same thing every ordinary file dialog already remembers regardless
    # of what happens to the file afterward.
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _DecliningConsentDialog)

    win.open_evidence_action.trigger()

    assert settings.get("last_evidence_dir") == str(fixture_dir)


# --- declining: nothing hashed, nothing parsed, History stays empty --------

def test_declining_consent_never_reaches_the_loader_and_history_stays_empty(
        win, monkeypatch, tmp_path):
    fixture_path = str(tmp_path / "WebCacheV01.dat")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (fixture_path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _DecliningConsentDialog)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader", _FakeLoader)

    win.open_evidence_action.trigger()

    assert _FakeLoader.calls == [], (
        "declining consent must never construct or call the loader -- "
        "nothing is hashed or parsed without consent")
    history = _history_view(win)
    model = history.table.model()
    assert model is None or model.rowCount() == 0


def test_cancelling_the_dialog_is_announced_in_the_status_bar(win, monkeypatch, tmp_path):
    fixture_path = str(tmp_path / "WebCacheV01.dat")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (fixture_path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _DecliningConsentDialog)

    win.open_evidence_action.trigger()

    assert "cancelled" in win.status_message().lower()


# --- accepting: the loader runs and rows really land in the table ---------

def test_accepting_consent_runs_the_loader_with_the_chosen_path(win, monkeypatch, tmp_path):
    fixture_path = str(tmp_path / "WebCacheV01.dat")
    _FakeLoader.result = {"rows": make_rows(50), "parser": None}
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (fixture_path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _AcceptingConsentDialog)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader", _FakeLoader)

    win.open_evidence_action.trigger()

    assert _FakeLoader.calls == [fixture_path]
    # The consent gate has already hashed this exhibit by the time this
    # fires (_AcceptingConsentDialog's EvidenceSet, built exactly the way
    # the real OpenEvidenceDialog builds one); that hash must reach the loader
    # so WebCacheParser.open() is never asked to read a potentially
    # multi-gigabyte exhibit a second time just to hash it again.
    expected_hash = hashlib.sha256(fixture_path.encode("utf-8")).hexdigest()
    assert _FakeLoader.hash_calls == [{fixture_path: expected_hash}]


def test_accepting_consent_ends_with_the_history_table_holding_the_rows(
        win, monkeypatch, tmp_path):
    fixture_path = str(tmp_path / "WebCacheV01.dat")
    rows = make_rows(50)
    _FakeLoader.result = {"rows": rows, "parser": None}
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (fixture_path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _AcceptingConsentDialog)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader", _FakeLoader)

    win.open_evidence_action.trigger()

    history = _history_view(win)
    model = history.table.model()
    assert model is not None
    assert model.rowCount() == 50
    # Not just the right COUNT -- the actual rows the fake loader handed
    # back, landing on the SAME model the table is showing.
    # History opens newest-first: the rows arrive in exactly the
    # order "AccessedUtc, newest first, blank times last" gives them.
    dated = sorted((r for r in rows if r["AccessedUtc"] is not None),
                   key=lambda r: r["AccessedUtc"], reverse=True)
    blank = [r for r in rows if r["AccessedUtc"] is None]
    assert ([model.row_at(i)["CleanUrl"] for i in range(model.rowCount())]
            == [r["CleanUrl"] for r in dated + blank])


# --- the evidence set reaches provenance: named in the status bar ---------

def test_evidence_set_reaches_provenance_named_in_the_status_bar(win, monkeypatch, tmp_path):
    fixture_path = str(tmp_path / "WebCacheV01.dat")
    _FakeLoader.result = {"rows": make_rows(5), "parser": None}
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (fixture_path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _AcceptingConsentDialog)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader", _FakeLoader)

    win.open_evidence_action.trigger()

    dlg = _FakeConsentDialog.instances[0]
    sha_prefix = list(dlg.evidence_set.hashes.values())[0][:12]
    status = win.status_message()
    assert os.path.basename(fixture_path) in status
    assert sha_prefix in status


# --- the carved-records rule: the count line says these are live-only -----

def test_history_count_line_states_these_are_live_records_only(win, monkeypatch, tmp_path):
    """A carve is not run at open time, so the row
    count an examiner actually reads must say so rather than let a
    live-only set silently read as the complete picture."""
    fixture_path = str(tmp_path / "WebCacheV01.dat")
    _FakeLoader.result = {"rows": make_rows(5), "parser": None}
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (fixture_path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _AcceptingConsentDialog)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader", _FakeLoader)

    win.open_evidence_action.trigger()

    history = _history_view(win)
    assert "not yet recovered" in history.line_text().lower()


# --- a parse failure is actionable and leaves the app usable ---------------

def test_parse_failure_shows_an_actionable_message_and_leaves_the_app_usable(
        win, monkeypatch, tmp_path):
    fixture_path = str(tmp_path / "WebCacheV01.dat")
    _FakeLoader.fail_message = "the database header is corrupt"
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (fixture_path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _AcceptingConsentDialog)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader", _FakeLoader)

    win.open_evidence_action.trigger()

    assert "corrupt" in win.status_message().lower()
    # The window must still be usable: navigation still works, and the
    # window itself was never disabled while the failure was handled.
    assert win.isEnabled()
    win.go_to("downloads")
    assert win.current_key == "downloads"


# --- the filter popup: a header trigger on RecordsTable --------------------

def test_right_clicking_a_history_column_heading_opens_filter_popup_for_it(win, qtbot):
    history = _history_view(win)
    history.set_records(make_rows(200))
    table = history.table
    header = table.horizontalHeader()
    domain_section = next(i for i, c in enumerate(table.model().columns)
                          if c.key == "Domain")
    pos = QPoint(header.sectionPosition(domain_section) + 5, 5)

    # A real right-click cannot be relied on to synthesize a native
    # QContextMenuEvent under the offscreen platform this whole suite runs
    # on (see conftest.py) -- on Windows that event is normally generated
    # by WM_CONTEXTMENU at the OS window-procedure level, which the
    # offscreen QPA plugin never produces. Emitting the exact signal Qt
    # itself emits on a genuine right-click (when contextMenuPolicy is
    # CustomContextMenu) exercises the identical connected slot without
    # depending on that platform event -- RecordsTable's own
    # _build_context_menu tests already use the same technique for the
    # per-cell menu, for the same reason.
    header.customContextMenuRequested.emit(pos)

    assert table._filter_popup is not None
    assert isinstance(table._filter_popup, FilterPopup)
    assert table._filter_popup.column.key == "Domain"
    # The popup must be seeded from the SAME model the table is showing,
    # not a detached copy that happens to look right.
    assert table._filter_popup.model is table.model()


def test_right_clicking_a_different_heading_opens_the_popup_for_that_one(win, qtbot):
    """Pins the click-to-column mapping itself, not just that A popup opens
    at all: right-clicking VisitCount must never open Domain's popup."""
    history = _history_view(win)
    history.set_records(make_rows(200))
    table = history.table
    header = table.horizontalHeader()
    visits_section = next(i for i, c in enumerate(table.model().columns)
                          if c.key == "VisitCount")
    pos = QPoint(header.sectionPosition(visits_section) + 5, 5)

    header.customContextMenuRequested.emit(pos)

    assert table._filter_popup.column.key == "VisitCount"


def test_applying_a_condition_through_the_header_popup_narrows_the_same_table(win, qtbot):
    history = _history_view(win)
    history.set_records(make_rows(2_000))
    table = history.table
    before = table.model().rowCount()
    assert before == 2_000
    header = table.horizontalHeader()
    domain_section = next(i for i, c in enumerate(table.model().columns)
                          if c.key == "Domain")
    pos = QPoint(header.sectionPosition(domain_section) + 5, 5)

    header.customContextMenuRequested.emit(pos)
    popup = table._filter_popup
    popup.operator_box.setCurrentText("contains")
    popup.operand_a.setText("login")
    assert popup.apply() is True

    after = table.model().rowCount()
    assert 0 < after < before
    for i in range(after):
        assert "login" in str(table.model().row_at(i)["Domain"]).lower()


def test_the_filter_popup_offers_to_copy_the_column_name(win, qtbot):
    """The examiner chose "Copy inside the filter popup"
    over an intermediate header menu -- right-click still opens
    FilterPopup directly, in one click, and the popup itself gains the
    copy control (see FilterPopup.copy_name_button)."""
    history = _history_view(win)
    history.set_records(make_rows(5))
    table = history.table
    header = table.horizontalHeader()
    domain_section = next(i for i, c in enumerate(table.model().columns)
                          if c.key == "Domain")
    pos = QPoint(header.sectionPosition(domain_section) + 5, 5)

    header.customContextMenuRequested.emit(pos)
    popup = table._filter_popup
    qtbot.mouseClick(popup.copy_name_button, Qt.LeftButton)

    assert QGuiApplication.clipboard().text() == "Domain"


def test_f1_on_a_history_cell_reaches_a_real_explain_handler(win, qtbot, monkeypatch):
    """RecordsTable.explainRequested is emitted by F1 and by the context
    menu's "Explain this value" entry -- test_records_table.py already
    pins THAT emit, at the widget level, in isolation
    (test_f1_emits_explain_requested_for_the_current_cell), including the
    real F1 keypress mechanics. Neither that test nor a signal existing at
    all proves anything is actually LISTENING on the other end -- and
    until MainWindow wired this signal to _explain_value, nothing was: F1
    emitted a signal into the void.

    This test's job is narrower and complementary: prove the CONNECTION
    end to end, through the real MainWindow that owns HistoryView's
    table, by triggering the exact same production code path
    (RecordsTable._explain_current_cell, the F1 shortcut's slot) directly
    rather than re-proving F1-the-keypress reaches it -- a nested table's
    WindowShortcut context depends on real OS-level window activation,
    which the offscreen QPA platform this whole suite runs under does not
    reliably provide for a widget several layers deep in a QStackedWidget
    (see the "This plugin does not support raise()" warning Qt itself
    emits here). Calling the slot directly sidesteps that platform gap
    without weakening what this test actually needs to prove: that the
    signal reaches a real consumer, and that what it shows reflects the
    specific cell that was explained.

    ExplainDialog.exec() is a real modal QDialog.exec() -- it would block
    this test in a nested event loop forever, the same reason
    _FakeConsentDialog stands in for OpenEvidenceDialog above. A tiny
    ExplainDialog subclass that records the text it was built with and
    returns immediately from exec() (rather than mocking QMessageBox.
    information, which _explain_value no longer calls at all -- see
    main_window.ExplainDialog) proves the same thing: the handler is real,
    and what it constructs reflects the specific cell that was explained.
    """
    history = _history_view(win)
    history.set_records(make_rows(50))
    table = history.table
    win.go_to("history")

    shown = []

    class _NonModalExplainDialog(ExplainDialog):
        def exec(self):
            shown.append(self._text)
            return QDialog.Accepted

    monkeypatch.setattr(main_window_module, "ExplainDialog",
                         _NonModalExplainDialog)

    address = [c.key for c in table.model().columns].index("CleanUrl")
    ix = table.model().index(0, address)
    table.setCurrentIndex(ix)
    table._explain_current_cell()  # the F1 shortcut's own slot

    assert shown, (
        "explainRequested must reach a real handler end to end -- it was "
        "emitted into a void before this wiring existed")
    record = table.model().row_at(0)
    shown_text = shown[0]
    assert record["CleanUrl"] in shown_text, (
        "the explanation shown must be for the cell that was actually "
        "explained, not a generic message")
    assert record["Origin"] in shown_text, (
        "provenance.describe_origin() is the whole point of wiring this "
        "up now rather than waiting for the Phase-2 Explain panel")


def test_explain_on_an_aggregate_row_says_aggregate_not_live_record(win, monkeypatch):
    """provenance.describe_origin() reads `row.get("Origin") or
    "Live record"` -- an AGGREGATE row (a Timeline period, a Location
    place) carries no Origin at all (it is not a record), so Explain
    asserted "Live record" for a place built entirely from carved fixes.
    detail_fields.origin_line already draws this distinction correctly
    for the record detail dialog (see location_loader.places' own
    docstring on why K_PLACE fires _aggregate_statement there) -- Explain
    must use the same function rather than calling describe_origin
    directly."""
    from webcache.shell import record_kinds

    shown = []

    class _NonModalExplainDialog(ExplainDialog):
        def exec(self):
            shown.append(self._text)
            return QDialog.Accepted

    monkeypatch.setattr(main_window_module, "ExplainDialog",
                        _NonModalExplainDialog)

    place = {
        "_kind": record_kinds.K_PLACE,
        "_record": None,
        "_members": [{}, {}],
        "Records": 2,
        "Carved": 2,
        "Coords": "51.5074, -0.1278",
    }
    win._explain_value(place, "Coords")

    assert shown, "explain must reach the handler for an aggregate row too"
    text = shown[0]
    assert "Live record" not in text, (
        "an aggregate has no origin of its own -- asserting one for a row "
        "built entirely from carved data contradicts its own Carved count",
        text)
    assert "Summary of 2 records, not a single record" in text, text


# --- a load superseded by a newer one must never --
# --- win. Reviewer traced this: the loader is parented to the window, so --
# --- Qt keeps a superseded one alive; nothing disabled the action or -----
# --- disconnected the old loader, so a slow exhibit A finishing AFTER a --
# --- fast exhibit B could silently overwrite B's rows and B's hash with --
# --- A's. -------------------------------------------------------------

def test_open_evidence_action_is_disabled_while_a_load_is_in_flight(win, monkeypatch, tmp_path):
    path = str(tmp_path / "exhibit.dat")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _accepting_dialog_for(path))
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader",
                        _DeferredFakeLoader)

    assert win.open_evidence_action.isEnabled()
    win.open_evidence_action.trigger()
    assert not win.open_evidence_action.isEnabled(), (
        "the action must be disabled the moment a load starts, so the "
        "ordinary UI path (menu click or Ctrl+O) cannot start a second "
        "load while the first is still in flight")


def test_open_evidence_action_is_reenabled_after_a_successful_load(win, monkeypatch, tmp_path):
    path = str(tmp_path / "exhibit.dat")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _accepting_dialog_for(path))
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader",
                        _DeferredFakeLoader)

    win.open_evidence_action.trigger()
    loader = _DeferredFakeLoader.instances[-1]
    loader.finish_now({"rows": make_rows(3), "parser": None})

    assert win.open_evidence_action.isEnabled()


def test_open_evidence_action_is_reenabled_after_a_failed_load(win, monkeypatch, tmp_path):
    path = str(tmp_path / "exhibit.dat")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _accepting_dialog_for(path))
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader",
                        _DeferredFakeLoader)

    win.open_evidence_action.trigger()
    loader = _DeferredFakeLoader.instances[-1]
    loader.fail_now("boom")

    assert win.open_evidence_action.isEnabled()


def test_a_load_superseded_by_a_newer_one_never_overwrites_the_screen(win, monkeypatch, tmp_path):
    """THE test: exhibit A is opened first (imagine a large, slow parse),
    then exhibit B is opened before A has finished. Verified empirically
    that QAction.trigger() itself respects
    isEnabled() in this Qt version and is a no-op while disabled -- so B's
    open is driven through win.open_evidence() directly here, standing in
    for whatever future code path might call it without going through the
    action (a menu built differently, a test, a keyboard shortcut wired a
    second way) rather than a literal second .trigger(). B finishes first
    and is shown correctly. Only THEN does A's parse finish late. A's rows
    and A's hash must never reach the screen -- the table and the status
    bar must both still show B, and only B, all the way through.
    """
    path_a = str(tmp_path / "exhibit_a.dat")
    path_b = str(tmp_path / "exhibit_b.dat")
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader",
                        _DeferredFakeLoader)

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path_a, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _accepting_dialog_for(path_a))
    win.open_evidence_action.trigger()
    loader_a = _DeferredFakeLoader.instances[-1]

    # B is opened while A is still in flight, via the underlying method
    # directly -- see the docstring above for why not a second .trigger().
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path_b, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _accepting_dialog_for(path_b))
    win.open_evidence()
    loader_b = _DeferredFakeLoader.instances[-1]
    assert loader_a is not loader_b

    rows_a = make_rows(3)
    rows_b = make_rows(9)
    hash_a = hashlib.sha256(path_a.encode("utf-8")).hexdigest()
    hash_b = hashlib.sha256(path_b.encode("utf-8")).hexdigest()

    # B finishes first...
    loader_b.finish_now({"rows": rows_b, "parser": None})
    history = _history_view(win)
    assert history.table.model().rowCount() == 9
    assert os.path.basename(path_b) in win.status_message()
    assert hash_b[:12] in win.status_message()

    # then A finishes LATE. Nothing about A may reach the screen.
    loader_a.finish_now({"rows": rows_a, "parser": None})

    assert history.table.model().rowCount() == 9, (
        "exhibit A's rows landed after exhibit B's -- a superseded load "
        "overwrote the newer one on screen")
    status = win.status_message()
    assert os.path.basename(path_b) in status
    assert hash_b[:12] in status
    assert hash_a[:12] not in status, (
        "exhibit A's hash reached the status bar after exhibit B's load "
        "had already completed and been shown")


def test_a_superseded_load_is_cancelled_and_disconnected(win, monkeypatch, tmp_path):
    """The mechanism behind the test above, isolated: starting a new load
    while A is still in flight must both request A's cancellation and cut
    A's signals loose, so a late A emission (cancellation is best-effort
    -- see EvidenceLoader.cancel's own docstring) reaches nothing. B's
    open goes through win.open_evidence() directly for the same reason as
    the test above: .trigger() itself already refuses to fire on a
    disabled action in this Qt version, so it cannot exercise this path."""
    path_a = str(tmp_path / "exhibit_a.dat")
    path_b = str(tmp_path / "exhibit_b.dat")
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader",
                        _DeferredFakeLoader)

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path_a, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _accepting_dialog_for(path_a))
    win.open_evidence_action.trigger()
    loader_a = _DeferredFakeLoader.instances[-1]

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path_b, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _accepting_dialog_for(path_b))
    win.open_evidence()

    assert loader_a.cancelled is True
    received = []
    loader_a.loaded.connect(received.append)  # a FRESH connection just to
    # prove the OLD one (MainWindow's) is gone: emitting now must reach
    # this new connection but must NOT reach MainWindow's history view.
    loader_a.finish_now({"rows": make_rows(3), "parser": None})
    assert received  # our own probe connection did fire...
    history = _history_view(win)
    assert history.table.model() is None or history.table.model().rowCount() != 3, (
        "MainWindow's own loaded-signal connection to the superseded "
        "loader was still live")


def test_triggering_open_evidence_while_a_load_is_in_flight_does_nothing(
        win, monkeypatch, tmp_path):
    """The UI-level half of the guard, confirmed directly: with the action
    disabled, a real .trigger() -- standing in for a menu click or Ctrl+O
    -- must not even reach the file dialog a second time, let alone
    construct a second OpenEvidenceDialog or loader."""
    path = str(tmp_path / "exhibit.dat")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _accepting_dialog_for(path))
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader",
                        _DeferredFakeLoader)

    win.open_evidence_action.trigger()
    assert len(_DeferredFakeLoader.instances) == 1
    assert not win.open_evidence_action.isEnabled()

    win.open_evidence_action.trigger()  # a no-op: the action is disabled
    assert len(_DeferredFakeLoader.instances) == 1, (
        "a disabled action's trigger() must not reach open_evidence() at all")


# --- the carved-note must survive filtering and -------
# --- navigation, not just the one instant right after load. -------------

def test_live_only_note_survives_filtering_and_navigation(win, monkeypatch, tmp_path):
    """Not just present once right after load (see
    test_history_count_line_states_these_are_live_records_only above) -- a
    future refactor of HistoryView._update_count or MainWindow.go_to could
    drop the note on the very next filter keystroke or view switch without
    either one raising anything, and nothing else in the suite would catch
    it."""
    fixture_path = str(tmp_path / "WebCacheV01.dat")
    _FakeLoader.result = {"rows": make_rows(200), "parser": None}
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (fixture_path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _AcceptingConsentDialog)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader", _FakeLoader)

    win.open_evidence_action.trigger()
    history = _history_view(win)
    assert "not yet recovered" in history.line_text().lower()

    # Filtering re-triggers _update_count via the model's own
    # layoutRefreshed signal -- the note must still be there afterwards.
    history.filter_box.setText("msn")
    assert "not yet recovered" in history.line_text().lower()
    history.clear_all_filters()
    assert "not yet recovered" in history.line_text().lower()

    # The view is built once and kept (see main_window.py's own
    # docstring), so navigating away and back should not touch it -- but
    # that is exactly the kind of assumption a future change could break
    # silently.
    win.go_to("downloads")
    win.go_to("history")
    assert "not yet recovered" in history.line_text().lower()


# --- busy state: progress bar, elapsed time, Cancel ------------------------
# Before this task, opening a multi-gigabyte exhibit gave an examiner two
# static messages ("Opening X…" then "Parsing evidence…") and nothing else
# for however long the parse actually took -- no way to tell progressing
# from stalled from hung, and no way to abandon it short of killing the
# process. These tests prove the busy indicator, the progress relay, and
# Cancel are actually WIRED -- each one written so that deleting the
# connection it is testing would make it fail, not just deleting the
# feature.

def _start_deferred_load(win, monkeypatch, tmp_path, name="exhibit.dat"):
    path = str(tmp_path / name)
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _accepting_dialog_for(path))
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader",
                        _DeferredFakeLoader)
    win.open_evidence_action.trigger()
    return _DeferredFakeLoader.instances[-1]


def test_busy_indicator_is_hidden_before_any_load(win):
    assert not win._load_progress.isVisible()
    assert not win._load_cancel_button.isVisible()


def test_busy_indicator_shows_while_a_load_is_in_flight(win, monkeypatch, tmp_path):
    """Not a wait cursor alone -- a cursor is easy to miss and disappears the moment the pointer leaves the window.
    A visible progress bar and Cancel button in the status bar are the
    thing an examiner can actually see without touching the mouse."""
    _start_deferred_load(win, monkeypatch, tmp_path)
    assert win._load_progress.isVisible()
    assert win._load_cancel_button.isVisible()


def test_busy_indicator_hides_after_a_successful_load(win, monkeypatch, tmp_path):
    loader = _start_deferred_load(win, monkeypatch, tmp_path)
    loader.finish_now({"rows": make_rows(3), "parser": None})
    assert not win._load_progress.isVisible()
    assert not win._load_cancel_button.isVisible()


def test_busy_indicator_hides_after_a_failed_load(win, monkeypatch, tmp_path):
    loader = _start_deferred_load(win, monkeypatch, tmp_path)
    loader.fail_now("boom")
    assert not win._load_progress.isVisible()
    assert not win._load_cancel_button.isVisible()


def test_the_progress_bar_is_indeterminate_not_a_fabricated_percentage(win):
    """parse_all_entries() has no cheap way to know its total record count
    up front (see EvidenceLoadWorker._check_progress's own docstring) --
    a determinate range here would mean inventing one. Qt's own idiom for
    "known to be working, unknown how much is left" is a (0, 0) range."""
    assert win._load_progress.minimum() == 0
    assert win._load_progress.maximum() == 0


def test_progress_signal_reaches_the_status_bar(win, monkeypatch, tmp_path):
    """Proves loader.progress is actually connected to something that
    updates the status bar -- if EvidenceLoader's progress signal were
    left unconnected (the exact "built and never wired" defect this task
    exists to close), this text would never appear."""
    loader = _start_deferred_load(win, monkeypatch, tmp_path)
    loader.progress.emit("Parsing evidence… 4,200 record(s) parsed so far")
    assert "4,200" in win.status_message()


def test_open_action_disabled_state_matches_cancel_button_visibility(
        win, monkeypatch, tmp_path):
    loader = _start_deferred_load(win, monkeypatch, tmp_path)
    assert not win.open_evidence_action.isEnabled()
    win._load_cancel_button.click()
    assert win.open_evidence_action.isEnabled()


def test_cancel_button_requests_interruption_on_the_real_loader(
        win, monkeypatch, tmp_path):
    """The button must reach EvidenceLoader.cancel() itself, not merely
    hide the progress bar -- a Cancel that only hides its own widget while
    the worker keeps running would not be a cancel at all."""
    loader = _start_deferred_load(win, monkeypatch, tmp_path)
    assert loader.cancelled is False
    win._load_cancel_button.click()
    assert loader.cancelled is True


def test_cancel_button_leaves_the_app_clean_and_usable(win, monkeypatch, tmp_path):
    """The full contract: the action re-enabled, the
    status bar plainly saying the load was cancelled, the busy UI gone,
    and -- the part a screenshot could get wrong -- no rows on screen."""
    _start_deferred_load(win, monkeypatch, tmp_path)
    win._load_cancel_button.click()

    assert win.open_evidence_action.isEnabled()
    assert not win._load_progress.isVisible()
    assert not win._load_cancel_button.isVisible()
    assert "cancelled" in win.status_message().lower()

    history = _history_view(win)
    assert history.table.model() is None or history.table.model().rowCount() == 0, (
        "a cancel must never leave a partially- or fully-populated table "
        "on screen -- an examiner could mistake it for a complete record set")


def test_cancelling_never_lets_a_late_result_populate_the_screen(
        win, monkeypatch, tmp_path):
    """The mechanism behind the test above, isolated: EvidenceLoader.cancel
    is best-effort (see its own docstring) -- a worker that raced past its
    last interruption check can still finish and emit `loaded` AFTER
    Cancel was clicked. _cancel_pending_load()'s disconnect (see its own
    docstring on the superseded-loader race it already closes) is what
    stops that from ever reaching the screen; this proves the Cancel
    button's path reuses the SAME mechanism rather than a second,
    incomplete one that only hides the widgets."""
    loader = _start_deferred_load(win, monkeypatch, tmp_path)
    win._load_cancel_button.click()

    # Emitted AFTER cancel, exactly the race a best-effort request cannot
    # rule out on its own.
    loader.finish_now({"rows": make_rows(7), "parser": None})

    history = _history_view(win)
    assert history.table.model() is None or history.table.model().rowCount() == 0, (
        "a result that raced in after Cancel reached the screen anyway")
    assert "cancelled" in win.status_message().lower(), (
        "the late result's own status text overwrote the cancellation "
        "message the examiner had already been shown")


def test_elapsed_time_is_shown_and_keeps_advancing(win, monkeypatch, tmp_path, qtbot):
    """The honest half of "no total record count available": elapsed time
    ticks on its own timer (see _refresh_load_elapsed's docstring),
    independent of whether the worker's own progress signal fires again --
    this is what still answers "is it alive?" if the parser goes quiet for
    a while."""
    _start_deferred_load(win, monkeypatch, tmp_path)
    first = win.status_message()
    qtbot.wait(1100)  # past _load_status_timer's 500ms interval, twice over
    second = win.status_message()
    assert first != second, (
        "the status bar never changed on its own -- elapsed time is not "
        "actually ticking, only the worker's own (possibly silent) "
        "progress signal would ever update it")


# --- Task: the record detail dialog ---------------------------------------
#
# recordActivated has existed on RecordsTable since it was written with NO
# LISTENER ANYWHERE. Double-click and Enter were a silent no-op on all
# seven record tables -- this project's signature defect, named in
# recovery_loader.py's own docstring as "built, but never wired". The tests
# below are what stop it recurring, and they deliberately prove the
# connection by EMITTING rather than by counting receivers: a receiver
# count says something is attached, not that it does anything.

#: Every nav key whose view owns a RecordsTable. Seven, and the count is
#: part of the assertion: a new record view that forgets this wiring must
#: fail here rather than ship a dead double-click.
_RECORD_VIEW_KEYS = ("history", "recovery", "downloads", "cookies",
                     "containers", "domains", "indicators")


def _detail_dialogs(win):
    return list(getattr(win, "_detail_dialogs", []))


def test_every_record_view_really_owns_a_table(win):
    """The premise the next test rests on. If a view stopped exposing
    .table, the loop below would silently check nothing."""
    for key in _RECORD_VIEW_KEYS:
        widget = win._ensure_view_built(key)
        assert hasattr(widget, "table"), key


def test_every_record_table_has_recordActivated_connected(win, qtbot):
    """All seven, proven by emitting: each activation must produce a real
    RecordDetailDialog in the shell's own registry."""
    for key in _RECORD_VIEW_KEYS:
        widget = win._ensure_view_built(key)
        before = len(_detail_dialogs(win))
        widget.table.recordActivated.emit(
            {"CleanUrl": "https://example.test/%s" % key,
             "Origin": "Live record", "_kind": "history", "_record": {}})
        assert len(_detail_dialogs(win)) == before + 1, (
            "%s: activating a record did nothing" % key)
    for dlg in _detail_dialogs(win):
        dlg.close()


def test_the_dialog_shows_the_record_it_was_given(win, qtbot):
    history = _history_view(win)
    history.table.recordActivated.emit(
        {"CleanUrl": "https://example.test/one", "Origin": "Live record",
         "_kind": "history", "_record": {"CleanUrl": "https://example.test/one"}})
    dlg = _detail_dialogs(win)[-1]
    assert "https://example.test/one" in dlg.identity_label.text()
    dlg.close()


def test_a_closed_dialog_leaves_the_registry(win, qtbot):
    """Python must not garbage-collect a still-visible non-modal dialog out
    from under Qt -- the same reason RecordsTable keeps _filter_popup as an
    attribute -- but a registry that only ever grows is a leak."""
    history = _history_view(win)
    history.table.recordActivated.emit(
        {"CleanUrl": "https://example.test/two", "Origin": "Live record",
         "_kind": "history", "_record": {}})
    assert len(_detail_dialogs(win)) == 1
    _detail_dialogs(win)[0].close()
    qtbot.waitUntil(lambda: not _detail_dialogs(win), timeout=2000)


def test_dialogs_stack_rather_than_replacing_each_other(win, qtbot):
    """Deliberate, and why no Back button is needed: a record reached by
    drilling from another dialog leaves the originating one open behind
    it."""
    history = _history_view(win)
    for i in range(3):
        history.table.recordActivated.emit(
            {"CleanUrl": "https://example.test/%d" % i,
             "Origin": "Live record", "_kind": "history", "_record": {}})
    assert len(_detail_dialogs(win)) == 3
    assert all(d.isVisible() for d in _detail_dialogs(win))
    for d in _detail_dialogs(win):
        d.close()


def test_a_member_row_opens_a_further_dialog(win, qtbot):
    """The aggregate drill-through. A summary that copies instead of
    opening reads as "that is all there is"."""
    domains = win._ensure_view_built("domains")
    member = {"CleanUrl": "https://example.test/member", "Origin": "Live record"}
    domains.table.recordActivated.emit(
        {"Domain": "example.test", "Records": 1, "_kind": "domain",
         "_record": None, "_members": [member]})
    first = _detail_dialogs(win)[-1]
    first.recordRequested.emit({"_record": member, "_kind": "history",
                                "Origin": "Live record"})
    assert len(_detail_dialogs(win)) == 2
    for d in _detail_dialogs(win):
        d.close()


def test_the_dialogs_explain_request_reaches_the_same_explain_dialog(
        win, qtbot, monkeypatch):
    """One ExplainDialog for the grid's F1 and the detail dialog's F1 --
    a second, differently-worded explanation of the same fact would be a
    second claim."""
    seen = []
    monkeypatch.setattr(main_window_module.ExplainDialog, "exec",
                        lambda self: seen.append(self._text))
    history = _history_view(win)
    history.table.recordActivated.emit(
        {"CleanUrl": "https://example.test/x", "Origin": "Live record",
         "_kind": "history", "_record": {}})
    dlg = _detail_dialogs(win)[-1]
    dlg.explainRequested.emit("Field: Clean URL\n\nsome explanation")
    assert seen and "some explanation" in seen[0]
    dlg.close()


def test_opening_a_second_exhibit_closes_open_record_dialogs(win, qtbot,
                                                             monkeypatch):
    """Open dialogs hold _record references into the PREVIOUS exhibit's
    parser. Leaving them open both keeps that parser (and its blobs) alive
    and shows the examiner rows from a database that is no longer the
    case."""
    history = _history_view(win)
    history.table.recordActivated.emit(
        {"CleanUrl": "https://example.test/old", "Origin": "Live record",
         "_kind": "history", "_record": {}})
    assert len(_detail_dialogs(win)) == 1
    evidence = EvidenceSet([], {}, {})
    win._on_evidence_loaded({"rows": [], "parser": None}, evidence)
    assert _detail_dialogs(win) == []
