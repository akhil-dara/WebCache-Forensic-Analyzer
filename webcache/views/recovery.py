"""Deleted Records: what a recovery scan recovers, laid out like History.

No carve runs to fill this view on its own (see recovery_loader.py).
Before the first scan the table is empty and the count line says how to
run one. MainWindow._start_recovery runs a scan, from Evidence > Recover
deleted records or from recover_button below, through one RecoveryLoader.

Columns show every provenance field the engine computes for a carved row
(provenance.PROVENANCE_FIELDS): Source names the file (a transaction log
or the database) the record came from, Offset and Page where in it, Method
which of RecoveryEngine's two carving techniques found it, and Confidence
the engine's grading. Timestamp holds two kinds of evidence in one column,
a structured record's AccessedTime and a string carve's nearby FILETIME,
and states which in the TimestampBasis column (see deleted_records_rows in
recovery_loader.py).

The filter box, count line and clear-filters control work as in History
(record_filter's LIVE_FILTER_MAX_ROWS/DEBOUNCE_MS and the same
RecordsTable).
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..engine import evidence_model
from ..shell import glyphs, theme
from ..shell.record_kinds import K_CARVED_STRING, K_CARVED_STRUCT, K_TOMBSTONE
from ..widgets import copyable
from ..widgets.column_spec import Column
from ..widgets.content_header import CaveatLine, ViewHeader, constant_text
from ..widgets.quick_filter_chip import QuickFilterChip
from ..widgets.record_filter import DEBOUNCE_MS, LIVE_FILTER_MAX_ROWS
from ..widgets.records_table import RecordsTable
from .records_view import constant_note_style, make_wrap_button

#: Shown before any scan has run this session, with how to run one: the
#: button above this count line, or Evidence > Recover deleted records.
NOT_SCANNED_NOTE = ("no scan has run yet — click “Recover deleted "
                    "records” above (or Evidence ▸ Recover "
                    "deleted records) to carve unallocated pages and "
                    "transaction logs")

#: Shown when a scan ran and recovered nothing; worded differently from
#: NOT_SCANNED_NOTE so the two states read differently. set_records tells
#: them apart by whether `note` is NOT_SCANNED_NOTE.
SCAN_FOUND_NOTHING_NOTE = ("the recovery scan completed and found no "
                           "recoverable deleted records in this exhibit")


class RecoveryView(QWidget):
    recoverRequested = Signal()
    #: The "Export view (N)" button: the view reports the request and
    #: MainWindow performs the export, as in RecordsView.
    exportRequested = Signal()
    #: the same toolbar toggle as every RecordsView.
    #: MainWindow._make_view wires any widget that has these two.
    wrapToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Provenance (Source/Offset/Page/Method/Confidence) follows the URL,
        # so where a record came from is visible without scrolling; Title
        # (empty on most carved rows) and Origin (one value on every row)
        # come after.
        #
        # CleanUrl is 174 px, its own heading floor: each provenance
        # column carries a basis badge, and RecordsTable._enforce_heading_
        # floor reserves twice the badge's width around such a heading.
        # With the origin column at its measured 69 px floor, this keeps
        # every provenance column inside a 1,223 px viewport (1,536 px
        # maximised with the sidebar expanded); see
        # test_recovery_provenance_visible.py and
        # test_header_labels_are_never_clipped.py.
        #
        # Source is headed "File": a complete word that fits beside its
        # badge, in the register of "Page" and "Method". Its key and
        # tooltip still say "Source".
        self.COLUMNS = [
            Column("CleanUrl", "URL", 174, kind="url", field="CleanUrl"),
            Column("Source", "File", 130, kind="text", field="Source"),
            # The default sort column, before Offset so it is on screen.
            # field=None: this column mixes a structured record's
            # AccessedTime with a string carve's nearby FILETIME, so no
            # single basis badge describes every cell; TimestampBasis
            # states it per row.
            Column("Timestamp", "Timestamp (UTC)", 150, kind="time", field=None,
                   basis_key="TimestampBasis",
                   note=("This column holds two kinds of evidence: a "
                         "structured record's own time, and a FILETIME "
                         "found near a carved string, which is context, "
                         "not a visit time. Each cell's tooltip says "
                         "which; Method and Confidence say how sure.")),
            Column("Offset", "Offset", 100, kind="offset", field="Offset"),
            Column("Method", "Method", 220, kind="text", field="Method"),
            Column("Confidence", "Confidence", 95, kind="text", field="Confidence"),
            # After Confidence: with Timestamp (UTC) on screen, File,
            # Offset, Method and Confidence fit 1536 px only if one
            # badge-floored column moves right. Offset already locates the
            # bytes, and the record dialog and every export state the page.
            Column("Page", "Page", 60, kind="num", field="Page"),
            # a stub's key is its own fact in its own column, so
            # Confidence can say "exact" and stay comparable.
            Column("Key", "Key (stubs)", 300, kind="text"),
            Column("ContainerType", "Container", 100, kind="text"),
            Column("Title", "Title", 160, kind="text"),
            # The Timestamp cell's basis as its own column: hidden on screen
            # (the cell's tooltip states it) and written by Export view like
            # every declared column, so the CSV says which times are a
            # record's own and which were found nearby. Before Origin, which
            # stays last.
            Column("TimestampBasis", "Timestamp basis", 260, kind="text",
                   optional=True),
            Column("Origin", "Origin detail", 170, kind="text", field="Origin"),
        ]
        # Basis badges are wired here, in a view (which may import the
        # engine), not in RecordsTable (a widget, which may not).
        for col in self.COLUMNS:
            if col.show_badge:
                basis = evidence_model.basis_of(col.field)
                col.badge = evidence_model.BASIS_SHORT[basis]
                col.badge_tooltip = "%s (%s) — %s" % (
                    col.badge, basis.capitalize(), evidence_model.BASIS_DEFINITION[basis])

        self.header = ViewHeader("trash", "Deleted Records")
        self.caveat = CaveatLine()

        self.recover_button = QPushButton("Recover deleted records…")
        self.recover_button.setIcon(glyphs.icon("trash", theme.color("primary"), 15))
        theme.mark_accent(self.recover_button)
        self._scanned = False
        # A minimum width that holds both of the button's texts, so
        # switching between "Recover deleted records…" and "Recovering…"
        # (set_scanning) never clips. Measured with sizeHint() after the
        # accent style is applied, so the bold weight and the icon are
        # included (tests/test_same_tick_clipping.py).
        self.recover_button.ensurePolished()
        floor = 0
        for text in ("Recovering…", "Recover deleted records…",
                     "Run recovery again…"):
            self.recover_button.setText(text)
            floor = max(floor, self.recover_button.sizeHint().width())
        self.recover_button.setMinimumWidth(floor)
        self.recover_button.setText("Recover deleted records…")
        self.recover_button.clicked.connect(self.recoverRequested.emit)
        self.filter_box = QLineEdit(placeholderText="Filter these records…")
        self._funnel_action = self.filter_box.addAction(
            glyphs.icon("funnel", theme.color("primary"), 15),
            QLineEdit.LeadingPosition)
        self.count_label = copyable.selectable(QLabel(""))
        self.count_label.setStyleSheet("font-size: 12px; background: transparent;")
        clear = QPushButton("Clear all filters")
        self.export_button = QPushButton("Export view")
        self.export_button.setIcon(
            glyphs.icon("download", theme.color("primary"), 15))
        theme.mark_outline(self.export_button)
        self.export_button.clicked.connect(self.exportRequested.emit)
        self.wrap_button = make_wrap_button()
        self.wrap_button.toggled.connect(self.wrapToggled.emit)
        self.table = RecordsTable()

        top = QHBoxLayout()
        top.addWidget(self.recover_button)
        top.addStretch(1)

        self.method_buttons = {}
        chips = QHBoxLayout()
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, label in (("all", "All methods"), ("structured", "Structured"),
                           ("strings", "String carves"),
                           ("stubs", "Deleted-record stubs")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(key == "all")
            button.clicked.connect(lambda _c=False, k=key: self._method(k))
            group.addButton(button)
            chips.addWidget(button)
            self.method_buttons[key] = button
        self.chip_high_confidence = QuickFilterChip("High confidence only")
        self.chip_high_confidence.toggled.connect(self._confidence)
        chips.addWidget(self.chip_high_confidence)
        self.identical_chip = copyable.selectable(QLabel(""))
        self.identical_chip.setWordWrap(True)
        self.identical_chip.setVisible(False)
        self.identical_chip.setStyleSheet(constant_note_style())
        chips.addWidget(self.identical_chip, 1)

        bar = QHBoxLayout()
        bar.addWidget(self.filter_box, 1)
        bar.addWidget(self.wrap_button)
        bar.addWidget(clear)
        bar.addWidget(self.export_button)

        root = QVBoxLayout(self)
        root.addWidget(self.header)
        root.addLayout(top)
        root.addLayout(chips)
        root.addLayout(bar)
        root.addWidget(self.count_label)
        root.addWidget(self.caveat)
        root.addWidget(self.table, 1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._apply_text)
        self.filter_box.textChanged.connect(self._text_changed)
        self.filter_box.returnPressed.connect(self._apply_text)
        clear.clicked.connect(self.clear_all_filters)
        self.table.clearFiltersRequested.connect(self.clear_all_filters)
        self.table.identicalColumnsChanged.connect(self._identical_changed)
        QShortcut(QKeySequence.Find, self, self.filter_box.setFocus)
        QShortcut(QKeySequence(Qt.Key_Escape), self.filter_box,
                  self.clear_all_filters)

        # set_records() is not called here: a model with every column's
        # width applied before any exhibit is open would raise this view's
        # minimum size, and so the QStackedWidget's. MainWindow calls
        # set_records([], note=NOT_SCANNED_NOTE) after the first evidence
        # load, as it fills HistoryView.
        self._note = None

    def refresh_theme(self):
        """Repaint this view's drawn icons and the table for the current
        theme (as HistoryView.refresh_theme)."""
        self.header.refresh_theme()
        self.caveat.refresh_theme()
        self._funnel_action.setIcon(glyphs.icon("funnel", theme.color("primary"), 15))
        self.recover_button.setIcon(glyphs.icon("trash", theme.color("primary"), 15))
        self.export_button.setIcon(
            glyphs.icon("download", theme.color("primary"), 15))
        # the chip draws its own fill; the method buttons'
        # checked look is the app stylesheet's.
        self.chip_high_confidence.refresh_theme()
        # The hidden-columns note: the same pill every view uses.
        self.identical_chip.setStyleSheet(constant_note_style())
        # Font metrics change with the theme: wrapped rows are re-measured.
        self.table.refit_rows()
        self.table.viewport().update()

    def set_caveat(self, text):
        """Set the caveat line (as HistoryView.set_caveat)."""
        self.caveat.set_text(text)

    def set_scanning(self, running):
        """The action disabled while a scan is running, re-enabled on
        every exit path (success, cancel, failure) -- MainWindow calls
        this on each of those, mirroring how it already disables/
        re-enables open_evidence_action around an evidence load."""
        self.recover_button.setEnabled(not running)
        if running:
            self.recover_button.setText("Recovering…")
        elif self._scanned:
            self.recover_button.setText("Run recovery again…")
        else:
            self.recover_button.setText("Recover deleted records…")

    def set_records(self, rows, note=None):
        self._note = note
        if note != NOT_SCANNED_NOTE and not self._scanned:
            # once the scan has run the big green button is quiet.
            self._scanned = True
            theme.unmark(self.recover_button, "accent")
            theme.mark_outline(self.recover_button)
            self.set_scanning(False)
        self.table.set_records(self.COLUMNS, rows)
        self.table.set_hide_identical(True)
        self._method(self._method_key())
        self._confidence(self.chip_high_confidence.isChecked())
        self.table.sort_by_key("Timestamp", True)
        # Two reasons the table can show zero rows (see
        # SCAN_FOUND_NOTHING_NOTE): MainWindow passes NOT_SCANNED_NOTE only
        # before the first scan, and no matching note once a scan has run
        # (main_window._on_recovery_loaded).
        self.table.set_empty_reason(
            NOT_SCANNED_NOTE if note == NOT_SCANNED_NOTE else SCAN_FOUND_NOTHING_NOTE)
        self.table.model().layoutRefreshed.connect(self._update_count)
        # set_records() builds a new RecordTableModel/RecordFilter on every
        # recovery merge, so the filter text in the box is re-applied to it;
        # otherwise the box would show a filter the table no longer
        # applies. A no-op when the box is empty.
        self.table.model().set_text(self.filter_box.text())
        self.header.set_subtitle(
            "%s recovered record%s. Each row shows its source file and "
            "carve confidence."
            % (format(len(rows), ","), "" if len(rows) == 1 else "s"))
        self._update_count()

    _METHOD_KINDS = {"all": None, "structured": {K_CARVED_STRUCT},
                     "strings": {K_CARVED_STRING}, "stubs": {K_TOMBSTONE}}

    def _method_key(self):
        for key, button in self.method_buttons.items():
            if button.isChecked():
                return key
        return "all"

    def _method(self, key):
        model = self.table.model()
        if model is not None:
            model.filter.extra_labels.setdefault("_kind", "Method")
            model.set_values("_kind", self._METHOD_KINDS[key])

    def _confidence(self, checked):
        model = self.table.model()
        if model is not None:
            model.set_values("Confidence", {"high"} if checked else None)

    def _identical_changed(self):
        found = self.table.identical_columns()
        hidden = [(c, v) for c, v in found
                  if c.key in self.table.auto_hidden_keys()]
        parts = [constant_text(c, v) for c, v in hidden]
        # columns empty in every row fold away too, and
        # are named here.
        blank = [c.label for c in self.table.blank_columns()
                 if c.key in self.table.auto_hidden_keys()]
        if blank:
            parts.append("empty in every row: %s" % ", ".join(blank))
        self.identical_chip.setText(
            "Hidden, identical in all rows: %s" % "; ".join(parts)
            if parts else "")
        self.identical_chip.setToolTip(self.identical_chip.text())
        self.identical_chip.setVisible(bool(parts))
        self._widen_url()

    def _widen_url(self):
        """The URL takes the width of the columns that gave way -- but ONLY
        as much as the provenance columns (File .. Confidence) leave spare
        in the viewport. A hidden column's whole width is not free: handing
        all of it to the URL pushed Confidence 170 px past the edge in a
        1,328 px view, the one thing this view must never do. Declared
        widths name what gave way (a hidden section reports 0); the live
        section sizes say what is spare. Re-run on resize."""
        model = self.table.model()
        if model is None:
            return
        columns = model.columns
        keys = [c.key for c in columns]
        hidden = self.table.auto_hidden_keys()
        extra = sum(c.width or 0 for c in columns if c.key in hidden)
        header = self.table.horizontalHeader()
        url = keys.index("CleanUrl")
        through = keys.index("Confidence")
        used = sum(header.sectionSize(i) for i in range(through + 1)
                   if i != url)
        spare = max(0, self.table.viewport().width() - used - 174 - 16)
        target = 174 + min(extra, spare)
        if header.sectionSize(url) != target:
            header.resizeSection(url, target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._widen_url()

    def showEvent(self, event):
        super().showEvent(event)
        self._widen_url()

    def _text_changed(self, _text):
        model = self.table.model()
        if model is not None and model.filter.total_count <= LIVE_FILTER_MAX_ROWS:
            self._apply_text()
        else:
            self._debounce.start(DEBOUNCE_MS)

    def _apply_text(self):
        self._debounce.stop()
        model = self.table.model()
        if model is not None:
            model.set_text(self.filter_box.text())

    def clear_all_filters(self):
        self.filter_box.clear()
        self.table.close_filter_popup()
        model = self.table.model()
        if model is not None:
            model.clear_all()
        self.method_buttons["all"].setChecked(True)
        self.chip_high_confidence.setChecked(False)

    def _update_count(self):
        model = self.table.model()
        if model is None:
            return
        shown, total = model.rowCount(), model.filter.total_count
        if shown == total:
            text = "{:,} recovered records".format(total)
        else:
            text = "{:,} of {:,} recovered records".format(shown, total)
        if getattr(self, "_note", None):
            text += " — " + self._note
        self.count_label.setText(text)
        # The button counts the rows on screen, updated from the same
        # layoutRefreshed signal as the count line (as in
        # RecordsView._update_count).
        self.export_button.setText("Export view (%s)" % format(shown, ","))
        # Laid out immediately: this runs in the handler that ends a scan,
        # and the next posted LayoutRequest would come after the longer
        # text was painted clipped.
        self.layout().activate()
