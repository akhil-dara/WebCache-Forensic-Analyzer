"""Table Browser filters column by column, like every record grid: a
right-click on a heading opens the same filter popup (value list with
search, conditions), over the whole open table, combined with the row
filter box and the sort."""
from PySide6.QtCore import QPoint

from tests.test_table_browser_view import _StubParser
from webcache.views.browser import TableBrowserView
from webcache.widgets.filter_popup import FilterPopup


def _open(qtbot, rows=450):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=rows))
    v.select_table("Container_2")
    return v


def _labels(v):
    return [v.grid.verticalHeaderItem(r).text()
            for r in range(v.grid.rowCount())]


def test_a_column_filter_reads_every_value_of_the_whole_table(qtbot):
    v = _open(qtbot)
    popup = v.open_column_filter(1)
    assert isinstance(popup, FilterPopup)
    assert popup.values_list.count() == 450
    popup.check_only({"value-3", "value-401"})
    assert popup.apply()
    assert _labels(v) == ["4", "402"]
    assert "2 of 450 rows" in v.row_count_label.text()
    assert "Value" in v.row_count_label.text()


def test_column_filter_and_row_filter_combine(qtbot):
    v = _open(qtbot)
    popup = v.open_column_filter(1)
    popup.check_only({"value-30", "value-31", "value-7"})
    popup.apply()
    v.row_filter_box.setText("value-3")
    v.apply_row_filter_now()
    assert _labels(v) == ["31", "32"]


def test_a_sort_keeps_the_column_filter(qtbot):
    v = _open(qtbot)
    popup = v.open_column_filter(1)
    popup.check_only({"value-5", "value-9"})
    popup.apply()
    v.sort_rows_by(0, descending=True)
    assert _labels(v) == ["10", "6"]


def test_right_clicking_a_heading_opens_the_filter(qtbot):
    v = _open(qtbot)
    header = v.grid.horizontalHeader()
    x = header.sectionViewportPosition(1) + 5
    header.customContextMenuRequested.emit(QPoint(x, 5))
    assert isinstance(v._column_popup, FilterPopup)
    assert v._column_popup.column.key == "Value"


def test_clear_removes_the_column_filter(qtbot):
    v = _open(qtbot)
    popup = v.open_column_filter(1)
    popup.check_only({"value-5"})
    popup.apply()
    v.clear_row_view()
    assert v.grid.rowCount() == 200
    assert v.open_column_filter(1).chosen_values() is None


def test_a_new_table_starts_unfiltered(qtbot):
    v = _open(qtbot)
    popup = v.open_column_filter(1)
    popup.check_only({"value-5"})
    popup.apply()
    v.select_table("CookieEntryEx_1")
    v.select_table("Container_2")
    assert v.grid.rowCount() == 200
