"""Integrity: hashes, source state and the parse log. A clean parse is
not a complete database, and the view's caveat says so.

Three cards (widgets/card.py):

Source Integrity: database state, the read-only guarantee, the derived
machine time zone and the three parse_stats counters, as label and
selectable value rows. A view may not import another view
(test_structure.py), so the row helper is local to this module.

SHA-256 Source Hashes: one row per file WebCacheParser hashed on open,
each naming its role (the database, a transaction log, the checkpoint;
see integrity_loader.hash_rows) beside a monospaced, selectable SHA-256.

Parsing Decision Log: WebCacheParser.decision_log, every line in order,
with skipped tables and record errors in the warning colour
(integrity_loader.decision_log_rows' "flagged" field). A QListWidget,
which scrolls within its own card, because the log's length varies with
the exhibit.

Before set_data() is called, every card states that there is nothing to
show yet.
"""
import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from ..shell import integrity_loader, theme
from ..widgets import copyable
from ..widgets.card import Card
from ..widgets.content_header import CaveatLine, ViewHeader

#: The monospace stack used for every hash, hex and path value in the
#: application.
_MONO_STYLE = "font-family: 'Cascadia Mono', Consolas, monospace;"


def _muted_line(text):
    lbl = copyable.selectable(QLabel(text))
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        "background: transparent; font-size: 12px; color: %s;"
        % theme.PALETTES[theme.current_name()]["muted"])
    return lbl


def _clear_layout(layout):
    """Remove and delete every item in `layout`. A view may not import
    another view, so this helper is local."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
        else:
            sub = item.layout()
            if sub is not None:
                _clear_layout(sub)


class _LogList(QListWidget):
    """The decision log: lines can be selected, and Ctrl+C copies the
    selected lines in log order."""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            rows = sorted(self.row(item) for item in self.selectedItems()
                          if item.flags() & Qt.ItemIsSelectable)
            if rows:
                QGuiApplication.clipboard().setText(
                    "\n".join(self.item(r).text() for r in rows))
            return
        super().keyPressEvent(event)


class IntegrityView(QWidget):
    #: The report text, for the shell to save where the examiner chooses.
    saveTextRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._info = None
        self._source_rows = []
        self._hash_rows = []

        self.header = ViewHeader("shield", "Integrity")
        self.caveat = CaveatLine()

        self.card_source = Card("shield", "Source Integrity")
        self.card_hashes = Card("lock", "SHA-256 Source Hashes")
        self.card_log = Card("file", "Parsing Decision Log")
        self.card_clock = Card("clock", "Clock")

        self._log_list = _LogList()
        self._log_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._log_list.setWordWrap(True)
        self._log_list.setTextElideMode(Qt.ElideNone)
        self._log_list.setFocusPolicy(Qt.ClickFocus)
        self._log_list.setToolTip("Select lines and press Ctrl+C to copy them")

        # The whole screen as text, every value in full.
        self.copy_report_button = QPushButton("Copy report")
        self.copy_report_button.setToolTip(
            "Copy every card and the whole decision log as text")
        self.copy_report_button.clicked.connect(self.copy_report)
        self.save_report_button = QPushButton("Save as text…")
        self.save_report_button.setToolTip(
            "Save every card and the whole decision log as a text file")
        self.save_report_button.clicked.connect(
            lambda: self.saveTextRequested.emit(self.report_text()))
        # The caveat and the report buttons share one line.
        actions = QHBoxLayout()
        actions.addWidget(self.caveat, 1)
        actions.addWidget(self.copy_report_button, 0, Qt.AlignTop)
        actions.addWidget(self.save_report_button, 0, Qt.AlignTop)
        self.card_log.body.addWidget(self._log_list)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addWidget(self.card_source, 1)
        top_row.addWidget(self.card_hashes, 1)

        root = QVBoxLayout(self)
        root.addWidget(self.header)
        root.addLayout(actions)
        root.addLayout(top_row)
        root.addWidget(self.card_clock)
        root.addWidget(self.card_log, 1)

        self.refresh_theme()

    # --- caveat / theme -----------------------------------------------

    def set_caveat(self, text):
        self.caveat.set_text(text)

    def refresh_theme(self):
        """Repaint for the current theme. Rows bake their colours in, so
        set_data() is re-run with the last data given, or the empty state
        is re-rendered before any data has been given."""
        self.header.refresh_theme()
        self.caveat.refresh_theme()
        self.card_source.refresh_theme()
        self.card_hashes.refresh_theme()
        self.card_log.refresh_theme()
        self.card_clock.refresh_theme()
        if self._info is None:
            self._render_empty()
        else:
            self.set_data(self._info)

    # --- data ------------------------------------------------------------

    def report_text(self):
        """The screen as plain text; "" when no evidence is open."""
        if self._info is None:
            return ""
        now = datetime.datetime.now(datetime.timezone.utc)
        return integrity_loader.report_text(
            self._info, now.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def copy_report(self):
        QGuiApplication.clipboard().setText(self.report_text())

    def set_data(self, info):
        """`info` is WebCacheParser.get_database_info()'s dict, or None
        when no evidence is open."""
        self._info = info
        self.copy_report_button.setEnabled(info is not None)
        self.save_report_button.setEnabled(info is not None)
        if info is None:
            self._render_empty()
            return

        source_rows = integrity_loader.source_integrity_rows(info)
        hash_rows = integrity_loader.hash_rows(info)
        log_rows = integrity_loader.decision_log_rows(info)

        self.header.set_subtitle(
            "%s source file(s) hashed; %s parsing decision(s) logged."
            % (format(len(hash_rows), ","), format(len(log_rows), ",")))

        self._render_source(source_rows)
        self._clock_rows = self._render_rows(
            self.card_clock, integrity_loader.clock_rows(info))
        self._render_hashes(hash_rows)
        self._render_log(log_rows)

    # --- Source Integrity card -------------------------------------------

    def _render_source(self, rows):
        self._source_rows = self._render_rows(self.card_source, rows)

    def _render_rows(self, card, rows):
        """Label and selectable value rows into `card`; returns the
        (label, value) widget pairs."""
        _clear_layout(card.body)
        made = []
        p = theme.PALETTES[theme.current_name()]
        # Sized to the widest label, measured with the real font, so no
        # label is clipped.
        fm = QFontMetrics(QLabel().font())
        label_width = max(
            (fm.horizontalAdvance(row["label"]) for row in rows), default=0) + 8
        for row in rows:
            line = QHBoxLayout()
            line.setSpacing(6)
            label_widget = copyable.selectable(QLabel(row["label"]))
            label_widget.setFixedWidth(label_width)
            label_widget.setStyleSheet(
                "background: transparent; color: %s;" % p["muted"])
            # Selectable and copyable, so a value can be put in a report.
            value_widget = QLabel(row["value"])
            value_widget.setWordWrap(True)
            copyable.selectable(value_widget)
            value_widget.setStyleSheet("background: transparent;")
            if row["tooltip"]:
                label_widget.setToolTip(row["tooltip"])
                value_widget.setToolTip(row["tooltip"])
            line.addWidget(label_widget)
            line.addWidget(value_widget, 1)
            card.body.addLayout(line)
            made.append((label_widget, value_widget))
        card.body.addStretch(1)
        return made

    # --- SHA-256 Source Hashes card ---------------------------------------

    def _render_hashes(self, rows):
        _clear_layout(self.card_hashes.body)
        self._hash_rows = []
        p = theme.PALETTES[theme.current_name()]
        for row in rows:
            block = QVBoxLayout()
            block.setSpacing(1)

            head = QHBoxLayout()
            head.setSpacing(8)
            file_label = copyable.selectable(QLabel(row["File"]))
            file_label.setStyleSheet(
                "background: transparent; font-weight: 600;")
            role_label = copyable.selectable(QLabel(row["Role"]))
            role_label.setWordWrap(True)
            role_label.setStyleSheet(
                "background: transparent; font-size: 11px; color: %s;"
                % p["muted"])
            head.addWidget(file_label)
            head.addWidget(role_label, 1)
            block.addLayout(head)

            hash_label = QLabel(row["SHA256"])
            hash_label.setWordWrap(True)
            copyable.selectable(hash_label)
            hash_label.setStyleSheet(
                "%s font-size: 11px; background: transparent; color: %s;"
                % (_MONO_STYLE, p["muted2"]))
            block.addWidget(hash_label)

            self.card_hashes.body.addLayout(block)
            self._hash_rows.append(
                {"file": file_label, "role": role_label, "hash": hash_label})
        if not self._hash_rows:
            self.card_hashes.body.addWidget(
                _muted_line("No source files were hashed for this exhibit."))
        self.card_hashes.body.addStretch(1)

    # --- Parsing Decision Log card -----------------------------------------

    def _render_log(self, rows):
        self._log_list.clear()
        p = theme.PALETTES[theme.current_name()]
        for row in rows:
            item = QListWidgetItem(row["text"])
            item.setForeground(
                theme.color("warn") if row["flagged"] else theme.color("text"))
            self._log_list.addItem(item)
        if not rows:
            empty = QListWidgetItem("No decision-log entries for this exhibit.")
            empty.setForeground(theme.color("muted"))
            empty.setFlags(Qt.NoItemFlags)
            self._log_list.addItem(empty)

    # --- the no-evidence state ---------------------------------------------

    def _render_empty(self):
        self.copy_report_button.setEnabled(False)
        self.save_report_button.setEnabled(False)
        self.header.set_subtitle("No evidence loaded yet.")
        self._source_rows = []
        self._hash_rows = []
        for card, text in (
            (self.card_source, "Open evidence to see source integrity."),
            (self.card_hashes, "Open evidence to see source hashes."),
            (self.card_clock, "Open evidence to see the clock offsets the "
                              "records show."),
        ):
            _clear_layout(card.body)
            card.body.addWidget(_muted_line(text))
            card.body.addStretch(1)
        # Cleared rather than filled with the empty-log row: no evidence
        # is open, which is a different fact from an open exhibit whose
        # decision log is empty.
        self._log_list.clear()
