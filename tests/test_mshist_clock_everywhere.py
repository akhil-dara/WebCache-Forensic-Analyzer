"""An MSHist ModifiedTime reads the same in
Search and the Table Browser as it does in History -- local, with the UTC
derived with THAT record's own offset -- and is never labelled UTC.

The synthetic exhibits are test_mshist_local_clock.py's: five visits held
twice (History + a daily MSHist container), and a two-offset (DST)
exhibit whose minority season is an hour away from the principal zone.
"""
import datetime
import types

from webcache.engine import local_clock
from webcache.shell import recovery_loader, table_browser_loader
from webcache.shell.evidence_loader import history_rows_from_parser
from webcache.shell.record_kinds import K_CARVED_STRUCT
from tests.test_mshist_local_clock import (SUMMER, VISITS, ZONE,
                                           build_dst_parser, build_parser, ft)


class _ColTable:
    def __init__(self, table):
        self._table = table
        records = list(table.records())
        names = []
        for rec in records:
            for key in rec:
                if key not in names:
                    names.append(key)
        self.columns = [types.SimpleNamespace(name=n) for n in names]

    def records(self):
        return self._table.records()


class _ColDb:
    def __init__(self, db):
        self._db = db

    def table(self, name):
        return _ColTable(self._db.table(name))


def _with_columns(parser):
    parser.db = _ColDb(parser.db)
    return parser


def _mshist_hits(parser, keyword):
    return [h for h in parser.search_all_tables(keyword)
            if h["table"] == "Container_2"]


# --- finding 2: Search -------------------------------------------------------

#: VISITS[0] is 20:00 UTC on 29 June: 01:30 local on 30 June at +05:30.
UTC_TEXT = "2024-06-29 20:00:00"
LOCAL_TEXT = "2024-06-30 01:30:00"


def test_search_decodes_an_mshist_modified_time_as_local_and_derived_utc():
    parser = _with_columns(build_parser())
    hit = _mshist_hits(parser, LOCAL_TEXT)[0]
    decoded = hit["row"]["ModifiedTime"]
    assert decoded.startswith("local: %s" % LOCAL_TEXT), decoded
    assert "UTC (derived, UTC+05:30): %s" % UTC_TEXT in decoded, decoded
    assert "%s UTC" % LOCAL_TEXT not in decoded


def test_searching_the_true_utc_instant_hits_the_mshist_modified_time():
    parser = _with_columns(build_parser())
    hits = _mshist_hits(parser, UTC_TEXT)
    assert any("ModifiedTime" in h["matched_columns"] for h in hits)


def test_the_local_digits_hit_the_local_reading_never_a_utc_claim():
    parser = _with_columns(build_parser())
    hit = _mshist_hits(parser, LOCAL_TEXT)[0]
    assert "ModifiedTime" in hit["matched_columns"]
    assert "%s UTC" % LOCAL_TEXT not in hit["match_value"]


def test_a_history_container_modified_time_still_reads_utc():
    parser = _with_columns(build_parser())
    hit = [h for h in parser.search_all_tables(UTC_TEXT)
           if h["table"] == "Container_1"][0]
    assert hit["row"]["ModifiedTime"].startswith(UTC_TEXT)
    assert hit["row"]["ModifiedTime"].endswith("UTC")


def test_a_carved_mshist_modified_time_is_searched_as_local_and_derived_utc():
    local = VISITS[0].replace(tzinfo=None) + datetime.timedelta(seconds=ZONE)
    record = {"MSHistFrom": "20240630", "ModifiedTime_raw": ft(local),
              local_clock.TZ_OFFSET_KEY: ZONE,
              local_clock.TZ_SOURCE_KEY: local_clock.SOURCE_ZONE}
    values = dict((f, v) for f, v, _w in recovery_loader.searched_values(
        {"_record": record, "_kind": K_CARVED_STRUCT}))
    assert values["ModifiedTime"].startswith("local: %s" % LOCAL_TEXT)
    assert "UTC (derived, UTC+05:30): %s" % UTC_TEXT in values["ModifiedTime"]


# --- finding 3: the Table Browser uses the record's own offset --------------

def _history_utc(parser, entry_id):
    for row in history_rows_from_parser(parser):
        record = row["_record"]
        if record.get("ContainerId") == 2 and record.get("EntryId") == entry_id:
            return record, row["AccessedUtc"]
    raise AssertionError("no MSHist row %d" % entry_id)


def test_a_minority_season_row_reads_the_same_utc_as_history():
    parser = _with_columns(build_dst_parser(winter=4, summer=3))
    # The principal zone is winter's; entry 54 is a summer visit.
    assert parser.derived_tz_offset_seconds != SUMMER
    record, _ = _history_utc(parser, 54)
    assert record[local_clock.TZ_OFFSET_KEY] == SUMMER
    page = table_browser_loader.table_page(parser, "Container_2")
    col = page["columns"].index("ModifiedTime")
    eid = page["columns"].index("EntryId")
    cell = next(r[col] for r in page["rows"] if r[eid]["text"] == "54")
    utc = local_clock.utc_raw(record, "ModifiedTime_raw")
    expected = (datetime.datetime(1601, 1, 1)
                + datetime.timedelta(microseconds=utc // 10)).strftime(
                    "%Y-%m-%d %H:%M:%S")
    assert "UTC (derived, %s): %s" % (local_clock.zone_label(SUMMER),
                                      expected) in cell["decoded"], cell
    assert "recovered zone" not in cell["decoded"]


def test_search_uses_the_records_own_offset_too():
    parser = _with_columns(build_dst_parser(winter=4, summer=3))
    record, _ = _history_utc(parser, 54)
    local = local_clock.local_naive(record).strftime("%Y-%m-%d %H:%M:%S")
    hit = _mshist_hits(parser, local)[0]
    assert "UTC (derived, %s)" % local_clock.zone_label(SUMMER) in (
        hit["row"]["ModifiedTime"])


def test_a_row_with_no_parsed_record_says_it_used_the_recovered_zone():
    cell = table_browser_loader._cell(
        types.SimpleNamespace(
            derived_tz_offset_seconds=ZONE, all_entries=[],
            container_map={2: "MSHist012024063020240701"},
            raw_rendering=str, raw_type_name=lambda v: "integer"),
        ft(datetime.datetime(2024, 6, 30, 1, 30)), column="ModifiedTime",
        table="Container_2")
    assert "(recovered zone)" in cell["decoded"]
