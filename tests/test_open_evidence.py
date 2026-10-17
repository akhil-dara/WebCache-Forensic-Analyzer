"""The one question at open, and the gates it replaces.

Opening evidence lists every file that will be read -- as information,
not as a consent -- and asks one thing: whether to recover deleted
records too. Nothing is read before Open is pressed.
"""
import builtins
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog

from webcache.shell import case_store, first_run, settings
from webcache.shell import main_window as mw
from webcache.shell.open_evidence import RECOVER_LABEL, OpenEvidenceDialog


@pytest.fixture
def evidence(tmp_path):
    d = tmp_path / "exhibit"
    d.mkdir()
    (d / "WebCacheV01.dat").write_bytes(b"database bytes")
    (d / "V01.log").write_bytes(b"log bytes")
    (d / "V0100123.log").write_bytes(b"more log bytes")
    (d / "V01.chk").write_bytes(b"chk")
    return d / "WebCacheV01.dat"


@pytest.fixture
def dlg(qtbot, evidence):
    d = OpenEvidenceDialog(str(evidence))
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    return d


def _worker_finished(worker):
    try:
        return worker.isFinished()
    except RuntimeError:
        return True


def test_it_is_titled_open_evidence_and_names_the_file(dlg, evidence):
    assert dlg.windowTitle() == "Open evidence"
    assert str(evidence) in [dlg.list.item(i).text()
                             for i in range(dlg.list.count())]


def test_every_file_that_will_be_read_is_listed(dlg, evidence):
    from webcache.engine.ese_parser import evidence_scope
    assert sorted(dlg.files) == sorted(evidence_scope(str(evidence)))


def test_the_recovery_box_is_ticked_by_default_and_worded_exactly(dlg):
    assert dlg.recover_box.text() == RECOVER_LABEL
    assert dlg.recover_box.isChecked()
    assert dlg.recover_deleted is True


def test_open_is_available_without_ticking_anything(dlg):
    assert dlg.ok_button.text() == "Open"
    assert dlg.ok_button.isEnabled()


def test_an_unticked_box_is_not_remembered(qtbot, evidence):
    first = OpenEvidenceDialog(str(evidence))
    qtbot.addWidget(first)
    first.recover_box.setChecked(False)
    first.reject()
    second = OpenEvidenceDialog(str(evidence))
    qtbot.addWidget(second)
    assert second.recover_deleted is True
    assert "recover" not in json.dumps(settings.load()).lower()


def test_nothing_asks_for_authorisation(dlg):
    text = dlg.intro_text().lower()
    assert "authoris" not in text and "consent" not in text
    assert "sha-256" in text


def test_no_evidence_file_is_opened_before_open_is_pressed(monkeypatch,
                                                           evidence, qtbot):
    exhibit_dir = str(evidence.parent)
    opened = []
    real_open = builtins.open

    def spy_open(file, *args, **kwargs):
        if str(file).startswith(exhibit_dir):
            opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    d = OpenEvidenceDialog(str(evidence))
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    assert opened == []
    with qtbot.waitSignal(d.hashingFinished, timeout=10_000):
        d.ok_button.click()
    assert sorted(opened) == sorted(d.files)


def test_open_hashes_every_file(dlg, qtbot):
    with qtbot.waitSignals([dlg.hashingProgress, dlg.hashingFinished],
                           timeout=10_000):
        dlg.ok_button.click()
    assert set(dlg.evidence_set.hashes) == set(dlg.files)


def test_the_recovery_box_is_outside_the_scrolling_list(dlg):
    assert not dlg.scroll_area.isAncestorOf(dlg.recover_box)


def test_escape_cancels_without_hashing(dlg, qtbot):
    from PySide6.QtTest import QTest
    QTest.keyClick(dlg, Qt.Key_Escape)
    qtbot.waitUntil(lambda: not dlg.isVisible(), timeout=2000)
    assert dlg.evidence_set is None


def test_paths_are_copyable_and_never_openable(dlg):
    actions = [a.text().lower() for a in dlg.path_actions()]
    assert any("copy" in a for a in actions)
    assert not any("open" in a for a in actions)
    assert dlg.list.contextMenuPolicy() == Qt.ActionsContextMenu


def test_copy_path_action_actually_copies_to_clipboard(dlg):
    item = dlg.list.item(0)
    dlg.list.setCurrentItem(item)
    next(a for a in dlg.path_actions() if "copy" in a.text().lower()).trigger()
    assert QGuiApplication.clipboard().text() == item.text()


def test_a_missing_database_is_reported_not_raised(qtbot, tmp_path):
    d = OpenEvidenceDialog(str(tmp_path / "nothing.dat"))
    qtbot.addWidget(d)
    assert "does not exist" in d.intro_text().lower()
    assert not d.ok_button.isEnabled()


def test_a_directory_is_reported_distinctly_from_a_missing_file(qtbot,
                                                                tmp_path):
    d = OpenEvidenceDialog(str(tmp_path))
    qtbot.addWidget(d)
    assert "directory" in d.intro_text().lower()


def test_cancelling_mid_hash_does_not_accept(monkeypatch, dlg, qtbot):
    import threading
    from webcache.provenance import EvidenceSet
    release = threading.Event()
    real_from_paths = EvidenceSet.from_paths

    def slow_from_paths(cls, paths, should_stop=None, on_bytes=None):
        release.wait(5)
        return real_from_paths(paths)

    monkeypatch.setattr(EvidenceSet, "from_paths", classmethod(slow_from_paths))
    dlg.ok_button.click()
    qtbot.waitUntil(lambda: dlg._worker is not None and dlg._worker.isRunning(),
                    timeout=2_000)
    worker = dlg._worker
    dlg.reject()
    assert dlg.result() == QDialog.Rejected
    release.set()
    qtbot.waitUntil(lambda: _worker_finished(worker), timeout=5_000)
    qtbot.wait(100)
    assert dlg.evidence_set is None


def test_from_paths_stops_early_when_told_to(evidence):
    from webcache.engine.ese_parser import evidence_scope
    from webcache.provenance import EvidenceSet
    files = evidence_scope(str(evidence))
    calls = []

    def should_stop():
        calls.append(1)
        return len(calls) > 2

    result = EvidenceSet.from_paths(files, should_stop=should_stop)
    assert 0 < len(result.hashes) < len(files)
    assert set(result.hashes) == set(result.files)


def test_cancelling_mid_hash_is_safe_to_destroy(monkeypatch, evidence, qtbot):
    import threading
    from PySide6.QtCore import qInstallMessageHandler
    d = OpenEvidenceDialog(str(evidence))
    d.show()
    qtbot.waitExposed(d)
    files = d.files
    release = threading.Event()
    reached = threading.Event()
    real_open = builtins.open

    def spy_open(file, *args, **kwargs):
        if str(file) == files[1]:
            reached.set()
            release.wait(5)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    messages = []
    old = qInstallMessageHandler(lambda *args: messages.append(args[-1]))
    try:
        d.ok_button.click()
        qtbot.waitUntil(reached.is_set, timeout=5_000)
        worker = d._worker
        d.reject()
        d.deleteLater()
        qtbot.wait(100)
        release.set()
        qtbot.waitUntil(lambda: _worker_finished(worker), timeout=5_000)
        qtbot.wait(50)
    finally:
        qInstallMessageHandler(old)
    assert not [m for m in messages
                if "Destroyed while thread is still running" in m]


# --- the gates are gone, the guarantees are not -----------------------

def test_the_main_window_has_no_consent_dialog_left():
    assert not hasattr(mw, "ConsentDialog")
    assert not hasattr(mw, "PositionExportConsentDialog")


def test_the_first_run_screen_makes_no_consent_promise():
    words = " ".join(h + " " + b for _g, h, b in first_run._PROMISES).lower()
    assert "consent" not in words and "authoris" not in words


def test_the_first_run_drop_cards_own_body_makes_no_consent_promise(qtbot):
    """The three _PROMISES cards said the right thing,
    but the drop card's own body text above them still said "nothing is
    read until you confirm you are authorised" -- the exact "you consent
    first" promise removes."""
    from PySide6.QtWidgets import QLabel
    view = first_run.FirstRunView()
    qtbot.addWidget(view)
    labels = [w.text().lower() for w in view.findChildren(QLabel)]
    assert not any("authoris" in t or "consent" in t for t in labels)
    body = next(t for t in labels if "webcachev01.dat" in t)
    assert "recover deleted records" in body
    assert "never written" in body


def test_the_case_file_records_what_was_opened_its_hash_and_when(tmp_path):
    from webcache.provenance import EvidenceSet
    path = str(tmp_path / "exhibit.dat")
    digest = "ab" * 32
    ev = EvidenceSet([path], {path: 14}, {path: digest})
    case = case_store.open_case(ev)
    assert case_store.record_open(case, ev) is True
    assert case_store.record_open(case, ev) is True
    log = json.loads(case.get_meta(case_store.OPEN_LOG_META_KEY))
    assert len(log) == 2, "appended, never overwritten"
    assert log[0]["files"] == [{"path": path, "sha256": digest, "bytes": 14}]
    assert log[0]["opened_utc"].endswith("Z")
    case.close()


def test_record_open_without_a_case_file_is_not_an_error():
    assert case_store.record_open(None, None) is False
