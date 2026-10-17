"""The transaction logs that belong to a database are named after it.

Every WebCache database ships with its own log family: WebCacheV01.dat
with V01.log, V01#####.log and V01.chk -- and the V16 and V24 databases of
early Windows 8 builds with V16* and V24*. The prefix was hard-coded
"V01", so a V24 database's logs were never listed, hashed or carved, and
nothing said so.

And when no log is beside the database at all, the open dialog says what
that costs: records not yet flushed into the database file live only in
the logs, which is where the newest activity usually is.
"""
from webcache.engine import ese_parser
from webcache.engine.recovery_engine import RecoveryEngine


def _folder(tmp_path, db, *siblings):
    (tmp_path / db).write_bytes(b"x")
    for name in siblings:
        (tmp_path / name).write_bytes(b"x")
    return str(tmp_path / db)


def test_the_log_prefix_is_read_from_the_database_name():
    assert ese_parser.log_prefix(r"C:\x\WebCacheV01.dat") == "V01"
    assert ese_parser.log_prefix(r"C:\x\WebCacheV24.dat") == "V24"
    assert ese_parser.log_prefix(r"C:\x\webcachev16.dat") == "V16"
    assert ese_parser.log_prefix(r"C:\x\copy-of-cache.dat") == "V01"


def test_a_v24_database_brings_its_own_logs(tmp_path):
    db = _folder(tmp_path, "WebCacheV24.dat", "V24.log", "V2400012.log",
                 "V24.chk", "V01.log")
    scope = [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
             for p in ese_parser.evidence_scope(db)]
    assert scope == ["WebCacheV24.dat", "V24.chk", "V24.log", "V2400012.log"]
    logs = RecoveryEngine().find_log_files(db)
    assert sorted(p.replace("\\", "/").rsplit("/", 1)[-1] for p in logs) == [
        "V24.log", "V2400012.log"]


def test_the_open_dialog_warns_when_no_log_is_beside_the_database(
        qtbot, tmp_path):
    from webcache.shell.open_evidence import NO_LOGS_NOTE, OpenEvidenceDialog
    dlg = OpenEvidenceDialog(_folder(tmp_path, "WebCacheV01.dat"))
    qtbot.addWidget(dlg)
    assert dlg.no_logs_label.text() == NO_LOGS_NOTE
    assert not dlg.no_logs_label.isHidden()
    # In the dialog itself, not a stray top-level label.
    assert dlg.isAncestorOf(dlg.no_logs_label)
    assert "only in" in NO_LOGS_NOTE and "not read" in NO_LOGS_NOTE


def test_no_warning_when_the_logs_are_there(qtbot, tmp_path):
    from webcache.shell.open_evidence import OpenEvidenceDialog
    dlg = OpenEvidenceDialog(_folder(tmp_path, "WebCacheV01.dat", "V01.log"))
    qtbot.addWidget(dlg)
    assert dlg.no_logs_label.isHidden()


# --- a file that cannot be read -------------------------------------------

def test_a_locked_file_is_explained_and_the_dialog_comes_back(
        qtbot, tmp_path, monkeypatch):
    """On a running system Windows holds WebCacheV01.dat open. Reading it
    raised inside the hashing thread, which then ended without a word:
    the dialog stayed on "Hashing" with every control disabled, forever.
    It now says what happened and what to do, and can be used again."""
    from webcache import provenance
    from webcache.shell import consent
    from webcache.shell.open_evidence import OpenEvidenceDialog

    def locked(*_a, **_k):
        raise PermissionError(
            13, "The process cannot access the file because it is being "
                "used by another process")
    monkeypatch.setattr(provenance.EvidenceSet, "from_paths",
                        classmethod(lambda cls, *a, **k: locked()))
    dlg = OpenEvidenceDialog(_folder(tmp_path, "WebCacheV01.dat", "V01.log"))
    qtbot.addWidget(dlg)
    dlg.ok_button.click()
    qtbot.waitUntil(lambda: dlg.ok_button.isEnabled(), timeout=5000)
    said = dlg._progress_label.text()
    assert "in use" in said
    # A statement of what happened, not advice on how to collect.
    assert "shadow" not in said.lower() and "copy" not in said.lower()
    assert dlg.result() == 0, "nothing was opened"


def test_the_explanation_names_the_cause_for_each_kind():
    from webcache.shell.consent import open_failure_text
    locked = open_failure_text(PermissionError(
        13, "being used by another process"))
    assert "in use" in locked and "shadow" not in locked
    missing = open_failure_text(FileNotFoundError(2, "No such file"))
    assert "no longer there" in missing
    other = open_failure_text(OSError(5, "Device not ready"))
    assert "Device not ready" in other
