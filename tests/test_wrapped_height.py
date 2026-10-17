"""A wrapped row is given the height of the lines it PAINTS.

Found on screen (Deleted Records, the largest sample exhibit, real font):
a 77-character URL in a 174 px column was given three lines and painted
four, and the style ended the third with an ellipsis -- a cut value on the
grid the examiner reads most. The row's height is asked of the style at the
cell's whole width, but the app's QSS gives every QTableView item
"padding: 0px 9px", and the text is painted inside that padding: 18 px
narrower than it was measured. A value within 18 px of a wrap boundary
needed one line more than its row was given.

Checked on a record grid and on the whole-row view, which exists to show
every line of a value. Synthetic values only.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from webcache.shell import theme
from webcache.widgets.column_spec import Column
from webcache.widgets.records_table import ROW_LINE_CAP, RecordsTable
from tests.test_table_row_view import _dialog as _row_dialog


@pytest.fixture(autouse=True)
def _scratch_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")


@pytest.fixture(autouse=True)
def _app_stylesheet():
    """The padding is the app's QSS; without it there is nothing to see."""
    theme.apply(QApplication.instance(), "dark")


def _values():
    """URL-shaped values whose lengths walk across several wrap
    boundaries of a narrow column, so some land in the padding's gap."""
    out = []
    for k in range(1, 40):
        out.append("https://media.example.test/Ab%dCdEf/" % k
                   + "-".join("word%d" % i for i in range(k // 2 + 1)) + ".png")
    return out


def _painted_lines(view, index):
    """How many lines the style paints this cell's text in: laid out at the
    width the text is drawn in (the item's text rect, less the style's text
    margin), with the delegate's own break points."""
    delegate = view.itemDelegateForIndex(index)
    opt = QStyleOptionViewItem()
    view.initViewItemOption(opt)
    opt.rect = view.visualRect(index)
    delegate.initStyleOption(opt, index)
    style = view.style()
    rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, view)
    margin = style.pixelMetric(QStyle.PM_FocusFrameHMargin, None, view) + 1
    layout = QTextLayout(opt.text.replace("\n", " "), opt.font)
    wrap = QTextOption()
    wrap.setWrapMode(QTextOption.WordWrap)
    layout.setTextOption(wrap)
    layout.beginLayout()
    lines, height = 0, 0.0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(rect.width() - 2 * margin)
        lines += 1
        height = line.height()
    layout.endLayout()
    return lines, height


def _short_rows(view, column, rows, cap=None):
    """(row, lines needed, line height, row height) for every row whose
    value is painted in more than one line and, under a cap, not capped."""
    short = []
    for r in rows:
        index = view.model().index(r, column)
        lines, height = _painted_lines(view, index)
        if lines < 2 or (cap is not None and lines > cap):
            continue
        if view.rowHeight(r) < lines * height:
            short.append((r, lines, round(height, 1), view.rowHeight(r)))
    return short


def test_a_record_grid_row_is_as_tall_as_the_lines_it_paints(qtbot):
    values = _values()
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records([Column("Name", "Name", 120),
                   Column("Url", "Url", 174, kind="url")],
                  [{"Name": "n%d" % i, "Url": v} for i, v in enumerate(values)])
    t.resize(900, 3000)
    t.show()
    qtbot.waitExposed(t)
    default = t.verticalHeader().defaultSectionSize()
    qtbot.waitUntil(lambda: t.rowHeight(len(values) - 1) > default,
                    timeout=2_000)
    qtbot.wait(80)
    short = _short_rows(t, 1, range(len(values)), cap=ROW_LINE_CAP)
    assert short == [], "rows painted in more lines than they were given: %s" % short


def test_the_whole_row_view_row_is_as_tall_as_the_lines_it_paints(qtbot):
    values = _values()
    names = ["C%d" % i for i in range(len(values))]
    dialog = _row_dialog(qtbot, names, [values])
    dialog.resize(900, 700)
    dialog.show()
    qtbot.waitExposed(dialog)
    table = dialog.table
    table.setColumnWidth(1, 174)
    table.resizeRowsToContents()
    rows = [r for r in range(table.rowCount())
            if table.item(r, 1) is not None and table.item(r, 1).text() in values]
    assert len(rows) == len(values)
    short = _short_rows(table, 1, rows)
    assert short == [], "rows painted in more lines than they were given: %s" % short
