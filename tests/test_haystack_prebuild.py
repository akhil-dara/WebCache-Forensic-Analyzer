"""The first keystroke must not pay for the whole haystack.

A lazy, display-text based search haystack moves its cost onto the FIRST
keystroke: 6.6 ms at 20k rows on the base, 132-179
ms after, inside the 150 ms stall window and un-debounced (20k is below
LIVE_FILTER_MAX_ROWS). The model now prebuilds it in idle chunks after
construction and after set_rows, and the grid's DisplayRole hands
display_text the real Column rather than allocating a stand-in per call.
"""
import time

from webcache.widgets import record_model
from webcache.widgets.column_spec import display_text
from webcache.widgets.record_model import RecordTableModel
from tests.fixtures import FIXTURE_COLUMNS, make_rows


def _wait_for_prebuild(qtbot, model, seconds=5.0):
    end = time.perf_counter() + seconds
    while model.filter._haystack is None and time.perf_counter() < end:
        qtbot.wait(20)


def test_the_haystack_is_prebuilt_while_idle(qtbot):
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(20_000))
    _wait_for_prebuild(qtbot, model)
    assert model.filter._haystack is not None, (
        "no idle prebuild ran: the first keystroke still builds the whole "
        "haystack synchronously")


def test_after_the_idle_prebuild_the_first_keystroke_is_cheap(qtbot):
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(20_000))
    _wait_for_prebuild(qtbot, model)
    t0 = time.perf_counter()
    model.set_text("m")
    took = (time.perf_counter() - t0) * 1000.0
    assert took < 50.0, "first keystroke after idle %.1f ms (budget 50)" % took


def test_set_rows_prebuilds_the_new_rows_too(qtbot):
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(2_000))
    _wait_for_prebuild(qtbot, model)
    model.set_rows(make_rows(5_000, seed=11))
    _wait_for_prebuild(qtbot, model)
    assert model.filter._haystack is not None
    assert len(model.filter._haystack) == 5_000


def test_every_cell_the_grid_shows_is_in_its_rows_haystack(qtbot):
    """The fast column-major build must match exactly what the grid paints."""
    rows = make_rows(3_000, seed=3)
    model = RecordTableModel(list(FIXTURE_COLUMNS), rows)
    hay = model.filter._ensure_haystack()
    for i, row in enumerate(model.filter.rows):
        for col in FIXTURE_COLUMNS:
            shown = display_text(row.get(col.key), col).lower()
            assert shown in hay[i], (i, col.key, shown)


def test_display_role_passes_the_real_column(qtbot, monkeypatch):
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(10))
    seen = []

    def spy(value, column):
        seen.append(column)
        return display_text(value, column)

    monkeypatch.setattr(record_model, "display_text", spy)
    col_index = 4
    model.data(model.index(0, col_index))
    assert seen and seen[-1] is model.columns[col_index], (
        "DisplayRole built a stand-in instead of passing the Column")
