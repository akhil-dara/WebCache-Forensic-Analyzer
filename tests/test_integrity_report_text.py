"""The Integrity screen as a text report: copied or saved, every value in
full. The screen's cards could only be selected one label at a time, and
the decision log not at all."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from webcache import provenance
from webcache.shell import integrity_loader
from webcache.views.integrity import IntegrityView


def _info():
    return {
        "path": r"C:\case\WebCacheV01.dat",
        "db_state_text": "Dirty shutdown",
        "derived_tz": "UTC+05:30",
        "parse_stats": {"parsed": 610, "skipped": 1, "errors": 0},
        "total_entries": 600,
        "source_hashes": {"WebCacheV01.dat": "a" * 64, "V01.log": "b" * 64},
        "decision_log": ["Opened read-only: WebCacheV01.dat",
                         "SomeTable: SKIPPED — permission denied"],
    }


def test_the_report_carries_every_section_in_full():
    text = integrity_loader.report_text(_info(), "2026-10-01T09:00:00Z")
    assert provenance.TOOL_VERSION in text
    assert "Generated (UTC): 2026-10-01T09:00:00Z" in text
    assert r"C:\case\WebCacheV01.dat" in text
    for heading in ("SOURCE INTEGRITY", "CLOCK", "SHA-256 SOURCE HASHES",
                    "PARSING DECISION LOG"):
        assert heading in text
    assert "a" * 64 in text and "b" * 64 in text
    assert "Database state" in text and "Dirty shutdown" in text
    assert "  Opened read-only: WebCacheV01.dat" in text
    # A flagged line is marked, so it survives being pasted as plain text.
    assert "! SomeTable: SKIPPED — permission denied" in text


def test_copy_report_puts_the_whole_report_on_the_clipboard(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info())
    assert v.copy_report_button.isEnabled()
    v.copy_report_button.click()
    copied = QApplication.clipboard().text()
    assert "a" * 64 in copied and "PARSING DECISION LOG" in copied


def test_save_asks_the_shell_with_the_report_text(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info())
    with qtbot.waitSignal(v.saveTextRequested) as sig:
        v.save_report_button.click()
    assert "b" * 64 in sig.args[0]


def test_nothing_to_copy_before_evidence_is_open(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    assert not v.copy_report_button.isEnabled()
    assert not v.save_report_button.isEnabled()


def test_decision_log_lines_can_be_selected_and_copied(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info())
    log = v._log_list
    log.item(0).setSelected(True)
    log.item(1).setSelected(True)
    log.setFocus()
    qtbot.keyClick(log, Qt.Key_C, Qt.ControlModifier)
    assert QApplication.clipboard().text() == (
        "Opened read-only: WebCacheV01.dat\n"
        "SomeTable: SKIPPED — permission denied")


def test_the_shell_saves_the_report_where_the_examiner_chose(
        qtbot, tmp_path, monkeypatch):
    import webcache.paths as paths
    monkeypatch.setattr(paths, "settings_path", lambda: tmp_path / "s.json")
    from webcache.shell.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    target = tmp_path / "integrity.txt"
    monkeypatch.setattr(w, "_choose_export_path",
                        lambda suggested, title, nf: str(target))
    w._save_integrity_text("REPORT\nline")
    assert target.read_text(encoding="utf-8-sig") == "REPORT\nline"
    assert "integrity.txt" in w.status_message()
