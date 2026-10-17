"""Restoring saved column state must never overwrite what the
sort indicator says about the model's actual order."""
from PySide6.QtCore import Qt

from webcache.widgets.records_table import RecordsTable
from tests.fixtures import FIXTURE_COLUMNS, make_rows


def _table(qtbot):
    t = RecordsTable()
    qtbot.addWidget(t)
    t.resize(1500, 500)
    t.set_records(list(FIXTURE_COLUMNS), make_rows(50))
    t.sort_by_key("AccessedUtc", True)
    t.show()
    return t


def _section(t, key):
    return [c.key for c in t.model().columns].index(key)


def _assert_mirrors_sort(t):
    header = t.horizontalHeader()
    assert header.isSortIndicatorShown()
    assert header.sortIndicatorSection() == _section(t, "AccessedUtc")
    assert header.sortIndicatorOrder() == Qt.DescendingOrder
    assert t.sort_keys() == [("AccessedUtc", True)]


def test_a_state_saved_after_the_examiner_sorted_another_column(qtbot):
    """Saved at HEAD after clicking Address: indicator on Address, ascending."""
    saved = _table(qtbot)
    saved._header_clicked(_section(saved, "CleanUrl"))
    state = saved.save_column_state()
    fresh = _table(qtbot)
    fresh.restore_column_state(state)
    _assert_mirrors_sort(fresh)


def test_a_state_saved_before_the_indicator_existed(qtbot):
    """A pre-task build never showed the indicator; its state says hidden."""
    old = _table(qtbot)
    old.horizontalHeader().setSortIndicatorShown(False)
    state = old.save_column_state()
    fresh = _table(qtbot)
    fresh.restore_column_state(state)
    _assert_mirrors_sort(fresh)


def test_restoring_with_a_signature_also_mirrors_the_sort(qtbot):
    saved = _table(qtbot)
    saved.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)
    fresh = _table(qtbot)
    fresh.restore_column_state(saved.save_column_state(),
                               signature=saved.column_signature())
    _assert_mirrors_sort(fresh)
