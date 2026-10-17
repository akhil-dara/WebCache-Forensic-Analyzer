"""One popup, two panels, combined with AND.

Values: every distinct value, checkable, with counts. Every value is
listed, with no cap and no "load more": a partial list could let an
examiner search for a value that is present and get no hits.

Condition: an operator and up to two operands, offered by column kind
(OPERATORS_BY_KIND in record_filter.py is authoritative; this file reads
it).

The two combine rather than replace, so ticked values are kept when a
condition is applied, and what produced the rows on screen can always be
stated.

That holds when the popup is reopened, too: a popup opened on a column
that already has a Condition seeds its operator and operand fields from
RecordFilter.condition_for() (_seed_condition), so OK after changing only
the values panel never removes the condition.

"in the last N days" is measured back from the newest value in the
column, not from today (see Condition in record_filter.py: an exhibit is
examined after it was collected, and anchoring to today would return no
rows). RecordFilter resolves the anchor whenever the condition is attached
or the rows change; anchor_label previews the resolved date as soon as
the operator is chosen.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListView,
                               QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

import collections
import datetime

from ..shell import glyphs, theme
from . import copyable
from .value_list import ValueList
from .column_spec import blank_label, display_text, searchable_text
from .calendar_button import CalendarButton
from .time_format import format_dt
from .record_filter import (OPERAND_PLACEHOLDERS, Condition, JoinedCondition,
                            operators_for, sort_labels)

#: Operators that need a second operand.
_TWO_OPERAND = ("between",)
#: Operators that need none.
_NO_OPERAND = ("is blank", "is not blank", "is yes", "is no")

#: The operator box's first entry: no condition at all.
NO_CONDITION = "(no condition)"
#: The one operator whose meaning depends on a reference point that is not
#: obvious from the operand alone -- see the module docstring.
_ANCHOR_OP = "in the last N days"
_SEARCH_DEBOUNCE_MS = 120


class _TitleRow(QFrame):
    """The popup's own title row: the column label and a compact Copy
    column name button, in the app's colours. Dragging it moves the
    popup. No Close here: Cancel and Esc already close it, and a second
    full-size button squeezed the column's own title."""

    def __init__(self, text, copy_button, parent=None):
        super().__init__(parent)
        self.setObjectName("filterTitle")
        self._drag_offset = None
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 6, 6)
        self.label = QLabel(text)
        # Inside a drag handle: a selectable label would eat the drag.
        # The Copy column name button beside it copies the same text.
        self.label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(self.label)
        self.label.setStyleSheet("font-weight: 600; background: transparent;")
        row.addWidget(self.label, 1)
        copy_button.setParent(self)
        row.addWidget(copy_button)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.window().pos())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            window = self.window()
            target = event.globalPosition().toPoint() - self._drag_offset
            # Clamped to the screen the window is on, so the popup cannot
            # be dragged fully off screen (on a second monitor too).
            screen = window.screen()
            if screen is not None:
                avail = screen.availableGeometry()
                max_x = avail.x() + avail.width() - window.width()
                max_y = avail.y() + avail.height() - window.height()
                target.setX(min(max(target.x(), avail.x()),
                                max(avail.x(), max_x)))
                target.setY(min(max(target.y(), avail.y()),
                                max(avail.y(), max_y)))
            window.move(target)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class FilterPopup(QDialog):
    filterApplied = Signal()

    #: a value list this short lays out in one pass, so the first
    #: paint already shows it. Longer lists keep the batched layout that
    #: stops a huge column stalling the event loop.
    #: The widest the value picker grows to fit long values (logical px).
    #: Wide enough that a typical address wraps once, not three times.
    MAX_WIDTH = 560
    #: Room around a value's text: indicator, gaps, padding, scrollbar and
    #: the popup's own margins.
    VALUE_CHROME_PX = 96

    SYNC_FILL_MAX = 400

    def __init__(self, model, column, parent=None):
        super().__init__(parent)
        # no native (white) title bar; the title row below is the
        # app's own, and QDialog's Escape handling still closes it.
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("filterPopup")
        self.model = model
        self.column = column
        self.setWindowTitle("Filter: %s" % column.label)
        # Not modal: while it is open, the sidebar, other views and other
        # columns' filters stay reachable. It closes itself when focus
        # moves to another window (see _on_focus_changed).
        self.setModal(False)
        self._status = ""

        self.search_box = QLineEdit(placeholderText="Search values…")
        self.values_list = ValueList()
        # A value is never cut. Wrapped rows are not uniform in height, so
        # the list lays out in batches on idle turns of the event loop, and
        # a long column's picker opens at once without stalling. 50 rows
        # per batch keeps each batch well under the 150 ms stall threshold
        # (test_no_elision): larger batches stall, and much smaller ones add
        # scheduling overhead without reducing the worst gap.
        self.values_list.setUniformItemSizes(False)
        self.values_list.setWordWrap(True)
        self.values_list.setTextElideMode(Qt.ElideNone)
        self.values_list.setLayoutMode(QListView.Batched)
        self.values_list.setBatchSize(50)
        self.status_label = copyable.selectable(QLabel(""))
        self.status_label.setWordWrap(True)
        # Index 0 is "no condition", so OK after ticking only values adds
        # no condition. Without it, a Yes/No column's first operator ("is
        # yes", no operand) would also hide every "No" row.
        ops = list(operators_for(
            column, model.value_counts(column.key)
            if column.kind == "flag" else ()))
        hint = OPERAND_PLACEHOLDERS.get(column.kind, "text")

        def condition_row():
            box = QComboBox()
            box.addItem(NO_CONDITION)
            box.addItems(ops)
            a, b = QLineEdit(), QLineEdit()
            for field in (a, b):
                field.setPlaceholderText(hint)
                # Never narrower than its hint, so it is not cut to "YY...".
                field.setMinimumWidth(
                    field.fontMetrics().horizontalAdvance(hint) + 28)
            return box, a, b
        self.operator_box, self.operand_a, self.operand_b = condition_row()
        #: Excel's Custom AutoFilter: a second condition on this column,
        #: joined to the first by And or Or. Filled alone, it is simply
        #: the column's one condition.
        self.join_box = QComboBox()
        self.join_box.addItems(["And", "Or"])
        self.operator_box_2, self.operand_a_2, self.operand_b_2 = condition_row()
        #: A calendar beside each date operand of a time column, limited to
        #: the dates the column holds (calendar_for).
        self._calendars = {}
        if column.kind in ("time", "time_local"):
            dates = [v for v in (r.get(column.key) for r in model.filter.rows)
                     if hasattr(v, "year")]
            per_day = collections.Counter(
                (v.date() if hasattr(v, "date") else v) for v in dates)
            for field in (self.operand_a, self.operand_b,
                          self.operand_a_2, self.operand_b_2):
                button = CalendarButton(field)
                if dates:
                    button.set_span(min(dates), max(dates))
                    button.set_day_counts(per_day)
                self._calendars[id(field)] = button
        #: a time column is picked by year > month > day, not from
        #: hundreds of distinct timestamps. The flat list stays built
        #: (hidden) for every other kind.
        self.date_tree = None
        if column.kind in ("time", "time_local"):
            self.date_tree = QTreeWidget()
            self.date_tree.setHeaderHidden(True)
            self.date_tree.setUniformRowHeights(True)
            # Room for a year opened to its months without scrolling.
            self.date_tree.setMinimumHeight(
                10 * (self.date_tree.fontMetrics().lineSpacing() + 8))
            self.values_list.setVisible(False)
        #: Case sensitivity of the Condition attached to this column. The
        #: popup has no control for it and builds case_sensitive=False, so
        #: this keeps a case-sensitive condition attached elsewhere
        #: unchanged on reopen (see _seed_condition).
        self._case_sensitive = False
        self._seed_condition()
        #: Preview of the resolved "in the last N days" window. Hidden for
        #: every other operator; see the module docstring for why this
        #: exists at all rather than only being visible after Apply.
        self.anchor_label = copyable.selectable(QLabel(""))
        self.anchor_label.setWordWrap(True)
        self.anchor_label.setVisible(False)
        btn_all = QPushButton("All")
        btn_none = QPushButton("None")
        #: Right-clicking a heading opens this popup directly, so "Copy
        #: column name" is offered here. It copies the heading label
        #: (column.label), as in the window title ("Filter: <label>"), not
        #: the internal key.
        self.copy_name_button = QPushButton("")
        self.copy_name_button.setIcon(
            glyphs.icon("copy", theme.color("primary"), 15))
        self.copy_name_button.setToolTip("Copy column name")
        self.copy_name_button.setAccessibleName("Copy column name")
        self.copy_name_button.setAutoDefault(False)
        self.copy_name_button.clicked.connect(self._copy_column_name)
        self.title_row = _TitleRow(column.label, self.copy_name_button)
        #: Exposed so a test (or any other caller) can drive the REAL OK
        #: button rather than calling apply() directly -- otherwise a
        #: severed accepted-signal wire would go undetected.
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons = self.button_box

        #: Sorts the table on this column, as a header click does.
        asc_text, desc_text = sort_labels(column)
        self.sort_asc_button = QPushButton(asc_text)
        self.sort_desc_button = QPushButton(desc_text)
        self.sort_asc_button.clicked.connect(lambda: self._sort(False))
        self.sort_desc_button.clicked.connect(lambda: self._sort(True))
        sort_row = QHBoxLayout()
        sort_row.addWidget(self.sort_asc_button)
        sort_row.addWidget(self.sort_desc_button)
        sort_row.addStretch(1)
        # All/None at the end of the search row, not a row of their own
        # (and not beside the sort buttons, which widened every popup for
        # a column of short values): the search box gives way to them.
        search_row = QHBoxLayout()
        search_row.addWidget(self.search_box, 1)
        search_row.addWidget(btn_all)
        search_row.addWidget(btn_none)
        cond = QHBoxLayout()
        cond.addWidget(self.operator_box)
        for field in (self.operand_a, self.operand_b):
            cond.addWidget(field)
            if id(field) in self._calendars:
                cond.addWidget(self._calendars[id(field)])
        join_row = QHBoxLayout()
        join_row.addWidget(self.join_box)
        join_row.addStretch(1)
        cond_2 = QHBoxLayout()
        cond_2.addWidget(self.operator_box_2)
        for field in (self.operand_a_2, self.operand_b_2):
            cond_2.addWidget(field)
            if id(field) in self._calendars:
                cond_2.addWidget(self._calendars[id(field)])
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 10)
        root.addWidget(self.title_row)
        body = QVBoxLayout()
        body.setContentsMargins(10, 8, 10, 0)
        body.addLayout(sort_row)
        body.addLayout(search_row)
        body.addWidget(self.values_list, 1)
        #: How many values are ticked, and how many of those a search is
        #: hiding: a hidden pick is kept, and this line says so.
        self.selection_label = QLabel("")
        self.selection_label.setTextFormat(Qt.PlainText)
        self.selection_label.setObjectName("filterSelection")
        body.addWidget(self.selection_label)
        if self.date_tree is not None:
            body.addWidget(self.date_tree, 1)
        body.addWidget(self.status_label)
        #: Excel's heading over its two condition rows.
        self.condition_caption = QLabel("Show rows where:")
        body.addWidget(self.condition_caption)
        body.addLayout(cond)
        body.addLayout(join_row)
        body.addLayout(cond_2)
        body.addWidget(self.anchor_label)
        body.addWidget(buttons)
        root.addLayout(body)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._apply_value_search)
        self.search_box.textChanged.connect(lambda _t: self._debounce.start())
        btn_all.clicked.connect(self.select_all)
        btn_none.clicked.connect(self.select_none)
        self.operator_box.currentTextChanged.connect(self._sync_operands)
        self.operator_box_2.currentTextChanged.connect(self._sync_operands)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        # Not modal, so the popup has to notice when the examiner moves to
        # another window without pressing Cancel. Both signals below are
        # needed (see _belongs_here).
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_changed)
            app.focusWindowChanged.connect(self._on_focus_window_changed)

        self.values_list.value_model.userChanged.connect(self._picked_by_hand)
        self._populate()
        self._sync_operands(self.operator_box.currentText())
        # The examiner opened this to type. Give them the box.
        self.search_box.setFocus()

    # --- values ------------------------------------------------------------

    def _populate_dates(self):
        """Year > month > day, each with a row count. A day leaf carries
        every stored value on that day (Qt.UserRole), so what is chosen is
        still the raw values and filtering is unchanged. The day is read
        off the datetime's own fields -- the clock the grid displays (UTC
        columns hold UTC values, LOCAL columns hold each record's own
        local clock)."""
        tree = self.date_tree
        tree.clear()
        active = self.model.filter.allowed_values(self.column.key)
        years = {}
        blanks = []
        for value, count in self.model.value_counts(self.column.key):
            if not isinstance(value, datetime.datetime):
                blanks.append((value, count))
                continue
            years.setdefault(value.year, {}).setdefault(
                value.month, {}).setdefault(value.day, []).append(
                    (value, count))
        tristate = Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate
        tree.blockSignals(True)
        for y in sorted(years):
            y_item = QTreeWidgetItem()
            y_item.setFlags(y_item.flags() | tristate)
            y_total = 0
            for m in sorted(years[y]):
                m_label = "%04d-%02d" % (y, m)
                m_item = QTreeWidgetItem()
                m_item.setFlags(m_item.flags() | tristate)
                m_total = 0
                for d in sorted(years[y][m]):
                    values = years[y][m][d]
                    n = sum(c for _v, c in values)
                    day = "%s-%02d" % (m_label, d)
                    d_item = QTreeWidgetItem(
                        ["%s  (%s)" % (day, format(n, ","))])
                    d_item.setFlags(d_item.flags() | Qt.ItemIsUserCheckable)
                    d_item.setData(0, Qt.UserRole, [v for v, _c in values])
                    d_item.setData(0, Qt.UserRole + 1, day)
                    on = active is None or any(v in active for v, _c in values)
                    d_item.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
                    m_item.addChild(d_item)
                    m_total += n
                m_item.setText(0, "%s  (%s)" % (m_label, format(m_total, ",")))
                y_item.addChild(m_item)
                y_total += m_total
            y_item.setText(0, "%04d  (%s)" % (y, format(y_total, ",")))
            tree.addTopLevelItem(y_item)
        for value, count in blanks:
            item = QTreeWidgetItem(["%s  (%s)" % (blank_label(self.column),
                                                  format(count, ","))])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setData(0, Qt.UserRole, [value])
            item.setData(0, Qt.UserRole + 1, blank_label(self.column))
            item.setCheckState(
                0, Qt.Checked if active is None or value in active
                else Qt.Unchecked)
            tree.addTopLevelItem(item)
        for i in range(tree.topLevelItemCount()):
            self._settle(tree.topLevelItem(i))
        tree.blockSignals(False)

    def _settle(self, item):
        """Post-order: a parent is checked when every child is, unchecked
        when none is, partial otherwise."""
        n = item.childCount()
        if not n:
            return item.checkState(0)
        states = {self._settle(item.child(i)) for i in range(n)}
        state = (next(iter(states)) if len(states) == 1
                 else Qt.PartiallyChecked)
        item.setCheckState(0, state)
        return state

    def _leaves(self):
        """Every checkable leaf of the date tree (days and the blank
        node), in tree order."""
        tree = self.date_tree
        out = []
        stack = [tree.topLevelItem(i)
                 for i in range(tree.topLevelItemCount() - 1, -1, -1)]
        while stack:
            item = stack.pop()
            n = item.childCount()
            if n:
                stack.extend(item.child(i) for i in range(n - 1, -1, -1))
            else:
                out.append(item)
        return out

    def _populate(self):
        if self.date_tree is not None:
            self._populate_dates()
            return
        counts = self.model.value_counts(self.column.key)
        self.values_list.setLayoutMode(
            QListView.SinglePass if len(counts) <= self.SYNC_FILL_MAX
            else QListView.Batched)
        active = self.model.filter.allowed_values(self.column.key)
        labels, values = [], []
        for value, count in counts:
            # The item text is what the grid paints for this value (e.g.
            # "Yes" for a flag column), so the picker uses the grid's words.
            # The item's data role keeps the raw value, so ticking filters
            # against what the rows store.
            label = display_text(value, self.column) or blank_label(self.column)
            labels.append("%s  (%s)" % (label, "{:,}".format(count)))
            values.append(value)
        self._fit_width_to(labels)
        self._fit_list_rows(len(labels))
        # One reset for the whole list (see value_list's docstring).
        self.values_list.value_model.set_items(
            labels, values,
            [True] * len(values) if active is None
            else [v in active for v in values])
        #: True while the ticks are the popup's own (everything, or a
        #: search's matches): a search then selects exactly its matches.
        #: False once the examiner picks by hand; picks then survive every
        #: later search.
        self._ticks_follow_search = active is None
        self._show_selection()

    #: Values on screen at once before the list scrolls.
    LIST_ROWS = 12

    def _fit_list_rows(self, count):
        """Tall enough for up to LIST_ROWS values, fewer when there are
        fewer: at its default height the list showed six values in a
        popup whose other rows had just been cut down to make room."""
        line = self.values_list.fontMetrics().lineSpacing()
        rows = max(3, min(count, self.LIST_ROWS))
        height = rows * (line + 10) + 2 * self.values_list.frameWidth()
        screen = self.screen()
        if screen is not None:
            height = min(height, screen.availableGeometry().height() // 2)
        self.values_list.setMinimumHeight(height)

    def _fit_width_to(self, labels):
        """As wide as the longest values need, never past MAX_WIDTH or the
        screen, so long values are not wrapped into a narrow box and a short
        column stays compact. Measured on the longest few labels only."""
        longest = sorted(labels, key=len, reverse=True)[:50]
        metrics = self.values_list.fontMetrics()
        need = max((metrics.horizontalAdvance(t) for t in longest),
                   default=0) + self.VALUE_CHROME_PX
        cap = self.MAX_WIDTH
        screen = self.screen()
        if screen is not None:
            cap = min(cap, screen.availableGeometry().width() - 40)
        # Only ever a floor: the layout keeps the popup's own natural width
        # (its sizeHint, mid-fill, is a pre-layout figure and too large).
        target = min(need, cap)
        if target > self.minimumWidth():
            self.setMinimumWidth(target)

    def _apply_value_search(self):
        """Matches against each item's value (Qt.UserRole), never the full
        label, whose "(1,234)" count suffix would let a numeric search
        match on a row count.

        The value is matched through column_spec.searchable_text (what the
        item shows, plus plain digits on a numeric column), the same rule
        as the grid's search box: "yes" finds "Yes", an offset is found by
        its hex, and "12,345" by either spelling."""
        needle = self.search_box.text().strip().lower()
        shown = 0
        if self.date_tree is not None:
            shown = self._search_dates(needle)
            self._set_status(
                "No values match \"%s\"." % self.search_box.text()
                if needle and not shown else "")
            return
        column = self.column
        hidden = [needle not in searchable_text(value, column).lower()
                  for value in self.values_list.value_model.values]
        model = self.values_list.value_model
        model.set_hidden_mask(hidden)
        if self._ticks_follow_search:
            if needle:
                model.set_checked_where(lambda i: not hidden[i])
            else:
                model.set_checked_where(lambda i: True)
        self._show_selection()
        shown = len(hidden) - sum(hidden)
        self._set_status(
            "No values match \"%s\"." % self.search_box.text()
            if needle and not shown else "")

    def _search_dates(self, needle):
        """A day stays when the needle is in its date or in any of its
        values' displayed text; empty months and years are hidden."""
        shown = 0
        for leaf in self._leaves():
            day = leaf.data(0, Qt.UserRole + 1).lower()
            hit = (not needle or needle in day or any(
                needle in searchable_text(v, self.column).lower()
                for v in leaf.data(0, Qt.UserRole)))
            leaf.setHidden(not hit)
            shown += hit
        for i in range(self.date_tree.topLevelItemCount()):
            self._hide_empty(self.date_tree.topLevelItem(i))
        return shown

    def _hide_empty(self, item):
        n = item.childCount()
        if not n:
            return not item.isHidden()
        any_shown = False
        for i in range(n):
            any_shown |= self._hide_empty(item.child(i))
        item.setHidden(not any_shown)
        return any_shown

    def visible_value_count(self):
        if self.date_tree is not None:
            return sum(not leaf.isHidden() for leaf in self._leaves())
        return len(self.values_list.value_model.rows)

    def status_text(self):
        return self._status

    def _set_status(self, text):
        self._status = text
        self.status_label.setText(text)

    def _copy_column_name(self):
        QGuiApplication.clipboard().setText(self.column.label)

    def _sort(self, descending):
        """Order the table on this column and close, as Excel's drop-down
        does. Through the table when there is one, so its sort indicator
        and remembered keys agree with what a header click would leave.
        Ticks and a condition not yet applied are dropped, as Cancel
        drops them."""
        table = self.parent()
        if hasattr(table, "sort_by_key"):
            table.sort_by_key(self.column.key, descending)
        else:
            self.model.sort_by(self.column.key, descending)
        self.reject()

    def select_all(self):
        self._set_all(Qt.Checked)
        self._picked_by_hand()

    def select_none(self):
        self._set_all(Qt.Unchecked)
        self._picked_by_hand()

    def _picked_by_hand(self):
        self._ticks_follow_search = False
        self._show_selection()

    def selection_text(self):
        """ "2 of 523 values ticked — 1 hidden by the search"."""
        if self.date_tree is not None:
            return ""
        model = self.values_list.value_model
        total = len(model.values)
        text = "%s of %s value%s ticked" % (
            format(model.ticked_count(), ","), format(total, ","),
            "" if total == 1 else "s")
        hidden = model.ticked_hidden_count()
        if hidden:
            text += " — %s hidden by the search" % format(hidden, ",")
        return text

    def _show_selection(self):
        if hasattr(self, "selection_label"):
            self.selection_label.setText(self.selection_text())
            self.selection_label.setVisible(self.date_tree is None)

    def _set_all(self, state):
        """Applies to the values currently shown, so a search then All ticks
        what the examiner is looking at rather than the whole list."""
        if self.date_tree is not None:
            for leaf in self._leaves():
                if not leaf.isHidden():
                    leaf.setCheckState(0, state)
            return
        self.values_list.value_model.set_checked_shown(state == Qt.Checked)

    def check_only(self, values):
        if self.date_tree is not None:
            for leaf in self._leaves():
                on = any(v in values for v in leaf.data(0, Qt.UserRole))
                leaf.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
            return
        model = self.values_list.value_model
        model.set_checked_where(lambda i: model.values[i] in values)
        self._picked_by_hand()

    def chosen_values(self):
        if self.date_tree is not None:
            checked, total = set(), set()
            for leaf in self._leaves():
                values = leaf.data(0, Qt.UserRole) or []
                total.update(values)
                if leaf.checkState(0) == Qt.Checked:
                    checked.update(values)
            return None if checked == total else checked
        model = self.values_list.value_model
        total = len(model.values)
        checked = {v for v, on in zip(model.values, model.checked) if on}
        # Everything ticked is no filter. Nothing ticked is a filter that
        # keeps no rows, never one that keeps everything.
        return None if len(checked) == total else checked

    # --- condition -----------------------------------------------------------

    def _seed_condition(self):
        """Seed the condition fields from the Condition already attached to
        this column. apply() calls set_condition() with whatever
        chosen_condition() reads from the fields, so blank fields would
        remove the condition when OK is pressed after changing only the
        values panel. See the module docstring.
        """
        existing = self.model.filter.condition_for(self.column.key)
        if existing is None:
            return
        rows = [(existing, self.operator_box, self.operand_a, self.operand_b)]
        if isinstance(existing, JoinedCondition):
            self.join_box.setCurrentText(existing.join.capitalize())
            rows = [(existing.first, self.operator_box, self.operand_a,
                     self.operand_b),
                    (existing.second, self.operator_box_2, self.operand_a_2,
                     self.operand_b_2)]
        for cond, box, a, b in rows:
            idx = box.findText(cond.op)
            if idx >= 0:
                box.setCurrentIndex(idx)
            if cond.a is not None:
                a.setText(str(cond.a))
            if cond.b is not None:
                b.setText(str(cond.b))
        self._case_sensitive = existing.case_sensitive

    def _sync_operands(self, _op=None):
        ops = []
        for box, a, b in self._condition_rows():
            op = box.currentText()
            a.setVisible(op not in _NO_OPERAND and op != NO_CONDITION)
            b.setVisible(op in _TWO_OPERAND)
            ops.append(op)
        # The second condition, and what joins it, appear once there is a
        # first to join it to -- or when the column already carries one.
        second = (self.operator_box.currentText() != NO_CONDITION
                  or self.operator_box_2.currentText() != NO_CONDITION)
        self.join_box.setVisible(second)
        self.operator_box_2.setVisible(second)
        if not second:
            self.operand_a_2.setVisible(False)
            self.operand_b_2.setVisible(False)
        # A calendar shows beside a visible date operand, never for a
        # number of days.
        for box, a, b in self._condition_rows():
            for field in (a, b):
                button = self._calendars.get(id(field))
                if button is not None:
                    button.setVisible(field.isVisibleTo(self)
                                      and box.currentText() != _ANCHOR_OP)
        anchored = _ANCHOR_OP in ops
        self.anchor_label.setVisible(anchored)
        if anchored:
            self.anchor_label.setText(self._anchor_preview_text())

    def calendar_for(self, field):
        """The calendar button beside operand `field`, or None."""
        return self._calendars.get(id(field))

    def _anchor_preview_text(self):
        """The window "in the last N days" will measure: back from the
        newest non-blank value this column holds, across every row, not
        from today. A preview only: RecordFilter resolves the anchor itself
        whenever the condition is attached or the rows change
        (RecordFilter._recompute)."""
        newest = self.model.filter.newest_value(self.column.key)
        if newest is None:
            return ("No dated value found in %s -- \"in the last N days\" "
                    "will match nothing until one is." % self.column.label)
        return ('Anchored to the newest %s in this column: %s '
                "(not today's date)."
                % (self.column.label, format_dt(newest)))

    def _condition_rows(self):
        return ((self.operator_box, self.operand_a, self.operand_b),
                (self.operator_box_2, self.operand_a_2, self.operand_b_2))

    def _row_condition(self, box, a, b):
        op = box.currentText()
        if op == NO_CONDITION:
            return None
        if op not in _NO_OPERAND and not a.text().strip():
            return None
        return Condition(op, a.text().strip() or None,
                         b.text().strip() or None,
                         case_sensitive=self._case_sensitive)

    def chosen_condition(self):
        """The first row's condition, the second's, or both joined by the
        And/Or between them -- whichever rows are filled."""
        first, second = (self._row_condition(*row)
                         for row in self._condition_rows())
        if first is None or second is None:
            return first or second
        return JoinedCondition(first, self.join_box.currentText().lower(),
                               second)

    # --- apply ---------------------------------------------------------------

    def apply(self):
        ops = [box.currentText() for box, _a, _b in self._condition_rows()]
        if any(box.currentText() == "between" and a.text().strip()
               and not b.text().strip()
               for box, a, b in self._condition_rows()):
            # Condition accepts a one-sided "between", which then matches
            # no row. Only the popup can tell an unfinished second value
            # from a finished, invalid one, so it refuses and says why
            # rather than applying a condition that cannot match.
            self._set_status('"between" needs a second value too.')
            return False
        cond = self.chosen_condition()
        if cond is not None and cond.error:
            self._set_status("Invalid regex: %s" % cond.error
                             if "matches regex" in ops
                             else "Invalid filter: %s" % cond.error)
            return False
        # One step, both halves or neither: committing the
        # values and then the condition left the values applied when the
        # condition raised. The exception is shown here rather than let
        # out of this slot, where PySide prints it and the examiner sees
        # nothing; the model has already rolled back.
        try:
            self.model.set_column_filter(
                self.column.key, self.chosen_values(), cond)
        except Exception as exc:                       # noqa: BLE001
            self._set_status("The filter could not be applied: %s" % exc)
            return False
        if self.model.rowCount() == 0:
            # emptied_by() returns a bare column key ("Domain") when one
            # kind of filter is active on this column, or a qualified one
            # ("Domain (values)" / "Domain (condition)") when both are; it
            # is printed as returned.
            culprit = self.model.filter.emptied_by()
            if culprit:
                self._set_status("No rows match %s." % culprit)
        else:
            self._set_status("")
        self.filterApplied.emit()
        return True

    def _ok(self):
        if self.apply():
            self.accept()

    # --- non-modal close-on-focus-out -----------------------------------

    def _belongs_here(self, widget):
        """True when `widget` (newly focused, from
        QApplication.focusChanged) is part of this dialog: a child widget,
        or a widget in a window Qt marks as transiently owned by this
        dialog's window.

        The second case covers a QComboBox's drop-down list (operator_box's),
        which is not a descendant of this dialog in the widget tree, though
        its window's transientParent is this dialog's window
        (_window_belongs_here). Without it, opening the operator drop-down
        would close the popup.
        """
        if widget is self or self.isAncestorOf(widget):
            return True
        top = widget.window()
        return self._window_belongs_here(top.windowHandle() if top else None)

    def _window_belongs_here(self, window):
        """True when `window` is this dialog's own window, or is owned by
        it through Qt's own transientParent chain (see _belongs_here) --
        a QComboBox's drop-down container is one hop up that chain, and
        nothing this dialog opens is ever more than one hop."""
        my_window = self.windowHandle()
        seen = window
        while seen is not None:
            if seen is my_window:
                return True
            seen = seen.transientParent()
        return False

    def _on_focus_changed(self, old, new):
        """Close the popup when focus leaves it for another window, as a
        QComboBox drop-down or QMenu does, since a non-modal popup is
        otherwise never closed.

        `new` is None during a transient hand-off (Qt clears the focus
        widget briefly during some window activations) and is ignored. See
        _belongs_here for what else is ignored.

        This fires only for widgets that accept keyboard focus. The
        sidebar's nav list is Qt.NoFocus (sidebar.py), so a click there is
        caught by _on_focus_window_changed below.
        """
        if not self.isVisible():
            return
        if new is None or self._belongs_here(new):
            return
        # Cancels rather than applies, as Escape does: clicking elsewhere
        # is not OK, and nothing unapplied reaches the live filter.
        self.reject()

    def _on_focus_window_changed(self, window):
        """The complement to _on_focus_changed above: window ACTIVATION,
        not widget focus. Any click inside another top-level window
        activates it at the OS level regardless of which specific child
        widget the click landed on -- including a Qt.NoFocus one, like
        the sidebar's nav list, which never fires focusChanged at all.
        `window` is None for the app losing OS focus entirely (e.g. an
        alt-tab to a different application), which must not discard a
        mid-edit popup any more than a purely transient focusChanged(None)
        does above."""
        if not self.isVisible() or window is None:
            return
        if self._window_belongs_here(window):
            return
        self.reject()
