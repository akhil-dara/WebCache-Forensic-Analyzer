"""View > Reset column layout: the way back from a layout that no longer
fits. A layout is saved per view and restored on every launch; one saved
from a cramped window (Containers' Partition squeezed until each SID
wrapped to five lines) had no way back but dragging every column."""
from webcache.widgets.column_spec import Column
from webcache.widgets.records_table import RecordsTable


def _columns():
    return [Column("Name", "Name", 220, kind="text"),
            Column("Path", "Path", 360, kind="text"),
            Column("Extra", "Extra", 180, kind="text", optional=True)]


def _table(qtbot):
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records(_columns(), [{"Name": "a%d" % i, "Path": "p%d" % i,
                                "Extra": "x%d" % i} for i in range(3)])
    return t


def test_reset_restores_declared_widths_order_and_visibility(qtbot):
    t = _table(qtbot)
    header = t.horizontalHeader()
    header.resizeSection(1, 90)          # squeezed
    header.moveSection(2, 0)             # dragged to the front
    t.set_column_hidden("Extra", False)  # an optional column shown
    t.reset_column_layout()
    assert [header.logicalIndex(v) for v in range(3)] == [0, 1, 2]
    assert header.sectionSize(0) == 220 and header.sectionSize(1) == 360
    assert t.isColumnHidden(2) and t.model().columns[2].hidden


def test_reset_keeps_identical_columns_folded(qtbot):
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records(_columns()[:2], [{"Name": "a%d" % i, "Path": "same"}
                                   for i in range(3)])
    t.set_hide_identical(True)
    t.reset_column_layout()
    assert t.isColumnHidden(1)


def test_the_view_menu_resets_the_view_on_screen(qtbot):
    from webcache.shell.main_window import MainWindow
    from tests.fixtures import make_rows
    from tests.test_main_window import _fake_evidence_set
    w = MainWindow()
    qtbot.addWidget(w)
    w._on_evidence_loaded({"rows": make_rows(5), "parser": None},
                          _fake_evidence_set())
    w.go_to("history")
    table = w._built_widget("history").table
    header = table.horizontalHeader()
    address = [c.key for c in table.model().columns].index("CleanUrl")
    want = table.model().columns[address].width
    header.resizeSection(address, want + 333)
    assert w.reset_columns_action.isEnabled()
    w.reset_columns_action.trigger()
    assert header.sectionSize(address) == want
    assert "reset" in w._status_message.full_text().lower()
    w.go_to("dashboard")
    assert not w.reset_columns_action.isEnabled()
