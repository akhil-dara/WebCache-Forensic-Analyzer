"""What the examiner sees while an exhibit is still in mid-air.

A drop target that looks inert is barely better than one that is. With
the window wired but silent, dragging a WebCacheV01.dat over it changes
nothing on screen: the only feedback is the platform's own cursor, which
says at most "a drop is possible somewhere here" and never says what the
application would do with it. The examiner finds out by letting go.

So the window answers three questions while the drag is still over it,
before anything is committed to:

    WILL this be taken?      -- the prompt appears at all
    WHAT will be opened?     -- it names the exhibit
    or WHY NOT?              -- it carries drop_target's own refusal, the
                                same words the status bar would show after

and it answers them in colour as well as in words, because "something
appeared" and "something appeared, in the refusing colour" are
distinguishable at a glance where two sentences are not.

The prompt is drawn INSIDE the window, so it is also a hazard: a widget
that appears under the cursor mid-drag is exactly the kind of thing that
steals the drop it was meant to advertise. The last test here pins that
it does not.
"""
import hashlib

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import (QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent,
                           QDropEvent)
from PySide6.QtWidgets import QApplication, QDialog, QFrame

from webcache.provenance import EvidenceSet
from webcache.shell import theme
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
    folder = tmp_path / "WebCache"
    folder.mkdir()
    db = folder / "WebCacheV01.dat"
    db.write_bytes(b"\x00" * 64)
    return db


@pytest.fixture(autouse=True)
def _keep_the_checkout_clean(monkeypatch, tmp_path):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    yield


@pytest.fixture(autouse=True)
def _restore_theme(qapp):
    """A toggle here must not leak the other palette into the rest of the
    session -- theme.apply() is application-wide."""
    original = theme.current_name()
    yield
    if theme.current_name() != original:
        theme.apply(qapp, original)


class _StubConsent:
    recover_deleted = False
    """Only ever used by the one test that actually lets go. A real
    OpenEvidenceDialog.exec() would block in a nested event loop forever."""
    instances = []

    def __init__(self, path, parent=None):
        self.path = path
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
        self.evidence_set = EvidenceSet([path], {path: 64}, {path: digest})
        _StubConsent.instances.append(self)

    def exec(self):
        return QDialog.Accepted

    def deleteLater(self):
        pass


def _mime_for(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


# See test_drop_open.py's own note: a drop is three events, never one --
# QApplication::notify delivers DragMove and Drop only to the widget a
# drag entered, and discards a Drop that had no enter before it.

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


def _drag_leave(widget):
    QApplication.sendEvent(widget, QDragLeaveEvent())


def _drop(widget, mime):
    if not _drag_enter(widget, mime):
        return False
    _drag_move(widget, mime)
    event = QDropEvent(QPointF(40, 40), Qt.CopyAction, mime,
                       Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, event)
    # The window defers the consent gate off the platform's own drop
    # callback -- see MainWindow.dropEvent and test_drop_open.py's two
    # tests for it -- so a whole drop includes the turn of the loop the
    # gate lands on.
    QApplication.processEvents()
    return bool(event.isAccepted())


# --- the prompt appears, and says what will happen ------------------------

def test_no_prompt_is_shown_before_any_drag_arrives(win):
    assert not win.drop_overlay.isVisible()


def test_a_dragged_exhibit_is_named_before_the_examiner_lets_go(win, exhibit):
    _drag_enter(win, _mime_for([exhibit]))

    assert win.drop_overlay.isVisible(), (
        "the window took the drag without showing the examiner anything -- "
        "an inert drop target is barely better than a missing one")
    assert "WebCacheV01.dat" in win.drop_overlay.message()


def test_the_prompt_repeats_the_open_promise_rather_than_only_inviting(
        win, exhibit):
    """The first-run card's own promise is now "nothing is read until
    you press Open" -- a statement, not a request for authority. A drop is
    the one entry point that can feel like it skips that, so this is where
    saying so matters most."""
    _drag_enter(win, _mime_for([exhibit]))

    detail = win.drop_overlay.detail().lower()
    assert "read" in detail and "open" in detail


def test_a_dragged_screenshot_says_why_it_will_be_refused(win, tmp_path):
    junk = tmp_path / "screenshot.png"
    junk.write_bytes(b"\x89PNG")

    _drag_enter(win, _mime_for([junk]))

    assert win.drop_overlay.isVisible()
    assert "screenshot.png" in win.drop_overlay.message()


def test_a_drag_during_a_load_says_the_drop_is_unavailable(win, exhibit):
    """Both Open Database buttons go grey mid-load. The drop target
    cannot go grey, so it has to say so instead."""
    win.open_evidence_action.setEnabled(False)

    _drag_enter(win, _mime_for([exhibit]))

    assert win.drop_overlay.message() == MainWindow.BUSY_DROP_REFUSAL


# --- and says it in colour, not only in words -----------------------------

def test_an_exhibit_and_a_refusal_do_not_look_the_same(win, exhibit, tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_bytes(b"hello")

    _drag_enter(win, _mime_for([exhibit]))
    ready_tone, ready_accent = win.drop_overlay.tone(), win.drop_overlay.accent()
    _drag_leave(win)
    _drag_enter(win, _mime_for([junk]))
    refused_tone, refused_accent = (win.drop_overlay.tone(),
                                    win.drop_overlay.accent())

    assert (ready_tone, refused_tone) == ("ready", "refused")
    assert ready_accent != refused_accent, (
        "a refusal that is painted like an invitation is read as an "
        "invitation -- the words are not looked at mid-drag")
    assert ready_accent == theme.color("primary")


def test_the_prompt_is_painted_in_the_palette_that_is_actually_current(
        win, exhibit):
    """theme.apply() cannot reach a colour baked into a stylesheet at
    construction time; every other drawn surface in this shell has a
    refresh_theme() for exactly that reason."""
    win._toggle_theme()

    _drag_enter(win, _mime_for([exhibit]))

    assert win.drop_overlay.accent() == theme.color("primary")


# --- and gets out of the way ---------------------------------------------

def test_the_prompt_clears_when_the_drag_leaves_the_window(win, exhibit):
    _drag_enter(win, _mime_for([exhibit]))
    assert win.drop_overlay.isVisible()

    _drag_leave(win)

    assert not win.drop_overlay.isVisible()


def test_the_prompt_clears_the_moment_the_drop_lands(win, exhibit, monkeypatch):
    """Left up, it would sit over the consent dialog's own parent window
    and then over the exhibit it just opened."""
    _StubConsent.instances = []
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog", _StubConsent)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader",
                        lambda parent=None: _NullLoader())

    _drop(win, _mime_for([exhibit]))

    assert _StubConsent.instances, "precondition: the drop reached the gate"
    assert not win.drop_overlay.isVisible()


def test_a_non_file_drag_shows_no_prompt_at_all(win, exhibit):
    text = QMimeData()
    text.setText(str(exhibit))
    web = QMimeData()
    web.setUrls([QUrl("https://example.invalid/WebCacheV01.dat")])

    for mime in (text, web):
        _drag_enter(win, mime)
        assert not win.drop_overlay.isVisible()


def test_the_prompt_covers_the_window_and_keeps_covering_it_when_resized(
        win, exhibit):
    """Sized once at construction it would be the wrong size for every
    window an examiner actually works at."""
    _drag_enter(win, _mime_for([exhibit]))
    win.resize(1000, 700)
    QApplication.processEvents()

    covered = win.drop_overlay.geometry()
    target = win.centralWidget().rect()
    assert covered.width() == target.width()
    assert covered.height() == target.height()


# --- and is actually DRAWN, which none of the above proves --------------
#
# Everything above passes on a prompt that is constructed, populated and
# never painted: isVisible() is a flag Qt sets from the widget tree, not a
# statement about pixels. This project has twice had a green suite over a
# GUI that was broken on screen, both times because every assertion was
# about structure. These two are about the picture.

def test_the_prompt_paints_over_the_view_behind_it(win, exhibit):
    """A plain QWidget does NOT paint its own stylesheet background --
    Qt draws that only for widgets that ask for it. Without the wash the
    prompt is a card floating over fully legible content, with the text
    behind it bleeding through the gaps between its lines, and every
    structural test here still passes.
    """
    central = win.centralWidget()
    # The sidebar's emerald Open Database button, asked for its own
    # position rather than guessed at: a fixed coordinate landed on bare
    # sidebar, which is already painted in the window colour the wash
    # itself is made of, so that pixel could not have changed however
    # well the wash worked. It is the one sample point here that is
    # certain not to be the wash's own colour, and it sits well clear of
    # the vertically centred card.
    button = win.sidebar.open_button
    sample = button.mapTo(central, button.rect().center())
    before = central.grab().toImage().pixelColor(sample)

    _drag_enter(win, _mime_for([exhibit]))
    QApplication.processEvents()

    after = central.grab().toImage().pixelColor(sample)
    assert after != before, (
        "the accent button is still full strength with the prompt up -- "
        "the window behind it is being read straight through it")


def test_a_realistic_refusal_is_not_clipped_by_the_card_it_sits_in(
        win, tmp_path):
    """Refusals are sentences, not labels: two or three wrapped lines
    naming the file. A card sized by a layout that never resolved
    heightForWidth comes up one line short and silently cuts the last one
    off -- which is where the actionable half of the sentence lives.
    first_run.py's own two comments document this exact failure twice.
    """
    junk = tmp_path / "TeamViewer15_Logfile.log"
    junk.write_bytes(b"x")

    _drag_enter(win, _mime_for([junk]))
    QApplication.processEvents()

    card = win.drop_overlay.findChild(QFrame, "dropOverlayCard")
    assert card.height() >= card.sizeHint().height(), (
        "the refusal is %dpx tall in a card %dpx high -- the examiner "
        "reads a sentence with its ending cut off"
        % (card.sizeHint().height(), card.height()))


def test_the_prompt_never_steals_the_drop_it_advertises(win, exhibit,
                                                        monkeypatch):
    """The hazard this whole widget creates: it appears under the cursor
    mid-drag, and Qt delivers a drop to the first widget under the cursor
    whose acceptDrops() is true, with no propagation to the parent
    afterwards. An overlay that accepted drops would swallow every one of
    them and the feature would fail exactly when it looked most ready."""
    _StubConsent.instances = []
    monkeypatch.setattr("webcache.shell.main_window.OpenEvidenceDialog", _StubConsent)
    monkeypatch.setattr("webcache.shell.main_window.EvidenceLoader",
                        lambda parent=None: _NullLoader())

    _drag_enter(win, _mime_for([exhibit]))
    assert win.drop_overlay.isVisible(), "precondition: the prompt is up"
    assert not win.drop_overlay.acceptDrops()

    _drop(win, _mime_for([exhibit]))

    assert _StubConsent.instances, (
        "the prompt swallowed the drop it was showing an invitation for")


class _NullLoader:
    """Enough of EvidenceLoader for a drop to be accepted without a parse
    actually starting -- these tests are about what is on screen."""

    class _Sig:
        def connect(self, _slot):
            pass

    progress = _Sig()
    loaded = _Sig()
    failed = _Sig()

    def load(self, db_path, known_hashes=None):
        pass

    def cancel(self):
        pass
