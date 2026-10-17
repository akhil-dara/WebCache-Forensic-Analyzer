"""The raw surfaces show and export the WHOLE stored
value.

The Table Browser is the one grid of raw stored values, and it showed a
one-line, elided rendering of a 400-character (text) or 48-byte (binary)
preview; it did not follow Wrap. Search hits carried the same preview as
"Matched value -- as stored", and in a search export that truncated string
was the ONLY raw value. Display length is the row cap's job, never the
data's: the grid holds the whole value and caps the painted cell with a
marker, exactly as every record grid does.
"""
import csv

import openpyxl
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from webcache.shell import export_formats as F
from webcache.shell import search_loader
from webcache.views.browser import TableBrowserView
from tests.test_ese_parser_search import _parser as _search_parser
from tests.test_ese_parser_search import _Table
from tests.test_table_browser_view import _StubParser

#: Synthetic, 1,000 characters, printable ASCII (so "as stored" = itself).
LONG = ("https://example.test/needle/" + "abcdefghij/" * 100)[:1000]


@pytest.fixture(autouse=True)
def _scratch_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")


class _Rows(_StubParser):
    def __init__(self, rows):
        super().__init__(row_count=0)
        self._rows = rows


def _browser(qtbot, rows):
    v = TableBrowserView(page_size=50)
    qtbot.addWidget(v)
    v.resize(1328, 700)
    v.set_parser(_Rows(rows))
    v.select_table("Container_2")
    v.show()
    qtbot.waitExposed(v)
    return v


# --- 2. the Table Browser ---------------------------------------------------

def test_the_browser_grid_holds_a_long_text_cell_whole(qtbot):
    v = _browser(qtbot, [[1, LONG]])
    assert v.grid.item(0, 1).text() == LONG
    assert v.grid.model().index(0, 1).data(Qt.DisplayRole) == LONG


def test_the_browser_grid_wraps_and_never_elides(qtbot):
    v = _browser(qtbot, [[1, LONG]])
    assert v.grid.wordWrap()
    assert v.grid.textElideMode() == Qt.ElideNone


def test_a_long_browser_cell_is_capped_with_the_marker(qtbot):
    v = _browser(qtbot, [[1, LONG], [2, "short"]])
    default = v.grid.verticalHeader().defaultSectionSize()
    qtbot.waitUntil(lambda: v.grid.rowHeight(0) > 2 * default, timeout=2_000)
    assert v.grid.rowHeight(0) < 10 * v.grid.fontMetrics().lineSpacing(), (
        "the row grew to the whole value instead of the cap")
    assert v.grid_cell_is_capped(0, 1)
    assert not v.grid_cell_is_capped(1, 1)
    assert v.grid.columnWidth(1) <= 420, "one long value widened its column"


def test_a_binary_cell_ends_in_a_marker_and_copies_every_byte(qtbot):
    blob = bytes(range(256)) * 4
    v = _browser(qtbot, [[1, blob]])
    shown = v.grid.item(0, 1).text()
    assert "View these bytes" in shown and "more bytes" in shown, shown
    v._copy_grid_cell(0, 1)
    assert QGuiApplication.clipboard().text() == " ".join(
        "%02X" % b for b in blob)


def test_turning_wrap_off_reaches_the_browser(qtbot):
    from webcache.shell.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    browser = w._ensure_view_built("browser")
    history = w._ensure_view_built("history")
    assert browser.grid.wordWrap()
    history.wrap_button.click()
    assert not browser.grid.wordWrap()
    assert browser.grid.textElideMode() == Qt.ElideRight
    history.wrap_button.click()
    assert browser.grid.wordWrap()
    assert browser.grid.textElideMode() == Qt.ElideNone


# --- 3. search hits ---------------------------------------------------------

def _hits():
    parser = _search_parser({"T1": _Table(["Url"], [[LONG], ["other"]])})
    results = parser.search_all_tables("needle")
    assert len(results) == 1
    return search_loader.search_rows(results)


def test_a_search_hit_carries_the_whole_stored_value():
    rows = _hits()
    assert rows[0]["RawValue"] == LONG


def test_the_search_export_writes_the_whole_stored_value(qtbot, tmp_path):
    from webcache.views.search import SearchView
    view = SearchView()
    qtbot.addWidget(view)
    columns = view._segments_by_key["hits"].columns
    rows = _hits()
    csv_path, xlsx_path = str(tmp_path / "s.csv"), str(tmp_path / "s.xlsx")
    F.write_view_csv(rows, columns, csv_path, {})
    F.write_view_xlsx(rows, columns, xlsx_path, {"view_label": "Search"})
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        header, line = list(csv.reader(fh))
    col = header.index("Matched value — as stored")
    assert line[col] == LONG
    ws = openpyxl.load_workbook(xlsx_path).active
    assert ws.cell(row=2, column=col + 1).value == LONG


def test_the_hit_pane_shows_the_whole_stored_value():
    class _P(_StubParser):
        def __init__(self):
            super().__init__(row_count=0)
            self._columns = ["Url"]
            self._rows = [[LONG]]

        def get_table_rows_raw(self, table_name, limit=200, offset=0):
            return self._columns, self._rows[offset:offset + limit]

    result = {"table": "Container_2", "row_index": 1,
              "matched_columns": ["Url"], "row": {"Url": LONG}}
    rows = search_loader.hit_field_rows(_P(), result)
    stored = [r["Stored"] for r in rows if r["Column"] == "Url"]
    assert stored == [LONG]
