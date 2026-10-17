"""Dates can be picked from a calendar as well as typed: Timeline's Go to
date and every date operand in a time column's filter. The calendar is
limited to the dates the rows hold, and the day picked fills the field."""
from PySide6.QtCore import QDate

from tests.test_filter_popup import time_popup  # noqa: F401 (fixture)
from tests.test_timeline_clock import view  # noqa: F401 (fixture)


def test_timeline_picks_a_day_and_goes_to_it(view):
    cal = view.date_calendar
    periods = sorted(view.table.model().row_at(i)["Period"]
                     for i in range(view.table.model().rowCount()))
    assert cal.calendar.minimumDate() == QDate.fromString(periods[0], "yyyy-MM-dd")
    assert cal.calendar.maximumDate() == QDate.fromString(periods[-1], "yyyy-MM-dd")
    cal._choose(QDate.fromString(periods[1], "yyyy-MM-dd"))
    assert view.date_box.text() == periods[1]
    assert view.selected_period() == periods[1]


def test_a_time_filter_offers_a_calendar_for_each_date_operand(time_popup):
    p = time_popup
    p.operator_box.setCurrentText("between")
    a, b = p.calendar_for(p.operand_a), p.calendar_for(p.operand_b)
    assert a.isVisibleTo(p) and b.isVisibleTo(p)
    a._choose(QDate(2024, 5, 1)); b._choose(QDate(2024, 5, 31))
    assert (p.operand_a.text(), p.operand_b.text()) == ("2024-05-01", "2024-05-31")


def test_no_calendar_for_a_number_of_days(time_popup):
    p = time_popup
    p.operator_box.setCurrentText("in the last N days")
    assert p.operand_a.isVisibleTo(p)
    assert not p.calendar_for(p.operand_a).isVisibleTo(p)
