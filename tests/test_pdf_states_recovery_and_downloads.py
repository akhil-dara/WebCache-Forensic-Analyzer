"""The PDF states whether the recovery scan ran, and how many download
records there were.

With no recovered records listed it said "either the recovery scan was
not run, or it recovered nothing" -- the app knows which -- and told the
reader to run it. And it gave no download count, so a reader could not
tell "no downloads recorded" from "downloads not looked at"."""
import pytest

from webcache.engine import forensic_engine as fe

pytest.importorskip("reportlab")
pypdf = pytest.importorskip("pypdf")

ENTRY = {"Url": "http://example.test/1", "CleanUrl": "http://example.test/1",
         "ContainerType": "History", "AccessedTime_raw": 133843382090000000,
         "AccessCount": 1, "EntryId": 1, "ContainerId": 3}


def _text(tmp_path, entries, **kw):
    engine = fe.ForensicEngine()
    engine.load_entries(entries)
    path = str(tmp_path / "r.pdf")
    engine.export_pdf_report(entries, engine.get_statistics(), path, {}, {},
                             **kw)
    return " ".join(" ".join((p.extract_text() or "").split())
                    for p in pypdf.PdfReader(path).pages)


def test_a_scan_that_ran_and_found_nothing_says_so(tmp_path):
    text = _text(tmp_path, [ENTRY], recovered=[], recovery_scan_run=True)
    assert "The recovery scan was run and recovered no records" in text
    assert "Either the recovery scan was not run" not in text
    assert "run the recovery scan" not in text


def test_a_scan_that_was_not_run_says_so(tmp_path):
    text = _text(tmp_path, [ENTRY], recovered=[], recovery_scan_run=False)
    assert "The recovery scan was not run for this case" in text
    assert "run the recovery scan" not in text


def test_the_download_record_count_is_stated_even_when_none(tmp_path):
    text = _text(tmp_path, [ENTRY])
    assert "Download records (iedownload) 0" in text
    dl = dict(ENTRY, EntryId=2, ContainerType="Downloads")
    assert "Download records (iedownload) 1" in _text(tmp_path, [ENTRY, dl])


def test_the_export_runner_tells_the_pdf_whether_the_scan_ran():
    import inspect
    from webcache.shell import export_runner
    src = inspect.getsource(export_runner.ExportWorker._writer_for)
    assert "recovery_scan_run" in src
