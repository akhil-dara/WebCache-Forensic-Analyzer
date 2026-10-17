"""After an export, where it went -- the full path, Copy path and
Show in folder, until dismissed.

Lives in the status bar, on one line: the full path, with the summary of
what was written in its tooltip."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QPushButton, QSizePolicy,
                               QToolButton, QWidget)

from ..widgets import copyable
from ..widgets.wrapping_text import WrappingText
from . import theme


class ExportResultBar(QWidget):
    copyRequested = Signal(str)
    showRequested = Signal(str)
    #: True when the bar appears, False when it is dismissed: the shell
    #: gives the bar the status message's room while it is up.
    shownChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        # A plain QWidget paints no stylesheet background without this.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._path = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, 4, 0)
        row.setSpacing(8)
        # WrappingText: a long path wraps and stays whole and copyable,
        # without setting a minimum width for the window.
        self.path_label = WrappingText("")
        self.path_label.setSizePolicy(QSizePolicy.Ignored,
                                      QSizePolicy.Preferred)
        self.path_label.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.copy_button = QPushButton("Copy path")
        self.show_button = QPushButton("Show in folder")
        self.show_button.setToolTip(
            "Opens the folder you exported into. Evidence folders are "
            "never opened.")
        self.close_button = QToolButton()
        self.close_button.setAutoRaise(True)
        self.close_button.setText("\u2715")
        self.close_button.setToolTip("Dismiss")
        self.close_button.setAccessibleName("Dismiss")
        row.addWidget(self.path_label, 1)
        row.addWidget(self.copy_button)
        row.addWidget(self.show_button)
        row.addWidget(self.close_button)
        self.copy_button.clicked.connect(
            lambda: self.copyRequested.emit(self._path))
        self.show_button.clicked.connect(
            lambda: self.showRequested.emit(self._path))
        self.close_button.clicked.connect(self.hide)
        self.setVisible(False)
        self.refresh_theme()

    def path(self):
        return self._path

    def show_result(self, summary, path):
        self._path = path or ""
        self.path_label.setText("Exported: %s" % self._path)
        self.path_label.setToolTip(copyable.literal_tooltip(
            "%s\n%s" % (summary, self._path)))
        self.copy_button.setEnabled(bool(self._path))
        self.show_button.setEnabled(bool(self._path))
        self.setVisible(True)

    def showEvent(self, event):
        super().showEvent(event)
        self.shownChanged.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.shownChanged.emit(False)

    def refresh_theme(self):
        p = theme.PALETTES[theme.current_name()]
        # The dismiss cross in the text colour on the bar's background,
        # instead of the native style's light button box.
        self.setStyleSheet(
            "ExportResultBar { background: %(success_bg)s; "
            "border-bottom: 1px solid %(border)s; }"
            "ExportResultBar QToolButton { background: transparent; "
            "border: none; color: %(text)s; font-size: 13px; "
            "padding: 2px 6px; }"
            "ExportResultBar QToolButton:hover { color: %(muted)s; }"
            # The bar's own stylesheet takes precedence over the app's, so
            # the keyboard focus ring is restated here.
            "ExportResultBar QToolButton:focus { border: 2px solid "
            "%(primary)s; }" % p)
