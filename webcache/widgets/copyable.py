"""Selectable text: anything shown can be selected and copied.

Labels are made selectable by mouse only. Keyboard selection would make
every caption a Tab stop; a mouse-selectable label already has the
standard right-click Copy and responds to Ctrl+C.
"""
import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

#: Set this dynamic property to True on a label that must NOT be
#: selectable: an icon-only label, or text inside a control whose clicks
#: selection would swallow.
DECORATIVE = "decorative"


def plain(label):
    """Show `label`'s text exactly as given, never as markup.

    Qt.AutoText renders text that looks like markup as rich text, and
    evidence can contain markup. A label that builds escaped markup itself
    sets Qt.RichText explicitly, and this leaves it alone."""
    if label.textFormat() == Qt.AutoText:
        label.setTextFormat(Qt.PlainText)
    return label


def selectable(label):
    """Make `label`'s text selectable by mouse (and so copyable), without
    changing whether it takes keyboard focus.

    setTextInteractionFlags can change a label's focus policy, so the
    original policy is restored afterwards. Also makes the label plain
    text unless it declared Qt.RichText (see plain()).
    """
    plain(label)
    original_policy = label.focusPolicy()
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if label.focusPolicy() != original_policy:
        label.setFocusPolicy(original_policy)
    return label


def literal_tooltip(text):
    """A tooltip that shows `text` exactly as given, never as markup.

    A tooltip has no text format and Qt renders markup-like text as rich
    text, so the text is escaped and wrapped in a pre-wrap paragraph:
    it shows literally, with its line breaks and spacing. Empty in, empty
    out."""
    if not text:
        return ""
    return ("<p style='white-space:pre-wrap'>%s</p>"
            % html.escape(str(text), quote=False))


class FixedWidthWrapLabel(QLabel):
    """A word-wrapped label whose height is measured at the width it paints.

    QLabel measures its height at the width the layout offers, not at its
    own maximum width, so a fixed-width label could reserve too few lines.
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return super().heightForWidth(min(width, self.maximumWidth()))
