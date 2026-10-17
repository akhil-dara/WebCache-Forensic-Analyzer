"""Grids wrap by default and rows grow to fit -- measured for the
visible rows only, so a 100k-row grid stays inside the budgets."""
import gc
import statistics
import time

import pytest
from PySide6.QtCore import Qt

from webcache.shell import settings
from webcache.shell.main_window import MainWindow
from webcache.views.history import HistoryView
from webcache.widgets.records_table import RecordsTable
from webcache.widgets.stall_detector import StallDetector
from tests.fixtures import FIXTURE_COLUMNS, make_rows

#: One pass over the viewport's rows at 100,000 rows, in ms. The pass
#: measures ~25 rows x the columns in view; it must not scale with the
#: row count.
ROW_FIT_BUDGET_MS = 50.0

LONG = "word " * 80                    # synthetic, and wraps at any width


def _elapsed_ms(fn):
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000.0


def _cpu_and_wall_ms(fn):
    """(GUI-thread CPU ms, wall ms) for one call. CPU is what the app
    itself spent; the wall figure also holds whatever else the machine
    was doing."""
    c0, t0 = time.thread_time(), time.perf_counter()
    fn()
    return ((time.thread_time() - c0) * 1000.0,
            (time.perf_counter() - t0) * 1000.0)


def _table(qtbot, rows):
    t = RecordsTable()
    t.set_records(list(FIXTURE_COLUMNS), rows)
    qtbot.addWidget(t)
    t.resize(1600, 700)
    t.show()
    qtbot.waitExposed(t)
    return t


@pytest.fixture
def wrapped(qtbot):
    rows = make_rows(300)
    rows[0]["Title"] = LONG
    rows[299]["Title"] = LONG
    return _table(qtbot, rows)


def _default(t):
    return t.verticalHeader().defaultSectionSize()


def test_a_grid_wraps_by_default(wrapped):
    assert wrapped.is_wrapping()
    assert wrapped.wordWrap()
    assert wrapped.textElideMode() == Qt.ElideNone


def test_a_long_value_grows_its_row_to_fit(wrapped, qtbot):
    qtbot.waitUntil(lambda: wrapped.rowHeight(0) > _default(wrapped),
                    timeout=2_000)
    assert wrapped.rowHeight(0) >= wrapped.sizeHintForRow(0)


def test_a_value_with_no_break_opportunity_still_wraps(qtbot):
    """Qt's item views wrap at word boundaries only: a token, hash or
    query string with no break opportunity stays one over-long line,
    clipped at the cell edge with no ellipsis to say so. It must wrap
    like any other value, and its row grow to show all of it."""
    rows = make_rows(50)
    rows[1]["Title"] = "q=" + "x" * 400          # one unbreakable run
    t = _table(qtbot, rows)
    # It grows to the row cap -- past two lines -- and
    # the part the cap does not paint is announced by the marker.
    title = [c.key for c in FIXTURE_COLUMNS].index("Title")
    qtbot.waitUntil(lambda: t.rowHeight(1) > 2 * _default(t)
                    and t.is_capped(t.model().index(1, title)), timeout=2_000)


def test_only_the_visible_rows_are_measured(wrapped, qtbot):
    qtbot.waitUntil(lambda: wrapped.rowHeight(0) > _default(wrapped),
                    timeout=2_000)
    assert wrapped.rowHeight(299) == _default(wrapped), (
        "a row far below the viewport was measured")


def test_scrolling_measures_rows_as_they_come_into_view(wrapped, qtbot):
    wrapped.scrollToBottom()
    qtbot.waitUntil(lambda: wrapped.rowHeight(299) > _default(wrapped),
                    timeout=2_000)


def test_turning_wrap_off_returns_every_row_to_one_line(wrapped, qtbot):
    qtbot.waitUntil(lambda: wrapped.rowHeight(0) > _default(wrapped),
                    timeout=2_000)
    wrapped.set_wrap(False)
    assert not wrapped.wordWrap()
    assert wrapped.textElideMode() == Qt.ElideRight
    assert all(wrapped.rowHeight(r) == _default(wrapped) for r in range(30))


def test_a_column_resize_refits(wrapped, qtbot):
    qtbot.waitUntil(lambda: wrapped.rowHeight(0) > _default(wrapped),
                    timeout=2_000)
    before = wrapped.rowHeight(0)
    title = [c.key for c in FIXTURE_COLUMNS].index("Title")
    wrapped.horizontalHeader().resizeSection(title, 1400)
    qtbot.waitUntil(lambda: wrapped.rowHeight(0) < before, timeout=2_000)


def test_a_filter_change_refits(wrapped, qtbot):
    wrapped.model().set_text("word word")
    qtbot.waitUntil(lambda: wrapped.model().rowCount() == 2
                    and wrapped.rowHeight(0) > _default(wrapped),
                    timeout=2_000)


def test_a_sort_leaves_no_stale_row_height_below_the_viewport(wrapped, qtbot):
    """QHeaderView keeps its section sizes across a model reset while the
    row count is unchanged, so a row grown for one record would stay tall
    for whichever record a sort moves there. Row 250 is far below the
    viewport: nothing re-measures it, so only a real reset puts it back."""
    wrapped.verticalHeader().resizeSection(250, 90)
    wrapped.model().sort_by("VisitCount")
    qtbot.wait(100)
    assert wrapped.rowHeight(250) == _default(wrapped), (
        "a row below the viewport kept the height of the record it held "
        "before the sort")


def test_a_theme_change_schedules_a_refit(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(make_rows(20))
    view.table._row_fit_timer.stop()
    view.refresh_theme()
    assert view.table._row_fit_timer.isActive()


def test_fitting_the_viewport_is_cheap_at_100k_rows(qtbot, rows_100k):
    # Every column of the visible rows is measured, and half of them
    # overflow, so the cheap one-line check and the full wrapped measure
    # are both inside the timed pass. Copies: rows_100k is session-wide.
    rows = list(rows_100k)
    for i in range(0, 40, 2):
        rows[i] = dict(rows[i], Title=LONG, CleanUrl="https://a.test/" + "p/" * 150)
    t = _table(qtbot, rows)
    t.invalidate_row_hints()
    measured = t.fit_visible_rows()
    assert 0 < measured < 200, "measured %d rows, not just the viewport" % measured
    # Ten COLD fits, each after the heights are reset and the remembered
    # hints forgotten, so every pass measures (and grows) from scratch.
    # Timed as the GUI thread's own CPU: a wall clock on a
    # loaded machine measured the machine -- the budget failed only in
    # full-suite runs, never alone. Windows' 15.6 ms thread-time tick
    # averages to ~1.6 ms over ten passes. The wall figure is reported.
    # The MEDIAN pass, not the mean: one stall (a garbage collection
    # landing mid-pass under a loaded full-suite run) pushed the mean of
    # ten to 67-94 ms while every other pass took ~25 ms. A real slowdown
    # slows every pass, and the median sees it just the same.
    gc.collect()
    cpus, walls = [], []
    runs = 10
    for _ in range(runs):
        t._reset_row_heights()
        t.invalidate_row_hints()
        c, w = _cpu_and_wall_ms(t.fit_visible_rows)
        cpus.append(c)
        walls.append(w)
        assert t.rowHeight(0) > _default(t), "the timed pass did not fit"
    took = statistics.median(cpus)
    assert took < ROW_FIT_BUDGET_MS, (
        "row fit took %.1f ms of GUI-thread CPU, median of %d (%.1f ms wall)"
        % (took, runs, statistics.median(walls)))


def test_a_rows_height_does_not_change_on_a_horizontal_scroll(qtbot):
    """Heights are measured over EVERY column of a visible row, so an
    examiner scrolling sideways never sees the rows under the pointer
    jump as a long column leaves or enters the view."""
    rows = make_rows(60)
    rows[0]["Title"] = LONG
    t = _table(qtbot, rows)
    t.resize(700, 500)
    qtbot.waitUntil(lambda: t.rowHeight(0) > _default(t), timeout=2_000)
    before = [t.rowHeight(r) for r in range(10)]
    bar = t.horizontalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    qtbot.wait(150)
    assert [t.rowHeight(r) for r in range(10)] == before


def test_a_section_move_refits(qtbot):
    """A column dragged to a new position must never be left clipped:
    the move schedules a re-fit, and the moved column's long value has
    its row grown to show it."""
    rows = make_rows(60)
    rows[0]["Title"] = LONG
    t = _table(qtbot, rows)
    t.resize(700, 500)
    header = t.horizontalHeader()
    title = [c.key for c in FIXTURE_COLUMNS].index("Title")
    header.moveSection(header.visualIndex(title), header.count() - 1)
    t._row_fit_timer.stop()
    header.moveSection(header.visualIndex(title), 0)
    assert t._row_fit_timer.isActive(), "a section move scheduled no re-fit"
    qtbot.waitUntil(lambda: t.rowHeight(0) > _default(t), timeout=2_000)


@pytest.mark.parametrize("n", [2_000, 20_000], ids=["2k", "20k"])
def test_no_stall_filtering_and_sorting_a_wrapped_grid(qtbot, n):
    t = _table(qtbot, make_rows(n))
    qtbot.wait(50)
    # The GUI thread's own CPU inside each gap: the
    # wall-clock gap on a loaded machine is partly other processes' time,
    # and failed only in full-suite runs. The wall figure is reported.
    with StallDetector(threshold_ms=150, cpu=True) as det:
        for needle in ("m", "ms", "msn"):
            t.model().set_text(needle)
            qtbot.wait(40)
        t.model().sort_by("VisitCount")
        qtbot.wait(40)
        t.model().clear_all()
        qtbot.wait(40)
    assert det.worst_busy_gap_ms < 150, (
        "worst gap %.0f ms of GUI-thread CPU (%.0f ms wall)"
        % (det.worst_busy_gap_ms, det.worst_gap_ms))


# --- the toggle: one switch, every grid, remembered --------------------------

def test_the_wrap_toggle_switches_every_grid_and_persists(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    history = w._ensure_view_built("history")
    cookies = w._ensure_view_built("cookies")
    # Deleted Records, the grid with the tallest rows,
    # carries the same toolbar toggle as every other record grid.
    recovery = w._ensure_view_built("recovery")
    assert getattr(recovery, "wrap_button", None) is not None, (
        "Deleted Records has no Wrap button")
    assert history.wrap_button.isChecked()
    assert recovery.wrap_button.isChecked()
    history.wrap_button.click()
    assert not history.table.is_wrapping()
    assert not cookies.table.is_wrapping()
    assert not cookies.wrap_button.isChecked()
    assert not recovery.table.is_wrapping()
    assert not recovery.wrap_button.isChecked()
    assert not w.wrap_action.isChecked()
    assert settings.get("grid_wrap") is False
    recovery.wrap_button.click()
    assert history.table.is_wrapping() and history.wrap_button.isChecked()
    assert settings.get("grid_wrap") is True
    recovery.wrap_button.click()
    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert not w2._ensure_view_built("history").table.is_wrapping()


def test_the_cheap_row_hint_agrees_with_qt_over_every_column(qtbot):
    """_row_height_hint skips the full measure for one-line values; it must
    still give exactly the height QTableView.sizeHintForRow would give
    over every column -- including at the width where a value stops
    fitting (Qt measures a cell one grid line narrower than its column)."""
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QStyleOptionViewItem
    rows = make_rows(30)
    rows[2]["Title"] = LONG
    t = _table(qtbot, rows)
    t._row_fit_timer.stop()
    t.verticalHeader().setResizeContentsPrecision(1000)   # Qt: every column
    base = QStyleOptionViewItem()
    t.initViewItemOption(base)
    fm = QFontMetrics(base.font)
    default = _default(t)
    origin = [c.key for c in FIXTURE_COLUMNS].index("Origin")
    for width in range(60, 240, 3):
        t.horizontalHeader().resizeSection(origin, width)
        for r in range(10):
            mine = max(default, t._row_height_hint(r, base, fm))
            assert mine == max(default, t.sizeHintForRow(r)), (
                "row %d at Origin width %d" % (r, width))
