"""A stat chip: a large coloured number over a small muted label, as on
the Dashboard.

Emits `clicked`; the caller decides what a click opens. Starts at "—",
not "0", so a figure not yet known never reads as zero.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QMenu, QSizePolicy, QVBoxLayout

from . import copyable
from ..shell import theme

#: What an unset chip shows.
_UNKNOWN = "—"


class StatChip(QFrame):
    clicked = Signal()

    def __init__(self, label, accent="primary", parent=None):
        super().__init__(parent)
        self.setObjectName("statChip")
        self._accent = accent
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(2)
        self._value_label = QLabel(_UNKNOWN)
        # Decorative labels: the whole chip is one click target, and a
        # selectable label would turn the click into a text selection.
        # The right-click menu copies the figure instead.
        self._value_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(self._value_label)  # text shown exactly, never as markup
        self._value_label.setAlignment(Qt.AlignCenter)
        self._label_label = QLabel(label)
        self._label_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(self._label_label)  # text shown exactly, never as markup
        self._label_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._value_label)
        lay.addWidget(self._label_label)

        self.refresh_theme()

    def set_value(self, text, tooltip=""):
        self._value_label.setText(text if text else _UNKNOWN)
        self.setToolTip(tooltip or "")

    def value(self):
        return self._value_label.text()

    def set_accent(self, role):
        """The value's colour role. A zero is not an alarm -- the
        caller passes "muted" for it."""
        if role != self._accent:
            self._accent = role
            self.refresh_theme()

    def accent(self):
        return self._accent

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def build_context_menu(self):
        """The right-click menu with Copy, which the decorative labels
        cannot offer themselves. Returned rather than shown, so tests can
        trigger an action without a blocking menu."""
        menu = QMenu(self)
        value = self.value()
        action = menu.addAction("Copy")
        action.triggered.connect(
            lambda: QGuiApplication.clipboard().setText(value))
        return menu

    def contextMenuEvent(self, event):
        self.build_context_menu().exec(event.globalPos())

    def refresh_theme(self):
        p = theme.PALETTES[theme.current_name()]
        self._value_label.setStyleSheet(
            "font-size: 20px; font-weight: 700; background: transparent; "
            "color: %s;" % theme.color(self._accent).name())
        self._label_label.setStyleSheet(
            "font-size: 10px; background: transparent; color: %s;"
            % p["muted"])
        self.setStyleSheet(
            "QFrame#statChip { background: %(base)s; "
            "border: 1px solid %(border)s; border-radius: 8px; } "
            "QFrame#statChip:hover { border: 1px solid %(primary)s; }" % p)
