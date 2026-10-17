"""As the application actually searches: the
Search worker opens its OWN parser and never parses entries, so the
exhibit's recovered zone and each MSHist record's own offset must travel
with the query. Without them the worker's reading of an MSHist
ModifiedTime was "no UTC: no time zone was recovered" on an exhibit whose
zone had been recovered."""
from webcache.provenance import EvidenceSet
from webcache.shell import search_runner
from webcache.shell.evidence_loader import history_rows_from_parser
from webcache.shell.main_window import MainWindow
from tests.test_mshist_clock_everywhere import (LOCAL_TEXT, UTC_TEXT,
                                                _with_columns)
from tests.test_mshist_local_clock import build_parser


def _fresh_open():
    """What the worker gets: the same tables, freshly opened -- no entries
    parsed, so no zone and no stamped offsets."""
    parser = _with_columns(build_parser())
    parser.all_entries = []
    parser.derived_tz_offset_seconds = None
    parser.open = lambda *a, **k: None
    parser.close = lambda: None
    return parser


def test_the_worker_reads_an_mshist_time_on_the_exhibits_clock(qtbot,
                                                               monkeypatch):
    parsed = build_parser()
    parsed.db_path = "C:/case/WebCacheV01.dat"
    win = MainWindow()
    qtbot.addWidget(win)
    win._on_evidence_loaded(
        {"rows": history_rows_from_parser(parsed), "parser": parsed},
        EvidenceSet([parsed.db_path], {parsed.db_path: 1},
                    {parsed.db_path: "a" * 64}))
    monkeypatch.setattr(search_runner.ese_parser, "WebCacheParser",
                        _fresh_open)
    query = win._search_query_for(LOCAL_TEXT, "Container_2")
    worker = search_runner.SearchWorker(query)
    got = []
    worker.found.connect(lambda q, payload: got.append(payload))
    worker.run()
    rows = got[0]["rows"]
    decoded = [r["_result"]["row"]["ModifiedTime"] for r in rows
               if "ModifiedTime" in r["_result"]["matched_columns"]]
    assert decoded, "the local digits did not hit ModifiedTime"
    assert decoded[0].startswith("local: %s" % LOCAL_TEXT), decoded[0]
    assert "UTC (derived, UTC+05:30): %s" % UTC_TEXT in decoded[0], decoded[0]
    assert "recovered zone" not in decoded[0]
