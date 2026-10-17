"""The date calendars show how many records each day holds, shaded by
that count: a busy day stands out before it is picked, and a day with
nothing is plain."""
import datetime

from PySide6.QtCore import QDate, QRect
from PySide6.QtGui import QColor, QImage, QPainter

from tests.test_filter_popup import time_popup  # noqa: F401 (fixture)
from tests.test_timeline_clock import view  # noqa: F401 (fixture)
from webcache.widgets.calendar_button import CalendarButton


def _cell(calendar, date):
    image = QImage(60, 44, QImage.Format_ARGB32)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    calendar.paintCell(painter, QRect(0, 0, 60, 44), date)
    painter.end()
    return image


def _green(image):
    total = 0
    for x in range(0, image.width(), 3):
        for y in range(0, image.height(), 3):
            c = QColor(image.pixel(x, y))
            total += c.green() - (c.red() + c.blue()) // 2
    return total


def test_a_day_shows_its_count_and_a_busier_day_is_deeper(qtbot):
    from PySide6.QtWidgets import QLineEdit
    field = QLineEdit()
    button = CalendarButton(field)
    qtbot.addWidget(field)
    qtbot.addWidget(button)
    button.set_span(datetime.date(2025, 12, 1), datetime.date(2025, 12, 31))
    button.set_day_counts({datetime.date(2025, 12, 16): 2,
                           datetime.date(2025, 12, 17): 40})
    cal = button.calendar
    assert cal.count_for(QDate(2025, 12, 17)) == 40
    assert cal.count_for(QDate(2025, 12, 18)) == 0
    quiet, busy, empty = (_cell(cal, QDate(2025, 12, d)) for d in (16, 17, 18))
    assert _green(busy) > _green(quiet) > _green(empty)
    assert "40 records" in cal.day_tooltip(QDate(2025, 12, 17))
    assert cal.day_tooltip(QDate(2025, 12, 18)).endswith("no records")


def test_timeline_counts_each_day_from_the_by_day_periods(view):
    days = view._segment_rows.get("day") or ()
    assert days
    row = max(days, key=lambda r: r.get("Records") or 0)
    date = QDate.fromString(row["Period"], "yyyy-MM-dd")
    assert view.date_calendar.calendar.count_for(date) == row["Records"]


def test_a_time_filter_counts_the_column_by_day(time_popup):
    p = time_popup
    cal = p.calendar_for(p.operand_a).calendar
    assert cal.counted_days()
    assert all(cal.count_for(d) for d in cal.counted_days())
