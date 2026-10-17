"""A 0..1 share painted into a cell as a bar.

A delegate rather than a widget per row, so only visible cells are painted
and grids stay virtualised at any size.

The width is square-root scaled: activity is long-tailed, and on a linear
scale most bars would be stubs beside the busiest period. Because the width
is not proportional, the tooltip states the linear percentage, and the
exact count is in the Records column.

The style draws the item (selection, alternating rows, focus) and the
delegate adds one rounded fill on top, with no track behind it. A carved
row's bar is drawn in the carved colour, a live row's in `secondary`.
Engine-free; it reads two roles from the model.
"""
from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QApplication, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QToolTip)

from ..shell import theme
from .record_model import ROLE_IS_CARVED, ROLE_RAW


class ShareBarDelegate(QStyledItemDelegate):
    """Draws a 0..1 share as a bar. Reads ROLE_RAW, never DisplayRole."""

    #: The bar's height, centred in the row; less than a row, so it reads
    #: as a measurement rather than a filled cell.
    BAR_HEIGHT_PX = 8
    RADIUS_PX = 4
    #: Left and right margin, so the longest bar does not touch the grid
    #: line.
    TRACK_INSET_PX = 8
    #: The narrowest bar a nonzero share draws, so a period with records
    #: is never drawn as empty.
    MIN_VISIBLE_PX = 2

    #: What the bar is a share of. TimelineView sets this per grain.
    DEFAULT_UNIT = "period"

    #: The tooltip: the linear share the width does not show.
    TOOLTIP = ("%.1f%% of the busiest %s in this view. The bar's width is "
               "square-root scaled so smaller periods stay visible — the "
               "exact count is in the Records column.")

    def __init__(self, parent=None, unit=DEFAULT_UNIT):
        super().__init__(parent)
        self._unit = unit or self.DEFAULT_UNIT

    def set_unit(self, unit):
        """Name what the share is measured against ("day", "hour").
        Set on every render, since one delegate serves every grain."""
        self._unit = unit or self.DEFAULT_UNIT

    def unit(self):
        return self._unit

    # --- reading the value -------------------------------------------

    @staticmethod
    def share_of(index):
        """The share at `index`, clamped to 0..1, or None.

        Read from ROLE_RAW, not the formatted DisplayRole. None for a
        value that is not a number; nothing is drawn for it.
        """
        value = index.data(ROLE_RAW)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        share = float(value)
        if share != share:                      # NaN
            return None
        return min(1.0, max(0.0, share))

    @classmethod
    def bar_width(cls, track_px, share):
        """Pixels of bar for `share` across a `track_px` cell, square-root
        scaled. A zero share draws nothing; any nonzero share draws at
        least MIN_VISIBLE_PX.
        """
        if not share or track_px <= 0:
            return 0
        scaled = float(share) ** 0.5
        return max(cls.MIN_VISIBLE_PX, min(int(track_px), int(track_px * scaled)))

    def tooltip_for(self, share):
        return self.TOOLTIP % (float(share) * 100.0, self._unit)

    # --- painting -----------------------------------------------------

    def prepared_option(self, option, index):
        """A copy of the style option with the text removed, so the raw
        value is not printed under the bar."""
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        return opt

    def paint(self, painter, option, index):
        opt = self.prepared_option(option, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        # The style draws the item first (selection, alternating row
        # colour, focus); the bar is drawn on top.
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)

        share = self.share_of(index)
        if not share:
            return
        rect = opt.rect.adjusted(self.TRACK_INSET_PX, 0,
                                 -self.TRACK_INSET_PX, 0)
        width = self.bar_width(rect.width(), share)
        if width <= 0:
            return
        role = "carved" if index.data(ROLE_IS_CARVED) else "secondary"
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color(role))
        top = rect.y() + (rect.height() - self.BAR_HEIGHT_PX) / 2.0
        painter.drawRoundedRect(
            QRectF(rect.x(), top, float(width), float(self.BAR_HEIGHT_PX)),
            self.RADIUS_PX, self.RADIUS_PX)
        painter.restore()

    # --- the tooltip ---------------------------------------------------

    def helpEvent(self, event, view, option, index):
        """The tooltip, handled here because only this delegate knows the
        column is drawn."""
        if event is not None and event.type() == QEvent.ToolTip:
            share = self.share_of(index)
            if share is not None:
                QToolTip.showText(event.globalPos(), self.tooltip_for(share),
                                  view)
                return True
        return super().helpEvent(event, view, option, index)
