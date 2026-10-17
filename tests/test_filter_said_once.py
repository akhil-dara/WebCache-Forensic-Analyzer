"""The filter sentence is said ONCE -- in the grid body when the
grid is empty, in the count/filter line otherwise."""
import pytest

from webcache.views.history import HistoryView
from webcache.widgets.record_filter import Condition
from tests.fixtures import make_rows


@pytest.fixture
def view(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records(make_rows(120))
    v.resize(1500, 800)
    v.show()
    qtbot.waitExposed(v)
    return v


def test_an_emptied_grid_says_it_in_the_body_only(view):
    view.table.model().set_condition("VisitCount", Condition(">", 10_000))
    assert view.count_label.text().startswith("0 of 120")
    assert "match" not in view.count_label.text()
    assert not view._filter_desc_label.isVisible()
    assert "Visits" in view.table.empty_state_text()


def test_a_populated_filtered_grid_says_it_in_the_filter_line_only(view):
    view.chip_inprivate.click()
    assert view.table.model().rowCount() > 0
    assert view.table.empty_state_text() == ""
    assert view._filter_desc_label.isVisible()
    assert view._filter_desc_label.text().startswith("filter: ")
    assert "match" not in view.count_label.text()


def test_recovery_count_line_is_plain_when_emptied(qtbot):
    from tests.test_recovery_view import _rows
    from webcache.views.recovery import RecoveryView
    v = RecoveryView()
    qtbot.addWidget(v)
    v.set_records(_rows(20))
    v.table.model().set_condition("Confidence", Condition("equals", "no-such"))
    assert v.table.model().rowCount() == 0
    assert v.count_label.text().startswith("0 of 20")
    assert "match" not in v.count_label.text()
