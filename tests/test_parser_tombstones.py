"""WebCacheParser.tombstones() wiring.

ese_records.tombstones is unit-tested on its own; this pins what the
parser adds on top: the key, the page and the absolute file offset of
each stub, the evidence FILE it lies in (never a table name standing in
for one), the container a Container_N stub belonged to, the cache, and
that one unreadable table is recorded rather than raised.
"""
import pytest

from webcache.engine.ese_parser import WebCacheParser


def _enc(value):
    return b"\x7f" + ((value + (1 << 64)) % (1 << 64) ^ (1 << 63)).to_bytes(8, "big")


class _Page:
    is_small_page = False

    def __init__(self, num):
        self.num = num


class _Tag:
    def __init__(self, page, offset, data):
        self.page, self.offset, self.data = page, offset, data


class _Node:
    def __init__(self, data, key, page_num, tag_offset, prefix_len):
        self.data, self.key = data, key
        self.tag = _Tag(_Page(page_num), tag_offset, b"\x00" * prefix_len + data)


class _Rec:
    def __init__(self, data, key, page_num=3, tag_offset=0x40, prefix_len=10):
        self._node = _Node(data, key, page_num, tag_offset, prefix_len)


class _Table:
    def __init__(self, name, recs, db):
        self.name, self._recs, self.db = name, recs, db

    def records(self):
        return iter(self._recs)


class _BadTable:
    def __init__(self, name):
        self.name = name

    def records(self):
        raise ValueError("unreadable page")


class _Db:
    page_size = 32768

    def __init__(self):
        self.calls = 0
        self._tables = []

    def tables(self):
        self.calls += 1
        return list(self._tables)


def _parser(extra_tables=()):
    db = _Db()
    db._tables = [
        _Table("Container_4", [
            _Rec(b"\x00" * 40, _enc(1) + _enc(1)),                 # real
            _Rec(b"\x00", _enc(111) + _enc(7), page_num=5,
                 tag_offset=0x120, prefix_len=18),                  # stub
        ], db),
        _Table("BlobEntry_8", [_Rec(b"\x00", _enc(12))], db),
    ] + list(extra_tables)
    parser = WebCacheParser()
    parser.db = db
    parser.db_path = "C:/case/evidence/WebCacheV01.dat"
    parser.container_map = {4: "History"}
    parser.container_type_map = {4: "History"}
    return parser, db


def test_a_container_stub_carries_key_page_offset_file_and_container():
    parser, _db = _parser()
    stubs = parser.tombstones()
    stub = [s for s in stubs if s["Table"] == "Container_4"][0]
    assert stub["KeyValues"] == (111, 7)
    assert stub.get("Page") == 5
    assert stub.get("Offset") == 6 * 32768 + 80 + 0x120 + 18
    assert stub.get("Source") == "WebCacheV01.dat", (
        "Source is shown under 'File' / 'Carved from file' -- it must be "
        "the evidence file, never the table name")
    assert stub.get("ContainerId") == 4
    assert stub.get("ContainerType") == "History"


def test_a_non_container_stub_names_its_file_but_no_container():
    parser, _db = _parser()
    stub = [s for s in parser.tombstones() if s["Table"] == "BlobEntry_8"][0]
    assert stub.get("Source") == "WebCacheV01.dat"
    assert stub.get("ContainerId") is None
    assert stub.get("ContainerType") is None


def test_tombstones_are_computed_once_and_cached():
    parser, db = _parser()
    first = parser.tombstones()
    second = parser.tombstones()
    assert first is second
    assert db.calls == 1


def test_an_unreadable_table_is_logged_not_raised():
    parser, _db = _parser([_BadTable("Container_9")])
    try:
        stubs = parser.tombstones()
    except Exception as exc:                        # noqa: BLE001
        pytest.fail("one unreadable table raised out of tombstones(): %r"
                    % exc)
    assert {s["Table"] for s in stubs} == {"Container_4", "BlobEntry_8"}
    assert any("Container_9" in line for line in parser.decision_log)
