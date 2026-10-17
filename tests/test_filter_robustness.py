"""A relative-days filter cannot be fed a non-number, and a failed
recompute cannot tear the filter (chip describing one filter, grid showing
another). See webcache/widgets/record_filter.py for the invariants these
tests pin: "in the last N days" validates N (finite, non-negative, capped at
100 years); set_condition and set_values roll back to the previous state and
re-raise if _recompute fails partway.
"""
import datetime

import pytest

from webcache.widgets.column_spec import Column
from webcache.widgets.filter_popup import FilterPopup
from webcache.widgets.record_filter import Condition, RecordFilter
from webcache.widgets.record_model import RecordTableModel
from tests.fixtures import FIXTURE_COLUMNS, make_rows


def _time_col():
    return next(c for c in FIXTURE_COLUMNS if c.key == "AccessedUtc")


@pytest.mark.parametrize("n", ["nan", "inf", "-inf", "1e400", "-3"])
def test_a_relative_window_rejects_what_it_cannot_mean(n):
    assert Condition("in the last N days", n).error


@pytest.mark.parametrize("n", ["0", "1.5", "30"])
def test_a_relative_window_still_accepts_valid_n(n):
    cond = Condition("in the last N days", n)
    assert cond.error is None


def test_valid_n_still_matches_the_same_rows_as_before():
    # A regression pin, driven through RecordFilter exactly as production
    # code does it: validation must not change matching behaviour for
    # values that were always legal. The anchor (newest row's t, day 3) is
    # resolved fresh by _recompute, not hand-built here -- see
    # Condition/_recompute's docstrings on why an anchor built any other
    # way is not equivalent to the one matches() actually gets in the app.
    rows = [{"t": datetime.datetime(2024, 1, d)} for d in (1, 2, 3)]
    f = RecordFilter(rows, [Column("t", "T", 100, kind="time")])

    f.set_condition("t", Condition("in the last N days", "1.5"))
    assert {r["t"].day for r in f.visible()} == {2, 3}

    f.set_condition("t", Condition("in the last N days", "0"))
    assert {r["t"].day for r in f.visible()} == {3}

    f.set_condition("t", Condition("in the last N days", "30"))
    assert {r["t"].day for r in f.visible()} == {1, 2, 3}


def test_the_hundred_year_ceiling_is_accepted_and_one_day_past_is_rejected():
    assert Condition("in the last N days", "36500").error is None
    assert Condition("in the last N days", "36501").error


def test_no_accepted_value_can_overflow_against_an_early_anchor():
    # A row near datetime.min becomes the anchor (it's the only/newest
    # row): anchor - timedelta(days=N) must not raise OverflowError for
    # any N this class will accept (0..36500), driven through
    # RecordFilter/_recompute exactly as production resolves the anchor.
    near_min = datetime.datetime.min + datetime.timedelta(days=1)
    rows = [{"t": near_min}]
    f = RecordFilter(rows, [Column("t", "T", 100, kind="time")])
    cond = Condition("in the last N days", "36500")
    assert cond.error is None
    f.set_condition("t", cond)  # must not raise OverflowError
    # The subtraction itself overflows (100 years back from a date one day
    # after datetime.min); matches() treats that the same as "no dated
    # value" -- doesn't match -- rather than crashing the pass. What this
    # test actually pins is the absence of OverflowError, not this row's
    # particular verdict.
    assert list(f.visible()) == []


@pytest.mark.parametrize("n", ["nan", "inf", "-3", "36501"])
def test_the_popup_refuses_a_rejected_n_and_says_why(qtbot, n):
    """apply() must show the examiner WHY a typed "in the last N days"
    was refused, not just silently decline to apply it -- a rejected
    filter with no visible message reads as "I typed it and nothing
    happened", which is a much easier failure to miss than an error
    string. Driven through the popup itself (operator_box + operand_a +
    apply()), not the Condition directly."""
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(50))
    p = FilterPopup(model, _time_col())
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    p.operator_box.setCurrentText("in the last N days")
    p.operand_a.setText(n)
    applied = p.apply()
    assert applied is False
    assert p.status_text()
    assert n in p.status_text() or "not a number" in p.status_text().lower() \
        or "N must be" in p.status_text()
    # And the refusal must not have torn the filter: no condition attached.
    assert p.model.filter.condition_for("AccessedUtc") is None


def test_a_failing_condition_leaves_the_previous_filter_in_force():
    rows = [{"t": datetime.datetime(2024, 1, d)} for d in (1, 2, 3)]
    f = RecordFilter(rows, [Column("t", "T", 100, kind="time")])
    good = Condition("after", "2024-01-01 12:00")
    f.set_condition("t", good)
    before = list(f.visible())

    class Boom(Condition):
        def matches(self, value):
            raise ValueError("synthetic")

    with pytest.raises(ValueError):
        f.set_condition("t", Boom("contains", "x"))
    assert f.condition_for("t") is good
    assert list(f.visible()) == before


def test_a_failing_set_values_leaves_the_previous_filter_in_force():
    rows = [{"t": datetime.datetime(2024, 1, d)} for d in (1, 2, 3)]
    f = RecordFilter(rows, [Column("t", "T", 100, kind="time")])
    good = Condition("after", "2024-01-01 12:00")
    f.set_condition("t", good)

    class Boom(Condition):
        def matches(self, value):
            raise ValueError("synthetic")

    f._conditions["t"] = Boom("contains", "x")
    before_values = dict(f._values)
    with pytest.raises(ValueError):
        f.set_values("t", {datetime.datetime(2024, 1, 1)})
    assert f._values == before_values


# --- sorting survives old dates, a reversed range still means something

from webcache.widgets.record_filter import _sort_key


def test_a_naive_pre_1970_datetime_sorts_without_raising():
    old, new = datetime.datetime(1601, 1, 1), datetime.datetime(2024, 1, 1)
    assert sorted([new, old], key=_sort_key) == [old, new]


def test_between_with_reversed_numbers_matches_the_range():
    assert Condition("between", "100", "10").matches(50) is True


def test_between_with_reversed_dates_matches_the_range():
    c = Condition("between", "2024-12-31", "2024-01-01")
    assert c.matches(datetime.datetime(2024, 6, 1)) is True


def test_reversed_between_describes_the_range_ascending():
    # The chip an examiner reads should describe the range as it is now
    # APPLIED (low -> high), not echo the operands back in the order they
    # were typed -- a chip reading "between 100 and 10" while actually
    # matching [10, 100] would mislead the very person it's meant to
    # inform.
    c = Condition("between", "100", "10")
    assert c.describe() == "between 10 and 100"


def test_aware_datetimes_sort_by_instant_not_local_wall_clock():
    # 13:00+02:00 and 12:00+00:00 are the SAME instant; 12:30+00:00 is
    # later than both. Sorting by naive wall-clock value (ignoring the
    # offset) would put the +02:00 value last; sorting by instant puts it
    # tied with the first and before the last.
    plus_two = datetime.datetime(2024, 1, 1, 13, 0,
                                  tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    utc_earlier = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
    utc_later = datetime.datetime(2024, 1, 1, 12, 30, tzinfo=datetime.timezone.utc)
    ordered = sorted([utc_later, plus_two, utc_earlier], key=_sort_key)
    assert ordered == [plus_two, utc_earlier, utc_later] or \
        ordered == [utc_earlier, plus_two, utc_later]
    # Either tie order is fine (they are the same instant); what matters is
    # utc_later sorts strictly after both.
    assert ordered[-1] is utc_later


def test_naive_datetime_sorts_as_utc_alongside_an_aware_value():
    # This tool's convention (see _parse_dt's docstring): a naive
    # datetime/timestamp in a row means UTC, never local time. A naive
    # value and an aware UTC value representing the same instant must sort
    # as equal (adjacent, key-equal), not offset by whatever the local
    # system timezone happens to be.
    naive = datetime.datetime(2024, 1, 1, 12, 0)
    aware = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
    assert _sort_key(naive) == _sort_key(aware)


def test_date_values_still_sort():
    old, new = datetime.date(1601, 1, 1), datetime.date(2024, 1, 1)
    assert sorted([new, old], key=_sort_key) == [old, new]


def test_sort_key_totally_orders_a_heterogeneous_list_without_raising():
    # value_counts() (see _sort_key's docstring) hands this a genuinely
    # mixed column from a carved/damaged database: ints, strings,
    # datetimes, and blanks all in one list. It must not raise, and must
    # produce a stable total order (every element comparable to every
    # other via the returned tuples).
    values = [3, "b", None, datetime.datetime(1601, 1, 1), "a", 1.5, "",
              datetime.datetime(2024, 1, 1), True, datetime.date(2000, 1, 1)]
    keys = [_sort_key(v) for v in values]
    assert sorted(keys)  # must not raise
    assert sorted(range(len(values)), key=lambda i: keys[i])  # same
