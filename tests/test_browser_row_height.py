"""A Table Browser row holding short integers and
a long binary cell is not several lines tall. The binary cell shows one
line of hex and the marker naming the bytes not shown -- nothing is cut
silently -- instead of a block of hex that makes every row ~84 px."""
from tests.test_table_browser_view import _StubParser
from webcache.shell import table_browser_loader
from webcache.views.browser import TableBrowserView


class _BlobParser(_StubParser):
    def __init__(self):
        super().__init__(row_count=0)
        self._rows = [[i, bytes(range(200))] for i in range(6)]


def test_a_row_with_a_long_blob_is_at_most_three_lines(qtbot):
    view = TableBrowserView(page_size=10)
    qtbot.addWidget(view)
    view.resize(1400, 800)
    view.show()
    qtbot.waitExposed(view)
    view.set_parser(_BlobParser())
    view.select_table("Container_2")
    line = view.grid.fontMetrics().lineSpacing()
    height = view.grid.rowHeight(0)
    assert height <= 3 * line + 12, (height, line)
    text = view.grid.item(0, 1).text()
    assert "more bytes" in text      # the rest is named, never cut silently


def test_the_grid_hex_is_one_line_at_the_column_width():
    assert table_browser_loader.GRID_HEX_BYTES <= 32
