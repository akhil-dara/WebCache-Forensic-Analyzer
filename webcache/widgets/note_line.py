"""A long note folds to one line behind an "ⓘ" toggle.

Wraps an existing label: the label keeps its whole text, and folding only
limits its height to one line. The toggle appears whenever there is more,
and the full text is one click or hover away.

Whether a note is open is remembered per `key` for the session."""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QToolButton

_UNBOUNDED = 16_777_215

#: key -> collapsed?  Session-wide; absent means "collapsed".
_STATE = {}

MORE = "ⓘ Note: show all"
LESS = "ⓘ Note: fold"


class NoteLine(QObject):
    def __init__(self, label, parent=None, key=None):
        super().__init__(parent or label)
        self.label = label
        self._key = key
        self._collapsed = _STATE.get(key, True) if key else True
        self.toggle = QToolButton()
        self.toggle.setAutoRaise(True)
        self.toggle.clicked.connect(
            lambda: self.set_collapsed(not self._collapsed))
        label.installEventFilter(self)
        self._sync()

    def is_collapsed(self):
        return self._collapsed

    def set_collapsed(self, collapsed):
        self._collapsed = bool(collapsed)
        if self._key:
            _STATE[self._key] = self._collapsed
        self._sync()

    def _one_line(self):
        margins = self.label.contentsMargins()
        return (self.label.fontMetrics().lineSpacing()
                + margins.top() + margins.bottom() + 2)

    def _needs_more(self):
        width = max(1, self.label.width())
        return self.label.heightForWidth(width) > self._one_line()

    def _sync(self):
        more = self._needs_more()
        self.toggle.setVisible(more)
        self.toggle.setText(LESS if not self._collapsed else MORE)
        self.label.setMaximumHeight(
            self._one_line() if (more and self._collapsed) else _UNBOUNDED)
        self.label.setToolTip(self.label.text() if more else "")

    def eventFilter(self, watched, event):
        if watched is self.label and event.type() in (QEvent.Resize,
                                                      QEvent.Show):
            self._sync()
        return False
