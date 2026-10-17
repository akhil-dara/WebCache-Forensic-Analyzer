"""Search: every table and every column of the open database.

This screen runs WebCacheParser.search_all_tables only. It reads the
database: every table dissect enumerates, including MSysObjects/
MSysObjectsShadow/MSysObjids, HSTS, dependency, AppCache and LeakFiles,
which no view interprets, and every column of every row, decoded once,
plus the hex, ASCII and UTF-16-LE readings of any binary value that did
not decode to text.

ForensicEngine.search is not used here: it searches the parsed record
set, which is what each record view's filter box does. The subtitle
states which search runs, so a zero is understood as "no cell in this
database holds this".

BOTH READINGS, SIDE BY SIDE. Every hit carries the matched value as
decoded and as stored (hex for binary, escaped for text). The column
labels distinguish them ("Matched value — decoded", "Matched value — as
stored"), which also carries into the CSV; colour is not used, because
ForegroundRole marks carved and live rows.

OPENING A HIT. A database hit is one row of a raw ESE table
(record_kinds.K_TABLE_ROW): it has no EntryId of the kind other rows carry
and no reference into parser.all_entries. Enter, Ctrl+Enter and the Table
link therefore open it in the Table Browser, on its table with that row
selected and a note naming the row (Row # is its position in the table).
A recovered hit is a parsed record and opens as one. The pane below the
grid holds every column of the selected hit, decoded and as stored.
explainRequested is wired, and origin_line describes this kind rather
than calling it a live record.

FOUR STATES, ALL WORDED. Idle, running, cancelled and finished with no
hits all show an empty grid, and each says which it is; above all, a
cancelled search never reads as one that found nothing (search_loader's
four constants).
"""
from PySide6.QtCore import Qt, QItemSelectionModel, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from ..shell import glyphs, search_loader, theme
from ..widgets import copyable
from ..widgets.column_spec import Column
from ..widgets.note_line import NoteLine
from ..widgets.keyword_delegate import KeywordDelegate
from ..widgets.sub_table import SubTable
from .records_view import RecordSet, RecordsView

#: What the pane says with nothing selected: what to do, as in SubTable.
PANE_PROMPT = ("Select a hit above. Every column of the row it was found "
               "in appears here, decoded and as the database stored it.")

#: What the pane's rows ARE. The distinction it draws is the whole point
#: of showing both columns: one of them is what this tool concluded, the
#: other is what it concluded it from.
PANE_NOTE = ("Every column of this row. The decoded reading is a "
             "conclusion; the stored reading is what it was drawn from.")

#: The pane's own empty state -- only reachable when a filter applied
#: INSIDE the pane removes every column of the row.
PANE_EMPTY = ("No column of this row matches the filter in force on this "
              "pane.")

#: Appended to PANE_NOTE when the bounded re-read returned nothing.
PANE_REREAD_NOTE = (" The stored reading could not be re-read for this "
                    "row, so every value in that column reads %s — the "
                    "decoded readings beside them are unaffected."
                    % search_loader.RAW_REREAD_FAILED)

#: The pane's note for a RECOVERED hit: its rows are the carved record's
#: own fields, not the columns of a database row.
PANE_RECOVERED_NOTE = ("Every field of this recovered record, as the "
                       "recovery scan holds it. It is not a row of any "
                       "table in the database: it was carved from the "
                       "bytes around them.")

#: The pane's share of the splitter with nothing selected, and with a hit
#: selected. Same arithmetic as TimelineView's, for the same reason: with
#: nothing selected the pane holds one sentence, and spending two fifths
#: of the window on that sentence would cut the hit grid down to a
#: handful of rows.
PANE_SHARE_IDLE = 0.16
PANE_SHARE_ACTIVE = 0.40

#: The two one-click presets. Each sets the keyword box AND searches, so
#: the box always says what produced the rows underneath it -- a preset
#: that searched without filling the box would leave the screen unable to
#: say what it had just done.
PRESETS = (("file:// only", "file://"),
           ("http(s)://", "http"))

#: The scope combo's width: wide enough for a Container_<id> display name
#: while leaving room for the keyword box.
_SCOPE_WIDTH = 280


#: What Row # means, for each kind of hit.
_ROW_MEANING = ("Row # is the 1-based position of the row WITHIN its table "
                "for a hit in one of the database's own tables — not an "
                "EntryId; two tables' row 4 have nothing to do with each "
                "other — and the record's position in Deleted Records for "
                "a hit in a recovered record. This searches what the "
                "database stored and what recovery carved, not the parsed "
                "records every other view lists.")


def _search_subtitle(count, recovered=None):
    """The subtitle. `recovered` is how many of `count` are hits in
    recovered records; None when the split is not known (the idle and
    empty states), and then no location is claimed for the hits."""
    head = "%s hit%s" % (format(count, ","), "" if count == 1 else "s")
    if recovered is not None:
        head += (": %s in the database's own tables and columns, %s in "
                 "recovered records (the fields read from the carved bytes)"
                 % (format(count - recovered, ","), format(recovered, ",")))
    # the count and the split only. What Row # means is
    # in the scope note, folded behind "Note: show all" with it.
    return head + "."


def hit_field_columns():
    """The pane's four columns -- one COLUMN of the matched row per row.

    Fresh per view for the reason headers.py already records: the base's
    badge loop annotates the Column objects themselves, so one shared
    list would be annotated once per view that used it. None of these
    names a `field` (a table-browser column name has no entry in the
    provenance catalogue, and basis_of() defaults an unknown key to
    DERIVED -- a fabricated badge), so none of them carries one.
    """
    return [
        Column("Column", "Column", 220, kind="text"),
        # Literal "yes"/"no", never a blank -- a blank here would read as
        # "not matched" for a column the pane failed to decide about.
        Column("Matched", "Matched", 90, kind="flag"),
        Column("Decoded", "Value as decoded", None, kind="text"),
        Column("Stored", "Value as stored", 300, kind="text"),
    ]


class SearchView(RecordsView):
    #: An examiner asked for a search. The view never calls the engine and
    #: never decides what "search" means -- the same division
    #: exportRequested already keeps. (keyword, table_filter); the filter
    #: is "" for every table, which is what the engine reads as no filter.
    searchRequested = Signal(str, str)

    #: The pane's own second export: the full field list of ONE hit's row.
    #: Forwarded from SubTable.exportRequested, same shape as
    #: TimelineView.periodRecordsExportRequested.
    rowFieldsExportRequested = Signal()

    #: A row here is a HIT, not a record: it is one row of a raw ESE
    #: table, and several of them can be the same underlying record seen
    #: through different tables. See RecordsView.COUNT_NOUN.
    COUNT_NOUN = "hits"

    #: Class defaults: _header_extra() and _table_area() are called from
    #: the base constructor, before this class's __init__ body, and PySide6
    #: refuses an instance attribute on a QWidget whose base __init__ has
    #: not run. All are replaced per instance.
    _splitter = None
    _pane_share = None
    _query_bar = None
    pane = None
    #: The hit ROW currently shown in the pane -- the actual dict, not its
    #: row number. See _resync_pane for why identity, not a row number, is
    #: what survives a filter keystroke.
    _current_row = None
    #: The parser the pane's bounded re-read uses. None until evidence is
    #: open; hit_field_rows then returns "(could not re-read)" rather than
    #: raising.
    _parser = None
    #: The Context column's highlight delegate -- built on the first
    #: render, which the BASE constructor runs (see above).
    _keyword_delegate = None
    #: What the hit grid currently holds. Only "done" is a search result:
    #: before one, while one runs and after a cancel, "0 hits" would read
    #: as a finding, so the heading and count line state the search's
    #: state instead and Export view waits for rows to export.
    _state = "idle"
    STATE_LINES = {"idle": "No search run yet",
                   "cancelled": "Search cancelled — nothing reported"}

    def __init__(self, parent=None):
        columns = [
            # A hit NAMES a real table, so this drills straight to it --
            # _drill_container_to_browser computes "Container_%d" from an
            # id and cannot serve a row that already has the name.
            Column("Table", "Table", 150, kind="text",
                   on_click=lambda row: self.drillRequested.emit("browser", row)),
            Column("Container", "Container", 190, kind="text",
                   field="ContainerName"),
            Column("TableType", "Table type", 110, kind="text"),
            # 1-BASED ORDINAL WITHIN THE TABLE, not an EntryId -- the
            # subtitle says so, because a number in a column called "Row"
            # beside a table name reads as an identifier otherwise.
            Column("Row", "Row #", 70, kind="num"),
            # Every matched column, ", "-joined. A text column with the
            # `contains` operator, since the set grows with each table's
            # columns. multi=True: these are ESE schema column names, which
            # cannot contain ", ", so split_multi() is safe and the value
            # picker offers each column name with its own row count.
            Column("MatchedColumns", "Matched columns", 175, kind="text",
                   multi=True),
            # flag, because this one IS a closed two-value set.
            Column("FoundIn", "Found in", 110, kind="flag"),
            # the keyword in its context, highlighted, and where in a
            # binary value it sits. The whole values are one click away:
            # the Columns menu, the pane below, and every export.
            Column("Context", "Keyword in context", 420, kind="text"),
            # BYTES, printed in hex -- the heading says so.
            Column("BlobOffset", "Byte offset in value", 150, kind="offset"),
            # The encoding the blob match was read in: the same bytes are
            # different text in another one.
            Column("BlobEncoding", "Matched as", 110, kind="flag"),
            Column("MatchedValue", "Matched value — decoded", 380,
                   kind="text", optional=True),
            Column("RawType", "Stored as", 90, kind="flag"),
            Column("RawValue", "Matched value — as stored", 380,
                   kind="text", optional=True),
            Column("Url", "URL", None, kind="url", field="Url"),
        ]
        super().__init__(
            record_sets=[RecordSet("hits", "Search hits", columns,
                                   subtitle=_search_subtitle,
                                   empty_text=search_loader.IDLE_TEXT)],
            header_icon="search", header_title="Search", parent=parent)
        self.set_idle()

    # --- the query bar -----------------------------------------------------

    def focus_target(self):
        """Arriving on Search, the examiner is about to type a query."""
        return self.keyword_box

    def _header_extra(self):
        """The keyword box, the scope, Search, the two presets, and the
        sentence that says what is being searched.

        Above the filter bar, not beside it: the filter box narrows the
        rows on screen, while this reads every table in the database
        again. Idempotent, as the base requires.
        """
        if self._query_bar is not None:
            return self._query_bar

        self.keyword_box = QLineEdit(
            placeholderText="Search every table, every column and the "
                            "recovered records…")
        self._search_action = self.keyword_box.addAction(
            glyphs.icon("search", theme.color("primary"), 15),
            QLineEdit.LeadingPosition)
        self.keyword_box.returnPressed.connect(self._emit_search)

        self.scope_combo = QComboBox()
        self.scope_combo.setFixedWidth(_SCOPE_WIDTH)
        self.set_scope_options(
            [(search_loader.ALL_TABLES, "All tables and recovered records")])

        self.search_button = QPushButton("Search")
        theme.mark_accent(self.search_button)
        self.search_button.clicked.connect(self._emit_search)

        self.preset_buttons = []
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.keyword_box, 1)
        row.addWidget(self.scope_combo)
        row.addWidget(self.search_button)
        for label, keyword in PRESETS:
            btn = QPushButton(label)
            btn.clicked.connect(
                lambda _checked=False, kw=keyword: self._search_preset(kw))
            self.preset_buttons.append(btn)
            row.addWidget(btn)

        # ON SCREEN, not in a tooltip. Three facts an examiner cannot get
        # anywhere else on this page, and the third one ("a hit inside a
        # blob is real but the Table Browser will not show it in that
        # cell") is the one that otherwise reads as a contradiction
        # between two screens.
        self.scope_note = copyable.selectable(QLabel(
            search_loader.SCOPE_NOTE + " " + _ROW_MEANING))
        self.scope_note.setWordWrap(True)

        bar = QWidget()
        self.scope_note_line = NoteLine(self.scope_note, bar,
                                        key="scope:SearchView")
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addLayout(row)
        note_row = QHBoxLayout()
        note_row.setSpacing(6)
        note_row.addWidget(self.scope_note, 1)
        note_row.addWidget(self.scope_note_line.toggle, 0, Qt.AlignTop)
        lay.addLayout(note_row)
        self._query_bar = bar
        self._refresh_query_bar_styles()
        return bar

    def _refresh_query_bar_styles(self):
        p = theme.PALETTES[theme.current_name()]
        self.scope_note.setStyleSheet(
            "font-size: 11.5px; background: transparent; color: %(muted)s;" % p)

    def _emit_search(self):
        self.searchRequested.emit(
            self.keyword(), search_loader.table_filter_for(self.scope()))

    def _search_preset(self, keyword):
        """Sets the box AND searches, in one step -- see PRESETS."""
        self.keyword_box.setText(keyword)
        self._emit_search()

    # --- what the shell asks of this view ---------------------------------

    def set_scope_options(self, options, keep_current=False):
        """Refill the scope combo from [(key, label), ...].

        Blocks signals while refilling: setCurrentIndex fires
        currentIndexChanged, and nothing here should be able to start a
        search as a side effect of an exhibit being opened.
        """
        options = list(options or [(search_loader.ALL_TABLES,
                                    "All tables and recovered records")])
        self.scope_combo.blockSignals(True)
        current = self.scope_combo.currentData() if keep_current else None
        self.scope_combo.clear()
        for key, label in options:
            self.scope_combo.addItem(label, key)
        # the tables are grouped by type under headings an examiner
        # reads but cannot pick.
        for i in range(self.scope_combo.count()):
            key = self.scope_combo.itemData(i)
            if str(key).startswith(search_loader.GROUP_PREFIX):
                item = self.scope_combo.model().item(i)
                item.setEnabled(False)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
        at = self.scope_combo.findData(current) if current is not None else -1
        self.scope_combo.setCurrentIndex(max(0, at))
        self.scope_combo.blockSignals(False)

    def set_parser(self, parser):
        """Hand the view the parser its pane re-reads stored bytes
        through -- see the _parser class attribute above."""
        self._parser = parser

    def keyword(self):
        return self.keyword_box.text().strip()

    def scope(self):
        data = self.scope_combo.currentData()
        return search_loader.ALL_TABLES if data is None else data

    def scope_label(self):
        return self.scope_combo.currentText().strip() or "All tables"

    # --- the four states ---------------------------------------------------

    def set_idle(self):
        """Evidence is open and nothing has been searched yet."""
        self._state = "idle"
        self._paint_empty(search_loader.IDLE_TEXT)
        self._end_running()

    def show_searching(self, query):
        """A search started. Clears the grid through set_records, as a real
        fill does, so the count line, the export button and the pane reset
        as for an empty result, and the previous search's rows are never
        shown under the new keyword."""
        self._state = "searching"
        self._searching_for = getattr(query, "keyword", "")
        self._paint_empty(search_loader.SEARCHING_TEXT)
        self.search_button.setEnabled(False)
        self.search_button.setText("Searching…")
        self._running_query = query

    def show_cancelled(self):
        """Nothing partial is ever reported -- see search_loader.
        CANCELLED_TEXT for why the wording matters more here than
        anywhere else on this screen."""
        self._state = "cancelled"
        self._paint_empty(search_loader.CANCELLED_TEXT)
        self._end_running()

    def show_results(self, query, result):
        """A finished search. `result` is the worker's payload: rows,
        skipped tables, rows scanned, tables searched."""
        result = result or {}
        rows = list(result.get("rows") or ())
        # The keyword is set BEFORE the rows paint, so the first frame
        # already highlights the search that produced them.
        self._ensure_keyword_delegate().keyword = getattr(query, "keyword", "")
        self._state = "done"
        self.set_records(rows, note=search_loader.result_note(query, result))
        recovered = sum(1 for r in rows
                        if r.get("Table") == search_loader.RECOVERED_TABLE)
        self.header.set_subtitle(_search_subtitle(len(rows), recovered))
        if not rows:
            text = search_loader.no_hits_text(getattr(query, "keyword", ""),
                                              result)
            sentence = search_loader.skipped_sentence(result.get("skipped"))
            if sentence:
                text += " " + sentence
            self.table.set_empty_reason(text)
        self._end_running()

    def _paint_empty(self, text):
        self.set_records([], note=None)
        # Overrides the RecordSet's empty_text that set_records just
        # restored (as TimelineView.show_building does); the next fill
        # restores it.
        self.table.set_empty_reason(text)
        # set_records wrote "0 hits" into the heading after the count
        # line ran; restate the search's state over both.
        self._update_count()

    def _state_line(self):
        model = self.table.model()
        if model is not None and model.filter.total_count:
            return None             # hits on the grid are a result
        if self._state == "searching":
            return 'Searching for "%s"…' % (self._searching_for or "")
        return self.STATE_LINES.get(self._state)

    def _end_running(self):
        self.search_button.setEnabled(True)
        self.search_button.setText("Search")
        self._running_query = None

    # --- the second table --------------------------------------------------

    def _table_area(self):
        """The base's one table-area hook -- see RecordsView._table_area.

        VERTICAL, like TimelineView's and for the same reason: the pane
        holds a four-column table whose two value columns are wide, and a
        table stacked beside another table gets neither of them enough
        width at 1280px.
        """
        if self._splitter is None:
            self.HIT_FIELD_COLUMNS = hit_field_columns()
        # The base's badge rule, applied to columns the base does not
        # build, so a heading here matches the same heading in a record
        # set.
            self.annotate_basis(self.HIT_FIELD_COLUMNS)
            self.pane = SubTable()
            self.pane.clear(PANE_PROMPT)
            self.pane.exportRequested.connect(
                self.rowFieldsExportRequested.emit)
            splitter = QSplitter(Qt.Vertical)
            splitter.addWidget(self.table)
            splitter.addWidget(self.pane)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 2)
            splitter.setChildrenCollapsible(True)
            self._splitter = splitter
            self._set_pane_share(PANE_SHARE_IDLE)
        return self._splitter

    def _ensure_keyword_delegate(self):
        if self._keyword_delegate is None:
            self._keyword_delegate = KeywordDelegate(self.table)
        return self._keyword_delegate

    def _set_pane_share(self, share):
        """Give the pane `share` of the splitter's height, as in
        TimelineView, keeping any size the examiner set in between."""
        splitter = self._splitter
        if splitter is None or self._pane_share == share:
            return
        self._pane_share = share
        total = max(splitter.height(), 800)
        splitter.setSizes([int(total * (1.0 - share)), int(total * share)])

    # --- rendering ---------------------------------------------------------

    def _render_active_segment(self):
        """The base rebuilds the model, and so the selection model, on
        every set_records, so the connection is remade and the pane cleared
        each time."""
        super()._render_active_segment()
        # set_records resets every non-bar column's delegate, so the
        # Context column's highlight is re-installed on every render.
        keys = [c.key for c in self.table.model().columns]
        if "Context" in keys:
            self.table.setItemDelegateForColumn(
                keys.index("Context"), self._ensure_keyword_delegate())
        selection = self.table.selectionModel()
        if selection is not None:
            selection.currentRowChanged.connect(self._show_selected)
        self._show_hit(None)

    def _update_count(self):
        """The base's count line, plus the pane's re-sync.

        A filter change refreshes the layout without emitting
        currentRowChanged, and the current index is a row number that does
        not move when the rows under it do, so the pane is re-read from the
        model here.
        """
        super()._update_count()
        # Only a finished search is a count: before one, while one runs
        # and after a cancel, the heading and count line say which.
        line = self._state_line()
        # Everything that acts on hits waits for hits to exist.
        for tool in (self.export_button, self.filter_box,
                     self.identical_button, self.columns_button,
                     self.clear_filters_button):
            tool.setEnabled(line is None)
        if line is not None:
            self.count_label.setText(line)
            self.header.set_subtitle(line + ".")
        if self.pane is not None:
            self._resync_pane()

    def _show_selected(self, current, _previous=None):
        model = self.table.model()
        if model is None or current is None or not current.isValid():
            self._show_hit(None)
            return
        self._show_hit(model.row_at(current.row()))

    def _resync_pane(self):
        """Re-sync the pane after ANY model refresh, by IDENTITY.

        table.currentIndex() is a row number, and every filter change
        runs inside beginResetModel/endResetModel -- which invalidates it
        even when the visible rows are completely unchanged. self.
        _current_row is the actual row DICT the pane is showing, and a
        filter narrows RecordFilter's visible list to a SUBSET of the
        same row objects, so the selected row can be found again by
        identity even though its row number cannot be trusted. Found, it
        is re-SELECTED so the grid's own highlight survives the reset;
        not found, the pane clears.
        """
        model = self.table.model()
        if model is None or self._current_row is None:
            self._show_hit(None)
            return
        for i, row in enumerate(model.filter.visible()):
            if row is self._current_row:
                selection = self.table.selectionModel()
                if selection is not None:
                    selection.setCurrentIndex(
                        model.index(i, 0),
                        QItemSelectionModel.ClearAndSelect
                        | QItemSelectionModel.Rows)
                self._show_hit(row)
                return
        self._show_hit(None)

    def _show_hit(self, row):
        """Fill the pane from one hit row, or invite a selection."""
        self._current_row = row or None
        if not row:
            self.pane.clear(PANE_PROMPT)
            self._set_pane_share(PANE_SHARE_IDLE)
            return
        if row.get("_result") is None and row.get("_record") is not None:
            # A recovered hit: the record is the carve itself, so
            # its fields are shown as held -- there is no row to re-read.
            rows = search_loader.recovered_field_rows(
                row, self._ensure_keyword_delegate().keyword)
            note = PANE_RECOVERED_NOTE
        else:
            rows = search_loader.hit_field_rows(self._parser,
                                                row.get("_result"))
            note = PANE_NOTE
            if search_loader.reread_failed(rows):
                note += PANE_REREAD_NOTE
        self.pane.set_rows(
            self.HIT_FIELD_COLUMNS, rows,
            "Row %s of %s" % (row.get("Row", ""), row.get("Table", "")),
            note, PANE_EMPTY)
        self._set_pane_share(PANE_SHARE_ACTIVE)

    def selected_hit_label(self):
        """Which hit the pane is showing, for an export sidecar to name.

        Read from the model at the current index, so a sidecar never names
        a row the file does not hold. "" when nothing is selected.
        """
        model = self.table.model()
        index = self.table.currentIndex()
        if model is None or not index.isValid() or index.row() >= model.rowCount():
            return ""
        row = model.row_at(index.row())
        return "%s row %s" % (row.get("Table", ""), row.get("Row", ""))

    # --- theme -------------------------------------------------------------

    def refresh_theme(self):
        super().refresh_theme()
        self._search_action.setIcon(
            glyphs.icon("search", theme.color("primary"), 15))
        self._refresh_query_bar_styles()
        self.pane.refresh_theme()
