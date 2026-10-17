"""A titled panel (icon, title, optional trailing widget) over a body the
caller fills; used by the Dashboard, Integrity, Findings and Export views.

ClickableRow is a plain content row that emits `clicked` on a left click,
with a pointing-hand cursor; the caller decides what a click opens.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import copyable
from ..shell import glyphs, theme


class ClickableRow(QFrame):
    """A content row that emits `clicked` on a left click.

    Its labels are decorative (a selectable label would turn the click
    into a selection), so the row offers a right-click Copy of the text it
    displays. `copy_figure_text` and `copy_row_text` are set when the row
    is built; a row with neither offers no menu.
    """
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        #: The figure as displayed; what "Copy" copies.
        self.copy_figure_text = None
        #: The row's label and figure; what "Copy row" copies.
        self.copy_row_text = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def build_context_menu(self):
        """Returned rather than shown, so tests can trigger an action
        without a blocking menu."""
        menu = QMenu(self)
        if self.copy_figure_text is not None:
            figure = self.copy_figure_text
            action = menu.addAction("Copy")
            action.triggered.connect(
                lambda: QGuiApplication.clipboard().setText(figure))
        if self.copy_row_text is not None:
            row_text = self.copy_row_text
            action = menu.addAction("Copy row")
            action.triggered.connect(
                lambda: QGuiApplication.clipboard().setText(row_text))
        return menu

    def contextMenuEvent(self, event):
        menu = self.build_context_menu()
        if menu.actions():
            menu.exec(event.globalPos())


class Card(QFrame):
    """Icon and title header, with an optional trailing widget, over a
    body the caller fills (`card.body.addWidget(...)`)."""

    def __init__(self, icon_name, title, parent=None):
        super().__init__(parent)
        self.setObjectName("dashCard")
        self._icon_name = icon_name
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("dashCardHeader")
        head_row = QHBoxLayout(header)
        head_row.setContentsMargins(12, 8, 12, 8)
        head_row.setSpacing(6)
        self._icon_label = QLabel()
        self._icon_label.setProperty(copyable.DECORATIVE, True)  # icon-only
        head_row.addWidget(self._icon_label)
        self._title_label = copyable.selectable(QLabel(title))
        self._title_label.setStyleSheet(
            "font-size: 12px; font-weight: 600; background: transparent;")
        head_row.addWidget(self._title_label)
        head_row.addStretch(1)
        self._trailing_slot = QHBoxLayout()
        self._trailing_slot.setContentsMargins(0, 0, 0, 0)
        head_row.addLayout(self._trailing_slot)
        outer.addWidget(header)

        body_wrap = QWidget()
        self.body = QVBoxLayout(body_wrap)
        self.body.setContentsMargins(12, 12, 12, 12)
        self.body.setSpacing(4)
        outer.addWidget(body_wrap, 1)

        self.refresh_theme()

    def set_trailing(self, widget):
        """Replace the trailing widget, if any."""
        while self._trailing_slot.count():
            item = self._trailing_slot.takeAt(0)
            old = item.widget()
            if old is not None:
                old.setParent(None)
        if widget is not None:
            self._trailing_slot.addWidget(widget)

    def refresh_theme(self):
        self._icon_label.setPixmap(
            glyphs.pixmap(self._icon_name, theme.color("primary"), 14))
        p = theme.PALETTES[theme.current_name()]
        self.setStyleSheet(
            "QFrame#dashCard { background: %(base)s; "
            "border: 1px solid %(border)s; border-radius: 8px; } "
            "QFrame#dashCardHeader { background: %(alt_base)s; "
            "border-top-left-radius: 7px; border-top-right-radius: 7px; "
            "border-bottom: 1px solid %(border)s; }" % p)
