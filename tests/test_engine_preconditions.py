"""The engine values the shell needs and the engine currently throws away.

Three separate discards, one theme: the engine computes a value, renders
it for a person, and drops the machine-readable original. Every one of
them blocks something the row builders in webcache/shell/ cannot honestly
do without it.

1. HSTS Expires. _parse_hsts_table computes the raw FILETIME, stores only
   filetime_to_str()'s output, and drops the int -- so the Expires column
   is a pre-formatted string sitting in a kind="time" column, which
   record_filter.py's time operators (before/after/between/on/in the last
   N days) cannot compare against at all. This codebase has already hit
   the "a pre-formatted string silently breaks every date-based filter"
   failure once (see evidence_loader.py's own DownloadTime comment).

2. Container LastAccessTime / LastScavengeTime. The identical discard,
   one table over: _load_containers keeps only the strings, which is why
   container_rows_from_parser's own docstring currently says "there is
   nothing to convert without inventing a value".

3. Seven carved columns. struct_carver.FIXED_COLUMNS recovers 17 columns
   from a deleted record; carve_structured_records' `rec = {...}` literal
   copies only ten of them and discards CacheId, UrlHash, SecureDirectory,
   Type, SyncCount and ExemptionDelta outright -- plus Filename, the
   recovered CACHED filename, which normalise_record then re-derives only
   for file: URLs, so a carved cached filename is lost for every other
   record. These were read off the disk once already; dropping them means
   a re-scan is the only way to get them back.

Tested against fakes, not a real WebCacheV01.dat: there is no evidence
file in this repository and never will be (see tests/fixtures.py).
"""
import types

import pytest

from webcache.engine import recovery_engine, struct_carver
from webcache.engine.ese_parser import WebCacheParser

#: The literal IE stores in Expires for a pin that never expires. Named
#: here rather than inlined so a test that asserts on it says which fact
#: it is asserting about.
NEVER = 0x7FFFFFFFFFFFFFFF


def _live_node():
    """A `_node` shaped like dissect's real one: long enough to pass
    ese_records.is_record_node, which is what every fake record here
    needs to be enumerated by live_records() instead of silently dropped
    as a 1-byte stub."""
    return types.SimpleNamespace(data=b"\x00" * 16, key=b"")


class _FakeRecord(dict):
    """An ESE record as dissect hands it over: .get(column_name)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._node = _live_node()


class _FakeTable:
    def __init__(self, records):
        self._records = records

    def records(self):
        return iter(self._records)


class _FakeDb:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _FakeTable(self._tables[name])


def _parser_with(table_name, records):
    parser = WebCacheParser()
    parser.db = _FakeDb({table_name: [_FakeRecord(r) for r in records]})
    parser.table_names = [table_name]
    return parser


# --- 1. the HSTS pin's raw expiry -----------------------------------------

def test_the_hsts_table_keeps_the_raw_expiry_filetime():
    """Expires_raw is the int the pin actually stores.

    Without it the shell has only "2024-03-11 09:14:02 UTC" -- a string
    that a time filter cannot compare and a sort orders lexically.
    """
    parser = _parser_with("HstsEntryEx_1", [
        {"RDomain": "moc.elpmaxe", "Expires": 133535904000000000,
         "LastTimeUsed": 133535904000000000, "IncludeSubdomains": 1,
         "EntryId": 4},
    ])
    parser._parse_hsts_table("HstsEntryEx_1")

    entry = parser.hsts_entries[0]
    assert entry["Expires_raw"] == 133535904000000000, (
        "the raw FILETIME the pin stores must survive alongside the "
        "formatted string; without it Expires cannot be a real datetime")


def test_the_never_sentinel_survives_as_itself_not_as_a_far_future_date():
    """A pin with no expiry stores 0x7FFFFFFFFFFFFFFF, which is not a
    time. Expires_raw must carry that exact sentinel through, so the
    shell can say "never" rather than render a nonsense year."""
    parser = _parser_with("HstsEntryEx_1", [
        {"RDomain": "moc.elpmaxe", "Expires": NEVER, "LastTimeUsed": 0,
         "IncludeSubdomains": 0, "EntryId": 5},
    ])
    parser._parse_hsts_table("HstsEntryEx_1")

    entry = parser.hsts_entries[0]
    assert entry["Expires"] == "never", "the existing wording must not change"
    assert entry["Expires_raw"] == NEVER, (
        "the sentinel itself must reach the shell -- a 0 or a missing key "
        "would read as 'no expiry recorded', which is a different claim "
        "from 'this pin never expires'")


# --- 2. the container's raw access/scavenge times -------------------------

def test_the_containers_table_keeps_its_two_raw_filetimes():
    """LastAccessTime_raw / LastScavengeTime_raw, for exactly the reason
    the HSTS pin needs Expires_raw: both columns are declared kind="time"
    in views/containers.py and both currently hold a string."""
    parser = WebCacheParser()
    parser.db = _FakeDb({"Containers": [_FakeRecord({
        "ContainerId": 3, "Name": "History", "Directory": "",
        "PartitionId": "", "Flags": 0, "Size": 4096, "Limit": 0,
        "LastScavengeTime": 133535904000000000,
        "LastAccessTime": 133535914000000000,
        "EntryMaxAge": 0, "SecureDirectories": None,
    })]})
    parser.table_names = ["Containers"]
    parser._load_containers()

    meta = parser.containers_meta[0]
    assert meta["LastAccessTime_raw"] == 133535914000000000
    assert meta["LastScavengeTime_raw"] == 133535904000000000
    assert meta["LastAccessTime"], "the formatted string stays too"


def test_a_container_that_was_never_scavenged_keeps_a_zero_not_a_missing_key():
    """0 is what the table stores for "never scavenged". The key must
    exist and hold 0 -- an absent key and a recorded zero are different
    facts, and only one of them is what the database says."""
    parser = WebCacheParser()
    parser.db = _FakeDb({"Containers": [_FakeRecord({
        "ContainerId": 9, "Name": "Content", "Directory": "",
        "PartitionId": "", "Flags": 0, "Size": 0, "Limit": 0,
        "LastScavengeTime": 0, "LastAccessTime": 0, "EntryMaxAge": 0,
        "SecureDirectories": None,
    })]})
    parser.table_names = ["Containers"]
    parser._load_containers()

    meta = parser.containers_meta[0]
    assert "LastScavengeTime_raw" in meta
    assert meta["LastScavengeTime_raw"] == 0
    assert meta["LastAccessTime_raw"] == 0


# --- 3. the seven carved columns the reconstruction throws away -----------

#: Every column struct_carver.carve_records recovers that
#: carve_structured_records' own dict literal did not copy forward.
#: Filename is in this list for a reason worth stating: normalise_record
#: re-derives Filename from the URL, but only for a file: URL, so the
#: CACHED filename a deleted Content record carried is lost outright for
#: every http(s) record.
DISCARDED = ("CacheId", "UrlHash", "SecureDirectory", "Type", "SyncCount",
             "ExemptionDelta", "Filename")


class _StubDbForCarve:
    """carve_structured_records only ever passes `db` through to
    struct_carver.carve_records, which this test replaces."""


@pytest.mark.parametrize("column", DISCARDED)
def test_a_recovered_column_is_not_discarded_on_the_way_out(
        column, monkeypatch, tmp_path):
    """struct_carver read this column off the disk; carve_structured_
    records must not drop it. Re-scanning the exhibit is the only other
    way to get it back, and a carve is the single most expensive read
    this application performs."""
    db_path = tmp_path / "WebCacheV01.dat"
    db_path.write_bytes(b"\x00" * 16)

    carved = {
        "Url": "https://example.test/a", "EntryId": 1, "ContainerId": 3,
        "AccessCount": 2, "Flags": 0, "FileSize": 10,
        "CacheId": 77, "UrlHash": 1234, "SecureDirectory": 2, "Type": 1,
        "SyncCount": 5, "ExemptionDelta": 60, "Filename": "cached[1].htm",
        "ResponseHeaders": b"", "_grade": "HIGH", "_offset": 4096,
        "_page": 2, "_mode": "terminated", "_sps": False,
    }
    for name in ("CreationTime", "ModifiedTime", "AccessedTime",
                 "ExpiryTime", "SyncTime", "PostCheckTime"):
        carved[name] = 0

    # carve_structured_records does `from . import struct_carver` inside
    # the method, so patching the module attribute is what it will see.
    monkeypatch.setattr(struct_carver, "carve_records",
                        lambda *a, **k: [dict(carved)])

    engine = recovery_engine.RecoveryEngine()
    engine.carve_structured_records(_StubDbForCarve(), str(db_path))

    assert engine.structured_records, "the stubbed carve produced one record"
    rec = engine.structured_records[0]
    assert rec.get(column) == carved[column], (
        "%s was recovered from the deleted record and then dropped by "
        "carve_structured_records' own dict literal" % column)


# --- 4. one visit-count fallback, not two -------------------------------

def test_the_visit_count_fallback_is_reachable_without_building_a_whole_row():
    """build_entry_row computes (value, source) for the exports and no
    caller outside it can reach that logic.

    The shell needs the same two answers per row, and the only ways to get
    them today are to re-type the fallback -- which is how two spellings
    of "which counter is this" start diverging -- or to run the entire
    69-field export builder per row on screen.
    """
    from webcache.engine import forensic_engine

    value, source = forensic_engine.visit_count_best(
        {"SPS_VisitCount": 3, "AccessCount": 9})
    assert value == 3
    assert source == forensic_engine.VISIT_SOURCE_SPS

    value, source = forensic_engine.visit_count_best({"AccessCount": 9})
    assert value == 9
    assert source == forensic_engine.VISIT_SOURCE_ACCESS_COUNT

    value, source = forensic_engine.visit_count_best({})
    assert value is None
    assert source == "", "no counter means no claim about a counter"


def test_visit_count_source_agrees_with_the_export():
    """The two must never diverge -- that is the entire reason the helper
    exists rather than a second copy of the fallback in the shell."""
    from webcache.engine import forensic_engine

    for entry in ({"SPS_VisitCount": 3, "AccessCount": 9},
                  {"AccessCount": 9},
                  {"SPS_VisitCount": 0, "AccessCount": 9},
                  {}):
        _value, source = forensic_engine.visit_count_best(entry)
        assert source == forensic_engine.build_entry_row(
            entry)["VisitCountBestSource"], entry


def test_a_zero_sps_visit_count_still_counts_as_the_sps_answer():
    """0 is a recorded count, not a missing one. `or` would fall through
    to AccessCount and mislabel the source -- the same falsy-zero bug
    class provenance.describe_origin already names for Offset."""
    from webcache.engine import forensic_engine

    value, source = forensic_engine.visit_count_best(
        {"SPS_VisitCount": 0, "AccessCount": 9})
    assert value == 0
    assert source == forensic_engine.VISIT_SOURCE_SPS


# --- 5. an HSTS row that can reach its own record -------------------------

def test_an_hsts_evidence_row_carries_the_pin_it_was_built_from():
    """hsts_visit_evidence builds a display row and drops the pin. The row
    therefore cannot name its own EntryId, Table or PartitionId -- three
    values the pin is sitting on -- and Expires_raw cannot reach the shell
    at all, which is what makes the Expires column a string."""
    from webcache.engine.analysis_extra import hsts_visit_evidence

    pin = {"Domain": "example.test", "LastTimeUsed": "", "LastTimeUsed_raw": 0,
           "Expires": "2024-03-11 09:14:02 UTC",
           "Expires_raw": 133544276420000000,
           "IncludeSubdomains": False, "Table": "HstsEntryEx_1",
           "PartitionId": "p1", "EntryId": 7}
    rows = hsts_visit_evidence([pin], [])

    assert len(rows) == 1
    assert rows[0]["SourceEntry"] is pin, (
        "by reference -- the pin is already resident, and a copy would "
        "make the row and the record able to disagree")
    assert rows[0]["Expires_raw"] == 133544276420000000
