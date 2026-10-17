"""The filter popup's value list: every distinct value of a column, each
with a tick box, held as plain arrays behind a QListView.

A column can hold 100,000 distinct values, so a fill is one model reset, a
search is one reset over the rows it keeps, and All/None is one
data-changed signal; no per-value item objects are created.

item(i) and count() read the list as a QListWidget would: index i is the
i-th distinct value whether or not a search hides it."""
import bisect

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QRect, QSize, Qt,
                            Signal)
from PySide6.QtGui import QTextLayout, QTextOption
from PySide6.QtWidgets import (QListView, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem)

_CHECKABLE = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable


def _is_checked(state):
    if isinstance(state, Qt.CheckState):
        return state == Qt.Checked
    return int(state) == Qt.Checked.value


class ValueListModel(QAbstractListModel):
    #: A value was ticked or unticked by the examiner (a click), as
    #: opposed to by the popup itself.
    userChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = []
        self.values = []
        self.checked = bytearray()
        self.hidden = bytearray()
        #: The value indices on show, in order -- every one unless a
        #: search hides some.
        self.rows = []

    # --- whole-list operations -------------------------------------------

    def set_items(self, labels, values, checked):
        self.beginResetModel()
        self.labels = list(labels)
        self.values = list(values)
        self.checked = bytearray(1 if c else 0 for c in checked)
        self.hidden = bytearray(len(self.labels))
        self.rows = list(range(len(self.labels)))
        self.endResetModel()

    def set_hidden_mask(self, hidden):
        self.beginResetModel()
        self.hidden = bytearray(1 if h else 0 for h in hidden)
        self.rows = [i for i, h in enumerate(self.hidden) if not h]
        self.endResetModel()

    def set_checked_where(self, predicate):
        """Tick each value for which PREDICATE(index) is True, untick the
        rest; one signal for the whole list."""
        self.checked = bytearray(1 if predicate(i) else 0
                                 for i in range(len(self.labels)))
        self._all_changed()

    def set_checked_shown(self, on):
        """Tick (or untick) every value a search leaves on show."""
        for i in self.rows:
            self.checked[i] = 1 if on else 0
        self._all_changed()

    def _all_changed(self):
        if self.rows:
            self.dataChanged.emit(self.index(0), self.index(len(self.rows) - 1),
                                  [Qt.CheckStateRole])

    # --- one value --------------------------------------------------------

    def set_checked(self, i, on):
        self.checked[i] = 1 if on else 0
        if not self.hidden[i]:
            row = self._row_of(i)
            if row is not None:
                ix = self.index(row)
                self.dataChanged.emit(ix, ix, [Qt.CheckStateRole])

    def set_hidden(self, i, hide):
        if bool(self.hidden[i]) == bool(hide):
            return
        mask = bytearray(self.hidden)
        mask[i] = 1 if hide else 0
        self.set_hidden_mask(mask)

    def _row_of(self, i):
        # rows is ascending, so a bisect finds a value's row.
        row = bisect.bisect_left(self.rows, i)
        return row if row < len(self.rows) and self.rows[row] == i else None

    # --- QAbstractListModel -----------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        i = self.rows[index.row()]
        if role in (Qt.DisplayRole, Qt.ToolTipRole, Qt.AccessibleTextRole):
            return self.labels[i]
        if role == Qt.CheckStateRole:
            return Qt.Checked if self.checked[i] else Qt.Unchecked
        if role == Qt.UserRole:
            return self.values[i]
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.CheckStateRole or not index.isValid():
            return False
        i = self.rows[index.row()]
        self.checked[i] = 1 if _is_checked(value) else 0
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        self.userChanged.emit()
        return True

    def ticked_count(self):
        return sum(self.checked)

    def ticked_hidden_count(self):
        return sum(1 for c, h in zip(self.checked, self.hidden) if c and h)

    def flags(self, index):
        return _CHECKABLE if index.isValid() else Qt.NoItemFlags


class ValueItem:
    """QListWidgetItem's reading of value I, for callers and tests that
    walk the list one value at a time."""

    __slots__ = ("_model", "_i")

    def __init__(self, model, i):
        self._model = model
        self._i = i

    def text(self):
        return self._model.labels[self._i]

    def data(self, role):
        if role == Qt.UserRole:
            return self._model.values[self._i]
        if role == Qt.CheckStateRole:
            return self.checkState()
        if role == Qt.DisplayRole:
            return self.text()
        return None

    def checkState(self):
        return Qt.Checked if self._model.checked[self._i] else Qt.Unchecked

    def setCheckState(self, state):
        self._model.set_checked(self._i, _is_checked(state))

    def isHidden(self):
        return bool(self._model.hidden[self._i])

    def setHidden(self, hide):
        self._model.set_hidden(self._i, hide)


#: Height around a value's text inside its row: the theme's item padding
#: (theme.py, valueList::item) and a pixel of slack each side.
_ROW_CHROME_Y = 8


def _wrapped_height(text, font, width):
    """Height of TEXT laid out the way the item delegate paints it: at
    word boundaries first, anywhere only when a word is wider than the
    line, so the measured line count matches the painted one."""
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    height = 0.0
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        height += line.height()
    layout.endLayout()
    return int(height + 0.999)


class _WrapDelegate(QStyledItemDelegate):
    """Each row as tall as its value wrapped to the list's visible width,
    so a long value is never cut off or pushed behind a horizontal
    scrollbar."""

    def __init__(self, view):
        super().__init__(view)
        self._view = view

    def sizeHint(self, option, index):
        width = max(60, self._view.viewport().width())
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.rect = QRect(0, 0, width, 1 << 16)
        style = self._view.style()
        # The text area the style itself will paint into -- after the tick
        # box, the spacing and the theme's padding -- less the text margin
        # QCommonStyle keeps inside it on each side.
        area = style.subElementRect(QStyle.SE_ItemViewItemText, opt,
                                    self._view)
        margin = style.pixelMetric(QStyle.PM_FocusFrameHMargin, None,
                                   self._view) + 1
        text_h = _wrapped_height(opt.text, opt.font,
                                 max(20, area.width() - 2 * margin))
        indicator = style.pixelMetric(QStyle.PM_IndicatorHeight, None,
                                      self._view)
        return QSize(width, max(text_h, indicator) + _ROW_CHROME_Y)


class ValueList(QListView):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("valueList")
        self.value_model = ValueListModel(self)
        self.setModel(self.value_model)
        self.setItemDelegate(_WrapDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # A stable viewport width: a scrollbar appearing mid-layout would
        # narrow it after the rows were measured.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setResizeMode(QListView.Adjust)
        self._laid_out_at = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.viewport().width()
        if width != self._laid_out_at:
            self._laid_out_at = width
            self.scheduleDelayedItemsLayout()

    def count(self):
        return len(self.value_model.labels)

    def item(self, i):
        return ValueItem(self.value_model, i)

    def clear(self):
        self.value_model.set_items([], [], [])
