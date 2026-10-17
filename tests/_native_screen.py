"""The native fit probes measure the examiner's own work area: a 1536 px
wide window, 793 px tall, in the real Segoe UI. A smaller screen cannot
hold that window -- Windows clamps it, and the probe would then measure a
different, narrower window and report its own clamping as a layout defect
(the release runner's 1024x768 display did exactly that). Such a machine
has nothing true to say about these layouts, so the probe says so and the
test skips with the reason, as it already does without the font."""
import pytest


def screen_too_small(app, width, height):
    """'' when this screen can hold a WIDTH x HEIGHT window, else the line
    the probe prints instead of measuring."""
    area = app.primaryScreen().availableGeometry()
    if area.width() < width or area.height() < height:
        return "SCREEN_TOO_SMALL %dx%d" % (area.width(), area.height())
    return ""


def skip_unless_measurable(out):
    """Skip, with the reason, when a probe could not measure."""
    if out == "FONT_MISSING":
        pytest.skip("the real Segoe UI font is not installed on this machine")
    if out.startswith("SCREEN_TOO_SMALL"):
        pytest.skip("this screen's work area (%s) cannot hold the examiner's "
                    "window these checks measure" % out.split()[1])
