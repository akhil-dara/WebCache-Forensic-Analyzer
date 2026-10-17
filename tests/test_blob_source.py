"""Where a viewer's bytes come from -- and the fact that it never knows.

BlobSource is one interface with two implementations so that
widgets/hex_view.py can page, decode, hash and export bytes without ever
learning whether they came out of a parsed database column or were read
back off the disk a moment ago. That is not tidiness: widgets/ may not
import the engine at all (tests/test_structure.py), and a hex pane that
had to ask ese_parser what a blob was could not live there.

The two properties this file pins hardest:

  * A MemoryBlob wraps the EXISTING bytes object. Unit 1's whole memory
    argument -- carry the reference, never the copy -- ends here if the
    viewer duplicates 379 KB the moment a dialog opens.
  * base_offset is 0 for a blob and the window start for a file window,
    which is what makes hex_view print an offset an examiner can seek to.
"""
import datetime
import hashlib
import os

import pytest

from webcache import provenance
from webcache.engine import blob_reader, carve_reader
from webcache.shell import blob_source
from webcache.shell.record_kinds import K_CARVED_STRING

from tests.test_detail_fields import (carved_string_row, carved_struct_row,
                                      cert_row, cookie_row, history_row)

UTC = datetime.timezone.utc


@pytest.fixture
def exhibit(tmp_path):
    path = tmp_path / "WebCacheV01.dat"
    path.write_bytes(bytes(range(256)) * 64)
    return str(path)


# --- MemoryBlob ---------------------------------------------------------

def test_a_memory_blob_wraps_the_existing_bytes_and_never_copies_them():
    """Identity, not equality. Unit 1 carries every blob by reference
    through _record precisely so that 379 KB of response headers is a
    pointer; a viewer that copied on construction would undo it."""
    data = b"1SPS" + b"\x00" * 4000
    src = blob_source.MemoryBlob("Response headers", data, "ResponseHeaders_raw")
    assert src.all_bytes() is data
    assert src.size == len(data)
    assert src.base_offset == 0


def test_a_memory_blob_hashes_the_bytes_as_extracted():
    data = b"\x30\x82" + b"\x00" * 200
    src = blob_source.MemoryBlob("Certificate blob (DER)", data, "Blob_raw")
    assert src.sha256 == hashlib.sha256(data).hexdigest()


def test_a_memory_blob_detects_its_type_from_the_bytes_not_the_label():
    """A column that is supposed to hold headers and actually holds a PNG
    says PNG. That is how a mislabelled column gets caught."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    src = blob_source.MemoryBlob("Response headers", png, "ResponseHeaders_raw")
    assert "PNG" in src.detected_type


def test_a_memory_blob_reads_a_slice_without_materialising_the_whole():
    data = bytes(range(256))
    src = blob_source.MemoryBlob("x", data, "k")
    assert src.read(16, 4) == data[16:20]
    assert src.read(250, 100) == data[250:]


def test_a_memory_blob_pages_hex_at_blob_offsets():
    src = blob_source.MemoryBlob("x", bytes(8192), "k")
    assert src.hex_page(0)[0].startswith("00000000")
    assert src.hex_page(4096)[0].startswith("00001000")


def test_a_memory_blob_states_where_its_bytes_came_from():
    src = blob_source.MemoryBlob("Request headers", b"abcd", "RequestHeaders_raw")
    assert "RequestHeaders_raw" in src.origin_note
    assert src.origin_note.strip().endswith(".")


def test_a_memory_blob_suggests_a_filename_safe_on_any_filesystem():
    src = blob_source.MemoryBlob("Response headers / property store",
                                 b"abcd", "ResponseHeaders_raw")
    name = src.suggested_filename()
    assert name.endswith(".bin")
    assert all(c.isalnum() or c in "_.-" for c in name)


def test_a_memory_blob_decodes_and_extracts_strings_lazily_and_once():
    data = b"HTTP/1.1 200 OK\r\nX-Test: marker-string\r\n\r\n"
    src = blob_source.MemoryBlob("Response headers", data, "ResponseHeaders_raw")
    assert src.decode_lines() is src.decode_lines()
    assert src.strings() is src.strings()
    assert any("marker-string" in t for _o, _e, t in src.strings())


# --- FileWindowBlob -----------------------------------------------------

def test_a_file_window_blob_prints_true_file_offsets(exhibit):
    src = blob_source.FileWindowBlob(
        "Bytes at the carve offset", exhibit, None, 8200)
    assert src.base_offset == src.window_start
    assert src.window_start % 16 == 0
    assert src.hex_page(0)[0].startswith("%08X" % src.window_start)


def test_a_file_window_blob_reads_the_evidence_at_construction(exhibit):
    src = blob_source.FileWindowBlob("Bytes", exhibit, None, 4096)
    with open(exhibit, "rb") as fh:
        fh.seek(src.window_start)
        assert src.all_bytes() == fh.read(len(src.all_bytes()))


def test_a_file_window_blob_carries_the_standing_verification_statement(exhibit):
    """The sentence that changes what can be testified to."""
    src = blob_source.FileWindowBlob("Bytes", exhibit, None, 4096)
    assert "read back from the evidence" in src.verification_statement
    assert "written to" in src.verification_statement
    assert "hex editor" in src.verification_statement


def test_a_file_window_blob_header_names_the_file_the_offset_and_the_window(
        exhibit):
    src = blob_source.FileWindowBlob("Bytes", exhibit, None, 8200)
    rows = src.header_rows()
    labels = [label for label, _value, _copy in rows]
    assert "Source file" in labels
    assert "Record offset" in labels
    assert "Window shown" in labels
    by_label = {label: (value, copy) for label, value, copy in rows}
    assert "8,200" in by_label["Record offset"][0]
    assert "0x00002008" in by_label["Record offset"][0]
    # The copy text is the bare hex, so it pastes straight into a seek box.
    assert by_label["Record offset"][1] == "0x00002008"
    assert os.path.basename(exhibit) == by_label["Source file"][1]


def test_a_file_window_blob_names_its_export_after_where_it_came_from(exhibit):
    src = blob_source.FileWindowBlob("Bytes", exhibit, None, 8200)
    assert src.suggested_filename() == "carve_00002008.bin"


def test_a_file_window_blob_offers_no_structured_decode(exhibit):
    """A raw window has no reading. It says so rather than running the
    download decoder over arbitrary bytes and reporting on the result."""
    src = blob_source.FileWindowBlob("Bytes", exhibit, None, 4096)
    assert src.decode_lines() == [blob_reader.NO_DECODE]


def test_a_file_window_blob_still_offers_its_strings(exhibit, tmp_path):
    path = tmp_path / "V01.log"
    path.write_bytes(b"\x00" * 64 + b"recoverable-text" + b"\x00" * 64)
    src = blob_source.FileWindowBlob("Bytes", str(tmp_path / "WebCacheV01.dat"),
                                     "V01.log", 64)
    assert any("recoverable-text" in t for _o, _e, t in src.strings())


def test_a_failed_read_is_a_source_that_says_why_not_one_that_is_missing(
        exhibit):
    """C2 again: the tab still opens, and it states the cause."""
    src = blob_source.FileWindowBlob("Bytes", exhibit, None, None)
    assert src.size == 0
    assert "no source offset" in src.note
    assert src.hex_page(0) == []


# --- verifying the exhibit has not changed ------------------------------

def test_verify_reports_unchanged_when_the_file_still_matches(exhibit):
    digest = hashlib.sha256(open(exhibit, "rb").read()).hexdigest()
    evidence = provenance.EvidenceSet([exhibit],
                                      {exhibit: os.path.getsize(exhibit)},
                                      {exhibit: digest})
    src = blob_source.FileWindowBlob("Bytes", exhibit, None, 4096,
                                     evidence_set=evidence)
    assert src.verify_supported
    assert "unchanged since it was opened" in src.verify()


def test_verify_reports_the_change_when_the_file_has_moved_under_us(exhibit):
    """Evidence should not change under an examiner. If it has, that is
    reportable, not something to paper over."""
    evidence = provenance.EvidenceSet([exhibit],
                                      {exhibit: os.path.getsize(exhibit)},
                                      {exhibit: "0" * 64})
    src = blob_source.FileWindowBlob("Bytes", exhibit, None, 4096,
                                     evidence_set=evidence)
    assert "changed since it was opened" in src.verify()


def test_verify_says_it_cannot_rather_than_claiming_a_pass(exhibit):
    src = blob_source.FileWindowBlob("Bytes", exhibit, None, 4096)
    assert not src.verify_supported
    assert src.verify().strip()
    assert "unchanged" not in src.verify()


# --- blobs_for ----------------------------------------------------------

def test_a_history_record_offers_its_response_headers():
    blobs = blob_source.blobs_for(history_row())
    assert [b.field_key for b in blobs] == ["ResponseHeaders_raw"]
    assert blobs[0].all_bytes() is history_row()["_record"]["ResponseHeaders_raw"] \
        or blobs[0].size == 64


def test_a_certificate_offers_its_der_blob():
    row = cert_row()
    blobs = blob_source.blobs_for(row)
    assert [b.field_key for b in blobs] == ["Blob_raw"]
    assert blobs[0].all_bytes() is row["_record"]["Blob_raw"]


def test_an_empty_blob_is_skipped_rather_than_shown_as_an_empty_tab():
    row = history_row()
    row["_record"]["ResponseHeaders_raw"] = b""
    assert blob_source.blobs_for(row) == []


def test_a_record_with_no_blobs_offers_none():
    assert blob_source.blobs_for(cookie_row()) == []


def test_a_carved_record_always_offers_the_bytes_at_its_carve_offset(exhibit):
    blobs = blob_source.blobs_for(carved_struct_row(), db_path=exhibit)
    assert any(isinstance(b, blob_source.FileWindowBlob) for b in blobs)
    window = [b for b in blobs if isinstance(b, blob_source.FileWindowBlob)][0]
    assert "carve offset" in window.label.lower()


def test_a_carved_row_without_its_own_offset_still_offers_real_bytes(exhibit):
    """carved_file_access_rows and carved_downloads_rows
    (recovery_loader.py) never copy Offset/Source onto the ROW itself,
    only onto row["_record"] -- unlike carved_history_rows/deleted_
    records_rows, which do. detail_fields._merged_source already falls
    back to _record for exactly this reason, so the field list prints a
    real byte offset while blobs_for(), reading only row.get("Offset")/
    row.get("Source"), handed FileWindowBlob None for both and it read
    nothing back -- the two disagreed within one dialog."""
    row = carved_struct_row()
    assert row["_record"]["Offset"] == 0          # a real, valid offset
    del row["Offset"]
    del row["Source"]
    blobs = blob_source.blobs_for(row, db_path=exhibit)
    windows = [b for b in blobs if isinstance(b, blob_source.FileWindowBlob)]
    assert windows, "no carve window offered at all"
    assert windows[0].size, "carve window read nothing back"


def test_a_carved_string_artifact_offers_the_carve_window_too(exhibit):
    row = carved_string_row()
    assert row["_kind"] == K_CARVED_STRING
    blobs = blob_source.blobs_for(row, db_path=exhibit)
    assert len(blobs) == 1
    assert isinstance(blobs[0], blob_source.FileWindowBlob)


def test_the_carve_window_is_last_so_the_record_s_own_blobs_come_first(exhibit):
    row = carved_struct_row()
    row["_record"]["ResponseHeaders_raw"] = b"1SPS" + b"\x00" * 60
    blobs = blob_source.blobs_for(row, db_path=exhibit)
    assert isinstance(blobs[0], blob_source.MemoryBlob)
    assert isinstance(blobs[-1], blob_source.FileWindowBlob)


def test_without_a_database_path_no_carve_window_is_invented(exhibit):
    """No exhibit open, no claim about what is at an offset in it."""
    blobs = blob_source.blobs_for(carved_string_row(), db_path="")
    assert blobs == []


def test_blobs_for_never_raises_on_a_row_it_does_not_recognise():
    for row in ({}, {"_kind": "nonsense"}, {"_kind": None, "_record": None}):
        assert blob_source.blobs_for(row) == []


# --- the table browser: any binary column of any table ------------------

def test_a_table_browser_cell_becomes_a_blob_labelled_by_its_column():
    """The column-agnostic property, and the most valuable thing the
    viewer does: a binary column nobody wrote a decoder for still gets a
    hex and strings view."""
    columns = ["EntryId", "ResponseHeaders", "Url"]
    cells = [{"type": "int", "text": "5", "raw": None},
             {"type": "bytes", "text": "40 bytes", "raw": b"\x89PNG" + b"\x00" * 36},
             {"type": "str", "text": "https://x", "raw": None}]
    blobs = blob_source.blobs_for_cells(columns, cells)
    assert len(blobs) == 1
    assert blobs[0].label == "ResponseHeaders"
    assert blobs[0].field_key == "ResponseHeaders"
    assert blobs[0].all_bytes() is cells[1]["raw"]


def test_table_browser_cells_with_no_bytes_offer_nothing():
    columns = ["A", "B"]
    cells = [{"type": "int", "text": "1", "raw": None},
             {"type": "str", "text": "x", "raw": None}]
    assert blob_source.blobs_for_cells(columns, cells) == []


# --- one declaration of which blobs a record carries --------------------

def test_the_blob_catalogue_is_declared_once_and_shared_with_detail_fields():
    """The Binary field row and the viewer tab must carry the SAME label,
    because Enter on the row is specified to jump to the tab. Two equal
    lists look identical the day they are written."""
    from webcache.shell import detail_fields
    assert detail_fields.BLOB_FIELDS is blob_source.BLOB_FIELDS


def test_every_catalogued_blob_label_reaches_a_tab_for_a_record_that_has_it():
    row = history_row()
    row["_record"]["RequestHeaders_raw"] = b"GET / HTTP/1.1\r\n"
    labels = [b.label for b in blob_source.blobs_for(row)]
    assert labels == [label for _key, label in blob_source.BLOB_FIELDS
                      if label in labels]
    assert len(labels) == 2


def test_the_page_size_is_not_redeclared_by_the_source(exhibit):
    """widgets/hex_view.py reads page_bytes off the source rather than
    holding its own 4096."""
    src = blob_source.MemoryBlob("x", b"abcd", "k")
    assert src.page_bytes == blob_reader.HEX_PAGE_BYTES
    window = blob_source.FileWindowBlob("Bytes", exhibit, None, 0)
    assert window.page_bytes == blob_reader.HEX_PAGE_BYTES
    assert len(window.all_bytes()) == carve_reader.CARVE_WINDOW
