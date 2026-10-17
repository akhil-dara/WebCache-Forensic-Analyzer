"""No column of any table view is narrower than
its heading AS PAINTED -- at load, or after it is dragged as narrow as it
will go. The standing rule is that a column never goes below its heading.

Native subprocess, real font, ink measured in the pixels: see
_heading_fit_probe.py for why neither the offscreen harness nor the
table's own painted_font() can be the judge here."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests._native_screen import skip_unless_measurable


def test_no_heading_is_clipped_at_load_or_after_a_drag():
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": "."}
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests._heading_fit_probe"],
        capture_output=True, text=True, timeout=300, cwd=root, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout.strip()
    skip_unless_measurable(out)
    first, *details = out.splitlines()
    values = dict(part.split("=") for part in first.split())
    assert int(values["CHECKED"]) > 200, first
    assert int(values["CLIPPED"]) == 0, "\n".join([first] + details[:40])
    assert int(values["DRAG_SHORT"]) == 0, "\n".join([first] + details[:40])
    assert int(values.get("BADGE_CUT", "0")) == 0, "\n".join(
        [first] + details[:40])
