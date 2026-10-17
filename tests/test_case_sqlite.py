"""The case SQLite export (export_sqlite) must be typed, complete and
queryable -- a column declared TEXT stores integers as text (numeric
ORDER BY lies and
`records JOIN containers ON ContainerId` returned 0 rows without a CAST),
carved rows built from a hand-typed 8-key dict instead of the canonical
build_entry_row() (dropping tens of thousands of recovered fields per
exhibit), no primary key, and a KeyTimestampUTC column holding two string
widths (with vs without milliseconds).
"""
import datetime
import sqlite3

from webcache.engine.forensic_engine import ForensicEngine, build_entry_row

LIVE = {"EntryId": 7, "ContainerId": 3, "FileSize": 900, "Url": "u1",
        "AccessedTime_raw": 133500000000000000}
CARVED = {"Url": "u2", "RecoverySource": "slack", "Confidence": "low",
          "Source": "WebCacheV01.dat", "Offset": 4096, "Page": 2,
          "EntryId": 9, "ContainerId": 3, "FileSize": 50,
          "NearbyFiletime": datetime.datetime(2024, 1, 1, 0, 0, 0, 500000)}


def _db(tmp_path):
    out = tmp_path / "c.sqlite"
    engine = ForensicEngine()
    engine.load_entries([LIVE])
    engine.export_sqlite(
        [LIVE], str(out), artifacts={"containers": [{"ContainerId": 3, "Name": "Content"}]},
        recovered=[CARVED])
    return sqlite3.connect(out)


def test_integers_are_stored_as_integers(tmp_path):
    con = _db(tmp_path)
    assert con.execute("select typeof(EntryId), typeof(FileSize) from records "
                       "where RecordSource = 'Live database'").fetchone() == ("integer", "integer")


def test_records_join_containers_without_a_cast(tmp_path):
    con = _db(tmp_path)
    n = con.execute("select count(*) from records r join containers c "
                    "on r.ContainerId = c.ContainerId").fetchone()[0]
    assert n == 2


def test_a_carved_row_carries_its_full_record(tmp_path):
    con = _db(tmp_path)
    row = con.execute("select FileSize, EntryId, Source, Offset from records "
                      "where RecordSource like 'RECOVERED%'").fetchone()
    assert row == (50, 9, "WebCacheV01.dat", 4096)


def test_every_key_timestamp_has_one_width(tmp_path):
    con = _db(tmp_path)
    widths = {len(r[0]) for r in con.execute(
        "select KeyTimestampUTC from records where KeyTimestampUTC <> ''")}
    assert widths == {24}


def test_records_has_a_primary_key(tmp_path):
    con = _db(tmp_path)
    assert any(r[5] for r in con.execute("pragma table_info(records)"))


def test_blob_record_rowid_still_points_at_its_record(tmp_path):
    """The blobs table tracks the live record's row with its own `rowid`
    counter, incremented once per INSERT into `records` -- independently of
    sqlite's own row numbering. Adding `id INTEGER PRIMARY KEY` to `records`
    must not desynchronise the two: `id` is a rowid alias, assigned in the
    same insertion order the manual counter already followed, so a blob's
    `record_rowid` must still join back to the SAME row it was captured
    from."""
    live_with_blob = dict(LIVE)
    live_with_blob["ResponseHeaders_raw"] = b"HTTP/1.1 200 OK\r\n\r\n"
    out = tmp_path / "c2.sqlite"
    engine = ForensicEngine()
    engine.load_entries([live_with_blob])
    engine.export_sqlite([live_with_blob], str(out), recovered=[CARVED])
    con = sqlite3.connect(out)
    row = con.execute(
        "select r.RecordSource, r.EntryId from records r "
        "join blobs b on b.record_rowid = r.id "
        "where b.field = 'ResponseHeaders_raw'").fetchone()
    assert row == ("Live database", 7)


# --- TableName must not be overwritten with a ------
# --- fabricated "Container_" when there is no ContainerId to derive it -----
# --- from. A stub dict (no ContainerId) supplies its own real TableName;   -
# --- build_entry_row used to discard it unconditionally.                  -

def test_stub_tablename_from_a_container_table_is_kept():
    stub = {"TableName": "Container_11", "EntryId": 42, "Url": ""}
    assert build_entry_row(stub)["TableName"] == "Container_11"


def test_stub_tablename_from_a_blobentry_table_is_kept():
    stub = {"TableName": "BlobEntry_13", "EntryId": 1, "Url": ""}
    assert build_entry_row(stub)["TableName"] == "BlobEntry_13"


def test_stub_tablename_from_leakfiles_is_kept():
    stub = {"TableName": "LeakFiles", "EntryId": 1, "Url": ""}
    assert build_entry_row(stub)["TableName"] == "LeakFiles"


def test_live_row_tablename_is_unchanged():
    """A live (or structured-carve) row carries ContainerId, so TableName
    must still be DERIVED from it -- never fall back to a supplied
    TableName it doesn't need."""
    row = build_entry_row(dict(LIVE))
    assert row["TableName"] == "Container_3"


def test_case_db_keeps_the_real_table_name_for_each_stub_kind(tmp_path):
    out = tmp_path / "stubs.sqlite"
    engine = ForensicEngine()
    engine.load_entries([])
    stubs = [
        {"TableName": "Container_11", "EntryId": 1, "UrlHash": 1, "Url": "",
         "Source": "Container_11", "RecoverySource": "Deleted-record stub (b-tree key only)",
         "Confidence": "exact key"},
        {"TableName": "BlobEntry_13", "EntryId": 2, "Url": "",
         "Source": "BlobEntry_13", "RecoverySource": "Deleted-record stub (b-tree key only)",
         "Confidence": "exact key"},
        {"TableName": "LeakFiles", "EntryId": 3, "Url": "",
         "Source": "LeakFiles", "RecoverySource": "Deleted-record stub (b-tree key only)",
         "Confidence": "exact key"},
    ]
    engine.export_sqlite([], str(out), recovered=stubs)
    con = sqlite3.connect(out)
    names = {r[0] for r in con.execute(
        "select TableName from records where RecordSource like 'RECOVERED%'")}
    assert names == {"Container_11", "BlobEntry_13", "LeakFiles"}


# --- ContainerId PRESENT --
# --- but None is a MISSING id, not a real one. recovery_engine.py:519    --
# --- builds every structured-carve row with                              -
# --- "ContainerId": r.get("ContainerId") -- when the source record never -
# --- resolved a container, that key is present with value None, and the  -
# --- round-1 fix (gating on key PRESENCE) still derived "Container_None",-
# --- the same fabricated, resolved-looking value finding 1 forbids.       -

def test_containerid_none_with_no_tablename_invents_nothing():
    row = build_entry_row({"EntryId": 1, "ContainerId": None, "Url": ""})
    assert row["TableName"] not in ("Container_None", "Container_")
    assert row["TableName"] == ""


def test_containerid_none_with_a_supplied_tablename_keeps_it():
    row = build_entry_row({"EntryId": 1, "ContainerId": None,
                           "TableName": "BlobEntry_13", "Url": ""})
    assert row["TableName"] == "BlobEntry_13"


def test_containerid_empty_string_with_a_supplied_tablename_keeps_it():
    row = build_entry_row({"EntryId": 1, "ContainerId": "",
                           "TableName": "LeakFiles", "Url": ""})
    assert row["TableName"] == "LeakFiles"


def test_containerid_empty_string_with_no_tablename_invents_nothing():
    row = build_entry_row({"EntryId": 1, "ContainerId": "", "Url": ""})
    assert row["TableName"] == ""


def test_containerid_a_real_int_still_derives_container_name():
    row = build_entry_row({"EntryId": 1, "ContainerId": 3, "Url": ""})
    assert row["TableName"] == "Container_3"


def test_structured_carve_shape_with_unresolved_containerid_has_no_fabricated_name(tmp_path):
    """The exact shape recovery_engine.py's structured carve produces
    (~line 519): "ContainerId": r.get("ContainerId") -- present, None,
    because the source record never resolved to a live container."""
    out = tmp_path / "structured.sqlite"
    engine = ForensicEngine()
    engine.load_entries([])
    structured_row = {
        "EntryId": 99, "ContainerId": None, "ContainerName": "",
        "Url": "", "Source": "WebCacheV01.dat",
        "RecoverySource": "Structured record reconstruction",
        "Confidence": "high",
    }
    engine.export_sqlite([], str(out), recovered=[structured_row])
    con = sqlite3.connect(out)
    names = {r[0] for r in con.execute(
        "select TableName from records where RecordSource like 'RECOVERED%'")}
    assert "Container_None" not in names


# --- regression guards -- IsInPrivate must never ---
# --- be derived from Flags bit 0x08 inside build_entry_row itself. That   -
# --- bit means InPrivate ONLY on a History record and something else      -
# --- (EDITED_CACHE_ENTRY) on Content -- ese_parser.py already gates this  -
# --- correctly for live entries (container_type == "History"), and no    -
# --- carve path (page/log/structured) ever attaches an ungated reading.   -
# --- build_entry_row must keep it that way: it only ever CARRIES an       -
# --- already-computed IsInPrivate through, never recomputes it.          --

def test_live_content_record_with_edited_bit_stays_not_inprivate():
    """A live Content record with Flags 0x08 -- ese_parser.py already
    resolved this correctly to False, because 0x08 is EDITED_CACHE_ENTRY on
    a non-History container, not InPrivate. build_entry_row must not
    recompute it from Flags and flip it to True."""
    entry = {"EntryId": 1, "ContainerId": 3, "ContainerType": "Content",
             "Flags": 0x08, "IsInPrivate": False, "Url": "http://x.test/"}
    assert build_entry_row(entry)["IsInPrivate"] is False


def test_carved_structured_content_record_with_edited_bit_is_not_inprivate():
    """A carved structured-record dict, shaped the way
    recovery_engine.py's structured carve produces one: it carries raw
    Flags but (correctly) no IsInPrivate key at all, because no carve path
    computes it. build_entry_row must not manufacture IsInPrivate=True out
    of the raw Flags bit."""
    carved = {"EntryId": 5, "ContainerId": 3, "ContainerType": "Content",
             "Flags": 0x08, "Url": "http://x.test/", "Source": "s",
             "RecoverySource": "Structured record reconstruction",
             "Confidence": "high"}
    assert build_entry_row(carved).get("IsInPrivate") is not True


def test_carved_record_with_no_container_type_is_not_inprivate():
    """A carve that never resolved a container type at all -- Flags 0x08 is
    ambiguous without one, so it must not resolve to InPrivate either."""
    carved = {"EntryId": 6, "Flags": 0x08, "Url": "http://x.test/",
             "Source": "s", "RecoverySource": "DB unallocated space",
             "Confidence": "low"}
    assert build_entry_row(carved).get("IsInPrivate") is not True
