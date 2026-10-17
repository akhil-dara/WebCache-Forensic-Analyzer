"""When the machine was busy, when it was silent, and what a silence is
not evidence of.

Each grain is a RecordSet, so the base's switcher provides:

  * buttons that read "By day (97)", showing how many buckets a grain
    produces before switching to it;
  * _switch_segment clearing the filter box and every chip, since a
    filter typed as a day label matches nothing at month grain;
  * fresh Column objects per grain (so badges are annotated once each)
    with identical keys, so switching grain keeps the scroll position.

The grains read fine to coarse, and the view opens on day (`initial_key`).

GAPS are shown in four places, following the caveat that gaps mean no
cached activity, which is not the same as no activity:

  1. GapBefore is a column on every row. No zero-count row is added for an
     empty bucket (get_timeline emits only periods that received a
     record); the size of each silence belongs to the row that follows it,
     so it sorts (descending finds the longest), filters (> 24), and goes
     into the view CSV, and no sort or filter can separate it from its row.
  2. Its unit is buckets at the current grain, not hours, so
     "Empty days before: 22" is what the rows on screen show, and it
     rescales with the grain. (analyze_time_voids measures
     record-to-record hours for Findings.)
  3. The count line states how many silences there are and the longest,
     followed by what a silence is not (timeline_loader.grain_note).
  4. The subtitle states, at every grain, that only populated periods are
     listed.

No colour is used for gaps: ForegroundRole marks carved and live rows.

A period opens its records in a second table below, in a draggable
QSplitter, so both grids stay on screen. The pane is re-read from the
model on every refresh, so a selection survives a re-render.

Two exports: the base's "Export view (N)" writes the period rows for the
active grain; the pane's "Export these records (N)" writes the records in
one period, with Origin.
"""
from PySide6.QtCore import QDate, Qt, QItemSelectionModel, Signal
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSplitter, QWidget)

from ..widgets import copyable
from ..widgets.calendar_button import CalendarButton
from ..shell.timeline_loader import DEFAULT_GRAIN, GRAINS, record_rows
from ..widgets.column_spec import Column
from ..widgets.sub_table import SubTable, rows_height
from .records_view import RecordSet, RecordsView, member_record_columns

#: What the pane says with nothing selected. An invitation, never a void.
PANE_PROMPT = ("Select a period above. The records that make it up appear "
               "here, and any of them can be opened in full.")

#: What the pane's rows are, stated once above them: the same records
#: History shows, reached through a period. Opened with double-click,
#: Enter, or the context menu's Open.
PANE_NOTE = ("Every record whose key timestamp falls in this period, live "
             "and recovered together. Double-click a record (or select "
             "it and press Enter) for every stored field.")

#: The pane's own empty state. Only reachable for a period whose members
#: were all filtered away inside the pane itself.
PANE_EMPTY = ("No records in this period match the filter in force on this "
              "pane.")

#: The empty state for the period grid, naming the three columns a period
#: is read from, so "no times stored" is not mistaken for a decode
#: failure.
EMPTY_TEXT = ("No record in this exhibit carries a ModifiedTime, "
              "AccessedTime or CreationTime, the columns a period is read "
              "from, so nothing can be placed on the timeline.")

#: Shown as soon as a background Timeline build starts (at open, or after
#: a recovery scan; see show_building), so the grid never shows a previous
#: exhibit's rows or the "nothing can be placed in time" empty state while
#: a large exhibit's build runs.
BUILDING_TEXT = ("Building the timeline for this exhibit — large "
                 "exhibits can take a while. Every grain fills in as "
                 "soon as it is ready.")

#: The pane's share of the splitter with nothing selected, and with a
#: period selected. See _set_pane_share for why it moves at all.
PANE_SHARE_IDLE = 0.16
PANE_SHARE_ACTIVE = 0.40
#: How far Qt's re-layout may move a split this view set before the move
#: counts as the examiner's drag (4 px under the stylesheet).
_SPLIT_SETTLE_PX = 12


def _period_columns(grain, plural):
    """One grain's columns, built per grain and per view.

    Per grain because the base annotates badges onto the Column objects:
    one shared list would be annotated four times. Per view because a
    Column with an on_click holds a reference to its view (none here has
    one, but the rule is kept).
    """
    return [
        # Text, not time: a month bucket is "2024-06", which
        # record_filter._parse_dt cannot read. "%Y-..." strings sort
        # chronologically, and "begins with 2024-06" filters naturally.
        Column("Period", "Period", 165, kind="text"),
        # The bucket's start instant, so date operators work on this
        # column.
        Column("PeriodStart", "Period start (UTC)", 175, kind="time"),
        Column("Records", "Records", 90, kind="num"),
        # The only bar column in the tree. See widgets/bar_delegate.py for
        # why it is drawn, and why square-root scaled.
        Column("Share", "Relative volume", 190, kind="bar"),
        # A count, not a flag: a period holds live and recovered records
        # together.
        Column("Carved", "From deleted", 105, kind="carved"),
        # Mixed int / "(not applicable)" in a num column is already
        # handled by record_filter._sort_key, with a precedent in
        # ContainersView's own Records column.
        Column("GapBefore", "Empty %s before" % plural, 165, kind="num"),
        Column("Types", "Record types", 240, kind="types",
               field="ContainerType"),
        Column("Domains", "Domains (busiest first)", 320, kind="text", field="Domain"),
    ]


def period_record_columns(view=None):
    """The pane's ten columns -- one record per row.

    Declared once in records_view.member_record_columns, shared with
    Domains' pane, so the two cannot drift.
    """
    return member_record_columns(view)


#: The column declaration with no drill target -- what anything that needs
#: to read the shape without building a view uses.
PERIOD_RECORD_COLUMNS = period_record_columns()


def _subtitle_for(grain, plural):
    def subtitle(count):
        return ("%s %s hold records. Periods without records are not "
                "listed; no cached activity does not mean no activity."
                % (format(count, ","), plural if count != 1 else plural[:-1]))
    return subtitle


class TimelineView(RecordsView):
    #: The pane's export. The view reports the request; MainWindow
    #: performs it (as HeadersView.pairExportRequested).
    periodRecordsExportRequested = Signal()

    #: the examiner chose the clock periods are cut on: "utc" | "local".
    clockChanged = Signal(str)

    #: A row here is a PERIOD, and the count line sits beside a note that
    #: counts RECORDS. See RecordsView.COUNT_NOUN.
    COUNT_NOUN = "periods"

    #: Class defaults: _table_area() is called from the base constructor,
    #: before this class's __init__ body, and PySide6 refuses an instance
    #: attribute on a QWidget whose base __init__ has not run. All three
    #: are replaced per instance.
    _splitter = None
    #: The grid height _fit_short_list last set, or None: only a split this
    #: view made itself is ever given back.
    _shrunk_to = None
    _pane_share = None
    pane = None
    #: The TimelineInput the pane's record rows are built from, set by
    #: MainWindow with the period rows: record_rows() needs its carved
    #: identity set to mark recovered members. None until evidence is
    #: open, and _show_period does not fill the pane while it is None,
    #: since every recovered record would otherwise read as live.
    _inputs = None
    #: The period ROW currently shown in the pane -- the actual dict, not
    #: its row number. See _resync_pane for why identity, not a row
    #: number, is what survives a filter keystroke. None with nothing
    #: selected. Declared as a class default for the same __init__-order
    #: reason as _splitter/pane above.
    _current_row = None
    _clock_bar = None
    _clock = "utc"
    _zone_offset = None

    def __init__(self, parent=None):
        super().__init__(
            record_sets=[
                RecordSet(grain, label, _period_columns(grain, plural),
                          subtitle=_subtitle_for(grain, plural),
                          empty_text=EMPTY_TEXT,
                          # newest first, applied once per render.
                          default_sort=("PeriodStart", True))
                for grain, label, plural in GRAINS],
            header_icon="clock", header_title="Timeline",
            initial_key=DEFAULT_GRAIN, parent=parent)

    # --- the clock, the zone, the date to jump to --------------------

    def _header_extra(self):
        """Idempotent, like Search's: the base constructor calls it."""
        if self._clock_bar is not None:
            return self._clock_bar
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(copyable.selectable(QLabel("Clock:")))
        self.clock_buttons = {}
        group = QButtonGroup(bar)
        group.setExclusive(True)
        for key, text in (("utc", "UTC"), ("local", "Local")):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setChecked(key == "utc")
            button.clicked.connect(lambda _c=False, k=key: self._set_clock(k))
            group.addButton(button)
            row.addWidget(button)
            self.clock_buttons[key] = button
        self.clock_buttons["local"].setEnabled(False)
        self.zone_label = copyable.selectable(QLabel(""))
        self.zone_label.setWordWrap(True)
        row.addWidget(self.zone_label, 1)
        self.date_box = QLineEdit(placeholderText="Go to date: YYYY-MM-DD")
        self.date_box.setFixedWidth(200)
        self.date_box.returnPressed.connect(
            lambda: self._go_from_box())
        go = QPushButton("Go")
        go.clicked.connect(lambda: self._go_from_box())
        self.go_status = copyable.selectable(QLabel(""))
        # Pick a day from a calendar limited to the periods listed; the day
        # fills the box and the view goes to it.
        self.date_calendar = CalendarButton(self.date_box)
        self.date_calendar.picked.connect(lambda _t: self._go_from_box())
        row.addWidget(self.date_box)
        row.addWidget(self.date_calendar)
        row.addWidget(go)
        row.addWidget(self.go_status)
        self._clock_bar = bar
        return bar

    def _go_from_box(self):
        text = self.date_box.text().strip()
        found = self.go_to_date(text)
        if found or not text:
            self.go_status.setText("")
            return
        # A miss clears the selection: the period left highlighted read as
        # the answer. An empty day's next question is where activity is.
        self.table.selectionModel().clearSelection()
        self.table.selectionModel().clearCurrentIndex()
        before, after = self.nearest_periods(text)
        self.go_status.setText("No records on %s. Nearest: %s before, %s." % (
            text, before or "nothing", ("%s after" % after) if after
            else "nothing after"))

    def nearest_periods(self, text):
        """(the latest period before `text`, the earliest after it) on the
        grain on screen, None where there is none. ISO labels compare as
        text, cut to the label's own length."""
        model = self.table.model()
        before = after = None
        if model is None:
            return before, after
        rows = self._segment_rows.get(self._active_key) or ()
        for row in rows:
            period = str(row.get("Period", ""))
            if not period:
                continue
            key = text[:len(period)]
            if period < key and (before is None or period > before):
                before = period
            elif period > key and (after is None or period < after):
                after = period
        return before, after

    def set_zone(self, offset_seconds, label):
        """The recovered zone, stated where the periods are read."""
        self._zone_offset = offset_seconds
        self._zone_name = label
        if offset_seconds is None:
            self.clock_buttons["local"].setEnabled(False)
            self.clock_buttons["local"].setText("Local")
            self.zone_label.setText(
                "No time zone was recovered for this exhibit, so periods "
                "are UTC only.")
        else:
            self.clock_buttons["local"].setEnabled(True)
            self.clock_buttons["local"].setText("Local (%s)" % label)
            self.zone_label.setText(
                "Recovered machine zone: %s (from SPS id-24 deltas). "
                "Periods follow the clock chosen here; a zone that changes "
                "with daylight saving is applied record by record."
                % label)

    def clock(self):
        return self._clock

    def show_clock(self, key):
        """Show `key` as the clock in force, without announcing it: the
        shell calls this when it rebuilds rows on that clock."""
        self._clock = key
        self.clock_buttons[key].setChecked(True)
        label = ("UTC" if key == "utc"
                 else getattr(self, "_zone_name", "") or "local")
        for rs in self._record_sets:
            for col in rs.columns:
                if col.key == "PeriodStart":
                    col.label = "Period start (%s)" % label

    def _set_clock(self, key):
        if key == self._clock:
            return
        self.show_clock(key)
        self.table.horizontalHeader().viewport().update()
        self.clockChanged.emit(key)

    def go_to_date(self, text):
        """Select the period whose label begins with `text` (a day, month,
        hour or minute prefix), clearing filters that hide it."""
        text = (text or "").strip()
        model = self.table.model()
        if not text or model is None:
            return False
        for attempt in (0, 1):
            for i in range(model.rowCount()):
                period = str(model.row_at(i).get("Period", ""))
                if period.startswith(text) or text.startswith(period):
                    self.table.selectionModel().setCurrentIndex(
                        model.index(i, 0),
                        QItemSelectionModel.ClearAndSelect
                        | QItemSelectionModel.Rows)
                    self.table.scrollTo(model.index(i, 0))
                    return True
            if attempt == 0 and model.filter.has_filters():
                self.clear_all_filters()
                model = self.table.model()
        return False

    # --- the second table --------------------------------------------------

    def _table_area(self):
        """The base's one hook -- see RecordsView._table_area.

        VERTICAL, unlike HeadersView's horizontal split: the pane holds a
        full record table with ten columns, and a table stacked beside
        another table gets neither of them enough width at 1280px.

        Idempotent for the same reason HeadersView's is: it is called once
        from the base constructor, but a caller (a test, most of all)
        asking a second time must get the SAME splitter rather than
        reparent the table out of the layout it is already in.
        """
        if self._splitter is None:
            # Built here rather than in __init__'s body: this method runs
            # from the base constructor, and _show_period needs both when
            # the first grain renders. annotate_basis is the base's badge
            # rule, so a heading here matches the same heading elsewhere.
            self.PERIOD_RECORD_COLUMNS = period_record_columns(self)
            self.annotate_basis(self.PERIOD_RECORD_COLUMNS)
            self.pane = SubTable()
            self.pane.clear(PANE_PROMPT)
            self.pane.exportRequested.connect(
                self.periodRecordsExportRequested.emit)
            splitter = QSplitter(Qt.Vertical)
            splitter.addWidget(self.table)
            splitter.addWidget(self.pane)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 2)
            # Draggable: whatever the examiner drags it to is theirs to
            # keep -- _set_pane_share only ever moves it on the transition
            # between "nothing selected" and "something selected".
            splitter.setChildrenCollapsible(True)
            # The grid keeps at least four rows in a window that fits the
            # page.
            self.table.setMinimumHeight(rows_height(self.table, 4))
            self._splitter = splitter
            self._set_pane_share(PANE_SHARE_IDLE)
        return self._splitter

    def _set_pane_share(self, share):
        """Hand the pane `share` of the splitter's height.

        Sizes are relative -- QSplitter normalises them against its real
        height -- so this works before the widget has ever been shown.
        With nothing selected the pane holds one sentence, and spending
        two fifths of the window on that sentence would cut the period
        grid down to a handful of rows; it widens on the first selection
        and narrows again when the selection goes away, and never touches
        a size the examiner set themselves in between.
        """
        splitter = self._splitter
        if splitter is None or self._pane_share == share:
            return
        self._pane_share = share
        total = max(splitter.height(), 800)
        splitter.setSizes([int(total * (1.0 - share)), int(total * share)])

    def _fit_short_list(self):
        """A short period list -- typically one day, typed into the filter
        -- keeps only the height its rows need, and the selected period's
        records get the rest: a one-row grid held three fifths of the
        window, mostly empty, while the day's records showed two at a time.
        When the list is long again (the filter cleared), the usual share
        comes back; a split the examiner dragged by hand is never undone."""
        splitter, table = self._splitter, self.table
        model = table.model() if table is not None else None
        if splitter is None or model is None:
            return
        sizes = splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        # The floor is four rows, or fewer when fewer periods are listed.
        listed = model.rowCount()
        table.setMinimumHeight(rows_height(table, max(1, min(4, listed))))
        rows = sum(table.rowHeight(i) for i in range(listed))
        scrollbar = table.horizontalScrollBar()
        need = (table.horizontalHeader().height() + rows
                + 2 * table.frameWidth()
                + (scrollbar.sizeHint().height() if scrollbar.isVisible() else 0)
                + 6)
        usual = int(total * (1.0 - PANE_SHARE_ACTIVE))
        if need < usual:
            splitter.setSizes([need, total - need])
            # What Qt applied: the grid's own minimum can take precedence.
            self._shrunk_to = splitter.sizes()[0]
        elif self._shrunk_to is not None:
            # Still where this view put it, give or take Qt's own re-layout
            # (a few pixels under the stylesheet); a drag moves it further.
            if abs(sizes[0] - self._shrunk_to) <= _SPLIT_SETTLE_PX:
                splitter.setSizes([usual, total - usual])
            self._shrunk_to = None

    # --- rendering ---------------------------------------------------------

    def _render_active_segment(self):
        """The base rebuilds the model, and so the selection model, on
        every set_records, so the connection is remade and the pane cleared
        each time."""
        super()._render_active_segment()
        self._set_calendar_span()
        # The bar's tooltip names what the share is of, which changes with
        # the grain, so it is set on every render.
        self.table.set_bar_unit(self._grain_singular())
        selection = self.table.selectionModel()
        if selection is not None:
            selection.currentRowChanged.connect(self._show_selected)
        self._show_period(None)

    def _set_calendar_span(self):
        """Limit Go to date's calendar to the first and last period."""
        model = self.table.model()
        starts = [r.get("PeriodStart") for r in
                  (model.filter.rows if model is not None else ())]
        starts = [d for d in starts if d is not None]
        if starts:
            self.date_calendar.set_span(min(starts), max(starts))
        # Each day's record count, from the by-day periods whatever grain
        # is on screen: the calendar picks days.
        counts = {}
        for row in self._segment_rows.get("day") or ():
            day = QDate.fromString(str(row.get("Period") or "")[:10],
                                   "yyyy-MM-dd")
            if day.isValid():
                counts[day] = row.get("Records") or 0
        self.date_calendar.set_day_counts(counts)

    def _update_count(self):
        """The base's count line, plus the pane's re-sync.

        A filter change refreshes the layout without emitting
        currentRowChanged, and the current index is a row number that does
        not move when the rows under it do, so the pane is re-read here.
        """
        super()._update_count()
        if self.pane is not None:
            self._resync_pane()
        self._rescale_share_bars()

    def _rescale_share_bars(self):
        """Recompute Share against the busiest period currently visible.

        period_rows() computes Share once against every bucket, and the
        bar's tooltip reads "N% of the busiest <grain> in this view". When
        a filter hides the busiest period, the shares are recomputed over
        the visible rows, so the peak is the one on screen. The row dicts
        are updated in place, so "Export view (N)", which writes
        model.filter.visible(), exports the Share the bars show.
        """
        model = self.table.model()
        if model is None:
            return
        visible = model.filter.visible()
        peak = max((row.get("Records") or 0 for row in visible), default=0) or 1
        for row in visible:
            row["Share"] = round((row.get("Records") or 0) / peak, 4)
        self.table.viewport().update()

    def _show_selected(self, current, _previous=None):
        model = self.table.model()
        if model is None or current is None or not current.isValid():
            self._show_period(None)
            return
        self._show_period(model.row_at(current.row()))

    def _resync_pane(self):
        """Re-sync the pane after any model refresh, including a filter
        keystroke that removes no rows.

        Every filter change runs inside beginResetModel/endResetModel
        (record_model.RecordTableModel._publishing), which resets the
        selection model and invalidates currentIndex() even when the
        visible rows are unchanged.

        So the pane's row is found by identity: self._current_row is the
        row dict shown, and a filter narrows RecordFilter._visible, a
        subset of the same row objects. Found, it is re-selected, so the
        table's highlight is kept; not found, the pane is cleared.
        """
        model = self.table.model()
        if model is None or self._current_row is None:
            self._show_period(None)
            return
        for i, row in enumerate(model.filter.visible()):
            if row is self._current_row:
                selection = self.table.selectionModel()
                if selection is not None:
                    selection.setCurrentIndex(
                        model.index(i, 0),
                        QItemSelectionModel.ClearAndSelect
                        | QItemSelectionModel.Rows)
                self._show_period(row)
                return
        self._show_period(None)

    def _show_period(self, row):
        """Fill the pane from one period row, or invite a selection."""
        self._current_row = row or None
        if not row or self._inputs is None:
            self.pane.clear(PANE_PROMPT)
            self._set_pane_share(PANE_SHARE_IDLE)
            return
        rows = record_rows(row, self._inputs)
        count = len(rows)
        self.grade_mixed(self.PERIOD_RECORD_COLUMNS, rows)
        # The note is on the heading line beside the export button, as in
        # Domains, so the pane keeps room for another record row.
        self.pane.set_rows(
            self.PERIOD_RECORD_COLUMNS, rows,
            "%s record%s in %s. %s" % (format(count, ","),
                                       "" if count == 1 else "s",
                                       row["Period"], PANE_NOTE),
            "", PANE_EMPTY, default_sort=("KeyTimeUtc", True))
        self._set_pane_share(PANE_SHARE_ACTIVE)
        self._fit_short_list()

    # --- what the pane needs from the shell --------------------------------

    def set_inputs(self, inputs):
        """Give the view the TimelineInput its period rows were built from
        (see _inputs above)."""
        self._inputs = inputs

    def show_building(self):
        """Called when a background Timeline build starts (at open, or
        after a recovery scan), before its results exist (see
        BUILDING_TEXT).

        Every grain is cleared through set_records_for(), as a real fill
        does, so the switcher buttons, the pane and the count line reset as
        for an empty exhibit. table.set_empty_reason() then shows
        BUILDING_TEXT in place of the grain's empty_text; the next real
        fill restores it.
        """
        self._inputs = None
        for grain, _label, _plural in GRAINS:
            self.set_records_for(grain, [], note=None)
        self.table.set_empty_reason(BUILDING_TEXT)

    def selected_period(self):
        """The label of the period whose records the pane is showing.

        Read from the model at the current index, so an export sidecar
        never names a period the file does not hold. "" when nothing is
        selected.
        """
        model = self.table.model()
        index = self.table.currentIndex()
        if model is None or not index.isValid() or index.row() >= model.rowCount():
            return ""
        return str(model.row_at(index.row()).get("Period") or "")

    def _grain_singular(self):
        for grain, _label, plural in GRAINS:
            if grain == self._active_key:
                return plural[:-1]
        return "period"

    # --- theme -------------------------------------------------------------

    def refresh_theme(self):
        super().refresh_theme()
        self.pane.refresh_theme()
