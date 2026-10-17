"""Export & Report: every export format, the bundle, and the case fields.

This module imports shell.export_formats for the catalogue only (strings,
booleans and group names, never an engine object or a writer) and never
imports forensic_engine. The view reports what the examiner asked for
through three signals; MainWindow performs the export, and the nine
setters here only paint.

Every declared format always has a card. A format that cannot run on this
exhibit keeps its card and its place in the grid, greyed, with the reason:
set_available(False, reason) repaints the title, icon, a warning line, the
button's enabled state and tooltip, and the border.

There is no "Open folder" button: an export path is copied, never opened.
The result strip names the full path and offers Copy path.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ..shell import export_formats as F
from ..shell import glyphs, theme
from ..widgets import copyable
from ..widgets.card import Card
from ..widgets.content_header import CaveatLine, ViewHeader

#: How long (ms) the case-metadata fields wait before emitting. A
#: GUI-thread QTimer, never a timer thread.
CASE_DEBOUNCE_MS = 400

#: (attribute, label, meta key) for the four case fields.
CASE_FIELDS = (
    ("examiner_field", "Examiner", "examiner"),
    ("case_field", "Case number", "case_number"),
    ("evidence_field", "Evidence ID", "evidence_id"),
    ("notes_field", "Methodology notes", "notes"),
)

#: What belongs in each case field, shown while it is empty. The label above
#: stays: a hint disappears once the examiner starts typing.
CASE_HINTS = {
    "examiner_field": "Your name, as it should appear on the report",
    "case_field": "Your agency's case reference",
    "evidence_field": "The exhibit or item number of this image",
    "notes_field": "How the evidence was acquired and examined, "
                   "e.g. imaging tool, write blocker, hash verified",
}

#: Shown when there is no case file to save the case fields to.
NO_CASE_REASON = (
    "Metadata is stored in the case file, which is keyed by the evidence "
    "SHA-256. Open a database first.")



#: What a "leak file" is, where the coverage line counts them.
LEAK_FILES_NOTE = ("Leak files are rows of the LeakFiles table: cache files "
                   "Windows could not delete because they were locked when "
                   "the cache was cleared, so they can outlive a clearing.")

class FormatCard(Card):
    """One format, as a card that always stays on the page.

    `available` records whether the format can run, separately from the
    button's enabled state, because "busy" also disables the button:
    set_busy(False) restores the button to what availability says, not to
    enabled.
    """
    exportRequested = Signal(str)

    #: Class defaults: Card.__init__ calls refresh_theme(), which this
    #: class overrides, before the body of __init__ below runs. _built
    #: tells the override that the body is not built yet.
    available = True
    _busy = False
    _blocked = False
    _built = False

    def __init__(self, fmt, parent=None):
        super().__init__(fmt.icon, fmt.title, parent)
        self.fmt = fmt
        self.available = True
        self._busy = False
        self._blocked = False

        self.description_label = copyable.selectable(QLabel(fmt.description))
        self.description_label.setWordWrap(True)
        self.body.addWidget(self.description_label)

        #: The second line, in warn, carrying the reason verbatim. Present
        #: in the layout from construction and merely hidden, so becoming
        #: unavailable never reflows the grid around it.
        self.reason_label = copyable.selectable(QLabel(""))
        self.reason_label.setWordWrap(True)
        self.reason_label.setVisible(False)
        self.body.addWidget(self.reason_label)

        self.busy_label = copyable.selectable(QLabel(""))
        self.busy_label.setWordWrap(True)
        self.busy_label.setVisible(False)
        self.body.addWidget(self.busy_label)

        #: A third line, separate from reason_label. reason_label states
        #: whether the format can run on this exhibit, and only
        #: set_available(False, ...) writes it. A failed write (a locked
        #: destination, a full disk) concerns this attempt only, so it is
        #: shown here and the format stays available (see
        #: report_failure).
        self.error_label = copyable.selectable(QLabel(""))
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self.body.addWidget(self.error_label)

        self.body.addStretch(1)

        row = QHBoxLayout()
        self.button = QPushButton(
            "Export…" if fmt.writes == "file" else "Choose folder…")
        self.button.clicked.connect(
            lambda: self.exportRequested.emit(self.fmt.key))
        row.addWidget(self.button)
        row.addStretch(1)
        self.body.addLayout(row)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._built = True
        self.refresh_theme()

    def set_available(self, ok, reason=""):
        """Never hides, never removes -- see the module docstring."""
        self.available = bool(ok)
        self.reason_label.setText("" if ok else (reason or ""))
        self.reason_label.setVisible(not ok and bool(reason))
        self.button.setToolTip("" if ok else (reason or ""))
        self._sync_button()
        self.refresh_theme()

    def set_busy(self, busy, message=""):
        self._busy = bool(busy)
        self.busy_label.setText(message or "")
        self.busy_label.setVisible(bool(busy) and bool(message))
        if busy:
            # A FRESH attempt starting clears whatever the previous one
            # failed with -- otherwise a stale error would sit on screen
            # forever once the examiner tries again, arguing with a busy
            # label describing a write already in progress.
            self.error_label.setText("")
            self.error_label.setVisible(False)
        self._sync_button()

    def report_failure(self, message):
        """Show a write failure for this attempt (a destination locked by
        another program, a read-only volume). Not routed through
        set_available: the format can still run, so the button stays
        enabled and the examiner can retry. The message stays on screen in
        error_label, which set_available never touches.
        """
        self.error_label.setText(message or "")
        self.error_label.setVisible(bool(message))
        self._sync_button()

    def set_blocked(self, blocked):
        """Disable the button while any export is running anywhere in the
        application (ExportView.set_export_running), not only this card's.
        A third condition alongside available and busy, which it never
        overwrites; when the running export ends, the button returns to
        what those two say.
        """
        self._blocked = bool(blocked)
        self.button.setToolTip(
            "Another export is already running." if blocked
            else ("" if self.available else (self.reason_label.text() or "")))
        self._sync_button()

    def _sync_button(self):
        self.button.setEnabled(
            self.available and not self._busy and not self._blocked)

    def refresh_theme(self):
        """Every drawn pixel this card owns. Card.refresh_theme repaints
        the icon and the frame; the three overrides below are the ones
        that carry availability, and each is set from the palette rather
        than from a hex literal so a theme switch reaches them too."""
        super().refresh_theme()
        if not self._built:
            # Reached from Card.__init__ before this card has a body. The
            # base has painted the frame and icon; the availability styling
            # is applied by the refresh_theme() call at the end of __init__.
            return
        p = theme.PALETTES[theme.current_name()]
        role = "muted" if not self.available else "primary"
        self._icon_label.setPixmap(
            glyphs.pixmap(self._icon_name, theme.color(role), 14))
        self._title_label.setStyleSheet(
            "font-size: 12px; font-weight: 600; background: transparent; "
            "color: %s;" % (p["muted"] if not self.available else p["text"]))
        self.description_label.setStyleSheet(
            "font-size: 11.5px; background: transparent; color: %s;"
            % p["muted"])
        self.reason_label.setStyleSheet(
            "font-size: 11.5px; background: transparent; color: %s;"
            % p["warn"])
        self.busy_label.setStyleSheet(
            "font-size: 11.5px; background: transparent; color: %s;"
            % p["primary_text"])
        self.error_label.setStyleSheet(
            "font-size: 11.5px; background: transparent; color: %s;"
            % p["error"])
        border = p["border"] if not self.available else p["primary"]
        self.setStyleSheet(
            "QFrame#dashCard { background: %s; border: 1px solid %s; "
            "border-radius: 8px; } "
            "QFrame#dashCardHeader { background: %s; "
            "border-top-left-radius: 7px; border-top-right-radius: 7px; "
            "border-bottom: 1px solid %s; }"
            % (p["base"], border, p["alt_base"], p["border"]))


class ExportView(QWidget):
    """The page. Three signals out; everything else is a setter in."""

    #: An examiner asked for one format (or the bundle). MainWindow
    #: decides what that means -- see the module docstring.
    exportRequested = Signal(str)
    #: (meta key, value) after the debounce. MainWindow writes it into
    #: the CaseDb; this view never touches a file.
    caseMetaChanged = Signal(str, str)
    #: Copy, never Open.
    copyPathRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.coverage_text = ""
        self._field_count = None
        self.cards = {}
        self.group_labels = {}
        self._grids = {}
        self._written_paths = []

        self.header = ViewHeader("download", "Export & Report")
        self.caveat = CaveatLine()

        page = QWidget()
        self._page_layout = QVBoxLayout(page)
        self._page_layout.setContentsMargins(0, 0, 12, 0)
        self._page_layout.setSpacing(14)

        self._build_case_card()
        self._build_bundle_card()
        for group in (F.G_COURT, F.G_GENERAL, F.G_POSITION):
            self._build_group(group)
        self._build_result_strip()
        self._build_footnote()
        self._page_layout.addStretch(1)

        # Nine cards plus the metadata card and the bundle card do not fit
        # a 900px window -- the page scrolls rather than the cards
        # shrinking into unreadability.
        self.scroll = QScrollArea()
        self.scroll.setObjectName("keyScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(page)

        root = QVBoxLayout(self)
        root.addWidget(self.header)
        root.addWidget(self.caveat)
        root.addWidget(self.scroll, 1)

        self._case_timers = {}
        self._wire_case_fields()
        self.refresh_theme()

    # --- construction ---------------------------------------------------

    def _build_case_card(self):
        self.case_card = Card("shield",
                              "Case metadata — stamped into every export")
        self.case_note_label = copyable.selectable(QLabel(NO_CASE_REASON))
        self.case_note_label.setWordWrap(True)
        self.case_card.body.addWidget(self.case_note_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for i, (attr, label, _key) in enumerate(CASE_FIELDS[:3]):
            widget = QLineEdit()
            widget.setPlaceholderText(CASE_HINTS[attr])
            setattr(self, attr, widget)
            grid.addWidget(copyable.selectable(QLabel(label)), 0, i)
            grid.addWidget(widget, 1, i)
        self.notes_field = QPlainTextEdit()
        self.notes_field.setPlaceholderText(CASE_HINTS["notes_field"])
        self.notes_field.setFixedHeight(66)          # three lines
        grid.addWidget(copyable.selectable(QLabel("Methodology notes")), 2, 0, 1, 3)
        grid.addWidget(self.notes_field, 3, 0, 1, 3)
        self.case_card.body.addLayout(grid)
        self._page_layout.addWidget(self.case_card)
        self.set_case_enabled(False, NO_CASE_REASON)

    def _build_bundle_card(self):
        fmt = F.BY_KEY["bundle"]
        self.bundle_card = Card("download", "Complete case bundle")
        body = copyable.selectable(QLabel(
            "Writes: " + ", ".join(name for _k, _l, name in F.BUNDLE_MEMBERS)))
        body.setWordWrap(True)
        self.bundle_members_label = body
        self.bundle_card.body.addWidget(body)
        extra = copyable.selectable(
            QLabel("plus a SHA-256 manifest of every file written."))
        extra.setWordWrap(True)
        self.bundle_manifest_label = extra
        self.bundle_card.body.addWidget(extra)
        self.bundle_coverage_label = copyable.selectable(QLabel(""))
        self.bundle_coverage_label.setWordWrap(True)
        self.bundle_card.body.addWidget(self.bundle_coverage_label)
        self.bundle_reason_label = copyable.selectable(QLabel(""))
        self.bundle_reason_label.setWordWrap(True)
        self.bundle_reason_label.setVisible(False)
        self.bundle_card.body.addWidget(self.bundle_reason_label)
        #: The bundle's error_label (see FormatCard.error_label).
        self.bundle_error_label = copyable.selectable(QLabel(""))
        self.bundle_error_label.setWordWrap(True)
        self.bundle_error_label.setVisible(False)
        self.bundle_card.body.addWidget(self.bundle_error_label)
        row = QHBoxLayout()
        self.bundle_button = QPushButton("Export bundle…")
        theme.mark_accent(self.bundle_button)
        self.bundle_button.clicked.connect(
            lambda: self.exportRequested.emit("bundle"))
        row.addWidget(self.bundle_button)
        row.addStretch(1)
        self.bundle_card.body.addLayout(row)
        # The bundle is a catalogue entry like any other, so it is in
        # self.cards and set_availability/set_busy/report_failed reach it.
        # Its card is a plain Card, so a small adapter gives it the same
        # interface.
        self.cards["bundle"] = _BundleCardAdapter(self, fmt)
        self._page_layout.addWidget(self.bundle_card)

    def _build_group(self, group):
        label = copyable.selectable(QLabel(group))
        self.group_labels[group] = label
        self._page_layout.addWidget(label)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self._grids[group] = grid
        for i, fmt in enumerate(F.formats_in(group)):
            card = FormatCard(fmt)
            card.exportRequested.connect(self.exportRequested)
            self.cards[fmt.key] = card
            grid.addWidget(card, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._page_layout.addLayout(grid)

    def _build_result_strip(self):
        self.result_line = QLabel("")
        self.result_line.setWordWrap(True)
        copyable.selectable(self.result_line)
        self.copy_path_button = QPushButton("Copy path")
        self.copy_path_button.setEnabled(False)
        self.copy_path_button.clicked.connect(self._emit_copy_path)
        theme.mark_outline(self.copy_path_button)
        row = QHBoxLayout()
        row.addWidget(self.result_line, 1)
        row.addWidget(self.copy_path_button, 0, Qt.AlignTop)
        self._page_layout.addLayout(row)

    def _build_footnote(self):
        self.footnote_label = copyable.selectable(QLabel(""))
        self.footnote_label.setWordWrap(True)
        self._page_layout.addWidget(self.footnote_label)
        self._refresh_footnote()

    def _wire_case_fields(self):
        for attr, _label, key in CASE_FIELDS:
            widget = getattr(self, attr)
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(CASE_DEBOUNCE_MS)
            timer.timeout.connect(lambda k=key: self._emit_case_meta(k))
            self._case_timers[key] = timer
            signal = (widget.textChanged if isinstance(widget, QLineEdit)
                      else widget.textChanged)
            signal.connect(lambda *_a, t=timer: t.start())

    # --- MainWindow's setters -------------------------------------------

    def set_coverage(self, counts):
        """The coverage text, used for the header subtitle and the bundle
        card's "Covers:" line.

        `recovered` is None before any scan has run, and the text then
        says "deleted records not yet recovered" rather than 0.
        """
        counts = counts or {}
        recovered = counts.get("recovered")
        recovered_text = ("deleted records not yet recovered"
                          if recovered is None
                          else "%s recovered" % format(recovered, ","))
        def n(key, one, many):
            value = counts.get(key, 0) or 0
            return "%s %s" % (format(value, ","), one if value == 1 else many)

        # The nouns the Cookies & HSTS tabs use, so one thing is not called
        # two names; "leak files" names the table they come from.
        self.coverage_text = " · ".join((
            n("records", "record", "records"),
            n("cookies", "cookie", "cookies"),
            n("hsts", "HSTS pin", "HSTS pins"),
            n("certs", "certificate", "certificates"),
            n("leaks", "leak file", "leak files"),
            recovered_text))
        self.header.set_subtitle(self.coverage_text)
        self.bundle_coverage_label.setText("Covers: %s" % self.coverage_text)
        self.bundle_coverage_label.setToolTip(LEAK_FILES_NOTE)
        self.header._subtitle.setToolTip(LEAK_FILES_NOTE)

    def set_case_meta(self, meta):
        """Fill the four fields from the case file WITHOUT emitting.

        blockSignals throughout: restoring what an examiner typed in a
        previous session must not read to the rest of the application as
        them typing it again, which would write it straight back into the
        case file and, worse, would fire on every Open Evidence.
        """
        meta = meta or {}
        for attr, _label, key in CASE_FIELDS:
            widget = getattr(self, attr)
            widget.blockSignals(True)
            try:
                if isinstance(widget, QLineEdit):
                    widget.setText(meta.get(key, "") or "")
                else:
                    widget.setPlainText(meta.get(key, "") or "")
            finally:
                widget.blockSignals(False)

    def set_case_enabled(self, enabled, reason=""):
        for attr, _label, _key in CASE_FIELDS:
            getattr(self, attr).setEnabled(bool(enabled))
        self.case_note_label.setText(
            "" if enabled else (reason or NO_CASE_REASON))
        self.case_note_label.setVisible(not enabled)

    def set_availability(self, mapping):
        for key, (ok, reason) in (mapping or {}).items():
            card = self.cards.get(key)
            if card is not None:
                card.set_available(ok, reason)

    def set_export_running(self, running):
        """Called by MainWindow when any export starts (and with False when
        it ends): every card on this page, the bundle included, becomes
        unavailable together. See FormatCard.set_blocked and
        _BundleCardAdapter.set_blocked."""
        for card in self.cards.values():
            card.set_blocked(running)

    def set_busy(self, key, busy, message=""):
        card = self.cards.get(key)
        if card is not None:
            card.set_busy(busy, message)

    def report_written(self, paths, summary):
        self._written_paths = [str(p) for p in (paths or [])]
        if not self._written_paths:
            self.result_line.setText(summary or "")
            self.copy_path_button.setEnabled(False)
            return
        names = ", ".join(_basename(p) for p in self._written_paths)
        self.result_line.setText(
            "%s\n%s\n%s" % (summary or "", self._written_paths[0], names))
        self.copy_path_button.setEnabled(True)

    def report_failed(self, key, message):
        """Show the failure text as the card's error message
        (report_failure), never as its unavailable reason (set_available):
        a write failure concerns this attempt, not whether the format can
        run, so the button stays enabled."""
        card = self.cards.get(key)
        if card is not None:
            card.set_busy(False)
            card.report_failure(message)
        self.result_line.setText(message or "")
        self.copy_path_button.setEnabled(bool(self._written_paths))

    def set_field_count(self, count):
        self._field_count = count
        self._refresh_footnote()

    def set_caveat(self, text):
        self.caveat.set_text(text)

    def flush_case_meta(self):
        """Emit every pending case field now, as the 400 ms timers would.
        Called by tests, and by MainWindow before it closes a case file, so
        a value typed just before Open Evidence is kept."""
        for key, timer in self._case_timers.items():
            if timer.isActive():
                timer.stop()
            self._emit_case_meta(key)

    # --- internals -------------------------------------------------------

    def grid_for(self, group):
        return self._grids.get(group)

    def _emit_case_meta(self, key):
        for attr, _label, meta_key in CASE_FIELDS:
            if meta_key != key:
                continue
            widget = getattr(self, attr)
            value = (widget.text() if isinstance(widget, QLineEdit)
                     else widget.toPlainText())
            self.caseMetaChanged.emit(key, value)

    def _emit_copy_path(self):
        if self._written_paths:
            self.copyPathRequested.emit(self._written_paths[0])

    def _refresh_footnote(self):
        # The same column rule the sidecar's "Column total" line states,
        # so the footnote, sidecar and file agree.
        count = ("all %d canonical fields" % self._field_count
                 if self._field_count else "every canonical field")
        self.footnote_label.setText(
            "Engine exports carry %s and the case metadata above. A view "
            "export carries the view's own columns, then every canonical "
            "field the view does not already show — its sidecar states the "
            "arithmetic. UTC timestamps are also written in RFC 3339 "
            "(…T…Z); LOCAL values are labelled LOCAL." % count)

    def refresh_theme(self):
        self.header.refresh_theme()
        self.caveat.refresh_theme()
        self.case_card.refresh_theme()
        self.bundle_card.refresh_theme()
        self.bundle_button.setIcon(
            glyphs.icon("download", theme.color("primary"), 15))
        p = theme.PALETTES[theme.current_name()]
        for label in self.group_labels.values():
            label.setStyleSheet(
                "font-size: 11px; font-weight: 600; letter-spacing: 0.8px; "
                "background: transparent; color: %s;" % p["muted"])
        for widget, role in ((self.case_note_label, "warn"),
                             (self.bundle_reason_label, "warn"),
                             (self.bundle_error_label, "error"),
                             (self.bundle_members_label, "muted"),
                             (self.bundle_manifest_label, "muted"),
                             (self.bundle_coverage_label, "muted"),
                             (self.footnote_label, "muted2"),
                             (self.result_line, "text")):
            widget.setStyleSheet(
                "font-size: 11.5px; background: transparent; color: %s;"
                % p[role])
        self.bundle_card.setStyleSheet(
            "QFrame#dashCard { background: %s; border: 1px solid %s; "
            "border-radius: 8px; } "
            "QFrame#dashCardHeader { background: %s; "
            "border-top-left-radius: 7px; border-top-right-radius: 7px; "
            "border-bottom: 1px solid %s; }"
            % (p["base"], p["primary"], p["alt_base"], p["border"]))
        for card in self.cards.values():
            card.refresh_theme()


class _BundleCardAdapter:
    """The bundle's card: a plain Card laid out full width, since the
    bundle is one deliverable rather than one of the formats. It has the
    same set_available/set_busy/refresh_theme interface as a FormatCard,
    so set_availability() and report_failed() treat every catalogue key
    alike.
    """

    def __init__(self, view, fmt):
        self._view = view
        self.fmt = fmt
        self.available = True
        self._busy = False
        self._blocked = False

    @property
    def button(self):
        return self._view.bundle_button

    @property
    def reason_label(self):
        return self._view.bundle_reason_label

    @property
    def busy_label(self):
        return self._view.bundle_coverage_label

    @property
    def error_label(self):
        return self._view.bundle_error_label

    def set_available(self, ok, reason=""):
        self.available = bool(ok)
        self.reason_label.setText("" if ok else (reason or ""))
        self.reason_label.setVisible(not ok and bool(reason))
        self.button.setToolTip("" if ok else (reason or ""))
        self._sync()

    def set_busy(self, busy, message=""):
        self._busy = bool(busy)
        if message:
            self._view.bundle_coverage_label.setText(message)
        elif not busy:
            self._view.bundle_coverage_label.setText(
                "Covers: %s" % self._view.coverage_text)
        if busy:
            # A new attempt clears the previous attempt's failure (as in
            # FormatCard.set_busy).
            self.error_label.setText("")
            self.error_label.setVisible(False)
        self._sync()

    def report_failure(self, message):
        """As FormatCard.report_failure: never set_available, so a failed
        bundle write leaves the button enabled."""
        self.error_label.setText(message or "")
        self.error_label.setVisible(bool(message))
        self._sync()

    def set_blocked(self, blocked):
        """As FormatCard.set_blocked."""
        self._blocked = bool(blocked)
        self.button.setToolTip(
            "Another export is already running." if blocked
            else ("" if self.available else (self.reason_label.text() or "")))
        self._sync()

    def _sync(self):
        self.button.setEnabled(
            self.available and not self._busy and not self._blocked)

    def refresh_theme(self):
        pass


def _basename(path):
    text = str(path).replace("\\", "/")
    return text.rsplit("/", 1)[-1]
