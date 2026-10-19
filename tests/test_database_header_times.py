"""The database header's own times: created, last opened, last cleanly
closed, last detached, last repaired.

Found working "when was this database last opened and closed": the
header records each, and the tool read only the dirty/clean state. On the
exhibit the header says it was opened on 17 Feb at 15:34:33 UTC and never
cleanly closed after -- the dirty shutdown, with a time."""
from types import SimpleNamespace

from webcache.engine.ese_parser import decode_logtime, header_times
from webcache.shell import integrity_loader


def _lt(y, mo, d, h, mi, s, ms=0, utc=1):
    return SimpleNamespace(bYear=y - 1900, bMonth=mo, bDay=d, bHours=h,
                           bMinutes=mi, bSeconds=s, fTimeIsUTC=utc,
                           bMillisecondsLow=ms % 128,
                           bMillisecondsHigh=ms // 128)


NEVER = SimpleNamespace(bYear=0, bMonth=0, bDay=0, bHours=0, bMinutes=0,
                        bSeconds=0, fTimeIsUTC=0, bMillisecondsLow=0,
                        bMillisecondsHigh=0)


def test_a_logtime_decodes_to_the_utc_instant_with_milliseconds():
    dt = decode_logtime(_lt(2026, 2, 17, 15, 34, 33, ms=833))
    assert dt.isoformat() == "2026-02-17T15:34:33.833000+00:00"


def test_a_time_never_set_is_none():
    assert decode_logtime(NEVER) is None


def _header():
    return SimpleNamespace(
        signDb=SimpleNamespace(logtimeCreate=_lt(2025, 6, 21, 15, 41, 50, 193)),
        logtimeAttach=_lt(2026, 2, 17, 15, 34, 33, 833),
        logtimeConsistent=_lt(2026, 2, 16, 17, 19, 33, 738),
        logtimeDetach=NEVER, logtimeRepair=NEVER, ulRepairCount=0)


def test_the_header_times_are_read_together():
    times = header_times(_header())
    assert times["created"].isoformat().startswith("2025-06-21T15:41:50")
    assert times["last_attach"].isoformat().startswith("2026-02-17T15:34:33")
    assert times["last_consistent"].isoformat().startswith("2026-02-16")
    assert times["last_detach"] is None
    assert times["repair_count"] == 0


def test_integrity_states_them_and_what_never_happened():
    rows = {r["label"]: r["value"] for r in
            integrity_loader.source_integrity_rows(
                {"db_state_text": "Dirty shutdown",
                 "header_times": header_times(_header())})}
    assert rows["Created (header)"] == "2025-06-21 15:41:50.193 UTC"
    assert rows["Last opened (header)"] == "2026-02-17 15:34:33.833 UTC"
    assert rows["Last clean close (header)"] == "2026-02-16 17:19:33.738 UTC"
    assert rows["Last detached (header)"] == "Never recorded"
    assert rows["Repaired (header)"] == "Never (repair count 0)"


def test_without_header_times_no_rows_are_invented():
    labels = {r["label"] for r in integrity_loader.source_integrity_rows(
        {"db_state_text": "Dirty shutdown"})}
    assert not any("(header)" in label for label in labels)
