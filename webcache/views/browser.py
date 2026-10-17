"""Table Browser: raw ESE tables as stored, with no interpretation
applied.

A master/detail view rather than a RecordsView: a raw table has no shared
row shape, and pages are loaded one at a time rather than holding a whole
result set in a model. It uses the same ViewHeader/CaveatLine chrome and
refresh_theme() hook.

Left: a filterable, grouped list of every table (table_browser_loader.
grouped_tables(), from ese_parser.get_table_type()'s classification, so a
table's group matches how the rest of the application labels it). A
QListWidget, styled by theme.py's QSS like the sidebar. Group headers are
non-selectable rows (_populate_table_list), so a click always lands on a
table.

Right: the selected table's columns (the grid's header row), its type,
its cached row count, its cache directory for a Container_<id> table
(table_browser_loader._directory_for_table), and one page of rows from
table_browser_loader.table_page(). Each cell shows the stored type and the
raw rendering: hex for binary, escaped for text, the plain number for an
integer that resembles a FILETIME.

select_table(name) is the drill target from Containers
(MainWindow._drill_container_to_browser): it opens that container's table,
clears a filter that would hide it, and states "no such table" for a
container whose Container_<id> table does not exist (HasTable False; see
ese_parser._load_containers).
"""
from PySide6.QtCore import QItemSelectionModel, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QComboBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QPushButton, QSizePolicy, QSplitter,
                               QStyleOptionViewItem, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..shell import glyphs, table_browser_loader, theme
from ..widgets import copyable
from ..widgets.content_header import CaveatLine, ViewHeader
# RecordsTable's TSV-safety rule (records_table.py), so a tab or newline
# in a raw stored value does not misalign a pasted rectangle.
from ..widgets.records_table import (MAX_AUTO_COLUMN_PX, ROW_LINE_CAP,
                                     WrappingDelegate, _tsv_safe)
from ..widgets.column_spec import Column
from ..widgets.filter_popup import FilterPopup
from ..widgets.record_model import RecordTableModel
from ..widgets.whole_value import WholeValueWindow

_NO_EVIDENCE_TEXT = "No evidence loaded yet. Open evidence to browse its tables."
_NO_SELECTION_TEXT = "Select a table on the left to view its rows."
#: A leaf item's row count, for the empty-table dimming and filter.
_COUNT_ROLE = Qt.UserRole + 1

#: The row filter's scope when no one column is chosen.
ALL_COLUMNS = "All columns"
_ROW_FILTER_DEBOUNCE_MS = 250


def _alive(widget):
    try:
        widget.isVisible()
        return True
    except RuntimeError:
        return False


class _CopyableTableWidget(QTableWidget):
    """A QTableWidget claims QKeySequence.Copy for itself through Qt's
    ShortcutOverride, so a QShortcut for Copy on it never fires, and its
    built-in copy takes only the current cell's text.

    keyPressEvent is overridden to accept the event and emit
    copyRequested, so the grid copies a selection as headed TSV like
    RecordsTable. Emitting a signal keeps this widget independent of its
    parent.
    """
    copyRequested = Signal()
    #: Enter/Return on the current row. QAbstractItemView's own
    #: `activated` signal is platform-conditional (on Windows it fires
    #: for double-click but not reliably for Return on a view with
    #: NoEditTriggers), so the key is handled here for the same reason
    #: copyRequested exists: what this grid does must not depend on which
    #: keys Qt happens to claim first.
    rowActivated = Signal()
    #: A click on a capped cell's "+N more lines" marker: (row, column).
    wholeValueRequested = Signal(int, int)

    def marker_rect(self, index):
        """The row cap's marker for a cell, in viewport coordinates, or
        None when the cell shows its whole value -- see
        records_table.WrappingDelegate."""
        delegate = self.itemDelegate()
        if not index.isValid() or not self.wordWrap() or not isinstance(
                delegate, WrappingDelegate):
            return None
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = self.visualRect(index)
        return delegate.marker_rect(option, index)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            marker = self.marker_rect(index)
            if marker is not None and marker.contains(pos):
                self.setCurrentIndex(index)
                self.wholeValueRequested.emit(index.row(), index.column())
                event.accept()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self.copyRequested.emit()
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.rowActivated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class TableBrowserView(QWidget):
    #: A binary cell's bytes were requested: (column name, bytes). The
    #: shell decides that this opens the blob viewer, and builds the
    #: BlobSource.
    blobRequested = Signal(str, object)
    #: One whole row was requested, as a payload the shell passes to
    #: TableRowDialog: table, row_number, row_count, columns and the row's
    #: raw cells.
    rowRequested = Signal(object)

    def __init__(self, parent=None, page_size=None):
        super().__init__(parent)
        self._parser = None
        self._current_table = None
        self._offset = 0
        #: The current page's columns and RAW cells -- see _render_page.
        self._page_columns = []
        self._page_rows = []
        #: The whole table's row count, not this page's -- the row view
        #: says "row 3 of 12,408", and on page two the third row on
        #: screen is not row 3.
        self._row_count = 0
        #: (header_item, [leaf_item, ...]) pairs -- see _populate_table_
        #: list and _apply_filter, which both need to know a group's own
        #: children without re-walking the whole QListWidget by index.
        self._groups = []
        self._page_size = page_size or table_browser_loader.DEFAULT_PAGE_SIZE
        #: The row filter and sort, over the WHOLE open table: its raw rows
        #: (loaded on first use), each row's lower-cased cell texts, and the
        #: matching rows' table ordinals in display order -- None while
        #: neither a filter nor a sort is in force, when paging reads the
        #: table straight through as before.
        self._all_columns = None
        self._all_rows = None
        self._row_texts = None
        #: Each row's cell texts as shown (not lower-cased), for the
        #: column filters' value lists.
        self._display_texts = None
        #: The column filters: a RecordTableModel over the open table's
        #: shown texts, used only as the filter engine behind the heading
        #: popups (the grid stays this view's own). None until a heading
        #: filter is first opened for this table.
        self._column_model = None
        self._column_popup = None
        self._view_ordinals = None
        self._sort = None
        #: The table ordinal of each row on the current page.
        self._page_ordinals = []

        self.header = ViewHeader("database", "Table Browser")
        self.caveat = CaveatLine()

        self.filter_box = QLineEdit(placeholderText="Filter tables…")
        self._funnel_action = self.filter_box.addAction(
            glyphs.icon("funnel", theme.color("primary"), 15),
            QLineEdit.LeadingPosition)
        self.filter_box.textChanged.connect(self._apply_filter)

        self.table_list = QListWidget()
        self.table_list.currentItemChanged.connect(self._on_selection_changed)

        left = QWidget()
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.addWidget(self.filter_box)
        self.list_summary = copyable.selectable(QLabel(""))
        self.list_summary.setStyleSheet(
            "background: transparent; font-size: 11px;")
        left_col.addWidget(self.list_summary)
        # Off by default: the list is the whole database, empty tables
        # included. On, it keeps only the tables that hold rows.
        self.hide_empty_box = QCheckBox("Hide empty tables")
        self.hide_empty_box.toggled.connect(
            lambda _on: self._apply_filter(self.filter_box.text()))
        left_col.addWidget(self.hide_empty_box)
        left_col.addWidget(self.table_list, 1)

        self._info_label = copyable.selectable(QLabel(_NO_EVIDENCE_TEXT))
        self._info_label.setWordWrap(True)
        self._directory_label = QLabel("")
        self._directory_label.setWordWrap(True)
        copyable.selectable(self._directory_label)
        self._directory_label.setVisible(False)
        #: Why the browser was opened where it was: a row being located, a
        #: deleted row, or a key not found. Cleared when another table is
        #: loaded or picked from the list.
        self._note_label = copyable.selectable(QLabel(""))
        self._note_label.setWordWrap(True)
        self._note_label.setVisible(False)

        self.grid = _CopyableTableWidget()
        # theme.py's QTableView#browserGrid rules: a visible selection.
        self.grid.setObjectName("browserGrid")
        self.grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid.setAlternatingRowColors(True)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.grid.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.grid.horizontalHeader().setStretchLastSection(False)
        # The shared evidence delegate and Wrap setting: a raw value
        # wraps, its row stops at the cap, and a capped cell shows
        # "+N more lines".
        self._grid_wrap = True
        self.grid.setItemDelegate(
            WrappingDelegate(self.grid, line_cap=ROW_LINE_CAP))
        self.grid.setWordWrap(True)
        self.grid.setTextElideMode(Qt.ElideNone)
        self.grid.wholeValueRequested.connect(self.show_whole_value)
        self._whole_value_windows = []
        # A column resized by hand re-wraps its values.
        self._row_fit_timer = QTimer(self)
        self._row_fit_timer.setSingleShot(True)
        self._row_fit_timer.setInterval(30)
        self._row_fit_timer.timeout.connect(self._fit_rows)
        self.grid.horizontalHeader().sectionResized.connect(
            lambda *_a: self._row_fit_timer.start() if self._grid_wrap else None)
        # Raw stored values are copied, never opened (paths belong to the
        # examined machine). Ctrl+C and the context menu copy as in
        # RecordsTable (records_table.py), except that there is no Origin
        # column to append: nothing here is carved. copyRequested is used
        # instead of a QShortcut (see _CopyableTableWidget).
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_context_menu)
        self.grid.copyRequested.connect(self._copy_grid_selection)
        # Every route an examiner might try to the row view: every column
        # of one row, each value whole.
        self.grid.rowActivated.connect(self._open_current_row)
        self.grid.itemDoubleClicked.connect(
            lambda item: self.open_row(item.row()))
        self.grid.currentCellChanged.connect(
            lambda r, *_a: self.view_row_button.setEnabled(
                0 <= r < len(self._page_rows)))

        # Visible routes to what Enter and double-click do.
        self.view_row_button = QPushButton("View whole row…")
        self.view_row_button.setToolTip(
            "Show every column of the selected row, one per line, with "
            "the whole value (Enter, or double-click a row)")
        self.view_row_button.setEnabled(False)
        self.view_row_button.clicked.connect(self._open_current_row)

        self.prev_button = QPushButton("◀ Previous")
        self.next_button = QPushButton("Next ▶")
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.prev_button.clicked.connect(self._go_previous_page)
        self.next_button.clicked.connect(self._go_next_page)
        self._page_label = copyable.selectable(QLabel(""))

        pager = QHBoxLayout()
        pager.addWidget(self.view_row_button)
        pager.addSpacing(12)
        pager.addWidget(self.prev_button)
        pager.addWidget(self._page_label, 1, Qt.AlignCenter)
        pager.addWidget(self.next_button)

        # Filters the rows of the open table: every row, not only the page
        # on screen.
        self.row_filter_column = QComboBox()
        self.row_filter_column.setToolTip("Which column the row filter reads")
        self.row_filter_column.addItem(ALL_COLUMNS)
        self.row_filter_column.currentIndexChanged.connect(
            lambda _i: self.apply_row_filter_now())
        self.row_filter_box = QLineEdit(
            placeholderText="Filter rows of this table — every row, as shown; "
                            "dates match decoded times")
        self._row_funnel = self.row_filter_box.addAction(
            glyphs.icon("funnel", theme.color("primary"), 15),
            QLineEdit.LeadingPosition)
        self.row_filter_box.setClearButtonEnabled(True)
        self._row_filter_timer = QTimer(self)
        self._row_filter_timer.setSingleShot(True)
        self._row_filter_timer.setInterval(_ROW_FILTER_DEBOUNCE_MS)
        self._row_filter_timer.timeout.connect(self.apply_row_filter_now)
        self.row_filter_box.textChanged.connect(
            lambda _t: self._row_filter_timer.start())
        self.row_filter_box.returnPressed.connect(self.apply_row_filter_now)
        self.clear_rows_button = QPushButton("Clear filter and sort")
        self.clear_rows_button.setEnabled(False)
        self.clear_rows_button.clicked.connect(lambda: self.clear_row_view())
        row_bar = QHBoxLayout()
        row_bar.addWidget(self.row_filter_column)
        row_bar.addWidget(self.row_filter_box, 1)
        row_bar.addWidget(self.clear_rows_button)
        self.row_count_label = copyable.selectable(QLabel(""))
        self.row_count_label.setVisible(False)
        self._set_row_controls_enabled(False, "Select a table first.")

        # A click on a heading sorts the whole table; again, the other way.
        header = self.grid.horizontalHeader()
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._heading_clicked)
        # A right-click on a heading filters that column, as on every
        # record grid.
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(
            lambda pos: self.open_column_filter(header.logicalIndexAt(pos)))
        header.setToolTip("Click to sort the whole table; right-click to "
                          "filter this column")

        right = QWidget()
        right_col = QVBoxLayout(right)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.addWidget(self._info_label)
        right_col.addWidget(self._directory_label)
        right_col.addWidget(self._note_label)
        right_col.addLayout(row_bar)
        right_col.addWidget(self.row_count_label)
        right_col.addWidget(self.grid, 1)
        right_col.addLayout(pager)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 1000])

        root = QVBoxLayout(self)
        root.addWidget(self.header)
        root.addWidget(self.caveat)
        root.addWidget(splitter, 1)

        self.refresh_theme()

    def focus_target(self):
        """Arriving here, keys go to the rows when a table is open, else
        to the list of tables -- never to a text box, which would swallow
        Back (Alt+Left, Backspace)."""
        return self.grid if self._current_table is not None else self.table_list

    # --- Wrap: the same switch as every record grid ---------------------

    def set_wrap(self, on):
        """MainWindow.set_grid_wrap reaches here too. Off: one line per
        row, elided at the cell edge, as the record grids do."""
        self._grid_wrap = bool(on)
        self.grid.setWordWrap(self._grid_wrap)
        self.grid.setTextElideMode(Qt.ElideNone if self._grid_wrap else Qt.ElideRight)
        self._fit_rows()

    def is_wrapping(self):
        return self._grid_wrap

    def _fit_rows(self):
        """Every row of the page to its content, under the row cap -- the
        page is bounded by DEFAULT_PAGE_SIZE, so measuring all of it is
        cheap. Wrap off: every row back to one line."""
        vheader = self.grid.verticalHeader()
        if self._grid_wrap:
            self.grid.resizeRowsToContents()
        else:
            for row in range(self.grid.rowCount()):
                vheader.resizeSection(row, vheader.defaultSectionSize())

    def grid_cell_is_capped(self, row, col):
        return self.grid.marker_rect(self.grid.model().index(row, col)) is not None

    def show_whole_value(self, row, col):
        """The "Whole value" window for one cell: the whole stored value
        (every byte as hex, for a binary cell), and a Copy of it."""
        text = self._grid_cell_text(row, col)
        heading = "%s, %s row %s" % (
            self._grid_header_label(col), self._current_table or "",
            format(self._table_row_number(row), ","))
        window = WholeValueWindow(text, text, heading, self.window())
        self._whole_value_windows = [
            w for w in self._whole_value_windows if _alive(w)] + [window]
        window.show()
        return window

    # --- caveat / theme -----------------------------------------------

    def set_caveat(self, text):
        self.caveat.set_text(text)

    def refresh_theme(self):
        """Repaint for the current theme. The table list is rebuilt (group
        header colours are set when built), keeping the table, page and
        filter on screen."""
        self.header.refresh_theme()
        self.caveat.refresh_theme()
        self._funnel_action.setIcon(glyphs.icon("funnel", theme.color("primary"), 15))
        current_table, offset, filter_text = (
            self._current_table, self._offset, self.filter_box.text())
        self._populate_table_list()
        if filter_text:
            self.filter_box.setText(filter_text)
        if self._parser is None:
            self._render_no_selection()
        elif current_table is not None:
            self._select_list_item(current_table)
            self._load_table(current_table, offset)
        else:
            self._render_no_selection()

    # --- parser lifecycle ---------------------------------------------

    def set_parser(self, parser):
        """A fresh Open Evidence must never leave a PREVIOUS exhibit's
        table selection on screen -- the same "reset, don't inherit"
        discipline RecordsView._switch_segment already applies to
        filters, one view over."""
        self._parser = parser
        self._current_table = None
        self._offset = 0
        self.filter_box.blockSignals(True)
        self.filter_box.clear()
        self.filter_box.blockSignals(False)
        self._populate_table_list()
        self._render_no_selection()

    def select_table(self, table_name):
        """The Containers-drill target -- see the module docstring."""
        if self._parser is None:
            return
        self.set_note("")
        self.filter_box.blockSignals(True)
        self.filter_box.clear()
        self.filter_box.blockSignals(False)
        self._apply_filter("")
        if self._select_list_item(table_name):
            self._load_table(table_name, offset=0)  # _select_list_item never loads -- see its own docstring
            # From the top: grid.clear() keeps the scroll position, and a
            # table re-opened after a landed row came up scrolled to
            # where that row had been, reading as if it pointed somewhere.
            self.grid.scrollToTop()
        else:
            self._render_missing_table(table_name)

    # --- the left panel: grouped, filterable table list -----------------

    def _populate_table_list(self):
        self.table_list.clear()
        self._groups = []
        self._tables = []
        self.list_summary.setText("")
        if self._parser is None:
            return
        for group_name, tables in table_browser_loader.grouped_tables(self._parser):
            header_item = QListWidgetItem(group_name)
            font = header_item.font()
            font.setBold(True)
            header_item.setFont(font)
            # Enabled (so it does not read as greyed-out/disabled) but not
            # selectable -- a click can only ever land on a real table.
            header_item.setFlags(Qt.ItemIsEnabled)
            header_item.setForeground(theme.color("muted"))
            self.table_list.addItem(header_item)

            leaf_items = []
            for info in tables:
                count = info.get("count", -1)
                count_text = format(count, ",") if count >= 0 else "?"
                item = QListWidgetItem(
                    "    %s (%s)" % (info["display_name"], count_text))
                item.setData(Qt.UserRole, info["name"])
                item.setData(_COUNT_ROLE, count)
                if count == 0:
                    # Dimmed, not removed, so empty tables are easy to tell
                    # apart.
                    item.setForeground(theme.color("muted"))
                    item.setToolTip("This table holds no rows.")
                self.table_list.addItem(item)
                leaf_items.append(item)
                self._tables.append((info["name"], count))
            self._groups.append((header_item, leaf_items))
        total = len(self._tables)
        with_rows = sum(1 for _n, c in self._tables if c and c > 0)
        self.list_summary.setText("%s tables in %s groups · %s of %s hold rows"
                                  % (format(total, ","), len(self._groups),
                                     format(with_rows, ","), format(total, ",")))

    def _apply_filter(self, text):
        needle = (text or "").strip().lower()
        hide_empty = self.hide_empty_box.isChecked()
        for header_item, leaf_items in self._groups:
            any_visible = False
            for item in leaf_items:
                visible = ((not needle or needle in item.text().lower())
                           and not (hide_empty and item.data(_COUNT_ROLE) == 0))
                item.setHidden(not visible)
                any_visible = any_visible or visible
            header_item.setHidden(not any_visible)

    def _select_list_item(self, table_name):
        """Highlight `table_name` in the list without loading it. Used by
        programmatic selections (select_table(), refresh_theme()), which set
        their own offset; signals are blocked so _on_selection_changed,
        which would reset the offset to 0, runs only for a real click."""
        for _header, leaf_items in self._groups:
            for item in leaf_items:
                if item.data(Qt.UserRole) == table_name:
                    item.setHidden(False)
                    self.table_list.blockSignals(True)
                    self.table_list.setCurrentItem(item)
                    self.table_list.blockSignals(False)
                    return True
        return False

    def _on_selection_changed(self, current, _previous):
        if current is None or current.data(Qt.UserRole) is None:
            return  # a group-header row, or the selection was cleared
        self._load_table(current.data(Qt.UserRole), offset=0)

    # --- the right panel: table info + one page of raw rows -------------

    def _load_table(self, table_name, offset):
        # Paging, or a theme refresh reloading the same table, keeps the
        # note: it still describes the table on screen.
        if table_name != self._current_table:
            self.set_note("")
            self._reset_row_view(table_name)
        self._current_table = table_name
        self._offset = offset
        if self._view_ordinals is not None:
            page = table_browser_loader.page_of_rows(
                self._parser, table_name, self._all_columns, self._all_rows,
                self._view_ordinals, offset, self._page_size)
        else:
            page = table_browser_loader.table_page(
                self._parser, table_name, offset=offset, limit=self._page_size)
        self._render_page(page)

    # --- the row filter and heading sort: the whole table -----------------

    def _set_row_controls_enabled(self, on, reason=""):
        for widget in (self.row_filter_box, self.row_filter_column):
            widget.setEnabled(on)
        self.row_filter_box.setToolTip(
            reason or "Every row of this table, every column as shown. A "
            "time column also matches its decoded reading, so a date finds "
            "the rows of that date.")

    def _reset_row_view(self, table_name):
        """A different table: no filter, no sort, nothing held."""
        self._all_columns = self._all_rows = self._row_texts = None
        self._display_texts = None
        self._drop_column_filters()
        self._view_ordinals = None
        self._sort = None
        self._row_filter_timer.stop()
        for widget in (self.row_filter_box, self.row_filter_column):
            widget.blockSignals(True)
        self.row_filter_box.clear()
        self.row_filter_column.clear()
        self.row_filter_column.addItem(ALL_COLUMNS)
        for widget in (self.row_filter_box, self.row_filter_column):
            widget.blockSignals(False)
        self.grid.horizontalHeader().setSortIndicatorShown(False)
        self.row_count_label.setVisible(False)
        self.clear_rows_button.setEnabled(False)
        if self._parser is None or table_name is None:
            self._set_row_controls_enabled(False, "Select a table first.")
            return
        # Every table is filtered and sorted whole, however large.
        count = self._parser.get_table_row_count(table_name)
        self._set_row_controls_enabled(
            count > 0, "" if count > 0 else "This table holds no rows.")

    def _ensure_all_rows(self):
        if self._all_rows is None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._all_columns, rows = table_browser_loader.all_rows(
                    self._parser, self._current_table)
                self._all_rows = list(rows)
            finally:
                QApplication.restoreOverrideCursor()
        return self._all_rows

    def _ensure_row_texts(self):
        if self._row_texts is None:
            rows = self._ensure_all_rows()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._display_texts = [
                    list(table_browser_loader.row_texts(
                        self._parser, self._current_table,
                        self._all_columns, row))
                    for row in rows]
                self._row_texts = [[t.lower() for t in texts]
                                   for texts in self._display_texts]
            finally:
                QApplication.restoreOverrideCursor()
        return self._row_texts

    def apply_row_filter_now(self):
        """Filter, then sort, the whole open table and show page one."""
        self._row_filter_timer.stop()
        if self._parser is None or self._current_table is None:
            return
        needle = self.row_filter_box.text().strip().lower()
        columns_on = (self._column_model is not None
                      and self._column_model.filter.has_filters())
        if not needle and self._sort is None and not columns_on:
            if self._view_ordinals is not None:
                self.clear_row_view()
            return
        rows = self._ensure_all_rows()
        ordinals = list(range(len(rows)))
        scope = self.row_filter_column.currentIndex() - 1
        if needle:
            texts = self._ensure_row_texts()
            if scope >= 0:
                ordinals = [i for i in ordinals
                            if scope < len(texts[i]) and needle in texts[i][scope]]
            else:
                ordinals = [i for i in ordinals
                            if any(needle in t for t in texts[i])]
        if columns_on:
            kept = {row["_ordinal"]
                    for row in self._column_model.filter.visible()}
            ordinals = [i for i in ordinals if i in kept]
        if self._sort is not None:
            col, descending = self._sort

            def value(i):
                row = rows[i]
                return row[col] if col < len(row) else None
            blank = [i for i in ordinals if value(i) in (None, b"", "")]
            filled = [i for i in ordinals if value(i) not in (None, b"", "")]
            filled.sort(key=lambda i: table_browser_loader.sort_key(value(i)),
                        reverse=descending)
            ordinals = filled + blank
        self._view_ordinals = ordinals
        self.clear_rows_button.setEnabled(True)
        self._say_row_view(needle, scope)
        self._load_table(self._current_table, 0)
        self.grid.scrollToTop()

    def _say_row_view(self, needle, scope):
        total = len(self._all_rows or ())
        parts = []
        columns_on = (self._column_model is not None
                      and self._column_model.filter.has_filters())
        if columns_on and not needle:
            shown = len(self._view_ordinals)
            parts.append("%s of %s rows%s" % (
                format(shown, ","), format(total, ","),
                "" if shown else ". Clear the filter to see every row"))
        if columns_on:
            parts.append("filtered: %s" % self._column_model.filter.chip_text())
        if needle:
            where = ("" if scope < 0 else " in %s"
                     % self.row_filter_column.currentText())
            said = self.row_filter_box.text().strip()
            shown = len(self._view_ordinals)
            if shown:
                parts.append("%s of %s rows match \u201c%s\u201d%s"
                             % (format(shown, ","), format(total, ","),
                                said, where))
            else:
                parts.append("No row of this table's %s matches "
                             "\u201c%s\u201d%s. Clear the filter to see every row."
                             % (format(total, ","), said, where))
        if self._sort is not None:
            col, descending = self._sort
            name = (self._all_columns[col] if self._all_columns
                    and col < len(self._all_columns) else "column")
            parts.append("sorted by %s, %s" % (
                name, "descending" if descending else "ascending"))
        text = " \u00b7 ".join(parts)
        self.row_count_label.setText(text[:1].upper() + text[1:])
        self.row_count_label.setVisible(bool(text))

    def sort_rows_by(self, column, descending=False):
        """Sort the whole open table by one column (blanks last)."""
        if self._current_table is None or not self.row_filter_box.isEnabled():
            return
        self._sort = (column, bool(descending))
        header = self.grid.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(
            column, Qt.DescendingOrder if descending else Qt.AscendingOrder)
        self.apply_row_filter_now()

    def _heading_clicked(self, column):
        same = self._sort is not None and self._sort[0] == column
        self.sort_rows_by(column, descending=same and not self._sort[1])

    # --- column filters ----------------------------------------------------

    def _ensure_column_model(self):
        if self._column_model is None:
            self._ensure_row_texts()
            columns = [Column(name, name, 140, kind="text")
                       for name in self._all_columns]
            rows = []
            for i, texts in enumerate(self._display_texts):
                row = {name: (texts[c] if c < len(texts) else "")
                       for c, name in enumerate(self._all_columns)}
                row["_ordinal"] = i
                rows.append(row)
            self._column_model = RecordTableModel(columns, rows, self)
        return self._column_model

    def open_column_filter(self, section):
        """The filter popup for column `section`, over every row of the
        open table. Returns the popup, or None when this table cannot be
        filtered (none open, empty, or too large to hold)."""
        if (section is None or section < 0 or self._current_table is None
                or not self.row_filter_box.isEnabled()):
            return None
        model = self._ensure_column_model()
        if section >= len(model.columns):
            return None
        self._close_column_popup()
        popup = FilterPopup(model, model.columns[section], self)
        popup.filterApplied.connect(self.apply_row_filter_now)
        self._column_popup = popup
        popup.show()
        return popup

    def _close_column_popup(self):
        popup, self._column_popup = self._column_popup, None
        if popup is not None:
            popup.close()
            popup.deleteLater()

    def _drop_column_filters(self):
        self._close_column_popup()
        if self._column_model is not None:
            self._column_model.deleteLater()
        self._column_model = None

    def clear_row_view(self):
        """Back to the table as stored, from row 1."""
        self._row_filter_timer.stop()
        if self._column_model is not None:
            self._close_column_popup()
            self._column_model.clear_all()
        self._view_ordinals = None
        self._sort = None
        self.row_filter_box.blockSignals(True)
        self.row_filter_box.clear()
        self.row_filter_box.blockSignals(False)
        self.grid.horizontalHeader().setSortIndicatorShown(False)
        self.row_count_label.setVisible(False)
        self.clear_rows_button.setEnabled(False)
        if self._current_table is not None:
            self._load_table(self._current_table, 0)

    def _render_page(self, page):
        directory = page["directory"]
        self._info_label.setText(
            "%s  ·  Type: %s  ·  %s column(s)  ·  %s row(s)"
            % (page["display_name"], page["type"], len(page["columns"]),
               format(page["row_count"], ",")))
        if directory:
            self._directory_label.setText("Cache directory: %s" % directory)
            self._directory_label.setVisible(True)
        else:
            self._directory_label.setText("")
            self._directory_label.setVisible(False)

        columns, rows = page["columns"], page["rows"]
        # Kept so a cell's raw bytes can be reached after the grid has
        # rendered them to text (table_browser_loader carries "raw" per
        # cell). Bounded by one page (DEFAULT_PAGE_SIZE) and replaced on
        # the next.
        self._page_columns = list(columns)
        self._page_rows = rows
        self._row_count = page["row_count"]
        self.grid.clear()
        # Rows dropped first: setRowCount keeps a surviving row's height,
        # and a row grown for the previous page's value would stay tall.
        self.grid.setRowCount(0)
        self.grid.setColumnCount(len(columns))
        self.grid.setHorizontalHeaderLabels(columns)
        self.grid.setRowCount(len(rows))
        # Numbered through the TABLE, not the page: the header, the pager
        # ("Rows 401-450") and a landed row's note ("Row 438") must all
        # name the same row by the same number.
        offset = page["offset"]
        self._page_ordinals = list(page.get("ordinals")
                                   or range(offset, offset + len(rows)))
        self.grid.setVerticalHeaderLabels(
            [str(o + 1) for o in self._page_ordinals])
        # The scope list names this table's own columns, once per table.
        if self.row_filter_column.count() != len(columns) + 1:
            self.row_filter_column.blockSignals(True)
            self.row_filter_column.clear()
            self.row_filter_column.addItem(ALL_COLUMNS)
            self.row_filter_column.addItems([str(c) for c in columns])
            self.row_filter_column.blockSignals(False)
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                item = QTableWidgetItem(cell["text"])
                # The only route to the blob
                # viewer here is the right-click "View these bytes..."
                # action (_build_grid_context_menu below), and nothing
                # marked which cells offer it -- every tooltip read "stored
                # as: <type>", the same shape whether or not right-clicking
                # did anything more than any other cell. A binary cell
                # renders its first bytes and a marker naming the rest
                # (table_browser_loader.grid_hex); the tooltip says how to
                # see them.
                if isinstance(cell.get("raw"), (bytes, bytearray)) and len(cell["raw"]):
                    item.setToolTip(
                        "stored as: %s — right-click to view these bytes "
                        "(hex and strings), or Enter for the whole row"
                        % cell["type"])
                else:
                    # The cell holds the whole value; a long one is capped
                    # on screen with a marker, and the tooltip names both
                    # routes to all of it.
                    decoded = cell.get("decoded") or ""
                    item.setToolTip(
                        ("decoded: %s\n" % decoded if decoded else "")
                        + "stored as: %s — Enter for the whole row, every "
                        "column and the whole value; click a “more lines” "
                        "marker for this value alone" % cell["type"])
                self.grid.setItem(r, c, item)
        self.grid.resizeColumnsToContents()
        # Measured, then capped: a long value wraps in a column no wider
        # than the widest declared text column.
        header = self.grid.horizontalHeader()
        for c in range(self.grid.columnCount()):
            if header.sectionSize(c) > MAX_AUTO_COLUMN_PX:
                header.resizeSection(c, MAX_AUTO_COLUMN_PX)
        self._row_fit_timer.stop()
        self._fit_rows()

        total, offset, limit = page["row_count"], page["offset"], page["limit"]
        listed = page.get("matches", total)
        shown = len(rows)
        start = offset + 1 if shown else 0
        end = offset + shown
        if listed != total:
            self._page_label.setText(
                "Rows %s–%s of %s matching · %s in the table"
                % (format(start, ","), format(end, ","), format(listed, ","),
                   format(total, ",")))
        else:
            self._page_label.setText(
                "Rows %s–%s of %s" % (format(start, ","), format(end, ","),
                                      format(total, ",")))
        self.prev_button.setEnabled(offset > 0)
        self.next_button.setEnabled(offset + limit < listed)
        # grid.clear() drops the current cell without emitting
        # currentCellChanged in every case, so the button is re-stated
        # from the page rather than left saying whatever the previous
        # table's selection said.
        self.view_row_button.setEnabled(
            0 <= self.grid.currentRow() < len(rows))

    def set_note(self, text):
        self._note_label.setText(text or "")
        self._note_label.setVisible(bool(text))

    def show_row(self, table_name, ordinal, page=None):
        """Open `table_name` on the page holding table row `ordinal`
        (0-based, as WebCacheParser.find_row_ordinal counts), select that
        row and scroll it into view. False if it cannot.

        `page` is that page already fetched (table_browser_loader.
        table_page) by the off-thread locate, so the GUI thread does not
        walk a large table a second time to reach the same offset."""
        if self._parser is None or ordinal is None or ordinal < 0:
            return False
        # A drill lands on the table as stored: a filter or sort left from
        # earlier would hide the row or move it off its page.
        if self._view_ordinals is not None or self._sort is not None:
            self.clear_row_view()
        offset = (ordinal // self._page_size) * self._page_size
        prefetched = (isinstance(page, dict)
                      and page.get("table") == table_name
                      and page.get("offset") == offset)
        if self._current_table != table_name or not prefetched:
            self.select_table(table_name)
            if self._current_table != table_name:
                return False
        if prefetched:
            self._offset = offset
            self._render_page(page)
        elif offset != self._offset:
            self._load_table(table_name, offset)
        row = ordinal - offset
        if not (0 <= row < self.grid.rowCount()):
            return False
        # ClearAndSelect|Rows, never setCurrentCell alone: with Ctrl held
        # (or believed held) that EXTENDS the selection.
        self.grid.setCurrentCell(row, 0, QItemSelectionModel.ClearAndSelect
                                 | QItemSelectionModel.Rows)
        self._center_row(row)
        # Again after the event loop has laid the view out: a browser that
        # was hidden until now would centre against a stale viewport
        # height.
        QTimer.singleShot(0, lambda r=row, t=table_name, o=offset:
                          self._center_row(r) if (self._current_table, self._offset)
                          == (t, o) else None)
        # Focused, so the selection paints in the active highlight rather
        # than the faint inactive one an examiner can miss.
        self.grid.setFocus(Qt.OtherFocusReason)
        return True

    def _center_row(self, row):
        item = self.grid.item(row, 0)
        if item is not None:
            self.grid.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    def _go_previous_page(self):
        if self._current_table is None:
            return
        self.set_note("")  # the examiner has moved on from where it pointed
        self._load_table(self._current_table, max(0, self._offset - self._page_size))

    def _go_next_page(self):
        if self._current_table is None:
            return
        self.set_note("")  # the examiner has moved on from where it pointed
        self._load_table(self._current_table, self._offset + self._page_size)

    # --- copy: the only place raw stored fields are visible ---------------

    def _grid_cell_text(self, row, col):
        """What a copy of this cell carries: the whole value as stored.
        A binary cell's grid text is only its first bytes and a marker
        (table_browser_loader.grid_hex); its copy is every byte as hex."""
        data = self._cell_bytes(row, col)
        if data is not None:
            return " ".join("%02X" % b for b in bytes(data))
        item = self.grid.item(row, col)
        return item.text() if item is not None else ""

    def _grid_header_label(self, col):
        header_item = self.grid.horizontalHeaderItem(col)
        return header_item.text() if header_item is not None else ""

    def copy_grid_selection_as_tsv(self):
        """As RecordsTable.copy_selection_as_tsv (records_table.py): a
        rectangle with headers, so it pastes into a spreadsheet intact; ""
        with nothing selected. A cell inside the selection's bounding
        rectangle but not selected is blank.

        No Origin column is appended: this grid shows raw tables, with no
        carved marker behind it.
        """
        ixs = self.grid.selectedIndexes()
        if not ixs:
            return ""
        selected = {(ix.row(), ix.column()) for ix in ixs}
        rows = sorted({r for r, _ in selected})
        cols = sorted({c for _, c in selected})
        header = [self._grid_header_label(c) for c in cols]
        lines = ["\t".join(header)]
        for r in rows:
            line = [_tsv_safe(self._grid_cell_text(r, c)) if (r, c) in selected else ""
                   for c in cols]
            lines.append("\t".join(line))
        return "\n".join(lines)

    def _copy_grid_selection(self):
        text = self.copy_grid_selection_as_tsv()
        if text:
            QGuiApplication.clipboard().setText(text)

    def _copy_grid_cell(self, row, col):
        """Byte-exact and undecorated, as RecordsTable._copy_cell: a
        single-value copy has no header or decoration."""
        QGuiApplication.clipboard().setText(self._grid_cell_text(row, col))

    def _copy_grid_row(self, row):
        values = [_tsv_safe(self._grid_cell_text(row, c))
                 for c in range(self.grid.columnCount())]
        QGuiApplication.clipboard().setText("\t".join(values))

    def _copy_grid_column(self, col):
        values = [_tsv_safe(self._grid_cell_text(r, col))
                 for r in range(self.grid.rowCount())]
        QGuiApplication.clipboard().setText("\n".join(values))

    def _grid_context_menu(self, pos):
        ix = self.grid.indexAt(pos)
        if not ix.isValid():
            return
        menu = self._build_grid_context_menu(ix)
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _build_grid_context_menu(self, ix):
        """Split from _grid_context_menu so tests can trigger an action
        directly without popping a real menu (QMenu.exec blocks for
        input) -- mirrors RecordsTable._build_context_menu's own reason
        for the split."""
        menu = QMenu(self)
        # FIRST: the row view, and this one value whole. The copies
        # below carry whole values too (a binary cell copies every byte
        # as hex), but a copy is not a way to read one.
        menu.addAction("View whole row…", lambda: self.open_row(ix.row()))
        menu.addAction("Show whole value",
                       lambda: self.show_whole_value(ix.row(), ix.column()))
        menu.addSeparator()
        if self._cell_bytes(ix.row(), ix.column()) is not None:
            # First, and only on a cell that holds bytes.
            menu.addAction(
                "View these bytes (hex and strings)…",
                lambda: self.request_cell_bytes(ix.row(), ix.column()))
            menu.addSeparator()
        menu.addAction("Copy cell", lambda: self._copy_grid_cell(ix.row(), ix.column()))
        menu.addAction("Copy row", lambda: self._copy_grid_row(ix.row()))
        menu.addAction("Copy column", lambda: self._copy_grid_column(ix.column()))
        return menu

    def _cell_bytes(self, row, col):
        """The raw bytes of one cell, or None. Never a copy: the same
        object table_browser_loader kept by reference."""
        if not (0 <= row < len(self._page_rows)):
            return None
        cells = self._page_rows[row]
        if not (0 <= col < len(cells)):
            return None
        raw = cells[col].get("raw") if isinstance(cells[col], dict) else None
        return raw if isinstance(raw, (bytes, bytearray)) and len(raw) else None

    def request_cell_bytes(self, row, col):
        """Ask the shell to show this cell's bytes.

        Any binary column of any ESE table, including one no decoder
        reads, gets a hex dump and a strings list.
        """
        data = self._cell_bytes(row, col)
        if data is None:
            return False
        name = (self._page_columns[col] if col < len(self._page_columns)
                else "column %d" % (col + 1))
        self.blobRequested.emit(name, data)
        return True

    # --- one row, read vertically -----------------------------------------

    def _table_row_number(self, row):
        """The TABLE's row number (1-based) of a row on this page --
        filtered or sorted, a row keeps its own."""
        if 0 <= row < len(self._page_ordinals):
            return self._page_ordinals[row] + 1
        return self._offset + row + 1

    def _open_current_row(self):
        return self.open_row(self.grid.currentRow())

    def open_row(self, row):
        """Ask the shell for the row view of one row of this page.

        Returns False and emits nothing for a row that is not on this
        page: Enter with no selection, or a stale row index after the
        page turned under it.
        """
        if not (0 <= row < len(self._page_rows)):
            return False
        self.rowRequested.emit({
            "table": self._current_table or "",
            # The TABLE's row number, not the page's. An examiner
            # reading "row 3" against a table of 5,000 means the third
            # row of the table; on page two the third row on screen is
            # not that one.
            "row_number": self._table_row_number(row),
            "row_count": self._row_count,
            "columns": list(self._page_columns),
            # By reference, as _cell_bytes hands out raw bytes: the dialog
            # shows what is stored.
            "cells": self._page_rows[row],
        })
        return True

    # --- empty / missing states ------------------------------------------

    def _render_no_selection(self):
        self._reset_row_view(None)
        self._page_ordinals = []
        self._current_table = None
        self._offset = 0
        self._page_columns = []
        self._page_rows = []
        self._row_count = 0
        self.view_row_button.setEnabled(False)
        self._info_label.setText(
            _NO_EVIDENCE_TEXT if self._parser is None
            else self._starting_text())
        self._directory_label.setVisible(False)
        self._directory_label.setText("")
        self.grid.clear()
        self.grid.setRowCount(0)
        self.grid.setColumnCount(0)
        self._page_label.setText("")
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)

    def _starting_text(self):
        """Where to start: how many tables hold rows, and the largest."""
        tables = getattr(self, "_tables", None) or []
        with_rows = sorted(((c, n) for n, c in tables if c and c > 0),
                           key=lambda t: (-t[0], t[1]))
        if not tables:
            return _NO_SELECTION_TEXT
        text = ("%s %s of %s tables hold rows"
                % (_NO_SELECTION_TEXT, format(len(with_rows), ","),
                   format(len(tables), ",")))
        if with_rows:
            text += "; the largest: %s." % ", ".join(
                "%s (%s)" % (n, format(c, ",")) for c, n in with_rows[:5])
        else:
            text += "."
        return text

    def _render_missing_table(self, table_name):
        """A container registered in the Containers table whose own
        Container_<id> table is absent (HasTable False; see ese_parser.
        _load_containers) has no table to open. Stated in the view."""
        self._render_no_selection()
        self._info_label.setText(
            "%s is not a live table in this exhibit — it is registered in "
            "the Containers table but its own storage table is gone."
            % table_name)
