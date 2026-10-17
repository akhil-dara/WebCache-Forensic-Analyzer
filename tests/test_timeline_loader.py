"""timeline_loader: what is on the timeline, what is not, and the silences.

THE ONE ADMISSION GATE. An earlier version gated carved records on the
DECODED fields (ModifiedTime/AccessedTime/CreationTime) while its
bucketing read the `_raw` siblings -- so a carved record with a decoded
string and no raw value passed the gate and was then silently dropped:
admitted, counted nowhere, explained nowhere. Here there is ONE predicate,
forensic_engine.key_timestamp(), and the loader, the badge count and the
excluded-count line all read it. The tests below are what hold that.

THE SILENCES. get_timeline emits only periods that actually received a
record; an empty bucket is never fabricated as a zero-count row, because
inventing filler is inventing evidence. The SIZE of each silence is a
property of the row that follows it (GapBefore), measured in buckets at
the current grain -- the same unit the rows on screen are in, so it
rescales when the grain does and cannot disagree with anything else on the
screen.
"""
import datetime

import pytest

from webcache.provenance import ABSENCE_NOT_APPLICABLE, CARVED_ORIGIN
from webcache.shell import record_kinds, timeline_loader

_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


def _filetime(*args):
    dt = datetime.datetime(*args, tzinfo=datetime.timezone.utc)
    return int((dt - _EPOCH).total_seconds() * 10_000_000)


def _entry(**overrides):
    base = {
        "Url": "https://a.example/page",
        "CleanUrl": "https://a.example/page",
        "ContainerType": "History",
        "ContainerId": 3,
        "ContainerName": "History",
        "EntryId": 1,
        "ModifiedTime_raw": _filetime(2024, 6, 15, 9, 0, 0),
    }
    base.update(overrides)
    return base


def _grains():
    return [g[0] for g in timeline_loader.GRAINS]


# --- the gate -------------------------------------------------------------

def test_a_record_whose_only_timestamp_is_creation_time_is_on_the_timeline():
    """THE BADGE BUG, asserted rather than commented. A badge counting
    `AccessedTime or ModifiedTime` that omits CreationTime under-counts
    against its own view. One predicate --
    key_timestamp, which walks all three -- removes the class of bug, not
    just this instance of it."""
    entry = _entry(ModifiedTime_raw=0, AccessedTime_raw=0,
                   CreationTime_raw=_filetime(2024, 6, 15, 9, 0, 0))
    inputs = timeline_loader.timeline_inputs([entry])

    assert timeline_loader.dated_record_count(inputs) == 1
    assert inputs.undated_live == 0
    for grain in _grains():
        rows = timeline_loader.period_rows(inputs, grain)
        assert sum(r["Records"] for r in rows) == 1, grain


def test_a_record_with_no_timestamp_at_all_is_counted_and_kept_out():
    entry = _entry(ModifiedTime_raw=0)
    inputs = timeline_loader.timeline_inputs([entry])

    assert timeline_loader.dated_record_count(inputs) == 0
    assert inputs.undated_live == 1
    assert inputs.live_total == 1
    assert timeline_loader.period_rows(inputs, "day") == []


def test_a_carved_record_with_a_decoded_time_but_no_raw_is_never_admitted():
    """THE GATE/BUCKET MISMATCH. A decoded string is not a bucketable
    instant; the record is excluded by the same predicate that buckets, and
    it is COUNTED as excluded rather than admitted and then dropped where
    nothing on screen could account for it."""
    carved = _entry(ModifiedTime="2024-06-15 09:00:00 UTC")
    carved.pop("ModifiedTime_raw")
    inputs = timeline_loader.timeline_inputs([], [carved])

    assert inputs.undated_carved == 1
    assert inputs.carved_total == 0
    assert timeline_loader.dated_record_count(inputs) == 0
    assert timeline_loader.period_rows(inputs, "day") == []


def test_building_the_inputs_never_writes_on_an_engine_dict():
    """The engine dicts are shared with Domains, Indicators, Dashboard and
    every export. Carved-ness is an IDENTITY SET here, never an Origin key
    stamped onto somebody else's record."""
    live = _entry()
    carved = _entry(Url="https://b.example/x")
    before_live, before_carved = dict(live), dict(carved)

    timeline_loader.timeline_inputs([live], [carved])

    assert live == before_live
    assert carved == before_carved
    assert "Origin" not in carved


# --- every admitted record is accounted for -------------------------------

def _mixed_inputs():
    live = [_entry(EntryId=i, ModifiedTime_raw=_filetime(2024, 6, 15, 9, i))
            for i in range(4)]
    live.append(_entry(EntryId=99, ModifiedTime_raw=0))          # undated
    carved = [_entry(EntryId=100 + i, Url="https://b.example/%d" % i,
                     ModifiedTime_raw=_filetime(2024, 7, 2, 11, i))
              for i in range(3)]
    return timeline_loader.timeline_inputs(live, carved)


@pytest.mark.parametrize("grain", ["minute", "hour", "day", "month"])
def test_the_periods_account_for_every_admitted_record(grain):
    inputs = _mixed_inputs()
    rows = timeline_loader.period_rows(inputs, grain)
    assert sum(r["Records"] for r in rows) == \
        timeline_loader.dated_record_count(inputs)


@pytest.mark.parametrize("grain", ["minute", "hour", "day", "month"])
def test_the_periods_account_for_every_carved_record(grain):
    inputs = _mixed_inputs()
    rows = timeline_loader.period_rows(inputs, grain)
    assert sum(r["Carved"] for r in rows) == inputs.carved_total
    assert inputs.carved_total == 3


def test_the_carved_count_is_a_count_never_a_flag():
    """A period holds live and carved records together; a boolean here
    would say the whole period was carved."""
    live = [_entry(EntryId=1)]
    carved = [_entry(EntryId=2), _entry(EntryId=3)]
    inputs = timeline_loader.timeline_inputs(live, carved)
    row = timeline_loader.period_rows(inputs, "day")[0]
    assert row["Records"] == 3
    assert row["Carved"] == 2


# --- the silences ---------------------------------------------------------

@pytest.mark.parametrize("grain,a,b,expected", [
    ("minute", "2024-06-15 09:00", "2024-06-15 09:01", 0),
    ("minute", "2024-06-15 09:00", "2024-06-15 09:05", 4),
    ("hour", "2024-06-15 09:00", "2024-06-16 09:00", 23),
    ("day", "2024-06-15", "2024-06-16", 0),
    ("day", "2024-06-01", "2024-06-23", 21),
    ("month", "2024-06", "2024-07", 0),
    # Across a year boundary, which is the one the naive month arithmetic
    # (b.month - a.month) gets wrong -- and gets wrong NEGATIVELY, so it
    # would read as a silence that ran backwards.
    ("month", "2024-11", "2025-02", 2),
    ("month", "2023-01", "2025-01", 23),
])
def test_empty_buckets_between_is_exact_at_every_grain(grain, a, b, expected):
    assert timeline_loader.empty_buckets_between(grain, a, b) == expected


@pytest.mark.parametrize("grain", ["minute", "hour", "day", "month"])
def test_each_gap_measures_the_silence_before_its_own_row(grain):
    """The arithmetic the column promises: this period, plus the empty
    buckets it declares, plus one, lands on the next period."""
    live = [
        _entry(EntryId=1, ModifiedTime_raw=_filetime(2024, 1, 5, 3, 4)),
        _entry(EntryId=2, ModifiedTime_raw=_filetime(2024, 3, 9, 7, 30)),
        _entry(EntryId=3, ModifiedTime_raw=_filetime(2025, 2, 1, 0, 0)),
    ]
    inputs = timeline_loader.timeline_inputs(live)
    rows = timeline_loader.period_rows(inputs, grain)
    assert len(rows) == 3, grain
    for previous, current in zip(rows, rows[1:]):
        assert current["GapBefore"] == timeline_loader.empty_buckets_between(
            grain, previous["Period"], current["Period"])


def test_the_first_row_says_not_applicable_never_zero():
    """There is no previous period, so there is no silence to measure. A
    0 there would assert that the row before it was adjacent -- to
    nothing."""
    inputs = timeline_loader.timeline_inputs([_entry()])
    rows = timeline_loader.period_rows(inputs, "day")
    assert rows[0]["GapBefore"] == ABSENCE_NOT_APPLICABLE


def test_no_row_leaves_a_gap_cell_blank():
    inputs = _mixed_inputs()
    for grain in _grains():
        for row in timeline_loader.period_rows(inputs, grain):
            assert row["GapBefore"] not in (None, ""), (grain, row["Period"])


# --- the row is an aggregate and says so ----------------------------------

def test_a_period_row_is_an_aggregate_that_names_its_members():
    a = _entry(EntryId=1)
    b = _entry(EntryId=2)
    rows = timeline_loader.period_rows(
        timeline_loader.timeline_inputs([a, b]), "day")

    assert rows[0]["_kind"] is record_kinds.K_PERIOD
    assert record_kinds.K_PERIOD in record_kinds.AGGREGATES
    members = rows[0]["_members"]
    assert any(m is a for m in members) and any(m is b for m in members), (
        "the engine dicts themselves, by reference -- one pointer per "
        "record, not a second copy of the set")


def test_a_period_row_carries_a_real_datetime_for_its_first_instant():
    """The Period cell is a STRING (a month bucket is "2024-06", which no
    date parser reads), so the filterable instant has to be its own
    column -- otherwise the funnel offers before/after/between operators
    that match nothing forever."""
    rows = timeline_loader.period_rows(
        timeline_loader.timeline_inputs([_entry()]), "day")
    start = rows[0]["PeriodStart"]
    assert isinstance(start, datetime.datetime)
    assert (start.year, start.month, start.day) == (2024, 6, 15)
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    assert isinstance(rows[0]["Period"], str)


def test_period_start_does_not_take_the_slow_strptime_path():
    """datetime.strptime re-resolves the current locale and
    re-compiles its format's regex on EVERY call -- there is no cache
    across calls, unlike a parser built once. Profiled on this machine
    building all four grains for 100,000 synthetic dated records:
    _period_start's strptime chain alone accounted for 62 of 144 profiled
    seconds (43%), called roughly three times per bucket (once for its
    own PeriodStart, twice more inside empty_buckets_between's two
    _period_start calls for adjacent buckets).

    Pinned in a way that holds across Python versions rather than by
    naming strptime's private internals (which differ 3.13 to 3.14):
    CPython defers importing the `_strptime` module until strptime is
    actually called at all, precisely because building it is expensive
    -- so if `_strptime` never enters sys.modules, strptime was never
    reached, on any version.
    """
    import sys
    sys.modules.pop("_strptime", None)
    for grain, period in (("minute", "2024-06-15 09:04"),
                          ("hour", "2024-06-15 09:00"),
                          ("day", "2024-06-15"),
                          ("month", "2024-06")):
        start = timeline_loader._period_start(grain, period)
        assert isinstance(start, datetime.datetime)
    assert "_strptime" not in sys.modules, (
        "_period_start must not reach for datetime.strptime")


def test_the_busiest_period_has_a_share_of_one_and_the_rest_are_fractions():
    live = [_entry(EntryId=i, ModifiedTime_raw=_filetime(2024, 6, 15, 9, 0))
            for i in range(4)]
    live.append(_entry(EntryId=9, ModifiedTime_raw=_filetime(2024, 6, 16, 9, 0)))
    rows = timeline_loader.period_rows(
        timeline_loader.timeline_inputs(live), "day")

    assert rows[0]["Share"] == 1.0
    assert rows[1]["Share"] == 0.25
    for row in rows:
        assert 0.0 <= row["Share"] <= 1.0


def test_the_domain_cell_names_every_domain_busiest_first():
    """No "+N more": a period's cell names every host it holds."""
    live = [_entry(EntryId=i, Url="https://h%d.example/x" % i,
                   CleanUrl="https://h%d.example/x" % i) for i in range(9)]
    live.append(_entry(EntryId=99, Url="https://h4.example/y",
                       CleanUrl="https://h4.example/y"))
    row = timeline_loader.period_rows(
        timeline_loader.timeline_inputs(live), "day")[0]

    assert row["Domains"].count(" (") == 9
    assert "more domain" not in row["Domains"]
    assert row["Domains"].startswith("h4.example (2)")


def test_a_carved_record_with_no_container_type_is_named_not_left_blank():
    carved = _entry(EntryId=5)
    carved.pop("ContainerType")
    row = timeline_loader.period_rows(
        timeline_loader.timeline_inputs([], [carved]), "day")[0]
    assert timeline_loader.CARVED_TYPE_UNKNOWN in row["Types"]


def test_a_period_row_stays_inside_its_size_bucket():
    """Ten keys, and ten is the ceiling: the dict table steps at the
    eleventh, and the minute grain on a large exhibit produces tens of
    thousands of period rows. `_record` is ABSENT rather than present-and-
    None for exactly this reason -- detail_fields tolerates its absence."""
    import sys

    row = timeline_loader.period_rows(
        timeline_loader.timeline_inputs([_entry()]), "day")[0]
    assert len(row) <= 10, "%d keys" % len(row)
    assert sys.getsizeof(row) == sys.getsizeof(
        {("k%03d" % i): i for i in range(10)})
    assert "_record" not in row


# --- the records inside one period ----------------------------------------

def test_record_rows_shape_one_row_per_member_pointing_at_the_engine_dict():
    live = _entry(EntryId=1)
    carved = _entry(EntryId=2, Url="https://b.example/x",
                    CleanUrl="https://b.example/x")
    inputs = timeline_loader.timeline_inputs([live], [carved])
    period = timeline_loader.period_rows(inputs, "day")[0]

    rows = timeline_loader.record_rows(period, inputs)
    assert len(rows) == 2
    by_origin = {r["Origin"]: r for r in rows}
    assert by_origin["Live record"]["_record"] is live
    assert by_origin[CARVED_ORIGIN]["_record"] is carved


def test_a_record_row_states_which_column_its_time_came_from():
    """"The visit was written" and "the cache entry was touched" are
    different claims about what happened, and one UTC column collapses
    them."""
    touched = _entry(EntryId=7, ModifiedTime_raw=0,
                     AccessedTime_raw=_filetime(2024, 6, 15, 9, 0))
    inputs = timeline_loader.timeline_inputs([touched])
    period = timeline_loader.period_rows(inputs, "day")[0]
    row = timeline_loader.record_rows(period, inputs)[0]

    assert isinstance(row["KeyTimeUtc"], datetime.datetime)
    assert "AccessedTime" in row["KeyTimeBasis"]
    assert row["_kind"] in record_kinds.ALL


def test_a_record_row_names_the_counter_its_visit_count_came_from():
    entry = _entry(EntryId=8, SPS_VisitCount=4)
    inputs = timeline_loader.timeline_inputs([entry])
    period = timeline_loader.period_rows(inputs, "day")[0]
    row = timeline_loader.record_rows(period, inputs)[0]
    assert row["VisitCount"] == 4
    assert "SPS" in row["VisitCountSource"]


# --- the count line -------------------------------------------------------

def test_the_note_states_what_is_on_the_timeline_and_what_is_not():
    inputs = _mixed_inputs()
    rows = timeline_loader.period_rows(inputs, "day")
    note = timeline_loader.grain_note(inputs, rows, "day", scan_run=True)

    assert "7 of 8 records" in note
    assert "1 carr" in note and "not on this timeline" in note


def test_the_note_states_the_silences_and_what_a_silence_is_not():
    inputs = _mixed_inputs()
    rows = timeline_loader.period_rows(inputs, "day")
    note = timeline_loader.grain_note(inputs, rows, "day", scan_run=True)

    assert "silence" in note
    assert "not necessarily no activity" in note


def test_before_a_scan_the_note_says_so_rather_than_showing_a_zero():
    inputs = timeline_loader.timeline_inputs([_entry()])
    rows = timeline_loader.period_rows(inputs, "day")
    note = timeline_loader.grain_note(inputs, rows, "day", scan_run=False)
    assert "no recovery scan has run" in note
    assert "recovered" not in note.split("no recovery scan has run")[0]


def test_after_a_scan_the_note_states_the_recovered_count():
    inputs = _mixed_inputs()
    rows = timeline_loader.period_rows(inputs, "day")
    note = timeline_loader.grain_note(inputs, rows, "day", scan_run=True)
    assert "3 recovered" in note
    assert "no recovery scan has run" not in note


def test_no_visible_string_asserts_more_than_it_can_show():
    """The standing rule for on-screen text in this application."""
    inputs = _mixed_inputs()
    rows = timeline_loader.period_rows(inputs, "day")
    texts = [timeline_loader.grain_note(inputs, rows, g, scan_run=s)
             for g in _grains() for s in (True, False)]
    for text in texts:
        lowered = text.lower()
        for word in ("confirm", "proves", "demonstrates"):
            assert word not in lowered, (word, text)


# --- the gate and the bucketer must be the SAME predicate ------------------
#
# This file's own header says there is ONE predicate and that the loader,
# the badge and the excluded-count line all read it. They do not, quite.
#
# _is_dated admits on bool(raw) -- any non-zero integer. The bucketer takes
# that same raw value through filetime_to_dt, which returns None for values
# outside the representable range. A record with a non-zero but undecodable
# raw stamp therefore passes the gate, is counted in the badge and in
# "N records carry a usable timestamp", and is then bucketed nowhere.
#
# That is precisely the earlier defect the header describes -- admitted,
# counted nowhere, explained nowhere -- reintroduced one layer down. A
# timestamp that cannot be decoded is not a usable timestamp.

_UNDECODABLE_FILETIME = 2650467743990000001


def test_a_raw_stamp_that_cannot_be_decoded_is_not_counted_as_dated():
    entry = {"ModifiedTime_raw": _UNDECODABLE_FILETIME}
    assert not timeline_loader._is_dated(entry), (
        "admitted on bool(raw) alone; filetime_to_dt cannot decode this "
        "value, so the bucketer will drop it after the badge has counted it")


def test_the_badge_counts_only_records_the_buckets_can_hold():
    good = {"ModifiedTime_raw": 133000000000000000}
    bad = {"ModifiedTime_raw": _UNDECODABLE_FILETIME}
    inputs = timeline_loader.timeline_inputs([good, bad])
    bucketed = sum(r["Records"] for r in timeline_loader.period_rows(inputs, "day"))
    assert timeline_loader.dated_record_count(inputs) == bucketed, (
        "badge says %d, buckets hold %d"
        % (timeline_loader.dated_record_count(inputs), bucketed))


# --- an undated carved duplicate is one record, counted once ---------------
#
# timeline_inputs de-duplicates carved entries by identity, because the
# union it is given can legitimately hand over the same dict twice. But the
# dated check runs FIRST, so an undated duplicate is counted as two
# excluded records before the identity check it never reaches.

def test_an_undated_carved_duplicate_is_excluded_once_not_twice():
    d = {"Url": "x"}
    inputs = timeline_loader.timeline_inputs([], [d, d])
    assert inputs.undated_carved == 1, (
        "counted %d exclusions for one record, so the note overstates how "
        "much evidence is being left out" % inputs.undated_carved)
