"""The recovery scan's own decisions reach the examiner. They were kept in
the recovery engine and shown nowhere: "No V01*.log transaction logs found
next to the database" (a collection that missed the logs) and "Not chosen
at open, so not read" (files deliberately left out) never appeared, though
each changes how complete the recovered set is."""
from webcache.shell import integrity_loader

INFO = {"decision_log": ["Opened read-only: example.dat (DIRTY shutdown)"]}
RECOVERY = ["No V01*.log transaction logs found next to the database.",
            "Not chosen at open, so not read: V0100123.log, V01.chk.",
            "Structured carve: 12 records reconstructed."]


def _rows(recovery=None):
    info = dict(INFO)
    if recovery is not None:
        info["recovery_log"] = recovery
    return integrity_loader.decision_log_rows(info)


def test_recovery_decisions_follow_the_parser_s_labelled():
    rows = _rows(RECOVERY)
    assert rows[0]["text"] == INFO["decision_log"][0]
    assert [r["text"] for r in rows[1:]] == ["Recovery: " + t for t in RECOVERY]


def test_missing_logs_and_unchosen_files_are_flagged():
    flagged = {r["text"]: r["flagged"] for r in _rows(RECOVERY)}
    assert flagged["Recovery: " + RECOVERY[0]]
    assert flagged["Recovery: " + RECOVERY[1]]
    assert not flagged["Recovery: " + RECOVERY[2]]


def test_before_recovery_there_is_nothing_extra():
    assert [r["text"] for r in _rows()] == INFO["decision_log"]
