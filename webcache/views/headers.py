"""HTTP Headers: the records that carry them, and a pane that reads one
as stored.

The nav caveat says headers are as stored by the cache, which may be a
partial record. This view also states which records are listed at all: a
History record whose ResponseHeaders blob is a property store (SPS) has no
header dict and is not listed (see shell/headers_loader.py). On a
History-heavy exhibit that is most of the database, so the reason is shown
with the count.

A two-pane view: RecordsView._table_area() is overridden to add the pane.
The splitter is draggable, and the pane starts on its placeholder so the
table has the width until something is selected.

Two buttons, two numbers. "Export view (N)" writes one row per record,
what the table shows. "Export header pairs (N)" writes one row per pair,
recounted from the rows currently visible. They are shown side by side.

No hex dump in the pane: the record dialog's blob viewer shows the full
blob, paged, with strings, a decode, a content hash and a byte export,
from the shared BLOB_FIELDS catalogue.

Colour: the response side is drawn in `primary`, the request side in
`secondary`, and a client-IP header name in `warn`. Each fact is also
stated in words: the section headings name the side and carry its count,
and a client-IP header carries HEADER_INTEREST's sentence beneath it.
"""
import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QSplitter,
                               QVBoxLayout, QWidget)

from ..provenance import ABSENCE_EMPTY
from ..shell import glyphs, theme
from ..widgets import copyable
from ..shell.headers_loader import (CLIENT_IP_NOTE, HEADER_INTEREST,
                                    STATUS_LINE_LABEL, duplicates_note,
                                    header_pairs, total_pairs)
from ..widgets.column_spec import Column
from ..widgets.record_filter import Condition
from .records_view import QuickFilter, RecordSet, RecordsView

#: What the pane says before anything is selected. A pane that opened
#: blank would read as a pane that failed to load.
PLACEHOLDER = "Select a request on the left to see its headers as stored."

#: The exclusion, in the subtitle an examiner reads on every visit.
_SPS_SENTENCE = ("A History record whose ResponseHeaders blob is a "
                 "property store (SPS) carries no headers at all and is "
                 "not listed here.")

#: The empty state, painted centred in the table. The search box, the
#: export button and the columns stay, so the view reads as "this exhibit
#: has none" rather than as broken.
EMPTY_TEXT = ("No record in this exhibit carries HTTP headers. History "
              "records store a property store (SPS) in the "
              "ResponseHeaders column instead, which is not a header set.")

#: The pane's share of the splitter with nothing selected, and with a row
#: selected. See HeadersView._set_pane_share for why it moves.
PANE_SHARE_IDLE = 0.18
PANE_SHARE_ACTIVE = 0.38


def build_columns(view=None):
    """This view's columns, built per instance.

    Per instance because ContainerId's on_click holds a reference to the
    view that owns it; a shared Column would bind only the last view
    built.

    `view=None` yields the same declaration with no drill target: the
    module-level COLUMNS below, for anything that only reads the spec.

    HttpStatus, ContentType and Server are in evidence_model.
    FIELD_PROVENANCE (graded OBSERVED), so they get basis badges.
    ClientIpHeaders and DuplicateCount are computed here and have no
    catalogue entry, so their field is None and no badge is painted.
    """
    drill = None
    if view is not None:
        drill = lambda row: view.drillRequested.emit("browser", row)  # noqa: E731
    return [
        Column("CleanUrl", "Address", 420, kind="url", field="CleanUrl"),
        Column("Status", "Status", 75, kind="text", field="HttpStatus"),
        Column("RespCount", "Response headers", 130, kind="num"),
        Column("ReqCount", "Request headers", 125, kind="num"),
        Column("DuplicateCount", "Repeated names", 120, kind="num",
               field=None),
        Column("ContentType", "Content type", 180, kind="text",
               field="ContentType"),
        Column("Server", "Server", 150, kind="text", field="Server"),
        Column("ClientIpHeaders", "Client-IP headers", 175, kind="text",
               field=None),
        Column("ModifiedTime", "Stored (UTC)", 165, kind="time"),
        Column("ContainerId", "Container", 100, kind="num", on_click=drill),
        Column("Origin", "Origin detail", 170, kind="text", field="Origin"),
        Column("Source", "Carved from", 150, kind="text", field="Source",
               blank_text="(live record, not carved)"),
    ]


#: The column declaration, with no drill target -- see build_columns.
COLUMNS = build_columns()


class HeaderPane(QWidget):
    """One record's headers, as stored, beside the table.

    Renders from headers_loader.header_pairs(): the raw blob in wire
    order, with every value a repeated name overwrote, rather than the
    decoded dict, which keeps only the last of each.

    Opening the whole record and browsing the container are emitted as
    signals; the shell acts on them.
    """
    detailRequested = Signal(object)
    containerRequested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row = None
        self._rendered = {"response": [], "request": []}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 4, 4)
        root.setSpacing(8)

        self.placeholder = copyable.selectable(QLabel(PLACEHOLDER))
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(Qt.AlignTop)
        root.addWidget(self.placeholder)

        self.content = QWidget()
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        self.url_label = QLabel("")
        self.url_label.setWordWrap(True)
        copyable.selectable(self.url_label)
        body.addWidget(self.url_label)

        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        copyable.selectable(self.meta_label)
        body.addWidget(self.meta_label)

        self.origin_label = copyable.selectable(QLabel(""))
        self.origin_label.setWordWrap(True)
        body.addWidget(self.origin_label)

        self.duplicates_label = copyable.selectable(QLabel(""))
        self.duplicates_label.setWordWrap(True)
        body.addWidget(self.duplicates_label)

        self.client_ip_label = copyable.selectable(QLabel(""))
        self.client_ip_label.setWordWrap(True)
        body.addWidget(self.client_ip_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.detail_button = QPushButton("Open full record detail")
        self.container_button = QPushButton("Browse container")
        theme.mark_outline(self.detail_button)
        theme.mark_outline(self.container_button)
        self.detail_button.clicked.connect(
            lambda: self.detailRequested.emit(self._row))
        self.container_button.clicked.connect(
            lambda: self.containerRequested.emit(self._row))
        buttons.addWidget(self.detail_button)
        buttons.addWidget(self.container_button)
        buttons.addStretch(1)
        body.addLayout(buttons)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("keyScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        pairs_holder = QWidget()
        self._pairs_column = QVBoxLayout(pairs_holder)
        self._pairs_column.setContentsMargins(0, 0, 8, 0)
        self._pairs_column.setSpacing(10)

        (self.response_block, self._response_heading,
         self.response_text) = self._build_block("Response")
        (self.request_block, self._request_heading,
         self.request_text) = self._build_block("Request")
        self._pairs_column.addWidget(self.response_block)
        self._pairs_column.addWidget(self.request_block)
        self._pairs_column.addStretch(1)
        self.scroll.setWidget(pairs_holder)
        body.addWidget(self.scroll, 1)

        root.addWidget(self.content, 1)
        self.content.setVisible(False)
        self.refresh_theme()

    # --- construction helpers --------------------------------------------

    def _build_block(self, title):
        """A heading, and one rich-text label under it for all the pairs.

        One wrapped label per side rather than two labels per pair: a
        word-wrapped QLabel in a QVBoxLayout inside a scroll area is not
        given its full wrapped height, so per-pair labels overlap.
        """
        block = QWidget()
        column = QVBoxLayout(block)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        heading = copyable.selectable(QLabel(title))
        column.addWidget(heading)
        text = QLabel("")
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        copyable.selectable(text)
        text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        column.addWidget(text)
        return block, heading, text

    # --- what is on screen -------------------------------------------------

    def current_row(self):
        return self._row

    def rendered_pairs(self, side):
        """(name, value) for one side, as painted, so tests check what the
        pane drew."""
        return [(name, value) for name, value in self._rendered[side]]

    def rendered_names(self, side):
        return [name for name, _value in self._rendered[side]]

    # --- filling -----------------------------------------------------------

    def set_row(self, row):
        """Show one row's headers. None clears back to the placeholder."""
        self._row = row
        self._rendered = {"response": [], "request": []}
        if row is None:
            self.response_text.setText("")
            self.request_text.setText("")
            self.content.setVisible(False)
            self.placeholder.setVisible(True)
            return
        self.placeholder.setVisible(False)
        self.content.setVisible(True)

        self.url_label.setText(row.get("CleanUrl") or "")
        container = row.get("ContainerName") or ""
        self.meta_label.setText(
            "Container %s%s · Entry %s · Stored %s"
            % (row.get("ContainerId"),
               (" (%s)" % container) if container else "",
               # ABSENCE_EMPTY, never a dash: a missing value is one of
               # the fixed absence sentences (tests/test_absence_vocabulary.py).
               row.get("EntryId"),
               row.get("ModifiedTime") or ABSENCE_EMPTY))

        origin = row.get("Origin") or ""
        source = row.get("Source") or ""
        self.origin_label.setText(
            origin + ((" — from %s" % source) if source else ""))
        self._paint_origin()

        duplicates = int(row.get("DuplicateCount") or 0)
        self.duplicates_label.setText(
            duplicates_note(duplicates) if duplicates else "")
        self.duplicates_label.setVisible(bool(duplicates))

        client_ip = row.get("ClientIpHeaders") or ""
        self.client_ip_label.setText(
            ("%s — %s" % (client_ip, CLIENT_IP_NOTE)) if client_ip else "")
        self.client_ip_label.setVisible(bool(client_ip))

        self.container_button.setText(
            "Browse Container_%s" % row.get("ContainerId"))

        record = row.get("_record") or {}
        self._fill_block("response", record, self.response_block,
                         self._response_heading, self.response_text,
                         "Response", "primary")
        self._fill_block("request", record, self.request_block,
                         self._request_heading, self.request_text,
                         "Request", "secondary")

    def _fill_block(self, side, record, block, heading, text, title, role):
        """One side. An EMPTY side is absent entirely -- no "(none)"
        placeholder: a heading with nothing under it says there is
        something here and then fails to show it."""
        text.setText("")
        pairs = header_pairs(record, side)
        if not pairs:
            block.setVisible(False)
            return
        block.setVisible(True)
        # The count is stated in WORDS beside the heading, so the side is
        # never distinguished by its colour alone.
        heading.setText("%s — %d line%s as stored"
                        % (title, len(pairs), "" if len(pairs) == 1 else "s"))
        heading.setStyleSheet(
            "font-size: 12px; font-weight: 600; background: transparent; "
            "color: %s;" % theme.color(role).name())
        blocks = []
        for _ordinal, name, value, _repeats in pairs:
            self._rendered[side].append((name, value))
            blocks.append(self._pair_markup(name, value, role))
        text.setText("".join(blocks))

    def _pair_markup(self, name, value, role):
        """One pair, as markup.

        EVERY value is escaped. A header value is evidence: a stored
        value containing angle brackets must be READ, not interpreted,
        and a tool that renders it as markup has changed what the
        examiner sees.
        """
        interesting = name.lower() in HEADER_INTEREST
        name_colour = theme.color(
            "warn" if interesting else
            ("muted" if name == STATUS_LINE_LABEL else role)).name()
        out = ['<p style="margin:0 0 7px 0;">'
               '<span style="color:%s; font-size:11px; font-weight:600;">'
               '%s</span><br/>'
               '<span style="color:%s; font-size:11px;">%s</span>'
               % (name_colour, html.escape(name),
                  theme.color("text").name(), html.escape(value or ""))]
        if interesting:
            out.append('<br/><span style="color:%s; font-size:11px;">%s</span>'
                       % (theme.color("warn").name(),
                          html.escape(CLIENT_IP_NOTE)))
        out.append("</p>")
        return "".join(out)

    def _paint_origin(self):
        """The origin line's colour, decided from the line itself.

        Called from set_row and from refresh_theme, so a carved record's
        origin line is coloured as carved. The words state the origin;
        colour reinforces it.

        The rule is "starts with Carved", as in record_model.py and
        provenance.describe_origin(), so a row is never styled differently
        in two places.
        """
        p = theme.PALETTES[theme.current_name()]
        self.origin_label.setStyleSheet(
            "font-size: 11.5px; background: transparent; color: %s;"
            % (p["carved"] if str(self.origin_label.text()).startswith("Carved")
               else p["muted"]))

    # --- theme -------------------------------------------------------------

    def refresh_theme(self):
        p = theme.PALETTES[theme.current_name()]
        self.placeholder.setStyleSheet(
            "font-size: 12px; background: transparent; color: %(muted)s;" % p)
        self.url_label.setStyleSheet(
            "font-size: 12.5px; font-weight: 600; background: transparent; "
            "color: %(url)s;" % p)
        self.meta_label.setStyleSheet(
            "font-size: 11.5px; background: transparent; color: %(muted)s;" % p)
        self._paint_origin()
        for label in (self.duplicates_label, self.client_ip_label):
            label.setStyleSheet(
                "font-size: 11.5px; background: transparent; "
                "color: %(warn)s;" % p)
        # This sheet outranks the app's, so the keyboard ring theme.py
        # gives QScrollArea#keyScroll is restated here.
        self.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea#keyScroll { border: 2px solid transparent; }"
            "QScrollArea#keyScroll:focus { border: 2px solid %(primary)s; }"
            % p)
        # Re-render what is on screen: the labels use inline styles, which
        # a stylesheet change alone does not update.
        if self._row is not None:
            self.set_row(self._row)


class HeadersView(RecordsView):
    #: The pair export. A SECOND signal rather than a parameter on
    #: exportRequested: the base's own signal is zero-argument on purpose
    #: (a view says only that an examiner asked), and giving it an
    #: argument would change that contract for six other views to save one
    #: line here.
    pairExportRequested = Signal()

    #: Class defaults: _table_area() is called from the base constructor,
    #: before this class's __init__ body, and PySide6 refuses an instance
    #: attribute on a QWidget whose base __init__ has not run. Both are
    #: replaced per instance later.
    _splitter = None
    #: The pane's current share of the splitter -- see
    #: _set_pane_share. A class default for the same reason
    #: _splitter is one: it is read from inside the base constructor.
    _pane_share = None
    #: The rows for the WHOLE record set, kept so the subtitle can state
    #: the pair total across all of them while the button states it across
    #: the visible ones. A list of the same row dicts, never a copy.
    _all_rows = ()

    def __init__(self, parent=None):
        quick_filters = [
            QuickFilter("chip_request_side", "Has request headers", "primary",
                        "ReqCount", condition=Condition(">", 0)),
            QuickFilter("chip_client_ip", "Client-IP headers", "error",
                        "ClientIpHeaders", condition=Condition("is not blank")),
            QuickFilter("chip_error_status", "4xx / 5xx", "error",
                        "StatusClass", values={"4xx", "5xx"}),
        ]
        super().__init__(
            record_sets=[RecordSet(
                "headers", "HTTP Headers", build_columns(self),
                subtitle=self._headers_subtitle, empty_text=EMPTY_TEXT)],
            header_icon="folder", header_title="HTTP Headers",
            quick_filters=quick_filters, parent=parent)

        self.pairs_export_button = QPushButton("Export header pairs (0)")
        self.pairs_export_button.setIcon(
            glyphs.icon("download", theme.color("primary"), 15))
        theme.mark_outline(self.pairs_export_button)
        self.pairs_export_button.clicked.connect(self.pairExportRequested.emit)
        bar = self._button_bar()
        bar.insertWidget(bar.indexOf(self.export_button) + 1,
                         self.pairs_export_button)

        self.detail_pane.detailRequested.connect(self._open_selected_record)
        self.detail_pane.containerRequested.connect(
            lambda row: self.drillRequested.emit("browser", row))

    # --- the second pane ---------------------------------------------------

    def _table_area(self):
        """The base's one hook -- see RecordsView._table_area.

        Idempotent: it is called once from the base constructor, but a
        caller (a test, most of all) asking for the table area a second
        time must get the SAME splitter. Building a second one would
        reparent the table out of the layout it is already in.
        """
        if self._splitter is None:
            self.detail_pane = HeaderPane()
            splitter = QSplitter(Qt.Horizontal)
            splitter.addWidget(self.table)
            splitter.addWidget(self.detail_pane)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 2)
            # Draggable. Whatever the examiner drags
            # it to is theirs to keep: _set_pane_share only ever moves it
            # on the transition between "nothing selected" and
            # "something selected".
            splitter.setChildrenCollapsible(True)
            self._splitter = splitter
            self._set_pane_share(PANE_SHARE_IDLE)
        return self._splitter

    def _set_pane_share(self, share):
        """Give the pane `share` of the splitter's width.

        Sizes are relative (QSplitter normalises them against its width), so
        this works before the widget is shown.

        With nothing selected the pane holds one sentence, so the table
        gets most of the width; the pane widens on the first selection and
        narrows when the selection is cleared, and a size the examiner set
        in between is kept.
        """
        splitter = self._splitter
        if splitter is None or self._pane_share == share:
            return
        self._pane_share = share
        total = max(splitter.width(), 1000)
        splitter.setSizes([int(total * (1.0 - share)), int(total * share)])

    def _button_bar(self):
        """The QHBoxLayout the base put the Export view button in.

        Found rather than passed, since the base owns that row. Raises if
        it is not found, rather than placing the button elsewhere.
        """
        root = self.layout()
        for index in range(root.count()):
            layout = root.itemAt(index).layout()
            if layout is not None and layout.indexOf(self.export_button) >= 0:
                return layout
        raise RuntimeError(
            "RecordsView no longer puts export_button in a row layout")

    def _render_active_segment(self):
        """The base rebuilds the model (and therefore the selection model)
        on every set_records, so the pane's connection has to be remade
        each time and the pane itself cleared -- a pane still showing the
        previous record set's row would be describing rows that are no
        longer in the table."""
        super()._render_active_segment()
        selection = self.table.selectionModel()
        if selection is not None:
            selection.currentRowChanged.connect(self._show_selected)
        self.detail_pane.set_row(None)
        self._set_pane_share(PANE_SHARE_IDLE)

    def _show_selected(self, current, _previous=None):
        model = self.table.model()
        if model is None or current is None or not current.isValid():
            self.detail_pane.set_row(None)
            self._set_pane_share(PANE_SHARE_IDLE)
            return
        self.detail_pane.set_row(model.row_at(current.row()))
        self._set_pane_share(PANE_SHARE_ACTIVE)

    def _open_selected_record(self, _row):
        """Through the table's own open_record, not by re-emitting the row
        directly: that is the one route a link column cannot intercept,
        and it is the same route Enter and the context menu already take.
        """
        index = self.table.currentIndex()
        if index.isValid():
            self.table.open_record(index.row())

    # --- counts ------------------------------------------------------------

    def set_records(self, rows, note=None):
        self._all_rows = list(rows)
        super().set_records(rows, note)

    def _headers_subtitle(self, count):
        return ("%s record%s carrying HTTP headers · %s header pairs. %s"
                % (format(count, ","), "" if count == 1 else "s",
                   format(total_pairs(self._all_rows), ","), _SPS_SENTENCE))

    def _update_count(self):
        """The base's count line, plus the pair button's own number.

        Recomputed from the rows currently VISIBLE, which is the whole
        point: pair rows captured once at view-build time would let a
        filtered view export pairs the examiner had never seen. Arithmetic on a key every row already carries, so it costs
        nothing on a keystroke.
        """
        super()._update_count()
        button = getattr(self, "pairs_export_button", None)
        if button is None:
            return
        model = self.table.model()
        pairs = total_pairs(model.filter.visible()) if model is not None else 0
        button.setText("Export header pairs (%s)" % format(pairs, ","))
        self._resync_pane()

    def _resync_pane(self):
        """Keep the pane on the row it describes.

        A filter change refreshes the layout without emitting
        currentRowChanged (the current index is a row number, which does
        not move when the rows under it do), so the pane is re-read from
        the model on every refresh: it shows whatever the current index
        points at, and nothing when it points at nothing.
        """
        model = self.table.model()
        index = self.table.currentIndex()
        if model is None or not index.isValid() or index.row() >= model.rowCount():
            self.detail_pane.set_row(None)
            self._set_pane_share(PANE_SHARE_IDLE)
            return
        self.detail_pane.set_row(model.row_at(index.row()))
        self._set_pane_share(PANE_SHARE_ACTIVE)

    def visible_rows(self):
        """The rows the pair export writes: on-screen order, after sorting,
        the rows the button's number counts."""
        model = self.table.model()
        return list(model.filter.visible()) if model is not None else []

    # --- theme -------------------------------------------------------------

    def refresh_theme(self):
        super().refresh_theme()
        self.pairs_export_button.setIcon(
            glyphs.icon("download", theme.color("primary"), 15))
        self.detail_pane.refresh_theme()
