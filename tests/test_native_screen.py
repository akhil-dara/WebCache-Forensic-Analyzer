"""The native probes' small-screen guard: a screen that cannot hold the
examiner's window says so instead of measuring a clamped one."""
import types

import pytest

from tests._native_screen import screen_too_small, skip_unless_measurable


def _app(width, height):
    area = types.SimpleNamespace(width=lambda: width, height=lambda: height)
    screen = types.SimpleNamespace(availableGeometry=lambda: area)
    return types.SimpleNamespace(primaryScreen=lambda: screen)


def test_a_screen_big_enough_is_measured():
    assert screen_too_small(_app(1536, 816), 1328, 816) == ""


@pytest.mark.parametrize("size", [(1024, 728), (1536, 700), (1200, 900)])
def test_a_screen_too_small_in_either_direction_is_reported(size):
    assert screen_too_small(_app(*size), 1328, 816) == (
        "SCREEN_TOO_SMALL %dx%d" % size)


def test_the_test_skips_with_the_screen_size_as_the_reason():
    with pytest.raises(pytest.skip.Exception, match="1024x728"):
        skip_unless_measurable("SCREEN_TOO_SMALL 1024x728")
    with pytest.raises(pytest.skip.Exception, match="Segoe UI"):
        skip_unless_measurable("FONT_MISSING")
    skip_unless_measurable("CHECKED=298 CLIPPED=0")      # measured: no skip
