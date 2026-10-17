"""The sidebar collapses to an icon strip and remembers it."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication

from webcache.shell import settings
from webcache.shell.main_window import NAV_SECTIONS, MainWindow
from webcache.shell.sidebar import (SIDEBAR_COLLAPSED_WIDTH, SIDEBAR_WIDTH,
                                    Sidebar)
from tests.test_literal_tooltips import shown
from tests._native_screen import skip_unless_measurable


def _sidebar(qtbot):
    s = Sidebar(NAV_SECTIONS)
    qtbot.addWidget(s)
    s.resize(SIDEBAR_WIDTH, 900)
    s.show()
    qtbot.waitExposed(s)
    return s


def test_the_toggle_collapses_the_sidebar_to_an_icon_strip(qtbot):
    s = _sidebar(qtbot)
    s.collapse_button.click()
    assert s.is_collapsed()
    assert s.width() == SIDEBAR_COLLAPSED_WIDTH
    qtbot.wait(20)
    for key, row in s._rows.items():
        # Geometry, not isVisible(): every icon sat at x = 87 of this 52 px
        # strip, off-screen, while isVisible() was True.
        left = row._icon_label.mapTo(s, QPoint(0, 0)).x()
        right = left + row._icon_label.width()
        assert 0 <= left and right <= SIDEBAR_COLLAPSED_WIDTH, (key, left, right)
        assert not row.text_label.isVisible()
        assert not row.count_label.isVisible()


def test_clicking_it_again_expands_it(qtbot):
    s = _sidebar(qtbot)
    s.collapse_button.click()
    s.collapse_button.click()
    assert not s.is_collapsed()
    assert s.width() == SIDEBAR_WIDTH
    assert all(r.text_label.isVisible() for r in s._rows.values())


def test_each_icon_names_its_view_and_count_in_a_tooltip(qtbot):
    s = _sidebar(qtbot)
    s.set_loaded(True)
    s.set_count("history", 1234)
    s.set_collapsed(True)
    assert shown(s._rows["history"].toolTip()) == "History — 1,234"


def test_an_expanded_row_also_carries_its_full_name(qtbot):
    """Nav names are the one place elision survives -- so the full
    name is always in the tooltip."""
    s = _sidebar(qtbot)
    assert shown(s._rows["recovery"].toolTip()).startswith(
        s._rows["recovery"]._full_label)


def test_right_click_copy_still_works_in_the_strip(qtbot):
    s = _sidebar(qtbot)
    s.set_loaded(True)
    s.set_count("history", 1234)
    s.set_collapsed(True)
    menu = s._rows["history"].build_context_menu()
    menu.actions()[0].trigger()
    assert QGuiApplication.clipboard().text() == "1,234"


def test_the_state_persists_across_launches(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.sidebar.collapse_button.click()
    assert settings.get("sidebar_collapsed") is True
    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.sidebar.is_collapsed()


def test_every_icon_and_every_foot_button_glyph_is_on_the_strip_natively():
    """With the real style and font: every nav icon's
    ink lies inside the collapsed strip, and the expand, Open and theme
    buttons each leave their glyph at least its own width once the QSS
    padding is taken (it left the expand glyph -6 px). Native subprocess:
    see _sidebar_collapse_probe.py."""
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": "."}
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests._sidebar_collapse_probe"],
        capture_output=True, text=True, timeout=300, cwd=root, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout.strip()
    skip_unless_measurable(out)
    lines = out.splitlines()
    strip = int(lines[0].split("=")[1])
    assert strip == SIDEBAR_COLLAPSED_WIDTH, lines[0]
    icons = [l.split() for l in lines if l.startswith("ICON ")]
    assert len(icons) == 17, out
    for _tag, key, left, right, width, visible in icons:
        assert visible == "1" and int(width) > 0, (key, "no icon painted")
        assert 0 <= int(left) and int(right) <= strip, (key, left, right)
    buttons = [l.split() for l in lines if l.startswith("BUTTON ")]
    assert len(buttons) == 3, out
    for _tag, name, room, need in buttons:
        assert int(room) >= int(need), (name, "room", room, "needs", need)
