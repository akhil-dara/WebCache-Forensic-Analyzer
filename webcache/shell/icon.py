"""The application's icon, drawn with Qt rather than shipped as a file.

The mark is a globe cut into cache-record layers, one shifted out of line
in teal: a record recovered. Its geometry lives in mark.py, shared with the
build-time renderer (packaging/build_icon.py).

Each size in SIZES is painted at its own resolution rather than scaled
from one bitmap, so the 16 px taskbar icon stays sharp; Qt picks the
closest size.
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from . import glyphs, mark, theme

#: From 16 px (taskbar, Alt+Tab) to 256 px (Explorer's largest view).
SIZES = (16, 24, 32, 48, 64, 128, 256)


def paint_mark(painter, size, mark_colour, hole_colour):
    """The mark itself, on a `painter` the caller has set up.

    Shared by the taskbar icon and the sidebar. Each layer is the globe
    clipped to that layer's band (the recovered one shifted and teal); the
    meridian is drawn in `hole_colour`, the colour behind the mark.
    """
    painter.setPen(Qt.NoPen)
    recovered = QColor(*mark.RECOVERED)
    for top, bottom, shift, is_recovered in mark.bands(size):
        painter.save()
        painter.setClipRect(QRectF(0, top, size, bottom - top))
        painter.setBrush(recovered if is_recovered else mark_colour)
        x0, y0, x1, y1 = mark.disc_bbox(size, shift)
        painter.drawEllipse(QRectF(x0, y0, x1 - x0, y1 - y0))
        painter.restore()
    meridian = mark.meridian(size)
    if meridian is not None:
        (x0, y0, x1, y1), stroke = meridian
        pen = QPen(hole_colour)
        pen.setWidthF(stroke)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(x0, y0, x1 - x0, y1 - y0))
        painter.setPen(Qt.NoPen)


def mark_pixmap(size, mark_colour, hole_colour):
    """The mark alone, on transparency, for the sidebar, which already
    provides the background the taskbar icon's backing square supplies.
    """
    # Drawn at glyphs.SCALE physical pixels with the matching device-pixel
    # ratio, as the nav glyphs are, so it is sharp under display scaling.
    scale = glyphs.SCALE
    physical = max(1, round(size * scale))
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(scale)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    # Painted in logical units (`size`); the device-pixel ratio supplies
    # the extra resolution.
    paint_mark(painter, size, mark_colour, hole_colour)
    painter.end()
    return pixmap


def _paint_one(size):
    """One size, painted at that resolution.

    Always in the dark palette's colours: the icon is the tool's fixed
    identity, whichever theme is chosen. Shapes come from mark.py.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    bg = theme.color("window", "dark")     # near-black #0D1117
    emerald = theme.color("primary", "dark")

    # A near-black rounded square, so the mark reads on a light or dark
    # taskbar; the mark's gaps are painted in the same colour.
    radius = mark.backing_radius(size)
    painter.setPen(Qt.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    paint_mark(painter, size, emerald, bg)

    painter.end()
    return pixmap


def build_icon():
    """A QIcon carrying every size in SIZES, set once on the
    QApplication by webcache.__main__."""
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(_paint_one(size))
    return icon
