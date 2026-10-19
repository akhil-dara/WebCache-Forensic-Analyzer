"""The record-table base every record-set view is built on.

It provides the filter box (live below LIVE_FILTER_MAX_ROWS, debounced by
DEBOUNCE_MS above it, on the GUI thread; see _text_changed),
clear_all_filters, the count line ("N of M records", or which filter
emptied the table with a way back), the "filter: ..." description beside
it, the identical-columns chip, set_caveat, refresh_theme, the Export view
(N) button (exportRequested: the view reports the request, MainWindow
performs it), Ctrl+F/Escape, and the basis-badge loop
(evidence_model.basis_of() over every column that names a `field`).

It lives in views/ because the basis-badge loop needs evidence_model,
which widgets/ may not import (test_structure.py). It is a base class, not
a nav destination.

_table_area() returns what the root layout adds in the table's place:
self.table by default. HTTP Headers overrides it with a QSplitter holding
the table and its pane.

QuickFilter declares a chip: the attribute it is reachable by (e.g.
"chip_inprivate"), a label and accent for QuickFilterChip, the row key it
filters, and either `values` (model.set_values, e.g. {True}) or
`condition` (a record_filter.Condition, model.set_condition), exactly one
of the two. The base creates the chip, wires `toggled`, re-applies every
checked chip after set_records() builds a fresh model, clears chips in
clear_all_filters and refreshes their theme. A view with no chips has no
chip row.

RecordSet is one named row set a view switches between with a segmented
control above the filter bar (File Access has two, Cookies three). A view
with one RecordSet has no switcher, and set_records(rows, note=None) sets
its rows; a view with several calls set_records_for(key, rows, note=None)
per segment, so MainWindow can update one segment (after a recovery scan,
say) without touching the others.

Switching segments rebuilds the table through RecordsTable.set_records(),
which builds a new RecordTableModel/RecordFilter, so no filter carries
from one segment's columns to another's. The filter-box text and checked
chips, which are not part of the model, are cleared as well, so nothing on
screen suggests a filter the new columns do not have.
"""
from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

from ..engine import evidence_model, local_clock
from ..shell import glyphs, theme
from ..widgets import copyable
from ..widgets.column_spec import Column, blank_label, display_text
from ..widgets.note_line import NoteLine
from ..widgets.content_header import CaveatLine, ViewHeader
from ..widgets.quick_filter_chip import QuickFilterChip
from ..widgets.record_filter import DEBOUNCE_MS, LIVE_FILTER_MAX_ROWS
from ..widgets.records_table import RecordsTable


def constant_note_style():
    """The small pill every view states its hidden/identical columns in."""
    p = theme.PALETTES[theme.current_name()]
    return ("font-size: 10.5px; background: %(alt_base)s; color: %(text)s; "
            "border: 1px solid %(border)s; border-radius: 11px; "
            "padding: 3px 9px;" % p)


def make_wrap_button():
    """The toolbar's Wrap toggle, the same on every record grid
    (RecordsView and Deleted Records). The view reports the press;
    MainWindow applies it to every grid and remembers it."""
    button = QPushButton("Wrap")
    button.setCheckable(True)
    button.setChecked(True)
    button.setToolTip(
        "Wrap long values onto several lines (on), or keep one line "
        "per row with the whole value in the tooltip (off). Applies to "
        "every grid.")
    return button


def _default_subtitle(count):
    return "%s record%s." % (format(count, ","), "" if count == 1 else "s")


def member_record_columns(view=None):
    """One record per row -- the pane columns Timeline (a period's
    members) and Domains (a domain's members) both show. Declared HERE,
    in the base, so two views share it without importing each other."""
    drill = None
    if view is not None:
        drill = lambda row: view.drillRequested.emit("browser", row)  # noqa: E731
    return [
        Column("KeyTimeUtc", "When (UTC)", 165, kind="time",
               field="ModifiedTime", basis_key="KeyTimeBasis"),
        # WHICH COLUMN THE TIME CAME FROM. "ModifiedTime (visit written)"
        # and "AccessedTime (cache touch)" are different claims about what
        # happened, and one UTC column collapses them. No `field`: this is
        # a sentence about the value beside it, not a stored value with a
        # provenance entry of its own.
        Column("KeyTimeBasis", "Read from", 210, kind="text",
               short=local_clock.short_basis),
        Column("LocalTime", "Last visit (LOCAL)", 165, kind="time_local",
               field="SPS_LastVisitLocal"),
        Column("ContainerType", "Record type", 120, kind="text",
               field="ContainerType"),
        Column("VisitCount", "Visits (property store)", 90, kind="num",
               field="SPS_VisitCount"),
        Column("CacheTouches", "Cache touches", 80, kind="num",
               field="AccessCount"),
        Column("CleanUrl", "Address", 380, kind="url", field="CleanUrl"),
        Column("SearchTerms", "Search terms", 180, kind="flag",
               field="SearchTerms"),
        # link_enabled: a bare string carve (record_kinds.K_CARVED_STRING)
        # has ContainerName "" and ContainerId None, so its cell has no
        # container to open and shows no link.
        Column("ContainerName", "Container", 150, kind="text",
               field="ContainerName", on_click=drill,
               link_enabled=lambda row: row.get("ContainerId") is not None),
        Column("IsInPrivate", "InPrivate", 90, kind="flag",
               field="IsInPrivate"),
        Column("Origin", "Source record", 170, kind="flag", field="Origin"),
    ]



#: A note at most this long, on one line, joins the count line.
NOTE_INLINE_MAX = 110

def _singular(noun):
    """A count noun for exactly one: "records" -> "record", "IOC
    matches" -> "IOC match". Every count noun here is a plain English
    plural."""
    for plural, single in (("ches", "ch"), ("ies", "y"), ("s", "")):
        if noun.endswith(plural):
            return noun[:-len(plural)] + single
    return noun


def export_view_tooltip(shown, noun="records"):
    """What "Export view (N)" saves, in words: the button alone did not
    say what would be written, or as what."""
    return ("Saves the %s %s shown here, in the order shown, as a CSV "
            "file or an Excel workbook (.xlsx), chosen in the save "
            "dialog. Every column is written, including ones hidden on "
            "screen, followed by every field each record carries. A "
            "provenance file beside it records the evidence hash, the "
            "filters in force and the time of export."
            % (format(shown, ","), noun))


class QuickFilter:
    """One quick-filter chip declaration (see the module docstring).
    Exactly one of `values`/`condition` must be given; anything else is
    refused.

    attr      the attribute name the built QuickFilterChip is reachable
              by, e.g. "chip_inprivate", used by tests and MainWindow.
    label     the chip's text, e.g. "InPrivate only".
    accent    QuickFilterChip's unchecked-outline colour role, e.g.
              "error" or "primary".
    key       the row-dict key this chip filters.
    values    a value set applied with model.set_values(key, values) when
              checked, e.g. {True}.
    condition a record_filter.Condition applied with
              model.set_condition(key, condition) when checked.
    none_note a sentence added to the chip's tooltip when it keeps no
              record: what that zero does and does not cover.
    """
    __slots__ = ("attr", "label", "accent", "key", "values", "condition",
                 "sentence", "post", "counted", "none_note")

    def __init__(self, attr, label, accent, key, values=None, condition=None,
                 sentence=None, post=None, counted=True, none_note=None):
        self.none_note = none_note
        if sum(x is not None for x in (values, condition, post)) != 1:
            raise ValueError(
                "QuickFilter %r needs exactly one of values/condition/post"
                % attr)
        #: fn(visible rows) -> rows kept, for a chip that must see which
        #: other rows are shown (RecordFilter.set_post).
        self.post = post
        self.attr = attr
        self.label = label
        self.accent = accent
        self.key = key
        self.values = values
        self.condition = condition
        #: What the chip does, in words, for the filter sentence and an
        #: emptied grid; None says the filter itself.
        self.sentence = sentence
        #: Whether the chip shows how many records it keeps ("Has search
        #: terms · 3"). Only a chip that SELECTS can: a chip that hides
        #: rows ("Hide duplicate copies") would read as keeping that
        #: many, and a post filter depends on what else is shown.
        self.counted = counted and post is None

    def keeps(self, row):
        """Whether this chip, on its own, keeps `row`."""
        value = row.get(self.key)
        if self.values is not None:
            return value in self.values
        return self.condition.matches(value)


class RecordSet:
    """One named row set a RecordsView can switch between (see the module
    docstring). `columns` is this segment's own Column list; segments can
    declare entirely different fields. `subtitle` is a callable(count) ->
    str for the header's per-segment phrasing ("204 history records...",
    "37 downloads..."); when omitted, a generic count line is used.

    `empty_text` is this segment's sentence for a table with no rows and no
    filter, e.g. a Downloads segment when the exhibit's iedownload
    container has no live entries. RecordsTable paints it centred in the
    table (RecordsTable.set_empty_reason), so "this exhibit has none" is
    distinguishable from a failure or a filter hiding everything. It is
    separate from the filtered-to-zero message (empty_message()). When
    omitted, a generic sentence names the record set by its label.

    `count_noun` is this segment's word for its rows in the count line,
    overriding RecordsView.COUNT_NOUN (None by default). Findings' six
    segments count six different things (hits, containers, silences,
    domains, hostnames, hops). Always the plural form.

    `default_sort` is `(key, descending)`, applied on every render: record
    views open newest first by their time column. Blank times sort last in
    both directions (RecordFilter._apply_sort).

    `caveat` is this segment's caveat, shown instead of the view's when set
    (an HSTS caveat belongs to the HSTS segment).
    """
    __slots__ = ("key", "label", "columns", "subtitle", "empty_text",
                 "count_noun", "default_sort", "caveat")

    def __init__(self, key, label, columns, subtitle=None, empty_text=None,
                 count_noun=None, default_sort=None, caveat=None):
        self.key = key
        self.label = label
        self.columns = columns
        self.subtitle = subtitle or _default_subtitle
        self.empty_text = empty_text or ("No %s records in this exhibit." % label)
        self.count_noun = count_noun
        self.default_sort = default_sort
        self.caveat = caveat


class RecordsView(QWidget):
    """Base class for a record-table view. See the module docstring for
    what this owns; a subclass supplies COLUMNS (via RecordSet), quick
    filters (via QuickFilter), a header icon/title, and nothing else --
    every other public attribute a subclass or MainWindow reaches
    (filter_box, count_label, table, export_button, caveat, header,
    COLUMNS, drillRequested, exportRequested) is built and kept current
    here.
    """
    #: Every drill-down in the application uses this signal (see
    #: column_spec.Column's on_click). MainWindow routes them all the same
    #: way: widget.drillRequested.connect(lambda k, _row: self.go_to(k)).
    #: What one row of this view is called in the count line ("73
    #: records"): "records" by default; Timeline uses "periods". Always the
    #: plural form.
    COUNT_NOUN = "records"

    drillRequested = Signal(str, dict)
    #: The "Export view (N)" button. A signal: the view reports the
    #: request and MainWindow performs the export.
    exportRequested = Signal()
    #: The Wrap button was pressed. MainWindow applies it to every grid
    #: and remembers it.
    wrapToggled = Signal(bool)
    #: The Details button was pressed: MainWindow applies it to every
    #: view and remembers it.
    detailsToggled = Signal(bool)
    #: The segment on screen changed: MainWindow restates
    #: the status bar from that segment's own caveat.
    segmentChanged = Signal(str)

    def __init__(self, record_sets, header_icon, header_title,
                quick_filters=(), initial_key=None, parent=None):
        super().__init__(parent)
        if not record_sets:
            raise ValueError("RecordsView needs at least one RecordSet")
        self._record_sets = list(record_sets)
        self._segments_by_key = {rs.key: rs for rs in self._record_sets}
        if len(self._segments_by_key) != len(self._record_sets):
            raise ValueError("RecordSet keys must be unique")
        # initial_key: which segment the view OPENS on, when that is not
        # the first one declared. Default None keeps "first declared wins"
        # for every view that existed before it -- none of them passes
        # this and none of their behaviour changes. TimelineView needs it
        # because its four grains must READ fine-to-coarse (By minute, By
        # hour, By day, By month -- the order an examiner scans them in)
        # while OPENING on day, which is the grain that is legible on a
        # first look. An unknown key falls back rather than raising: a
        # typo in a subclass would otherwise leave _active_key naming a
        # segment no RecordSet answers to, and every lookup after that
        # point raises KeyError somewhere far from the cause.
        self._active_key = (initial_key if initial_key in self._segments_by_key
                            else self._record_sets[0].key)
        self._segment_rows = {rs.key: [] for rs in self._record_sets}
        self._segment_notes = {rs.key: None for rs in self._record_sets}
        self._note = None
        #: The current segment's Column list; for a single-segment view it
        #: never changes, so HistoryView.COLUMNS reads as before.
        self.COLUMNS = self._segments_by_key[self._active_key].columns
        #: The column keys this table was last rendered with; scroll is
        #: reset only when they change (see _render_active_segment).
        self._last_rendered_column_keys = None

        # The header basis badge (OBS/DER/INF/CARV): every column of every
        # segment that names a `field` gets one. The rule is in
        # annotate_basis() below, so a subclass with a second table can
        # apply it too. See column_spec.Column on why badge/badge_tooltip
        # are set here rather than in the constructor.
        for rs in self._record_sets:
            self.annotate_basis(rs.columns)

        self.header = ViewHeader(header_icon, header_title)
        self.caveat = CaveatLine(key=type(self).__name__)

        # --- the segmented switcher: only when there is more than one
        # record set to switch between -- see the module docstring.
        self._switcher_buttons = {}
        switcher_row = None
        if len(self._record_sets) > 1:
            switcher_row = QHBoxLayout()
            switcher_row.setSpacing(8)
            self._switcher_group = QButtonGroup(self)
            self._switcher_group.setExclusive(True)
            for rs in self._record_sets:
                btn = QPushButton(self._switcher_label(rs.key))
                btn.setCheckable(True)
                btn.setChecked(rs.key == self._active_key)
                # A lambda, not functools.partial: clicked(bool checked =
                # false) has a default-valued parameter, and PySide6 cannot
                # read a partial's arity, so it would call the partial with
                # no arguments. The same lambda form is used for the chips'
                # `toggled` connections below.
                btn.clicked.connect(
                    lambda _checked=False, k=rs.key: self._switch_segment(k))
                self._switcher_group.addButton(btn)
                switcher_row.addWidget(btn)
                self._switcher_buttons[rs.key] = btn
            switcher_row.addStretch(1)
            # The THIRD seam: controls that govern every segment but need
            # no row of their own -- see _switcher_trailing.
            trailing = self._switcher_trailing()
            if trailing is not None:
                switcher_row.addWidget(trailing)

        # --- quick-filter chips: only when the subclass declares any ----
        self._quick_filters = list(quick_filters)
        chip_row = None
        if self._quick_filters:
            chip_row = QHBoxLayout()
            chip_row.setSpacing(10)
            for spec in self._quick_filters:
                chip = QuickFilterChip(spec.label, accent=spec.accent)
                chip.toggled.connect(
                    lambda checked, s=spec: self._toggle_chip(s, checked))
                setattr(self, spec.attr, chip)
                chip_row.addWidget(chip)
            chip_row.addStretch(1)
            # With a segment switcher too, the chips sit at the right end
            # of ITS row instead of taking a row of their own (File
            # Access stacked both, above a filter bar and a count line).
            if switcher_row is not None:
                for i in range(chip_row.count()):
                    item = chip_row.itemAt(i)
                    if item.widget() is not None:
                        switcher_row.addWidget(item.widget())
                chip_row = None

        self.filter_box = QLineEdit(placeholderText="Filter these records…")
        self._funnel_action = self.filter_box.addAction(
            glyphs.icon("funnel", theme.color("primary"), 15),
            QLineEdit.LeadingPosition)
        self.count_label = copyable.selectable(QLabel(""))
        # Wrapped, not clipped: this line carries the `note` MainWindow
        # passes to set_records, which can be several sentences (Timeline's
        # states what is on the timeline, the silences, and what a silence
        # is not). A wrapping QLabel does not widen the view's minimum.
        self.count_label.setWordWrap(True)
        # a long note folds to one line behind a toggle -- the NOTE,
        # never the count. The count line is primary information and is
        # always whole; only caveat prose folds.
        self.note_label = copyable.selectable(QLabel(""))
        self.note_label.setWordWrap(True)
        self.note_line = NoteLine(self.note_label, self,
                                  key="count:" + type(self).__name__)
        self._filter_desc_label = copyable.selectable(QLabel(""))
        self._filter_desc_label.setWordWrap(True)  # the chip line is never cut
        self._constant_chip = copyable.selectable(QLabel(""))
        self._constant_chip.setVisible(False)
        self._constant_chip.setWordWrap(True)
        clear = self.clear_filters_button = QPushButton("Clear all filters")
        self.export_button = QPushButton("Export view")
        self.export_button.setIcon(glyphs.icon("download", theme.color("primary"), 15))
        theme.mark_outline(self.export_button)
        self.export_button.clicked.connect(self.exportRequested.emit)
        # Optional columns (a view preference): one menu, rebuilt per
        # segment, visible only when the segment declares any. A
        # QPushButton rather than a QToolButton, so it is styled like the
        # buttons beside it.
        self.columns_button = QPushButton("Columns")
        self.columns_button.setToolTip(
            "Show or hide the optional columns. Hidden columns are still "
            "written by every export.")
        self.columns_button.setMenu(QMenu(self.columns_button))
        self.columns_button.setVisible(False)
        # One switch for every grid. The view reports the press;
        # MainWindow applies it everywhere and remembers it.
        self.wrap_button = make_wrap_button()
        self.wrap_button.toggled.connect(self.wrapToggled.emit)
        self.table = RecordsTable()
        # Columns identical in every visible row fold away by default: a
        # view preference (every export still writes them), named beside
        # the count.
        self.identical_button = QPushButton("Hide identical columns")
        self.identical_button.setCheckable(True)
        self.identical_button.setChecked(True)
        self.identical_button.setToolTip(
            "Hide columns whose value is the same in every row on screen "
            "(named beside the count). A view preference: every export "
            "still writes them.")
        self.identical_button.toggled.connect(self.table.set_hide_identical)
        self.table.set_hide_identical(True)
        self.table.identicalColumnsChanged.connect(
            self._update_constant_chip_now)
        self.table.columnVisibilityRestored.connect(
            lambda: self._rebuild_columns_menu(
                self._segments_by_key[self._active_key].columns))

        # The selected record beside the grid -- see shell/details_pane.
        # Built by _table_area; a view with a pane of its own has none.
        self.details_pane = None
        self.details_button = QPushButton("Details")
        self.details_button.setCheckable(True)
        self.details_button.setChecked(True)
        self.details_button.setToolTip(
            "Show the selected record's fields beside the grid")
        self.details_button.toggled.connect(self.set_details_visible)
        self.details_button.toggled.connect(self.detailsToggled.emit)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        bar.addWidget(self.filter_box, 1)
        bar.addWidget(self.details_button)
        bar.addWidget(self.wrap_button)
        bar.addWidget(self.identical_button)
        bar.addWidget(self.columns_button)
        bar.addWidget(clear)
        bar.addWidget(self.export_button)

        count_row = QHBoxLayout()
        count_row.setSpacing(8)
        count_row.addWidget(self.count_label, 1)
        # Both top-aligned: the count label wraps, so this row is as tall as
        # the note (several lines on Location), and the identical-columns
        # chip and the "filter:" line align with its first line rather than
        # its middle. Stretch 2 rather than 0, so a two-filter sentence is
        # not folded into a narrow column.
        count_row.addWidget(self._filter_desc_label, 2, Qt.AlignTop)
        # Its own full-width row, so a long list of identical columns does
        # not wrap into a tall narrow pill.
        constant_row = QHBoxLayout()
        constant_row.addWidget(self._constant_chip, 1, Qt.AlignTop)
        note_row = QHBoxLayout()
        note_row.setSpacing(8)
        note_row.addWidget(self.note_label, 1)
        note_row.addWidget(self.note_line.toggle, 0, Qt.AlignTop)

        root = QVBoxLayout(self)
        root.addWidget(self.header)
        # The second hook (see _header_extra). None for most views, which
        # then add nothing here.
        header_extra = self._header_extra()
        if header_extra is not None:
            root.addWidget(header_extra)
        if switcher_row is not None:
            root.addLayout(switcher_row)
        if chip_row is not None:
            root.addLayout(chip_row)
        root.addLayout(bar)
        root.addLayout(count_row)
        root.addLayout(constant_row)
        root.addLayout(note_row)
        root.addWidget(self.caveat)
        root.addWidget(self._table_area(), 1)
        self.details_button.setVisible(self.details_pane is not None)

        self._refresh_static_styles()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._apply_text)
        self.filter_box.textChanged.connect(self._text_changed)
        self.filter_box.returnPressed.connect(self._apply_text)
        clear.clicked.connect(self.clear_all_filters)
        self.table.clearFiltersRequested.connect(self.clear_all_filters)
        QShortcut(QKeySequence.Find, self, self.filter_box.setFocus)
        QShortcut(QKeySequence(Qt.Key_Escape), self.filter_box,
                  self.clear_all_filters)

    # --- the basis badge ---------------------------------------------------

    @staticmethod
    def annotate_basis(columns):
        """Set badge/badge_tooltip on every Column that names a `field`.

        A staticmethod, callable without a view, because TimelineView's
        per-period pane has columns that are not part of any RecordSet;
        one rule keeps a column there badged as the same column is in a
        record set.

        Here rather than on Column because widgets/ may not import the
        engine (test_structure.py), and evidence_model.basis_of() is the
        engine.
        """
        for col in columns:
            if col.show_badge:
                basis = evidence_model.basis_of(col.field)
                col.badge = evidence_model.BASIS_SHORT[basis]
                col.badge_tooltip = "%s (%s) — %s" % (
                    col.badge, basis.capitalize(),
                    evidence_model.BASIS_DEFINITION[basis])

    @staticmethod
    def grade_mixed(columns, rows):
        """Badge a column whose rows are on different footings. A column
        declaring a basis_key keeps its field's badge while every row is as
        stored; when any row's value was derived from an MSHist record's
        LOCAL clock the badge reads "<field>/INF" and the tooltip says the
        basis is mixed, and each cell's tooltip names its basis. Run before
        the rows reach the table, so the heading width allows for this
        badge."""
        for col in columns:
            if not col.basis_key or not col.show_badge:
                continue
            RecordsView.annotate_basis([col])
            derived = sum(
                1 for r in rows
                if r.get(col.key) is not None
                and local_clock.is_mshist_record(r.get("_record") or {}))
            if not derived:
                continue
            observed = col.badge
            col.badge = "%s/%s" % (observed, evidence_model.BASIS_SHORT[
                evidence_model.INFERRED])
            col.badge_tooltip = (
                "Mixed basis: %s for rows stored in UTC; INF (Inferred) for "
                "%s MSHist row%s whose UTC is derived from the LOCAL value "
                "the container stores. Each cell's tooltip names its own "
                "basis." % (observed, format(derived, ","),
                            "" if derived == 1 else "s"))

    # --- the table's place in the layout -----------------------------------

    def _table_area(self):
        """The widget added to the root layout in the table's place.

        self.table by default. A view that pairs the table with a second
        pane (HTTP Headers) overrides this to return a QSplitter holding
        both.

        Called once, from __init__, after the table exists, so an override
        may reference self.table.
        """
        from ..shell.details_pane import DetailsPane
        self.details_pane = DetailsPane()
        self.table.currentRecordChanged.connect(self.details_pane.show_row)
        self._details_split = QSplitter(Qt.Horizontal)
        self._details_split.setChildrenCollapsible(False)
        self._details_split.addWidget(self.table)
        self._details_split.addWidget(self.details_pane)
        # Spare width goes to the grid; the pane keeps the width it has
        # (the handle still resizes it).
        self._details_split.setStretchFactor(0, 1)
        self._details_split.setStretchFactor(1, 0)
        self._details_split.setSizes([1000, 380])
        return self._details_split

    def set_details_visible(self, on):
        """The pane beside the grid, shown or not -- a view preference
        MainWindow remembers for every view."""
        if self.details_pane is None:
            return
        self.details_pane.setVisible(bool(on))
        if self.details_button.isChecked() != bool(on):
            self.details_button.blockSignals(True)
            self.details_button.setChecked(bool(on))
            self.details_button.blockSignals(False)

    def _switcher_trailing(self):
        """A widget at the right end of the segment switcher row, or None.

        For a small control that governs every segment (Location's place
        grouping) and so belongs above them, without the extra row
        _header_extra costs. Same contract as _header_extra: called once
        from the base constructor, idempotent. Only views with a switcher
        call it."""
        return None

    def _header_extra(self):
        """The widget placed between the header and the switcher, or None.

        None by default. Search (its query bar: keyword, scope, Search) and
        Findings (corpus line and watchlist) use it for controls that
        govern every segment, so they sit above the switcher.

        As for _table_area: called once from the base constructor, after
        self.table and self.filter_box exist, and it must be idempotent
        (return the same cached widget on a second call), or the widget
        would be reparented out of its layout.
        """
        return None

    # --- theme / caveat ----------------------------------------------------

    def refresh_theme(self):
        """MainWindow._refresh_drawn_theme's per-view hook -- see
        HistoryView's original docstring (history.py) for the full
        reasoning on why every one of these needs an explicit repaint on
        a theme switch rather than relying on QSS/QPalette alone."""
        self.header.refresh_theme()
        self.caveat.refresh_theme()
        self._funnel_action.setIcon(glyphs.icon("funnel", theme.color("primary"), 15))
        self.export_button.setIcon(glyphs.icon("download", theme.color("primary"), 15))
        self._refresh_static_styles()
        for _spec, chip in self._chip_widgets():
            chip.refresh_theme()
        # Font metrics change with the theme: wrapped rows are re-measured.
        self.table.refit_rows()
        self.table.viewport().update()

    def set_caveat(self, text):
        """MainWindow calls this once, right after construction -- see
        HistoryView's original docstring for the full reasoning."""
        self._view_caveat = text
        self._show_caveat()

    def _show_caveat(self):
        """The active segment's own caveat, else the view's."""
        rs = self._segments_by_key[self._active_key]
        self.caveat.set_text(rs.caveat or getattr(self, "_view_caveat", ""))

    def _refresh_static_styles(self):
        p = theme.PALETTES[theme.current_name()]
        self._filter_desc_label.setStyleSheet(
            "font-size: 12px; background: transparent; color: %s;" % p["muted"])
        self._constant_chip.setStyleSheet(constant_note_style())
        self.count_label.setStyleSheet("font-size: 12px; background: transparent;")
        self.note_label.setStyleSheet(
            "font-size: 12px; background: transparent; color: %s;" % p["muted"])
        # Every checkable button's checked look comes from the stylesheet's
        # QPushButton:checked rule, so it follows the theme.

    # --- record sets ---------------------------------------------------

    def set_records(self, rows, note=None):
        """Set rows for the active segment. For a view with one RecordSet
        that is the only segment, so callers keep the single-argument
        call."""
        self.set_records_for(self._active_key, rows, note)

    def set_note_for(self, segment_key, note):
        """Restate one segment's count-line note WITHOUT rebuilding its
        rows: the recovery state changes the words, not the records. The model, filters and selection are untouched."""
        if segment_key not in self._segment_notes:
            return
        self._segment_notes[segment_key] = note
        if segment_key == self._active_key:
            self._note = note
            self._update_count()

    def empty_text_for(self, rs):
        """What an empty `rs` says now: its own sentence, unless a subclass
        knows more (FindingsView before any watchlist scan). The grid and
        the offline report both ask here, so they agree."""
        return rs.empty_text

    def set_records_for(self, segment_key, rows, note=None):
        """Cache rows/note for one named record set (see RecordSet). If
        this segment is the one currently on screen, the table re-renders
        immediately; otherwise only the switcher button's own row count
        updates, so an examiner sees "Downloads (37)" before ever
        switching to it."""
        self._segment_rows[segment_key] = rows
        self._segment_notes[segment_key] = note
        self._update_switcher_button(segment_key)
        if segment_key == self._active_key:
            self._render_active_segment()

    def _render_active_segment(self):
        rs = self._segments_by_key[self._active_key]
        rows = self._segment_rows[self._active_key]
        self._note = self._segment_notes[self._active_key]
        self.grade_mixed(rs.columns, rows)
        self.table.set_records(rs.columns, rows)
        self._show_chip_counts(rows)
        self.table.set_hide_identical(self.identical_button.isChecked())
        self._show_caveat()
        if rs.default_sort:
            self.table.sort_by_key(*rs.default_sort)
        # A scroll offset is valid only for the column set it was measured
        # against, so both scrollbars are reset when that set changes, and
        # only then. Only _switch_segment changes it (each RecordSet's
        # columns are fixed); a refresh of the active segment (a second
        # Open Evidence, a recovery merge) keeps the examiner's scroll
        # position, as it keeps the filter state.
        #
        # Without the reset, scrolling one segment to its right edge and
        # switching to a narrower one could leave the grid scrolled past
        # every column: Qt clamps an out-of-range value down to the new
        # maximum rather than back to 0.
        #
        # Navigation between views (MainWindow's QStackedWidget) keeps
        # each view's own scroll; this applies only to a segment switch
        # within one view.
        new_keys = [c.key for c in rs.columns]
        if new_keys != self._last_rendered_column_keys:
            self.table.horizontalScrollBar().setValue(0)
            self.table.verticalScrollBar().setValue(0)
            self._last_rendered_column_keys = new_keys
        # set_records() cleared the previous segment's empty-state
        # sentence; this sets this segment's own.
        self.table.set_empty_reason(self.empty_text_for(rs))
        self.table.model().layoutRefreshed.connect(self._update_count)
        # set_records() builds a new RecordTableModel/RecordFilter with no
        # filter applied, while checked chips stay checked, so the checked
        # chips are re-applied (see _reapply_quick_filters). A no-op when
        # none is checked.
        self._reapply_quick_filters()
        self._refresh_chip_availability(rs.columns, rows)
        # The filter-box text is re-applied too. A second set_records() on
        # the same segment (a second Open Evidence, a recovery merge) keeps
        # the same columns, so the text still applies; _switch_segment
        # clears the box itself before calling this, because there the
        # columns change. A no-op when the box is empty.
        model = self.table.model()
        if model is not None:
            model.set_text(self.filter_box.text())
        self.header.set_subtitle(rs.subtitle(len(rows)))
        self._update_count()
        self._rebuild_columns_menu(rs.columns)

    def _rebuild_columns_menu(self, columns):
        """The Columns menu: one checkable entry per OPTIONAL column of
        the active segment, checked when shown. Hidden only when the
        segment declares none -- a menu of nothing is a dead end."""
        menu = self.columns_button.menu()
        menu.clear()
        optional = [c for c in columns if c.optional]
        for col in optional:
            action = menu.addAction(col.label)
            action.setCheckable(True)
            action.setChecked(not col.hidden)
            action.toggled.connect(
                lambda on, k=col.key: self.table.set_column_hidden(k, not on))
        self.columns_button.setVisible(bool(optional))

    def _switcher_label(self, key):
        rs = self._segments_by_key[key]
        return "%s (%s)" % (rs.label, format(len(self._segment_rows[key]), ","))

    def _update_switcher_button(self, key):
        btn = self._switcher_buttons.get(key)
        if btn is not None:
            btn.setText(self._switcher_label(key))

    def _switch_segment(self, key):
        """Switch segments, fully resetting filter state. The new model
        from table.set_records() has no filter; the filter-box text and any
        checked quick-filter chip are cleared here as well, so nothing on
        screen suggests a filter that does not apply to the new columns.
        """
        if key not in self._segments_by_key or key == self._active_key:
            return
        self._active_key = key
        self.COLUMNS = self._segments_by_key[key].columns
        self.filter_box.clear()
        for _spec, chip in self._chip_widgets():
            chip.blockSignals(True)
            chip.setChecked(False)
            chip.blockSignals(False)
        self._render_active_segment()
        for k, btn in self._switcher_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(k == key)
            btn.blockSignals(False)
        self.segmentChanged.emit(key)

    def active_caveat(self):
        """The caveat of the segment on screen, "" when it has none."""
        rs = self._segments_by_key.get(self._active_key)
        return (rs.caveat if rs is not None else "") or ""

    # --- filtering: the debounced/live split --------------------------------

    def _text_changed(self, _text):
        """Live below the measured threshold, debounced above it.

        The debounce uses a QTimer, which fires on the GUI thread, the only
        place widgets may be touched; a background timer thread could
        blank the window.
        """
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
        # model.clear_all() already dropped whatever the chips applied
        # (they write into the SAME _values/_conditions maps a header
        # funnel filter would); the chips themselves are ordinary
        # checkable buttons and do not know that happened. Left checked,
        # they would keep claiming a filter is in force the model no
        # longer applies. Signals blocked while unchecking: the model is
        # already clear, so _toggle_chip would only redo a no-op reset.
        for _spec, chip in self._chip_widgets():
            chip.blockSignals(True)
            chip.setChecked(False)
            chip.blockSignals(False)

    # --- quick-filter chips --------------------------------------------

    def _chip_widgets(self):
        return [(spec, getattr(self, spec.attr)) for spec in self._quick_filters]

    def _refresh_chip_availability(self, columns, rows):
        """After every fill, a chip whose column holds one
        value in EVERY row can only empty the grid or change nothing, so
        it is disabled with that reason in its tooltip. Enabled again by
        the next fill that brings a row that differs. A chip already in
        force is never disabled -- it must stay possible to turn it off."""
        by_key = {c.key: c for c in columns}
        for spec, chip in self._chip_widgets():
            base = chip.property("baseToolTip")
            if base is None:
                base = chip.toolTip() or ""
                chip.setProperty("baseToolTip", base)
            reason = None
            if rows and not chip.isChecked() and spec.post is None:
                first = rows[0].get(spec.key)
                if all(r.get(spec.key) == first for r in rows):
                    col = by_key.get(spec.key)
                    shown = (display_text(first, col) if col is not None
                             else str(first if first is not None else ""))
                    shown = shown or "blank"
                    keeps = (first in spec.values if spec.values is not None
                             else spec.condition.matches(first))
                    reason = ("Every row is %s \u2014 this chip would %s"
                              % (shown, "change nothing" if keeps
                                 else "show nothing"))
                    if spec.none_note and not keeps:
                        reason += ". " + spec.none_note
            chip.setEnabled(reason is None)
            chip.setToolTip(reason or base)

    @staticmethod
    def _say_chip(model, spec, checked):
        """Record the chip's own sentence against the filter it puts in
        force."""
        if not spec.sentence:
            return
        if checked:
            model.filter.sentences[spec.key] = (
                spec.post if spec.post is not None
                else spec.condition if spec.condition is not None
                else frozenset(spec.values), spec.sentence)
        else:
            model.filter.sentences.pop(spec.key, None)

    def _show_chip_counts(self, rows):
        """Each selective chip states how many of the segment's records it
        keeps, over the whole record set, so the number does not change when
        another chip is ticked and "are there any?" is answered without a
        click."""
        total = len(rows)
        for spec in self._quick_filters:
            if not spec.counted:
                continue
            chip = getattr(self, spec.attr)
            kept = sum(1 for r in rows if spec.keeps(r))
            chip.setText("%s · %s" % (spec.label, format(kept, ",")))
            tip = ("%s of %s %s in this list. Ticked, it applies on top "
                   "of the other filters." % (
                       format(kept, ","), format(total, ","),
                       "record" if total == 1 else "records"))
            if not kept and spec.none_note:
                tip += " " + spec.none_note
            # The BASE tooltip _refresh_chip_availability falls back to,
            # re-stated on every fill so a disabled chip's reason never
            # outlives the data it described, nor a count its rows.
            chip.setProperty("baseToolTip", tip)
            chip.setToolTip(tip)

    def _toggle_chip(self, spec, checked):
        model = self.table.model()
        if model is None:
            return
        self.table.close_filter_popup()
        self._say_chip(model, spec, checked)
        try:
            if spec.post is not None:
                model.set_post(spec.key, spec.post if checked else None)
            elif spec.values is not None:
                model.set_values(spec.key, spec.values if checked else None)
            else:
                model.set_condition(spec.key,
                                    spec.condition if checked else None)
        except Exception as exc:                       # noqa: BLE001
            # The model rolled back, so the chip must too, or it claims a
            # filter the grid is not applying. Blocked so
            # putting the state back does not re-run this handler.
            self._chip_failed(getattr(self, spec.attr), not checked, exc)

    def _chip_failed(self, chip, state, exc):
        blocker = QSignalBlocker(chip)
        try:
            chip.setChecked(state)
        finally:
            blocker.unblock()
        self.count_label.setText(
            "A quick filter could not be applied: %s" % exc)

    def _reapply_quick_filters(self):
        """Re-apply the checked chips to a freshly built model, on every
        render (see _render_active_segment)."""
        model = self.table.model()
        if model is None:
            return
        # a chip whose key no column declares is named by the chip's
        # own label, never by the row key.
        for spec in self._quick_filters:
            model.filter.extra_labels.setdefault(spec.key, spec.label)
        for spec, chip in self._chip_widgets():
            self._say_chip(model, spec, chip.isChecked())
            if chip.isChecked():
                try:
                    if spec.post is not None:
                        model.set_post(spec.key, spec.post)
                    elif spec.values is not None:
                        model.set_values(spec.key, spec.values)
                    else:
                        model.set_condition(spec.key, spec.condition)
                except Exception as exc:               # noqa: BLE001
                    self._chip_failed(chip, False, exc)

    # --- the count line, filter description, constant-column chip ------

    def _update_count(self):
        """The count line beneath the filter box. When a filter emptied the
        table, this uses RecordsTable.empty_message(), which names the
        column responsible and offers "Show all records", so it never reads
        like a table with nothing to show."""
        model = self.table.model()
        if model is None:
            return
        shown, total = model.rowCount(), model.filter.total_count
        # The active segment's noun when it declares one, this view's
        # otherwise (RecordSet.count_noun). Read on every count, because
        # _switch_segment changes the active segment.
        noun = (self._segments_by_key[self._active_key].count_noun
                or self.COUNT_NOUN)
        # I3: an emptied grid says WHY once, in its body (with the Clear
        # filters button); the count stays a plain "0 of N".
        if shown == total:
            text = "{:,} {}".format(total, _singular(noun) if total == 1
                                     else noun)
        else:
            text = "{:,} of {:,} {}".format(shown, total, noun)
        # A short note ("927 live, 500 recovered") joins the count line;
        # a long note keeps its own row, behind its expander.
        note = getattr(self, "_note", None) or ""
        inline = bool(note) and "\n" not in note and len(note) <= NOTE_INLINE_MAX
        self.count_label.setText(text + (" — " + note if inline else ""))
        self.note_label.setText("" if inline else note)
        self.note_label.setVisible(bool(self.note_label.text()))
        self.note_line._sync()
        self.export_button.setText("Export view (%s)" % format(shown, ","))
        self.export_button.setToolTip(export_view_tooltip(shown, noun))
        # Laid out immediately: this can run in the handler that ends a
        # scan, and the next posted LayoutRequest would come after the
        # longer text was painted clipped.
        self.layout().activate()
        self._update_filter_description(model)
        self._update_constant_chip(model)

    def line_text(self):
        """The count line and its caveat as one sentence -- what an
        examiner reads across the two labels, and what callers that
        predate their separation mean by "the count line"."""
        note = self.note_label.text()       # "" when it is on the count line
        return self.count_label.text() + (" — " + note if note else "")

    def _update_filter_description(self, model):
        """"filter: ..." beside the count -- record_filter.RecordFilter.
        chip_text() already builds this exact line."""
        chip = model.chip_text()
        # Said once: an emptied grid carries the sentence in its body.
        chip = "" if not model.rowCount() else chip
        self._filter_desc_label.setText(("filter: %s" % chip) if chip else "")
        self._filter_desc_label.setVisible(bool(chip))

    #: A value longer than this is named by its column, never repeated.
    CHIP_VALUE_MAX = 60

    def _update_constant_chip_now(self):
        model = self.table.model()
        if model is not None:
            self._update_constant_chip(model)

    def _update_constant_chip(self, model):
        found = self.table.identical_columns()
        blank = [c for c in self.table.blank_columns() if not c.optional]
        if not found and not blank:
            self._constant_chip.setVisible(False)
            self._constant_chip.setToolTip("")
            return
        hidden = self.table.auto_hidden_keys()
        # A column with a filter on it is identical by construction and
        # stays on screen (see RecordsTable._apply_identical): it is named,
        # marked as shown, and never counted among the hidden.
        kept = (lambda col: hidden and col.key not in hidden)
        shown_parts, tip_parts = [], []
        for col, value in found:
            text = display_text(value, col) or blank_label(col)
            mark = " (filtered, shown)" if kept(col) else ""
            tip_parts.append("%s = %s%s" % (col.label, text, mark))
            shown_parts.append(
                "%s: %s%s" % (col.label, text, mark)
                if len(text) <= self.CHIP_VALUE_MAX else
                "%s (the same text; hover to read)%s" % (col.label, mark))
        count = format(len(model.filter.visible()), ",")
        if blank:
            # a column empty in every row is named too.
            names = ", ".join(c.label + (" (filtered, shown)" if kept(c) else "")
                              for c in blank)
            shown_parts.append("empty in every row: %s" % names)
            tip_parts.append("Empty in every row: %s" % names)
        if hidden:
            n_found = sum(1 for col, _v in found if not kept(col))
            n_blank = sum(1 for col in blank if not kept(col))
            total = n_found + n_blank
            kinds = (["%d identical" % n_found] if n_found else []) + (
                ["%d empty in every row" % n_blank] if n_blank else [])
            lead = "%d column%s hidden: %s \u2014 " % (
                total, "" if total == 1 else "s", ", ".join(kinds))
            lead += "in all %s: " % count
        else:
            lead = "Identical in all %s: " % count
        self._constant_chip.setText(lead + "; ".join(shown_parts))
        self._constant_chip.setToolTip(
            copyable.literal_tooltip("\n\n".join(tip_parts)))
        self._constant_chip.setVisible(True)
