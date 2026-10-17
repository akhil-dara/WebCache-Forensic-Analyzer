"""The whole of one cell's value, in a small window of its own.

A wrapped grid row stops at records_table.ROW_LINE_CAP lines and a capped
cell shows a "+N more lines" marker; the marker, Enter on the cell and
"Show whole value" open this window. The value is shown whole, and Copy
places the stored value on the clipboard exactly.

Non-modal, so the grid stays usable beside it.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout)

from . import copyable
from .wrapping_text import WrappingText

#: Every window title starts with this, so the window reads as what it is.
TITLE_PREFIX = "Whole value"


class WholeValueWindow(QDialog):
    def __init__(self, text, copy_text, heading, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setModal(False)
        self.setWindowTitle("%s — %s" % (TITLE_PREFIX, heading))
        self._text = "" if text is None else str(text)
        self._copy_text = self._text if copy_text is None else str(copy_text)

        root = QVBoxLayout(self)
        caption = copyable.selectable(QLabel(
            "%s — %s characters, shown whole." % (
                heading, format(len(self._text), ","))))
        caption.setWordWrap(True)
        root.addWidget(caption)

        self.text_view = WrappingText(self._text)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.text_view)
        root.addWidget(area, 1)

        bar = QHBoxLayout()
        self.status_label = copyable.selectable(QLabel(""))
        bar.addWidget(self.status_label, 1)
        self.copy_button = QPushButton("Copy value")
        self.copy_button.clicked.connect(self.copy)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bar.addWidget(self.copy_button)
        bar.addWidget(close)
        root.addLayout(bar)
        self.resize(720, 460)

    def full_text(self):
        return self._text

    def copy(self):
        """Copy the stored value exactly, as the grid's Copy cell does."""
        QGuiApplication.clipboard().setText(self._copy_text)
        self.status_label.setText("Copied.")
