"""Hex, strings and structured decode -- the pure half of the blob viewer.

No Qt at all. Every claim the hex pane makes about a blob is decided here,
which is why it is testable without a QApplication: whether the offset
column can be pasted into another hex editor, whether string #847 is
reachable, and whether a malformed blob takes the pane down with it are
forensic questions, not painting questions.

THE ONE THIS FILE EXISTS FOR is test_hex_lines_print_file_offsets_when_a_
base_offset_is_given. An earlier version printed the index INTO THE
BUFFER, so a 1 KB window carved out of the middle of a database rendered
its rows as 00000000..000003F0 -- congruent to the file's own offsets mod
16, and therefore plausible, and wrong by however far into the file the
window started. An examiner who seeks to 0x00000000 in a hex editor sees
the database header, not the record. The offset column is the entire
reason the pane is evidence rather than decoration.
"""
import re
import struct

from webcache.engine import blob_reader, sps_decoder


# --- building a synthetic property store --------------------------------
#
# [MS-PROPSTORE], the layout sps_decoder.parse_property_store reads:
#   set:    [4-byte size][1SPS][16-byte FMTID][records][4 zero bytes]
#   record: [4-byte size][4-byte id][1 reserved][2-byte VT][2-byte pad][value]

def _record(pid, vt, payload):
    body = struct.pack("<IB", pid, 0) + struct.pack("<HH", vt, 0) + payload
    return struct.pack("<I", 4 + len(body)) + body


def _store(records, fmtid=b"\x01" * 16):
    body = b"1SPS" + fmtid + b"".join(records) + b"\x00\x00\x00\x00"
    one_set = struct.pack("<I", 4 + len(body)) + body
    return struct.pack("<I", len(one_set) + 4) + one_set


def _lpwstr(text):
    raw = text.encode("utf-16-le") + b"\x00\x00"
    return struct.pack("<I", len(text) + 1) + raw


#: Every property id observed on the real exhibits. Two are named by
#: sps_decoder.KNOWN_HISTORY_PROPS; the other six are decoded, stored and
#: shown in the blob reader.
REAL_PROP_IDS = (6, 9, 13, 23, 24, 28, 32, 33)


def sample_store():
    return _store([
        _record(6, sps_decoder.VT_UI4, struct.pack("<I", 4)),
        _record(9, sps_decoder.VT_UI4, struct.pack("<I", 17)),
        _record(13, sps_decoder.VT_UI4, struct.pack("<I", 2)),
        _record(23, sps_decoder.VT_UI4, struct.pack("<I", 1)),
        _record(24, sps_decoder.VT_FILETIME,
                struct.pack("<Q", 133544360420000000)),
        _record(28, sps_decoder.VT_LPWSTR, _lpwstr("Example page")),
        _record(32, sps_decoder.VT_UI4, struct.pack("<I", 0)),
        _record(33, sps_decoder.VT_UI4, struct.pack("<I", 3)),
    ])


# --- hex_lines ----------------------------------------------------------

def test_hex_lines_print_file_offsets_when_a_base_offset_is_given():
    """The regression guard for printed offsets.

    A window read at 0x0001A400 must render its first row AT 0001A400, not
    at 00000000. Anything else is an offset an examiner cannot seek to.
    """
    data = bytes(range(64))
    lines = blob_reader.hex_lines(data, 0, 64, base_offset=0x0001A400)
    assert lines[0].startswith("0001A400")
    assert lines[1].startswith("0001A410")
    assert lines[3].startswith("0001A430")


def test_hex_lines_offsets_advance_from_the_slice_start_not_from_zero():
    """Page 2 of a blob starts at 4096, and says so."""
    data = bytes(8192)
    lines = blob_reader.hex_lines(data, 4096, 4096)
    assert lines[0].startswith("00001000")
    assert lines[-1].startswith("00001FF0")


def test_hex_lines_pad_a_short_final_row_to_alignment():
    """A five-byte tail must not drag its ASCII column sixteen characters
    left of every row above it."""
    lines = blob_reader.hex_lines(b"ABCDE", 0, 5)
    assert len(lines) == 1
    full = blob_reader.hex_lines(b"A" * 16, 0, 16)[0]
    assert lines[0].index("ABCDE") == full.index("A" * 16)


def test_hex_lines_render_unprintable_bytes_as_dots_and_printables_as_themselves():
    line = blob_reader.hex_lines(b"AB\x00\x1f\x7f\xffCD", 0, 8)[0]
    assert line.endswith("AB....CD")
    assert "41 42 00 1F 7F FF 43 44" in line


def test_hex_lines_of_nothing_is_no_lines_not_a_blank_line():
    assert blob_reader.hex_lines(b"", 0, 0) == []


def test_hex_lines_clamp_a_count_that_runs_past_the_end():
    lines = blob_reader.hex_lines(b"A" * 20, 0, 4096)
    assert len(lines) == 2


# --- extract_strings ----------------------------------------------------

def test_extract_strings_finds_utf16le_and_ascii_in_offset_order():
    data = (b"\x00\x00" + "wide-string".encode("utf-16-le")
            + b"\x00\x00" + b"plain-ascii" + b"\x00")
    found = blob_reader.extract_strings(data)
    texts = [t for _o, _e, t in found]
    assert "wide-string" in texts
    assert "plain-ascii" in texts
    encodings = {t: e for _o, e, t in found}
    assert encodings["wide-string"] == "utf-16-le"
    assert encodings["plain-ascii"] == "ascii"
    assert [o for o, _e, _t in found] == sorted(o for o, _e, _t in found)


def test_extract_strings_is_uncapped():
    """5,000 runs in, 5,000 out.

    A cap at 200 pointing the examiner at "Export blob" for the rest would
    fail them -- that exports RAW BYTES, not strings, so string #847 would
    have nowhere at all to be read. On a blob no decoder
    understands the strings pane is the last readable evidence there is.
    """
    data = b"\x00".join(b"str%04d" % i for i in range(5000))
    assert len(blob_reader.extract_strings(data)) == 5000


def test_extract_strings_ignores_runs_shorter_than_the_minimum():
    assert blob_reader.extract_strings(b"\x00abc\x00ab\x00") == []


def test_extract_strings_reports_the_offset_the_run_starts_at():
    data = b"\x00\x00\x00\x00" + b"marker-text"
    assert blob_reader.extract_strings(data)[0][0] == 4


def test_extract_strings_never_raises_on_arbitrary_bytes():
    for data in (b"", b"\xff" * 64, bytes(range(256)) * 4):
        assert isinstance(blob_reader.extract_strings(data), list)


# --- decode_blob_lines --------------------------------------------------

def test_decode_blob_lines_states_the_detected_class_first():
    lines = blob_reader.decode_blob_lines(sample_store())
    assert lines[0] == "Detected class: sps"


def test_decode_blob_lines_enumerates_every_sps_property_not_just_the_named_two():
    """Every id is listed, not just the two KNOWN_HISTORY_PROPS names (6
    and 24)."""
    text = "\n".join(blob_reader.decode_blob_lines(sample_store()))
    for pid in REAL_PROP_IDS:
        assert re.search(r"\bid %d\b" % pid, text), "property id %d missing" % pid


def test_decode_blob_lines_never_invents_a_name_for_an_undocumented_property():
    """sps_decoder documents 6 and 24 only; the other six get the
    stated absence of a meaning, never a plausible-looking guess.

    PREMISE CORRECTED. This first assumed exactly one line mentions each
    id, and took the first match. That is not true and should not be: ids
    6 and 24 are ALSO summarised above the enumeration (the visit count
    and the local-time last visit are the two readings an examiner wants
    without scrolling), so "the first line mentioning id 6" is the
    summary line and says "Visit count", not the catalogue's own
    "VisitCount". The claim worth pinning is about the ENUMERATION -- the
    per-property listing that must cover every id and name none it cannot
    -- so the rows are selected by their own indented shape.
    """
    lines = blob_reader.decode_blob_lines(sample_store())
    enumerated = [ln for ln in lines if ln.startswith("    id ")]
    assert len(enumerated) == len(REAL_PROP_IDS)
    named = set(sps_decoder.KNOWN_HISTORY_PROPS)
    for pid in REAL_PROP_IDS:
        line = [ln for ln in enumerated
                if re.search(r"\bid %d\b" % pid, ln)][0]
        if pid in named:
            assert sps_decoder.KNOWN_HISTORY_PROPS[pid][0] in line
            assert blob_reader.NO_DOCUMENTED_MEANING not in line
        else:
            assert blob_reader.NO_DOCUMENTED_MEANING in line


def test_decode_blob_lines_names_the_property_set_and_its_fmtid():
    text = "\n".join(blob_reader.decode_blob_lines(sample_store()))
    assert "property set" in text.lower()
    assert "01010101-0101-0101-0101-010101010101" in text


def test_decode_blob_lines_labels_the_sps_last_visit_as_local_time():
    """Every other timestamp in this database is UTC. Property 24 is not,
    and a pane that prints it beside them without saying so invites an
    examiner to compare two different clocks."""
    text = "\n".join(blob_reader.decode_blob_lines(sample_store()))
    assert "LOCAL" in text


def test_decode_blob_lines_reads_http_headers_as_stored():
    blob = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
    lines = blob_reader.decode_blob_lines(blob)
    assert lines[0] == "Detected class: http"
    assert "HTTP/1.1 200 OK" in lines
    assert "Content-Type: text/html" in lines
    assert "" not in lines[1:]


def test_decode_blob_lines_falls_back_to_the_download_decoder():
    from webcache.engine import download_decoder
    blob = download_decoder.build_synthetic_download_blob(
        "3f2a1b4c-5d6e-7f80-9012-3456789abcde", 133544180420000000, 20480,
        "C:\\Users\\x\\Downloads\\report.pdf",
        "https://example.test/report.pdf")
    text = "\n".join(blob_reader.decode_blob_lines(blob))
    assert "onfidence" in text
    assert "report.pdf" in text


def test_decode_blob_lines_names_a_windows_cert_blob():
    blob = b"\x00\x00\x00\x00CERT" + b"\x00" * 64
    assert any("CERT" in ln for ln in blob_reader.decode_blob_lines(blob))


def test_decode_blob_lines_never_raises_on_malformed_bytes():
    """The pane never disappears on a damaged blob, and never claims a
    clean decode of one."""
    for data in (b"", b"1SPS", b"1SPS" + b"\xff" * 40,
                 struct.pack("<I", 0xFFFFFFFF) + b"1SPS" + b"\x00" * 20,
                 bytes(range(256)), b"HTTP/" + b"\xff" * 30):
        lines = blob_reader.decode_blob_lines(data)
        assert isinstance(lines, list)
        assert all(isinstance(ln, str) for ln in lines)


def test_decode_blob_lines_of_nothing_says_so_rather_than_returning_nothing():
    """An empty pane and "there is nothing to decode" are different
    statements, and only one of them is honest about a zero-byte blob."""
    lines = blob_reader.decode_blob_lines(b"")
    assert lines and lines[-1].strip()


def test_the_no_decode_sentence_is_a_sentence_not_an_empty_pane():
    assert blob_reader.NO_DECODE.strip()


def test_the_page_size_and_carve_window_are_declared_once_here():
    """widgets/hex_view.py must not carry a second copy of either number
    -- see BlobSource.page_bytes."""
    assert blob_reader.HEX_PAGE_BYTES == 4096
    assert blob_reader.CARVE_WINDOW == 1024


# --- what a decoder is allowed to claim about bytes it did not identify -

def test_a_certificate_blob_is_named_before_it_is_guessed_at():
    """Found by LOOKING at a real certificate.

    An 8,108-byte DER certificate fell through to the download decoder,
    which found "http://ocsp.digicert.com" inside it and reported it as
    "Source URL" under "Download record confidence: low". Every word was
    a pattern match over bytes nothing had identified as a download
    record, printed in the vocabulary of a finding.

    These bytes identify themselves: the four at offset 4 are the
    Windows certificate store's own marker. Say that, and do not run a
    download decoder over a certificate.
    """
    blob = (b"\x00\x00\x00\x00CERT" + b"\x00" * 32
            + b"http://ocsp.example.test/" + b"\x00" * 32)
    text = "\n".join(blob_reader.decode_blob_lines(blob))
    assert "CERT" in text
    assert "Download record confidence" not in text
    assert "Source URL" not in text


def test_an_unidentified_blob_says_the_download_read_is_a_hypothesis():
    """Where nothing identifies the bytes, the download decoder's reading
    is still worth offering -- it grades itself, and on a genuine
    iedownload record it is right. It must not be offered in the
    vocabulary of a finding."""
    blob = b"\x11" * 8 + rb"C:\Users\jo\file.bin" + b"\x00" * 8
    lines = blob_reader.decode_blob_lines(blob)
    text = "\n".join(lines)
    assert blob_reader.SPECULATIVE_DECODE in text
    # and the caveat comes BEFORE the reading it qualifies.
    assert (text.index(blob_reader.SPECULATIVE_DECODE)
            < text.index("Download record confidence"))


def test_a_real_download_blob_still_decodes_under_the_caveat():
    from webcache.engine import download_decoder
    blob = download_decoder.build_synthetic_download_blob(
        "3f2a1b4c-5d6e-7f80-9012-3456789abcde", 133544180420000000, 20480,
        r"C:\Users\jo\Downloads\report.pdf",
        "https://example.test/report.pdf")
    text = "\n".join(blob_reader.decode_blob_lines(blob))
    assert "report.pdf" in text
    assert "example.test/report.pdf" in text
    # A grade, and not the "none" that would mean nothing anchored at all.
    # NOT asserted to be "high": that was an unverified guess about this
    # fixture. The synthetic blob's own layout puts a printable run early
    # enough that download_decoder's FILETIME scan stops before reaching
    # it, so it grades medium -- which is the decoder's business, not
    # this test's. What matters here is that a genuine download record
    # still decodes under the new caveat.
    assert blob_reader.SPECULATIVE_DECODE in text
    assert "confidence: none" not in text
