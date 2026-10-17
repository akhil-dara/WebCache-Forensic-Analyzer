"""The Origin column filters like any other: its heading opens a list of
the origins on screen with their counts, and unticking one hides those
rows. It filters on the label the grid paints, the filter line (which
every export records) names it, and Clear all filters removes it."""
from PySide6.QtCore import Qt

from webcache.provenance import CARVED_ORIGIN, LIVE_ORIGIN
from webcache.widgets.column_spec import Column
from webcache.widgets.records_table import RecordsTable

COLUMNS = [Column("Url", "URL", 200, kind="url")]


def _rows():
    live = [{"Url": "https://a.example.test/%d" % i, "Origin": LIVE_ORIGIN}
            for i in range(3)]
    carved = [{"Url": "https://b.example.test/%d" % i, "Origin": CARVED_ORIGIN}
              for i in range(2)]
    return live + carved


def _table(qtbot):
    table = RecordsTable()
    qtbot.addWidget(table)
    table.set_records(COLUMNS, _rows())
    table.show()
    qtbot.waitExposed(table)
    return table


def _origins_shown(table):
    model = table.model()
    return {model.origin_label(model.row_at(r)) for r in range(model.rowCount())}


def test_the_model_counts_each_origin_in_paint_order(qtbot):
    table = _table(qtbot)
    assert table.model().origin_counts() == [("Live", 3), ("Carved", 2)]


def test_keeping_only_carved_hides_every_live_row_and_says_so(qtbot):
    table = _table(qtbot)
    model = table.model()
    model.set_origin_filter({"Carved"})
    assert model.rowCount() == 2
    assert _origins_shown(table) == {"Carved"}
    assert "Origin: Is Carved" in model.chip_text()
    assert model.origin_filter() == frozenset({"Carved"})


def test_clear_all_filters_removes_it(qtbot):
    table = _table(qtbot)
    model = table.model()
    model.set_origin_filter({"Live"})
    model.clear_all()
    assert model.rowCount() == 5
    assert model.origin_filter() is None
    assert "Origin" not in model.chip_text()


def test_clicking_the_heading_offers_every_origin_with_its_count(qtbot):
    table = _table(qtbot)
    qtbot.mouseClick(table.corner_button, Qt.LeftButton)
    menu = table.origin_menu
    assert menu is not None and menu.isVisible()
    choices = [a for a in menu.actions() if a.isCheckable()]
    assert [a.text() for a in choices] == ["Live (3)", "Carved (2)"]
    assert all(a.isChecked() for a in choices)
    menu.close()


def test_unticking_live_in_the_menu_leaves_only_carved(qtbot):
    table = _table(qtbot)
    qtbot.mouseClick(table.corner_button, Qt.LeftButton)
    live = next(a for a in table.origin_menu.actions()
                if a.text().startswith("Live"))
    live.trigger()
    assert _origins_shown(table) == {"Carved"}
    table.origin_menu.close()
    # Reopened, the menu shows what is in force.
    qtbot.mouseClick(table.corner_button, Qt.LeftButton)
    states = {a.text(): a.isChecked() for a in table.origin_menu.actions()
              if a.isCheckable()}
    assert states == {"Live (3)": False, "Carved (2)": True}
    table.origin_menu.close()


def test_the_heading_no_longer_selects_every_row(qtbot):
    table = _table(qtbot)
    qtbot.mouseClick(table.corner_button, Qt.LeftButton)
    table.origin_menu.close()
    assert not table.selectionModel().selectedRows()
