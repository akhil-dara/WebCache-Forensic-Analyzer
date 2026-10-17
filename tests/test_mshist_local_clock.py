"""An MSHist container stores ModifiedTime on the LOCAL clock.

A synthetic ESE database -- built the way test_engine_preconditions.py
builds one, a real WebCacheParser over a fake dissect surface -- holds
five visits twice: once in the History container (UTC ModifiedTime, and
the SPS id-24 local time the zone is recovered from) and once in a daily
MSHist container whose ModifiedTime holds the same visit's LOCAL digits.
The visits sit near midnight UTC so the local day is the next calendar
day: a record on the wrong clock lands in the wrong day bucket.
"""
import datetime
import json
import struct
import types
import uuid

import pytest

from webcache.engine import forensic_engine
from webcache.engine.ese_parser import WebCacheParser
from webcache.shell.evidence_loader import (file_access_rows_from_parser,
                                             history_rows_from_parser)

UTC = datetime.timezone.utc
ZONE = 5 * 3600 + 30 * 60
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=UTC)


def ft(dt):
    """Datetime -> FILETIME. A naive datetime is read as the digits it
    holds (a local wall-clock value)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int((dt - _EPOCH).total_seconds()) * 10_000_000


def sps_blob(local_filetime, visits=1):
    """A minimal [MS-PROPSTORE] set: id 24 (VT_FILETIME) and id 6 (VT_I4)."""
    def prop(pid, vt, payload):
        body = struct.pack("<I", pid) + b"\x00" + struct.pack("<HH", vt, 0) + payload
        return struct.pack("<I", 4 + len(body)) + body
    props = (prop(24, 0x0040, struct.pack("<Q", local_filetime))
             + prop(6, 0x0003, struct.pack("<i", visits)))
    body = b"1SPS" + uuid.UUID(int=7).bytes_le + props + struct.pack("<I", 0)
    return struct.pack("<I", 4 + len(body)) + body + struct.pack("<I", 0)


class _Record(dict):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._node = types.SimpleNamespace(data=b"\x00" * 16, key=b"")


class _Table:
    def __init__(self, records):
        self._records = records

    def records(self):
        return iter(self._records)


class _Db:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _Table(self._tables[name])


#: 20:00 UTC on 29 June -> 01:30 local on 30 June.
VISITS = [datetime.datetime(2024, 6, 29, 20, i, tzinfo=UTC) for i in range(5)]
DAILY = "MSHist012024063020240701"


def _container(cid, name):
    return _Record({"ContainerId": cid, "Name": name, "Directory": "",
                    "PartitionId": "", "Flags": 0, "Size": 0, "Limit": 0,
                    "LastScavengeTime": 0, "LastAccessTime": 0,
                    "EntryMaxAge": 0, "SecureDirectories": None})


def _local(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(seconds=ZONE)


def _history_row(i, utc, url=None):
    return _Record({"EntryId": 10 + i,
                    "Url": url or "Visited: alice@https://example.test/p%d" % i,
                    "ModifiedTime": ft(utc), "AccessedTime": ft(utc),
                    "ResponseHeaders": sps_blob(ft(_local(utc))), "Flags": 0})


def _mshist_row(i, utc, url=None):
    return _Record({"EntryId": 50 + i,
                    "Url": url or ":2024063020240701: alice@https://example.test/p%d" % i,
                    "ModifiedTime": ft(_local(utc)), "AccessedTime": ft(utc),
                    "Flags": 0})


def build_parser(with_twins=True, mshist_urls=None):
    tables = {"Containers": [_container(1, "History"), _container(2, DAILY)],
              "Container_1": ([_history_row(i, t) for i, t in enumerate(VISITS)]
                              if with_twins else []),
              "Container_2": [_mshist_row(i, t, (mshist_urls or {}).get(i))
                              for i, t in enumerate(VISITS)]}
    parser = WebCacheParser()
    parser.db = _Db(tables)
    parser.table_names = list(tables)
    parser._load_containers()
    parser.parse_all_entries()
    return parser


def _pairs(rows):
    by_url = {}
    for r in rows:
        by_url.setdefault(r["CleanUrl"], {})[
            "mshist" if r["_record"].get("MSHistFrom") else "twin"] = r
    return [p for p in by_url.values() if len(p) == 2]


# --- the synthetic exhibit is what it claims to be -------------------------

def test_the_zone_is_recovered_from_the_history_twins():
    assert build_parser().derived_tz_offset_seconds == ZONE


# --- History ----------------------------------------------------------------

def test_an_mshist_rows_stored_time_is_its_local_time():
    pairs = _pairs(history_rows_from_parser(build_parser()))
    assert len(pairs) == 5
    for p in pairs:
        assert p["mshist"]["AccessedLocal"] == p["twin"]["AccessedLocal"]


def test_an_mshist_rows_utc_is_the_twins_utc_derived_from_the_zone():
    for p in _pairs(history_rows_from_parser(build_parser())):
        assert p["mshist"]["AccessedUtc"] == p["twin"]["AccessedUtc"]
        basis = p["mshist"]["AccessedUtcBasis"]
        assert "LOCAL" in basis and "UTC+05:30" in basis


def test_without_a_recovered_zone_utc_is_blank_and_says_why():
    parser = build_parser(with_twins=False)
    assert parser.derived_tz_offset_seconds is None
    rows = history_rows_from_parser(parser)
    assert len(rows) == 5
    for row in rows:
        assert row["AccessedUtc"] is None
        assert row["AccessedLocal"] is not None
        assert "no time zone was recovered" in row["AccessedUtcBasis"]


# --- Timeline, exports ------------------------------------------------------

def test_the_timeline_puts_both_copies_of_a_visit_on_the_same_utc_day():
    parser = build_parser()
    buckets = forensic_engine.ForensicEngine().get_timeline(
        "day", parser.all_entries)
    assert [b["period"] for b in buckets] == ["2024-06-29"]
    assert buckets[0]["count"] == 10


def test_every_export_row_states_the_same_instant_for_both_copies():
    parser = build_parser()
    by_url = {}
    for entry in parser.all_entries:
        by_url.setdefault(entry["CleanUrl"], []).append(
            forensic_engine.build_entry_row(entry))
    for rows in by_url.values():
        assert len({r["KeyTimestampUTC"] for r in rows}) == 1
        mshist = next(r for r in rows if r.get("MSHistFrom"))
        twin = next(r for r in rows if not r.get("MSHistFrom"))
        assert mshist["ModifiedTime"] == twin["ModifiedTime"]
        assert mshist["ModifiedTimeLocal"].endswith("LOCAL")
        assert mshist["ModifiedTime_rfc"] == twin["ModifiedTime_rfc"]


# --- File Access, carved rows, the dialog badge ----------------------------

def test_file_access_rows_follow_the_same_clock():
    urls = {i: ":2024063020240701: alice@file:///C:/Users/alice/f%d.txt" % i
            for i in range(5)}
    rows = file_access_rows_from_parser(build_parser(mshist_urls=urls))
    assert len(rows) == 5
    for row, utc in zip(sorted(rows, key=lambda r: r["CleanUrl"]), VISITS):
        assert row["ModifiedTime"] == utc
        assert row["AccessedLocal"] == _local(utc)


def test_a_carved_mshist_record_is_stamped_with_the_zone_and_follows():
    from webcache.shell import recovery_loader
    parser = build_parser()
    carved = dict(next(e for e in parser.all_entries if e.get("MSHistFrom")))
    carved.pop("TzOffsetSeconds", None)
    carved.update(RecoverySource="unallocated page", Source="WebCacheV01.dat",
                  Offset=4096, Page=1, Confidence="high")
    engine = types.SimpleNamespace(structured_records=[carved],
                                   all_artifacts=lambda: [])
    assert recovery_loader.stamp_recovered_clock(engine, parser) == 1
    row = recovery_loader.carved_history_rows(engine)[0]
    twin = next(r for r in history_rows_from_parser(parser)
                if r["CleanUrl"] == row["CleanUrl"]
                and not r["_record"].get("MSHistFrom"))
    assert row["AccessedUtc"] == twin["AccessedUtc"]
    assert row["AccessedLocal"] == twin["AccessedLocal"]


def test_the_dialog_marks_a_derived_utc_inferred_with_its_reason():
    from webcache.shell import detail_fields
    parser = build_parser()
    mshist = next(e for e in parser.all_entries if e.get("MSHistFrom"))
    twin = next(e for e in parser.all_entries if not e.get("MSHistFrom"))
    short, tip = detail_fields.basis_badge("KeyTimestampUTC", carved=False,
                                           record=mshist)
    assert short == "INF" and "LOCAL" in tip and "UTC+05:30" in tip
    assert detail_fields.basis_badge("KeyTimestampUTC", carved=False,
                                     record=twin)[0] == "DER"


# --- the writer that reads ModifiedTime_raw directly ----------------------

def test_the_xlsx_history_sheet_is_in_utc_order_with_pairs_agreeing(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    parser = build_parser()
    engine = forensic_engine.ForensicEngine()
    engine.load_entries(parser.all_entries)
    path = str(tmp_path / "workbook.xlsx")
    engine.export_xlsx(parser.all_entries, path, True, {"examiner": "E"}, {},
                       {}, None, None, None, engine.get_statistics())
    sheet = openpyxl.load_workbook(path)["History"]
    header = [c.value for c in sheet[1]]
    col = header.index("Visit (UTC)")
    visits = [row[col].value for row in sheet.iter_rows(min_row=2)]
    assert len(visits) == 10
    assert len(set(visits)) == 5
    assert visits == sorted(visits, reverse=True)


# --- the badge branches ---------------------------------------

def test_the_badge_is_not_inf_when_the_key_instant_is_a_true_utc_column():
    from webcache.shell import detail_fields
    rec = dict(next(e for e in build_parser().all_entries
                    if e.get("MSHistFrom")))
    rec["ModifiedTime_raw"] = 0    # key_timestamp falls to AccessedTime (UTC)
    assert detail_fields.basis_badge("KeyTimestampUTC", carved=False,
                                     record=rec)[0] == "DER"


def test_an_mshist_local_visit_is_badged_as_the_stored_column_not_sps24():
    from webcache.shell import detail_fields
    rec = next(e for e in build_parser().all_entries if e.get("MSHistFrom"))
    assert (detail_fields.basis_badge("SPS_LastVisitLocal", carved=False,
                                      record=rec)
            == detail_fields.basis_badge("ModifiedTimeLocal"))


def test_the_no_zone_badge_says_why():
    from webcache.shell import detail_fields
    rec = next(e for e in build_parser(with_twins=False).all_entries
               if e.get("MSHistFrom"))
    short, tip = detail_fields.basis_badge("KeyTimestampUTC", carved=False,
                                           record=rec)
    assert short == "INF" and "no time zone was recovered" in tip


# --- DST: one exhibit, two offsets ------------------------------
#
# A zone an hour apart in winter and summer (-05:00 / -04:00). Each History
# twin's SPS id-24 LOCAL value carries its own season's offset; each MSHist
# copy stores that visit's LOCAL digits. A single rounded median applied to
# every date is an hour wrong for the minority season -- and on an even
# split the median sits BETWEEN the two, an invented -04:30.

WINTER, SUMMER = -5 * 3600, -4 * 3600


def _local_at(utc, offset):
    return utc.replace(tzinfo=None) + datetime.timedelta(seconds=offset)


def build_dst_parser(winter=4, summer=3, unpaired=()):
    """`unpaired`: (utc, offset) visits held ONLY by an MSHist container,
    under a URL no History twin shares."""
    visits = ([(datetime.datetime(2024, 1, 10 + i, 15, 0, tzinfo=UTC), WINTER)
               for i in range(winter)]
              + [(datetime.datetime(2024, 7, 10 + i, 15, 0, tzinfo=UTC), SUMMER)
                 for i in range(summer)])
    history, mshist = [], []
    for i, (utc, off) in enumerate(visits):
        local = _local_at(utc, off)
        history.append(_Record({
            "EntryId": 10 + i,
            "Url": "Visited: alice@https://example.test/d%d" % i,
            "ModifiedTime": ft(utc), "AccessedTime": ft(utc),
            "ResponseHeaders": sps_blob(ft(local)), "Flags": 0}))
        mshist.append(_Record({
            "EntryId": 50 + i,
            "Url": ":2024010120241231: alice@https://example.test/d%d" % i,
            "ModifiedTime": ft(local), "AccessedTime": ft(utc), "Flags": 0}))
    for j, (utc, off) in enumerate(unpaired):
        mshist.append(_Record({
            "EntryId": 90 + j,
            "Url": ":2024010120241231: alice@https://example.test/only%d" % j,
            "ModifiedTime": ft(_local_at(utc, off)), "AccessedTime": ft(utc),
            "Flags": 0}))
    tables = {"Containers": [_container(1, "History"),
                             _container(2, "MSHist012024010120241231")],
              "Container_1": history, "Container_2": mshist}
    parser = WebCacheParser()
    parser.db = _Db(tables)
    parser.table_names = list(tables)
    parser._load_containers()
    parser.parse_all_entries()
    return parser


def test_across_dst_each_paired_mshist_utc_is_its_twins_utc():
    pairs = _pairs(history_rows_from_parser(build_dst_parser()))
    assert len(pairs) == 7
    for p in pairs:
        assert p["mshist"]["AccessedUtc"] == p["twin"]["AccessedUtc"]
        assert p["mshist"]["AccessedLocal"] == p["twin"]["AccessedLocal"]


def test_across_dst_an_unpaired_record_takes_the_offset_nearest_in_time():
    summer_only = datetime.datetime(2024, 7, 20, 15, 0, tzinfo=UTC)
    winter_only = datetime.datetime(2024, 1, 20, 15, 0, tzinfo=UTC)
    parser = build_dst_parser(
        unpaired=[(summer_only, SUMMER), (winter_only, WINTER)])
    rows = {r["CleanUrl"]: r for r in history_rows_from_parser(parser)}
    summer = rows["https://example.test/only0"]
    winter = rows["https://example.test/only1"]
    assert summer["AccessedUtc"] == summer_only
    assert winter["AccessedUtc"] == winter_only
    assert "UTC-04:00" in summer["AccessedUtcBasis"]
    assert "nearest" in summer["AccessedUtcBasis"]
    assert "UTC-05:00" in winter["AccessedUtcBasis"]


def test_an_even_split_never_fabricates_an_offset_between_the_two():
    parser = build_dst_parser(winter=3, summer=3,
                              unpaired=[(datetime.datetime(
                                  2024, 7, 20, 15, 0, tzinfo=UTC), SUMMER)])
    assert parser.derived_tz_offset_seconds in (WINTER, SUMMER)
    offsets = {e.get("TzOffsetSeconds") for e in parser.all_entries
               if e.get("MSHistFrom")}
    assert offsets <= {WINTER, SUMMER}
    notes = " ".join(r["AccessedUtcBasis"]
                     for r in history_rows_from_parser(parser))
    assert "UTC-04:30" not in notes
    assert "UTC-04:30" not in " ".join(parser.decision_log)


def test_the_decision_log_names_every_offset_the_exhibit_shows():
    log = " ".join(build_dst_parser().decision_log)
    assert "UTC-05:00" in log and "UTC-04:00" in log


# --- no zone recovered: every consumer says so ------------------

_FIX_URL = "https://tiles.example.test/v1?clientlocation=51.5074|-0.1278"


def test_the_timeline_says_unplaced_local_visits_have_a_time_not_none():
    from webcache.shell import timeline_loader
    inputs = timeline_loader.timeline_inputs(
        build_parser(with_twins=False).all_entries)
    rows = timeline_loader.period_rows(inputs, "day")
    note = timeline_loader.grain_note(inputs, rows, "day", scan_run=True)
    assert "no time zone was recovered" in note
    assert "5 carry a LOCAL time" in note
    assert "carry none" not in note


def _dated(when):
    return {"Url": "https://example.test/t", "CleanUrl": "https://example.test/t",
            "ContainerType": "Content", "AccessedTime_raw": ft(when)}


def test_a_silence_that_may_hold_an_unplaced_local_visit_is_withheld_and_named():
    base = datetime.datetime(2024, 6, 20, 0, 0, tzinfo=UTC)
    dated = ([_dated(base + datetime.timedelta(hours=h)) for h in range(3)]
             + [_dated(datetime.datetime(2024, 6, 27, h, 0, tzinfo=UTC))
                for h in range(6)]
             + [_dated(datetime.datetime(2024, 6, 30, 6 + h, 0, tzinfo=UTC))
                for h in range(6)])
    unplaced = [e for e in build_parser(with_twins=False).all_entries
                if e.get("MSHistFrom")]
    engine = forensic_engine.ForensicEngine()
    engine.load_entries(dated + unplaced)
    voids = engine.analyze_time_voids(24, [])
    # 20 Jun 02:00 -> 27 Jun 00:00 is far from any unplaced visit and
    # stands; 27 Jun 05:00 -> 30 Jun 06:00 may hold the five local
    # 30 Jun 01:30 visits under any real offset, and is withheld.
    assert [v["From"][:10] for v in voids] == ["2024-06-20"]
    report = {}
    engine.analyze_time_voids(24, [], report=report)
    assert report == {"unplaced_records": 5, "withheld_voids": 1}


def test_the_findings_note_names_the_withheld_silences():
    from webcache.shell import iocs_loader
    unplaced = [e for e in build_parser(with_twins=False).all_entries
                if e.get("MSHistFrom")]
    dated = ([_dated(datetime.datetime(2024, 6, 27, h, 0, tzinfo=UTC))
              for h in range(6)]
             + [_dated(datetime.datetime(2024, 6, 30, 6 + h, 0, tzinfo=UTC))
                for h in range(6)])
    rows, note = iocs_loader.time_void_rows_and_note(dated + unplaced)
    assert rows == []
    assert "5" in note and "no time zone was recovered" in note
    assert "1 silence" in note


def test_location_never_swaps_in_accessed_time_for_an_unplaced_visit():
    from webcache.engine import geolocation
    parser = build_parser(with_twins=False,
                          mshist_urls={0: ":2024063020240701: alice@" + _FIX_URL})
    entry = next(e for e in parser.all_entries if e["EntryId"] == 50)
    fixes = geolocation.collect([entry])
    assert len(fixes) == 1
    assert fixes[0]["RecordTimeUTC"] == ""
    assert "no time zone was recovered" in fixes[0]["RecordTimeNote"]


def test_a_carved_unplaced_fix_states_why_the_cache_time_is_blank():
    from webcache.shell import location_loader
    parser = build_parser(with_twins=False,
                          mshist_urls={0: ":2024063020240701: alice@" + _FIX_URL})
    carved = dict(next(e for e in parser.all_entries if e["EntryId"] == 50))
    carved.update(RecoverySource="unallocated page", Source="WebCacheV01.dat")
    fixes = location_loader.position_fixes([], [carved])
    assert len(fixes) == 1
    assert fixes[0]["RecordTimeUtc"] is None
    assert "LOCAL" in fixes[0]["Disagreement"]


# --- the raw FILETIME sits beside the value it decodes to ------

def _dialog_fields(parser):
    from webcache.shell import detail_fields
    row = next(r for r in history_rows_from_parser(parser)
               if r["_record"].get("MSHistFrom"))
    fields = {f.key: f for f in
              detail_fields.flatten(detail_fields.fields_for(row))}
    return row["_record"], fields


def test_the_raw_filetime_is_printed_beside_the_local_value_it_decodes_to():
    record, fields = _dialog_fields(build_parser())
    stored = record["ModifiedTime_raw"]
    assert fields["ModifiedTimeLocal"].raw_value == stored
    assert "[raw FILETIME: %d]" % stored in fields["ModifiedTimeLocal"].display_value
    utc = fields["ModifiedTime"]
    assert utc.raw_value is None
    assert "[raw FILETIME: %d]" % stored not in utc.display_value
    assert "derived" in utc.display_value
    assert "19,800 s" in utc.display_value and "UTC+05:30" in utc.display_value


def test_with_no_zone_the_utc_row_says_why_and_the_raw_stays_with_local():
    record, fields = _dialog_fields(build_parser(with_twins=False))
    stored = record["ModifiedTime_raw"]
    assert fields["ModifiedTimeLocal"].raw_value == stored
    assert "no time zone was recovered" in fields["ModifiedTime"].display_value
    assert ("[raw FILETIME: %d]" % stored
            not in fields["ModifiedTime"].display_value)
