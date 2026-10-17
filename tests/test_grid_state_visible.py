"""What the grid shows is what is in force."""
import pytest
from PySide6.QtCore import QRectF, Qt

from webcache.shell import theme
from webcache.views.history import HistoryView
from webcache.widgets.record_filter import Condition
from tests.fixtures import make_rows


@pytest.fixture
def view(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records(make_rows(300))
    v.resize(1500, 800)
    v.show()
    qtbot.waitExposed(v)
    return v


# --- ------------------------------------------------------------------

def test_clear_all_filters_unticks_the_chip_on_screen(view):
    view.chip_local_files.click()
    assert view.chip_local_files.styleSheet()
    p = theme.PALETTES[theme.current_name()]
    assert p["success_bg"] in view.chip_local_files.styleSheet()
    view.clear_all_filters()
    assert not view.chip_local_files.isChecked()
    assert p["success_bg"] not in view.chip_local_files.styleSheet()
    assert not view.chip_local_files.looks_checked()


def test_a_blocked_uncheck_still_repaints_the_chip(view):
    chip = view.chip_search_terms
    chip.click()
    chip.blockSignals(True)
    chip.setChecked(False)
    chip.blockSignals(False)
    p = theme.PALETTES[theme.current_name()]
    assert p["success_bg"] not in chip.styleSheet()
    assert not chip.looks_checked()


# --- ------------------------------------------------------------------

def test_the_filtered_empty_message_names_every_filter_by_its_label(view):
    model = view.table.model()
    model.set_values("IsInPrivate", {True})
    model.set_condition("VisitCount", Condition(">", 10_000))
    text = view.table.empty_message()
    assert "InPrivate" in text and "IsInPrivate" not in text
    assert "Visits" in text
    assert view.table.empty_state_text() == text


def test_the_grid_body_offers_a_clear_filters_button_that_works(view, qtbot):
    view.chip_inprivate.click()
    view.table.model().set_condition("VisitCount", Condition(">", 10_000))
    qtbot.waitUntil(lambda: view.table.clear_filters_button.isVisible(),
                    timeout=2000)
    view.table.clear_filters_button.click()
    assert view.table.model().rowCount() == 300
    assert not view.chip_inprivate.looks_checked()
    assert not view.table.clear_filters_button.isVisible()


# --- ------------------------------------------------------------------

def test_history_opens_newest_first_with_blanks_last(view):
    model = view.table.model()
    times = [model.row_at(i)["AccessedUtc"] for i in range(model.rowCount())]
    dated = [t for t in times if t is not None]
    assert dated and len(dated) < len(times)
    assert dated == sorted(dated, reverse=True)
    assert all(t is None for t in times[len(dated):])


def test_the_header_shows_which_column_orders_the_rows(view):
    header = view.table.horizontalHeader()
    section = [c.key for c in view.table.model().columns].index("AccessedUtc")
    assert header.isSortIndicatorShown()
    assert header.sortIndicatorSection() == section
    assert header.sortIndicatorOrder() == Qt.DescendingOrder
    view.table._header_clicked(0)
    assert header.sortIndicatorSection() == 0
    assert header.sortIndicatorOrder() == Qt.AscendingOrder


def test_the_arrow_sits_in_the_left_padding_clear_of_the_label(view):
    from webcache.widgets.records_table import SECTION_QSS_PAD_X
    header = view.table.horizontalHeader()
    rect = QRectF(100, 0, 160, 28)
    arrow = header.sort_arrow_rect(rect)
    assert arrow.left() >= rect.left()
    assert arrow.right() <= rect.left() + SECTION_QSS_PAD_X


# --- a filtered column says so in its heading ---------------------------------

def _section(view, key):
    return [c.key for c in view.table.model().columns].index(key)


def test_a_filtered_heading_is_marked_and_the_rest_are_not(view, qtbot):
    header = view.table.horizontalHeader()
    flag, visits = _section(view, "IsInPrivate"), _section(view, "VisitCount")
    assert not header.is_filtered(flag) and not header.is_filtered(visits)
    view.table.model().set_values("IsInPrivate", {True})
    view.table.model().set_condition("VisitCount", Condition(">", 3))
    assert header.is_filtered(flag) and header.is_filtered(visits)
    assert not header.is_filtered(_section(view, "AccessedUtc"))
    view.clear_all_filters()
    assert not header.is_filtered(flag) and not header.is_filtered(visits)


def test_the_mark_is_painted_under_the_filtered_heading_only(view, qtbot):
    header = view.table.horizontalHeader()
    flag = _section(view, "IsInPrivate")
    view.table.scrollTo(view.table.model().index(0, flag))
    view.table.model().set_values("IsInPrivate", {True})
    qtbot.wait(50)
    primary = theme.color("primary")
    image = header.grab().toImage()
    ratio = image.devicePixelRatio()

    def colour_at(section):
        x = header.sectionViewportPosition(section) + header.sectionSize(section) / 2
        mark = header.filter_mark_rect(QRectF(0, 0, 10, header.height()))
        y = mark.center().y()
        return image.pixelColor(int(x * ratio), int(y * ratio))
    assert colour_at(flag) == primary
    other = flag - 1 if flag > 0 else flag + 1
    assert colour_at(other) != primary


def test_a_filtered_headings_tooltip_names_the_filter(view):
    model = view.table.model()
    visits = _section(view, "VisitCount")
    assert "Filtered" not in model.headerData(visits, Qt.Horizontal, Qt.ToolTipRole)
    model.set_condition("VisitCount", Condition(">", 3))
    tip = model.headerData(visits, Qt.Horizontal, Qt.ToolTipRole)
    assert 'Filtered: > "3"' in tip


def test_the_filter_line_gets_room_to_read_on_one_line(view, qtbot):
    """It sat at its narrowest width beside an empty stretch and wrapped a
    two-filter sentence into a column three lines tall."""
    model = view.table.model()
    model.set_values("IsInPrivate", {True})
    model.set_condition("VisitCount", Condition(">", 3))
    label = view._filter_desc_label
    qtbot.waitUntil(lambda: label.isVisible() and bool(label.text()))
    qtbot.wait(50)
    line = label.fontMetrics().height()
    assert label.width() > 500, label.width()
    assert label.height() < 2 * line, (label.height(), line, label.text())

