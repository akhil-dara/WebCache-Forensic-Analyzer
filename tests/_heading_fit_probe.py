"""Standalone probe for test_heading_fit_native.py: does any column of any
table view sit narrower than its heading AS PAINTED -- at load, or after
an examiner drags it as narrow as it will go?

Run as a SUBPROCESS with the interpreter's own platform, for the reason
_recovery_fit_probe.py gives: the suite's offscreen platform registers no
fonts, so every width measured there is a substitute font's.

THE TRUTH IS INK, NOT A FONT. The previous guard measured the heading
with RecordsTable's own painted_font() -- the very function that was
wrong (it measured a 9 pt label while the style painted 12 pt), so it
could never fail on that defect. This probe asks no font anything: it
widens each section, grabs the header, and measures the label's painted
pixels. Whatever font the style really uses, that is what is measured.

Prints "FONT_MISSING", or "CHECKED=<n> CLIPPED=<n> DRAG_SHORT=<n> BADGE_CUT=<n>"
followed by one line per offending section.
"""
import math
import sys

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QFont, QFontInfo, QImage
from PySide6.QtWidgets import QApplication

#: How wide a section is made for its label to be measured: far wider
#: than any heading, so the label is never clipped while it is measured.
MEASURE_W = 900


def _ink_span(img, bg, top, bottom, left, right):
    """(first, last) pixel column in img[top:bottom, left:right] whose colour
    differs from `bg` by more than 120 (summed over R, G, B), or None.
    Plain Python over the raw bytes: numpy is not a dependency of this
    project, and the release runner does not have it."""
    data = bytes(img.constBits())
    stride = img.bytesPerLine()
    r0, g0, b0 = bg.red(), bg.green(), bg.blue()
    first = last = None
    for y in range(top, bottom):
        row = y * stride
        for x in range(left, right):
            i = row + 4 * x                    # Format_RGB32: B, G, R, X
            if (abs(data[i + 2] - r0) + abs(data[i + 1] - g0)
                    + abs(data[i] - b0)) > 120:
                if first is None or x < first:
                    first = x
                if last is None or x > last:
                    last = x
    return None if first is None else (first, last)


def _ink(app, theme, header, index, reserve_right):
    """The painted label's width in logical px, found in the pixels."""
    old = header.sectionSize(index)
    old_offset = header.offset()
    header.resizeSection(index, MEASURE_W)
    # Bring the section to the left edge: a grab only sees what is inside
    # the header widget, and a far-right column is scrolled out of it.
    # By POSITION, not setOffsetToSectionPosition: that one takes a
    # visual index that skips hidden sections, so with an optional column
    # hidden (Search's whole values) it scrolled to a different section.
    header.setOffset(header.sectionPosition(index))
    app.processEvents()
    x = header.sectionViewportPosition(index)
    pix = header.grab(QRect(x, 0, MEASURE_W, header.height()))
    header.resizeSection(index, old)
    header.setOffset(old_offset)
    app.processEvents()
    if pix.isNull() or pix.width() < MEASURE_W:
        raise RuntimeError("section %d could not be grabbed whole" % index)
    dpr = pix.devicePixelRatio()
    img = pix.toImage().convertToFormat(QImage.Format_RGB32)
    w, h = img.width(), img.height()
    bg = theme.color("alt_base")
    # Leave out the section's borders (top/bottom rows, the right edge)
    # and, on the right, whatever the header reserves for a badge or a
    # future affordance -- the label is centred, far from both.
    pad = int(math.ceil(3 * dpr))
    right = w - int(math.ceil((reserve_right + 2) * dpr))
    span = _ink_span(img, bg, pad, h - pad, pad, right)
    if span is None:
        return 0.0
    return (span[1] - span[0] + 1) / dpr


def _ink_of(pix, bg):
    """Width in logical px of whatever differs from `bg` in `pix`."""
    dpr = pix.devicePixelRatio()
    img = pix.toImage().convertToFormat(QImage.Format_RGB32)
    w, h = img.width(), img.height()
    pad = int(math.ceil(3 * dpr))
    # The carved edge sits at the left of a row label; skip it too.
    left = int(math.ceil(8 * dpr))
    span = _ink_span(img, bg, pad, h - pad, left, w - pad)
    if span is None:
        return 0.0
    return (span[1] - span[0] + 1) / dpr


def _origin_column(app, theme, table, pad_x):
    """The origin column: its corner heading and its row labels, measured
    in the pixels with the column made far wider, against its real width.
    Returns (width, need)."""
    vheader = table.verticalHeader()
    width = vheader.width()
    vheader.setFixedWidth(400)
    table.updateGeometries()        # the corner button follows the header
    app.processEvents()
    if table.corner_button.width() < 400:
        raise RuntimeError("corner button did not widen with the header")
    bg = theme.color("alt_base")
    inks = [_ink_of(table.corner_button.grab(), bg)]
    for row in range(min(2, table.model().rowCount())):
        inks.append(_ink_of(vheader.grab(QRect(
            0, vheader.sectionViewportPosition(row), 400,
            vheader.sectionSize(row))), bg))
    vheader.setFixedWidth(width)
    table.updateGeometries()
    app.processEvents()
    return width, math.ceil(max(inks) + 2 * pad_x + 1)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))          # exactly as __main__.py does
    if not QFontInfo(app.font()).exactMatch():
        print("FONT_MISSING")
        return
    from tests._native_screen import screen_too_small
    small = screen_too_small(app, 1536 - 208, 816)
    if small:
        print(small)
        return
    from webcache.shell import sidebar, theme
    theme.apply(app, "dark")
    from webcache.widgets.records_table import (
        RecordsTable, SECTION_QSS_PAD_X, _ProvenanceHeaderView)
    from webcache.views.containers import ContainersView
    from webcache.views.cookies import CookiesView
    from webcache.views.domains import DomainsView
    from webcache.views.file_access import FileAccessView
    from webcache.views.headers import HeadersView
    from webcache.views.history import HistoryView
    from webcache.views.indicators import IndicatorsView
    from webcache.views.iocs import FindingsView
    from webcache.views.location import LocationView
    from webcache.views.recovery import RecoveryView
    from webcache.views.search import SearchView
    from webcache.views.timeline import TimelineView
    views = [ContainersView, CookiesView, DomainsView, FileAccessView,
             HeadersView, HistoryView, IndicatorsView, FindingsView,
             LocationView, RecoveryView, SearchView, TimelineView]

    def rows_for(columns, n=5):
        return [{c.key: (i if c.kind == "num" else "x%d" % i)
                 for c in columns} for i in range(n)]

    checked, clipped, drag_short, badge_cut, lines = 0, 0, 0, 0, []
    for cls in views:
        view = cls()
        # The pane beside the grid leaves the header narrower than the
        # MEASURE_W strip each label is grabbed in; a column's floor does
        # not depend on it, so it is closed while the ink is measured.
        if getattr(view, "set_details_visible", None):
            view.set_details_visible(False)
        view.resize(1536 - sidebar.SIDEBAR_WIDTH, 816)
        keys = list(getattr(view, "_segments_by_key", {}) or [None])
        for key in keys:
            if key is None:
                view.set_records(rows_for(view.COLUMNS))
            else:
                view.set_records_for(
                    key, rows_for(view._segments_by_key[key].columns))
        view.show()
        app.processEvents()
        for key in keys:
            if key is not None and key != view._active_key:
                view._switch_segment(key)
                app.processEvents()
            for table in view.findChildren(RecordsTable):
                if not table.isVisible() or table.model() is None:
                    continue
                # the probe measures the LABEL's ink; the sort arrow
                # lives in the padding the floor already reserves.
                table.horizontalHeader().paint_sort_arrow = False
                if getattr(table, "corner_button", None) is not None:
                    checked += 1
                    width, need = _origin_column(app, theme, table,
                                                 SECTION_QSS_PAD_X)
                    if width < need:
                        clipped += 1
                        lines.append("CLIP %s/%s origin column width=%d "
                                     "need=%d" % (cls.__name__, key, width,
                                                  need))
                header = table.horizontalHeader()
                for i, col in enumerate(table.model().columns):
                    if header.isSectionHidden(i):
                        continue
                    checked += 1
                    reserve = 0
                    badge = (col.show_badge and col.badge
                             and isinstance(header, _ProvenanceHeaderView))
                    if isinstance(header, _ProvenanceHeaderView):
                        reserve = header.RESERVED_RIGHT_PX
                        if badge:
                            reserve += (header.badge_width(col.badge)
                                        + header.BADGE_GAP_PX)
                    ink = _ink(app, theme, header, i, reserve)
                    # A centred label clear of a right-hand reserve needs
                    # that reserve mirrored on the left too.
                    need = math.ceil(max(ink + 2 * SECTION_QSS_PAD_X + 1,
                                         ink + 2 * reserve if badge else 0))
                    size = header.sectionSize(i)
                    header.resizeSection(i, 1)
                    app.processEvents()
                    dragged = header.sectionSize(i)
                    header.resizeSection(i, size)
                    app.processEvents()
                    if badge:
                        # a chip drawn at the viewport's right edge is
                        # whole or absent, at every scroll position.
                        edge = header.viewport().rect().right()
                        bar = table.horizontalScrollBar()
                        for pos in (bar.minimum(), bar.maximum()):
                            bar.setValue(pos)
                            app.processEvents()
                            section = QRectF(
                                header.sectionViewportPosition(i), 0,
                                header.sectionSize(i), header.height())
                            chip = header._chip_rect(
                                section, col.badge, visible_right=edge,
                                label=col.label)
                            if chip is not None and (chip.right() > edge
                                                     or chip.left() < 0):
                                badge_cut += 1
                                lines.append("CUT %s/%s %r at scroll %d"
                                             % (cls.__name__, key,
                                                col.label, pos))
                        bar.setValue(bar.minimum())
                    if size < need:
                        clipped += 1
                        lines.append("CLIP %s/%s %r size=%d need=%d"
                                     % (cls.__name__, key, col.label, size,
                                        need))
                    if dragged < need:
                        drag_short += 1
                        lines.append("DRAG %s/%s %r dragged=%d need=%d"
                                     % (cls.__name__, key, col.label,
                                        dragged, need))
        view.close()
        view.deleteLater()
        app.processEvents()
    print("CHECKED=%d CLIPPED=%d DRAG_SHORT=%d BADGE_CUT=%d"
          % (checked, clipped, drag_short, badge_cut))
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
