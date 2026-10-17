"""As the application actually locates a row in a
large table: the row-locate worker opens its OWN parser and never parses
entries, so the page it builds must still read an MSHist ModifiedTime
with the record's own offset -- the same sentence History and the Table
Browser's own pages print."""
from webcache.provenance import EvidenceSet
from webcache.shell import row_locate_runner, row_locator
from webcache.shell.evidence_loader import history_rows_from_parser
from webcache.shell.main_window import MainWindow
from tests.test_mshist_clock_everywhere import UTC_TEXT
from tests.test_search_worker_clock import _fresh_open
from tests.test_mshist_local_clock import build_parser


def test_a_located_page_reads_mshist_on_the_exhibits_clock(qtbot, monkeypatch):
    parsed = build_parser()
    parsed.db_path = "C:/case/WebCacheV01.dat"
    win = MainWindow()
    qtbot.addWidget(win)
    rows = history_rows_from_parser(parsed)
    win._on_evidence_loaded(
        {"rows": rows, "parser": parsed},
        EvidenceSet([parsed.db_path], {parsed.db_path: 1},
                    {parsed.db_path: "a" * 64}))
    monkeypatch.setattr(row_locate_runner, "open_parser",
                        lambda *a, **k: _fresh_open())
    monkeypatch.setattr(row_locate_runner.RowLocateWorker, "start",
                        lambda self: self.run())
    pages = []
    monkeypatch.setattr(win, "_on_row_located",
                        lambda ref, ordinal, page: pages.append(page))
    mshist_row = next(r for r in rows if r["_record"].get("MSHistFrom"))
    ref = row_locator.source_row(mshist_row)
    win._start_row_locate(ref, win._ensure_view_built("browser"))
    page = pages[0]
    col = page["columns"].index("ModifiedTime")
    decoded = page["rows"][0][col]["decoded"]
    assert decoded.startswith("local: "), decoded
    assert "UTC (derived, UTC+05:30)" in decoded, decoded
    assert "recovered zone" not in decoded
    assert UTC_TEXT[:10] in decoded
