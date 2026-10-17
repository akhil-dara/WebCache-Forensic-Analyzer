"""The Open dialog says what each file beside the database is, lets the
examiner choose which of them are read, and the choice binds: an unticked
file is neither hashed nor read by recovery."""
import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView

from webcache.engine.ese_parser import evidence_scope
from webcache.engine.recovery_engine import RecoveryEngine
from webcache.shell.open_evidence import OpenEvidenceDialog, role_of


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


def _name(path):
    return os.path.basename(path)


def test_every_file_says_what_it_is(dlg, evidence):
    roles = {_name(p): role_of(p, str(evidence)) for p in dlg.candidates}
    assert "chose" in roles["WebCacheV01.dat"].lower()
    assert "transaction log" in roles["V01.log"].lower()
    assert "transaction log" in roles["V0100123.log"].lower()
    assert "checkpoint" in roles["V01.chk"].lower()
    for row in dlg.rows:
        assert row.role_label.text() == role_of(row.path, str(evidence))


def test_the_folder_is_named_once_and_rows_show_names(dlg, evidence):
    assert dlg.folder_label.text().endswith(str(evidence.parent))
    for row in dlg.rows:
        assert row.name_label.text() == _name(row.path)


def test_everything_is_ticked_by_default_and_the_database_cannot_be_unticked(dlg, evidence):
    assert sorted(dlg.files) == sorted(evidence_scope(str(evidence)))
    db_row = next(r for r in dlg.rows if r.path == str(evidence))
    assert db_row.box.isChecked() and not db_row.box.isEnabled()


def test_an_unticked_file_is_not_hashed(dlg, qtbot, evidence):
    log_row = next(r for r in dlg.rows if _name(r.path) == "V0100123.log")
    log_row.box.setChecked(False)
    assert log_row.path not in dlg.files
    dlg.ok_button.click()
    qtbot.waitUntil(lambda: dlg.evidence_set is not None, timeout=5000)
    assert log_row.path not in dlg.evidence_set.hashes
    assert set(dlg.evidence_set.hashes) == set(dlg.files)


def test_none_keeps_only_the_database_and_all_brings_everything_back(dlg, evidence):
    dlg.none_button.click()
    assert dlg.files == [str(evidence)]
    assert "not read" in dlg.scope_note.text().lower()
    dlg.all_button.click()
    assert sorted(dlg.files) == sorted(dlg.candidates)


def test_clicking_anywhere_on_a_row_toggles_it(dlg, qtbot):
    row = next(r for r in dlg.rows if _name(r.path) == "V01.chk")
    qtbot.mouseClick(row.name_label, Qt.LeftButton)
    assert not row.box.isChecked()
    qtbot.mouseClick(row, Qt.LeftButton)
    assert row.box.isChecked()


def test_rows_are_never_selected_so_a_click_leaves_no_tint(dlg):
    assert dlg.list.selectionMode() == QAbstractItemView.NoSelection


def test_the_summary_states_how_many_files_and_bytes_will_be_read(dlg, evidence):
    total = sum(os.path.getsize(p) for p in dlg.candidates)
    assert dlg.summary_label.text().startswith("4 of 4 files")
    assert ("%d B" % total) in dlg.summary_label.text()
    next(r for r in dlg.rows if _name(r.path) == "V01.log").box.setChecked(False)
    assert dlg.summary_label.text().startswith("3 of 4 files")


# --- recovery reads only what was chosen -----------------------------------

def test_recovery_reads_only_the_logs_that_were_chosen(evidence):
    engine = RecoveryEngine()
    logs = engine.find_log_files(str(evidence), allowed_names={"V01.log"})
    assert [_name(p) for p in logs] == ["V01.log"]
    engine.carve_transaction_logs(str(evidence), set(),
                                  allowed_names={"WebCacheV01.dat", "V01.log"})
    assert engine.checkpoint == {}          # V01.chk was not chosen: not read
    said = " ".join(engine.decision_log).lower()
    assert "v0100123.log" in said and "v01.chk" in said and "not chosen" in said


def test_logs_left_out_are_never_reported_as_missing(evidence):
    """With every log left out, the log said "Not chosen at open, so not
    read: V01.log" and then "No V01*.log transaction logs found next to the
    database" -- a collection gap that did not exist, in the Integrity
    record an examiner hands over."""
    engine = RecoveryEngine()
    engine.carve_transaction_logs(str(evidence), set(),
                                  allowed_names={"WebCacheV01.dat"})
    said = " ".join(engine.decision_log)
    assert "found next to the database" not in said, said
    assert any(line.startswith("No V01*.log") and "not chosen" in line
               for line in engine.decision_log), engine.decision_log


def test_no_logs_at_all_is_still_reported_as_missing(tmp_path):
    db = tmp_path / "WebCacheV01.dat"
    db.write_bytes(bytes(16))
    engine = RecoveryEngine()
    engine.carve_transaction_logs(str(db), set(),
                                  allowed_names={"WebCacheV01.dat"})
    assert any("found next to the database" in line
               for line in engine.decision_log), engine.decision_log


def test_recovery_with_no_choice_reads_every_sibling_as_before(evidence):
    engine = RecoveryEngine()
    assert {_name(p) for p in engine.find_log_files(str(evidence))} == {
        "V01.log", "V0100123.log"}


def test_a_short_file_list_shows_no_scrollbar(dlg, qtbot):
    """Every file of an ordinary exhibit is on screen at once -- and the
    list says so: a scrollbar beside three fully visible files (seen on a
    real machine) reads as more files below."""
    dlg.show()
    qtbot.waitExposed(dlg)
    assert dlg.list.verticalScrollBar().maximum() == 0
    assert dlg.scroll_area.verticalScrollBar().maximum() == 0


def test_a_long_file_list_scrolls_in_one_place(tmp_path, qtbot):
    for i in range(12):
        (tmp_path / ("V01%05d.log" % i)).write_bytes(b"log")
    (tmp_path / "WebCacheV01.dat").write_bytes(b"db")
    d = OpenEvidenceDialog(str(tmp_path / "WebCacheV01.dat"))
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    assert d.list.verticalScrollBar().maximum() == 0
    assert d.scroll_area.verticalScrollBar().maximum() > 0
