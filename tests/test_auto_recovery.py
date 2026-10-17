"""With the box ticked, recovery runs by itself once the parse is done."""
import hashlib

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QFileDialog

from webcache.provenance import EvidenceSet
from webcache.shell import main_window as mw
from webcache.shell.main_window import MainWindow
from tests.fixtures import make_rows
from tests.test_recovery_wiring import (_DeferredFakeRecoveryLoader,
                                        _FakeEngine, _FakeParser)


def _dialog(recover):
    class _Dialog:
        recover_deleted = recover

        def __init__(self, path, parent=None):
            digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
            self.evidence_set = EvidenceSet([path], {path: 1}, {path: digest})

        def exec(self):
            return QDialog.Accepted

        def deleteLater(self):
            pass
    return _Dialog


@pytest.fixture
def win(qtbot):
    _DeferredFakeRecoveryLoader.instances = []
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    return w


def _open(win, monkeypatch, tmp_path, recover, parser):
    class _SyncLoader(QObject):
        progress = Signal(str)
        loaded = Signal(object)
        failed = Signal(str)

        def load(self, db_path, known_hashes=None):
            self.loaded.emit({"rows": make_rows(5), "parser": parser})

        def cancel(self):
            pass

    path = str(tmp_path / "exhibit.dat")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr(mw, "OpenEvidenceDialog", _dialog(recover))
    monkeypatch.setattr(mw, "EvidenceLoader", _SyncLoader)
    monkeypatch.setattr(mw, "RecoveryLoader", _DeferredFakeRecoveryLoader)
    win.open_evidence_action.trigger()


def test_a_ticked_box_starts_recovery_once_the_parse_completes(
        win, monkeypatch, tmp_path, qtbot):
    parser = _FakeParser("exhibit")
    _open(win, monkeypatch, tmp_path, True, parser)
    qtbot.waitUntil(lambda: len(_DeferredFakeRecoveryLoader.instances) == 1,
                    timeout=2_000)
    assert _DeferredFakeRecoveryLoader.instances[0].parser is parser


def test_an_unticked_box_starts_nothing(win, monkeypatch, tmp_path, qtbot):
    _open(win, monkeypatch, tmp_path, False, _FakeParser("exhibit"))
    qtbot.wait(100)
    assert _DeferredFakeRecoveryLoader.instances == []
    assert win.recover_action.isEnabled()


def test_no_parser_means_no_scan(win, monkeypatch, tmp_path, qtbot):
    _open(win, monkeypatch, tmp_path, True, None)
    qtbot.wait(100)
    assert _DeferredFakeRecoveryLoader.instances == []


def test_the_recover_action_is_there_for_a_later_run(win, monkeypatch,
                                                     tmp_path, qtbot):
    _open(win, monkeypatch, tmp_path, True, _FakeParser("exhibit"))
    qtbot.waitUntil(lambda: len(_DeferredFakeRecoveryLoader.instances) == 1,
                    timeout=2_000)
    _DeferredFakeRecoveryLoader.instances[0].finish_now(_FakeEngine())
    assert win.recover_action.isEnabled()
    win.recover_action.trigger()
    assert len(_DeferredFakeRecoveryLoader.instances) == 2


def test_a_replaced_parser_before_the_queued_turn_stops_the_scan(
        win, monkeypatch, tmp_path, qtbot):
    parser = _FakeParser("exhibit")
    _open(win, monkeypatch, tmp_path, True, parser)
    # The auto-recovery is queued (QTimer.singleShot(0, ...)) but has not
    # fired yet -- swap the parser out from under it before the event loop
    # gets its next turn, exactly what a second open landing first would
    # do.
    win._parser = _FakeParser("swapped")
    qtbot.wait(100)
    assert _DeferredFakeRecoveryLoader.instances == []
