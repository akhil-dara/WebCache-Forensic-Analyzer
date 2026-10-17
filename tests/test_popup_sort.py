"""Excel's filter drop-down sorts as well as filters: Sort ascending and
Sort descending sit at the top of the popup, worded for the column's kind
(A to Z, smallest first, oldest first), and order the table on that column
exactly as a header click would."""
import pytest

from webcache.views.history import HistoryView
from webcache.widgets.record_filter import natural_key, sort_labels
from tests.fixtures import make_rows


@pytest.fixture
def view(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records(make_rows(300))
    v.resize(1500, 800)
    v.show()
    qtbot.waitExposed(v)
    return v


def _open_popup(view, key):
    section = [c.key for c in view.table.model().columns].index(key)
    view.table._open_filter_popup(section)
    return view.table._filter_popup


@pytest.mark.parametrize("kind, expected", [
    ("text", ("Sort A to Z", "Sort Z to A")),
    ("url", ("Sort A to Z", "Sort Z to A")),
    ("num", ("Sort smallest first", "Sort largest first")),
    ("size", ("Sort smallest first", "Sort largest first")),
    ("time", ("Sort oldest first", "Sort newest first")),
    ("time_local", ("Sort oldest first", "Sort newest first")),
])
def test_the_sort_buttons_are_worded_for_the_column_kind(kind, expected):
    assert sort_labels(type("C", (), {"kind": kind})()) == expected


@pytest.mark.parametrize("descending", [False, True])
def test_a_sort_button_orders_the_table_and_closes_the_popup(view, qtbot,
                                                             descending):
    popup = _open_popup(view, "Domain")
    button = popup.sort_desc_button if descending else popup.sort_asc_button
    assert button.text() == sort_labels(popup.column)[1 if descending else 0]
    button.click()
    assert view.table.sort_keys() == [("Domain", descending)]
    qtbot.waitUntil(lambda: not popup.isVisible())
    model = view.table.model()
    shown = [str(model.row_at(r).get("Domain") or "")
             for r in range(model.rowCount())]
    shown = [s for s in shown if s]
    assert len(set(shown)) > 1
    assert shown == sorted(shown, key=natural_key, reverse=descending)


def test_sorting_from_the_popup_keeps_the_filter_in_force(view):
    model = view.table.model()
    model.filter.set_values("IsInPrivate", {True})
    model.refresh()
    before = model.rowCount()
    popup = _open_popup(view, "Domain")
    popup.sort_asc_button.click()
    assert view.table.model().rowCount() == before
