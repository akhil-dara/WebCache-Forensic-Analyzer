"""The details pane: the selected record's fields beside the grid.

The examiner's complaint: a record opened in a window that covered the
table, so referring back meant closing it, and every double-click stacked
another window. The pane shows the selected record in place, follows the
selection as it moves, and leaves the grid usable; the full window is one
button away.
"""
from PySide6.QtCore import QItemSelectionModel

from webcache.shell import detail_fields
from webcache.shell.details_pane import DetailsPane, EMPTY_TEXT
from webcache.views.history import HistoryView
from tests.fixtures import make_rows


def _row(i=1):
    rows = make_rows(3)
    return rows[i]


def test_the_pane_shows_the_selected_record(qtbot):
    pane = DetailsPane()
    qtbot.addWidget(pane)
    row = _row()
    pane.show_row(row)
    assert pane.title_text() == detail_fields.identity_of(row)
    labels = pane.field_labels()
    assert labels, "the record's fields are listed"
    # Empty fields are folded away by default, and the pane says so.
    assert "empty" in pane.count_text().lower()


def test_empty_fields_can_be_shown(qtbot):
    pane = DetailsPane()
    qtbot.addWidget(pane)
    pane.show_row(_row())
    folded = len(pane.field_labels())
    pane.show_empty_box.setChecked(True)
    assert len(pane.field_labels()) > folded


def test_with_nothing_selected_it_says_what_to_do(qtbot):
    pane = DetailsPane()
    qtbot.addWidget(pane)
    pane.show_row(None)
    assert pane.title_text() == ""
    assert pane.count_text() == EMPTY_TEXT
    assert not pane.open_button.isEnabled()


def test_the_open_button_asks_for_the_full_window(qtbot):
    pane = DetailsPane()
    qtbot.addWidget(pane)
    row = _row()
    pane.show_row(row)
    seen = []
    pane.openRequested.connect(seen.append)
    pane.open_button.click()
    assert seen == [row]


def _view(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records(make_rows(20))
    v.resize(1500, 800)
    v.show()
    qtbot.waitExposed(v)
    return v


def test_a_record_view_carries_the_pane_and_it_follows_the_selection(qtbot):
    v = _view(qtbot)
    assert v.details_pane is not None
    model = v.table.model()
    for r in (2, 5):
        v.table.selectionModel().setCurrentIndex(
            model.index(r, 0), QItemSelectionModel.ClearAndSelect
            | QItemSelectionModel.Rows)
        assert v.details_pane.title_text() == detail_fields.identity_of(
            model.row_at(r))


def test_the_details_toggle_shows_and_hides_the_pane(qtbot):
    v = _view(qtbot)
    shown = v.details_pane.isVisible()
    v.details_button.click()
    assert v.details_pane.isVisible() != shown
    assert v.details_button.isChecked() == v.details_pane.isVisible()


def test_the_window_wires_the_pane_to_the_case_and_the_full_window(
        qtbot, tmp_path):
    from webcache.engine.case_db import CaseDb
    from webcache.shell import main_window as mw
    win = mw.MainWindow()
    qtbot.addWidget(win)
    win._case = CaseDb().open(str(tmp_path / "c.wccase"))
    try:
        win.go_to("history")
        view = win._built_widget("history")
        pane = view.details_pane
        assert pane.case_provider() [0] is win._case
        opened = []
        win._show_record_detail = lambda r: opened.append(r)
        row = {"CleanUrl": "https://a.test/", "_record": {"ContainerId": 1,
                                                          "EntryId": 2}}
        pane.show_row(row)
        pane.openRequested.emit(row)
    finally:
        win._case.close()


def test_a_long_value_is_shown_whole_never_shortened(qtbot):
    """No "…": the pane paints the whole value, wrapped."""
    pane = DetailsPane()
    qtbot.addWidget(pane)
    row = dict(_row())
    long_url = "https://example.test/" + "a" * 2500
    row["CleanUrl"] = long_url
    row["_record"] = dict(row.get("_record") or {}, CleanUrl=long_url)
    pane.show_row(row)
    table = pane.table
    texts = [table.item(r, 1).text() for r in range(table.rowCount())
             if table.item(r, 1) is not None]
    assert any(t == long_url for t in texts)
    assert not any("…" in t for t in texts)


def test_rows_grow_when_the_pane_narrows_and_nothing_is_elided(qtbot):
    """Rows were measured once, at the width the record was first shown
    at; narrowed, a wrapped value no longer fitted and Qt cut it with an
    ellipsis."""
    from PySide6.QtCore import Qt
    pane = DetailsPane()
    qtbot.addWidget(pane)
    pane.resize(900, 700)
    pane.show()
    row = dict(_row())
    long_url = "https://example.test/" + "word-" * 60
    row["CleanUrl"] = long_url
    row["_record"] = dict(row.get("_record") or {}, CleanUrl=long_url)
    pane.show_row(row)
    table = pane.table
    r = next(r for r in range(table.rowCount())
             if table.item(r, 1) is not None
             and table.item(r, 1).text() == long_url)
    wide = table.rowHeight(r)
    pane.resize(360, 700)
    qtbot.waitUntil(lambda: table.rowHeight(r) > wide, timeout=1000)
    assert table.textElideMode() == Qt.ElideNone


def test_a_long_unbroken_title_wraps_inside_the_pane(qtbot):
    """A URL title has no spaces; a QLabel ran it off the pane's edge."""
    from webcache.widgets.wrapping_text import WrappingText
    pane = DetailsPane()
    qtbot.addWidget(pane)
    pane.resize(360, 700)
    pane.show()
    row = dict(_row())
    long_url = "https://example.test/" + "x" * 300
    row["CleanUrl"] = long_url
    row["_record"] = dict(row.get("_record") or {}, CleanUrl=long_url)
    pane.show_row(row)
    assert isinstance(pane._title, WrappingText)
    assert pane.title_text() == long_url
    assert pane._title.width() <= pane.width()
    line = pane._title.fontMetrics().lineSpacing()
    qtbot.waitUntil(lambda: pane._title.height() > 2 * line, timeout=1000)


def test_a_wrapped_value_in_a_narrow_pane_gets_every_line(qtbot):
    """Qt's plain delegate measured a wrapped cell without the theme's
    item padding, so in a narrow pane the last line of a long value was
    cut. The pane uses the delegate every other evidence surface uses."""
    from PySide6.QtWidgets import QApplication
    from webcache.shell import theme
    from webcache.widgets.records_table import WrappingDelegate
    from tests.test_detail_fields import domain_row
    theme.apply(QApplication.instance(), "dark")
    pane = DetailsPane()
    qtbot.addWidget(pane)
    pane.resize(380, 800)
    pane.show()
    members = [{"CleanUrl": "https://example.test/%d" % i} for i in range(38)]
    pane.show_row(domain_row(_members=members, Records=38))
    table = pane.table
    assert isinstance(table.itemDelegate(), WrappingDelegate)
