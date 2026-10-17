"""Reading the exhibit back at a carve offset. Writes a temp file, reads it.

WHY THIS EXISTS AT ALL. Without it the Recovery view asserts "a record was
found at offset 107,760" and there is no way for anyone to look. With it,
the examiner copies the offset, opens the same file in their own hex
editor and sees the same rows -- a carve engine's assertion becomes a
checkable claim. That is the difference this module makes, and every test
below is about not undermining it: the window has to be where it says it
is, the file has to be opened read-only, and a failure has to name its own
cause instead of producing an empty pane that looks like "no data here".

WHY THE BYTES ARE NOT CARRIED ON THE ROW. A snapshot copied at scan time
is something the examiner has to take on trust. Bytes re-read from the
exhibit at display time are something they can check. Memory is the weaker
argument and is not the reason.
"""
import builtins
import os

import pytest

from webcache.engine import carve_reader


@pytest.fixture
def exhibit(tmp_path):
    """A file with a recognisable byte at every position."""
    path = tmp_path / "WebCacheV01.dat"
    path.write_bytes(bytes(range(256)) * 64)      # 16,384 bytes
    return str(path)


# --- the window ---------------------------------------------------------

def test_the_window_is_16_aligned_and_centred_on_the_offset(exhibit):
    """16-aligned so the dump's rows line up with the FILE's own row
    boundaries -- which is what makes the offset column comparable to
    another tool's, rather than merely internally consistent."""
    data, start, _note = carve_reader.read_carve_window(exhibit, None, 8200)
    assert start % 16 == 0
    assert start == (8200 - carve_reader.CARVE_WINDOW // 2) & ~0xF
    assert len(data) == carve_reader.CARVE_WINDOW
    assert start <= 8200 < start + len(data)


def test_the_window_is_the_bytes_actually_at_that_position(exhibit):
    data, start, _note = carve_reader.read_carve_window(exhibit, None, 8200)
    with open(exhibit, "rb") as fh:
        fh.seek(start)
        assert data == fh.read(len(data))


def test_a_window_near_the_start_is_clamped_to_zero_not_negative(exhibit):
    data, start, note = carve_reader.read_carve_window(exhibit, None, 32)
    assert start == 0
    assert len(data) == carve_reader.CARVE_WINDOW
    assert note.strip()


def test_a_window_near_the_end_returns_what_is_there(exhibit):
    size = os.path.getsize(exhibit)
    data, start, note = carve_reader.read_carve_window(exhibit, None, size - 8)
    assert 0 < len(data) <= carve_reader.CARVE_WINDOW
    assert start + len(data) <= size
    assert note.strip()


# --- resolution and its failures ----------------------------------------

def test_a_source_names_a_file_beside_the_database(exhibit, tmp_path):
    log = tmp_path / "V01.log"
    log.write_bytes(b"L" * 4096)
    data, start, note = carve_reader.read_carve_window(exhibit, "V01.log", 2048)
    assert data == b"L" * len(data)
    assert "V01.log" in note


def test_a_source_can_never_steer_the_read_out_of_the_evidence_folder(
        exhibit, tmp_path):
    """Source is a basename by construction (recovery_engine sets
    os.path.basename), and it is re-basenamed here so a carved value that
    happens to look like a path cannot reach outside the folder."""
    outside = tmp_path.parent / "elsewhere.bin"
    outside.write_bytes(b"X" * 64)
    data, _start, note = carve_reader.read_carve_window(
        exhibit, "..\\elsewhere.bin", 0)
    assert b"X" * 64 not in data
    assert "elsewhere.bin" in note


def test_a_missing_source_falls_back_to_the_database_and_says_so(exhibit):
    """A carve out of a transaction log that has since been deleted still
    has bytes worth showing -- but the examiner must be told they are
    looking at the database instead."""
    data, _start, note = carve_reader.read_carve_window(
        exhibit, "V01-gone.log", 2048)
    assert data
    assert "V01-gone.log" in note
    assert os.path.basename(exhibit) in note


def test_an_offset_past_the_end_names_the_file_and_its_size(exhibit):
    size = os.path.getsize(exhibit)
    data, _start, note = carve_reader.read_carve_window(
        exhibit, None, size + 10_000)
    assert data == b""
    assert os.path.basename(exhibit) in note
    assert "{:,}".format(size) in note


def test_an_offset_that_is_not_a_number_says_so(exhibit):
    data, _start, note = carve_reader.read_carve_window(exhibit, None, "abc")
    assert data == b""
    assert "abc" in note


def test_no_offset_at_all_says_the_record_carries_none(exhibit):
    data, _start, note = carve_reader.read_carve_window(exhibit, None, None)
    assert data == b""
    assert "no source offset" in note


def test_an_unreadable_file_names_the_cause(tmp_path):
    data, _start, note = carve_reader.read_carve_window(
        str(tmp_path / "not-there.dat"), None, 0)
    assert data == b""
    assert note.strip()


# --- the invariants that must never slip --------------------------------

def test_the_evidence_file_is_opened_read_only(exhibit, monkeypatch):
    """The exhibit folder is read-only for the whole life of the case.
    Every open in this module passes exactly "rb", positionally."""
    seen = []
    real_open = builtins.open

    def watched(file, mode="r", *args, **kwargs):
        seen.append(mode)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", watched)
    carve_reader.read_carve_window(exhibit, None, 4096)
    assert seen and set(seen) == {"rb"}


@pytest.mark.parametrize("offset", [None, "abc", -1, 10 ** 12, 0, 4096])
def test_the_note_is_never_empty_whatever_happens(exhibit, offset):
    """Every failure names its cause and none of them returns a blank
    pane -- an empty box says "no data here", which is a claim about the
    evidence rather than about the read."""
    _data, _start, note = carve_reader.read_carve_window(exhibit, None, offset)
    assert note.strip()


def test_the_note_is_never_empty_when_the_data_is_empty(exhibit):
    for source, offset in ((None, None), (None, "x"),
                           (None, 10 ** 12), ("V01.log", None)):
        data, _start, note = carve_reader.read_carve_window(
            exhibit, source, offset)
        if not data:
            assert note.strip(), (source, offset)


def test_a_zero_offset_is_read_not_treated_as_missing(exhibit):
    """Offset 0 is the first byte of a file, not an absent value -- the
    same bug class provenance.describe_origin already guards against."""
    data, start, note = carve_reader.read_carve_window(exhibit, None, 0)
    assert start == 0
    assert len(data) == carve_reader.CARVE_WINDOW
    assert "no source offset" not in note


def test_the_relative_position_inside_the_window_is_reported(exhibit):
    """The header says "the record begins N bytes in", and N has to be
    inside the window it describes."""
    rel = carve_reader.offset_within(8200, 7680, carve_reader.CARVE_WINDOW)
    assert rel == 520
    assert carve_reader.offset_within(0, 0, 1024) == 0
    assert carve_reader.offset_within(99999, 0, 16) == 15
