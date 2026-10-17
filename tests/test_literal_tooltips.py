"""Evidence text in a tooltip is shown literally, never as markup.

Qt decides per tooltip whether to render it as rich text
(Qt.mightBeRichText). A stored value starting with a tag -- a page title
'<b>bold</b><img src="x">', say -- was rendered as markup in every tooltip
that carried it: bold text, and an <img> that shows nothing and could
point anywhere. Each tooltip that can carry evidence must, once Qt has
decided how to render it, show exactly the stored characters.
"""
import pytest
from PySide6.QtGui import Qt as QtGuiNS, QTextDocument
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QWidget

MARKUP = '<b>bold</b><img src="x">'


def shown(tip):
    """What a tooltip actually displays: Qt renders it as rich text when
    mightBeRichText says so, as plain text otherwise."""
    tip = tip or ""
    if QtGuiNS.mightBeRichText(tip):
        doc = QTextDocument()
        doc.setHtml(tip)
        return doc.toPlainText()
    return tip


def assert_literal(tip):
    assert MARKUP in shown(tip), (
        "tooltip rendered the evidence as markup: %r -> %r"
        % (tip, shown(tip)))


@pytest.fixture(autouse=True)
def _settings_go_somewhere_disposable(tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")


def test_grid_cell_tooltip(qtbot):
    from webcache.widgets.record_model import RecordTableModel
    from tests.fixtures import FIXTURE_COLUMNS, make_rows
    rows = make_rows(3)
    rows[0]["Title"] = MARKUP
    model = RecordTableModel(list(FIXTURE_COLUMNS), rows)
    col = [c.key for c in model.columns].index("Title")
    row = next(i for i in range(model.rowCount())
               if model.row_at(i)["Title"] == MARKUP)
    assert_literal(model.data(model.index(row, col), Qt.ToolTipRole))


def test_wrapping_text_shows_markup_literally(qtbot):
    from webcache.widgets.wrapping_text import WrappingText
    text = WrappingText(MARKUP)
    qtbot.addWidget(text)
    assert text.toPlainText() == MARKUP


def test_eliding_button_tooltip(qtbot):
    from webcache.shell.record_detail import ElidingButton
    button = ElidingButton()
    qtbot.addWidget(button)
    button.set_full_text(MARKUP, "a note")
    assert_literal(button.toolTip())


def test_status_bar_label_tooltip(qtbot):
    from webcache.shell.main_window import _ElidingStatusLabel
    label = _ElidingStatusLabel()
    qtbot.addWidget(label)
    label.set_full_text(MARKUP)
    assert_literal(label.toolTip())


def test_consent_file_row_tooltip(qtbot):
    from webcache.shell.open_evidence import _FileRow
    row = _FileRow(r"C:\case\%s.dat" % MARKUP)
    qtbot.addWidget(row)
    tips = [w.toolTip() for w in row.findChildren(QWidget) if w.toolTip()]
    assert tips
    for tip in tips:
        assert_literal(tip)


def test_hex_view_strings_tooltip(qtbot):
    from webcache.widgets.hex_view import _StringsModel
    model = _StringsModel([(16, "ascii", MARKUP)], 0)
    assert_literal(model.data(model.index(0, 0), Qt.ToolTipRole))


def _item_tooltips(dialog):
    tips = []
    for table in dialog.findChildren(QTableWidget):
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item is not None and item.toolTip():
                    tips.append(item.toolTip())
    return tips


def test_record_dialog_value_tooltips(qtbot):
    from webcache.shell.record_detail import RecordDetailDialog
    from tests.test_detail_fields import history_row
    row = history_row(Title=MARKUP)
    row["_record"] = dict(row["_record"], SPS_PageTitle=MARKUP)
    parent = QWidget()
    parent.show()
    dlg = RecordDetailDialog(row, parent)
    try:
        dlg.show()
        qtbot.waitExposed(dlg)
        carrying = [t for t in _item_tooltips(dlg) if "img" in t]
        assert carrying, "no value tooltip carries the synthetic title"
        for tip in carrying:
            assert_literal(tip)
    finally:
        dlg.close()
        parent.close()


def test_table_row_dialog_tooltips(qtbot):
    from webcache.shell.table_row_detail import TableRowDialog
    from tests.test_table_row_view import _page
    page = _page([MARKUP, "Value"], [{MARKUP: MARKUP, "Value": "v"}])
    parent = QWidget()
    parent.show()
    dlg = TableRowDialog(page["columns"], page["rows"][0], parent,
                         table=page["display_name"])
    try:
        dlg.show()
        qtbot.waitExposed(dlg)
        carrying = [t for t in _item_tooltips(dlg) if "img" in t]
        assert len(carrying) >= 2, carrying      # the name and the value
        for tip in carrying:
            assert_literal(tip)
    finally:
        dlg.close()
        parent.close()
