"""Integrity lists every UTC offset the SPS pairs show, with how many
records and when, so a period in another zone is visible even when the
tool does not adopt it."""
import datetime

from webcache.engine import local_clock as lc
from webcache.engine.ese_parser import filetime_to_dt
from webcache.shell import integrity_loader

EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


def _ft(dt):
    return int((dt - EPOCH).total_seconds() * 10_000_000)


def _obs(day, offset_h):
    utc = datetime.datetime(2025, 10, day, 12, tzinfo=datetime.timezone.utc)
    return lc.Observation(0, _ft(utc), int(offset_h * 3600), "")


def test_every_offset_seen_is_listed_with_its_dates_and_whether_it_is_used():
    obs = ([_obs(d, 5.5) for d in range(1, 21)]
           + [_obs(25, -4)])                      # one lone reading
    periods = lc.offset_periods(obs)
    by = {p["offset"]: p for p in periods}
    assert by["UTC+05:30"]["records"] == 20 and by["UTC+05:30"]["adopted"]
    assert by["UTC+05:30"]["first"] == "2025-10-01"
    assert by["UTC+05:30"]["last"] == "2025-10-20"
    assert by["UTC-04:00"]["records"] == 1 and not by["UTC-04:00"]["adopted"]
    assert by["UTC-04:00"]["first"] == by["UTC-04:00"]["last"] == "2025-10-25"


def test_integrity_states_the_offsets_and_the_display_format():
    info = {"clock_offsets": [
        {"offset": "UTC+05:30", "records": 20, "first": "2025-10-01",
         "last": "2025-10-20", "adopted": True, "source": "live"},
        {"offset": "UTC-04:00", "records": 1, "first": "2025-10-25",
         "last": "2025-10-25", "adopted": False, "source": "recovered"}]}
    rows = integrity_loader.clock_rows(info)
    text = " | ".join("%s: %s" % (r["label"], r["value"]) for r in rows)
    assert "UTC+05:30" in text and "20 records" in text
    assert "UTC-04:00" in text and "not adopted" in text
    assert "recovered" in text
    assert any(r["label"] == "Times shown as" for r in rows)


def test_no_pairs_is_stated_not_left_blank():
    rows = integrity_loader.clock_rows({"clock_offsets": []})
    assert "No record pairs" in rows[0]["value"]


def test_the_integrity_view_shows_the_clock_card(qtbot):
    from webcache.views.integrity import IntegrityView
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data({"clock_offsets": [
        {"offset": "UTC+05:30", "records": 3, "first": "2025-10-01",
         "last": "2025-10-02", "adopted": True, "source": "live"}],
        "source_hashes": {}, "decision_log": [], "parse_stats": {}})
    labels = [label.text() for label, _value in v._clock_rows]
    assert "UTC+05:30" in labels and "Times shown as" in labels
