"""A small pill-shaped, checkable filter shortcut ("InPrivate only",
"Has search terms").

This widget is the look and the checked state; the view applies the
filter. A checkable QPushButton gives keyboard toggling, a focus ring and
an accessible state, and is simpler to style than QCheckBox's platform
indicator. The two indicator states are painted with QPainter, as
shell/glyphs.py paints icons.
"""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QPushButton

from ..shell import theme

#: Device-pixel ratio the indicator pixmaps are drawn at, so they stay
#: sharp under display scaling.
_SCALE = 4
_INDICATOR_PX = 13


class QuickFilterChip(QPushButton):
    """One toggle. `accent` is the indicator's outline colour while
    unchecked, as a theme role ("error" for InPrivate, "primary"
    otherwise). The checked look is the same for every chip.
    """

    def __init__(self, text, accent="primary", parent=None):
        super().__init__(text, parent)
        self._accent = accent
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(_INDICATOR_PX, _INDICATOR_PX))
        self.setFixedHeight(28)
        self.toggled.connect(self._refresh_look)
        self._drawn_checked = None
        self._refresh_look(False)

    def refresh_theme(self):
        """Repaint the indicator pixmaps for the current theme."""
        self._refresh_look(self.isChecked())

    def setChecked(self, checked):
        """The look follows the state, including when the state is set
        with signals blocked."""
        super().setChecked(checked)
        self._refresh_look(self.isChecked())

    def looks_checked(self):
        """What the chip is currently painted as."""
        return bool(self._drawn_checked)

    def paintEvent(self, event):
        # Re-sync if the state changed without toggled() (a C++ caller,
        # a QSignalBlocker).
        if self._drawn_checked != self.isChecked():
            self._refresh_look(self.isChecked())
        super().paintEvent(event)

    def _refresh_look(self, checked):
        self._drawn_checked = bool(checked)
        self.setIcon(QIcon(self._indicator_pixmap(checked)))
        p = theme.PALETTES[theme.current_name()]
        if checked:
            self.setStyleSheet(
                "QPushButton { background: %(success_bg)s; "
                "border: 1px solid %(secondary)s; border-radius: 14px; "
                "padding: 0 11px 0 8px; color: %(text)s; font-size: 11.5px; "
                "font-weight: 500; text-align: left; } "
                "QPushButton:hover { border-color: %(primary)s; } "
                "QPushButton:focus { border: 2px solid %(primary)s; }" % p)
        else:
            self.setStyleSheet(
                "QPushButton { background: %(base)s; "
                "border: 1px solid %(border)s; border-radius: 14px; "
                "padding: 0 11px 0 8px; color: %(muted)s; font-size: 11.5px; "
                "font-weight: 400; text-align: left; } "
                "QPushButton:hover { border-color: %(muted)s; } "
                "QPushButton:focus { border: 2px solid %(primary)s; }" % p)

    def _indicator_pixmap(self, checked):
        size = _INDICATOR_PX
        px = QPixmap(size * _SCALE, size * _SCALE)
        px.fill(Qt.transparent)
        px.setDevicePixelRatio(_SCALE)
        painter = QPainter(px)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0.9, 0.9, size - 1.8, size - 1.8)
        if checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("primary"))
            painter.drawRoundedRect(rect, 3, 3)
            # The tick in the on-primary text colour.
            pen = QPen(theme.color("on_primary"))
            pen.setWidthF(1.8)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(size * 0.24, size * 0.52)
            path.lineTo(size * 0.44, size * 0.72)
            path.lineTo(size * 0.78, size * 0.30)
            painter.drawPath(path)
        else:
            pen = QPen(theme.color(self._accent))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, 3, 3)
        painter.end()
        return px
