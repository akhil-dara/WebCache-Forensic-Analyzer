"""The Dashboard: the first screen once evidence opens.

Six headline chips and three cards (Container Types, Top 10 Domains, Case
summary) in a 1:2:1 proportion. Domain bars use a square-root scale; on a
linear one most bars would be indistinguishable stubs beside the busiest.

Every figure is reproduced in the view it came from, and every chip and
card row emits drillRequested to open that view:

  Total Records  -> Table Browser  (a sum across every container type; the
                    raw tables are where it can be enumerated)
  Tables         -> Table Browser  (the tables it counts)
  Containers     -> Containers     (the containers it counts)
  InPrivate      -> History        (where InPrivate records can be
                    filtered, with the "InPrivate only" chip)
  Cache Size     -> File Access    (the view with FileSize/DownloadSize)

Container Types rows open Containers, and Top Domains rows open Domains.
MainWindow.go_to(key) navigates; the destination is not pre-filtered.

This view never reads the engine or a parser: dashboard_data.py
(webcache/shell/) shapes the figures. set_data() takes that module's dict
and an optional `summary`, dashboard_data.case_summary()'s rows for the
Case summary card: the activity range in UTC and local (and what it
covers), the recovered zone, the database state, the SHA-256 and whether
recovery ran. The live/recovered split is in the headline chips and the
subtitle.

Before set_data() is called every chip reads "-", never "0", and every
card states that no evidence is open. A count of zero is a fact; a count
never computed is not (see StatChip).
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                               QVBoxLayout, QWidget)

from .. import provenance
from ..provenance import CONTAINER_NOT_DETERMINABLE
from ..shell import theme
from ..shell import record_counts
from ..shell.dashboard_data import (apportioned_percentages,
                                    database_info_rows, format_size)
from ..widgets import copyable
from ..widgets.card import Card, ClickableRow
from ..widgets.content_header import CaveatLine, ViewHeader
from ..widgets.stat_chip import StatChip
from ..widgets.wrapping_text import WrappingText

#: chip attribute key -> nav key it drills to -- see the module docstring
#: for why each one is the chosen destination.
_CHIP_DRILL_TARGETS = {
    "records": "browser", "recovered": "recovery",
    "tables": "browser", "containers": "containers",
    "inprivate": "history", "cache_size": "downloads",
}

#: Container-type dot and count colours, from theme.py's palette roles.
#: Downloads takes the "url" accent. Unknown types, and
#: CONTAINER_NOT_DETERMINABLE, use a neutral tone: an unresolved container
#: is a limit of string carving, not a finding.
_CONTAINER_TYPE_COLORS = {
    "History": "primary", "Content": "secondary", "Cookies": "carved",
    "Downloads": "url", "DOMStore": "warn", "BackgroundTransfer": "muted2",
    CONTAINER_NOT_DETERMINABLE: "muted2",
}


def _container_type_color(name):
    return _CONTAINER_TYPE_COLORS.get(name, "muted")


def _clear_layout(layout):
    """Removes every item a layout holds -- widgets AND stretches/spacers
    -- so a card's body can be rebuilt from scratch on every set_data()
    call (evidence load, then again after a recovery scan, then again on
    every theme toggle) without old rows or a growing pile of leftover
    stretch items accumulating underneath the new ones."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
        else:
            sub = item.layout()
            if sub is not None:
                _clear_layout(sub)


def _muted_line(text):
    lbl = copyable.selectable(QLabel(text))
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        "background: transparent; font-size: 12px; color: %s;"
        % theme.PALETTES[theme.current_name()]["muted"])
    return lbl


class DashboardView(QWidget):
    #: Same signature as RecordsView.drillRequested, so MainWindow wires
    #: both the same way: drillRequested.connect(lambda k, _row: go_to(k)).
    drillRequested = Signal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stats = None
        self._container_type_rows = []
        self._domain_rows = []
        self.all_domains_row = None
        self._db_info_rows = []
        self._container_type_names = []
        self._summary = None

        self.header = ViewHeader("grid", "Dashboard")
        self.caveat = CaveatLine()

        chip_row = QHBoxLayout()
        chip_row.setSpacing(10)
        # Colours: accent for records, secondary
        # accent for tables/containers, danger for InPrivate, gold
        # (theme's "carved" role) for cache size -- theme.py tokens only.
        self.chip_records = StatChip("Live records", accent="primary")
        self.chip_recovered = StatChip("Recovered records", accent="carved")
        self.chip_tables = StatChip("Tables", accent="secondary")
        self.chip_containers = StatChip("Containers", accent="secondary")
        self.chip_inprivate = StatChip("InPrivate", accent="error")
        self.chip_cache_size = StatChip("Cache Size", accent="carved")
        for chip, key in (
            (self.chip_records, "records"),
            (self.chip_recovered, "recovered"), (self.chip_tables, "tables"),
            (self.chip_containers, "containers"),
            (self.chip_inprivate, "inprivate"),
            (self.chip_cache_size, "cache_size"),
        ):
            chip.clicked.connect(lambda k=key: self._drill_chip(k))
            chip_row.addWidget(chip, 1)

        card_row = QHBoxLayout()
        card_row.setSpacing(8)
        self.card_container_types = Card("database", "Container Types")
        self.card_top_domains = Card("database", "Top 10 Domains")
        self.card_case_summary = Card("file", "Case summary")
        #: Alias kept for existing callers.
        self.card_database_info = self.card_case_summary
        # 1:2:1: Top Domains carries a rank, a bar and a count per row and
        # needs the extra width.
        card_row.addWidget(self.card_container_types, 1)
        card_row.addWidget(self.card_top_domains, 2)
        card_row.addWidget(self.card_case_summary, 2)

        root = QVBoxLayout(self)
        root.addWidget(self.header)
        root.addWidget(self.caveat)
        root.addLayout(chip_row)
        root.addLayout(card_row, 1)

        # Renders the no-evidence state: self._stats is still None, and
        # refresh_theme() builds the empty state in that case.
        self.refresh_theme()

    # --- caveat / theme -----------------------------------------------

    def set_caveat(self, text):
        self.caveat.set_text(text)

    def refresh_theme(self):
        """Repaint for the current theme. Card rows are built with inline
        styles from theme.color(), so they are rebuilt by re-running
        set_data() with the last data given, or the empty state is
        re-rendered when no data has been given."""
        self.header.refresh_theme()
        self.caveat.refresh_theme()
        for chip in (self.chip_records, self.chip_recovered, self.chip_tables,
                    self.chip_containers, self.chip_inprivate,
                    self.chip_cache_size):
            chip.refresh_theme()
        for card in (self.card_container_types, self.card_top_domains,
                    self.card_case_summary):
            card.refresh_theme()
        if self._stats is None:
            self._render_empty()
        else:
            self.set_data(self._stats, summary=self._summary)

    # --- data ------------------------------------------------------------

    def set_data(self, stats, summary=None):
        """`stats` is dashboard_data.compute_dashboard_stats()'s (or
        merge_recovered_into_stats()'s) dict, or None when no evidence is
        open. `summary` is dashboard_data.case_summary's rows for the Case
        summary card."""
        self._stats = stats
        self._summary = summary
        if stats is None:
            self._render_empty()
            return

        recovered = stats.get("recovered_count", 0)
        run = stats.get("recovery_run", bool(recovered))
        self.header.set_subtitle(record_counts.split_text(
            record_counts.RecordCounts(
                stats["total_records"] - recovered,
                recovered if run else None)) + ".")

        self.chip_records.set_value(format(stats["total_records"] - recovered, ","))
        self.chip_recovered.set_value(
            format(recovered, ",") if run else "—",
            tooltip=("Records the recovery scan produced (structured and "
                     "string carves, and deleted-record stubs)." if run else
                     "Recovery has not run for this exhibit."))
        self.chip_recovered.set_accent("carved" if recovered else "muted")
        self.chip_tables.set_value(format(stats["table_count"], ","))
        self.chip_containers.set_value(format(stats["container_count"], ","))
        self.chip_inprivate.set_accent(
            "error" if stats["inprivate_count"] else "muted")
        inprivate_tip = ("Live records only -- a recovered (carved) record "
                         "does not preserve the InPrivate flag.")
        if not stats["inprivate_count"]:
            # The figure an examiner most easily over-reads: survivors are
            # the exception, not the record of every private session.
            inprivate_tip += (" InPrivate entries are normally removed when "
                              "the private session ends, and only Internet "
                              "Explorer and legacy Edge write them here, so 0 "
                              "does not show that no private browsing took "
                              "place.")
        self.chip_inprivate.set_value(
            format(stats["inprivate_count"], ","), tooltip=inprivate_tip)
        self.chip_cache_size.set_value(
            format_size(stats["total_file_size"]),
            # A different figure from Database Info's "Size": this chip sums
            # FileSize across cached records, the response bodies stored as
            # separate files on disk, while Size is the WebCacheV01.dat file,
            # which indexes those bodies but does not contain them.
            tooltip="Total size of CACHED RESPONSE BODIES -- files stored "
                    "on disk outside the .dat, not the database file "
                    "itself (see Database Info's own Size row for that). "
                    "Live records only -- a recovered (carved) record "
                    "does not carry a file size.")

        self._render_container_types(stats)
        self._render_top_domains(stats)
        self._render_case_summary(summary or database_info_rows(stats))

    def _drill_chip(self, key):
        self.drillRequested.emit(_CHIP_DRILL_TARGETS[key], {})

    # --- Container Types card -------------------------------------------

    def _render_container_types(self, stats):
        _clear_layout(self.card_container_types.body)
        self._container_type_rows = []
        # Largest-remainder apportionment (dashboard_data.
        # apportioned_percentages), so the percentages sum to 100.
        # most_common() is count-descending and the apportionment keeps
        # that order, so pct lines up with each (name, count) pair below.
        items = stats["container_types"].most_common()
        # "Not determinable" is a fact about the carve, not a container
        # type: it is listed after every real type, in muted text.
        items = ([(n, c) for n, c in items if n != CONTAINER_NOT_DETERMINABLE]
                 + [(n, c) for n, c in items if n == CONTAINER_NOT_DETERMINABLE])
        self._container_type_names = [n for n, _c in items]
        percentages = apportioned_percentages([count for _n, count in items])
        for (name, count), pct in zip(items, percentages):
            row = self._build_container_type_row(name, count, pct)
            self.card_container_types.body.addWidget(row)
            self._container_type_rows.append(row)
        if not self._container_type_rows:
            self.card_container_types.body.addWidget(
                _muted_line("No container types recorded in this exhibit."))
        self.card_container_types.body.addStretch(1)

    def _build_container_type_row(self, name, count, pct):
        row = ClickableRow()
        # Exposed for tests, and for anything else that wants to know
        # which fact a given row is -- the same "the row IS the data"
        # convenience RecordsTable's own row_at() already offers.
        row.container_type = name
        row.count = count
        row.pct = pct
        lay = QHBoxLayout(row)
        lay.setContentsMargins(3, 4, 3, 4)
        lay.setSpacing(8)

        role = _container_type_color(name)
        dot = QFrame()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            "background: %s; border-radius: 2px;" % theme.color(role).name())
        lay.addWidget(dot, 0, Qt.AlignVCenter)

        # DECORATIVE, all three: this whole row is a single drill-through
        # click target (row.clicked below), the same "nav rows, chips"
        # exception copyable.py documents -- a mouse-selectable child
        # label would swallow the click into a text selection instead of
        # emitting it. Nothing here is lost: the same name/count/percent
        # is reproduced, unabridged and selectable, once the click lands
        # on Containers (see the module docstring's "Headline figures
        # only; every number here is reproduced in the view it came from").
        # WrappingText, never elided. Transparent to the mouse: the
        # whole row is one drill-through click target, and the row's own
        # right-click Copy carries the same text.
        name_label = WrappingText(name)
        if name == CONTAINER_NOT_DETERMINABLE:
            name_label.setStyleSheet(
                "QTextEdit { background: transparent; border: none; "
                "color: %s; }" % theme.PALETTES[theme.current_name()]["muted"])
        name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        name_label.viewport().setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(name_label, 1)

        count_label = QLabel(format(count, ","))
        count_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(count_label)  # text shown exactly, never as markup
        count_label.setFixedWidth(55)
        count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        count_label.setStyleSheet(
            "background: transparent; font-weight: 600; color: %s;"
            % theme.color(role).name())
        lay.addWidget(count_label)

        pct_label = QLabel("%d%%" % pct)
        pct_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(pct_label)  # text shown exactly, never as markup
        pct_label.setFixedWidth(38)
        pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pct_label.setStyleSheet(
            "background: transparent; font-size: 11px; color: %s;"
            % theme.color("muted2").name())
        lay.addWidget(pct_label)

        # The right-click Copy the name/count/pct labels above cannot
        # offer themselves (DECORATIVE, so left-click keeps drilling
        # through) -- see ClickableRow.build_context_menu(). "Copy" takes
        # the SAME formatted count the label displays, not the raw int.
        row.copy_figure_text = format(count, ",")
        row.copy_row_text = "%s: %s (%d%%)" % (name, format(count, ","), pct)

        row.clicked.connect(
            lambda n=name, c=count: self.drillRequested.emit(
                "containers", {"ContainerType": n, "Count": c}))
        return row

    # --- Top 10 Domains card ---------------------------------------------

    def _render_top_domains(self, stats):
        _clear_layout(self.card_top_domains.body)
        self._domain_rows = []
        self.all_domains_row = None
        top = stats["top_domains"].most_common(10)
        max_count = top[0][1] if top else 1
        recovered = stats.get("top_domains_recovered") or {}
        for rank, (domain, count) in enumerate(top, 1):
            carved = recovered.get(domain, 0)
            row = self._build_domain_row(rank, domain, count, max_count)
            # the aggregate origin word, from the same
            # live and recovered members the Domains view counts.
            row.origin_word = provenance.aggregate_origin(
                count - carved, carved)
            origin = QLabel(row.origin_word)
            origin.setProperty(copyable.DECORATIVE, True)
            copyable.plain(origin)
            origin.setToolTip(
                "%s live, %s recovered record(s) for this domain."
                % (format(count - carved, ","), format(carved, ",")))
            origin.setStyleSheet(
                "background: transparent; font-size: 10.5px; color: %s;"
                % theme.color("carved" if carved else "muted").name())
            row.layout().addWidget(origin)
            self.card_top_domains.body.addWidget(row)
            self._domain_rows.append(row)
        if not self._domain_rows:
            self.card_top_domains.body.addWidget(
                _muted_line("No domains recorded in this exhibit."))
        # A top ten never reads as the whole list: the total, and every
        # domain one click away.
        self.all_domains_row = None
        total = len(stats["top_domains"])
        if total > len(top):
            more = ClickableRow()
            text = "View all %s domains" % format(total, ",")
            more.copy_row_text = text
            lay = QHBoxLayout(more)
            lay.setContentsMargins(3, 6, 3, 3)
            label = QLabel(text + " →")
            label.setProperty(copyable.DECORATIVE, True)
            copyable.plain(label)
            label.setStyleSheet("background: transparent; color: %s;"
                                % theme.color("primary").name())
            lay.addWidget(label)
            lay.addStretch(1)
            more.setToolTip("Every domain in this exhibit, on the Domains screen")
            more.clicked.connect(
                lambda: self.drillRequested.emit("domains", {}))
            self.card_top_domains.body.addWidget(more)
            self.all_domains_row = more
        self.card_top_domains.body.addStretch(1)

    def _build_domain_row(self, rank, domain, count, max_count):
        row = ClickableRow()
        row.domain = domain
        row.count = count
        lay = QHBoxLayout(row)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(8)

        # DECORATIVE throughout this row -- same reason as
        # _build_container_type_row above: a single drill-through click
        # target, reproduced unabridged in Domains once clicked.
        rank_label = QLabel(str(rank))
        rank_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(rank_label)  # text shown exactly, never as markup
        rank_label.setFixedWidth(16)
        rank_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rank_label.setStyleSheet(
            "background: transparent; font-size: 10px; color: %s;"
            % theme.color("muted2").name())
        lay.addWidget(rank_label)

        # WrappingText, never elided. Transparent to the mouse: the
        # whole row is one drill-through click target, and the row's own
        # right-click Copy carries the same text.
        name_label = WrappingText(domain)
        name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        name_label.viewport().setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(name_label, 1)

        # A square-root scale (see the module docstring). The exact count
        # is printed beside every bar, so the bar only has to make values
        # comparable.
        bar = QProgressBar()
        bar.setRange(0, 1000)
        frac = (count / max_count) ** 0.5 if max_count else 0.0
        bar.setValue(int(frac * 1000))
        bar.setTextVisible(False)
        bar.setFixedWidth(90)
        bar.setToolTip(
            "%s record(s). Bars use a square-root scale so the smaller "
            "domains stay distinguishable; the number beside each bar is "
            "the exact count." % format(count, ","))
        bar.setStyleSheet(
            "QProgressBar::chunk { background: %s; }"
            % theme.color("secondary").name())
        lay.addWidget(bar)

        count_label = QLabel(format(count, ","))
        count_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(count_label)  # text shown exactly, never as markup
        count_label.setFixedWidth(50)
        count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        count_label.setStyleSheet(
            "background: transparent; font-weight: 600; color: %s;"
            % theme.color("primary_text").name())
        lay.addWidget(count_label)

        # As in _build_container_type_row.
        row.copy_figure_text = format(count, ",")
        row.copy_row_text = "%s: %s" % (domain, format(count, ","))

        row.clicked.connect(
            lambda d=domain, c=count: self.drillRequested.emit(
                "domains", {"Domain": d, "Count": c}))
        return row

    # --- Case summary card ------------------------------------------------

    def _render_case_summary(self, rows):
        _clear_layout(self.card_case_summary.body)
        self._db_info_rows = []
        p = theme.PALETTES[theme.current_name()]
        for label, value in rows:
            text = format_size(value) if label == "Size" else (
                format(value, ",") if isinstance(value, int) else str(value))
            # A fact is a small muted label over its value, not two columns:
            # "Activity (local, UTC+05:30)" and a 64-character hash both
            # need the card's whole width.
            box = QVBoxLayout()
            box.setSpacing(0)
            label_widget = copyable.selectable(QLabel(label))
            label_widget.setWordWrap(True)
            label_widget.setStyleSheet(
                "background: transparent; font-size: 11px; color: %s;"
                % p["muted"])
            # Selectable and copyable, never elided, only wrapped -- and
            # never opened ("Copy, never Open"): WrappingText breaks a hash
            # or a path anywhere, so nothing an examiner copies is partial.
            value_widget = WrappingText(text)
            if label == "SHA-256":
                value_widget.setStyleSheet(
                    "QTextEdit { background: transparent; border: none; "
                    "font-family: Consolas, 'Courier New', monospace; }")
            if label == "Size":
                # The other half of chip_cache_size's own tooltip above --
                # this is the .dat file on disk, not the cached response
                # bodies the Cache Size chip sums.
                size_tip = ("The WebCacheV01.dat database file itself, on "
                            "disk -- not the cached response bodies it "
                            "indexes. See the Cache Size chip above for "
                            "that figure.")
                label_widget.setToolTip(size_tip)
                value_widget.setToolTip(size_tip)
            box.addWidget(label_widget)
            box.addWidget(value_widget)
            self.card_case_summary.body.addLayout(box)
            self._db_info_rows.append((label_widget, value_widget))
        self.card_case_summary.body.addStretch(1)

    # --- the no-evidence state ---------------------------------------------

    def _render_empty(self):
        """first_run.py's own voice ("No evidence open"), not a table
        rendered with nothing in it -- see the module docstring."""
        self.header.set_subtitle("No evidence loaded yet.")
        for chip in (self.chip_records, self.chip_recovered, self.chip_tables,
                    self.chip_containers, self.chip_inprivate,
                    self.chip_cache_size):
            chip.set_value("—", tooltip="Open evidence to see this figure.")
        for card, text in (
            (self.card_container_types,
             "Open evidence to see the container breakdown."),
            (self.card_top_domains,
             "Open evidence to see the busiest domains."),
            (self.card_case_summary,
             "Open evidence to see the case summary."),
        ):
            _clear_layout(card.body)
            card.body.addWidget(_muted_line(text))
            card.body.addStretch(1)
        self._container_type_rows = []
        self._domain_rows = []
        self._db_info_rows = []
