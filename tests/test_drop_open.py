"""The promise the first-run card has always made: drag an exhibit here.

first_run.py has told examiners "Open a WebCacheV01.dat to begin. Drag it
here, or use the button below" since it was written, and until this file
nothing in the application accepted a drop -- no setAcceptDrops, no
dragEnterEvent, no dropEvent anywhere under webcache/. Dropping a file did
nothing whatsoever, and a drop target that does nothing is indistinguishable
from a broken application. It is the same shape of defect as recordActivated,
ROLE_ROW and selected_rows: advertised, then never wired.

THE CARDINAL RULE these tests exist to pin: a dropped file must never
bypass the consent gate. A drop is a convenience for CHOOSING a file --
nothing about it authorises reading one. So a drop goes to exactly the
place the Open Database button goes, MainWindow._open_evidence_at(), and
if the OpenEvidenceDialog there is declined, nothing is opened, hashed or
parsed. test_a_drop_the_consent_gate_declines_reads_nothing pins that
with the REAL OpenEvidenceDialog and a poisoned open(), not a stand-in.

Drops are driven by constructing QDragEnterEvent/QDropEvent with a
QMimeData carrying setUrls([...]) and sending them to the widget, which is
how the real drag manager delivers them; synthesised mouse input is not
reliable in this environment.
"""
import builtins
import hashlib
import os

import pytest
from PySide6.QtCore import QMimeData, QObject, QPoint, QPointF, Qt, QUrl, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from webcache.provenance import EvidenceSet
from webcache.shell import settings
from webcache.shell.open_evidence import OpenEvidenceDialog
from webcache.shell.main_window import MainWindow


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1400, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


@pytest.fixture
def exhibit(tmp_path):
    """A WebCache folder as it sits on an examined machine."""
    folder = tmp_path / "WebCache"
    folder.mkdir()
    db = folder / "WebCacheV01.dat"
    db.write_bytes(b"\x00" * 64)
    (folder / "V01.log").write_bytes(b"\x00" * 16)
    return db


def _mime_for(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


# Both helpers return the accepted FLAG, never the event object. Qt takes
# ownership of an event passed to sendEvent and deletes the C++ side of it;
# a surviving Python wrapper is then a dangling handle, and pytest's
# assertion rewriting -- which reprs every operand of a failing assert --
# turned a plain test failure into a hard interpreter crash the first time
# one of these was returned. Reading the flag before the wrapper goes out
# of scope is the whole fix.
#
# A DROP IS THREE EVENTS, NEVER ONE. QApplication::notify tracks the
# widget a drag entered and delivers DragMove and Drop only to that
# widget: a Drop sent on its own is discarded inside notify() and the
# receiver's event() is never even called -- verified directly against a
# stock QWidget with a dropEvent override that simply never fired. So a
# helper that sent only the Drop would report "the window ignores drops"
# no matter what the window did, which is a failure for the wrong reason
# in the most dangerous shape: it looks exactly like the feature being
# absent, and it would still look like that after the feature was built.
# _drop() therefore sends the sequence the platform's own drag manager
# sends -- enter, move, drop -- and a drag the window turns down at the
# enter never reaches the drop, which is precisely the real behaviour a
# refusal has to have.

def _drag_enter(widget, mime):
    event = QDragEnterEvent(QPoint(40, 40), Qt.CopyAction, mime,
                            Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, event)
    return bool(event.isAccepted())


def _drag_move(widget, mime):
    event = QDragMoveEvent(QPoint(40, 40), Qt.CopyAction, mime,
                           Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, event)
    return bool(event.isAccepted())


def _raw_drop(widget, mime):
    """The three events and NOTHING after them -- no turn of the event
    loop. This is the state the platform's own drop callback is in at the
    instant it returns, which is what the last two tests in this file are
    about; every other test wants _drop below."""
    if not _drag_enter(widget, mime):
        return False
    _drag_move(widget, mime)
    event = QDropEvent(QPointF(40, 40), Qt.CopyAction, mime,
                       Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, event)
    return bool(event.isAccepted())


def _drop(widget, mime):
    """A whole drop, as an examiner experiences one: the three events,
    and then the turn of the event loop the window defers the consent
    gate onto (see dropEvent -- the gate must not run inside the
    platform's own drop callback)."""
    accepted = _raw_drop(widget, mime)
    QApplication.processEvents()
    return accepted


class _SpyConsentDialog:
    recover_deleted = False
    """Stands in for OpenEvidenceDialog exactly the way test_wiring.py's does --
    a real QDialog.exec() would block in a nested event loop forever. What
    it records is which path the shell asked to open, which is the whole
    question for a drop."""
    instances = []
    accept = False

    def __init__(self, path, parent=None):
        self.path = path
        self.parent = parent
        self.evidence_set = None
        if _SpyConsentDialog.accept:
            digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
            self.evidence_set = EvidenceSet([path], {path: 64}, {path: digest})
        _SpyConsentDialog.instances.append(self)

    def exec(self):
        return QDialog.Accepted if _SpyConsentDialog.accept else QDialog.Rejected

    def deleteLater(self):
        pass


class _FakeLoader(QObject):
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    calls = []

    def load(self, db_path, known_hashes=None):
        _FakeLoader.calls.append((db_path, known_hashes))

    def cancel(self):
        pass


@pytest.fixture(autouse=True)
def _reset_spies(monkeypatch, tmp_path):
    _SpyConsentDialog.instances = []
    _SpyConsentDialog.accept = False
    _FakeLoader.calls = []
    # Settings are written by a drop the same way the file dialog writes
    # them; keep that out of the checkout.
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    yield


@pytest.fixture
def spy(monkeypatch):
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog",
                        _SpyConsentDialog)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader", _FakeLoader)
    return _SpyConsentDialog


# --- the drop reaches the consent gate, and only the consent gate ---------

def test_a_dragged_database_is_accepted_by_the_window(win, exhibit):
    """The window has to SAY it will take the drag, or Windows shows the
    examiner a no-entry cursor and the drop never happens at all."""
    accepted = _drag_enter(win, _mime_for([exhibit]))

    assert accepted, (
        "the window refused a dragged WebCacheV01.dat -- the first-run "
        "card's 'Drag it here' is a promise nothing keeps")


def test_dropping_a_database_opens_the_consent_gate_for_that_exact_path(
        win, spy, exhibit):
    _drop(win, _mime_for([exhibit]))

    assert len(spy.instances) == 1, (
        "a dropped exhibit never reached OpenEvidenceDialog")
    assert spy.instances[0].path == os.path.normpath(str(exhibit))
    assert spy.instances[0].parent is win


def test_a_drop_cancelled_at_the_dialog_reads_nothing(
        win, monkeypatch, exhibit):
    """The cardinal rule, pinned against the REAL OpenEvidenceDialog.

    Only exec() is stubbed -- the dialog itself is constructed exactly as
    a drop would construct it, lists the files it would read, and is then
    cancelled. open() is poisoned for everything under the evidence folder,
    so if any part of this path so much as opened the exhibit to sniff it,
    this test says so rather than passing quietly.
    """
    real_open = builtins.open
    folder = str(exhibit.parent)

    def _no_reads(path, *args, **kwargs):
        if str(path).startswith(folder):
            raise AssertionError(
                "a cancelled drop opened %s -- the dialog was not the gate"
                % (path,))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _no_reads)
    monkeypatch.setattr(OpenEvidenceDialog, "exec", lambda self: QDialog.Rejected)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader", _FakeLoader)

    _drop(win, _mime_for([exhibit]))

    assert _FakeLoader.calls == [], (
        "a cancelled drop reached the loader -- nothing may be parsed "
        "before Open is pressed")
    assert win._parser is None, "a cancelled drop left a parser behind"
    assert getattr(win, "_evidence_set", None) is None, (
        "a cancelled drop left an evidence set behind -- something was hashed")
    assert "cancelled" in win.status_message().lower()


def test_an_accepted_drop_opens_the_exhibit_through_the_ordinary_loader(
        win, spy, exhibit):
    """Accepting must land in exactly the same machinery the button uses,
    hashes and all -- not a second, parallel open path."""
    spy.accept = True

    _drop(win, _mime_for([exhibit]))

    assert len(_FakeLoader.calls) == 1
    db_path, known_hashes = _FakeLoader.calls[0]
    assert db_path == os.path.normpath(str(exhibit))
    assert known_hashes == spy.instances[0].evidence_set.hashes, (
        "the consent gate's own hashes must be carried into the load, "
        "the same as the file-dialog path does")


def test_a_drop_remembers_the_directory_the_file_dialog_will_start_in(
        win, spy, exhibit):
    """open_evidence() saves last_evidence_dir the moment a file is
    chosen, whatever consent then decides. A drop chooses a file too."""
    _drop(win, _mime_for([exhibit]))

    assert settings.get("last_evidence_dir") == os.path.normpath(
        str(exhibit.parent))


# --- the cases a real desktop produces ------------------------------------

def test_dropping_a_webcache_folder_opens_the_database_inside_it(
        win, spy, exhibit):
    _drop(win, _mime_for([exhibit.parent]))

    assert len(spy.instances) == 1
    assert spy.instances[0].path == os.path.normpath(str(exhibit))


def test_dropping_five_databases_opens_none_of_them_and_says_why(
        win, spy, tmp_path):
    dropped = []
    for n in range(5):
        folder = tmp_path / ("case%d" % n)
        folder.mkdir()
        db = folder / "WebCacheV01.dat"
        db.write_bytes(b"\x00")
        dropped.append(db)

    _drop(win, _mime_for(dropped))

    assert spy.instances == [], "one of five was opened without being chosen"
    assert "5" in win.status_message()


def test_dropping_a_screenshot_opens_nothing_and_names_it(win, spy, tmp_path):
    """Refused with a reason, not handed to the parser to fail obscurely."""
    junk = tmp_path / "screenshot.png"
    junk.write_bytes(b"\x89PNG")

    _drop(win, _mime_for([junk]))

    assert spy.instances == []
    assert "screenshot.png" in win.status_message()


def test_a_database_dropped_with_its_own_logs_is_one_exhibit(
        win, spy, exhibit):
    """Select-all inside a WebCache folder: the logs are already in the
    consent scope, so this is one choice, not three."""
    _drop(win, _mime_for([exhibit, exhibit.parent / "V01.log"]))

    assert len(spy.instances) == 1
    assert spy.instances[0].path == os.path.normpath(str(exhibit))


def test_a_non_file_drag_is_never_taken_and_never_crashes(win, spy, exhibit):
    """Dragged text and a dragged web URL both have to fall straight
    through -- and leave the window able to take a real exhibit right
    afterwards, which is what proves the guard is a filter rather than a
    dead handler."""
    text = QMimeData()
    text.setText(str(exhibit))
    web = QMimeData()
    web.setUrls([QUrl("https://example.invalid/WebCacheV01.dat")])
    before = win.status_message()

    for mime in (text, web):
        assert not _drag_enter(win, mime)
        assert not _drop(win, mime)

    assert spy.instances == []
    assert win.status_message() == before

    _drop(win, _mime_for([exhibit]))
    assert len(spy.instances) == 1, (
        "the window stopped taking real drops after a non-file drag")


def test_a_drop_is_refused_while_an_exhibit_is_already_being_opened(
        win, spy, exhibit, tmp_path):
    """The Open Database button is disabled for the whole of a load. A
    drop is the same affordance, so it has to be unavailable at the same
    moments -- otherwise the one path that CANNOT be disabled becomes a
    way round the guard the other path keeps."""
    spy.accept = True
    _drop(win, _mime_for([exhibit]))
    assert not win.open_evidence_action.isEnabled(), (
        "precondition: a load in flight disables Open Evidence")

    second = tmp_path / "other.dat"
    second.write_bytes(b"\x00")
    _drop(win, _mime_for([second]))

    assert len(spy.instances) == 1, (
        "a second exhibit was opened while the first was still loading")
    assert len(_FakeLoader.calls) == 1


# --- the window is the drop target, not one card inside it ----------------

def test_nothing_inside_the_window_can_swallow_a_dropped_exhibit(win):
    """Qt does NOT propagate a drag up the widget tree: QDragManager picks
    the first widget under the cursor whose acceptDrops() is true and
    stops there, so one QLineEdit deep inside a view is enough to make an
    exhibit dropped on that part of the window silently do nothing while
    the rest of it works. Every view is built here, because the offenders
    arrive with the views.
    """
    for key in win.nav_keys:
        win._ensure_view_built(key)

    greedy = [child for child in win.findChildren(QLineEdit)
              if child.window() is win and child.acceptDrops()]

    assert greedy == [], (
        "%d widget(s) inside the window would eat a dropped exhibit "
        "before the window ever saw it" % len(greedy))


def test_an_exhibit_can_be_dropped_once_another_is_already_open(
        win, spy, exhibit, tmp_path):
    """The first-run card is gone once evidence is open, so a drop target
    tied to that card would stop existing exactly when an examiner wants
    to compare a second exhibit."""
    spy.accept = True
    _drop(win, _mime_for([exhibit]))
    win.open_evidence_action.setEnabled(True)  # stand in for a finished load

    second_folder = tmp_path / "second"
    second_folder.mkdir()
    second = second_folder / "WebCacheV01.dat"
    second.write_bytes(b"\x00")

    _drop(win, _mime_for([second]))

    assert len(spy.instances) == 2
    assert spy.instances[1].path == os.path.normpath(str(second))


# --- the drop callback belongs to the platform, not to this window -------

def test_the_consent_gate_does_not_open_inside_the_platforms_drop_callback(
        win, spy, exhibit):
    """A modal dialog opened from dropEvent freezes the application the
    exhibit was dragged FROM.

    On Windows a drop is delivered synchronously from inside
    IDropTarget::Drop, which is itself called from inside the source
    application's DoDragDrop -- Explorer, usually. Explorer's own message
    loop is inside that call and does not come back until Drop returns.
    Open OpenEvidenceDialog there and Explorer is frozen for as long as the
    examiner spends reading the file list, ticking the box, and then
    waiting for the SHA-256 of a multi-gigabyte exhibit: minutes of a
    dead File Explorer window, blamed on Windows rather than on this.

    So dropEvent hands the platform its callback back immediately and the
    gate opens on the next turn of this application's own event loop.
    Nothing an examiner can perceive changes; what changes is who is
    waiting.
    """
    _raw_drop(win, _mime_for([exhibit]))

    assert spy.instances == [], (
        "the consent gate opened while the platform's drop callback was "
        "still on the stack -- the application dragged from is frozen "
        "behind it")

    QApplication.processEvents()

    assert len(spy.instances) == 1, (
        "deferring the gate lost the drop entirely")
    assert spy.instances[0].path == os.path.normpath(str(exhibit))


def test_two_drops_in_the_same_instant_open_one_gate(win, spy, exhibit,
                                                     tmp_path):
    """The guard that deferral must not quietly remove.

    Refusing a drop mid-load leans on open_evidence_action being
    disabled, and that only happens once the gate has been reached. With
    the gate deferred there is a window -- however short -- in which two
    drops have been taken and neither has opened anything yet, and the
    action still looks enabled to both. Two consent dialogs for two
    different exhibits, stacked, is the failure being prevented.
    """
    second = tmp_path / "other.dat"
    second.write_bytes(b"\x00")

    _raw_drop(win, _mime_for([exhibit]))
    _raw_drop(win, _mime_for([second]))
    QApplication.processEvents()

    assert len(spy.instances) == 1, (
        "%d gates opened for one pair of drops" % len(spy.instances))
