"""A default sort must not be paid for again on every filter
change. Filtering a sorted list keeps it sorted, so the sort happens once,
when the rows or the sort key change."""
import time

import pytest

from webcache.widgets.record_model import RecordTableModel
from tests.fixtures import FIXTURE_COLUMNS, make_rows
from tests.test_perf import SIZES, _elapsed_ms, budget_ms


def _model(n=600, desc=True):
    m = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(n))
    m.sort_by("AccessedUtc", desc)
    return m


def _order(m):
    return [id(m.row_at(i)) for i in range(m.rowCount())]


def _spy(m):
    calls = []
    real = m.filter._apply_sort
    m.filter._apply_sort = lambda: (calls.append(1), real())[1]
    return calls


def test_a_filter_change_does_not_sort_again():
    m = _model()
    calls = _spy(m)
    m.set_text("nimbus")
    m.set_values("IsInPrivate", {True})
    m.clear_all()
    assert calls == []


@pytest.mark.parametrize("desc", [True, False])
def test_filtering_a_sorted_model_keeps_the_sorted_order(desc):
    m = _model(desc=desc)
    m.set_text("search")
    filtered = _order(m)
    fresh = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(600))
    fresh.set_text("search")
    fresh.sort_by("AccessedUtc", desc)
    assert [m.row_at(i)["CleanUrl"] for i in range(m.rowCount())] == \
        [fresh.row_at(i)["CleanUrl"] for i in range(fresh.rowCount())]
    m.clear_all()
    times = [m.row_at(i)["AccessedUtc"] for i in range(m.rowCount())]
    dated = [t for t in times if t is not None]
    assert dated == sorted(dated, reverse=desc)
    assert all(t is None for t in times[len(dated):])
    assert filtered


def test_a_new_sort_key_after_filtering_is_honoured():
    m = _model()
    m.set_text("search")
    m.sort_by("VisitCount", False)
    m.set_text("s")
    counts = [m.row_at(i)["VisitCount"] for i in range(m.rowCount())]
    assert counts == sorted(counts)


def test_replacing_the_rows_resorts_them():
    m = _model(200)
    m.set_rows(make_rows(300, seed=11))
    times = [m.row_at(i)["AccessedUtc"] for i in range(m.rowCount())]
    dated = [t for t in times if t is not None]
    assert dated == sorted(dated, reverse=True)


@pytest.fixture(params=SIZES, ids=["2k", "20k", "100k"])
def sorted_sized(request):
    n, slot = request.param
    return _model(n), slot


def test_sorted_filter_keystroke_within_the_existing_budget(sorted_sized):
    """test_perf builds an UNSORTED model; every shipped record view is
    sorted. Same budget, same needles, sorted model."""
    model, slot = sorted_sized
    model.filter._ensure_haystack()
    worst = 0.0
    for needle in ("n", "ni", "nim", "nimb", "nimbus"):
        c0 = time.thread_time()
        model.set_text(needle)
        worst = max(worst, (time.thread_time() - c0) * 1000.0)
    budget = budget_ms("filter_keystroke", slot)
    assert worst < budget, "worst keystroke %.1f ms (CPU) over %.1f" % (worst, budget)


def test_a_render_sorts_once(qtbot, monkeypatch):
    from webcache.views.history import HistoryView
    from webcache.widgets import record_filter
    calls = []
    real = record_filter.RecordFilter._apply_sort

    def spy(self):
        calls.append(1)
        return real(self)
    monkeypatch.setattr(record_filter.RecordFilter, "_apply_sort", spy)
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records(make_rows(300))
    assert len(calls) == 1


def test_ties_keep_the_order_on_screen_and_keep_it_across_a_filter_change():
    """A stable sort breaks ties by the order shown just before the click
    (the default sort, here) -- and a later filter change must not quietly
    swap them back to loader order: one view, one tie order."""
    m = _model()
    m.set_values("IsInPrivate", {False})
    shown = [m.row_at(i) for i in range(m.rowCount())]
    m.sort_by("Domain", False)
    expected = [r["CleanUrl"] for r in
                sorted(shown, key=lambda r: r["Domain"].lower())]
    assert [m.row_at(i)["CleanUrl"] for i in range(m.rowCount())] == expected
    m.set_text("a")
    m.set_text("")
    assert [m.row_at(i)["CleanUrl"] for i in range(m.rowCount())] == expected
