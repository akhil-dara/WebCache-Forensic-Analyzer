"""A second record table beneath a first: a heading, a note, the grid,
and its own export button.

Lists the records behind a selected summary row (a period, a domain) as a
real table: sortable, filterable, openable and exportable. The owning view
supplies the columns and rows.

With nothing selected it shows an instruction rather than an empty
rectangle. The export button counts the rows currently visible and is
recounted on every refresh; the shell decides what exporting means.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QStyle,
                               QVBoxLayout, QWidget)

from ..shell import glyphs, theme
from . import copyable
from .records_table import RecordsTable


def rows_height(table, rows):
    """The height a RecordsTable needs to show its heading and `rows`
    rows at the default row height, with a horizontal scrollbar."""
    header = max(table.horizontalHeader().sizeHint().height(),
                 2 * table.fontMetrics().height())
    return (header + rows * table.verticalHeader().defaultSectionSize()
            + table.style().pixelMetric(QStyle.PM_ScrollBarExtent)
            + 2 * table.frameWidth())


class SubTable(QWidget):
    #: Export the records in this grid.
    exportRequested = Signal()

    #: The button's wording: "these records", distinct from the view's
    #: own Export view, which writes something else.
    EXPORT_LABEL = "Export these records (%s)"

    #: A filled pane never shrinks below its heading, its note and this
    #: many records.
    MIN_ROWS = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prompt = ""
        #: Whether the pane is showing rows. An explicit flag, since a
        #: widget in a window never shown reports isVisible() False.
        self._filled = False

        self.heading = copyable.selectable(QLabel(""))
        self.heading.setWordWrap(True)
        self.note = copyable.selectable(QLabel(""))
        self.note.setWordWrap(True)
        self.prompt = copyable.selectable(QLabel(""))
        self.prompt.setWordWrap(True)
        self.prompt.setAlignment(Qt.AlignTop)

        self.table = RecordsTable()
        self.export_button = QPushButton(self.EXPORT_LABEL % "0")
        self.export_button.setIcon(
            glyphs.icon("download", theme.color("primary"), 15))
        theme.mark_outline(self.export_button)
        self.export_button.clicked.connect(self.exportRequested.emit)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.heading, 1)
        top.addWidget(self.export_button)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(4)
        root.addLayout(top)
        root.addWidget(self.note)
        root.addWidget(self.prompt)
        root.addWidget(self.table, 1)

        self.refresh_theme()

    # --- filling -----------------------------------------------------------

    def set_rows(self, columns, rows, heading, note, empty_reason,
                 default_sort=("KeyTimeUtc", True)):
        """Show `rows` under `heading`, with `note` saying what they are.

        `empty_reason` is shown when a filter inside this pane removes every
        row (the rows themselves are never empty). Set after set_records,
        which clears the previous reason.
        """
        rows = list(rows)
        self._prompt = ""
        self._filled = True
        self.prompt.setVisible(False)
        self.heading.setText(heading)
        self.heading.setVisible(True)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.table.setVisible(True)
        self.table.set_records(columns, rows)
        self.setMinimumHeight(self._filled_minimum())
        # Newest first, with the sort arrow showing it; a key these
        # columns do not declare is ignored.
        if default_sort:
            self.table.sort_by_key(*default_sort)
        self.table.set_filtered_empty_reason(empty_reason)
        self.table.model().layoutRefreshed.connect(self._update_button)
        self.export_button.setVisible(True)
        self._update_button()

    def _filled_minimum(self):
        margins = self.layout().contentsMargins()
        top = max(self.export_button.sizeHint().height(),
                  self.heading.fontMetrics().lineSpacing())
        note = self.note.fontMetrics().lineSpacing() if self.note.text() else 0
        return (margins.top() + margins.bottom() + top + note
                + 2 * self.layout().spacing()
                + rows_height(self.table, self.MIN_ROWS))

    def clear(self, prompt):
        """Nothing is selected: show what to do."""
        self._prompt = prompt
        self._filled = False
        # Idle, the pane is one sentence and takes no extra room.
        self.setMinimumHeight(0)
        self.heading.setText("")
        self.heading.setVisible(False)
        self.note.setText("")
        self.note.setVisible(False)
        self.prompt.setText(prompt)
        self.prompt.setVisible(True)
        self.table.setVisible(False)
        self.export_button.setVisible(False)
        self.export_button.setText(self.EXPORT_LABEL % "0")

    # --- what is on screen -------------------------------------------------

    def visible_rows(self):
        """The rows on screen, in on-screen order: what the button counts
        and an export writes."""
        if not self._filled:
            return []
        model = self.table.model()
        return list(model.filter.visible()) if model is not None else []

    def heading_text(self):
        return self.heading.text()

    def note_text(self):
        return self.note.text()

    def prompt_text(self):
        return self._prompt

    def _update_button(self):
        self.export_button.setText(
            self.EXPORT_LABEL % format(len(self.visible_rows()), ","))

    # --- theme -------------------------------------------------------------

    def refresh_theme(self):
        p = theme.PALETTES[theme.current_name()]
        self.heading.setStyleSheet(
            "font-size: 12.5px; font-weight: 600; background: transparent; "
            "color: %(text)s;" % p)
        for label in (self.note, self.prompt):
            label.setStyleSheet(
                "font-size: 11.5px; background: transparent; "
                "color: %(muted)s;" % p)
        self.export_button.setIcon(
            glyphs.icon("download", theme.color("primary"), 15))
        self.table.viewport().update()
