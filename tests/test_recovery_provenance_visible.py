"""Where a carved record came from must be visible without scrolling."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from webcache.views.recovery import RecoveryView
from webcache.widgets import record_model
from tests.test_recovery_view import _rows
from tests._native_screen import skip_unless_measurable


@pytest.fixture
def view(qtbot):
    v = RecoveryView()
    # set_records([]) gives the table a real model with every declared
    # column's own width, exactly as MainWindow does right after the
    # first evidence load -- RecoveryView.__init__ deliberately builds no
    # model on its own (see its own comment on why), so a bare
    # RecoveryView() has no table.model() at all to read columns from.
    # Fine for the two ORDER-only checks below, which never measure a
    # pixel; the real column-fit check does not use this fixture at all
    # -- see test_every_provenance_column_is_visible_without_scrolling
    # and its own reasons why (this exact window size, +100 widened for
    # no reason tied to the real screen, is what hid a real regression
    # once already).
    v.set_records([])
    qtbot.addWidget(v)
    v.resize(1237 + 260, 800)
    v.show()
    qtbot.waitExposed(v)
    return v


def _order(view):
    return [c.key for c in view.table.model().columns]


def test_provenance_columns_come_straight_after_the_url(view):
    order = _order(view)
    # the default sort column, Timestamp (UTC), before
    # Offset; Page moved right of Confidence to make room at 1536 px.
    assert order[:7] == ["CleanUrl", "Source", "Timestamp", "Offset",
                         "Method", "Confidence", "Page"]


def test_the_constant_origin_column_is_last(view):
    assert _order(view)[-1] == "Origin"


def test_every_provenance_column_is_visible_without_scrolling():
    """File, Timestamp (UTC), Offset, Method and Confidence must all end
    inside the
    viewport, at the examiner's real screen size, filled with realistic
    carved rows -- not just Confidence: a column further right could
    overflow too, and nothing would catch it. Not the empty table an
    earlier version of this test used either: an empty table sizes every
    column to its bare header label, narrower than any of these columns
    ever render at with real content.

    Run via _recovery_fit_probe.py in a FRESH subprocess, not this
    process's own (conftest-forced offscreen) QApplication: see that
    module's own docstring for why a real font is required here and why
    a subprocess is the only way to get one inside this suite. A widened
    window and an empty table both independently hid a real regression
    here once already -- this checks the
    real requirement instead, at the real production size:
    1536px (the examiner's own maximised screen, logical px) minus
    sidebar.SIDEBAR_WIDTH (the EXPANDED sidebar's real width), not a
    number tuned to make the assertion pass.
    """
    webcache_qt_dir = Path(__file__).resolve().parent.parent
    # This process's own QT_QPA_PLATFORM is "offscreen" -- conftest.py sets
    # it as a real environment variable, not just an in-process default, so
    # a plain env=os.environ subprocess would inherit it and get the same
    # zero-font substitute this test exists to get AWAY from. Popped, not
    # overridden to a specific platform name: the subprocess's own default
    # (this machine's real "windows" plugin) is what has real fonts.
    env = {**os.environ, "PYTHONPATH": "."}
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests._recovery_fit_probe"],
        capture_output=True, text=True, timeout=60,
        cwd=webcache_qt_dir, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout.strip()
    skip_unless_measurable(out)
    values = dict(part.split("=") for part in out.split())
    viewport = int(values.pop("viewport"))
    # Every recovery method fits its column on one line: a wrapped Method
    # made every row two lines tall and halved the rows on screen.
    assert int(values.pop("MethodRoom")) >= 0, out
    for name, right in values.items():
        right = int(right)
        assert right <= viewport, "%s ends at %d, past the %dpx viewport" % (
            name, right, viewport)


def test_an_offset_reads_the_same_as_in_the_record_dialog():
    assert record_model._format(0x3B0523, False, kind="offset") == "0x003B0523"
