"""The "Origin" heading keeps its size through a theme switch: measured
natively, with the real font, in a subprocess (see the probe)."""
import os
import subprocess
import sys
from pathlib import Path

from tests._native_screen import skip_unless_measurable


def test_origin_is_the_same_size_at_launch_and_after_each_theme_switch():
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": "."}
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests._origin_heading_probe"],
        capture_output=True, text=True, timeout=300, cwd=root, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout.strip().splitlines()[-1]
    skip_unless_measurable(out)
    w0, h0, w1, h1, w2, h2 = (float(v) for v in out.split())
    assert w0 > 20 and h0 > 8, out
    for w, h in ((w1, h1), (w2, h2)):
        assert abs(w - w0) <= 1.0 and abs(h - h0) <= 1.0, out
