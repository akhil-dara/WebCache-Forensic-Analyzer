"""The signed PDF report, read back from its own bytes.

Found by exporting a real exhibit and reading the file an analyst would
print: 108 pages with no page numbers and nothing on any page that tied
it to its case or exhibit, an Author of "(anonymous)", and a creation
date stamped +05'00' on a +05:30 machine -- reportlab computes the
offset's minutes as `gmtoff % 3600 % 60`, which is seconds, so every
half-hour zone is written thirty minutes wrong.

Read without a PDF library: reportlab's content streams are ASCII85
then zlib (/ASCII85Decode /FlateDecode), and the info dictionary is
plain text.
"""
import base64
import re
import zlib

import pytest

from webcache.engine import forensic_engine

pytest.importorskip("reportlab")

SHA = "ab" * 32


def _entries(n):
    return [{"Url": "http://example.test/%d" % i,
             "CleanUrl": "http://example.test/%d" % i,
             "ContainerType": "History", "ContainerName": "History",
             "AccessedTime": "2026-02-17T16:50:09Z",
             "AccessedTime_raw": 133843382090000000,
             "AccessCount": 1, "EntryId": i, "ContainerId": 3}
            for i in range(n)]


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("pdf") / "report.pdf")
    engine = forensic_engine.ForensicEngine()
    entries = _entries(400)
    engine.load_entries(entries)
    engine.export_pdf_report(
        entries, engine.get_statistics(), path,
        {"examiner": "J. Examiner", "case_number": "CASE-7"},
        {"path": "C:/x/WebCacheV01.dat", "sha256": SHA})
    return open(path, "rb").read()


def _page_texts(raw):
    texts = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        data = m.group(1).strip()
        if data.endswith(b"~>"):
            data = base64.a85decode(data[:-2])
        try:
            data = zlib.decompress(data)
        except zlib.error:
            pass
        texts.append(data.decode("latin-1"))
    return [t for t in texts if " Tj" in t or "TJ" in t]


def test_every_page_says_which_page_of_how_many(pdf):
    pages = _page_texts(pdf)
    total = len(pages)
    assert total >= 2, "the fixture must span several pages"
    for n, text in enumerate(pages, 1):
        assert "Page %d of %d" % (n, total) in text, n


def test_every_page_names_its_case_and_exhibit(pdf):
    for text in _page_texts(pdf):
        assert "CASE-7" in text
        assert SHA in text


def test_the_metadata_names_examiner_and_tool(pdf):
    assert b"/Author (J. Examiner)" in pdf
    assert b"/Creator (WebCache Forensic Analyzer" in pdf


def test_the_creation_date_is_stated_in_utc(pdf):
    """UTC, as every other time this report states -- and immune to
    reportlab's half-hour-zone arithmetic."""
    stamp = re.search(rb"/CreationDate \(D:(\d{14})([^)]*)\)", pdf)
    assert stamp is not None
    assert stamp.group(2) in (b"+00'00'", b"Z")
