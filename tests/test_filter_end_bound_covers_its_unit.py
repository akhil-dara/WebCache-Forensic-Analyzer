"""An end bound covers the whole unit it names.

Found working a time-window question: "between 2026-02-15 and 2026-02-16"
kept only the instant 2026-02-16 00:00:00 of the second day, so every
other record of the 16th was silently dropped; the calendar buttons write
exactly such date-only operands. "...and 2026-02-15 12:00" likewise
dropped 12:00:30. The start bound and the worded operators (before,
after, on) are unchanged."""
import datetime as dt

import pytest

from webcache.widgets.record_filter import Condition

UTC = dt.timezone.utc


def _t(text):
    return dt.datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize("value,expected", [
    ("2026-02-14T23:59:59", False),
    ("2026-02-15T00:00:00", True),
    ("2026-02-16T12:00:00", True),
    ("2026-02-16T23:59:59.999999", True),
    ("2026-02-17T00:00:00", False),
])
def test_a_date_range_covers_both_whole_days(value, expected):
    c = Condition("between", "2026-02-15", "2026-02-16")
    assert c.matches(_t(value)) is expected


@pytest.mark.parametrize("value,expected", [
    ("2026-02-15T09:59:59", False),
    ("2026-02-15T10:00:00", True),
    ("2026-02-15T12:00:30", True),
    ("2026-02-15T12:00:59.900000", True),
    ("2026-02-15T12:01:00", False),
])
def test_a_minute_range_covers_its_last_minute(value, expected):
    c = Condition("between", "2026-02-15 10:00", "2026-02-15 12:00")
    assert c.matches(_t(value)) is expected


def test_operands_given_the_wrong_way_round_cover_the_same_days():
    c = Condition("between", "2026-02-16", "2026-02-15")
    assert c.matches(_t("2026-02-16T23:00:00"))
    assert not c.matches(_t("2026-02-17T00:00:00"))


def test_on_or_before_a_date_covers_that_day():
    c = Condition("<=", "2026-02-16")
    assert c.matches(_t("2026-02-16T18:00:00"))
    assert not c.matches(_t("2026-02-17T00:00:00"))


def test_numbers_are_untouched():
    c = Condition("between", "10", "20")
    assert c.matches(20) and not c.matches(20.5)


def test_the_description_states_the_end_it_applied():
    """The sentence travels into the count line and every export's
    provenance, so it says what was applied."""
    assert Condition("between", "2026-02-15", "2026-02-16").describe() == (
        "between 2026-02-15 and the end of 2026-02-16")
    assert Condition("between", "2026-02-15 10:00",
                     "2026-02-15 12:00").describe() == (
        "between 2026-02-15 10:00 and the end of 2026-02-15 12:00")
