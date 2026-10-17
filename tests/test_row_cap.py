"""One long value set the whole row's height. On the
largest sample exhibit 13 Deleted Records rows and every Location Raw records row
were TALLER than the viewport, and with per-item scrolling the bottom of
such a row can never be brought into view -- truncation, not just poor
use of the screen.

The examiner's decision: a wrapped row grows to at most a few lines; a
cell holding more paints a visible "+N more lines" marker in the accent
colour; the marker (a click), Enter on the cell and "Show whole value" on
the context menu open the whole value. Copy, the tooltip, the record
dialog and every export still carry the whole value -- only the painted
cell is capped, and the marker says so.
"""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from webcache.shell import theme
from webcache.widgets.column_spec import Column
from webcache.widgets.records_table import RecordsTable
from tests.fixtures import FIXTURE_COLUMNS, make_rows

#: Synthetic, 5,000 characters, and wraps at any width.
HUGE = "https://example.test/" + "/".join("seg%04d" % i for i in range(620))
HUGE = HUGE[:5000]
#: The most lines a capped row may show, text and marker together (the
#: review recommends 6; the examiner allowed 6 to 8).
MOST_LINES = 8


@pytest.fixture(autouse=True)
def _scratch_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")


def _title():
    return [c.key for c in FIXTURE_COLUMNS].index("Title")


def _table(qtbot, rows, height=451):
    t = RecordsTable()
    t.set_records(list(FIXTURE_COLUMNS), rows)
    qtbot.addWidget(t)
    t.resize(1328, height)
    t.show()
    qtbot.waitExposed(t)
    return t


def _fitted(qtbot, t, row=0):
    default = t.verticalHeader().defaultSectionSize()
    qtbot.waitUntil(lambda: t.rowHeight(row) > default, timeout=2_000)
    qtbot.wait(80)          # the fit's later passes
    return t


def _whole_value_windows():
    return [w for w in QApplication.topLevelWidgets()
            if w.isVisible() and "Whole value" in w.windowTitle()]


def _close_whole_value_windows():
    for w in _whole_value_windows():
        w.close()


def test_a_huge_value_gives_a_capped_row(qtbot):
    rows = make_rows(40)
    rows[0]["Title"] = HUGE
    t = _fitted(qtbot, _table(qtbot, rows))
    line = t.fontMetrics().lineSpacing()
    default = t.verticalHeader().defaultSectionSize()
    assert t.rowHeight(0) <= default + (MOST_LINES - 1) * line, (
        "a 5,000-character value set a %d px row" % t.rowHeight(0))
    assert t.rowHeight(0) >= 5 * t.fontMetrics().height(), (
        "the cap is too low to read")


def test_no_row_is_ever_taller_than_the_viewport(qtbot):
    rows = make_rows(60)
    for r in rows:
        r["Title"] = HUGE
    t = _fitted(qtbot, _table(qtbot, rows, height=371))
    for step in range(0, 60, 5):
        t.scrollTo(t.model().index(step, 0))
        qtbot.wait(60)
        for r in range(t.model().rowCount()):
            assert t.rowHeight(r) <= t.viewport().height(), (
                "row %d is %d px in a %d px viewport"
                % (r, t.rowHeight(r), t.viewport().height()))


def _accent_pixels(image, rect):
    accent = QColor(theme.color("primary"))
    hits = 0
    for x in range(rect.left(), rect.right()):
        for y in range(rect.top(), rect.bottom()):
            c = image.pixelColor(x, y)
            if (abs(c.red() - accent.red()) < 40 and abs(c.green() - accent.green()) < 40
                    and abs(c.blue() - accent.blue()) < 40):
                hits += 1
    return hits


def test_a_capped_cell_paints_a_more_marker_in_the_accent_colour(qtbot):
    rows = make_rows(40)
    rows[0]["Title"] = HUGE
    t = _fitted(qtbot, _table(qtbot, rows))
    cell = t.visualRect(t.model().index(0, _title()))
    image = t.viewport().grab().toImage()
    ratio = image.devicePixelRatio()
    corner = cell.adjusted(cell.width() // 3, cell.height() * 2 // 3, 0, 0)
    corner = type(cell)(int(corner.left() * ratio), int(corner.top() * ratio),
                        int(corner.width() * ratio), int(corner.height() * ratio))
    assert _accent_pixels(image, corner) > 10, (
        "no marker in the accent colour at the capped cell's bottom right")
    # A cell that is NOT capped carries no marker.
    plain = t.visualRect(t.model().index(1, _title()))
    image_rect = type(plain)(int(plain.left() * ratio), int(plain.top() * ratio),
                             int(plain.width() * ratio), int(plain.height() * ratio))
    assert _accent_pixels(image, image_rect) == 0


def test_show_whole_value_is_on_the_context_menu_and_shows_it_whole(qtbot):
    rows = make_rows(40)
    rows[0]["Title"] = HUGE
    t = _fitted(qtbot, _table(qtbot, rows))
    menu = t._build_context_menu(t.model().index(0, _title()))
    actions = [a for a in menu.actions() if a.text().startswith("Show whole value")]
    assert actions, [a.text() for a in menu.actions()]
    actions[0].trigger()
    windows = _whole_value_windows()
    assert len(windows) == 1
    assert windows[0].full_text() == HUGE
    assert "Title" in windows[0].windowTitle()
    _close_whole_value_windows()


def test_enter_on_a_capped_cell_shows_the_whole_value(qtbot):
    rows = make_rows(40)
    rows[0]["Title"] = HUGE
    t = _fitted(qtbot, _table(qtbot, rows))
    t.setCurrentIndex(t.model().index(0, _title()))
    t.setFocus()
    QTest.keyClick(t, Qt.Key_Return)
    windows = _whole_value_windows()
    assert len(windows) == 1 and windows[0].full_text() == HUGE
    _close_whole_value_windows()


def test_a_click_on_the_marker_shows_the_whole_value(qtbot):
    rows = make_rows(40)
    rows[0]["Title"] = HUGE
    t = _fitted(qtbot, _table(qtbot, rows))
    cell = t.visualRect(t.model().index(0, _title()))
    QTest.mouseClick(t.viewport(), Qt.LeftButton, Qt.NoModifier,
                     QPoint(cell.right() - 20, cell.bottom() - 6))
    windows = _whole_value_windows()
    assert len(windows) == 1 and windows[0].full_text() == HUGE
    _close_whole_value_windows()


def test_copy_and_the_tooltip_still_carry_the_whole_value(qtbot):
    rows = make_rows(40)
    rows[0]["Title"] = HUGE
    t = _fitted(qtbot, _table(qtbot, rows))
    ix = t.model().index(0, _title())
    t._copy_cell(ix)
    assert QGuiApplication.clipboard().text() == HUGE
    assert HUGE in ix.data(Qt.ToolTipRole)


def test_a_column_with_no_declared_width_is_given_a_most_width(qtbot):
    """Cookies' Value auto-sized to a 1,117-character column. A column
    with no width of its own stops at the widest declared text column and
    wraps from there."""
    cols = [Column("Name", "Name", 120), Column("Value", "Value", None)]
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records(cols, [{"Name": "a", "Value": HUGE}])
    assert t.horizontalHeader().sectionSize(1) <= 420


def test_location_raw_records_give_the_url_columns_the_fixes_width():
    from webcache.views.location import _record_columns
    widths = {c.key: c.width for c in _record_columns()}
    assert widths["Url"] == 420 and widths["CleanUrl"] == 420
