"""Where the examiner came from.

NavHistory is a plain stack of (view key, breadcrumb, view state) -- Qt-free,
so its rules are testable without a window. The state is opaque here: the
window stores the row selection and scroll position it captured when the
examiner left the view, and hands it back on Back.

NavBar is the strip above the view stack that shows it: a Back button and
the breadcrumb of the view on screen ("from: History record -- row 8,
history"). The breadcrumb is plain text: it names a view and a row number
and kind, never a record's content, and nothing in it opens a path or URL."""
import collections

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ..widgets import copyable
from ..widgets.wrapping_text import WrappingText
from . import glyphs, theme

NavEntry = collections.namedtuple("NavEntry", "key crumb state",
                                  defaults=(None,))


class NavHistory:
    def __init__(self, limit=100):
        self._limit = limit
        self._stack = []

    def push(self, key, crumb="", state=None):
        self._stack.append(NavEntry(key, crumb or "", state))
        del self._stack[:-self._limit]

    def pop(self):
        return self._stack.pop() if self._stack else None

    def peek(self):
        return self._stack[-1] if self._stack else None

    def can_go_back(self):
        return bool(self._stack)

    def clear(self):
        self._stack = []


class NavBar(QWidget):
    HINT = "Alt+Left, or Backspace outside a text box"

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 4, 12, 0)
        row.setSpacing(10)
        # An ordinary QPushButton, so it takes the app's secondary-button
        # look in both themes; the navback property only trims its size
        # and adds the focus ring (theme.py).
        self.back_button = QPushButton("Back")
        self.back_button.setProperty("navback", True)
        self.back_button.setFocusPolicy(Qt.StrongFocus)
        self.back_button.setEnabled(False)
        # WrappingText: the identity in the crumb may be a long URL, which
        # a QLabel cannot wrap and copy exactly. Plain text, selectable by
        # mouse, never a link.
        self.crumb_label = WrappingText("")
        row.addWidget(self.back_button, 0, Qt.AlignTop)
        row.addWidget(self.crumb_label, 1)
        self.set_can_go_back(False)
        self.refresh_theme()

    def set_crumb(self, text):
        self.crumb_label.setText(text or "")
        self.crumb_label.setToolTip(copyable.literal_tooltip(text or ""))
        self._sync_visible()

    def _sync_visible(self):
        """Shown only when there is somewhere to go back to or a
        breadcrumb to show."""
        self.setVisible(self.back_button.isEnabled()
                        or bool(self.crumb_label.toPlainText()))

    def set_can_go_back(self, on, target=""):
        self.back_button.setEnabled(bool(on))
        self._sync_visible()
        if on:
            self.back_button.setToolTip(
                "Back to %s (%s)" % (target, self.HINT) if target
                else "Back (%s)" % self.HINT)
        else:
            self.back_button.setToolTip("Nothing to go back to")

    def refresh_theme(self):
        self.back_button.setIcon(glyphs.icon("chevron_left",
                                             theme.color("primary"), 14))
        self.crumb_label.setStyleSheet(
            "QTextEdit { background: transparent; border: none; "
            "font-size: 11.5px; color: %s; }" % theme.color("muted").name())
