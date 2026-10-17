"""History: pages and resources visited.

At open, the rows are live records (evidence_loader.history_rows_from_
parser), and the count line states that recovered records are not yet
included. After Evidence > Recover deleted records, recovered History
records (recovery_loader.carved_history_rows) are merged in, labelled
"Carved (deleted/unflushed)", and the count line gives the live and
recovered split.

"Last visit (LOCAL)" is shown exactly as decoded (SPS property 24, on the
machine's local clock); no time zone is added to it.

The record-table behaviour comes from records_view.RecordsView; this view
declares its columns, quick-filter chips and header text.
"""
from ..widgets.column_spec import Column
from ..widgets.record_filter import Condition
from .record_chips import (copies_hidden_note, hide_copies_chip,
                           one_row_per_visit_chip, twins_hidden_note)
from .records_view import QuickFilter, RecordSet, RecordsView

#: What only the MSHist side of a linked pair says in "Same visit as".
SAME_VISIT_MSHIST_MARK = "(this is its MSHist"


def _history_subtitle(count):
    return ("%s history record%s. Visit counts and the local-clock "
           "last-visit time are decoded from the property store."
           % (format(count, ","), "" if count == 1 else "s"))


class HistoryView(RecordsView):
    def __init__(self, parent=None):
        # Quick filters use the same filter machinery as the column
        # funnels, so the count line always states what is in force.
        quick_filters = [
            QuickFilter("chip_inprivate", "InPrivate only", "error",
                       "IsInPrivate", values={True}),
            QuickFilter("chip_search_terms", "Has search terms", "primary",
                       "SearchTerms", condition=Condition("is not blank"),
                       none_note="Chromium-based Edge (v79+) does not use "
                                 "this database, so a search made in it "
                                 "cannot appear here."),
            QuickFilter("chip_local_files", "Local files only", "primary",
                       "IsLocalFile", values={True}),
            hide_copies_chip(),
            # An MSHist record and its History twin are one visit in two
            # containers. Off by default; hides only the MSHist half of a
            # linked pair.
            one_row_per_visit_chip(),
        ]
        # What an examiner reads first: when, how often, where. The two
        # links to other records of the same visit follow the address;
        # they are blank on most rows, so they stay narrow and wrap.
        columns = [
            Column("AccessedUtc", "Last visit (UTC)", 165, kind="time",
                  field="AccessedUtc"),
            Column("AccessedLocal", "Last visit (LOCAL)", 165,
                  kind="time_local", field="AccessedLocal"),
            Column("VisitCount", "Visits", 70, kind="num", field="VisitCount"),
            Column("CleanUrl", "Address", 460, kind="url", field="CleanUrl"),
            # The other record of the same visit; blank when there is none.
            Column("SameVisit", "Same visit as", 220, kind="text"),
            # Repeated carves of one record; blank on a live row and on a
            # unique carve.
            Column("Copies", "Copies", 100, kind="text"),
            Column("Domain", "Domain", 170, kind="domain",
                  on_click=lambda row: self.drillRequested.emit("domains", row)),
            Column("Title", "Title", 240, kind="text"),
            Column("IsInPrivate", "InPrivate", 85, kind="flag"),
            # Origin is graded CARV (evidence_model): a row's live or
            # recovered status is the result of recovery.
            Column("Origin", "Origin detail", 170, kind="text", field="Origin"),
            # Which container holds the record: History, or an MSHist
            # daily/weekly container.
            Column("Container", "Container", 200, kind="text"),
            Column("Source", "Carved from", 150, kind="text", field="Source",
                   blank_text="(live record, not carved)"),
            # Where a recovered row came from; optional, blank on a live row.
            Column("Offset", "Offset", 100, kind="offset", field="Offset",
                   optional=True),
            Column("Page", "Page", 70, kind="num", field="Page",
                   optional=True),
            Column("Method", "Method", 190, kind="text", field="Method",
                   optional=True),
        ]
        super().__init__(
            record_sets=[RecordSet(
                "history", "History", columns, subtitle=_history_subtitle,
                empty_text=("No History records in this exhibit — the "
                            "History container held no live entries when "
                            "the database was parsed."),
                default_sort=("AccessedUtc", True))],
            header_icon="clock", header_title="History",
            quick_filters=quick_filters, parent=parent)

    def _update_count(self):
        super()._update_count()
        # Hidden rows are left out of Export view; the full case exports
        # keep every row. The count line says so.
        model = self.table.model()
        if model is None:
            return
        if self.chip_hide_copies.isChecked():
            self.count_label.setText(
                self.count_label.text() + copies_hidden_note(model))
        if self.chip_one_row_per_visit.isChecked():
            # A twin filtered out leaves its MSHist partner on screen.
            self.count_label.setText(
                self.count_label.text() + twins_hidden_note(model))
