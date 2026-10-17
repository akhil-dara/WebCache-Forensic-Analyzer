"""No column header's own label may be clipped by its basis badge.

RecordsTable._enforce_heading_floor is
the ONE shared floor every badge-bearing column, in every view, is sized
by. It added its safety slack (_LABEL_ESTIMATE_SLACK_PX) exactly once, but
the header CENTRES its label -- so only HALF of that slack ever lands on
the side that matters, where paintSection's own background-repaint erases
whatever spilled into the badge's reserved zone, with no ellipsis and no
warning, just missing glyphs. Recovery's "Carved from file" header
rendered as "Carved from fil" because of exactly this (see recovery.py's
own comment on the fix, and records_table.py's _enforce_heading_floor
docstring for the algebra).

The bug reduces to a font- and label-INDEPENDENT constant -- the margin
the old formula guaranteed is exactly _LABEL_ESTIMATE_SLACK_PX / 2 for any
label, any badge, once the section is sized at its own floor (the label
width and reserve terms cancel out of the algebra). That is exactly why
this reproduces identically under the offscreen Qt platform every test in
this suite runs under (a completely different, substitute font from the
real app's Segoe UI): the bug never depended on which font was measured,
only on the formula's own arithmetic.

This checks the invariant the floor exists to guarantee directly, against
the SAME building blocks _enforce_heading_floor itself reads
(painted_font(), badge_width(), BADGE_GAP_PX, RESERVED_RIGHT_PX) at each
column's REAL, already-fitted sectionSize -- not by re-deriving the floor
formula (that would just restate the implementation and could never catch
a regression in it), but by checking the GEOMETRIC fact that actually
matters: the centred label's own right edge must clear the badge's
reserved (erased) zone by a real margin, not a hairline one.

Covers every view this codebase declares with at least one basis-badge
column (grepped `field="` across webcache/views/) -- the cause is shared,
so every view is checked, not just Deleted Records.
"""
import pytest
from PySide6.QtGui import QFontMetricsF

from webcache.views.containers import ContainersView
from webcache.views.cookies import CookiesView
from webcache.views.domains import DomainsView
from webcache.views.file_access import FileAccessView
from webcache.views.headers import HeadersView
from webcache.views.history import HistoryView
from webcache.views.iocs import FindingsView
from webcache.views.location import LocationView
from webcache.views.recovery import RecoveryView
from webcache.views.search import SearchView
from webcache.views.timeline import TimelineView

#: Deliberately less than _LABEL_ESTIMATE_SLACK_PX (16, records_table.py)
#: but comfortably more than half of it (8) -- the OLD, buggy formula's
#: own guaranteed margin, exactly (see the module docstring's algebra).
#: A regression back to the halved margin fails this at 8 < 12; the fixed
#: formula's 16px margin clears it with room to spare.
_MIN_SAFE_MARGIN_PX = 12

#: Every view this codebase declares with at least one basis-badge
#: (`field=`) column. RecoveryView is a standalone RecordsTable owner;
#: every other entry is a segmented RecordsView subclass (see
#: _tables_and_columns below for how each shape is walked).
_VIEW_CLASSES = [
    RecoveryView, ContainersView, CookiesView, DomainsView, FileAccessView,
    HeadersView, HistoryView, FindingsView, LocationView, SearchView,
    TimelineView,
]


def _tables_and_columns(view):
    """Yields every (RecordsTable, Column list) `view` can ever show --
    every segment for a segmented RecordsView subclass, or the one table
    a standalone view like RecoveryView owns directly.

    A GENERATOR, not a list built up front: for a segmented view,
    switching segments reassigns the SAME shared `view.table`'s model in
    place (records_view.py's _switch_segment), so collecting
    `(view.table, columns)` pairs for every segment before checking any of
    them would leave every earlier pair holding the identical table
    object, by then re-rendered to the LAST segment switched to -- the
    columns would be one segment's, the table's actual geometry another's.
    Yielding immediately after each switch is what keeps a check reading
    the segment it thinks it is."""
    if hasattr(view, "_segments_by_key"):
        view.set_records([])
        for key, rs in view._segments_by_key.items():
            if key != view._active_key:
                view._switch_segment(key)
            yield view.table, list(rs.columns)
        return
    view.set_records([])
    yield view.table, list(view.COLUMNS)


@pytest.mark.parametrize("view_cls", _VIEW_CLASSES, ids=[c.__name__ for c in _VIEW_CLASSES])
def test_no_header_label_is_clipped_by_its_badge(qtbot, view_cls):
    view = view_cls()
    qtbot.addWidget(view)
    # Column objects are module-level and remember "hidden": showing an
    # optional column below must not leak into later tests.
    saved = [(c, c.hidden) for _t, cols in _tables_and_columns(view)
             for c in cols]
    try:
        _check_headers(view, view_cls)
    finally:
        for col, hidden in saved:
            col.hidden = hidden


def _check_headers(view, view_cls):
    for table, columns in _tables_and_columns(view):
        header = table.horizontalHeader()
        for i, col in enumerate(columns):
            if not (col.show_badge and col.badge):
                continue
            # An optional column starts hidden (section size 0); the fit
            # that matters is the one it has when the examiner shows it.
            if header.isSectionHidden(i):
                table.set_column_hidden(col.key, False)
            size = header.sectionSize(i)
            label_w = QFontMetricsF(header.painted_font()).horizontalAdvance(col.label)
            reserve = (header.badge_width(col.badge) + header.BADGE_GAP_PX
                       + header.RESERVED_RIGHT_PX)
            erase_left = size - reserve
            centered_right = (size + label_w) / 2.0
            margin = erase_left - centered_right
            assert margin >= _MIN_SAFE_MARGIN_PX, (
                "%s column %r label %r: only %.1fpx of clearance before "
                "its own badge's erase zone (section=%d, label_w=%.1f) -- "
                "the label will be clipped, exactly the way Recovery's "
                "'Carved from file' was" % (
                    view_cls.__name__, col.key, col.label, margin, size,
                    label_w))
