"""The application's drawn icon set: sidebar glyphs, the content-header
badge, button icons and the theme pill's mark.

Drawn with QPainter strokes into a QPixmap, as icon.py draws the window
icon: no SVG, no asset files and no QtSvg dependency. Each path is a
simplified drawing of the design's glyph that keeps what reads at 15-20px:
silhouette, stroke weight, and the theme colour that carries the meaning.
icon.py keeps its own API (SIZES, _paint_one, build_icon).

Every glyph is drawn at SCALE times its logical size with the matching
devicePixelRatio, so it stays sharp at 125%, 150% and 200% display
scaling.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap, QColor

#: Physical-to-logical ratio every glyph is rendered at. 4x covers 200%
#: Windows scaling with headroom; QPixmap.setDevicePixelRatio tells Qt to
#: treat the extra resolution as a high-DPI asset rather than a bigger icon.
#:
#: Public, because icon.mark_pixmap() renders the brand mark at the same
#: ratio, so it is as sharp as the nav glyphs beside it.
SCALE = 4

#: Names this module can draw. A tuple rather than the dispatch dict's
#: keys, so an unknown name fails with KeyError rather than returning a
#: blank pixmap.
NAMES = ("shield", "clock", "folder", "search", "chart", "database", "pin",
          "globe", "trash", "moon", "warning", "lock", "funnel", "download",
          "swap", "check", "chevron_down", "chevron_right", "chevron_left",
          "grid", "file", "dash", "calendar")


def _pen(color, width=1.8):
    p = QPen(QColor(color))
    p.setWidthF(width)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def _draw_shield(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(12, 2.6)
    path.lineTo(5, 5.6)
    path.lineTo(5, 11.4)
    path.quadTo(5, 16.6, 12, 19.6)
    path.quadTo(19, 16.6, 19, 11.4)
    path.lineTo(19, 5.6)
    path.closeSubpath()
    pt.drawPath(path)


def _draw_clock(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    # A circular-arrow ring, three-quarters round, with a small arrowhead:
    # "recent activity" rather than a clock face.
    rect = QRectF(3, 3, 18, 18)
    pt.drawArc(rect, 40 * 16, 265 * 16)
    pt.drawLine(QPointF(3.4, 4.6), QPointF(3, 9))
    pt.drawLine(QPointF(3, 9), QPointF(7.4, 8.6))
    # Clock hands from the centre.
    pt.drawLine(QPointF(12, 12), QPointF(12, 7.5))
    pt.drawLine(QPointF(12, 12), QPointF(15.2, 13.8))


def _draw_folder(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(3, 7.5)
    path.lineTo(3, 17.3)
    path.quadTo(3, 19, 4.7, 19)
    path.lineTo(17.5, 19)
    path.quadTo(19, 19, 19, 17.5)
    path.lineTo(19, 10)
    path.quadTo(19, 8.5, 17.5, 8.5)
    path.lineTo(10.5, 8.5)
    path.lineTo(8.5, 6)
    path.lineTo(4.5, 6)
    path.quadTo(3, 6, 3, 7.5)
    pt.drawPath(path)


def _draw_search(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    pt.drawEllipse(QPointF(11, 11), 6.4, 6.4)
    pt.drawLine(QPointF(15.6, 15.6), QPointF(20.5, 20.5))


def _draw_chart(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(3, 15)
    path.lineTo(7.5, 9.5)
    path.lineTo(11.5, 13)
    path.lineTo(15, 5.5)
    path.lineTo(21, 15.5)
    pt.drawPath(path)


def _draw_database(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    pt.drawRoundedRect(QRectF(3, 4, 18, 6), 1.5, 1.5)
    pt.drawRoundedRect(QRectF(3, 14, 18, 6), 1.5, 1.5)
    dot = _pen(pen.color(), pen.widthF() * 1.7)
    pt.setPen(dot)
    pt.drawPoint(QPointF(6.5, 7))
    pt.drawPoint(QPointF(6.5, 17))


def _draw_pin(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(12, 21)
    path.cubicTo(8.6, 17.6, 5, 13.3, 5, 9)
    path.arcTo(QRectF(5, 2, 14, 14), 180, 180)
    path.cubicTo(19, 13.3, 15.4, 17.6, 12, 21)
    path.closeSubpath()
    pt.drawPath(path)
    pt.drawEllipse(QPointF(12, 9.2), 2.4, 2.4)


def _draw_tag(pt, pen):
    """A luggage tag: a pentagon pointing up-left, with its eyelet."""
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(3.5, 3.5)
    path.lineTo(11.5, 3.5)
    path.lineTo(20.5, 12.5)
    path.lineTo(12.5, 20.5)
    path.lineTo(3.5, 11.5)
    path.closeSubpath()
    pt.drawPath(path)
    pt.drawEllipse(QPointF(8, 8), 1.6, 1.6)


def _draw_globe(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    pt.drawEllipse(QPointF(12, 12), 9, 9)
    pt.drawLine(QPointF(3.2, 12), QPointF(20.8, 12))
    pt.drawArc(QRectF(7.2, 3, 9.6, 18), 0, 360)
    pt.drawLine(QPointF(12, 3), QPointF(12, 21))


def _draw_trash(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    pt.drawLine(QPointF(4, 7), QPointF(20, 7))
    path = QPainterPath()
    path.moveTo(6.5, 7)
    path.lineTo(7.5, 19.5)
    path.lineTo(16.5, 19.5)
    path.lineTo(17.5, 7)
    pt.drawPath(path)
    pt.drawRoundedRect(QRectF(9.5, 4, 5, 3), 0.6, 0.6)


def _draw_moon(pt, pen, size):
    # Subtractive crescent: paint a filled disc in the mark colour, then
    # cut a smaller offset disc out of its alpha channel. This is the only
    # glyph that needs a fill (a stroked crescent outline is two joined
    # arcs Qt has no one-call primitive for) -- CompositionMode_Clear
    # erases pixels regardless of whatever sits underneath, so the result
    # is a real crescent silhouette rather than a colour-matched circle
    # that only looks right against one specific background.
    pt.setPen(Qt.NoPen)
    pt.setBrush(QColor(pen.color()))
    pt.drawEllipse(QPointF(size * 0.46, size * 0.5), size * 0.36, size * 0.36)
    pt.setCompositionMode(QPainter.CompositionMode_Clear)
    pt.setBrush(QColor(0, 0, 0, 255))
    pt.drawEllipse(QPointF(size * 0.60, size * 0.38), size * 0.30, size * 0.30)
    pt.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _draw_warning(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    pt.drawEllipse(QPointF(12, 12), 9, 9)
    pt.drawLine(QPointF(12, 7.5), QPointF(12, 13.2))
    dot = _pen(pen.color(), pen.widthF() * 1.7)
    pt.setPen(dot)
    pt.drawPoint(QPointF(12, 16.4))


def _draw_lock(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    pt.drawRoundedRect(QRectF(4.5, 10.5, 15, 9.5), 1.5, 1.5)
    pt.drawArc(QRectF(8, 3.5, 8, 8), 0, 180 * 16)


def _draw_funnel(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(4, 5)
    path.lineTo(20, 5)
    path.lineTo(13.5, 12.5)
    path.lineTo(13.5, 19)
    path.lineTo(10.5, 17)
    path.lineTo(10.5, 12.5)
    path.closeSubpath()
    pt.drawPath(path)


def _draw_download(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    pt.drawLine(QPointF(12, 3.5), QPointF(12, 13.5))
    path = QPainterPath()
    path.moveTo(8, 10)
    path.lineTo(12, 14)
    path.lineTo(16, 10)
    pt.drawPath(path)
    pt.drawLine(QPointF(4.5, 17.5), QPointF(4.5, 19.5))
    pt.drawLine(QPointF(4.5, 19.5), QPointF(19.5, 19.5))
    pt.drawLine(QPointF(19.5, 19.5), QPointF(19.5, 17.5))


def _draw_swap(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    pt.drawLine(QPointF(4, 8), QPointF(17, 8))
    pt.drawLine(QPointF(17, 8), QPointF(14, 5))
    pt.drawLine(QPointF(20, 16), QPointF(7, 16))
    pt.drawLine(QPointF(7, 16), QPointF(10, 19))


def _draw_check(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(4, 12.5)
    path.lineTo(9, 17.5)
    path.lineTo(20, 6.5)
    pt.drawPath(path)


def _draw_calendar(pt, pen):
    """A wall calendar: a page with a header band, two binding rings and
    a grid of days."""
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    pt.drawRoundedRect(QRectF(3.5, 5, 17, 15.5), 2.2, 2.2)
    pt.drawLine(QPointF(3.5, 9.5), QPointF(20.5, 9.5))
    pt.drawLine(QPointF(8, 3), QPointF(8, 7))
    pt.drawLine(QPointF(16, 3), QPointF(16, 7))
    for x in (7.5, 12, 16.5):
        for y in (13, 16.8):
            pt.drawPoint(QPointF(x, y))


def _draw_dash(pt, pen):
    """A partly-selected box's mark: state is never
    shown by colour alone."""
    pt.setPen(pen)
    pt.drawLine(QPointF(6, 12), QPointF(18, 12))


def _draw_chevron_down(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(6, 10)
    path.lineTo(12, 16)
    path.lineTo(18, 10)
    pt.drawPath(path)


def _draw_chevron_right(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(9, 6)
    path.lineTo(15, 12)
    path.lineTo(9, 18)
    pt.drawPath(path)


def _draw_chevron_left(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(15, 6)
    path.lineTo(9, 12)
    path.lineTo(15, 18)
    pt.drawPath(path)


def _draw_file(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(6, 3.5)
    path.lineTo(14, 3.5)
    path.lineTo(18, 7.5)
    path.lineTo(18, 20.5)
    path.lineTo(6, 20.5)
    path.closeSubpath()
    pt.drawPath(path)
    corner = QPainterPath()
    corner.moveTo(14, 3.5)
    corner.lineTo(14, 7.5)
    corner.lineTo(18, 7.5)
    pt.drawPath(corner)


def _draw_grid(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    for x, y in ((3, 3), (13.5, 3), (3, 13.5), (13.5, 13.5)):
        pt.drawRoundedRect(QRectF(x, y, 7.5, 7.5), 1, 1)


def _draw_copy(pt, pen):
    pt.setPen(pen)
    pt.setBrush(Qt.NoBrush)
    pt.drawRoundedRect(QRectF(8, 8, 12, 12), 2, 2)
    pt.drawRoundedRect(QRectF(4, 4, 12, 12), 2, 2)


_DRAWERS = {
    "shield": _draw_shield, "clock": _draw_clock, "folder": _draw_folder,
    "search": _draw_search, "chart": _draw_chart, "database": _draw_database,
    "pin": _draw_pin, "globe": _draw_globe, "trash": _draw_trash,
    "warning": _draw_warning, "lock": _draw_lock, "funnel": _draw_funnel,
    "download": _draw_download, "swap": _draw_swap, "check": _draw_check,
    "chevron_down": _draw_chevron_down, "chevron_right": _draw_chevron_right,
    "chevron_left": _draw_chevron_left, "grid": _draw_grid, "file": _draw_file,
    "copy": _draw_copy, "dash": _draw_dash, "calendar": _draw_calendar, "tag": _draw_tag,
}


#: (name, colour, size, stroke) -> QPixmap. The same glyph is painted at
#: the same colour and size many times (every unselected nav row, every
#: header badge), so each is painted once. QPixmap is implicitly shared,
#: so one instance can be handed to many callers, none of which modify
#: it. Unbounded: the set of names, colours and sizes in use is small and
#: fixed.
_pixmap_cache = {}


def pixmap(name, color, size=16, stroke=1.8):
    """One glyph, painted at `size` logical px in `color` (any QColor-
    acceptable value: a QColor, a "#RRGGBB" string, ...). Transparent
    background, so it composites onto whatever the caller already painted
    -- a sidebar row, a button, a status-bar label."""
    qcolor = QColor(color)
    key = (name, qcolor.name(QColor.HexArgb), size, stroke)
    cached = _pixmap_cache.get(key)
    if cached is not None:
        return cached
    physical = max(1, round(size * SCALE))
    px = QPixmap(physical, physical)
    px.fill(Qt.transparent)
    px.setDevicePixelRatio(SCALE)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(size / 24.0, size / 24.0)
    pen = _pen(qcolor, stroke)
    if name == "moon":
        _draw_moon(painter, pen, 24)
    else:
        drawer = _DRAWERS.get(name)
        if drawer is None:
            raise KeyError("no such glyph: %r (known: %s)"
                            % (name, ", ".join(NAMES)))
        drawer(painter, pen)
    painter.end()
    _pixmap_cache[key] = px
    return px


def icon(name, color, size=16, stroke=1.8):
    return QIcon(pixmap(name, color, size, stroke))
