"""The grid path repeated avoidable work, and the timing
tests measured the machine as much as the app.

A paint asked the model for 7.5 roles per cell, BackgroundRole twice, and
did the row lookup for Font, Decoration and CheckState, which are always
None. And every sort, cleared filter or scroll back re-measured rows the
fit had already measured at the same column widths.
"""
import pytest
from PySide6.QtCore import Qt

from webcache.widgets.records_table import RecordsTable
from tests.fixtures import FIXTURE_COLUMNS, make_rows

LONG = "word " * 80


@pytest.fixture(autouse=True)
def _scratch_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")


def _table(qtbot, rows):
    t = RecordsTable()
    t.set_records(list(FIXTURE_COLUMNS), rows)
    qtbot.addWidget(t)
    t.resize(1600, 700)
    t.show()
    qtbot.waitExposed(t)
    qtbot.wait(80)
    return t


def test_a_paint_looks_up_the_row_only_for_roles_that_answer(qtbot):
    t = _table(qtbot, make_rows(2_000))
    model = t.model()
    calls = {"lookups": 0, "background": 0, "cells": set()}
    visible = model.filter.visible
    data = model.data

    def counting_visible():
        calls["lookups"] += 1
        return visible()

    def counting_data(index, role=Qt.DisplayRole):
        calls["cells"].add((index.row(), index.column()))
        if role == Qt.BackgroundRole:
            calls["background"] += 1
        return data(index, role)

    model.filter.visible = counting_visible
    model.data = counting_data
    try:
        t.viewport().repaint()
    finally:
        model.filter.visible = visible
        model.data = data
    cells = len(calls["cells"])
    assert cells > 50
    assert calls["background"] <= cells, (
        "BackgroundRole asked %d times for %d cells" % (calls["background"], cells))
    assert calls["lookups"] <= 4 * cells, (
        "%d row lookups for %d cells" % (calls["lookups"], cells))


def test_a_refit_after_a_filter_is_cleared_does_not_remeasure_rows(qtbot):
    rows = make_rows(300)
    for i in range(0, 30, 3):
        rows[i]["Title"] = LONG
    t = _table(qtbot, rows)
    t.fit_visible_rows()                          # warm: whatever is in view
    t.model().set_text("word")
    t.model().clear_all()
    t._reset_row_heights()
    first = t.fit_visible_rows()
    t._reset_row_heights()
    again = t.fit_visible_rows()
    assert again == 0, (
        "the same rows at the same widths were measured again (%d, then %d)"
        % (first, again))
    grown = [r for r in range(t.rowAt(0), t.rowAt(t.viewport().height() - 1))
             if t.model().row_at(r).get("Title") == LONG]
    assert grown, "no long row in view: the check below would be vacuous"
    default = t.verticalHeader().defaultSectionSize()
    assert all(t.rowHeight(r) > default for r in grown), (
        "a remembered height must still be applied")


def test_a_width_change_forgets_the_remembered_heights(qtbot):
    rows = make_rows(300)
    rows[0]["Title"] = LONG
    t = _table(qtbot, rows)
    t.fit_visible_rows()
    title = [c.key for c in FIXTURE_COLUMNS].index("Title")
    t.horizontalHeader().resizeSection(title, 1400)
    t._row_fit_timer.stop()
    assert t.fit_visible_rows() > 0, "a column resize must re-measure"


def test_the_stall_detector_can_tell_the_apps_own_work_from_waiting(qtbot):
    """cpu=True: a GUI thread that SLEEPS (the machine busy elsewhere, as
    far as this process can tell) shows a long wall gap and almost no busy
    time; one that COMPUTES shows both."""
    import time
    from webcache.widgets.stall_detector import StallDetector
    with StallDetector(threshold_ms=150, cpu=True) as det:
        qtbot.wait(40)
        time.sleep(0.3)
        qtbot.wait(40)
    assert det.worst_gap_ms > 250
    assert det.worst_busy_gap_ms < 150 and not det.busy_stalls
    with StallDetector(threshold_ms=150, cpu=True) as det:
        qtbot.wait(40)
        end = time.perf_counter() + 0.3
        while time.perf_counter() < end:
            pass
        qtbot.wait(40)
    assert det.worst_busy_gap_ms > 200 and det.busy_stalls
