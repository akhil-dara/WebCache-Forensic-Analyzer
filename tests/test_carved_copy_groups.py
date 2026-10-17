"""Carved "copies" are grouped only when they are
the same URL at the same time in the SAME container, never on a URL
alone, and the label says what was compared -- not "identical", since no
bytes were compared. A carved MSHist record and its carved History twin
are one visit in two containers, not copies."""
import datetime
import types

from webcache.shell import recovery_loader

UTC = datetime.timezone.utc
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=UTC)
FT = int((datetime.datetime(2024, 6, 29, 10, tzinfo=UTC) - _EPOCH)
         .total_seconds()) * 10_000_000


def carved(url, offset, when=FT, container="History", **extra):
    record = {"Url": url, "CleanUrl": url, "ContainerType": "History",
              "ContainerName": container,
              "RecoverySource": "Structured record reconstruction",
              "Source": "WebCacheV01.dat", "Offset": offset, "Page": 1,
              "Confidence": "high", "ModifiedTime_raw": when}
    record.update(extra)
    return record


def _rows(records):
    return recovery_loader.carved_history_rows(
        types.SimpleNamespace(structured_records=list(records)))


def _copies(rows):
    return [r.get("Copies") for r in rows]


def test_same_url_and_time_in_the_same_container_is_counted_and_worded():
    rows = _rows([carved("https://dup.example.test/", 4096 * i)
                  for i in (1, 2)])
    assert _copies(rows) == ["2 copies (same URL, time and container)",
                             "copy 2 of 2"]


ZONE = 19800


def test_the_same_url_and_time_in_two_containers_is_not_a_copy():
    """The MSHist copy stores the LOCAL digits; with its stamped offset its
    derived UTC is the History record's -- the same instant, two
    containers."""
    rows = _rows([
        carved("https://pair.example.test/", 4096),
        carved("https://pair.example.test/", 8192,
               when=FT + ZONE * 10_000_000,
               container="MSHist012024062920240630",
               MSHistFrom="2024-06-29", MSHistTo="2024-06-30",
               TzOffsetSeconds=ZONE)])
    assert rows[0]["AccessedUtc"] == rows[1]["AccessedUtc"] is not None
    assert _copies(rows) == ["", ""]


def test_records_with_no_usable_time_are_never_grouped_on_the_url_alone():
    rows = _rows([carved("https://undated.example.test/", 4096 * i, when=0)
                  for i in (1, 2, 3)])
    assert _copies(rows) == ["", "", ""]


def test_a_carved_mshist_record_is_linked_to_its_carved_history_twin():
    """stamp_recovered_clock pairs the carved side, as parsing does live."""
    local = FT + ZONE * 10_000_000
    history = carved("https://pair.example.test/", 4096,
                     SPS_LastVisitLocal_raw=local, EntryId=7)
    mshist = carved("https://pair.example.test/", 8192, when=local,
                    container="MSHist012024062920240630",
                    MSHistFrom="2024-06-29", MSHistTo="2024-06-30",
                    EntryId=31)
    engine = types.SimpleNamespace(structured_records=[history, mshist])
    parser = types.SimpleNamespace(derived_tz_offset_seconds=ZONE,
                                   zone_observations=[])
    recovery_loader.stamp_recovered_clock(engine, parser)
    rows = recovery_loader.carved_history_rows(engine)
    assert [r.get("SameVisit") for r in rows] == [
        "also in its MSHist daily copy for 2024-06-29 "
        "(MSHist012024062920240630)",
        "History record History #7 (this is its MSHist daily copy)"]
    assert _copies(rows) == ["", ""]
