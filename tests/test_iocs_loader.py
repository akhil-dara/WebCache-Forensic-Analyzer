"""iocs_loader: six previously-built, never-called forensic_engine/
analysis_extra heuristics, reshaped into the row sets the Findings view
(nav key "iocs") switches between -- see iocs_loader.py's own module
docstring for which engine call feeds which segment, and views/iocs.py
for the columns each one renders.

Pure-function tests, no Qt needed -- mirrors test_indicator_loader.py's
own stub-testable contract: entries are plain dicts, never a real
WebCacheParser or a real ForensicEngine built by the caller.
"""
import datetime

from webcache.shell import record_kinds
from webcache.shell.iocs_loader import (beaconing_rows, deceptive_hostname_rows,
                                        entryid_gap_rows, ioc_hit_rows,
                                        redirect_hop_rows, split_watchlist,
                                        time_void_rows)

_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


def _filetime(dt):
    return int((dt - _EPOCH).total_seconds() * 10_000_000)


def _entry(**overrides):
    base = {"Url": "https://example.com/a", "ContainerType": "History"}
    base.update(overrides)
    base.setdefault("CleanUrl", base["Url"])
    return base


# --- ioc_hit_rows ------------------------------------------------------

def test_a_watchlist_term_is_matched_and_carries_the_term_itself():
    rows = ioc_hit_rows([_entry(Url="https://evil.example/x")], terms=["evil.example"])
    assert len(rows) == 1
    assert "watchlist:evil.example" in rows[0]["Reasons"]
    assert rows[0]["Why"]


def test_a_dot_onion_address_fires_the_built_in_rule_with_its_own_basis():
    rows = ioc_hit_rows([_entry(Url="http://abc.onion/x")])
    assert len(rows) == 1
    assert "tor-onion" in rows[0]["Reasons"]
    # the engine's own sentence for why the rule fired, not a phrase this
    # loader invented
    assert "onion" in rows[0]["Why"].lower() or "tor" in rows[0]["Why"].lower()


def test_an_ordinary_url_with_no_watchlist_is_not_a_hit():
    assert ioc_hit_rows([_entry()]) == []


def test_a_live_hit_points_back_at_its_own_entry_by_reference():
    entry = _entry(Url="http://x.onion/a")
    rows = ioc_hit_rows([entry])
    assert rows[0]["_record"] is entry
    assert rows[0]["Source"] == "live"
    assert rows[0]["_kind"] is record_kinds.K_HISTORY


def test_a_carved_hit_is_labelled_carved_and_kept_distinct_from_a_live_one():
    carved = _entry(Url="http://y.onion/b", ContainerId=3, Flags=0)
    rows = ioc_hit_rows([], carved_entries=[carved])
    assert len(rows) == 1
    assert rows[0]["Source"] == "carved"
    assert rows[0]["_kind"] is record_kinds.K_CARVED_STRUCT
    assert rows[0]["_record"] is carved


def test_a_hit_carries_a_real_datetime_when_the_entry_has_one():
    ft = _filetime(datetime.datetime(2024, 3, 11, 9, 14, 2,
                                     tzinfo=datetime.timezone.utc))
    rows = ioc_hit_rows([_entry(Url="http://z.onion/c", ModifiedTime_raw=ft)])
    assert isinstance(rows[0]["AccessedUtc"], datetime.datetime)


# --- entryid_gap_rows ---------------------------------------------------

def test_a_hole_in_the_entryid_sequence_is_reported_once_per_container():
    live = [_entry(ContainerId=3, ContainerName="History", EntryId=1),
           _entry(ContainerId=3, ContainerName="History", EntryId=3)]
    rows = entryid_gap_rows(live)
    assert len(rows) == 1
    row = rows[0]
    assert row["ContainerId"] == 3
    assert row["Live"] == 2
    assert row["Missing"] == 1
    assert row["GapRuns"] == 1
    assert row["_kind"] is record_kinds.K_ENTRYID_GAP
    assert row["_record"] is None
    assert row["Interpretation"]


def test_the_gap_row_names_its_own_live_records_as_members():
    a = _entry(ContainerId=3, EntryId=1)
    b = _entry(ContainerId=3, EntryId=3)
    rows = entryid_gap_rows([a, b])
    members = rows[0]["_records"]
    assert any(m is a for m in members) and any(m is b for m in members)


def test_recovered_counts_a_carved_id_that_falls_inside_the_gap():
    live = [_entry(ContainerId=3, EntryId=1), _entry(ContainerId=3, EntryId=5)]
    carved = [_entry(ContainerId=3, EntryId=3, Flags=0)]
    rows = entryid_gap_rows(live, carved_entries=carved)
    assert rows[0]["Recovered"] == 1


def test_a_sequential_container_with_no_hole_reports_no_gap():
    live = [_entry(ContainerId=3, EntryId=1), _entry(ContainerId=3, EntryId=2)]
    assert entryid_gap_rows(live) == []


# --- time_void_rows ------------------------------------------------------

def _dated_entries(hours_apart, count, start=None):
    start = start or datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    out = []
    for i in range(count):
        when = start + datetime.timedelta(hours=hours_apart * i)
        out.append(_entry(Url="https://example.com/%d" % i,
                          ModifiedTime_raw=_filetime(when)))
    return out


def test_a_silence_of_a_day_or_more_is_reported():
    dense = _dated_entries(1, 10)
    gap_start = dense[-1]["ModifiedTime_raw"]
    later = _entry(Url="https://example.com/late",
                   ModifiedTime_raw=_filetime(
                       datetime.datetime(2024, 1, 3, tzinfo=datetime.timezone.utc)))
    rows = time_void_rows(dense + [later])
    assert len(rows) == 1
    assert rows[0]["GapHours"] >= 24
    # "19,271.3" hours made the examiner divide to see two years; the row
    # states it in days and hours beside the exact figure.
    assert rows[0]["Length"].endswith(" h") and " d" in rows[0]["Length"]
    assert rows[0]["_kind"] is record_kinds.K_TIME_VOID
    assert rows[0]["_record"] is None


def test_fewer_than_ten_dated_records_reports_no_silence_at_all():
    assert time_void_rows(_dated_entries(48, 3)) == []


# --- beaconing_rows ------------------------------------------------------

def test_a_low_jitter_periodic_domain_is_reported_as_a_beacon():
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    live = [_entry(Url="https://beacon.example/%d" % i,
                   ModifiedTime_raw=_filetime(
                       start + datetime.timedelta(seconds=300 * i)))
           for i in range(8)]
    rows = beaconing_rows(live)
    assert len(rows) == 1
    assert rows[0]["Domain"] == "beacon.example"
    assert rows[0]["Events"] == 8
    assert rows[0]["_kind"] is record_kinds.K_BEACON
    members = rows[0]["_records"]
    assert len(members) == 8
    assert all(m in live for m in members)


def test_a_handful_of_irregular_requests_is_not_a_beacon():
    assert beaconing_rows(_dated_entries(1, 3)) == []


# --- deceptive_hostname_rows ---------------------------------------------

def test_a_punycode_hostname_is_flagged_with_the_engines_own_reason():
    rows = deceptive_hostname_rows([_entry(Url="https://xn--e1aybc.example/x",
                                          CleanUrl="https://xn--e1aybc.example/x")])
    assert len(rows) == 1
    assert rows[0]["Why"]
    assert rows[0]["Decoded"] != rows[0]["Host"] or "xn--" not in rows[0]["Host"]
    assert rows[0]["_kind"] is record_kinds.K_DECEPTIVE_HOST
    assert rows[0]["_record"] is None
    assert rows[0]["Records"] == 1


def test_an_ordinary_ascii_hostname_is_not_flagged():
    assert deceptive_hostname_rows([_entry(Url="https://plain.example/x")]) == []


def test_a_carved_only_hostname_still_counts():
    carved = _entry(Url="https://xn--e1aybc.example/gone",
                    CleanUrl="https://xn--e1aybc.example/gone")
    rows = deceptive_hostname_rows([], carved_entries=[carved])
    assert len(rows) == 1
    assert rows[0]["Records"] == 1


# --- redirect_hop_rows ----------------------------------------------------

def test_a_recorded_redirect_becomes_a_two_hop_chain():
    start = _entry(Url="https://a.example/start",
                   CleanUrl="https://a.example/start",
                   RedirectUrl="https://b.example/end")
    end = _entry(Url="https://b.example/end", CleanUrl="https://b.example/end")
    rows = redirect_hop_rows([start, end])
    assert len(rows) == 2
    assert rows[0]["Step"] == 1
    assert rows[1]["Step"] == 2
    assert rows[0]["Chain"] == rows[1]["Chain"]
    assert rows[1]["InDb"] == "yes"
    assert all(r["_kind"] is record_kinds.K_REDIRECT_HOP for r in rows)
    assert all(r["_record"] is None for r in rows)


def test_no_recorded_redirects_yields_no_hops():
    assert redirect_hop_rows([_entry()]) == []


# --- split_watchlist -------------------------------------------------------

def test_split_watchlist_accepts_commas_and_newlines_and_drops_blanks():
    assert split_watchlist("a.example, b.example\nc.example\n\n") == [
        "a.example", "b.example", "c.example"]


def test_split_watchlist_of_nothing_is_an_empty_list():
    assert split_watchlist("") == []
    assert split_watchlist(None) == []
