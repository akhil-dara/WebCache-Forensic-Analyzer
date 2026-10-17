"""No word-wrapped label on the first screen or the
drop overlay paints more lines than its layout reserved.

The first-run paragraph is fixed at 430 px, but its parent layouts asked
its height at the column's 480 px: two lines reserved, three painted, and
"... and the exhibit is never" was the last thing on screen. Native
subprocess, real font: see _label_fit_probe.py."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests._native_screen import skip_unless_measurable


def test_no_wrapped_label_on_the_first_screen_or_the_overlay_is_clipped():
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": "."}
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests._label_fit_probe"],
        capture_output=True, text=True, timeout=300, cwd=root, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout.strip()
    skip_unless_measurable(out)
    first, *details = out.splitlines()
    values = dict(part.split("=") for part in first.split())
    assert int(values["CHECKED"]) >= 12, first
    assert int(values["CLIPPED"]) == 0, "\n".join([first] + details)
