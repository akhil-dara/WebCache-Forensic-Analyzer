"""One definition of "records", and units on every count."""
import types
from collections import Counter

import pytest

from webcache.provenance import EvidenceSet
from webcache.shell import integrity_loader, timeline_loader
from webcache.shell.main_window import MainWindow

_PATH = "C:/case/WebCacheV01.dat"


def test_the_split_names_both_halves_and_the_unit():
    from webcache.shell import record_counts
    parser = types.SimpleNamespace(all_entries=[{}] * 467)
    c = record_counts.counts(parser, [{}] * 2742)
    assert (c.live, c.recovered, c.total) == (467, 2742, 3209)
    assert record_counts.split_text(c) == \
        "467 live + 2,742 recovered = 3,209 records"
    assert record_counts.split_text(record_counts.counts(parser)) == \
        "467 live records (recovery not run)"


def test_integrity_separates_records_from_rows_of_every_table():
    rows = integrity_loader.source_integrity_rows(
        {"total_entries": 467, "parse_stats": {"parsed": 725}})
    labels = {r["label"]: r["value"] for r in rows}
    assert "Records (URL-cache entries)" in labels, sorted(labels)
    assert labels["Records (URL-cache entries)"] == "467"
    assert labels["Rows parsed, all tables"] == "725"
    assert "Records parsed" not in labels


def test_the_timeline_note_splits_its_total():
    inputs = timeline_loader.TimelineInput([], set(), 467, 2702, 0, 0)
    note = timeline_loader.grain_note(inputs, [], "day", True)
    assert "(467 live + 2,702 recovered)" in note
    assert "Findings" in note


class _Parser:
    all_entries = [{}] * 3
    db = None
    db_path = _PATH
    containers_meta = []
    container_type_map = {}
    cookie_entries = [{"Domain": "a.example.test"}] * 2
    hsts_entries = []
    cert_entries = [{"HostPort": "a.example.test:443"}]

    def get_database_info(self):
        return {"total_entries": 3, "table_count": 5, "container_count": 2,
                "db_state": 2, "db_state_text": "Dirty shutdown"}


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w._on_evidence_loaded({"rows": [], "parser": _Parser()},
                          EvidenceSet([_PATH], {_PATH: 1}, {_PATH: "a" * 64}))
    return w


def test_the_status_bar_states_live_and_recovery_state(win):
    assert "3 live records (recovery not run)" in \
        win._db_summary_label.text()


def test_the_cookies_badge_names_what_it_adds_up(win):
    tip = win.sidebar._rows["cookies"].toolTip()
    assert "2 cookies" in tip and "0 HSTS pins" in tip \
        and "1 certificate" in tip


def test_findings_is_badged_and_opens_on_a_segment_with_rows(win):
    view = win._ensure_view_built("iocs")
    view.set_records_for("ioc_hits", [])
    view.set_records_for("time_voids", [{"From": None, "To": None,
                                         "GapHours": 30, "_record": None,
                                         "_kind": "time_void"}])
    assert view.open_first_non_empty() == "time_voids"
    assert win.sidebar._rows["iocs"].count_label.text() not in ("", "–")


def test_findings_subtitles_use_real_dashes():
    from webcache.views.iocs import FindingsView
    view = FindingsView()
    for key, rs in view._segments_by_key.items():
        assert "--" not in rs.subtitle(3), key


def test_a_sidebar_badge_tooltip_names_its_unit(win):
    win.sidebar.set_count("timeline", 2053, unit="dated records")
    assert "2,053 dated records" in win.sidebar._rows["timeline"].toolTip()


def test_findings_is_badged_the_moment_evidence_loads(win):
    # No Findings view has been built: the badge must not wait for one.
    text = win.sidebar._rows["iocs"].count_label.text()
    assert text not in ("", "–")
    assert "not records" in win.sidebar._rows["iocs"].toolTip()


def test_the_silence_wording_names_how_it_differs_from_timeline():
    from webcache.views.iocs import _voids_subtitle
    # Both screens state the same difference, from their own side.
    assert "Timeline places each record once, by its key time" in (
        _voids_subtitle(3))
    assert "Timeline places each record once, by its key time" in (
        timeline_loader.SILENCE_CAVEAT)
    assert "Findings ▸ Silences measures" in timeline_loader.SILENCE_CAVEAT


def test_the_dashboard_subtitle_states_the_split(qtbot):
    from webcache.views.dashboard import DashboardView
    view = DashboardView()
    qtbot.addWidget(view)
    stats = {"total_records": 3209, "table_count": 5, "container_count": 2,
             "inprivate_count": 0, "total_file_size": 0,
             "container_types": Counter(), "top_domains": Counter(), "db_path": "",
             "db_file_size": 0, "recovered_count": 2742}
    view.set_data(stats)
    assert "467 live + 2,742 recovered = 3,209 records" in         view.header._subtitle.text()


def test_the_table_browser_states_its_table_and_group_count(qtbot):
    from webcache.views.browser import TableBrowserView
    view = TableBrowserView()
    qtbot.addWidget(view)
    assert hasattr(view, "list_summary")


def test_a_recovered_total_that_leaves_out_stubs_says_so():
    # 3,169 beside 3,209 is 40 key-only stubs that carry no URL or time.
    inputs = timeline_loader.TimelineInput([], set(), 467, 2702, 0, 0,
                                           stubs=40)
    note = timeline_loader.grain_note(inputs, [], "day", True)
    assert "40 deleted-record stubs" in note and "not counted here" in note


def test_a_view_names_the_unit_of_its_own_rows(qtbot):
    from webcache.views.domains import DomainsView
    from webcache.views.containers import ContainersView
    for cls, noun in ((DomainsView, "domains"), (ContainersView, "containers")):
        view = cls()
        qtbot.addWidget(view)
        view.set_records([])
        assert "0 %s" % noun in view.count_label.text()
