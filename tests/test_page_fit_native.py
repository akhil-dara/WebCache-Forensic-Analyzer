"""The content column never scrolls, and a scroll
offset is never carried from one screen to the next.

A QStackedWidget's minimum height is the largest over every page it has
ever held, so once a tall view had been visited every later screen grew a
page scroll, and go_to() left the offset where the last screen put it:
titles and Back were cut at the top, the Table Browser pager sat below
the window, and the export bar was drawn above it.

Native subprocess with the real font: see _page_fit_probe.py."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests._native_screen import skip_unless_measurable


def test_every_screen_fits_after_timeline_a_hit_landing_and_an_export():
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": "."}
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests._page_fit_probe"],
        capture_output=True, text=True, timeout=300, cwd=root, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout.strip()
    skip_unless_measurable(out)
    first, *details = out.splitlines()
    values = dict(part.split("=") for part in first.split())
    assert int(values["SCREENS"]) >= 30, first
    assert int(values["BAD"]) == 0, "\n".join([first] + details[:40])
