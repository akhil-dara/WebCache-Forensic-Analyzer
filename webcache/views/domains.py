"""Domains: one row per host, from live records and, after a recovery
scan, recovered ones.

Rows come from domain_loader.domain_rows(). A host can exist only in
recovered data; "Deleted only" (OnlyCarved) says so explicitly as Yes or
No on every row. Before a recovery scan the count line states that no scan
has run, so the zero counts are not read as "nothing deleted".

Selecting a domain lists, in the pane below, every record counted for it,
live and recovered, from every container; the pane lists exactly the
records the Records cell counts. Every domain drill-down in the
application (History's Domain cell, the Dashboard, Findings' Beaconing)
lands here through MainWindow._drill_to_domain.
"""
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QSplitter

from ..shell.timeline_loader import member_record_rows
from ..widgets.column_spec import Column
from ..widgets.sub_table import SubTable, rows_height
from .records_view import RecordSet, RecordsView, member_record_columns


def _domains_subtitle(count):
    return ("%s domain%s. Grouped by host; one host can serve many "
           "unrelated services."
           % (format(count, ","), "" if count == 1 else "s"))


class DomainsView(RecordsView):
    #: A row is a domain; its records are the members.
    COUNT_NOUN = "domains"

    def __init__(self, parent=None):
        columns = [
            Column("Domain", "Domain", 280, kind="url", field="Domain",
                  on_click=lambda row: self.show_domain(row.get("Domain"))),
            Column("Records", "Records", 80, kind="num"),
            # The browser's own visit counter, each address once; not the
            # record count, which also holds cache requests.
            Column("Visits", "Visits (property store)", 110, kind="num",
                  field="DomainVisits"),
            Column("Carved", "From deleted", 100, kind="carved"),
            Column("OnlyCarved", "Deleted only", 120, kind="only_carved"),
            Column("FileSize", "Cached size", 100, kind="size", field="FileSize"),
            Column("FirstSeen", "First seen (UTC)", 165, kind="time"),
            Column("LastSeen", "Last seen (UTC)", 165, kind="time"),
            Column("ContainerType", "Container types", 170, kind="types",
                  field="ContainerType", multi=True),
            Column("AccessCount", "Mean cache touches", 80, kind="num",
                  field="AccessCount"),
            Column("IsInPrivate", "InPrivate", 80, kind="flag",
                  field="IsInPrivate"),
        ]
        super().__init__(
            record_sets=[RecordSet(
                "domains", "Domains", columns, subtitle=_domains_subtitle,
                empty_text=("No domains in this exhibit — no record with "
                            "a network URL was found when the database "
                            "was parsed."))],
            header_icon="database", header_title="Domains",
            parent=parent)

    PANE_PROMPT = ("Select a domain above. Every record counted for it -- "
                   "live and recovered, from every container -- appears here.")
    PANE_NOTE = ("Each row is one record; carved rows came from deleted or "
                 "unflushed data. Open a row for its fields, or right-click "
                 "for its raw database row.")
    #: The pane's share of the splitter with nothing selected (one line)
    #: and with a domain selected.
    PANE_SHARE_IDLE = 0.15
    PANE_SHARE_ACTIVE = 0.65
    PANE_EMPTY = "No record of this domain matches the filter in this pane."

    _splitter = None
    pane = None
    _current_row = None
    _pane_share = None

    def _table_area(self):
        if self._splitter is None:
            self.MEMBER_COLUMNS = member_record_columns(self)
            self.annotate_basis(self.MEMBER_COLUMNS)
            self.pane = SubTable()
            self.pane.clear(self.PANE_PROMPT)
            splitter = QSplitter(Qt.Vertical)
            splitter.addWidget(self.table)
            splitter.addWidget(self.pane)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 2)
            splitter.setChildrenCollapsible(True)
            # The grid keeps at least four rows.
            self.table.setMinimumHeight(rows_height(self.table, 4))
            self._splitter = splitter
            self._set_pane_share(self.PANE_SHARE_IDLE)
        return self._splitter

    def _set_pane_share(self, share):
        """Give the pane `share` of the splitter's height, only when the
        selection changes between none and some, so a size the examiner
        dragged is kept."""
        splitter = self._splitter
        if splitter is None or self._pane_share == share:
            return
        self._pane_share = share
        total = max(splitter.height(), 800)
        splitter.setSizes([int(total * (1.0 - share)), int(total * share)])

    def _render_active_segment(self):
        # The model is rebuilt on every set_records (a recovery merge
        # included); the selected domain is kept if it still exists.
        # Filters are cleared only by show_domain, for a drill-down.
        kept = self.selected_domain()
        super()._render_active_segment()
        selection = self.table.selectionModel()
        if selection is not None:
            selection.currentRowChanged.connect(self._show_selected)
        if not (kept and self._select_row_of(kept)):
            self._show_row(None)

    def _select_row_of(self, domain):
        model = self.table.model()
        if model is None:
            return False
        for i in range(model.rowCount()):
            if model.row_at(i).get("Domain") == domain:
                self.table.selectionModel().setCurrentIndex(
                    model.index(i, 0),
                    QItemSelectionModel.ClearAndSelect
                    | QItemSelectionModel.Rows)
                self.table.scrollTo(model.index(i, 0))
                self._show_row(model.row_at(i))
                return True
        return False

    def _show_selected(self, current, _previous=None):
        model = self.table.model()
        if model is None or current is None or not current.isValid():
            self._show_row(None)
            return
        self._show_row(model.row_at(current.row()))

    def _show_row(self, row):
        self._current_row = row or None
        if not row:
            self.pane.clear(self.PANE_PROMPT)
            self._set_pane_share(self.PANE_SHARE_IDLE)
            return
        members = row.get("_members") or ()
        # The last row["Carved"] members came from the carved list.
        n_carved = row.get("Carved") or 0
        carved_ids = {id(m) for m in members[len(members) - n_carved:]}
        rows = member_record_rows(members, carved_ids)
        self.grade_mixed(self.MEMBER_COLUMNS, rows)
        self.pane.set_rows(
            self.MEMBER_COLUMNS, rows,
            "%s record%s for %s. %s" % (format(len(rows), ","),
                                        "" if len(rows) == 1 else "s",
                                        row.get("Domain", ""), self.PANE_NOTE),
            "", self.PANE_EMPTY, default_sort=("KeyTimeUtc", True))
        self._set_pane_share(self.PANE_SHARE_ACTIVE)

    def show_domain(self, domain):
        """Select `domain`'s row and list its records. Filters that would
        hide it are cleared first."""
        model = self.table.model()
        if model is None or not domain:
            return False
        for attempt in (0, 1):
            if self._select_row_of(domain):
                return True
            if attempt == 0:
                self.clear_all_filters()
        return False

    def selected_domain(self):
        return (self._current_row or {}).get("Domain", "")

    def refresh_theme(self):
        super().refresh_theme()
        self.pane.refresh_theme()
