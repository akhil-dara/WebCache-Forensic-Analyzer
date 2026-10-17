"""The selected record, beside the grid.

Shows the record the grid's selection is on (its title, its origin, the
examiner's tags and comments, and its fields with their basis badges) and
follows the selection as it moves, so the grid stays in view and usable.
The full window (every field, the bytes, Explain) is one button away.

The fields are detail_fields.fields_for's, the same as the full window
renders, so the two always agree. Empty fields are folded away by default
here, and the count line says how many.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..widgets import copyable
from ..widgets.records_table import WrappingDelegate
from ..widgets.wrapping_text import WrappingText
from . import detail_fields, theme
from .case_notes_bar import CaseNotesBar

EMPTY_TEXT = ("Select a record to see its fields here. Double-click it, or "
              "press Ctrl+Enter, to open it in full.")


class DetailsPane(QWidget):
    #: Open this row in the full record window.
    openRequested = Signal(object)
    #: A tag or comment was saved from the pane.
    caseNotesChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("detailsPane")
        self.setMinimumWidth(300)
        #: fn() -> (case, examiner name). Set by the shell, which owns the
        #: case file; until then the pane offers no notes.
        self.case_provider = lambda: (None, "")
        self._row = None

        # WrappingText: a long URL title has no spaces to wrap at; it
        # wraps anywhere, stays whole, and copies exactly as stored.
        # Up to four lines; a longer title scrolls inside itself rather
        # than push the record's fields out of the pane.
        self._title = WrappingText("", max_lines=4)
        title_font = QFont(self._title.font())
        title_font.setWeight(QFont.DemiBold)
        title_font.setPixelSize(13)
        self._title.setFont(title_font)
        self._origin = copyable.selectable(QLabel(""))
        self._origin.setWordWrap(True)
        self._origin.setTextFormat(Qt.PlainText)

        self._notes_holder = QVBoxLayout()
        self._notes_holder.setContentsMargins(0, 0, 0, 0)
        self._notes = None

        self.show_empty_box = QCheckBox("Show empty fields")
        self.show_empty_box.toggled.connect(lambda _on: self._render())
        self.open_button = QPushButton("Open full record")
        self.open_button.setToolTip(
            "Every field, the stored bytes and Explain, in a window "
            "(Ctrl+Enter)")
        self.open_button.clicked.connect(
            lambda: self._row is not None and self.openRequested.emit(self._row))
        tools = QHBoxLayout()
        tools.addWidget(self.show_empty_box)
        tools.addStretch(1)
        tools.addWidget(self.open_button)

        self._count = copyable.selectable(QLabel(""))
        self._count.setWordWrap(True)
        self._count.setTextFormat(Qt.PlainText)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Field", "Value", "Basis"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 150)
        # Never cut a value with an ellipsis: rows are re-measured whenever
        # the value column changes width, so a wrapped value always fits.
        self.table.setTextElideMode(Qt.ElideNone)
        # The delegate every evidence surface uses: it measures a wrapped
        # value as the themed cell paints it, so no line is cut.
        self.table.setItemDelegate(WrappingDelegate(self.table))
        self._remeasure = QTimer(self)
        self._remeasure.setSingleShot(True)
        self._remeasure.setInterval(0)
        self._remeasure.timeout.connect(self.table.resizeRowsToContents)
        header.sectionResized.connect(
            lambda index, _old, _new: index == 1 and self._remeasure.start())

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 0, 0, 0)
        root.setSpacing(6)
        root.addWidget(self._title)
        root.addWidget(self._origin)
        root.addLayout(self._notes_holder)
        root.addLayout(tools)
        root.addWidget(self._count)
        root.addWidget(self.table, 1)
        self.refresh_theme()
        self.show_row(None)

    # --- reading -------------------------------------------------------

    def title_text(self):
        return self._title.text()

    def count_text(self):
        return self._count.text()

    def field_labels(self):
        return [self.table.item(r, 0).text() for r in range(self.table.rowCount())
                if self.table.item(r, 1) is not None]

    def current_row(self):
        return self._row

    # --- showing a record ------------------------------------------------

    def show_row(self, row):
        self._row = row if isinstance(row, dict) else None
        self.open_button.setEnabled(self._row is not None)
        if self._notes is not None:
            self._notes.hide()
            self._notes.deleteLater()
            self._notes = None
        if self._row is not None:
            case, author = self.case_provider()
            # Parented from the start: a parentless widget that shows
            # itself is a top-level window, however briefly.
            self._notes = CaseNotesBar(case, [self._row], author=author,
                                       parent=self, compact=True)
            self._notes.changed.connect(self.caseNotesChanged.emit)
            self._notes_holder.addWidget(self._notes)
        self._render()

    def _render(self):
        self.table.setRowCount(0)
        if self._row is None:
            self._title.setText("")
            self._origin.setText("")
            self._title.setVisible(False)
            self._origin.setVisible(False)
            self._count.setText(EMPTY_TEXT)
            return
        row = self._row
        self._title.setVisible(True)
        self._origin.setVisible(True)
        self._title.setText(detail_fields.identity_of(row))
        self._origin.setText(detail_fields.origin_line(row))
        carved = str(row.get("Origin") or "").startswith("Carved")
        record = row.get("_record") if isinstance(row.get("_record"), dict) else None
        show_empty = self.show_empty_box.isChecked()
        total = hidden = 0
        bold = QFont(self.font())
        bold.setBold(True)
        for group in detail_fields.fields_for(row):
            fields = [f for f in group.fields if show_empty or not f.absence]
            total += len(group.fields)
            hidden += len(group.fields) - len(fields)
            if not fields:
                continue
            at = self.table.rowCount()
            self.table.insertRow(at)
            heading = QTableWidgetItem(group.name.upper())
            heading.setFont(bold)
            heading.setForeground(theme.color("muted"))
            self.table.setItem(at, 0, heading)
            self.table.setSpan(at, 0, 1, 3)
            for f in fields:
                at = self.table.rowCount()
                self.table.insertRow(at)
                label = QTableWidgetItem(f.label)
                text = f.display_value
                # The whole value, wrapped: never shortened.
                value = QTableWidgetItem(text)
                value.setToolTip(copyable.literal_tooltip(text))
                if f.absence:
                    value.setForeground(theme.color("muted"))
                short, tip = detail_fields.basis_badge(
                    f.key, carved=carved, record=record)
                basis = QTableWidgetItem(short or "")
                basis.setToolTip(tip or "")
                self.table.setItem(at, 0, label)
                self.table.setItem(at, 1, value)
                self.table.setItem(at, 2, basis)
        self.table.resizeRowsToContents()
        shown = total - hidden
        if hidden and not show_empty:
            self._count.setText("%s of %s fields — %s empty %s folded away."
                                % (format(shown, ","), format(total, ","),
                                   format(hidden, ","),
                                   "field" if hidden == 1 else "fields"))
        else:
            self._count.setText("%s fields." % format(total, ","))

    def refresh_theme(self):
        self._origin.setStyleSheet("color: %s;" % theme.color("muted").name())
        self._count.setStyleSheet("color: %s; font-size: 11px;"
                                  % theme.color("muted").name())
        if self._row is not None:
            self._render()
