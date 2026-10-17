"""One raw table row, read vertically: every column, field and value.

The Table Browser shows a raw ESE table as a wide grid, where a cell can
paint only part of a long value (a few wrapped lines under the row cap,
or a binary column's first bytes and a marker naming the rest). This
dialog shows one row with every column whole.

It is separate from RecordDetailDialog because that dialog is built on
detail_fields.fields_for(row): named engine fields in groups, each with a
basis badge, a provenance line, absence wording, carved styling and a
drill target. Each of those interprets a parsed record, and the Table
Browser shows raw tables with no interpretation applied; a raw column has
no basis, no provenance beyond its table and row, and no record behind
it.

The binary half is shared rather than rebuilt:

  * blob_source.blobs_for_cells() turns the row's bytes cells into blob
    sources;
  * record_detail.build_blob_tabs() mounts the same BlobPane, with the
    same tab labels and export guards, as the record dialog;
  * record_detail.BlobRegion folds it to a bar that names the bytes, and
    the same helpers divide the splitter, so both surfaces behave alike;
  * ElidingButton/WrappingText, the TSV-safety rule and the clipboard's
    busy sentence come from their own modules.

Values are never reformatted: what is shown is the engine's rendering of
what is stored (raw_rendering), untruncated, escapes intact, a
FILETIME-shaped integer still an integer. The only text this tool adds
describes an absence or a blob's size, and neither is copied as a value.
"""
from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtGui import QBrush, QFont, QGuiApplication
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu,
                               QPushButton, QSizePolicy, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

import types

from ..widgets import copyable
from ..widgets.wrapping_text import WrappingText
from ..widgets.hex_view import CLIPBOARD_BUSY
from ..widgets.record_model import foreground
from ..widgets.records_table import WrappingDelegate
from . import blob_source, export_target, record_detail, settings, theme
from .record_detail import (MIN_HEIGHT, MIN_HEIGHT_WITH_VIEWER, MIN_WIDTH,
                            PARENT_MARGIN_H, PARENT_MARGIN_H_WITH_VIEWER,
                            PARENT_MARGIN_W, PROPERTY_LABEL_WIDTH,
                            ElidingButton, _tsv_safe)

#: The caveat the Table Browser itself carries, repeated here rather than
#: assumed remembered. This dialog can be left open beside three others;
#: the one that shows uninterpreted values is the one that must say so.
CAVEAT = ("Raw ESE values exactly as stored, with no interpretation "
          "applied — shown in full, and escaped so a NUL or a bidi "
          "override stays visible.")

#: What a null column and a stored empty string say: a column with no
#: value, and a zero-length string that was stored. Spelled out so they
#: differ on screen; neither is copied as a value.
NULL_TEXT = "(null — no value is stored in this column)"
EMPTY_TEXT = "(empty — a zero-length value is stored in this column)"

#: The type column: narrow, fixed, and never narrower than its heading.
TYPE_COLUMN_PX = 90


class RawField:
    """One column of one raw row.

    Not a detail_fields.DetailField: a raw ESE column has no basis,
    provenance note, absence token or drill target.

    name       the column's own name, in the table's own order
    type_name  what the database stored there ("text", "binary", "null")
    shown      what is painted; always a non-empty string
    value      what a copy emits, or None where there is nothing to copy
    blob_key   the blob source's key, for a bytes column; "" otherwise
    """

    __slots__ = ("name", "type_name", "shown", "value", "blob_key",
                 "decoded")

    def __init__(self, name, type_name, shown, value=None, blob_key="",
                 decoded=""):
        self.decoded = decoded
        self.name = name
        self.type_name = type_name
        self.shown = shown
        self.value = value
        self.blob_key = blob_key

    @property
    def is_absent(self):
        """True where the row holds no value to copy -- a null column, a
        zero-length value, or a blob whose bytes are in the viewer rather
        than in this cell."""
        return self.value is None

    def __repr__(self):
        return "RawField(%r, %r)" % (self.name, self.type_name)


def fields_for_row(columns, cells):
    """The row, as fields, in the table's own column order.

    Pure and separately testable, as detail_fields.py is for the record
    dialog.

    A cell's "text" is its whole value as stored (table_browser_loader.
    _cell); binary is summarised here and shown whole in the hex viewer.
    """
    out = []
    for index, name in enumerate(columns or ()):
        cell = cells[index] if index < len(cells or ()) else {}
        if not isinstance(cell, dict):
            cell = {}
        type_name = cell.get("type") or "null"
        raw = cell.get("raw")
        text = cell.get("text") or ""
        if isinstance(raw, (bytes, bytearray)) and len(raw):
            # A composed summary, and it says so by naming a unit rather
            # than showing bytes: the value itself is in the hex viewer
            # below, which is the one place bytes are rendered.
            out.append(RawField(
                name, type_name,
                "%s bytes · shown in the hex viewer below"
                % format(len(raw), ","), None, blob_key=name))
            continue
        if type_name == "null":
            out.append(RawField(name, type_name, NULL_TEXT, None))
            continue
        if text == "":
            out.append(RawField(name, type_name, EMPTY_TEXT, None))
            continue
        out.append(RawField(name, type_name, text, text,
                            decoded=cell.get("decoded") or ""))
    return out


class TableRowDialog(QDialog):
    """One raw row, every column, modeless.

    Modeless and stacking, like every detail surface: a second row opened
    leaves the first on screen, so two rows can be compared side by side.
    """

    def __init__(self, columns, cells, parent=None, table="", row_number=0,
                 row_count=0, db_path="", evidence_set=None):
        super().__init__(parent)
        self.columns = list(columns or ())
        self.cells = list(cells or ())
        self.table_name = table or ""
        self.row_number = int(row_number or 0)
        self.row_count = int(row_count or 0)
        self.fields = fields_for_row(self.columns, self.cells)
        self._rows = []          # table row -> RawField
        self.blob_area = None
        self.blob_region = None
        self._splitter_sized = False
        self._fold_decided = False
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("Table row")
        # Where the exhibit lives, so every pane's export can refuse to
        # write beside it (as in the record dialog).
        self._evidence_files, self._evidence_dirs = (
            export_target.evidence_paths(
                evidence_set, types.SimpleNamespace(db_path=db_path or "")))

        self.blobs = blob_source.blobs_for_cells(self.columns, self.cells)
        floor = MIN_HEIGHT_WITH_VIEWER if self.blobs else MIN_HEIGHT
        margin = (PARENT_MARGIN_H_WITH_VIEWER if self.blobs
                  else PARENT_MARGIN_H)
        if parent is not None:
            self.resize(max(MIN_WIDTH, parent.width() - PARENT_MARGIN_W),
                        max(floor, parent.height() - margin))
        else:
            self.resize(MIN_WIDTH, floor)

        root = QVBoxLayout(self)
        root.setContentsMargins(record_detail.DIALOG_MARGIN_X,
                                record_detail.DIALOG_MARGIN_TOP,
                                record_detail.DIALOG_MARGIN_X,
                                record_detail.DIALOG_MARGIN_BOTTOM)
        root.addWidget(self._build_header())
        root.addLayout(self._build_toolbar())

        summary = QHBoxLayout()
        self.count_label = copyable.selectable(QLabel())
        self.count_label.setWordWrap(True)
        summary.addWidget(self.count_label, 1)
        self.status_label = copyable.selectable(QLabel(""))
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # Ignored horizontally: a confirmation naming a long column must
        # not put a floor under the whole dialog's width.
        self.status_label.setSizePolicy(QSizePolicy.Ignored,
                                        QSizePolicy.Preferred)
        self.status_label.setStyleSheet(
            "color: %s;" % theme.color("muted").name())
        summary.addWidget(self.status_label, 1)
        root.addLayout(summary)

        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.splitterMoved.connect(
            self._remember_the_examiner_moved_it)
        self._splitter.addWidget(self._build_fields())
        # ABSENT ENTIRELY where the row carries no bytes: no empty pane,
        # no bar saying there is nothing -- a region that exists only to
        # say "no binary data here" is a region taking room from the
        # columns in order to say it.
        if self.blobs:
            self.blob_area = record_detail.build_blob_tabs(
                self.blobs, self._evidence_files, self._evidence_dirs)
            self.blob_region = record_detail.BlobRegion(self.blob_area,
                                                        self._blob_summary())
            self.blob_region.foldChanged.connect(self._fold_changed)
            self._splitter.addWidget(self.blob_region)
            self._splitter.setStretchFactor(0, 1)
            self._splitter.setStretchFactor(1, 0)
            # Sized in showEvent, not here: at construction the splitter
            # has not been laid out and its height is not yet the height
            # it will have.
        root.addWidget(self._splitter, 1)

        buttons = QDialogButtonBox()
        close = buttons.addButton("Close", QDialogButtonBox.AcceptRole)
        close.setDefault(False)
        close.setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._populate()
        self.table.installEventFilter(self)
        self.filter_box.installEventFilter(self)
        self.setAccessibleName("Raw table row")
        self.setAccessibleDescription(CAVEAT)

    # --- construction ----------------------------------------------------

    def _build_header(self):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        # WrappingText: a long table name wraps instead of flooring the
        # dialog's own width.
        self.identity_label = WrappingText(self._identity())
        font = QFont(self.identity_label.font())
        font.setBold(True)
        self.identity_label.setFont(font)
        layout.addWidget(self.identity_label)

        self.caveat_label = QLabel(CAVEAT)
        self.caveat_label.setWordWrap(True)
        copyable.selectable(self.caveat_label)
        self.caveat_label.setStyleSheet(
            "color: %s;" % theme.color("muted2").name())
        layout.addWidget(self.caveat_label)
        layout.addSpacing(record_detail.HEADER_GAP_PX)
        return box

    def _identity(self):
        """Which row of which table, said in the header.

        The row NUMBER, not a key: a raw table has no guaranteed identity
        column, and inventing one out of whichever column happens to look
        like an id would be an interpretation this view may not make.
        """
        parts = [self.table_name or "Raw table row"]
        if self.row_number:
            if self.row_count:
                parts.append("row %s of %s" % (format(self.row_number, ","),
                                               format(self.row_count, ",")))
            else:
                parts.append("row %s" % format(self.row_number, ","))
        return "  ·  ".join(parts)

    def _build_toolbar(self):
        bar = QHBoxLayout()
        # First, before the two whole-row copies: the per-column copy is
        # the one most often needed.
        self.copy_field_button = ElidingButton(
            "Copy value", floor_px=record_detail._TOOLBAR_FLOOR_PX)
        # copy_selection, as the Ctrl+C its tooltip names, so the button
        # and the shortcut do the same thing.
        self.copy_field_button.clicked.connect(self.copy_selection)
        self.copy_all_button = QPushButton("Copy all columns")
        self.copy_all_button.clicked.connect(self.copy_all)
        self.copy_tsv_button = QPushButton("Copy as TSV")
        self.copy_tsv_button.clicked.connect(self.copy_tsv)
        for button in (self.copy_field_button, self.copy_all_button,
                       self.copy_tsv_button):
            button.setAutoDefault(False)
            bar.addWidget(button)
        bar.addStretch(1)

        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filter columns (Ctrl+F)")
        self.filter_box.setClearButtonEnabled(True)
        # Never narrower than its placeholder text, with the same allowance
        # the record dialog's filter box makes: the frame and the clear
        # button take width the font metrics do not include.
        needed = self.filter_box.fontMetrics().horizontalAdvance(
            self.filter_box.placeholderText())
        self.filter_box.setMinimumWidth(
            needed + record_detail._FILTER_BOX_CHROME_PX)
        self.filter_box.setMaximumWidth(
            needed + 2 * record_detail._FILTER_BOX_CHROME_PX)
        self.filter_box.textChanged.connect(self.apply_filter)
        bar.addWidget(self.filter_box)
        return bar

    def _build_fields(self):
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Column", "Value", "Stored as", "Decoded (derived)"])
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(0, PROPERTY_LABEL_WIDTH)
        self.table.setColumnWidth(2, TYPE_COLUMN_PX)
        self.table.setColumnWidth(3, 260)
        # Rows size to their CONTENT: a 900-character URL wraps to full
        # height rather than being elided, which is the whole reason this
        # surface exists.
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        # The one evidence delegate: a run with no break opportunity (a
        # token, a hash) wraps instead of being cut at the cell edge, and
        # nothing is elided.
        self.table.setItemDelegate(WrappingDelegate(self.table))
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.currentCellChanged.connect(
            lambda *_a: self._refresh_copy_button())
        self.table.itemSelectionChanged.connect(self._refresh_copy_button)
        return self.table

    # --- the bytes ---------------------------------------------------------

    def _blob_summary(self):
        """What the fold bar says the region holds.

        The SAME words the tab label uses, so a folded region and an open
        one describe the same thing. With several bytes columns it counts
        them rather than listing them -- a bar that wraps to two lines is
        a bar that costs the columns a row.
        """
        first = self.blobs[0]
        head = "%s · %s bytes" % (first.label, format(first.size, ","))
        if len(self.blobs) > 1:
            head = "%s, and %d more" % (head, len(self.blobs) - 1)
        return "Bytes: %s" % head

    def blob_pane_for(self, blob_key):
        """The tab showing the bytes of one column, or -1.

        Matched on the KEY (the column's own name), never on the tab
        label: the label carries a formatted size and would stop matching
        the moment the wording changed.
        """
        if self.blob_area is None:
            return -1
        for index in range(self.blob_area.count()):
            if self.blob_area.widget(index).blob_key == blob_key:
                return index
        return -1

    def current_blob_pane(self):
        if self.blob_area is None:
            return None
        return self.blob_area.currentWidget()

    def toggle_blob_region(self):
        """Ctrl+B, and the fold bar's click. None when the row has no
        bytes, since there is nothing to fold."""
        if self.blob_region is None:
            self.status_label.setText("This row stores no binary value.")
            self.status_label.setStyleSheet(
                "color: %s;" % theme.color("muted").name())
            return None
        self.blob_region.set_expanded(not self.blob_region.is_expanded(),
                                      deliberate=True)
        return self.blob_region.is_expanded()

    def show_blob_region(self):
        """Unfold, if folded. Not deliberate: opening one column's bytes is
        navigation to one value, not a layout preference, so nothing is
        written to settings."""
        if self.blob_region is not None and not self.blob_region.is_expanded():
            self.blob_region.set_expanded(True)

    def export_focused_blob(self):
        """Ctrl+E. The column whose tab is showing, never "the first
        one"."""
        pane = self.current_blob_pane()
        if pane is None:
            self.status_label.setText(
                "This row stores no binary value to export.")
            return False
        return pane.export_blob()

    # --- room: the same rules the record dialog's viewer follows -----------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.table.resizeRowsToContents()
        self._apply_splitter_sizes()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_splitter_sizes()

    def _remember_the_examiner_moved_it(self, *_args):
        """Once the handle has been dragged, the split is theirs."""
        self._splitter_sized = True

    def _apply_splitter_sizes(self, force=False):
        """Re-applied on every resize until the examiner drags the handle.

        Through the shared helpers, not a second arithmetic: the room
        rules an examiner learns on the record dialog hold here, and two
        copies of them are two that will drift.
        """
        if self.blob_region is None or (self._splitter_sized and not force):
            return
        total = record_detail.splitter_room(self._splitter)
        if total <= 0:
            return
        self._decide_the_fold(total)
        record_detail.divide_for_viewer(
            self._splitter, self.blob_region, total, self._viewer_minimum())

    def _viewer_minimum(self):
        return record_detail.viewer_minimum(self.blob_area, self.blob_region)

    def _decide_the_fold(self, total):
        """Once per dialog, and only where the examiner has not chosen.

        The stored preference is the record dialog's key, shared: working
        in the bytes is the examiner's preference on both surfaces. With
        nothing stored, the viewer opens only where its minimum height
        still leaves the column list the larger share, and otherwise folds
        to a bar naming the bytes.
        """
        if self._fold_decided:
            return
        self._fold_decided = True
        stored = settings.get(record_detail.BLOB_OPEN_KEY, None)
        if isinstance(stored, bool):
            self.blob_region.set_expanded(stored)
            return
        self.blob_region.set_expanded(
            record_detail.viewer_fits_beside_the_fields(
                total, self._viewer_minimum()))

    def _fold_changed(self, expanded, deliberate):
        """Re-divide always; save the state only for a deliberate toggle,
        never on open or close, so viewing a row does not write the
        settings file.
        """
        if deliberate:
            settings.save(**{record_detail.BLOB_OPEN_KEY: bool(expanded)})
        if expanded:
            shortfall = (self._viewer_minimum() + record_detail._FIELDS_FLOOR_PX
                         - record_detail.splitter_room(self._splitter))
            record_detail.grow_for_the_viewer(self, shortfall)
        # force: folding is a fresh instruction about the division and
        # replaces an earlier drag of the handle.
        self._apply_splitter_sizes(force=True)

    # --- painting ---------------------------------------------------------

    def _populate(self, needle=""):
        # Captured BEFORE setRowCount(0), which drops the current row:
        # _populate runs on every filter keystroke, and a filter that
        # still shows the selected column must not deselect it.
        held = self.field_at(self.table.currentRow())
        held_name = held.name if held is not None else None
        self.table.setRowCount(0)
        self._rows = []
        for field in self.fields:
            if needle and not _matches(field, needle):
                continue
            self._add_field(field)
        self.table.resizeRowsToContents()
        self._restore_or_choose_a_column(held_name)
        self._refresh_count(needle)
        self._refresh_copy_button()

    def _add_field(self, field):
        row = self.table.rowCount()
        self.table.insertRow(row)

        name = QTableWidgetItem(field.name)
        name.setToolTip(copyable.literal_tooltip(field.name))
        self.table.setItem(row, 0, name)

        value = QTableWidgetItem(field.shown)
        value.setToolTip(copyable.literal_tooltip(
            field.shown if not field.is_absent else
            "%s\n\n%s" % (field.shown, CAVEAT)))
        if field.is_absent:
            # Muted, like every other stated absence in this application:
            # what the tool is saying about the row, not what the row
            # says about itself.
            value.setForeground(QBrush(foreground("muted")))
        else:
            value.setForeground(QBrush(foreground("text")))
        self.table.setItem(row, 1, value)

        type_item = QTableWidgetItem(field.type_name)
        type_item.setForeground(QBrush(foreground("muted2")))
        type_item.setToolTip("What the database stores in this column.")
        self.table.setItem(row, 2, type_item)

        decoded = QTableWidgetItem(field.decoded)
        decoded.setForeground(QBrush(foreground("primary")))
        decoded.setToolTip("Derived by this tool from the stored value "
                           "beside it; the stored value is the evidence.")
        self.table.setItem(row, 3, decoded)
        self._rows.append(field)

    def _refresh_count(self, needle):
        total = len(self.fields)
        shown = len(self._rows)
        if needle:
            hidden = total - shown
            self.count_label.setText(
                "Showing %s of %s columns — filtered. %s %s hidden by this "
                "filter." % (format(shown, ","), format(total, ","),
                             format(hidden, ","),
                             "column is" if hidden == 1 else "columns are"))
            # A filter may hide columns; it may never do it quietly.
            self.count_label.setStyleSheet(
                "color: %s;" % theme.color("warn").name())
            return
        absent = len([f for f in self.fields if f.is_absent])
        self.count_label.setText(
            "%s columns — every value this row stores, nothing truncated. "
            "%d of them hold nothing to copy." % (format(total, ","), absent))
        self.count_label.setStyleSheet(
            "color: %s;" % theme.color("muted2").name())

    def _refresh_copy_button(self):
        """What "Copy value" will act on, said before it is pressed.

        Disabled outright where there is nothing to copy: a button that
        looks live and does nothing is worse than one that plainly is
        not.
        """
        selected = sorted({ix.row() for ix in self.table.selectedIndexes()})
        if len(selected) > 1:
            self.copy_field_button.setEnabled(True)
            self.copy_field_button.setToolTip(
                "Ctrl+C — copy the %d selected columns, each with its "
                "column name in front of it." % len(selected))
            return
        field = self.field_at(self.table.currentRow())
        self.copy_field_button.setEnabled(
            field is not None and not field.is_absent)
        if field is None:
            self.copy_field_button.setToolTip(
                "Ctrl+C — select a column below to copy its value.")
            return
        if field.is_absent:
            self.copy_field_button.setToolTip(
                "%s holds nothing to copy: %s" % (field.name, field.shown))
            return
        self.copy_field_button.setToolTip(
            "Ctrl+C — copy the value of “%s” exactly as this view shows "
            "it, in full and with no column name in front of it."
            % field.name)

    def _restore_or_choose_a_column(self, held_name):
        """Keep the examiner's column selected, or select one if none is.

        On open nothing is selected, which would leave the primary copy
        action disabled as if unavailable for this row. After a filter
        keystroke setRowCount(0) has dropped the selection, so it is found
        again by name.

        The fallback prefers a column that holds something, since an
        absent one leaves the button disabled anyway.
        """
        rows = range(len(self._rows))
        if held_name is not None:
            back = next((r for r in rows
                         if self._rows[r] is not None
                         and self._rows[r].name == held_name), None)
            if back is not None:
                return self._select_only(back)
        pick = next((r for r in rows
                     if self._rows[r] is not None
                     and not self._rows[r].is_absent), None)
        if pick is None:
            pick = next((r for r in rows if self._rows[r] is not None), None)
        if pick is not None:
            self._select_only(pick)

    def _select_only(self, row):
        """Select exactly this row, whatever modifier keys Qt believes are
        held.

        With Ctrl held, setCurrentCell() adds to the selection rather than
        replacing it. This is the dialog's own initial selection, so it is
        always exactly one row.
        """
        self.table.setCurrentCell(row, 0, QItemSelectionModel.ClearAndSelect
                                   | QItemSelectionModel.Rows)

    # --- lookups ----------------------------------------------------------

    def field_at(self, table_row):
        if 0 <= table_row < len(self._rows):
            return self._rows[table_row]
        return None

    # --- filtering --------------------------------------------------------

    def apply_filter(self, text):
        self._populate((text or "").strip().lower())

    # --- keys -------------------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.ControlModifier)
        if ctrl and key == Qt.Key_W:
            self.close()
            return
        if ctrl and key == Qt.Key_F:
            self.filter_box.setFocus()
            self.filter_box.selectAll()
            return
        if ctrl and key == Qt.Key_C:
            self.copy_selection()
            return
        if ctrl and key == Qt.Key_B:
            self.toggle_blob_region()
            return
        if ctrl and key == Qt.Key_E:
            self.export_focused_blob()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter) and not self.filter_box.hasFocus():
            # BEFORE super(): QDialog reads Enter as "press the default
            # button", which would close the dialog over the row being
            # read.
            self.activate_field(self.table.currentRow())
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if event.type() != QEvent.KeyPress:
            return super().eventFilter(watched, event)
        if (watched is self.filter_box and event.key() == Qt.Key_Escape
                and self.filter_box.text()):
            # Escape clears a filter in force and keeps the dialog open;
            # with the box already empty it falls through and closes.
            self.filter_box.setText("")
            return True
        if watched is self.table and event.key() in (Qt.Key_Return,
                                                     Qt.Key_Enter):
            # QAbstractItemView consumes Enter (it means "edit this cell"
            # to a view, even with NoEditTriggers), so it never reaches
            # this dialog's own keyPressEvent by propagation.
            self.keyPressEvent(event)
            return True
        return super().eventFilter(watched, event)

    # --- activation --------------------------------------------------------

    def activate_field(self, table_row):
        """Enter, or a double-click, on a column row.

        A bytes column jumps to its own tab rather than copying: its
        painted value is a sentence this tool composed, and the useful
        thing to do with a blob is look at it. Every other column copies,
        which is the one action a raw value has.
        """
        field = self.field_at(table_row)
        if field is None:
            return False
        if field.blob_key:
            index = self.blob_pane_for(field.blob_key)
            if index >= 0:
                # Unfold first, so the tab switched to is visible.
                self.show_blob_region()
                self.blob_area.setCurrentIndex(index)
                self.blob_area.currentWidget().setFocus()
                self.status_label.setText(
                    "Showing %s in the tab below." % field.name)
                self.status_label.setStyleSheet(
                    "color: %s;" % theme.color("muted").name())
                return True
        return self.copy_field(table_row)

    # --- copy --------------------------------------------------------------

    def _set_clipboard(self, text):
        """True when the text reached the clipboard.

        setText can fail while another application holds the Windows
        clipboard; that is reported (CLIPBOARD_BUSY, as for every copy)
        rather than claimed as success.
        """
        try:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(text)
            return clipboard.text() == text
        except Exception:                          # noqa: BLE001
            return False

    def _report(self, ok, message, warn=False):
        self.status_label.setText(message if ok else CLIPBOARD_BUSY)
        self.status_label.setStyleSheet(
            "color: %s;" % theme.color("muted" if ok and not warn
                                       else "warn").name())
        return ok

    def _refuse(self, message):
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color: %s;" % theme.color("warn").name())
        return False

    def copy_field(self, table_row):
        """The value of one column, as this view shows it.

        Undecorated: no column name, no quotes, as RecordsTable._copy_cell
        and RecordDetailDialog.copy_field do. An absence copies nothing,
        so this tool's sentence about a null is never pasted as a stored
        value.
        """
        field = self.field_at(table_row)
        if field is None:
            return self._refuse("Select a column below to copy its value.")
        if field.is_absent:
            return self._refuse("Nothing to copy — %s %s"
                                % (field.name, field.shown))
        return self._report(self._set_clipboard(field.value),
                            "Copied %s." % field.name)

    def copy_selection(self):
        """Ctrl+C. ONE column copies its value; several keep their names.

        Everything that is SELECTED, never merely the current cell. The
        list selects rows in the ordinary extended way, so an examiner
        can drag across three columns -- and a copy that acted on the
        current cell alone dropped the other two with nothing said, or,
        after a select-all (which sets no current cell at all), copied
        nothing whatever and left the clipboard holding the previous
        copy's contents.

        The single-column case goes THROUGH copy_field, not a second
        byte-exact path of its own: that is where an absence refuses
        rather than copying this tool's sentence about a null, and where
        a bytes column refuses rather than copying a composed summary. A
        parallel implementation here would be one that forgets both.
        """
        rows = sorted({ix.row() for ix in self.table.selectedIndexes()})
        if not rows:
            rows = [self.table.currentRow()]
        fields = [(r, self.field_at(r)) for r in rows]
        fields = [(r, f) for r, f in fields if f is not None]
        if not fields:
            return self._refuse("Select a column below to copy its value.")
        if len(fields) == 1:
            return self.copy_field(fields[0][0])
        # The shown value, so an absent column copies as the sentence that
        # says it holds nothing; leaving it out would read as a column that
        # does not exist.
        text = "\n".join("%s: %s" % (f.name, f.shown) for _r, f in fields)
        return self._report(self._set_clipboard(text),
                            "Copied %d columns." % len(fields))

    def copy_field_with_name(self, table_row):
        field = self.field_at(table_row)
        if field is None:
            return False
        return self._report(
            self._set_clipboard("%s: %s" % (field.name, field.shown)),
            "Copied %s with its column name." % field.name)

    def copy_all_text(self):
        """Every column, labelled, in the table's own order, headed by the
        table and row, so a pasted copy names its source.
        """
        lines = [self._identity(), CAVEAT, ""]
        for field in self.fields:
            lines.append("%s: %s" % (field.name, field.shown))
        return "\n".join(lines).rstrip("\n")

    def copy_tsv_text(self):
        lines = ["Column\tValue\tStored as"]
        for field in self.fields:
            lines.append("%s\t%s\t%s" % (_tsv_safe(field.name),
                                         _tsv_safe(field.shown),
                                         _tsv_safe(field.type_name)))
        return "\n".join(lines)

    def copy_all(self):
        return self._report(self._set_clipboard(self.copy_all_text()),
                            "Copied every column.")

    def copy_tsv(self):
        return self._report(self._set_clipboard(self.copy_tsv_text()),
                            "Copied every column as TSV.")

    # --- the column context menu -------------------------------------------

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if self.field_at(row) is None:
            return
        self.build_field_menu(row).exec(
            self.table.viewport().mapToGlobal(pos))

    def build_field_menu(self, table_row):
        """Split from _context_menu so a test can trigger an action
        without popping a real menu (QMenu.exec blocks for input) -- the
        same split RecordsTable and RecordDetailDialog both make."""
        menu = QMenu(self)
        field = self.field_at(table_row)
        if field is None:
            return menu
        # Copy, never Open. Nothing here launches a path.
        menu.addAction("Copy value\tCtrl+C",
                       lambda: self.copy_field(table_row))
        menu.addAction("Copy column name and value",
                       lambda: self.copy_field_with_name(table_row))
        menu.addSeparator()
        menu.addAction("Copy all columns", self.copy_all)
        menu.addAction("Copy all columns as TSV", self.copy_tsv)
        return menu

    # --- lifecycle ---------------------------------------------------------

    def closeEvent(self, event):
        """Drop the row's references.

        The cells hold bytes read out of the parser that produced them,
        by reference -- a dialog left holding them keeps that whole
        exhibit alive, the same reason RecordDetailDialog drops its own.
        """
        self.cells = []
        self.fields = []
        self._rows = []
        self.blobs = []
        super().closeEvent(event)


def _matches(field, needle):
    if not needle:
        return True
    return (needle in field.name.lower()
            or needle in field.shown.lower()
            or needle in field.type_name.lower())
