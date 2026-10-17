"""A filter with no values selected says so."""
import pytest

from webcache.views.history import HistoryView
from tests.fixtures import make_rows

NONE_SELECTED = "Domain: no values selected (matches nothing)"


@pytest.fixture
def view(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records(make_rows(120))
    v.resize(1500, 800)
    v.show()
    qtbot.waitExposed(v)
    return v


def test_chip_text_says_no_values_selected(view):
    view.table.model().set_values("Domain", set())
    text = view.table.model().chip_text()
    assert text == NONE_SELECTED
    assert "Is ." not in text and "Is " != text[-3:]


def test_the_grid_body_says_no_values_selected(view):
    view.table.model().set_values("Domain", set())
    assert NONE_SELECTED in view.table.empty_state_text()


def test_the_empty_message_says_it_and_a_real_set_still_reads_normally(view):
    """An empty set names itself; a real set is worded as before."""
    model = view.table.model()
    model.set_values("Domain", set())
    assert NONE_SELECTED in view.table.empty_message()
    model.clear_all()
    model.set_values("Domain", {"bing.com"})
    assert "no values selected" not in model.chip_text()
