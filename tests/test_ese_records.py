"""What counts as a record.

dissect.esedb yields every b-tree leaf node as a Record, including nodes
whose payload is shorter than the 4-byte ESE record header. Those resolve
every column to None and were reported as real rows -- 134 of them across
the five sample databases. The record header is what makes a node a
record; a node too short to hold one is a deleted-record stub.
"""
import ast
import pathlib

import pytest

from webcache.engine import ese_records


class _Node:
    def __init__(self, data, key=b""):
        self.data = data
        self.key = key


class _Rec:
    def __init__(self, data, key=b""):
        self._node = _Node(data, key)


class _Table:
    name = "Container_1"

    def __init__(self, recs):
        self._recs = recs

    def records(self):
        return iter(self._recs)


def test_the_header_is_four_bytes():
    assert ese_records.RECORD_HEADER_LEN == 4


def test_a_one_byte_leaf_node_is_not_a_record():
    stub, real = _Rec(b"\x00"), _Rec(b"\x05\x00\x10\x00" + b"\x00" * 30)
    assert list(ese_records.live_records(_Table([stub, real]))) == [real]


def test_exactly_the_header_length_is_a_record():
    rec = _Rec(b"\x00" * 4)
    assert ese_records.is_record_node(rec) is True


def test_a_record_whose_columns_are_all_null_is_still_a_record():
    """Pins the refuted discriminator. "Every column is NULL" would drop a
    legitimate all-null record; only the payload length decides."""
    rec = _Rec(b"\x01\x7f\x04\x00")        # a well-formed header, no data
    assert ese_records.is_record_node(rec) is True


def test_nothing_else_in_the_engine_enumerates_records_directly():
    """Sixteen call sites existed. Fixing some of them left the tool
    contradicting itself -- counts from one method, rows from another."""
    root = pathlib.Path(__file__).resolve().parent.parent / "webcache" / "engine"
    offenders = []
    for path in root.glob("*.py"):
        if path.name == "ese_records.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "records"
                    and not node.args):
                offenders.append("%s:%d" % (path.name, node.lineno))
    assert offenders == [], "call ese_records.live_records(table) instead: %s" % offenders


def _enc(value):
    """ESE's normalised form of a signed 64-bit integer: 0x7F, then the
    big-endian two's-complement bytes with the sign bit flipped."""
    return b"\x7f" + ((value & (2 ** 64 - 1)) ^ (1 << 63)).to_bytes(8, "big")


@pytest.mark.parametrize("value", [0, 12, 2 ** 62, -5, -(2 ** 63)])
def test_a_single_segment_key_round_trips(value):
    assert ese_records.decode_node_key(_enc(value)) == (value,)


def test_a_two_segment_key_decodes_both():
    assert ese_records.decode_node_key(_enc(7) + _enc(42)) == (7, 42)


@pytest.mark.parametrize("junk", [b"", b"\x00" * 9, b"\x7f\x00", _enc(1) + b"\x01"])
def test_a_key_not_in_that_form_decodes_to_nothing(junk):
    assert ese_records.decode_node_key(junk) == ()


def test_stubs_are_enumerated_with_the_key_they_name():
    stub = _Rec(b"\x00", key=_enc(99) + _enc(3))
    real = _Rec(b"\x00" * 40, key=_enc(1) + _enc(1))
    got = list(ese_records.tombstones([_Table([real, stub])]))
    assert got == [{"Table": "Container_1",
                    "KeyColumns": ("UrlHash", "EntryId"),
                    "KeyValues": (99, 3), "Page": None, "Offset": None}]


def test_a_stub_whose_key_cannot_be_decoded_is_still_reported():
    """Evidence of a deletion is reported even when the key is unreadable."""
    got = list(ese_records.tombstones([_Table([_Rec(b"\x00", key=b"??")])]))
    assert got == [{"Table": "Container_1", "KeyColumns": (), "KeyValues": (),
                    "Page": None, "Offset": None}]


# --- a stub's page and offset; one bad table ----------

class _Page:
    is_small_page = False

    def __init__(self, num):
        self.num = num


class _Tag:
    def __init__(self, page, offset, data):
        self.page = page
        self.offset = offset
        self.data = data


class _PlacedRec:
    """A leaf node with the tag dissect gives it: page, offset in page,
    and the tag's own bytes (key prefix + node data)."""

    def __init__(self, data, key, page_num, tag_offset, prefix_len):
        self._node = _Node(data, key)
        self._node.tag = _Tag(_Page(page_num), tag_offset,
                              b"\x00" * prefix_len + data)


class _PlacedTable(_Table):
    def __init__(self, recs, page_size=32768):
        super().__init__(recs)
        self.db = type("_Db", (), {"page_size": page_size})()


def test_a_stub_carries_the_page_and_absolute_file_offset_of_its_node():
    """The node's tag gives both exactly -- the same formula
    struct_carver._live_record_offsets uses for a live record, so a stub's
    offset and a carved record's offset are the same kind of number."""
    stub = _PlacedRec(b"\x00", _enc(99) + _enc(3), page_num=5,
                      tag_offset=0x120, prefix_len=18)
    got = list(ese_records.tombstones([_PlacedTable([stub])]))
    assert len(got) == 1
    assert got[0].get("Page") == 5
    assert got[0].get("Offset") == (5 + 1) * 32768 + 80 + 0x120 + 18


def test_one_unreadable_table_does_not_lose_the_stubs_of_the_others():
    class _Bad:
        name = "Container_9"

        def records(self):
            raise ValueError("page checksum mismatch")

    good = _Table([_Rec(b"\x00", key=_enc(1))])
    try:
        got = list(ese_records.tombstones([_Bad(), good]))
    except Exception as exc:                      # noqa: BLE001
        pytest.fail("one unreadable table aborted the whole walk: %r" % exc)
    assert [g["Table"] for g in got] == ["Container_1"]
