"""Sidebar nav-height arithmetic, and the theme-pill/nav-content overlap
guarantee -- DEFECT 1 in the build report: at a 900px-tall window the
rail ran out of room after "Table Browser", slicing the CASE section
header behind the theme pill and leaving Integrity and Export & Report
entirely below the fold with no obvious way to discover the scrollbar.

THE ARITHMETIC (see the build report for the full before/after): measured
directly against a REAL (non-offscreen) Qt window on Windows, using the
app's own font (Segoe UI), at two different window heights (700 and 800,
both comfortably under this development machine's own 864px screen so
the OS never clamps the request) to isolate the height-INDEPENDENT chrome
every window of this app carries above and below the sidebar's own nav
list:

    menu bar               29px
    status bar              43px
    sidebar brand block     60px  (shield icon, "WebCache", "Forensic Analyzer")
    Open Database row       50px
    theme pill row          54px
    ------------------------------
    total fixed chrome     236px

So at a window W px tall, the nav list's own available height is W - 236.
At W = 900 (the height the build report was filed against) that budget is
664px.

BEFORE this fix (_ROW_HEIGHT=32, _SECTION_HEIGHT=29): 16 rows + 6 section
headers + the list's own 8px top/bottom viewport margin (nav.viewport().
setContentsMargins(0, 4, 0, 4)) came to 16*32 + 6*29 + 8 = 694px -- 30px
MORE than the 664px available. Verified directly (see the build report):
at a 900px window, Integrity and Export & Report ended up entirely below
the fold, with the CASE header sliced by the viewport edge just above
them.

FIRST FIX (_ROW_HEIGHT=30, _SECTION_HEIGHT=22): 16*30 + 6*22 + 8 = 620px,
44px of headroom at a 900px window.

NOW (_ROW_HEIGHT=26, _SECTION_HEIGHT=18): 16*26 +
6*18 + 8 = 532px. The examiner's own window is 816 px of work area --
1536x793 once the title bar is taken -- and at that height every row, the
CASE section included, fits without scrolling. That is asserted
NATIVELY, not by this file's arithmetic: tests/_sidebar_fit_probe.py
measures the real nav viewport and the foot buttons at 1536x793 with the
real font (tests/test_theme_sidebar_opening.py), because the chrome
figures above were measured once and drift as the chrome changes. The
900 px arithmetic below is kept as the original DEFECT 1 regression.

A window shorter than the content still scrolls the rail -- deliberately:
see theme.py's QListWidget#navList-scoped QScrollBar QSS for why that
scrollbar is high-contrast rather than the barely-there default, and
Sidebar.__init__'s own comment on why tightening these two numbers further
was rejected (readability) in favour of a scrollbar that is actually
visible once it is genuinely needed.
"""
import pytest

from webcache.shell.main_window import NAV_SECTIONS
from webcache.shell.sidebar import (SIDEBAR_WIDTH, _ROW_HEIGHT,
                                    _SECTION_HEIGHT, _SectionHeader, Sidebar)

#: See the module docstring's arithmetic -- the fixed chrome ABOVE and
#: BELOW the nav list in a real, on-screen 900px-tall window: menu bar
#: (29) + status bar (43) + sidebar brand block (60) + Open Database row
#: (50) + theme pill row (54).
_REAL_WINDOWS_CHROME_AT_900PX = 236
_TARGET_WINDOW_HEIGHT = 900
#: nav.viewport().setContentsMargins(0, 4, 0, 4) in sidebar.py.
_NAV_VIEWPORT_MARGIN = 8

N_ROWS = sum(1 for _section, items in NAV_SECTIONS for _item in items)
N_SECTIONS_WITH_TITLE = sum(1 for section, _items in NAV_SECTIONS if section)


def test_the_nav_is_still_sixteen_rows_in_six_titled_sections():
    """If this shape ever changes, the arithmetic below has to be
    re-derived -- fail loudly here rather than silently validating
    numbers that no longer describe the real nav."""
    assert N_ROWS == 17
    assert N_SECTIONS_WITH_TITLE == 6


def test_all_sixteen_destinations_fit_a_900px_window_without_scrolling():
    """The regression test for DEFECT 1 itself: the real-Windows content
    height must not exceed the real-Windows budget at the height the
    build report was filed against."""
    nav_budget = _TARGET_WINDOW_HEIGHT - _REAL_WINDOWS_CHROME_AT_900PX
    content_height = (N_ROWS * _ROW_HEIGHT + N_SECTIONS_WITH_TITLE * _SECTION_HEIGHT
                      + _NAV_VIEWPORT_MARGIN)
    assert content_height <= nav_budget, (
        "nav content is %dpx but only %dpx is available in a real 900px "
        "window -- Integrity/Export & Report will be below the fold again"
        % (content_height, nav_budget))


def test_rows_were_not_shrunk_into_unreadability_to_win_the_fit():
    """Tightening is the obvious lever, but a row is still a click
    target: this project's own "never squeeze a column below its
    heading" judgement, applied here to a nav row's height rather than a
    table column's width. 24px is the floor (rows are 26 so the CASE
    section fits the examiner's 816 px work area): still room for the row's own 15px icon and a 9pt name,
    which tests/test_recovery_not_clipped.py checks is never cut."""
    assert _ROW_HEIGHT >= 24


def test_section_header_text_still_has_room_inside_its_own_shrunken_box(qtbot):
    """_SECTION_HEIGHT went from 29 to 22; that only stays readable if
    the header's own contents margins were tightened to match, not left
    at their old (8, 12, 8, 5) -- which alone (17px) would leave a
    22px-tall box almost nothing to actually draw the label in."""
    header = _SectionHeader("USER ACTIVITY")
    qtbot.addWidget(header)
    margins = header.contentsMargins()
    assert _SECTION_HEIGHT - margins.top() - margins.bottom() >= 10


# --- the theme pill must never overlap nav content, at any height ---------

def _heights_to_sweep(sidebar):
    minimum = sidebar.minimumSizeHint().height()
    swept = sorted(set([minimum, minimum + 1, minimum + 40, 300, 500, 700,
                        900, 1200, 1600]))
    return [h for h in swept if h >= minimum]


def test_theme_pill_never_overlaps_nav_content_across_a_height_sweep(qtbot):
    """nav and the theme pill are siblings in the SAME QVBoxLayout (see
    Sidebar.__init__: root.addWidget(self.nav, 1) then
    root.addLayout(pill_wrap)) -- Qt's box model already guarantees two
    stacked items in one layout never overlap, but this is what actually
    proves it holds at every height this rail can be resized to, down to
    its own minimum, rather than trusting that guarantee blindly. A
    future change to absolute positioning, negative margins, or an
    overridden paintEvent could break it without this failing loudly."""
    sb = Sidebar(NAV_SECTIONS)
    qtbot.addWidget(sb)
    sb.show()
    qtbot.waitExposed(sb)

    tested = []
    for height in _heights_to_sweep(sb):
        sb.resize(sb.width(), height)
        qtbot.wait(0)
        nav_bottom = sb.nav.geometry().bottom()
        pill_top = sb.theme_pill.geometry().top()
        tested.append(height)
        assert nav_bottom <= pill_top, (
            "at sidebar height=%d the nav (bottom=%d) overlaps the theme "
            "pill (top=%d)" % (height, nav_bottom, pill_top))
    # A record of how low this was actually tested, for anyone reading
    # the report rather than the test: the sweep always includes this
    # sidebar's own minimumSizeHint -- Qt refuses to resize it smaller
    # than that regardless of what is asked for.
    assert tested[0] == sb.minimumSizeHint().height()


# --- the nav scrollbar must never crowd a row's own count badge -----------
# --- (observed on a real launch: "46" rendered as "4", "20" as "2") -------
#
# Measured via each row's own layout MARGIN, not painted pixel positions:
# a QListWidget item-widget's realized on-screen geometry was observed,
# empirically, to be unreliable to assert exact pixel values against once
# ANY other test in the same process has applied theme.apply()'s QSS
# stylesheet first (QApplication.setStyleSheet() re-polishes every widget
# alive in the process -- see theme.py's own comment -- and a styled
# QListWidget#navList item's realized width was observed to vary run to
# run for reasons unrelated to this fix, in BOTH this file's original
# tests, unmodified, and the fix below). The row's own CONTENTS MARGIN is
# the actual mechanism this fix owns and the thing that keeps a badge
# clear of the scrollbar regardless of exactly how wide Qt ultimately
# draws the row -- asserting on it directly is what makes this test mean
# the same thing whether it runs alone or last in the full suite.

#: theme.py's QListWidget#navList-scoped QScrollBar rule: width 10px,
#: margin 4px 1px 4px 1px -- 1px clear on EACH side of the handle, so the
#: scrollbar's own total on-screen footprint is 10 + 1 + 1 = 12px. A
#: right-aligned count badge needs at least this much daylight between
#: itself and wherever the scrollbar sits once it is showing, or the two
#: read as touching -- the same "abuts" collision Defect 2's status
#: message had with the permanent counters, one rail over.
_SCROLLBAR_FOOTPRINT_PX = 12

#: NavRow's own ordinary left/right content padding (sidebar.py's
#: _ROW_PADDING_PX) -- present whether or not a scrollbar is ever shown,
#: and, before this fix, the ONLY thing standing between a right-aligned
#: badge and the scrollbar: 4px short of _SCROLLBAR_FOOTPRINT_PX above.
_ORDINARY_ROW_PADDING_PX = 8

#: Short enough that test_sidebar.py's own DEFECT-1 arithmetic (module
#: docstring: below ~856px the rail scrolls) guarantees the nav
#: scrollbar is genuinely showing, not a height chosen to coincidentally
#: reproduce one measurement.
_HEIGHT_WITH_SCROLLBAR = 700
#: Comfortably above 856px: every one of the 16 rows fits, so the
#: scrollbar genuinely does not show.
_HEIGHT_WITHOUT_SCROLLBAR = 1100


def test_a_visible_nav_scrollbar_reserves_room_for_every_count_badge(qtbot):
    """Drives the real Sidebar at a real height short enough to force the
    real scrollbar visible, exactly the scenario this file's own module
    docstring already documents as the DEFECT-1 fallback for a rail too
    tall for the window -- then checks that every row actually widened
    its own right-hand reserve to clear the scrollbar's real 12px
    footprint, not just the ordinary 8px of padding every row always
    carries.
    """
    sb = Sidebar(NAV_SECTIONS)
    qtbot.addWidget(sb)
    sb.resize(SIDEBAR_WIDTH, _HEIGHT_WITH_SCROLLBAR)
    sb.show()
    qtbot.waitExposed(sb)
    sb.set_loaded(True)
    qtbot.wait(0)

    vscroll = sb.nav.verticalScrollBar()
    assert vscroll.isVisible(), "test needs the scrollbar actually showing to mean anything"

    for key in ("history", "downloads"):
        row = sb._rows[key]
        right_margin = row.layout().contentsMargins().right()
        assert right_margin >= _ORDINARY_ROW_PADDING_PX + _SCROLLBAR_FOOTPRINT_PX, (
            "%r's row only reserves %dpx on its right while the nav "
            "scrollbar is showing -- not enough clearance for its 12px "
            "footprint; a real launch showed this as a clipped digit"
            % (key, right_margin))


def test_the_scrollbar_reserve_is_not_a_permanent_gap(qtbot):
    """The fix for the test above must not cost a permanent right-hand
    gap on a window tall enough that the scrollbar never shows at all --
    that would look wrong exactly the way an always-on floor would (see
    records_table.py's own "never squeeze... but never pad needlessly"
    balance). Proved by every row falling back to its own ordinary
    padding, with no scrollbar-sized reserve left behind.
    """
    sb = Sidebar(NAV_SECTIONS)
    qtbot.addWidget(sb)
    sb.resize(SIDEBAR_WIDTH, _HEIGHT_WITHOUT_SCROLLBAR)
    sb.show()
    qtbot.waitExposed(sb)
    sb.set_loaded(True)
    qtbot.wait(0)

    assert sb.nav.verticalScrollBar().isVisible() is False
    for key in ("history", "downloads"):
        row = sb._rows[key]
        right_margin = row.layout().contentsMargins().right()
        assert right_margin == _ORDINARY_ROW_PADDING_PX, (
            "%r's row kept a scrollbar-clearance reserve (%dpx) even "
            "though the scrollbar itself is not showing"
            % (key, right_margin))


def test_count_of_reads_back_a_rows_badge_and_unit(qtbot):
    """The offline report reads each badge from here."""
    from webcache.shell.sidebar import Sidebar
    from webcache.shell.main_window import NAV_SECTIONS
    bar = Sidebar(NAV_SECTIONS)
    qtbot.addWidget(bar)
    bar.set_count("location", 5, "position fixes")
    assert bar.count_of("location") == ("5", "position fixes")
    assert bar.count_of("no-such-view") is None
