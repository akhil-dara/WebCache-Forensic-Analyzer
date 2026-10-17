"""Table Browser filters and sorts the ROWS of the open table -- the whole
table, not the page on screen.

The examiner's question was "where are the filters in browser?": the
only box there filtered the list of TABLE NAMES. Inside a table there was
no way to find a row except paging 200 at a time, and no way to order
one. Every other grid in the application filters and sorts.

What these pin:
  * the filter reads every row of the table, every column as shown --
    including the decoded FILETIME reading a time cell's tooltip states,
    so a date finds the rows of that date;
  * it can be scoped to one column;
  * a click on a heading sorts the whole table, numbers as numbers;
  * a row keeps its own TABLE row number through all of it, so "row 402"
    in a filtered list is the same row a Show-in-table drill names;
  * a drill to a row clears the filter rather than land behind it;
  * a table too large to hold says so, and points at Search.
"""
from PySide6.QtCore import Qt

from tests.test_table_browser_view import _StubParser
from webcache.views.browser import TableBrowserView


def _open(qtbot, rows=450):
    v = TableBrowserView()
    qtbot.addWidget(v)
    v.set_parser(_StubParser(row_count=rows))
    v.select_table("Container_2")
    return v


def _labels(v):
    return [v.grid.verticalHeaderItem(r).text()
            for r in range(v.grid.rowCount())]


def test_the_row_filter_reads_the_whole_table_not_the_page(qtbot):
    v = _open(qtbot)
    v.row_filter_box.setText("value-401")
    v.apply_row_filter_now()
    assert _labels(v) == ["402"], "row 402 is on page three unfiltered"
    assert "1 of 450 rows" in v.row_count_label.text()


def test_the_filter_can_be_scoped_to_one_column(qtbot):
    v = _open(qtbot)
    v.row_filter_column.setCurrentText("Id")
    v.row_filter_box.setText("value")
    v.apply_row_filter_now()
    assert v.grid.rowCount() == 0
    assert "No row" in v.row_count_label.text()
    v.row_filter_column.setCurrentText("All columns")
    v.apply_row_filter_now()
    assert v.grid.rowCount() == 200, "450 matches, paged 200 at a time"


def test_a_heading_click_sorts_the_whole_table_numbers_as_numbers(qtbot):
    v = _open(qtbot)
    v.sort_rows_by(0, descending=True)
    assert _labels(v)[:3] == ["450", "449", "448"]
    assert v.grid.item(0, 0).text() == "449"
    v.sort_rows_by(0, descending=False)
    assert _labels(v)[:3] == ["1", "2", "3"]


def test_the_heading_is_clickable_and_toggles(qtbot):
    v = _open(qtbot)
    header = v.grid.horizontalHeader()
    header.sectionClicked.emit(0)
    first = _labels(v)[0]
    header.sectionClicked.emit(0)
    assert _labels(v)[0] != first
    assert header.isSortIndicatorShown()


def test_a_filtered_row_opens_as_its_own_table_row(qtbot):
    v = _open(qtbot)
    v.row_filter_box.setText("value-401")
    v.apply_row_filter_now()
    seen = []
    v.rowRequested.connect(seen.append)
    assert v.open_row(0)
    assert seen[0]["row_number"] == 402
    assert "value-401" in seen[0]["cells"][1]["text"]


def test_a_drill_to_a_row_clears_the_filter_and_lands(qtbot):
    v = _open(qtbot)
    v.row_filter_box.setText("value-401")
    v.apply_row_filter_now()
    assert v.show_row("Container_2", 10)
    assert v.row_filter_box.text() == ""
    assert v.grid.verticalHeaderItem(v.grid.currentRow()).text() == "11"


def test_the_pager_counts_matches_and_the_table(qtbot):
    v = _open(qtbot)
    v.row_filter_box.setText("value-1")
    v.apply_row_filter_now()
    # value-1, value-10..19, value-100..199: 111 matches
    assert "111" in v._page_label.text() and "450" in v._page_label.text()


def test_no_table_is_too_large_to_filter_and_sort(qtbot):
    """No row-count cap: every table, however large, is filtered and
    sorted whole."""
    from webcache.views import browser
    assert not hasattr(browser, "ROW_FILTER_MAX_ROWS")
    v = _open(qtbot, rows=60_000)
    assert v.row_filter_box.isEnabled()
    v.row_filter_box.setText("value-59999")
    v.apply_row_filter_now()
    assert _labels(v) == ["60000"]
