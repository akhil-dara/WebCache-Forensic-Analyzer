"""A calendar button beside a date field.

Opens a month calendar limited to the exhibit's date span; the day picked
is written into the field as YYYY-MM-DD, where it can still be edited
(a month prefix, a time of day). The field stays the source of truth, so
typing and picking are interchangeable.

Each day shows how many records it holds, shaded by that count (deeper
for more), so a busy day stands out before it is picked and a day with
nothing is plain.
"""
import datetime
import math

from PySide6.QtCore import QDate, QEvent, QObject, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (QCalendarWidget, QMenu, QTableView,
                               QToolButton, QToolTip, QWidgetAction)

from ..shell import glyphs, theme


def _qdate(value):
    if isinstance(value, datetime.datetime):
        value = value.date()
    if isinstance(value, datetime.date):
        return QDate(value.year, value.month, value.day)
    if isinstance(value, QDate):
        return value
    return None


class _DayTips(QObject):
    """Shows a day's count as a tooltip over the calendar's day grid. A
    separate object: QCalendarWidget filters its own internal events, and
    an override there would run while the grid is being torn down."""

    def __init__(self, calendar, cells):
        super().__init__(calendar)
        self._calendar = calendar
        self._cells = cells
        cells.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ToolTip:
            date = self._calendar._date_at(self._cells, event.pos())
            if date is not None:
                QToolTip.showText(event.globalPos(),
                                  self._calendar.day_tooltip(date), obj)
                return True
        return False


class HeatCalendar(QCalendarWidget):
    """A month calendar whose day cells carry a record count and a fill
    whose strength follows that count."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts = {}
        self._peak = 0
        cells = self.findChild(QTableView)
        if cells is not None:
            self._tips = _DayTips(self, cells)

    def set_day_counts(self, counts):
        """`counts`: {date or QDate: number of records}."""
        self._counts = {}
        for day, n in (counts or {}).items():
            q = _qdate(day)
            if q is not None and n:
                self._counts[q.toJulianDay()] = int(n)
        self._peak = max(self._counts.values(), default=0)
        self.updateCells()

    def count_for(self, date):
        return self._counts.get(date.toJulianDay(), 0)

    def counted_days(self):
        return [QDate.fromJulianDay(j) for j in sorted(self._counts)]

    def day_tooltip(self, date):
        n = self.count_for(date)
        return "%s: %s" % (date.toString("yyyy-MM-dd"),
                           "%s record%s" % (format(n, ","), "" if n == 1 else "s")
                           if n else "no records")

    def _strength(self, n):
        """0..1 on a square-root scale, so one very busy day does not wash
        every other day out to nothing."""
        if not n or not self._peak:
            return 0.0
        return 0.18 + 0.82 * math.sqrt(n / self._peak)

    def paintCell(self, painter, rect, date):
        in_month = (date.month() == self.monthShown()
                    and date.year() == self.yearShown())
        in_span = self.minimumDate() <= date <= self.maximumDate()
        n = self.count_for(date)
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        cell = rect.adjusted(2, 2, -2, -2)
        if n:
            fill = QColor(theme.color("primary"))
            fill.setAlphaF(0.12 + 0.6 * self._strength(n)
                           if in_month else 0.08)
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(cell, 5, 5)
        if date == self.selectedDate():
            painter.setPen(theme.color("primary"))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(cell, 5, 5)
        text = theme.color("text") if in_month and in_span else theme.color("muted")
        font = QFont(painter.font())
        painter.setPen(text)
        if n:
            day_rect = QRect(cell.left(), cell.top() + 2, cell.width(),
                             cell.height() // 2)
            painter.drawText(day_rect, Qt.AlignHCenter | Qt.AlignBottom,
                             str(date.day()))
            small = QFont(font)
            small.setPointSizeF(max(6.5, font.pointSizeF() * 0.78))
            painter.setFont(small)
            count_rect = QRect(cell.left(), cell.top() + cell.height() // 2,
                               cell.width(), cell.height() // 2 - 1)
            count_pen = QColor(theme.color("text") if in_month
                               else theme.color("muted"))
            painter.setPen(count_pen)
            painter.drawText(count_rect, Qt.AlignHCenter | Qt.AlignTop,
                             format(n, ","))
        else:
            painter.drawText(cell, Qt.AlignCenter, str(date.day()))
        painter.restore()

    def _date_at(self, cells, pos):
        """The date under `pos` in the day grid, or None (a weekday
        heading). The grid is six weeks of seven days starting from the
        week that holds the first of the month."""
        index = cells.indexAt(pos)
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        has_header = self.horizontalHeaderFormat() != QCalendarWidget.NoHorizontalHeader
        has_weeks = self.verticalHeaderFormat() != QCalendarWidget.NoVerticalHeader
        week = row - (1 if has_header else 0)
        day = col - (1 if has_weeks else 0)
        if week < 0 or day < 0:
            return None
        first = QDate(self.yearShown(), self.monthShown(), 1)
        offset = (first.dayOfWeek() - int(self.firstDayOfWeek().value)) % 7
        if offset == 0:
            offset = 7          # the grid always shows part of the week before
        return first.addDays(week * 7 + day - offset)


class CalendarButton(QToolButton):
    """Picks a day into `target` (a QLineEdit). `picked` is emitted with
    the YYYY-MM-DD text after it is written."""
    picked = Signal(str)

    def __init__(self, target, parent=None):
        super().__init__(parent)
        self.target = target
        self._first = self._last = None
        self.setToolTip("Pick a date from a calendar")
        self.setAccessibleName("Pick a date")
        self.setAutoRaise(True)
        self.setIconSize(QSize(18, 18))
        self.calendar = HeatCalendar()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(
            QCalendarWidget.NoVerticalHeader)
        # Room for a two-digit day, its record count under it and the
        # weekday names in every cell.
        self.calendar.setMinimumSize(400, 320)
        self.calendar.clicked.connect(self._choose)
        self.calendar.activated.connect(self._choose)
        self._menu = QMenu(self)
        action = QWidgetAction(self._menu)
        action.setDefaultWidget(self.calendar)
        self._menu.addAction(action)
        self.clicked.connect(self.open_calendar)
        self.refresh_theme()

    def refresh_theme(self):
        self.setIcon(QIcon(glyphs.pixmap("calendar", theme.color("muted"),
                                         18)))
        self.calendar.updateCells()

    def set_span(self, first, last):
        """Limit the calendar to [first, last] (dates or datetimes); None
        leaves it open."""
        self._first, self._last = _qdate(first), _qdate(last)
        if self._first is not None and self._last is not None:
            self.calendar.setDateRange(self._first, self._last)

    def set_day_counts(self, counts):
        """How many records each day holds: {date: count}."""
        self.calendar.set_day_counts(counts)

    def open_calendar(self):
        """Show the calendar on the day in the field, else the latest day
        of the span."""
        shown = QDate.fromString(self.target.text().strip()[:10], "yyyy-MM-dd")
        if not shown.isValid():
            shown = self._last or QDate.currentDate()
        self.calendar.setSelectedDate(shown)
        self._menu.popup(self.mapToGlobal(self.rect().bottomLeft()))

    def _choose(self, date):
        text = date.toString("yyyy-MM-dd")
        self.target.setText(text)
        self._menu.close()
        self.picked.emit(text)
