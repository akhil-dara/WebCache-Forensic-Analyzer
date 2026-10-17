"""In Local mode a Timeline period's start is an
aware value at the zone's offset, and a date typed into its filter is a
date on THAT clock -- "on D" selects the period labelled D, not the next
one. UTC and naive columns are unchanged."""
import datetime

from webcache.shell import timeline_loader
from webcache.widgets.record_filter import Condition
from tests.test_timeline_clock import EARLY, LATE, ZONE, rec

UTC = datetime.timezone.utc


def _local_day_rows():
    inputs = timeline_loader.timeline_inputs([rec(EARLY), rec(LATE)])
    rows = timeline_loader.period_rows(inputs, "day", offset_seconds=ZONE)
    assert [r["Period"] for r in rows] == ["2024-06-29", "2024-06-30"]
    return rows


def _selected(rows, condition):
    return [r["Period"] for r in rows if condition.matches(r["PeriodStart"])]


def test_on_a_date_selects_the_local_period_labelled_with_it():
    rows = _local_day_rows()
    assert _selected(rows, Condition("on", "2024-06-30")) == ["2024-06-30"]
    assert _selected(rows, Condition("on", "2024-06-29")) == ["2024-06-29"]


def test_before_and_after_read_the_operand_on_the_periods_clock():
    rows = _local_day_rows()
    assert _selected(rows, Condition("after", "2024-06-29 20:00:00")) == [
        "2024-06-30"]
    assert _selected(rows, Condition("before", "2024-06-29 20:00:00")) == [
        "2024-06-29"]
    assert _selected(rows, Condition("before", "2024-06-30 00:00:01")) == [
        "2024-06-29", "2024-06-30"]


def test_between_reads_both_operands_on_the_periods_clock():
    rows = _local_day_rows()
    assert _selected(rows, Condition("between", "2024-06-29 20:00:00",
                                     "2024-06-30 01:00:00")) == ["2024-06-30"]


def test_a_utc_column_is_unchanged():
    late = datetime.datetime(2024, 6, 29, 23, 0, tzinfo=UTC)
    assert Condition("on", "2024-06-29").matches(late)
    assert not Condition("on", "2024-06-30").matches(late)
    assert Condition("after", "2024-06-29 22:00:00").matches(late)


def test_an_operand_with_its_own_offset_is_an_instant_and_kept():
    start = _local_day_rows()[1]["PeriodStart"]      # 00:00 local = 18:30Z
    assert Condition("after", "2024-06-29T18:00:00+00:00").matches(start)
    assert not Condition("after", "2024-06-29T19:00:00+00:00").matches(start)
