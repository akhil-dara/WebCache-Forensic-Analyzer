"""A column can say what an empty cell MEANS. "Carved from" is empty on
every live row -- not unknown, just not carved -- so its file filter lists
that, not a bare "(blank)". The cells and exports keep the true empty."""
from webcache.provenance import CARVED_ORIGIN, LIVE_ORIGIN
from webcache.views.history import HistoryView
from webcache.widgets.filter_popup import FilterPopup
from webcache.widgets.record_model import RecordTableModel

LIVE_SOURCE = "(live record, not carved)"


def _carved_from(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    columns = view._segments_by_key[view._active_key].columns
    return next(c for c in columns if c.key == "Source")


def _rows():
    return [{"Url": "https://a.example.test/", "Origin": LIVE_ORIGIN,
             "Source": ""},
            {"Url": "https://b.example.test/", "Origin": CARVED_ORIGIN,
             "Source": "WebCacheV01.dat"}]


def test_the_file_filter_names_what_a_blank_carved_from_means(qtbot):
    column = _carved_from(qtbot)
    model = RecordTableModel([column], _rows())
    popup = FilterPopup(model, column)
    qtbot.addWidget(popup)
    labels = [popup.values_list.item(i).text()
              for i in range(popup.values_list.count())]
    assert any(l.startswith(LIVE_SOURCE) for l in labels), labels
    assert not any(l.startswith("(blank)") for l in labels), labels


def test_the_filter_line_says_it_too(qtbot):
    column = _carved_from(qtbot)
    model = RecordTableModel([column], _rows())
    model.set_values("Source", {""})
    assert LIVE_SOURCE in model.chip_text()
    assert model.row_at(0)["Source"] == ""      # the cell keeps its empty


def test_a_column_that_says_nothing_still_reads_blank(qtbot):
    from webcache.widgets.column_spec import Column, blank_label
    assert blank_label(Column("X", "X", 50)) == "(blank)"
    assert blank_label(None) == "(blank)"
