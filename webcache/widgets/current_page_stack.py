"""A stack of pages sized by the page on screen, not by every page it holds.

QStackedWidget takes its minimum size, size hint and height-for-width as
the largest over all its pages, so one tall view would give every screen a
page scroll. This widget uses a QStackedLayout whose size answers are the
current page's, and keeps the QStackedWidget API the shell uses.
"""
from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QFrame, QStackedLayout


class _CurrentPageLayout(QStackedLayout):
    def _page(self):
        return self.currentWidget()

    def sizeHint(self):
        page = self._page()
        return page.sizeHint() if page is not None else QSize(0, 0)

    def minimumSize(self):
        page = self._page()
        if page is None:
            return QSize(0, 0)
        return page.minimumSizeHint().expandedTo(page.minimumSize())

    def hasHeightForWidth(self):
        page = self._page()
        return page is not None and page.hasHeightForWidth()

    def heightForWidth(self, width):
        """The current page's minimum height at this width.

        A box layout's height-for-width is its preferred height, which
        would ask the scroll area for more room than the grids need; they
        shrink to fit."""
        page = self._page()
        if page is None or not page.hasHeightForWidth():
            return -1
        layout = page.layout()
        if layout is not None:
            margins = page.contentsMargins()
            need = (layout.minimumHeightForWidth(
                width - margins.left() - margins.right())
                + margins.top() + margins.bottom())
        else:
            need = page.heightForWidth(width)
        return max(need, self.minimumSize().height())


class CurrentPageStack(QFrame):
    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = _CurrentPageLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.currentChanged.connect(self._on_changed)

    def _on_changed(self, index):
        self._layout.invalidate()
        self.updateGeometry()
        self.currentChanged.emit(index)

    def addWidget(self, widget):
        return self._layout.addWidget(widget)

    def insertWidget(self, index, widget):
        return self._layout.insertWidget(index, widget)

    def removeWidget(self, widget):
        self._layout.removeWidget(widget)

    def setCurrentIndex(self, index):
        self._layout.setCurrentIndex(index)

    def setCurrentWidget(self, widget):
        self._layout.setCurrentWidget(widget)

    def currentIndex(self):
        return self._layout.currentIndex()

    def currentWidget(self):
        return self._layout.currentWidget()

    def widget(self, index):
        return self._layout.widget(index)

    def indexOf(self, widget):
        return self._layout.indexOf(widget)

    def count(self):
        return self._layout.count()

    def sizeHint(self):
        return self._layout.sizeHint()

    def minimumSizeHint(self):
        return self._layout.minimumSize()
