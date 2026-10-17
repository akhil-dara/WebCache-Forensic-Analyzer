"""While recovery runs, no surface says it has
not run. The status summary, the History count line, the Deleted Records
badge and the Dashboard's case summary all say it is running -- with the
pages done when the worker has reported them -- and the badge is never a
"0" that reads as "nothing was recovered"."""
import pytest

from webcache.provenance import EvidenceSet
from webcache.shell import dashboard_data
from webcache.shell import main_window as mw
from webcache.shell.main_window import MainWindow
from tests.fixtures import make_rows
from tests.test_dashboard_case_card import _Parser as _CaseParser
from tests.test_recovery_wiring import _DeferredFakeRecoveryLoader, _FakeParser

PROGRESS = "Recovering deleted records: 3 of 10 database pages scanned…"


class _InfoParser(_FakeParser):
    def get_database_info(self):
        return {"db_state_text": "Clean shutdown", "table_count": 2,
                "container_count": 1}


@pytest.fixture
def win(qtbot, monkeypatch):
    _DeferredFakeRecoveryLoader.instances = []
    monkeypatch.setattr(mw, "RecoveryLoader", _DeferredFakeRecoveryLoader)
    w = MainWindow()
    qtbot.addWidget(w)
    parser = _InfoParser("exhibit")
    w._on_evidence_loaded({"rows": make_rows(5), "parser": parser},
                          EvidenceSet([parser.db_path], {parser.db_path: 1},
                                      {parser.db_path: "a" * 64}))
    w._ensure_view_built("history")
    w._start_recovery()
    w._on_recovery_progress(PROGRESS)
    return w


def test_the_status_summary_says_recovery_is_running(win):
    text = win._db_summary_label.text()
    assert "recovery not run" not in text
    assert "recovery running (3 of 10 pages)" in text


def test_the_history_count_line_says_recovery_is_running(win):
    # The note may sit on the count line (short) or its own row (long).
    line = win._built_widget("history").line_text()
    assert "not yet recovered" not in line
    assert "recovery running" in line


def test_the_deleted_records_badge_is_never_a_zero_while_running(win):
    row = win.sidebar._rows["recovery"]
    assert row.count_label.text() != "0"
    assert "recovery running" in row.toolTip()


def test_the_case_summary_says_running():
    try:
        rows = dict(dashboard_data.case_summary(_CaseParser(), None,
                                                recovery_state="running"))
    except TypeError:
        rows = dict(dashboard_data.case_summary(_CaseParser(), None))
    assert rows["Recovery"].startswith("Running")
    assert "not run" not in rows["Activity covers"]


def test_after_the_scan_the_state_says_it_ran(win):
    from tests.test_recovery_wiring import _FakeEngine
    _DeferredFakeRecoveryLoader.instances[-1].finish_now(_FakeEngine())
    assert "recovery running" not in win._db_summary_label.text()
    assert win.sidebar._rows["recovery"].count_label.text() == "0"


def test_the_dashboard_badge_does_not_say_not_run_while_running(win):
    assert "recovery not run" not in win.sidebar._rows["dashboard"].toolTip()
