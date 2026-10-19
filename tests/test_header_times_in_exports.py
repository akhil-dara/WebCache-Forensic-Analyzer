"""The database header's own times travel with every export.

The Integrity screen states when the database was created, last opened
and last cleanly closed; a report is built from the exports, whose
provenance header and PDF said only "Dirty shutdown"."""
import datetime as dt

import pytest

from webcache.engine import forensic_engine as fe

UTC = dt.timezone.utc
TIMES = {
    "created": dt.datetime(2025, 6, 21, 15, 41, 50, 193000, tzinfo=UTC),
    "last_attach": dt.datetime(2026, 2, 17, 15, 34, 33, 833000, tzinfo=UTC),
    "last_consistent": dt.datetime(2026, 2, 16, 17, 19, 33, 738000,
                                   tzinfo=UTC),
    "last_detach": None, "last_repair": None, "repair_count": 0,
}
DB_INFO = {"path": "C:/case/WebCacheV01.dat", "db_state_text": "Dirty shutdown",
           "header_times": TIMES}


def test_every_exports_provenance_header_carries_them():
    header = fe.ForensicEngine().build_report_header({}, DB_INFO)
    times = header["database_header_times"]
    assert times["last_attach"] == "2026-02-17T15:34:33.833Z"
    assert times["last_consistent"] == "2026-02-16T17:19:33.738Z"
    assert times["created"] == "2025-06-21T15:41:50.193Z"
    assert times["last_detach"] is None
    assert times["repair_count"] == 0


def test_the_pdf_states_them_beside_the_database_state(tmp_path):
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    entries = [{"Url": "http://example.test/1", "CleanUrl": "http://example.test/1",
                "ContainerType": "History", "AccessedTime_raw": 133843382090000000,
                "AccessCount": 1, "EntryId": 1, "ContainerId": 3}]
    engine = fe.ForensicEngine()
    engine.load_entries(entries)
    path = str(tmp_path / "r.pdf")
    engine.export_pdf_report(entries, engine.get_statistics(), path, {}, DB_INFO)
    text = " ".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages)
    for line in ("Last opened (header)", "2026-02-17 15:34:33.833 UTC",
                 "Last clean close (header)", "2026-02-16 17:19:33.738 UTC",
                 "Never (repair count 0)"):
        assert line in text, line
