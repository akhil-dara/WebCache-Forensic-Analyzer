"""Text that wraps, is never elided, and copies exactly.

A QLabel wraps only at spaces, so a long URL either widens its parent or
is clipped. This read-only, frameless QTextEdit wraps anywhere it must and
sizes its height to its content. Break opportunities come from
break_points.py (shared with the grid) and exist only in the drawn text;
text(), full_text() and copies return the stored value.

Plain text only, since evidence may contain markup. Selectable by mouse
only, so it does not join the Tab chain.
"""
import math

from PySide6.QtCore import QMimeData, QSize, Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import QFrame, QSizePolicy, QTextEdit

from .break_points import ZWSP, with_soft_breaks


class WrappingText(QTextEdit):
    """`max_lines`: grow up to that many lines, then scroll the rest
    (the text stays whole); None grows to the whole content."""

    def __init__(self, text="", parent=None, max_lines=None):
        super().__init__(parent)
        self._max_lines = max_lines
        self.setReadOnly(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setFocusPolicy(Qt.NoFocus)
        self.document().setDocumentMargin(0)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QTextEdit { background: transparent; border: none; }")
        policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._full_text = ""
        self.set_full_text(text)

    # --- the QLabel-like surface callers and tests use --------------------

    def set_full_text(self, text):
        self._full_text = "" if text is None else str(text)
        self.setPlainText(with_soft_breaks(self._full_text))
        self._fit_height()

    def toPlainText(self):
        """The text as stored: the document's break points are drawn
        text, never the value."""
        return super().toPlainText().replace(ZWSP, "")

    def createMimeDataFromSelection(self):
        """Copy the stored text: a selection never carries a break point."""
        mime = QMimeData()
        mime.setText(self.textCursor().selection().toPlainText()
                     .replace(ZWSP, ""))
        return mime

    def setText(self, text):
        self.set_full_text(text)

    def full_text(self):
        return self._full_text

    def text(self):
        return self._full_text

    def textFormat(self):
        return Qt.PlainText

    # --- height follows width -------------------------------------------

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        doc = self.document().clone()
        doc.setDocumentMargin(0)
        doc.setTextWidth(max(1, width))
        return math.ceil(doc.size().height()) + 2 * self.frameWidth()

    def sizeHint(self):
        natural = self.fontMetrics().horizontalAdvance(self._full_text) + 4
        return QSize(natural, self.heightForWidth(self.width() or natural))

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().lineSpacing())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def _fit_height(self):
        width = self.viewport().width() if self.width() > 0 else 400
        wanted = self.heightForWidth(width)
        if self._max_lines is not None:
            # A few pixels past the last line, so its descenders are not
            # cut against whatever sits below.
            ceiling = (self._max_lines * self.fontMetrics().lineSpacing()
                       + 2 * self.frameWidth() + 4)
            if wanted > ceiling:
                wanted = ceiling
                self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            else:
                self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if self.height() != wanted:
            self.setFixedHeight(wanted)
