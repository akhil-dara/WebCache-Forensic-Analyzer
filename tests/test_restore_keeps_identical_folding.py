"""A restored column layout and "Hide identical columns" agree.

Seen on a real exhibit: Findings' strip said "1 column hidden … in all 5:
Interpretation" while Interpretation stood on screen repeating one
sentence five times -- the saved header, restored once per launch, had
shown it again. The mirror case is worse: a layout saved while a column
was folded away came back with that column hidden AS THE EXAMINER'S OWN
CHOICE, so on the next exhibit, where its values differ, it stayed out of
sight with nothing saying why."""
from webcache.widgets.column_spec import Column
from webcache.widgets.records_table import RecordsTable


def _columns():
    return [Column("Name", "Name", 120, kind="text"),
            Column("Note", "Note", 160, kind="text")]


def _rows(notes):
    return [{"Name": "row %d" % i, "Note": n} for i, n in enumerate(notes)]


def _table(qtbot, notes, hide_identical):
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records(_columns(), _rows(notes))
    t.set_hide_identical(hide_identical)
    return t


def test_a_restored_layout_does_not_unfold_an_identical_column(qtbot):
    saved = _table(qtbot, ["a", "b", "c"], False).save_column_state()
    t = _table(qtbot, ["same", "same", "same"], True)
    assert t.isColumnHidden(1)
    t.restore_column_state(saved)
    assert "Note" in t.auto_hidden_keys()
    assert t.isColumnHidden(1)


def test_a_layout_saved_while_folded_does_not_hide_a_varying_column(qtbot):
    saved = _table(qtbot, ["same", "same", "same"], True).save_column_state()
    t = _table(qtbot, ["a", "b", "c"], True)
    t.restore_column_state(saved)
    assert not t.isColumnHidden(1)
    assert not t.model().columns[1].hidden


def test_saving_while_folded_leaves_the_fold_on_screen(qtbot):
    t = _table(qtbot, ["same", "same", "same"], True)
    t.save_column_state()
    assert t.isColumnHidden(1)


def test_an_older_layout_cannot_hide_a_column_the_examiner_cannot_show(qtbot):
    """Layouts saved before the fix stored a folded column as hidden. Only
    an OPTIONAL column has a Columns-menu entry to bring it back, so a
    restored hide on any other column is a leftover fold and is ignored."""
    old = _table(qtbot, ["a", "b", "c"], False)
    old.horizontalHeader().setSectionHidden(1, True)
    saved = bytes(old.horizontalHeader().saveState())
    t = _table(qtbot, ["a", "b", "c"], True)
    t.restore_column_state(saved)
    assert not t.isColumnHidden(1)
    assert not t.model().columns[1].hidden
