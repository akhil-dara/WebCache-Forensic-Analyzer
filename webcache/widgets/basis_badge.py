"""The OBS / DER / INF / CARV chip, painted the same way everywhere.

Used by column headings and by the record dialog's field rows; the sizes
are defined once here so the two surfaces cannot drift. Engine-free, like
every widget: the caller decides what the letters say.
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPen
from PySide6.QtWidgets import QStyledItemDelegate

from ..shell import theme

#: The chip's own internal left/right text padding.
BADGE_PAD_PX = 5
BADGE_HEIGHT_PX = 16
#: Gap between the end of the label's reserved area and the chip.
BADGE_GAP_PX = 5

#: How much smaller than its host font the chip's text is, relative to
#: the host font so Qt's DPI scaling applies.
BADGE_FONT_DELTA_PT = 2.5
#: The smallest point size the chip's text may have.
BADGE_FONT_MIN_PT = 6.5


def badge_font(base_font):
    """A bold, slightly smaller copy of `base_font`; the caller's font is
    never modified."""
    font = QFont(base_font)
    font.setPointSizeF(max(BADGE_FONT_MIN_PT,
                           base_font.pointSizeF() - BADGE_FONT_DELTA_PT))
    font.setBold(True)
    return font


def badge_width(font, text):
    """The chip's total width: the text plus padding on both sides.
    Column widths are reserved against this value."""
    return QFontMetricsF(font).horizontalAdvance(text) + 2 * BADGE_PAD_PX


def _as_color(value):
    """A QColor from a QColor or QBrush, or None.

    Qt.ForegroundRole returns a QBrush, which QPainter.setPen rejects; a
    TypeError raised inside a paint callback can crash the process, so
    every colour passes through here first.
    """
    if isinstance(value, QColor):
        return value
    if isinstance(value, QBrush):
        return value.color()
    if isinstance(value, str) and value:
        return QColor(value)
    return None


def paint_badge(painter, rect, text, font, text_color=None):
    """Draw the chip inside `rect`, leaving the painter as it was found.

    Colours are read from theme.color() at call time, so a theme switch
    applies.
    """
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(theme.color("border"), 1))
    painter.setBrush(theme.color("surface3"))
    painter.drawRoundedRect(QRectF(rect), 3, 3)
    painter.setPen(_as_color(text_color) or theme.color("primary"))
    painter.setFont(font)
    painter.drawText(QRectF(rect), Qt.AlignCenter, text)
    painter.restore()


class BadgeDelegate(QStyledItemDelegate):
    """Paints a cell's DisplayRole text as a basis chip.

    Used in the record dialog's Basis column, so field rows use the same
    chip as column headings. An empty value paints nothing: an
    uncatalogued field has no chip.
    """

    def paint(self, painter, option, index):
        # The base paint() is not called, so the background (the
        # recovered-row tint) is filled here.
        bg = index.data(Qt.BackgroundRole)
        if bg is not None:
            painter.save()
            painter.fillRect(option.rect, bg)
            painter.restore()
        text = index.data(Qt.DisplayRole)
        if not text:
            return
        font = badge_font(option.font)
        width = badge_width(font, text)
        rect = QRectF(option.rect)
        chip = QRectF(rect.left() + BADGE_GAP_PX,
                      rect.top() + max(0.0, (rect.height() - BADGE_HEIGHT_PX) / 2.0),
                      width, min(BADGE_HEIGHT_PX, rect.height()))
        # Through _as_color: ForegroundRole is a QBrush.
        paint_badge(painter, chip, text, font,
                    _as_color(index.data(Qt.ForegroundRole)))

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        text = index.data(Qt.DisplayRole)
        if text:
            size.setWidth(int(badge_width(badge_font(option.font), text)
                              + 2 * BADGE_GAP_PX))
        return size
