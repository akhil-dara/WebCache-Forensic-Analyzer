"""The shell: nav rail, view stack, menus, status bar.

Views live in a QStackedWidget, built when first opened and then kept. A
hidden widget costs nothing in Qt, so switching is a stack index change.

Sixteen destinations, grouped in the order an investigation proceeds.
"""
import html
import json
import os
import pathlib
import re

from PySide6.QtCore import (QElapsedTimer, QEvent, QItemSelectionModel, Qt,
                            QTimer)
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMainWindow,
                               QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QSizePolicy, QStackedWidget,
                               QStatusBar, QTextEdit, QVBoxLayout, QWidget)

from .. import paths  # noqa: F401  (kept so settings monkeypatching works)
from .. import provenance
from ..widgets.records_table import RecordsTable
from ..engine import forensic_engine, local_clock
from ..views.browser import TableBrowserView
from ..views.containers import ContainersView
from ..views.cookies import CookiesView
from ..views.dashboard import DashboardView
from ..views.domains import DomainsView
from ..views.file_access import FileAccessView
from ..views.headers import HeadersView
from ..views.history import HistoryView
from ..views.indicators import IndicatorsView
from ..views.integrity import IntegrityView
from ..views.iocs import FindingsView
from ..views.location import LocationView
from ..views.export import ExportView
from ..views.recovery import NOT_SCANNED_NOTE, RecoveryView
from ..views.search import SearchView
from ..views.tagged import TaggedView
from ..views.timeline import TimelineView
from ..widgets import copyable
from ..widgets.content_header import CaveatLine, ViewHeader
from ..widgets.records_table import RecordsTable
from . import case_store, dashboard_data, export_folder, export_formats
from . import case_notes, case_notes_bar, export_target, tagged_loader
from . import detail_fields, glyphs, help_texts, settings, theme
from . import nav_history, row_locate_runner, row_locator
from . import html_package, package_snapshot
from .open_evidence import OpenEvidenceDialog
from . import location_loader, record_counts, record_kinds, timeline_loader
from . import derived
from ..widgets import time_format
from .time_format_dialog import EXAMPLE as TIME_FORMAT_EXAMPLE
from .time_format_dialog import TimeFormatDialog
from .domain_loader import domain_rows
from .export_dialogs import SafeFolderDialog
from .export_result_bar import ExportResultBar
from ..widgets.current_page_stack import CurrentPageStack
from .export_runner import ExportJob, ExportRunner
from .evidence_loader import (EvidenceLoader, cert_rows_from_parser,
                              container_rows_from_parser,
                              cookie_rows_from_parser,
                              downloads_rows_from_parser,
                              file_access_rows_from_parser,
                              hsts_rows_from_parser)
from .first_run import FirstRunView
from .headers_loader import (carved_header_rows, header_rows_from_parser,
                             pair_export_rows)
from .headers_loader import total_pairs as headers_total_pairs
from .indicator_loader import indicator_rows
from .record_kinds import K_TOMBSTONE
from .iocs_loader import (beaconing_rows, deceptive_hostname_rows,
                          entryid_gap_rows, ioc_hit_rows, redirect_hop_rows,
                          split_watchlist, time_void_rows_and_note)
from . import blob_source
from .record_detail import BlobViewerDialog, RecordDetailDialog
from .table_row_detail import TableRowDialog
from .recovery_loader import (RecoveryLoader, carved_downloads_rows,
                              carved_file_access_rows, carved_history_rows,
                              deleted_records_rows, file_access_note,
                              file_text_only_count, stub_artifact)
from . import drop_target
from .drop_overlay import OPEN_PROMISE, DropOverlay
from . import search_loader
from .search_runner import SearchRunner
from .sidebar import NAV_ICONS, Sidebar
from .table_browser_loader import grouped_tables as browser_grouped_tables
from .timeline_builder import TimelineBuilder

#: The count-line note while the loaded rows are live records only (no
#: recovery scan has run for this exhibit). A page visited and then deleted
#: was still visited, so the note says the set is live-only and how to
#: recover the rest (see _start_recovery).
LIVE_ONLY_NOTE = ("live records only; deleted records not yet recovered — "
                  "run Evidence ▸ Recover deleted records to scan for them")

#: What every live-only note says while a recovery scan is running, rather
#: than "not yet recovered".
RECOVERY_RUNNING_NOTE = ("live records only; recovery running — deleted "
                         "records are added here when it finishes")

_PAGES_DONE = re.compile(r"([\d,]+ of [\d,]+) database pages")

#: The answer to any navigation before evidence is open (see _nav_changed).
#: One constant, so every route to go_to() (the Export menu's Ctrl+Shift+E
#: too) states the same fact.
_LOAD_FIRST_MESSAGE = ("Load a database first — File ▸ Open Evidence… or "
                       "the Open Database button.")

#: Domains' note before a recovery scan: every column is complete at open
#: except the two carved-derived ones (From deleted, Deleted only), which
#: read 0/No until a scan has run. The note says so, so those values are
#: not read as "no deleted records exist" (see domains.py).
DOMAIN_CARVED_NOT_SCANNED_NOTE = (
    "“From deleted” and “Deleted only” are not yet "
    "meaningful — no recovery scan has run for this exhibit; run "
    "Evidence ▸ Recover deleted records to populate them")

#: Timeline's own equivalent, for its "From deleted" column. ALIASED from
#: the loader that builds the count line rather than re-typed here: two
#: spellings of the same claim would be two claims, and the loader is
#: where the sentence has to be reachable from (grain_note assembles it).
TIMELINE_CARVED_NOT_SCANNED_NOTE = timeline_loader.CARVED_NOT_SCANNED_NOTE

#: The same for Location's carved count: a position is often found only in
#: a deleted or unflushed URL, so a zero before any scan is stated as "not
#: yet scanned". An alias, so the wording is defined once.
LOCATION_CARVED_NOT_SCANNED_NOTE = location_loader.CARVED_NOT_SCANNED_NOTE

#: Indicators' equivalent: until a recovery scan has run, url_intel.py
#: scans only the URLs the live database holds, so an indicator in a
#: deleted URL is not yet visible.
INDICATOR_NOT_SCANNED_NOTE = (
    "scanned from live records only; deleted records not yet recovered — "
    "run Evidence ▸ Recover deleted records to scan their URLs too")

#: Findings' equivalent, for the five segments that use carved data (all
#: except Beaconing; forensic_engine.detect_beaconing() takes no
#: extra_entries, see record_kinds.K_BEACON), so a zero before a scan is
#: not read as "nothing to find".
IOCS_NOT_SCANNED_NOTE = (
    "live records only; deleted records not yet recovered — run "
    "Evidence ▸ Recover deleted records to include them in this heuristic")

#: Beaconing's own note, PERMANENT rather than scan-state-dependent -- see
#: IOCS_NOT_SCANNED_NOTE above for why this one segment never resolves to
#: the "recovered" half of that pair.
IOCS_BEACON_NOTE = (
    "computed from live records only — this heuristic does not "
    "incorporate carved records, even after a recovery scan")

#: The corpus banner above the switcher (FindingsView._header_extra's own
#: Card) before any recovery scan has run for this exhibit: "Live tables
#: only... on this evidence that is the difference between most of the
#: hits and few of them."
IOCS_CORPUS_LIVE_ONLY = (
    "Live tables only. Deleted and unflushed records are not included; "
    "run Evidence ▸ Recover deleted records to add them, as they often "
    "hold most of the hits.")


def _stub_suffix(stubs):
    """'; 40 deleted-record stubs (key only ...) not counted here', or
    nothing -- so a 'recovered' figure that leaves the stubs out says so."""
    text = record_counts.stub_clause(stubs)
    return "; " + text if text else ""


def _iocs_scan_note(carved_count):
    """The count-line note once a scan has run, saying the segments now
    include the carved set (the counterpart of IOCS_NOT_SCANNED_NOTE)."""
    return "%s recovered record(s) also included" % format(carved_count, ",")


def _iocs_corpus_recovered(carved_count, stubs=0):
    return ("Includes %s recovered record(s) from the recovery scan%s. "
           "Beaconing uses live records only."
           % (format(carved_count, ","), _stub_suffix(stubs)))

#: key, label, one-line caveat -- what this view does NOT prove.
NAV_SECTIONS = [
    ("", [
        ("dashboard", "Dashboard",
         "Headline figures only; every number here is reproduced in the view it came from."),
    ]),
    ("USER ACTIVITY", [
        ("history", "History",
         "A record of a page being loaded, not proof a person read it."),
        ("downloads", "File Access",
         "Shows files opened through the browser, not every file opened on the machine."),
        ("search", "Search",
         "Searches what the database stored, not what was typed and abandoned."),
    ]),
    ("ANALYSIS", [
        ("timeline", "Timeline",
         "Gaps mean no cached activity, which is not the same as no activity."),
        ("domains", "Domains",
         "Grouped by host; one host can serve many unrelated services."),
        ("location", "Location",
         "Positions the device reported to servers, which it can be told to fake."),
        ("indicators", "Indicators",
         "Values carried inside URLs; presence is not intent."),
        ("iocs", "Findings",
         "Heuristics that raise questions, never conclusions."),
    ]),
    ("ARTIFACTS", [
        ("cookies", "Cookies & HSTS",
         "Cookies, HSTS entries and cached certificates each prove less than "
         "a page view; each segment states what it shows."),
        ("headers", "HTTP Headers",
         "Headers as stored by the cache, which may be a partial record."),
        ("containers", "Containers",
         "Container metadata as the database records it, including stale entries."),
    ]),
    ("RECOVERY", [
        ("recovery", "Deleted Records",
         "Carved from unallocated pages or the transaction log. A "
         "Container of “Not determinable” means the carve did not "
         "preserve which container the record came from."),
    ]),
    ("DATABASE", [
        ("browser", "Table Browser",
         "Raw ESE tables exactly as stored, with no interpretation applied."),
    ]),
    ("CASE", [
        ("tagged", "Tagged",
         "Your own tags and comments on records, kept in the case file "
         "beside the application, never in the evidence."),
        ("integrity", "Integrity",
         "Hashes and the parse log; a clean parse is not a complete database."),
        ("export", "Export & Report",
         "Exports carry the filters in force; an export is a view, not the whole evidence."),
    ]),
]

#: Nav destinations that show no number: for these, no single figure means
#: what a row count means elsewhere on the rail.
#:
#: "search": a hit count belongs to a keyword, not to the exhibit; it is
#: stated in the count line and on the "Export view (N)" button.
#: "export": the Export & Report page is not a record set.
#: "integrity": source hashes and a parsing decision log, not a record set.
#:
#: Sidebar.set_no_count(key) gives each a permanent dash
#: (NavRow.set_no_count) that remains after Sidebar.set_loaded(True), so it
#: is never read as zero. Every record-set view shows a real count instead:
#: Findings shows the total of its six segments ("findings across six
#: heuristics (not records)"), HTTP Headers the records that carry headers,
#: Timeline the records with a usable timestamp (not its row count, which
#: changes with the grain), and Location the position fixes (the places are
#: stated on the switcher button).
_NO_COUNT_KEYS = frozenset(
    {"search", "export", "integrity"})


class ExplainDialog(QDialog):
    """"Explain this value", with a Copy button, so the explanation can go
    into a report without retyping a byte offset.

    A QDialog rather than QMessageBox.addButton(): a QMessageBox closes on
    any button click whatever its role, so Copy would also dismiss the
    explanation. QDialogButtonBox wires accepted/rejected only for buttons
    in an Accept/Reject role; Copy is an ActionRole button that does not
    close the dialog, and Close ends it. Tab, Enter and Escape work as in
    any QDialog.
    """

    def __init__(self, parent, text, table=False):
        super().__init__(parent)
        self.setWindowTitle("Explain this value")
        self._text = text

        if table:
            body = self._two_column_body(text)
        else:
            body = QLabel(text)
            body.setWordWrap(True)
            copyable.selectable(body)

        buttons = QDialogButtonBox()
        self.copy_button = buttons.addButton(
            "Copy", QDialogButtonBox.ActionRole)
        self.copy_button.clicked.connect(self._copy)
        close_button = buttons.addButton(
            "Close", QDialogButtonBox.AcceptRole)
        close_button.setDefault(True)
        buttons.accepted.connect(self.accept)

        # A readable measure: at its natural size a two-sentence answer
        # wrapped into a 270 px column eight lines tall.
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.addWidget(body)
        root.addWidget(buttons)

    @staticmethod
    def _two_column_body(text):
        """keys<TAB>description lines as a real grid: keycap-style keys on
        the left, descriptions all starting at one x on the right, every
        cell selectable. The copied text stays the tab-separated lines."""
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        keycap = ("QLabel { font-family: 'Cascadia Mono', Consolas, "
                  "monospace; background: %s; border: 1px solid %s; "
                  "border-radius: 4px; padding: 2px 7px; }"
                  % (theme.color("alt_base").name(),
                     theme.color("border").name()))
        for row, line in enumerate(text.split("\n")):
            keys, _sep, desc = line.partition("\t")
            key_label = QLabel(keys)
            key_label.setStyleSheet(keycap)
            desc_label = QLabel(desc)
            for label in (key_label, desc_label):
                copyable.selectable(label)
            grid.addWidget(key_label, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(desc_label, row, 1, Qt.AlignLeft | Qt.AlignVCenter)
        return body

    def _copy(self):
        """The full explanation as plain text: column name, value, and
        provenance.describe_origin()'s line, as on screen, so the report
        matches what the examiner read."""
        QGuiApplication.clipboard().setText(self._text)


class _ElidingStatusLabel(QLabel):
    """The status bar's left-hand caveat/status message.

    Used instead of QStatusBar.showMessage(), which draws its text without
    eliding or clearance from the permanent widgets, so a long caveat could
    run into the record counter. The caveat's wording is kept; this widget
    elides it on display, and the full sentence is always in its tooltip.

    Re-elided on every resize, since the room available changes with the
    window and with the permanent widgets (the database summary grows with
    its numbers).
    """

    #: Kept clear of whatever sits immediately to the right (the permanent
    #: counters, or the status bar's edge), so elided text never touches
    #: it.
    _RIGHT_MARGIN_PX = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        copyable.selectable(self)
        self._full_text = ""
        # Ignored, not Preferred: this label must be free to shrink below
        # its text's own natural width -- that is the entire point of
        # eliding it -- rather than have the box layout grow the status
        # bar (or squeeze a permanent widget) to fit the unelided text.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def set_full_text(self, text):
        self._full_text = text or ""
        self.setToolTip(copyable.literal_tooltip(self._full_text))
        self._reelide()

    def full_text(self):
        return self._full_text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reelide()

    def _reelide(self):
        available = max(0, self.width() - self._RIGHT_MARGIN_PX)
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._full_text, Qt.ElideRight, available))


def _suffix_for_filter(path, chosen_filter):
    """`path` with the suffix the chosen save filter names.

    The chooser suggests "....csv"; an examiner who picks
    "Excel workbook (*.xlsx)" and keeps that name meant a workbook, and
    the format is decided from the suffix downstream. A filter that names
    no single suffix ("All files (*)"), or a path that already carries one
    of the filter's suffixes, leaves the path as it is."""
    inside = ""
    if chosen_filter and "(" in chosen_filter:
        inside = chosen_filter[chosen_filter.find("(") + 1:chosen_filter.rfind(")")]
    suffixes = [p[1:].lower() for p in inside.split()
                if p.startswith("*.") and len(p) > 2]
    if not suffixes or os.path.splitext(path)[1].lower() in suffixes:
        return path
    return os.path.splitext(path)[0] + suffixes[0]


#: What a format's sidecar rows_written counts, as (singular, plural). A
#: format absent here (the PDF lists selected records, the offline report
#: counts several units at once) puts no number on the status line.
_WRITTEN_UNITS = {
    "loc_csv": ("position fix", "position fixes"),
    "loc_kml": ("position fix", "position fixes"),
    "loc_json": ("position fix", "position fixes"),
    "loc_xlsx": ("position fix", "position fixes"),
    "csv": ("record, live and recovered", "records, live and recovered"),
    "sqlite": ("record, live and recovered", "records, live and recovered"),
    "json": ("live record", "live records"),
    "xlsx": ("live record", "live records"),
    "sqlite_raw": ("table row", "table rows"),
}


def _written_count(key, paths):
    """ "94 position fixes": what the file just written holds, read from the
    sidecar the writer produced beside it; "" when the format has no single
    unit or no sidecar was written."""
    units = _WRITTEN_UNITS.get(key)
    if units is None:
        return ""
    for path in paths[1:]:
        if not str(path).endswith(".metadata.json"):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                side = json.load(fh)
        except (OSError, ValueError):
            return ""
        rows = side.get("rows_written")
        if not isinstance(rows, int):
            return ""
        text = "%s %s" % (format(rows, ","),
                          units[0] if rows == 1 else units[1])
        # Recovered records written to a section of their own are named
        # with it, so the live count is not read as the whole file.
        recovered = side.get("recovered_rows_written")
        if isinstance(recovered, int) and recovered:
            text += " and %s recovered record%s (%s)" % (
                format(recovered, ","), "" if recovered == 1 else "s",
                side.get("recovered_rows_section") or "own section")
        return text
    return ""


def _picked_from(name, listed, noun):
    """ "2026-02-17, 1 of 112 periods" -- which row of a summary list an
    export took its records from, counted in that list's own unit."""
    count = "1 of %s %s%s" % (format(listed, ","), noun,
                              "" if listed == 1 else "s")
    return "%s, %s" % (name, count) if name else count


def _export_name_part(view, label):
    """What a view export holds, as a filename part: the record set on
    screen when the view has several (File access, Downloads, HSTS pins),
    otherwise the view's own label."""
    segments = getattr(view, "_segments_by_key", {})
    if len(segments) > 1:
        label = segments[view._active_key].label
    return export_target.name_part(label)


def _button_promised_count(text):
    """The N a button's label promises ("Export view (1,234)" -> 1234,
    "Export header pairs (546)" -> 546), read from the text itself.

    The button's text was set when the row set last changed, so comparing it
    with the model's current count detects rows that changed between the
    label and the click (_export_view, _export_header_pairs).

    None when the text does not end in a parenthesised integer; a caller
    then has nothing to compare against and does not refuse the export.
    """
    text = (text or "").strip()
    if not text.endswith(")") or "(" not in text:
        return None
    inside = text[text.rfind("(") + 1:-1].replace(",", "")
    return int(inside) if inside.isdigit() else None


#: The size a fresh launch aims for on a display with room for it, clamped
#: to the screen present (see default_size() below). Sizing is this class's
#: job; __main__.py shows the window it is given.
_DEFAULT_SIZE = (1600, 900)

#: The smallest saved geometry worth restoring.
#:
#: _on_a_current_screen() below checks only that the restored rectangle
#: overlaps an attached screen. A window can do that and still be unusable
#: (820x360, say, where the 208px sidebar leaves a sliver of table).
#:
#: Low on purpose: a window the examiner made small on purpose is restored,
#: so the floor is the smallest full-screen mode Windows has offered, below
#: any size chosen deliberately, and catches only broken geometry.
MIN_USABLE_SIZE = (640, 480)


#: Left clear around a default-sized window so it reads as a window
#: rather than as a maximised one, and so its edges stay grabbable.
#: availableGeometry() has already excluded the taskbar; this is margin
#: on top of that, not compensation for it.
_DEFAULT_MARGIN = 48


def default_size(available):
    """_DEFAULT_SIZE, but never larger than the screen it opens on (a
    1920x1080 panel at 125% offers 1536x864).

    Never smaller than MIN_USABLE_SIZE: a screen too small for a working
    window is not something sizing can solve.
    """
    return (max(MIN_USABLE_SIZE[0],
                min(_DEFAULT_SIZE[0], available.width() - _DEFAULT_MARGIN)),
            max(MIN_USABLE_SIZE[1],
                min(_DEFAULT_SIZE[1], available.height() - _DEFAULT_MARGIN)))


def geometry_floor(available):
    """MIN_USABLE_SIZE, per axis, but never more than the screen offers.

    A guard demanding 640x480 on a smaller screen would reject every
    geometry there is and spend every launch fighting Qt's own clamping.
    """
    return (min(MIN_USABLE_SIZE[0], available.width()),
            min(MIN_USABLE_SIZE[1], available.height()))


def _companions_written(paths):
    """The files written beside an export, each by its own name and what
    it is: an export can carry a provenance sidecar AND a SHA-256 file
    (the offline report), and the done bar names what was written."""
    words = []
    for path in paths:
        name = os.path.basename(path)
        if name.endswith(".metadata.json"):
            words.append("%s (provenance sidecar)" % name)
        elif name.endswith(".sha256"):
            words.append("%s (SHA-256)" % name)
        else:
            words.append(name)
    return " and ".join(words)


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WebCache Forensic Analyzer")
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        # Used instead of QStatusBar.showMessage() (see
        # _ElidingStatusLabel). addWidget, not addPermanentWidget, puts it in
        # the left, stretch=1 region, ahead of the permanent widgets added
        # below.
        self._status_message = _ElidingStatusLabel()
        self._status.addWidget(self._status_message, 1)

        # Busy state for opening an exhibit. The parse runs on a QThread
        # (evidence_loader.py), so the window stays live, and an
        # indeterminate QProgressBar shows that work is in progress.
        #
        # Indeterminate, because parse_all_entries() cannot know its total
        # record count in advance without reading every table (see
        # WebCacheParser.count_all_tables). The status text gives the real
        # figures: a running record count from the parser's
        # progress_callback, and the elapsed time.
        self._load_progress = QProgressBar()
        self._load_progress.setRange(0, 0)
        self._load_progress.setTextVisible(False)
        self._load_progress.setMaximumWidth(120)
        self._load_progress.setVisible(False)
        self._load_cancel_button = QPushButton("Cancel")
        self._load_cancel_button.setVisible(False)
        # Routed through a dispatcher rather than _cancel_current_load: the
        # pair serves an evidence load or a recovery scan (self._busy_for).
        self._load_cancel_button.clicked.connect(self._cancel_current_busy_operation)
        self._status.addPermanentWidget(self._load_progress)
        self._status.addPermanentWidget(self._load_cancel_button)
        # The "993 records | 83 tables | 34 containers | Dirty shutdown"
        # segment, as rich text so the dirty-shutdown word can carry its own
        # colour (see _db_summary_html). Empty until an exhibit is open:
        # _db_summary_html(None) -> "", so no zero is shown before anything
        # is parsed.
        self._db_summary_info = None
        self._db_summary_label = copyable.selectable(QLabel(""))
        self._db_summary_label.setTextFormat(Qt.RichText)
        self._status.addPermanentWidget(self._db_summary_label)
        # The version chip: provenance.TOOL_VERSION, the string every
        # export stamps into its provenance block.
        version_label = copyable.selectable(
            QLabel("v%s" % provenance.TOOL_VERSION.rsplit(".", 1)[0]))
        version_label.setStyleSheet(
            "font-family: 'Cascadia Mono', Consolas, monospace; font-size: 11px;")
        # Apart from the summary (else "Dirty shutdown v5.0" reads as one
        # phrase) and off the window edge.
        version_label.setContentsMargins(10, 0, 10, 0)
        self._status.addPermanentWidget(version_label)
        # Ticks independently of the worker's own progress signal -- see
        # _refresh_load_elapsed's docstring for why elapsed time must keep
        # moving even if the parser itself goes quiet for a while.
        self._load_elapsed = QElapsedTimer()
        self._load_status_timer = QTimer(self)
        self._load_status_timer.setInterval(500)
        self._load_status_timer.timeout.connect(self._refresh_load_elapsed)
        self._load_last_message = ""

        # The recovery scan uses this same progress bar and Cancel button.
        # An evidence load and a recovery scan never run together:
        # _start_recovery needs self._parser, which exists only after a load
        # has finished, and opening a new exhibit mid-scan cancels the scan
        # (_cancel_pending_recovery) before the new load starts.
        # self._busy_for records which operation the pair belongs to, so
        # Cancel reaches the right one.
        self._busy_for = None  # None | "load" | "recovery" | "export"
        #: The runner for the export in progress, and its format key: used
        #: to route the shared Cancel button (_cancel_current_busy_operation)
        #: and to reset that card when the export ends.
        self._export_runner = None
        self._export_key = None
        self._last_view_scope = None
        #: The case file for the exhibit on screen, or None. Opened by
        #: _on_evidence_loaded through case_store; app-local and keyed by
        #: the evidence SHA-256, NEVER beside the exhibit.
        self._case = None
        #: True once _open_case_file has run, whether or not a case file
        #: opened. self._case is None both before any exhibit loads and when
        #: the case file could not open; _push_export_state tells them apart
        #: (the Export page keeps its initial state for the first, and shows
        #: "no case file" with fields disabled for the second).
        self._case_opened_ever = False
        #: None until an exhibit has been opened; set in _on_evidence_loaded
        #: and cleared on every new Open Evidence, so a scan of a previous
        #: exhibit is never taken as covering the current one.
        self._parser = None
        self._recovery_loader = None
        self._recovery_engine = None
        #: "not_run" | "running" | "done", and the scan's
        #: pages done in words while it runs ("" before any report).
        self._recovery_state = "not_run"
        self._recovery_pages = ""
        #: The admitted-record set every Timeline grain is bucketed from,
        #: and the carved identity set its pane uses to mark recovered
        #: records. Rebuilt on every load and after a scan.
        self._timeline_inputs = None
        #: which clock Timeline's periods are cut on, "utc" | "local".
        self._timeline_clock = "utc"
        #: The TimelineBuilder in progress (or last finished); None before
        #: the first _fill_timeline. Read by _cancel_pending_timeline_build,
        #: as _cancel_pending_load reads self._loader.
        self._timeline_builder = None
        #: The (inputs, rows_by_grain, notes_by_grain) the last completed
        #: TimelineBuilder delivered, kept even when the Timeline view has
        #: not been built yet (_fill_timeline runs at every open and scan).
        #: `inputs` is kept so _push_timeline_state can check, by identity,
        #: that the result still answers self._timeline_inputs, and apply it
        #: to a view built later without a second build.
        self._timeline_results = None
        #: The SearchRunner in progress (or last finished); None before the
        #: first search. Read by _cancel_pending_search, as
        #: _cancel_pending_load reads self._loader; a new search can start
        #: with one keystroke and Return.
        self._search_runner = None
        #: The (query, result) of the last COMPLETED search, cached
        #: unconditionally -- Search view built or not -- so a view built
        #: late replays a finished search instead of paying a second
        #: seven-second scan for an answer already in hand. Exhibit-
        #: scoped: results belong to a database, not to a session, and
        #: _push_search_state refuses to replay one whose query names a
        #: different db_path.
        self._search_results = None
        #: The position fixes and the places they group into, for this
        #: exhibit; reset with each exhibit, like _recovery_engine. The loc_*
        #: capability tokens and every position export read these.
        self._location_fixes = []
        self._location_places = []
        #: The scale places are grouped at (location_loader.GROUPINGS). An
        #: examiner's choice, so it outlives an exhibit change.
        self._location_grouping = location_loader.DEFAULT_GROUPING
        #: The live-only row set from the most recent load, kept separately
        #: from whatever HistoryView.table.model() currently holds -- once
        #: a scan completes, History shows live + carved MERGED, but a
        #: second scan (or a fresh live-only reset) needs the ORIGINAL live
        #: rows back, not whatever carved rows happen to already be on
        #: screen.
        self._live_history_rows = []
        #: Same discipline as _live_history_rows above, one per File
        #: Access segment -- kept separately so a completed recovery scan
        #: can merge carved rows onto the ORIGINAL live set for each
        #: segment, not onto whatever carved rows a previous scan already
        #: left on screen.
        self._live_file_access_rows = []
        self._live_download_rows = []
        #: The same discipline once more, for HTTP Headers.
        self._live_header_rows = []
        #: dashboard_data.compute_dashboard_stats()'s dict, or None: the
        #: live-only figures from the latest load, kept apart from what
        #: DashboardView shows. A completed recovery scan
        #: (_on_recovery_loaded) merges carved rows onto this, never onto a
        #: previously merged state.
        self._dashboard_live_stats = None
        #: ForensicEngine.get_statistics() for the open exhibit, or None
        #: -- see _compute_report_statistics for why this is NOT the
        #: dashboard's dict and why it is computed once rather than per
        #: export.
        self._report_stats = None

        # Applied FIRST, before any widget below ever calls theme.color():
        # a drawn glyph (glyphs.py) is a QPixmap baked in at construction
        # time, not re-read from the stylesheet the way QPalette/QSS
        # colours are -- building Sidebar/FirstRunView/the view stack
        # before the saved theme setting is loaded would paint every one
        # of them from whatever theme a PREVIOUS MainWindow in this same
        # process happened to leave active in theme's module state.
        theme.apply(QApplication.instance(), settings.get("theme", "dark"))
        # The saved palette is applied now, so the summary label can read
        # theme.color() (see _refresh_db_summary_widget).
        self._refresh_db_summary_widget()

        #: whether every grid wraps long values. Read before any view
        #: is built, so each grid is born in the saved state.
        self._grid_wrap = bool(settings.get("grid_wrap"))
        time_format.set_pattern(settings.get("time_format")
                                or time_format.DEFAULT_PATTERN)
        # Sized by the view on screen, never by the tallest one ever
        # visited -- see current_page_stack.py.
        self.stack = CurrentPageStack()
        self._index = {}
        self._labels = {}
        self._caveats = {}
        #: Keys already given a chance to restore their saved column
        #: widths -- see _restore_column_state's docstring for why this is
        #: a one-shot-per-view gate rather than something reapplied on
        #: every Open Evidence.
        self._column_state_restored = set()
        #: True once an exhibit has loaded this session. Gates the swap from
        #: FirstRunView to the view stack, and is not reverted by a later
        #: failed load, which leaves the window as it was
        #: (test_parse_failure_shows_an_actionable_message_and_leaves_the_
        #: app_usable).
        self._ever_loaded = False
        #: Every RecordDetailDialog currently open, in the order opened.
        #:
        #: Kept for the same reason RecordsTable holds _filter_popup as an
        #: attribute: Python must not garbage-collect a still-visible
        #: non-modal dialog out from under Qt. Entries are removed on
        #: `destroyed` rather than on close, so the list cannot grow
        #: without bound, and _on_evidence_loaded empties it before
        #: swapping self._parser -- see _close_record_dialogs.
        self._detail_dialogs = []

        self._built_keys = set()
        #: stack index -> (view, stand-in) for built views parked outside
        #: the window during a theme switch (see _park_hidden_views).
        self._parked = {}
        for section, items in NAV_SECTIONS:
            for key, label, caveat in items:
                self._labels[key] = label
                self._caveats[key] = caveat
                self._index[key] = self.stack.count()
                # A bare stand-in with no children for every key, replaced
                # by the real, wired view the first time it is needed (see
                # _ensure_view_built).
                self.stack.addWidget(QWidget())

        # The shell around the view stack: sidebar | (first-run or the
        # view stack); see sidebar.py and first_run.py.
        self.sidebar = Sidebar(NAV_SECTIONS)
        self.nav = self.sidebar.nav  # still literally a QListWidget -- see sidebar.py
        # Marked once here (see _NO_COUNT_KEYS for why these keys never get
        # a sidebar.set_count() call).
        for _key in _NO_COUNT_KEYS:
            self.sidebar.set_no_count(_key)
        self.first_run = FirstRunView()
        self.content_stack = CurrentPageStack()
        self.content_stack.addWidget(self.first_run)  # index 0: no evidence yet
        # the Back button and breadcrumb sit above the view stack.
        self._nav_history = nav_history.NavHistory()
        self._current_crumb = ""
        self.nav_bar = nav_history.NavBar()
        self.nav_bar.back_button.clicked.connect(self.go_back)
        stack_page = QWidget()
        stack_layout = QVBoxLayout(stack_page)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.setSpacing(0)
        stack_layout.addWidget(self.nav_bar)
        # after an export, where it went, until dismissed. In the
        # status bar, OUT of the content column's layout flow: in the
        # flow it added its own height to every screen and pushed the
        # column into a page scroll.
        self.export_result_bar = ExportResultBar()
        self.export_result_bar.copyRequested.connect(self._copy_path)
        self.export_result_bar.showRequested.connect(self._show_export_folder)
        # Index 1: after the one normal widget (the status message), so
        # it is the FIRST permanent widget, left of the progress and the
        # database summary.
        self._status.insertPermanentWidget(1, self.export_result_bar, 1)
        # While the bar is up it carries the full path the status message
        # also states, so it takes the message's room and the database
        # summary's (both back on dismiss): a case-folder path then fits
        # one line, and the status bar -- and the sidebar above it --
        # keeps its height.
        self.export_result_bar.shownChanged.connect(
            self._export_bar_shown)
        stack_layout.addWidget(self.stack, 1)
        self.content_stack.addWidget(stack_page)       # index 1: the real views
        self.content_stack.setCurrentIndex(0)

        # In a resizable QScrollArea rather than directly in body's
        # QHBoxLayout: a layout makes every child's minimumSizeHint a floor
        # for the window's minimum size, and FirstRunView's card row would
        # set a minimum width above 900px. A QScrollArea does not pass its
        # contents' minimum on, so the window can shrink, while every view
        # renders at full size whenever there is room.
        #
        # The scroll area is for width. Every screen fits its height at the
        # shipped size, and go_to() resets the offset to the top.
        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QFrame.NoFrame)
        content_scroll.setWidget(self.content_stack)
        # Not a Tab stop: it has nothing to show the keyboard, and the
        # views inside it carry their own stops.
        content_scroll.setFocusPolicy(Qt.NoFocus)
        self._content_scroll = content_scroll

        central = QWidget()
        body = QHBoxLayout(central)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.sidebar)
        body.addWidget(content_scroll, 1)
        self.setCentralWidget(central)
        self.nav.currentItemChanged.connect(self._nav_changed)

        self._build_menus()
        # Both Open Database buttons trigger the same QAction rather than
        # calling open_evidence(): trigger() does nothing while the action
        # is disabled (test_wiring.py), which prevents a second load while
        # one is in progress.
        self.sidebar.openRequested.connect(self.open_evidence_action.trigger)
        self.first_run.open_button.clicked.connect(self.open_evidence_action.trigger)
        self.open_evidence_action.changed.connect(self._sync_open_buttons_enabled)
        self._sync_open_buttons_enabled()
        self.sidebar.themeToggleRequested.connect(self._toggle_theme)
        # restored BEFORE the persisting connection, so a launch does
        # not write the value it just read.
        self.sidebar.set_collapsed(bool(settings.get("sidebar_collapsed")))
        self.sidebar.collapsedChanged.connect(
            lambda collapsed: settings.save(sidebar_collapsed=bool(collapsed)))

        # The third way to name an exhibit, alongside the menu and both
        # Open Database buttons -- see the "evidence by drag and drop"
        # section below for the whole of it. The window is the drop
        # target, not the first-run card, so an examiner who already has
        # one exhibit open can still drop the next one; and every child
        # widget that would have intercepted the drag first is disarmed
        # here (and again per view in _ensure_view_built).
        self.setAcceptDrops(True)
        #: A drop accepted whose Open Evidence dialog has not opened yet
        #: (dropEvent defers it by one turn of the event loop).
        self._drop_pending = False
        #: The Open evidence dialog's answer, held until the live parse
        #: lands. Reset on every exit path so a failed or
        #: superseded open never starts a scan later.
        self._recover_after_load = False
        # Sized to the central widget and kept sized by its resize events
        # (see eventFilter): MainWindow.resizeEvent fires before the layout
        # has moved the central widget, so a geometry set there would lag by
        # one resize.
        self.drop_overlay = DropOverlay(central)
        central.installEventFilter(self)
        self._disarm_child_drop_targets(self)

        self._install_shortcuts()
        self._restore_geometry()
        self.go_to("dashboard")

    # --- construction helpers -------------------------------------------

    def _restore_geometry(self):
        """Restore the window geometry closeEvent saved.

        Three ways restoring can go wrong; none may raise or strand the
        window:

        1. A truncated or hand-edited hex string: bytes.fromhex raises
           ValueError, caught as settings.load() catches a corrupt
           settings.json, and the default size is used.
        2. A geometry saved on a monitor no longer attached (common when
           moving between a docked workstation and a laptop):
           restoreGeometry() restores it regardless, so it is checked
           against every currently attached screen and replaced by the
           default size if it lands on none.
        3. A size too small to work in (see MIN_USABLE_SIZE).
        """
        raw = settings.get("window_geometry", "")
        if raw:
            try:
                blob = bytes.fromhex(raw)
            except ValueError:
                blob = b""
            if (blob and self.restoreGeometry(blob)
                    and self._on_a_current_screen()
                    and self._is_a_usable_size()):
                return self._restore_maximized()
        self._resize_to_default()
        self._restore_maximized()

    def _restore_maximized(self):
        """Re-apply the maximized state, whatever happened to the geometry.

        Called on BOTH paths above on purpose. When restoreGeometry()
        succeeded it has usually already done this and the call is a
        no-op; when it refused the blob -- which it does for any geometry
        saved on a screen of a different width -- this is the only thing
        that still knows the examiner works maximized.

        Set through setWindowState rather than showMaximized(): this runs
        during __init__, before the window is shown, and showMaximized()
        would show it.
        """
        if settings.get("window_maximized"):
            self.setWindowState(self.windowState() | Qt.WindowMaximized)

    def _resize_to_default(self):
        """Open at the default size for THIS screen, centred on it.

        Centred because this is the no-saved-geometry path: there is no
        position to honour, and a window that opens under the taskbar or
        half off the right edge looks like a fault rather than a first
        run.
        """
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(*_DEFAULT_SIZE)
            return
        available = screen.availableGeometry()
        width, height = default_size(available.size())
        self.resize(width, height)
        self.move(available.x() + (available.width() - width) // 2,
                  available.y() + (available.height() - height) // 2)

    def _on_a_current_screen(self):
        """True if this window's geometry overlaps at least one attached
        screen. Checked after restoreGeometry() has moved and resized the
        window, so self.geometry() reflects the restored value."""
        frame = self.geometry()
        return any(screen.geometry().intersects(frame)
                   for screen in QGuiApplication.screens())

    def _is_a_usable_size(self):
        """True if the restored size clears geometry_floor() on both axes.

        Measured against the screen the window landed on, not the primary
        one, so a small secondary display is judged by its own size.
        self.screen() is None until the window has a handle, so the
        primary screen stands in.
        """
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return True
        floor_w, floor_h = geometry_floor(screen.availableGeometry().size())
        size = self.size()
        return size.width() >= floor_w and size.height() >= floor_h

    def _make_placeholder(self, key, label, caveat):
        """A fallback: a nav key's title and caveat under the standard
        ViewHeader/CaveatLine chrome.

        Reached only from _construct_view's `else:` branch, for a key in
        NAV_SECTIONS with no branch of its own; every shipped key has one.
        It keeps a newly added destination without a branch visible and
        labelled rather than failing.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        w.header = ViewHeader(NAV_ICONS.get(key, "grid"), label,
                              "Not yet built in this phase.")
        w.caveat = CaveatLine(caveat)
        lay.addWidget(w.header)
        lay.addWidget(w.caveat)
        lay.addStretch(1)
        return w

    def _construct_view(self, key, label, caveat):
        """The real widget for `key`: construct it and wire every signal it
        needs. The one place a view is built, called for the dashboard at
        the end of __init__ and for every other key from
        _ensure_view_built. Every key in NAV_SECTIONS has a branch; the
        `else:` fallback renders a labelled stub (see _make_placeholder).
        """
        if key == "dashboard":
            widget = DashboardView()
            widget.drillRequested.connect(
                lambda k, row: (self._drill_to_domain(k, row)
                                if k == "domains" else self.go_to(k)))
            widget.set_caveat(caveat)
        elif key == "history":
            widget = HistoryView()
            widget.drillRequested.connect(
                lambda k, row: (self._drill_to_domain(k, row)
                                if k == "domains" else self.go_to(k)))
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            widget.set_caveat(caveat)
        elif key == "recovery":
            widget = RecoveryView()
            widget.recoverRequested.connect(self._start_recovery)
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            # The Deleted Records "Export view (N)" button.
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            widget.set_caveat(caveat)
        elif key == "downloads":
            widget = FileAccessView()
            widget.drillRequested.connect(lambda k, _row: self.go_to(k))
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            widget.set_caveat(caveat)
        elif key == "headers":
            widget = HeadersView()
            # Not the generic `lambda k, _row: self.go_to(k)`: this
            # view's Container cell and its pane's "Browse Container_N"
            # button name a specific container, and
            # _drill_container_to_browser opens the Table Browser on that
            # container's table.
            widget.drillRequested.connect(self._drill_container_to_browser)
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            # Two exports, for two counts (see views/headers.py); both go
            # through _start_export.
            widget.pairExportRequested.connect(
                lambda w=widget: self._export_header_pairs(w))
            widget.set_caveat(caveat)
        elif key == "cookies":
            widget = CookiesView()
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            widget.set_caveat(caveat)
        elif key == "containers":
            widget = ContainersView()
            # Not the generic `lambda k, _row: self.go_to(k)`: a container
            # name opens the Table Browser on that container's table (see
            # _drill_container_to_browser).
            widget.drillRequested.connect(self._drill_container_to_browser)
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            widget.set_caveat(caveat)
        elif key == "export":
            widget = ExportView()
            widget.exportRequested.connect(self._export_format)
            widget.caseMetaChanged.connect(self._case_meta_changed)
            widget.copyPathRequested.connect(self._copy_path)
            # Read from the engine's schema rather than written as a
            # number.
            widget.set_field_count(export_formats.CANONICAL_FIELD_COUNT)
            widget.set_caveat(caveat)
        elif key == "integrity":
            widget = IntegrityView()
            widget.saveTextRequested.connect(self._save_integrity_text)
            widget.set_caveat(caveat)
        elif key == "browser":
            widget = TableBrowserView()
            # The view reports which bytes were requested; the shell opens
            # the blob viewer, as for recordActivated.
            widget.blobRequested.connect(self._show_blob)
            widget.rowRequested.connect(self._show_table_row)
            widget.set_caveat(caveat)
        elif key == "domains":
            widget = DomainsView()
            # The pane's Container cell names a container, as Timeline's
            # does; the Domain cell selects in place.
            widget.drillRequested.connect(self._drill_container_to_browser)
            widget.pane.table.explainRequested.connect(self._explain_value)
            widget.pane.table.recordActivated.connect(self._show_record_detail)
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            # The pane's own "Export these records (N)": the records of the
            # ONE selected domain, each with its own raw fields.
            widget.pane.exportRequested.connect(
                lambda w=widget: self._export_domain_records(w))
            widget.set_caveat(caveat)
        elif key == "location":
            widget = LocationView()
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            # COPY, NEVER OPEN. The view says only "an examiner
            # asked for this text"; the shell owns the clipboard,
            # the same division exportRequested already follows.
            widget.copyRequested.connect(self._copy_link)
            widget.groupingChanged.connect(self._location_grouping_changed)
            widget.show_grouping(self._location_grouping)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            widget.set_caveat(caveat)
        elif key == "timeline":
            widget = TimelineView()
            # Not the generic `lambda k, _row: self.go_to(k)`: the pane's
            # Container cell names a specific container, as in HeadersView.
            widget.drillRequested.connect(self._drill_container_to_browser)
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            # The pane's table too: a record reached through a period opens
            # as one reached through History does (_show_record_detail
            # accepts any row carrying a _record).
            widget.pane.table.explainRequested.connect(self._explain_value)
            widget.pane.table.recordActivated.connect(self._show_record_detail)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            # Two exports, for the two things this screen calls a timeline
            # (see views/timeline.py).
            widget.periodRecordsExportRequested.connect(
                lambda w=widget: self._export_period_records(w))
            widget.clockChanged.connect(self._timeline_clock_changed)
            widget.set_caveat(caveat)
        elif key == "tagged":
            widget = TaggedView()
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            widget.drillRequested.connect(self._drill_container_to_browser)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            widget.set_caveat(caveat)
        elif key == "indicators":
            widget = IndicatorsView()
            widget.table.explainRequested.connect(self._explain_value)
            widget.table.recordActivated.connect(self._show_record_detail)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            widget.set_caveat(caveat)
        elif key == "search":
            widget = SearchView()
            widget.searchRequested.connect(self._start_search)
            # NOT the generic `lambda k, _row: self.go_to(k)`, and NOT
            # _drill_container_to_browser either -- a hit NAMES a real
            # table directly, where that method computes "Container_%d"
            # from an id it does not have here.
            widget.drillRequested.connect(self._drill_table_to_browser)
            widget.table.explainRequested.connect(self._explain_value)
            # A hit opens: a database hit at its row in Table
            # Browser, a recovered hit as the record it is.
            widget.table.recordActivated.connect(self._open_search_hit)
            widget.pane.table.explainRequested.connect(self._explain_value)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            # Two exports: the hits, and the full field list of the row a
            # hit was found in.
            widget.rowFieldsExportRequested.connect(
                lambda w=widget: self._export_hit_fields(w))
            widget.set_caveat(caveat)
        elif key == "iocs":
            widget = FindingsView()
            # Not the generic `lambda k, _row: self.go_to(k)` (see
            # _drill_iocs): two segments name different drill targets
            # (EntryId gaps' Container to the Table Browser,
            # Beaconing's Domain to Domains), through the one drillRequested
            # signal.
            widget.drillRequested.connect(self._drill_iocs)
            widget.watchlistScanRequested.connect(self._rescan_iocs)
            widget.table.explainRequested.connect(self._explain_value)
            # ioc_hits rows are records (each wraps the live or carved entry
            # match_iocs matched, by reference; see
            # iocs_loader.ioc_hit_rows), so Enter or double-click opens the
            # record as in History. The other five segments carry no
            # `_record` (see record_kinds.AGGREGATES/ORIGIN_SENTENCE), and
            # fields_for() handles that without raising, so this is wired
            # once for the shared table.
            widget.table.recordActivated.connect(self._show_record_detail)
            widget.exportRequested.connect(
                lambda w=widget, k=key: self._export_view(w, k))
            widget.set_caveat(caveat)
        else:
            widget = self._make_placeholder(key, label, caveat)
        # "Search the database for this value" is on every RecordsTable's
        # context menu (widgets/records_table.py), panes included, so it is
        # wired on every table the view holds. findChildren walks the widget
        # once, at construction.
        for table in widget.findChildren(RecordsTable):
            table.searchRequested.connect(self.search_for)
            table.showInTableRequested.connect(self.show_in_database_table)
            table.set_wrap(self._grid_wrap)
        # The Table Browser's raw grid follows the same switch; it is a
        # QTableWidget, not a RecordsTable.
        set_wrap = getattr(widget, "set_wrap", None)
        if callable(set_wrap):
            set_wrap(self._grid_wrap)
        wrap_button = getattr(widget, "wrap_button", None)
        if wrap_button is not None:
            wrap_button.blockSignals(True)
            wrap_button.setChecked(self._grid_wrap)
            wrap_button.blockSignals(False)
            widget.wrapToggled.connect(self.set_grid_wrap)
        self._wire_case_notes(widget)
        header = getattr(widget, "header", None)
        if header is not None and hasattr(header, "show_help_button"):
            # _c first: clicked(bool) passes the checked state, which
            # would otherwise land in `k` and open the wrong section.
            header.show_help_button(
                lambda _c=False, k=key: self.show_user_guide(k))
        return widget

    def _ensure_view_built(self, key):
        """The way to a real view, for anything about to show or use one:
        go_to(), a drill-down, or a menu action that opens a page not yet
        visited. Builds and wires it (_construct_view) the first time it is
        asked for, and swaps it into self.stack at the index its stand-in
        held (removeWidget then insertWidget, never appended), so
        self._index and self._page_at(self._index[key]) keep working.
        self._built_keys ensures it is built once.

        If evidence, and possibly a recovery scan, has already loaded when
        a view is built, it is given the same state every other view
        received at load and scan time (_replay_view_state), so a view built
        late is never empty.

        Gated on self._ever_loaded rather than self._parser: a load can
        succeed with parser=None (some tests, a minimal WebCacheParser
        stand-in) and still have state to replay, such as
        self._live_history_rows, which comes from EvidenceLoader's `rows`.
        """
        if key in self._built_keys:
            return self._page_at(self._index[key])
        index = self._index[key]
        stand_in = self.stack.widget(index)
        widget = self._construct_view(key, self._labels[key], self._caveats[key])
        self.stack.removeWidget(stand_in)
        stand_in.deleteLater()
        self.stack.insertWidget(index, widget)
        self._built_keys.add(key)
        if self._ever_loaded:
            self._replay_view_state(key)
        # An export may be in progress from another view's button
        # (_start_export disables every export entry point except the one
        # writing; see _export_entry_point_widgets), and this view's button
        # did not exist then, so it is disabled to match.
        if self._busy_for == "export":
            btn = getattr(widget, "export_button", None)
            if btn is not None:
                btn.setEnabled(False)
        # Every filter box in a view is a QLineEdit, which accepts drops by
        # default, and Qt does not pass a drag up the widget tree, so one
        # under the cursor would swallow a dropped exhibit. See
        # _disarm_child_drop_targets.
        self._disarm_child_drop_targets(widget)
        # The segment's caveat is shown in the caveat line above its grid,
        # not repeated in the status bar.
        return widget

    def _page_at(self, index):
        """The view at stack `index`, whether it is in the window or parked
        outside it during a theme switch (see _park_hidden_views)."""
        parked = self._parked.get(index)
        return parked[0] if parked is not None else self.stack.widget(index)

    def _all_record_tables(self):
        """Every RecordsTable, in the window and in parked views."""
        tables = list(self.findChildren(RecordsTable))
        for page, _stand in self._parked.values():
            tables.extend(page.findChildren(RecordsTable))
        return tables

    def _park_hidden_views(self):
        """Lift every built view that is not on screen out of the window.

        QApplication.setStyleSheet re-polishes every widget inside the
        window, and laying out the hidden views is most of that cost. A
        parked view is replaced in the stack by an empty stand-in and is
        brought back, refreshed for the theme then in force, when it is
        next shown (_unpark)."""
        current = self.stack.currentIndex()
        for key in self._built_keys:
            index = self._index[key]
            if index == current or index in self._parked:
                continue
            page = self.stack.widget(index)
            stand = QWidget()
            self.stack.removeWidget(page)
            self.stack.insertWidget(index, stand)
            page.setParent(None)
            self._parked[index] = (page, stand)

    def _unpark(self, index):
        """Put a parked view back in the stack and refresh it for the
        current theme."""
        parked = self._parked.pop(index, None)
        if parked is None:
            return
        page, stand = parked
        self.stack.removeWidget(stand)
        stand.deleteLater()
        self.stack.insertWidget(index, page)
        refresh = getattr(page, "refresh_theme", None)
        if callable(refresh):
            refresh()
        for table in page.findChildren(RecordsTable):
            table.refit_rows()

    def _built_widget(self, key):
        """The widget for `key` if it is already built, otherwise None. Used
        by every load-time and scan-time update instead of
        _ensure_view_built, so opening an exhibit does not build views no
        one has opened.
        """
        if key not in self._built_keys:
            return None
        return self._page_at(self._index[key])

    def _replay_view_state(self, key):
        """Called once, from _ensure_view_built, when a view is built after
        evidence (and possibly a scan) has loaded. Every _push_*_state method
        derives the current state from self._parser/self._recovery_engine
        and the cached self._live_*/self._dashboard_live_stats/
        self._location_* fields, so calling the same methods here, now that
        _built_widget(key) returns the new widget, is the whole mechanism:
        the same calls _on_evidence_loaded and _on_recovery_loaded make for
        views already built.
        """
        push = getattr(self, "_push_%s_state" % key, None)
        if push is not None:
            push()

    def _sync_open_buttons_enabled(self):
        """Both Open Database buttons (sidebar, first-run) mirror
        open_evidence_action's own enabled state -- connected to the
        action's changed signal (QAction emits it on every property
        change, including setEnabled) so a load starting/finishing
        disables/re-enables all three entry points together, rather than
        the menu action alone going dim while two prominent buttons keep
        inviting a second click mid-load."""
        enabled = self.open_evidence_action.isEnabled()
        self.sidebar.open_button.setEnabled(enabled)
        self.first_run.open_button.setEnabled(enabled)

    def _toggle_theme(self):
        """Switch to the other palette (the sidebar pill), save the choice,
        and repaint every drawn pixmap the QSS/QPalette change cannot reach
        (see _refresh_drawn_theme).

        QApplication.setStyleSheet re-polishes every widget in the window,
        so built views that are not on screen are parked outside it first
        (_park_hidden_views) and restyled when next shown; the switch then
        costs only what is visible."""
        new_name = "light" if theme.current_name() == "dark" else "dark"
        # Whatever the status bar said before (a caveat, a running load's
        # elapsed time) is what it says again afterwards.
        previous = self.status_message()
        self._park_hidden_views()
        theme.apply(QApplication.instance(), new_name)
        settings.save(theme=new_name)
        self._refresh_drawn_theme()
        self._set_status_message(previous)

    def set_details_pane(self, on):
        """The details pane, shown or hidden in every view at once, and
        remembered."""
        on = bool(on)
        settings.save(details_pane=on)
        for index in range(self.stack.count()):
            setter = getattr(self._page_at(index), "set_details_visible",
                             None)
            if callable(setter):
                setter(on)

    def choose_time_format(self):
        """View > Time display format."""
        dialog = TimeFormatDialog(time_format.pattern(), self)
        if dialog.exec() == QDialog.Accepted:
            self.set_time_format(dialog.chosen_pattern())

    def set_time_format(self, pattern):
        """Write times with `pattern` everywhere on screen from now on, and
        remember it. Grids are refilled so their text, their search and
        their value lists all use the new spelling; exports are unchanged."""
        time_format.set_pattern(pattern)
        settings.save(time_format=time_format.pattern())
        for table in self._all_record_tables():
            model = table.model()
            if model is not None:
                model.set_rows(list(model.filter.rows))
        self._push_dashboard_state()
        self._push_integrity_state()
        self._set_status_message(
            "Times are now shown as %s. Exports still write ISO 8601."
            % time_format.format_with(time_format.pattern(),
                                      TIME_FORMAT_EXAMPLE))

    def set_grid_wrap(self, on):
        """Every grid, every view's button and the menu item move
        together, and the choice outlives the session."""
        on = bool(on)
        self._grid_wrap = on
        settings.save(grid_wrap=on)
        for table in self._all_record_tables():
            table.set_wrap(on)
        for index in range(self.stack.count()):
            set_wrap = getattr(self._page_at(index), "set_wrap", None)
            if callable(set_wrap):
                set_wrap(on)
            button = getattr(self._page_at(index), "wrap_button", None)
            if button is not None and button.isChecked() != on:
                button.blockSignals(True)
                button.setChecked(on)
                button.blockSignals(False)
        if self.wrap_action.isChecked() != on:
            self.wrap_action.blockSignals(True)
            self.wrap_action.setChecked(on)
            self.wrap_action.blockSignals(False)

    def _refresh_drawn_theme(self):
        """theme.apply() already repainted every QSS/QPalette-driven pixel
        the instant it ran. What it cannot reach is a QPixmap this shell
        painted itself with theme.color() and baked in at construction
        time (glyphs.py icons, and the few inline colour strings sidebar.py
        and content_header.py set outside QSS) -- those need an explicit
        second pass, which is what every refresh_theme() call below is."""
        self.sidebar.refresh_theme()
        self.nav_bar.refresh_theme()
        self.export_result_bar.refresh_theme()
        self.first_run.refresh_theme()
        self._refresh_db_summary_widget()
        for index in range(self.stack.count()):
            widget = self.stack.widget(index)
            refresh = getattr(widget, "refresh_theme", None)
            if callable(refresh):
                refresh()
                continue
            for attr in ("header", "caveat"):
                sub = getattr(widget, attr, None)
                if sub is not None and hasattr(sub, "refresh_theme"):
                    sub.refresh_theme()
        # Font metrics change with the theme: wrapped rows are re-measured,
        # including the grids inside panes.
        for table in self.findChildren(RecordsTable):
            table.refit_rows()

    def _build_menus(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        self._file_menu = file_menu
        self.open_evidence_action = QAction("Open Evidence…", self)
        self.open_evidence_action.setShortcut(QKeySequence("Ctrl+O"))
        self.open_evidence_action.triggered.connect(self.open_evidence)
        file_menu.addAction(self.open_evidence_action)
        file_menu.addSeparator()
        self.case_folder_action = QAction("Case files folder…", self)
        self.case_folder_action.triggered.connect(self.show_case_folder)
        file_menu.addAction(self.case_folder_action)
        evidence_menu = bar.addMenu("&Evidence")
        self._evidence_menu = evidence_menu
        self.recover_action = QAction("Recover deleted records…", self)
        # Disabled until an exhibit is open (_on_evidence_loaded enables
        # it): RecoveryWorker needs a parsed WebCacheParser.
        self.recover_action.setEnabled(False)
        self.recover_action.triggered.connect(self._start_recovery)
        evidence_menu.addAction(self.recover_action)
        view_menu = bar.addMenu("&View")
        self._view_menu = view_menu
        for key in self.nav_keys:
            act = QAction(self._labels[key], self)
            act.triggered.connect(lambda _c=False, k=key: self.go_to(k))
            view_menu.addAction(act)
        self.back_action = QAction("Back", self)
        self.back_action.setShortcut(QKeySequence("Alt+Left"))
        self.back_action.setEnabled(False)
        self.back_action.triggered.connect(self.go_back)
        view_menu.addAction(self.back_action)
        # A window-level action, so Alt+Left works whatever has focus.
        self.addAction(self.back_action)
        view_menu.addSeparator()
        self.wrap_action = QAction("Wrap long values", self)
        self.wrap_action.setCheckable(True)
        self.wrap_action.setChecked(self._grid_wrap)
        self.wrap_action.toggled.connect(self.set_grid_wrap)
        view_menu.addAction(self.wrap_action)
        self.time_format_action = QAction("Time display format…", self)
        self.time_format_action.triggered.connect(self.choose_time_format)
        view_menu.addAction(self.time_format_action)
        # The way back from a saved layout that no longer fits: layouts are
        # saved per view and restored at launch, so one saved from a cramped
        # window can be reset in one step.
        self.reset_columns_action = QAction("Reset column layout", self)
        self.reset_columns_action.setEnabled(False)
        self.reset_columns_action.triggered.connect(self._reset_column_layout)
        view_menu.addAction(self.reset_columns_action)
        # The Export menu.
        export_menu = bar.addMenu("&Export")
        self._export_menu = export_menu
        self.export_report_action = QAction("Export & Report…", self)
        self.export_report_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.export_report_action.triggered.connect(
            lambda: self._guarded_go_to("export"))
        export_menu.addAction(self.export_report_action)
        export_menu.addSeparator()
        self.export_this_view_action = QAction("Export this view…", self)
        self.export_this_view_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_this_view_action.triggered.connect(
            self._export_current_view)
        export_menu.addAction(self.export_this_view_action)
        self.export_bundle_action = QAction("Complete case bundle…", self)
        self.export_bundle_action.triggered.connect(
            lambda: self._export_format("bundle"))
        export_menu.addAction(self.export_bundle_action)
        help_menu = bar.addMenu("&Help")
        self.help_guide_action = QAction("User guide…", self)
        self.help_guide_action.setShortcut(QKeySequence("Ctrl+F1"))
        self.help_guide_action.triggered.connect(
            lambda: self.show_user_guide(self._current_key()))
        help_menu.addAction(self.help_guide_action)
        help_menu.addSeparator()
        self.help_about_action = QAction("About WebCache…", self)
        self.help_about_action.setData(help_texts.ABOUT_TEXT)
        self.help_shortcuts_action = QAction("Keyboard shortcuts…", self)
        self.help_shortcuts_action.setData(help_texts.shortcuts_text())
        self.help_badges_action = QAction(
            "Basis badges (OBS, DER, INF, CARV)…", self)
        self.help_badges_action.setData(help_texts.badge_legend_text())
        for action in (self.help_about_action, self.help_shortcuts_action,
                       self.help_badges_action):
            action.triggered.connect(
                lambda _c=False, a=action: self._show_help(
                    a.text().rstrip("…"), a.data()))
            help_menu.addAction(action)

    def _install_shortcuts(self):
        # Ctrl+1..9 reaches the first nine. Sixteen views cannot fit on nine
        # number keys, so the View menu is the keyboard route to the rest.
        for i, key in enumerate(self.nav_keys[:9], start=1):
            QShortcut(QKeySequence("Ctrl+%d" % i), self,
                      lambda k=key: self.go_to(k))
            self.sidebar._rows[key].set_shortcut("Ctrl+%d" % i)
        QShortcut(QKeySequence(Qt.Key_Backspace), self,
                  self._back_unless_typing)

    def _back_unless_typing(self):
        """Backspace is Back only when no text field has focus -- a line
        edit keeps its own Backspace (it accepts the ShortcutOverride), and
        this guard covers every other editable widget too."""
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit,
                              QAbstractSpinBox)):
            return
        if isinstance(focus, QComboBox) and focus.isEditable():
            return
        self.go_back()

    def go_back(self):
        entry = self._nav_history.pop()
        if entry is None:
            self._sync_back_controls()
            return False
        # go_to cancels any row locate still running, so an answer that
        # arrives after this finds no pending request and selects nothing.
        self.go_to(entry.key, crumb=entry.crumb or None, remember=False)
        self._restore_view_state(entry.key, entry.state)
        return True

    def _sync_back_controls(self):
        can = self._nav_history.can_go_back()
        top = self._nav_history.peek()
        self.nav_bar.set_can_go_back(
            can, self._labels.get(top.key, top.key) if top else "")
        self.back_action.setEnabled(can)

    @property
    def current_crumb(self):
        return self._current_crumb

    # -- what Back gives back: the row selection and the scroll position --

    def _state_grid(self, key):
        widget = self._page_at(self._index[key])
        for attr in ("table", "grid"):
            grid = getattr(widget, attr, None)
            if grid is not None and hasattr(grid, "selectionModel"):
                return grid
        return None

    @staticmethod
    def _grid_state(grid):
        if grid is None or grid.model() is None:
            return None
        cur = grid.currentIndex()
        return {"rows": sorted({ix.row() for ix in
                                grid.selectionModel().selectedIndexes()}),
                "current": (cur.row(), cur.column()) if cur.isValid() else None,
                "vscroll": grid.verticalScrollBar().value(),
                "hscroll": grid.horizontalScrollBar().value()}

    @staticmethod
    def _apply_grid_state(grid, state, select=True):
        if not state or grid is None or grid.model() is None:
            return
        model, sel = grid.model(), grid.selectionModel()
        if select:
            sel.clearSelection()
            for row in state["rows"]:
                if row < model.rowCount():
                    sel.select(model.index(row, 0),
                               QItemSelectionModel.Select
                               | QItemSelectionModel.Rows)
            if state["current"] and state["current"][0] < model.rowCount():
                sel.setCurrentIndex(model.index(*state["current"]),
                                    QItemSelectionModel.NoUpdate)
        grid.verticalScrollBar().setValue(state["vscroll"])
        grid.horizontalScrollBar().setValue(state["hscroll"])

    def _capture_view_state(self, key):
        """The main grid, plus -- for the views with a detail pane (Domains,
        Search) -- which record the pane is describing and the pane's own
        selection and scroll."""
        widget = self._page_at(self._index[key])
        state = self._grid_state(self._state_grid(key))
        if state is None:
            return None
        state["obj"] = getattr(widget, "_current_row", None)
        selected = getattr(widget, "selected_domain", None)
        state["domain"] = selected() if callable(selected) else ""
        pane = getattr(widget, "pane", None)
        state["pane"] = self._grid_state(getattr(pane, "table", None))
        return state

    @staticmethod
    def _select_row_object(grid, obj):
        """Select the row dict `obj` wherever it now sits; False if gone."""
        model = grid.model()
        for i in range(model.rowCount()):
            if model.row_at(i) is obj:
                grid.selectionModel().setCurrentIndex(
                    model.index(i, 0),
                    QItemSelectionModel.ClearAndSelect
                    | QItemSelectionModel.Rows)
                return True
        return False

    def _restore_view_state(self, key, state):
        grid = self._state_grid(key)
        if not state or grid is None or grid.model() is None:
            return
        widget = self._page_at(self._index[key])
        obj, domain = state.get("obj"), state.get("domain")
        placed = False
        if obj is not None and hasattr(grid.model(), "row_at"):
            placed = self._select_row_object(grid, obj)
            show = getattr(widget, "_show_selected", None)
            if placed and show is not None:
                # The current row can be unchanged across a model reset, in
                # which case Qt says nothing and the pane would stay empty.
                show(grid.currentIndex())
        if not placed and domain and hasattr(widget, "_select_row_of"):
            placed = widget._select_row_of(domain)
        # A record the view no longer holds is not guessed at by position.
        by_index = not placed and obj is None and not domain

        def apply():
            self._apply_grid_state(grid, state, select=by_index)
            pane = getattr(widget, "pane", None)
            if placed or by_index:
                self._apply_grid_state(getattr(pane, "table", None),
                                       state.get("pane"))
        apply()
        # Row heights fit lazily once the view is shown again; the range
        # they settle on is only known a beat later.
        QTimer.singleShot(0, apply)

    def _record_crumb(self, row, fallback):
        """Where the record sat and what kind it is, in words -- never an
        internal kind key, and never what it says beyond its identity:

          "from: History record 8 (on screen): <identity>"
          "from: Search hit 1 → Container_5 row 2"

        The position is the row's place in the grid AS SHOWN, and says so:
        it is not the table's own row. A search hit also names the table
        row it matched, which is where it lands. A row that is not in the
        view's table (a dialog's copy, a summary card) gets the fallback
        wording."""
        label = self._labels.get(self._current, self._current)
        kind = (row or {}).get("_kind") or ""
        grid = self._state_grid(self._current) if self._current else None
        model = grid.model() if grid is not None else None
        n = None
        if model is not None and hasattr(model, "row_at"):
            for i in range(model.rowCount()):
                if model.row_at(i) is row:
                    n = i + 1
                    break
        result = (row or {}).get("_result")
        if kind == record_kinds.K_TABLE_ROW and isinstance(result, dict):
            hit = "Search hit %d" % n if n is not None else "Search hit"
            table = result.get("table") or "a table"
            ordinal = result.get("row_index")
            return ("from: %s → %s row %s" % (hit, table, ordinal)
                    if ordinal else "from: %s → %s" % (hit, table))
        if not kind and n is None:
            return "from: %s — %s" % (label, fallback)
        word = record_kinds.kind_word(kind) if kind else "record"
        if not word.lower().startswith(str(label).lower()):
            word = "%s — %s" % (label, word)
        head = ("from: %s %d (on screen)" % (word, n) if n is not None
                else "from: %s" % word)
        who = detail_fields.identity_of(row) if row else ""
        return "%s: %s" % (head, who) if who else head

    # --- navigation ------------------------------------------------------

    @property
    def nav_keys(self):
        return [k for _s, items in NAV_SECTIONS for k, _l, _c in items]

    def label_for(self, key):
        return self._labels[key]

    def caveat_for(self, key):
        return self._caveats[key]

    def menu_for_views(self):
        return self._view_menu

    def menu_for_file(self):
        return self._file_menu

    def menu_for_evidence(self):
        return self._evidence_menu

    def menu_for_export(self):
        return self._export_menu

    def go_to(self, key, crumb=None, remember=True):
        # Built (wired, and populated if evidence has loaded) the first
        # time anything navigates here (see _ensure_view_built); afterwards
        # a lookup only.
        self._ensure_view_built(key)
        if key != "browser":
            # Leaving the Table Browser cancels a row locate still running
            # there.
            self._cancel_pending_row_locate()
        previous = getattr(self, "_current", None)
        if remember and previous is not None and previous != key:
            self._nav_history.push(previous, self._current_crumb,
                                   self._capture_view_state(previous))
        self._current_crumb = crumb or ""
        self.nav_bar.set_crumb(self._current_crumb)
        if key == "browser" and crumb is None:
            # A plain visit: the locate note described an earlier drill.
            browser = self._built_widget("browser")
            if browser is not None:
                browser.set_note("")
        # Read before the switch: hiding the old page makes Qt move focus
        # into the new one.
        focus_was_in_a_view = self._focus_is_in(self.stack)
        self._unpark(self._index[key])
        self.stack.setCurrentIndex(self._index[key])
        self._current = key
        if focus_was_in_a_view:
            self._focus_view(self._page_at(self._index[key]))
        # A new screen starts at its top: an offset left by the previous
        # one cut this one's title and Back.
        self._content_scroll.verticalScrollBar().setValue(0)
        # Blocked rather than left to fire: an unblocked setCurrentRow
        # below re-triggers currentItemChanged -> _nav_changed -> go_to()
        # a second, redundant time for the SAME key (harmless on its own,
        # since Qt does not re-emit for setting an already-current row,
        # but it would also run _nav_changed's own dormant guard below
        # against a purely PROGRAMMATIC call -- go_to("dashboard") is
        # called once at startup, before any evidence is open, and must
        # never be second-guessed the way a genuine click is).
        self.nav.blockSignals(True)
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) == key:
                self.nav.setCurrentRow(i)
                break
        self.nav.blockSignals(False)
        # QListWidget's own selection (setCurrentRow above) already moves
        # theme.py's QSS-owned selected background/left-bar; this is the
        # other half -- the NavRow's own icon colour, bold label and count
        # colour (sidebar.py's NavRow.set_selected), which QSS has no way
        # to reach because it lives inside an already-painted QPixmap.
        self.sidebar.set_current(key)
        # Ctrl+E / Export this view is enabled only where there IS a view
        # to export -- an enabled menu item over the Dashboard would be
        # a promise with no handler.
        has_grid = (getattr(self._page_at(self._index[key]), "table", None)
                    is not None)
        self.export_this_view_action.setEnabled(has_grid)
        if hasattr(self, "reset_columns_action"):
            self.reset_columns_action.setEnabled(has_grid)
        # Cleared: every view states its caveat above its grid, so the
        # status bar does not repeat it.
        self._set_status_message("")
        if hasattr(self, "back_action"):
            self._sync_back_controls()

    def _reset_column_layout(self):
        """View > Reset column layout, for the view on screen. Saved at
        close like any other layout, so the defaults are what comes back."""
        table = getattr(self._page_at(self._index[self._current]),
                        "table", None)
        reset = getattr(table, "reset_column_layout", None)
        if not callable(reset):
            return
        reset()
        self._set_status_message(
            "%s: columns reset to their default widths, order and "
            "visibility." % self._labels.get(self._current, self._current))

    @staticmethod
    def _focus_is_in(container):
        focus = QApplication.focusWidget()
        while focus is not None:
            if focus is container:
                return True
            focus = focus.parentWidget()
        return False

    def _focus_view(self, page):
        """Give keyboard focus to what a view is FOR: its focus_target()
        when it names one (Search: the keyword box), else its grid, so
        arrows, Enter and Ctrl+C work at once. Left to Qt, focus fell on
        the first control in the page -- Location's "Exact" grouping
        button, Timeline's "UTC" clock -- where a stray Space changed the
        view and the focus ring read as the choice in force. A page with
        neither (the Dashboard) takes focus itself, so none is left on a
        control the examiner cannot see."""
        target = getattr(page, "focus_target", None)
        target = target() if callable(target) else getattr(page, "table", None)
        if target is None:
            page.setFocusPolicy(Qt.ClickFocus)
            target = page
        target.setFocus(Qt.OtherFocusReason)

    @property
    def current_key(self):
        return self._current

    def _nav_changed(self, item, prev):
        """The nav list's currentItemChanged handler, reached only by a
        click or keyboard selection on the nav list itself (go_to() blocks
        the signal for its own selection updates). Keyboard shortcuts and
        drill-downs call go_to() directly.

        NavRow.setEnabled(False) (sidebar.py's set_dormant) dims a row's
        contents but does not stop QListWidget's hit-testing, so a click
        arrives here before evidence is open, when there is nothing behind
        FirstRunView to show (content_stack shows the view stack only after
        _on_evidence_loaded). The status bar answers "Load a database
        first" rather than changing self._current invisibly.
        """
        if item is None or not item.data(Qt.UserRole):
            return
        if not self._ever_loaded:
            self.nav.blockSignals(True)
            self.nav.setCurrentItem(prev)
            self.nav.blockSignals(False)
            self._set_status_message(_LOAD_FIRST_MESSAGE)
            return
        self.go_to(item.data(Qt.UserRole))

    def _guarded_go_to(self, key):
        """The not-yet-loaded guard _nav_changed applies to a nav click,
        applied to the Export menu's "Export & Report…" action
        (Ctrl+Shift+E), which calls go_to("export") directly and is enabled
        from construction (export_this_view_action is gated by go_to()).
        Without it the nav selection would move to "Export & Report" while
        content_stack stayed on FirstRunView.
        """
        if not self._ever_loaded:
            self._set_status_message(_LOAD_FIRST_MESSAGE)
            return
        self.go_to(key)

    def _drill_to_domain(self, key, row):
        """Every domain drill -- History's Domain cell, the Dashboard's
        Top Domains card, a Findings Beaconing domain -- lands on Domains
        with that domain selected and its records listed, live and
        carved, from every container. Any other key just navigates."""
        domain = (row or {}).get("Domain")
        if key != "domains" or not domain:
            self.go_to(key)
            return
        view = self._ensure_view_built("domains")
        self.go_to("domains", crumb="from: %s \u2014 domain %s" % (
            self._labels.get(self._current, self._current), domain))
        if not view.show_domain(domain):
            self._set_status_message(
                "No domain named %s in this exhibit's Domains list." % domain)

    def _drill_container_to_browser(self, key, row):
        """Open the Table Browser on a container's table. Used by
        ContainersView (a click on a container's name) and HeadersView (the
        Container cell and the pane's "Browse Container_N" button), instead
        of the generic `lambda k, _row: self.go_to(k)`.
        ese_parser._load_containers names every container's table
        f"Container_{cid}" (meta["TableName"]), so the name is computed
        here. TableBrowserView.select_table() states "no such table" when
        that table does not exist (HasTable False), so nothing is checked
        first.

        The container id is read from whichever key the row carries: "Id"
        for a ContainersView row (container_rows_from_parser), "ContainerId"
        for a HeadersView row (headers_loader.py).

        Written on `key`, like _drill_to_domain: a table is selected only
        when the target is "browser"; any other key just navigates.
        """
        if key == "browser":
            # Built here, as History is in _drill_domain_to_history: the
            # table is selected on the widget before navigating, and the
            # Table Browser may not have been opened this session.
            browser = self._ensure_view_built("browser")
            cid = row.get("Id")
            if cid is None:
                cid = row.get("ContainerId")
            if cid is not None:
                browser.select_table("Container_%d" % cid)
                self.go_to(key, crumb="from: %s \u2014 Container_%d" % (
                    self._labels.get(self._current, self._current), cid))
                return
        self.go_to(key)

    def _drill_iocs(self, key, row):
        """FindingsView's drillRequested handler.

        One signal reaches two handlers: EntryId gaps' Container
        column names a table (_drill_container_to_browser, key "browser")
        and Beaconing's Domain column names a domain
        (_drill_to_domain, key "domains"); see views/iocs.py for the other
        segments. This dispatches to the handler that matches, so go_to()
        runs once, and navigates plainly for any other key.
        """
        if key == "browser":
            self._drill_container_to_browser(key, row)
        elif key == "domains":
            self._drill_to_domain(key, row)
        else:
            self.go_to(key)

    def _rescan_iocs(self, text):
        """FindingsView's watchlistScanRequested handler: the examiner
        typed a watchlist and pressed Scan (or Enter). Re-runs only the
        ioc_hits segment; the other five do not depend on the watchlist
        (see iocs_loader.py).

        A no-op before evidence is open, or for a parser that cannot
        enumerate entries, as in every _push_*_state method: the watchlist
        box can be typed in before any exhibit is loaded.
        """
        widget = self._built_widget("iocs")
        if (widget is None or self._parser is None
                or not hasattr(self._parser, "all_entries")):
            return
        carved = (self._domains_carved_entries()
                 if self._recovery_engine is not None else ())
        terms = split_watchlist(text)
        note = (_iocs_scan_note(len(carved))
               if self._recovery_engine is not None
               else self._not_scanned(IOCS_NOT_SCANNED_NOTE))
        widget.set_records_for(
            "ioc_hits", derived.finding(self._parser, self._recovery_engine,
                                        "ioc_hits", tuple(terms)),
            note=note)

    def _drill_table_to_browser(self, key, row):
        """Like _drill_container_to_browser, for a row that names a table
        directly, as a search hit does. A hit in MSysObjects, PartitionsEx
        or LeakFiles has no container id to compute a name from.
        select_table() states "no such table" rather than failing, so the
        name is not checked first.
        """
        if key == "browser" and row_locator.source_row(row) is not None:
            self.show_in_database_table(row)
            return
        if key == "browser":
            browser = self._ensure_view_built("browser")
            name = row.get("Table")
            if name:
                browser.select_table(str(name))
                self.go_to(key, crumb="from: Search \u2014 table %s" % name)
                return
        self.go_to(key)

    def _open_search_hit(self, row):
        """Enter / Ctrl+Enter / "Open this row" on a search hit: a
        recovered hit IS a record and opens as one; a database hit is a
        raw table row and lands on that row in Table Browser."""
        if isinstance(row.get("_record"), dict):
            return self._show_record_detail(row)
        return self.show_in_database_table(row)

    def search_for(self, keyword):
        """"Search the database for this value", from any record table's
        context menu. Public: it is the entry point for finding a value
        everywhere.

        Always at full scope, so a scope left from a previous search never
        narrows it to one table.
        """
        keyword = str(keyword or "").strip()
        if not keyword:
            self._set_status_message(
                "That cell holds no value to search the database for.")
            return
        view = self._ensure_view_built("search")
        view.keyword_box.setText(keyword)
        view.scope_combo.setCurrentIndex(0)
        self.go_to("search")
        self._start_search(keyword, "")

    def status_message(self):
        return self._status_message.full_text()

    def _set_status_message(self, text):
        """The path every caveat and status message goes through (see
        _ElidingStatusLabel)."""
        self._status_message.set_full_text(text)

    # --- status bar: the trailing DB-summary segment ----------------------

    def _db_summary_html(self, info):
        """The "993 records | 83 tables | 34 containers | Dirty shutdown"
        segment, as rich text.

        `info` is WebCacheParser.get_database_info(), or None before any
        exhibit is opened. total_entries is every record the parser holds
        (History, Cookies, HSTS, the certificate store and the rest), a
        different figure from the History row count in the status bar's
        left-hand message.

        db_state 2 is a dirty shutdown, the normal state for a live-acquired
        exhibit, and the reason this tool reads with dissect.esedb rather
        than running ESE soft recovery (see SCOPE_STATEMENTS in
        evidence_model.py). It is coloured amber, and the word "Dirty" is in
        the text as well.
        """
        if not info:
            return ""
        state_text = info.get("db_state_text") or ""
        if info.get("db_state") == 2:
            state_text = "<span style='color:%s'>%s</span>" % (
                theme.color("warn").name(), state_text)
        split = record_counts.split_text(
            record_counts.counts(
                self._parser,
                derived.deleted_records(self._parser, self._recovery_engine)
                if self._recovery_engine is not None else None),
            running=(self._recovery_pages
                     if getattr(self, "_recovery_state", "") == "running"
                     else None))
        return ("%s&nbsp;&nbsp;|&nbsp;&nbsp;%s tables&nbsp;&nbsp;|"
                "&nbsp;&nbsp;%s containers&nbsp;&nbsp;|&nbsp;&nbsp;%s"
                % (html.escape(split),
                   format(info.get("table_count", 0), ","),
                   format(info.get("container_count", 0), ","), state_text))

    def _refresh_db_summary_widget(self):
        """Apply the current theme's colours to the database-summary label
        and regenerate its text from the last info (self._db_summary_info,
        set by _on_evidence_loaded).

        Called at construction (info None: an empty label) and by
        _refresh_drawn_theme on every theme switch, because the colours are
        written into the label's HTML text, which a stylesheet change does
        not update.
        """
        self._db_summary_label.setStyleSheet(
            "font-family: 'Cascadia Mono', Consolas, monospace; "
            "font-size: 11px; color: %s;" % theme.color("muted").name())
        self._db_summary_label.setText(
            self._db_summary_html(self._db_summary_info))

    # --- explain -----------------------------------------------------------

    def _explain_value(self, record, column_key):
        """F1, and the context menu's "Explain this value": both emit
        RecordsTable.explainRequested (records_table.py).

        Explains where a record came from, for a live record and a carved
        one (file, offset, page, method, confidence), in an ExplainDialog
        (a QDialog, so Copy does not close it).

        The origin line comes from detail_fields.origin_line, as in the
        record detail dialog, rather than provenance.describe_origin()
        directly: describe_origin defaults to "Live record", which is false
        for a row that is not a record (a Timeline period or a Location
        place, record_kinds.AGGREGATES), whose members may be carved.
        """
        ExplainDialog(self, self._explain_text_for(record, column_key)).exec()

    def _show_help(self, title, text, table=None):
        """A Help page: the same copyable ExplainDialog F1 uses, modeless,
        kept alive like the record dialogs. Text only -- no URL is opened."""
        if table is None:
            table = all("\t" in line for line in text.split("\n"))
        dialog = ExplainDialog(self, text, table=table)
        dialog.setWindowTitle(title)
        dialog.setModal(False)
        dialog.destroyed.connect(
            lambda *_a, d=dialog: self._forget_record_dialog(d))
        self._detail_dialogs.append(dialog)
        dialog.show()
        return dialog

    def _column_for(self, column_key):
        widget = self.stack.currentWidget()
        for table in (widget.findChildren(RecordsTable) if widget else []):
            model = table.model()
            if model is None:
                continue
            for column in model.columns:
                if column.key == column_key:
                    return column
        return None

    def _explain_text_for(self, record, column_key):
        value = record.get(column_key)
        column = self._column_for(column_key)
        label = column.label if column is not None else column_key
        text = "Column: %s\nValue: %s\n\n" % (
            label, "" if value is None else str(value))
        if value is None or value == "":
            carved = str(record.get("Origin") or "").startswith("Carved")
            field = (column.field if column is not None and column.field
                     else detail_fields.provenance_field_for(
                         column_key, record.get("_kind")))
            text += help_texts.explain_empty(label, field, carved) + "\n\n"
        return text + detail_fields.origin_line(record)

    # --- the record detail dialog -----------------------------------------

    def _show_record_detail(self, record):
        """A record was activated on any record table.

        The table reports only that a record was activated; the shell
        decides what that opens, as for explainRequested. RecordDetailDialog
        lives in shell/ because a view may not import another view's dialog
        (test_structure.py) and a widget may not reach the engine through
        it.

        Modeless and stacking: each activation gets its own dialog, and the
        one it was opened from stays behind it, so no Back button is
        needed.
        """
        if not isinstance(record, dict):
            return None
        # The exhibit path and the opening hashes come from HERE, not from
        # the row: a carved record names its source file by basename, so
        # the "Bytes at the carve offset" tab can only be resolved against
        # the exhibit this window currently has open. Passed on to every
        # dialog a drill opens, too -- dialogs stack, and a record reached
        # from another dialog must be able to read the same exhibit.
        dialog = RecordDetailDialog(
            record, self, db_path=self._exhibit_path(),
            evidence_set=getattr(self, "_evidence_set", None),
            case=self._case,
            author=self._case_meta().get("examiner", ""))
        dialog.caseNotesChanged.connect(self._case_notes_changed)
        dialog.recordRequested.connect(self._show_record_detail)
        dialog.explainRequested.connect(self._explain_text)
        dialog.showInTableRequested.connect(self.show_in_database_table)
        # Removed on `destroyed`, not on close: the dialog sets
        # WA_DeleteOnClose, so `destroyed` fires once, after Qt has finished
        # with it. Otherwise the list would keep every record opened this
        # session alive, and the parser with them.
        dialog.destroyed.connect(
            lambda *_a, d=dialog: self._forget_record_dialog(d))
        self._detail_dialogs.append(dialog)
        dialog.show()
        return dialog

    # --- from a record to its raw row --------------------------------

    def show_in_database_table(self, row):
        """Table Browser on the record's table and page with the row
        selected (live); the record's bytes (carved); the table with a
        note, nothing selected (deleted stub).

        A live row in a large table is located off the GUI thread (see
        row_locate_runner): the browser opens on the table at once with a
        "Locating..." note, and lands on the row when the worker answers."""
        ref = row_locator.source_row(row)
        if ref is None:
            return None
        if ref.kind == row_locator.CARVED:
            dialog = self._show_record_detail(row)
            if dialog is not None:
                dialog.reveal_bytes(tab=blob_source.CARVE_TAB_LABEL)
            return dialog
        browser = self._ensure_view_built("browser")
        # Shown FIRST, so the row is centred against the real viewport.
        self.go_to("browser", crumb=self._record_crumb(row, "record"))
        # A locate still running is cancelled.
        self._cancel_pending_row_locate()
        if ref.kind == row_locator.ORDINAL:
            ordinal = ref.key["Row #"] - 1
            if browser.show_row(ref.table, ordinal):
                browser.set_note(row_locator.landed_note(ref, ordinal))
            else:
                browser.select_table(ref.table)
                browser.set_note(row_locator.not_found_note(ref))
        elif ref.kind == row_locator.DELETED:
            browser.select_table(ref.table)
            browser.set_note(row_locator.deleted_note(ref))
        elif row_locate_runner.needs_worker(self._parser, ref.table):
            browser.select_table(ref.table)
            browser.set_note(row_locator.locating_note(ref))
            self._start_row_locate(ref, browser)
        else:
            ordinal = row_locator.locate(self._parser, ref)
            if ordinal is not None and browser.show_row(ref.table, ordinal):
                browser.set_note(row_locator.landed_note(ref, ordinal))
            else:
                browser.select_table(ref.table)
                browser.set_note(row_locator.not_found_note(ref))
        return browser

    def _cancel_pending_row_locate(self):
        """Cancel a pending row locate, as _cancel_pending_search does:
        cancel() is only a request, so the signal is disconnected as well
        and the request (which holds its parser) is dropped. A late answer
        reaches nothing."""
        self._row_locate_request = None
        old = getattr(self, "_row_locate_runner", None)
        self._row_locate_runner = None
        if old is None:
            return
        old.cancel()
        try:
            old.located.disconnect()
        except (RuntimeError, TypeError):
            pass

    def _start_row_locate(self, ref, browser):
        self._cancel_pending_row_locate()
        runner = row_locate_runner.RowLocateRunner(self)
        runner.located.connect(self._on_row_located)
        self._row_locate_runner = runner
        self._row_locate_request = (ref, self._parser)
        runner.start(
            ref, self._exhibit_path(),
            dict(getattr(getattr(self, "_evidence_set", None), "hashes", None)
                 or {}) or None,
            browser._page_size,
            # the worker's parser never parses entries;
            # the MSHist clock travels with the request.
            clock=local_clock.clock_snapshot(
                getattr(self._parser, "all_entries", None),
                getattr(self._parser, "derived_tz_offset_seconds", None)))

    def _on_row_located(self, ref, ordinal, page):
        pending = getattr(self, "_row_locate_request", None)
        # Superseded by a later request, or by a different exhibit.
        if pending is None or pending[0] is not ref or pending[1] is not self._parser:
            return
        self._row_locate_request = None
        browser = self._ensure_view_built("browser")
        # The examiner has since picked another table or paged: leave them
        # where they are. Both clear the "Locating..." note.
        if (browser._current_table != ref.table
                or browser._note_label.text() != row_locator.locating_note(ref)):
            return
        if ordinal is not None and browser.show_row(ref.table, ordinal,
                                                    page=page):
            browser.set_note(row_locator.landed_note(ref, ordinal))
        else:
            browser.set_note(row_locator.not_found_note(ref))

    def _exhibit_path(self):
        """The database currently open, or "".

        hasattr-guarded for the same reason every other parser access in
        this module is: the test suite and the no-evidence state both put
        objects here that are not a full WebCacheParser, and a viewer
        that raised rather than simply offering no carve window would
        take the whole dialog with it.
        """
        return getattr(self._parser, "db_path", "") or ""

    def _show_blob(self, label, data):
        """A Table Browser cell's bytes, in the viewer a record's blob uses.

        Registered in the same list as the record dialogs, so opening
        another exhibit closes it: it holds bytes read from the parser that
        is about to be replaced.
        """
        source = blob_source.MemoryBlob(label, data, label)
        dialog = BlobViewerDialog(
            source, self, context=self._blob_context(),
            db_path=self._exhibit_path(),
            evidence_set=getattr(self, "_evidence_set", None))
        dialog.destroyed.connect(
            lambda *_a, d=dialog: self._forget_record_dialog(d))
        self._detail_dialogs.append(dialog)
        dialog.show()
        return dialog

    def _show_table_row(self, payload):
        """One raw table row, read vertically.

        Tracked in _detail_dialogs like every detail dialog: it holds the
        row's cells by reference from the parser, so opening another exhibit
        closes it rather than keeping the previous parser alive with a row
        from another database on screen.
        """
        dialog = TableRowDialog(
            payload.get("columns") or [], payload.get("cells") or [],
            parent=self,
            table=payload.get("table") or "",
            row_number=payload.get("row_number") or 0,
            row_count=payload.get("row_count") or 0,
            db_path=self._exhibit_path(),
            evidence_set=getattr(self, "_evidence_set", None))
        dialog.destroyed.connect(
            lambda *_a, d=dialog: self._forget_record_dialog(d))
        self._detail_dialogs.append(dialog)
        dialog.show()
        return dialog

    def _blob_context(self):
        # Only ever reached via _show_blob, itself only reachable from
        # TableBrowserView's own blobRequested signal -- Table Browser is
        # necessarily already built and on screen for that signal to have
        # fired at all, so _built_widget (never _ensure_view_built) is
        # the correct, non-forcing lookup here.
        view = self._built_widget("browser")
        name = getattr(view, "_current_table", None)
        return "Table %s" % name if name else ""

    def _forget_record_dialog(self, dialog):
        self._detail_dialogs = [d for d in self._detail_dialogs
                                if d is not dialog]

    def _close_record_dialogs(self):
        """Called before self._parser is replaced for a new exhibit.

        An open dialog holds `_record` references into the parser that
        produced them. Closing them releases the previous exhibit's parser
        and blobs, and removes rows from a database that is no longer the
        one open.
        """
        for dialog in list(self._detail_dialogs):
            try:
                dialog.close()
            except RuntimeError:
                # Its C++ half is already gone; there is nothing to close.
                pass
        self._detail_dialogs = []

    def _explain_text(self, text):
        """The detail dialog's F1, landing in the SAME ExplainDialog the
        grid's F1 uses. The dialog emits composed text rather than
        constructing the dialog itself, because this module imports it and
        importing back would be a cycle."""
        ExplainDialog(self, text).exec()

    # --- evidence ----------------------------------------------------------

    def open_evidence(self):
        """File ▸ Open Evidence… / Ctrl+O. A native file dialog names the
        database; OpenEvidenceDialog lists what will be read and nothing is
        read before Open is pressed.

        Seeded with settings.py's own "last_evidence_dir" -- "" (Qt's own
        default) on a fresh install where nothing has ever been chosen,
        never a path this method invents itself.
        """
        path, _name_filter = QFileDialog.getOpenFileName(
            self, "Open evidence", settings.get("last_evidence_dir", ""),
            "WebCache database (WebCacheV01.dat);;All files (*)")
        if not path:
            return
        # The chosen directory is remembered whether or not
        # OpenEvidenceDialog (below, via _open_evidence_at) is accepted, as
        # an ordinary file dialog remembers it.
        settings.save(last_evidence_dir=os.path.dirname(path))
        self._open_evidence_at(path)

    def _open_evidence_at(self, path):
        dlg = OpenEvidenceDialog(path, self)
        # The worker is unparented (consent.py), so deleteLater() is safe
        # however far a hash got before Cancel.
        accepted = dlg.exec() == QDialog.Accepted
        evidence_set = dlg.evidence_set if accepted else None
        self._recover_after_load = bool(accepted and dlg.recover_deleted)
        dlg.deleteLater()
        if evidence_set is None:
            self._set_status_message(
                "Evidence not opened — cancelled before anything was "
                "hashed or parsed.")
            return
        self._evidence_set = evidence_set
        # A load in progress must never deliver its rows under a newer
        # exhibit. open_evidence_action.setEnabled(False) below closes the
        # menu and Ctrl+O routes (QAction.trigger() does nothing while
        # disabled). This covers anything that reaches _open_evidence_at()
        # without the action (a direct open_evidence() call, a test):
        # cancel() is a best-effort request (see EvidenceLoader.cancel), so
        # a cancelled worker can still finish and emit; disconnecting its
        # signals means a late loaded/failed reaches nothing.
        self._cancel_pending_load()
        # A recovery scan in progress belongs to the old exhibit, and its
        # result must not deliver carved rows for a database no longer
        # open (see _cancel_pending_recovery).
        self._cancel_pending_recovery()
        # A search in progress belongs to the exhibit being replaced; its
        # hits name tables and row ordinals in that database, so it is
        # cancelled the same way.
        self._cancel_pending_search()
        # A row being located belongs to the exhibit being replaced too,
        # and its worker holds that file open.
        self._cancel_pending_row_locate()
        self.open_evidence_action.setEnabled(False)
        # the card on screen says what is opening, not "No evidence
        # open" -- the name from the examiner's own chosen path, as plain
        # text.
        self.first_run.set_opening(os.path.basename(path))
        self._begin_load_busy_ui("Parsing %s…" % os.path.basename(path))
        loader = EvidenceLoader(self)
        self._loader = loader  # kept alive for the duration of this load
        loader.progress.connect(self._on_load_progress)
        loader.loaded.connect(
            lambda result: self._on_evidence_loaded(result, evidence_set))
        loader.failed.connect(self._on_evidence_failed)
        # evidence_set.hashes was computed by the Open dialog; passing it
        # lets WebCacheParser.open() skip hashing the exhibit again.
        loader.load(path, evidence_set.hashes)

    # --- evidence by drag and drop ----------------------------------------
    #
    # A drop only chooses a file; it carries no authority to read one.
    # dropEvent ends in the call open_evidence() ends in,
    # _open_evidence_at(), so the Open Evidence dialog, the hashing and the
    # parse follow unchanged, and declining the dialog after a drop opens,
    # hashes and parses nothing. drop_target.classify() reads nothing
    # either: it decides by name alone (isdir, splitext, one listdir per
    # dropped folder), as evidence_scope() does.
    #
    # The whole window is the drop target, not the first-run card, so
    # another exhibit can be dropped while one is open.

    #: Refusing a drop during a load, in the status bar's words. The Open
    #: Evidence action is disabled for the whole load and both Open Database
    #: buttons follow it (_sync_open_buttons_enabled), so a drop is refused
    #: at the same moments.
    BUSY_DROP_REFUSAL = ("An exhibit is already being opened — wait for "
                         "that to finish before dropping another.")

    def _disarm_child_drop_targets(self, root):
        """Stop widgets inside the window from taking a dropped exhibit.

        Qt does not pass a drag up the widget tree: the drop goes to the
        first widget under the cursor whose acceptDrops() is true, and if it
        ignores the event the parent never sees it. A QLineEdit accepts
        drops by default (for text), and every view's filter box, the search
        bar and the watchlist editor are QLineEdits, so they are disarmed
        here and per view in _ensure_view_built. Text can then no longer be
        dragged into a filter box.

        Only widgets of this window: a dialog or popup is its own window,
        not in the path of a drag onto this one.
        """
        for child in [root] + root.findChildren(QWidget):
            if child is not self and child.window() is self \
                    and child.acceptDrops():
                child.setAcceptDrops(False)

    def _dropped_paths(self, event):
        """The local files a drag event carries -- [] for anything else.

        Dragged text, a dragged web link, a drag from an application that
        offers no file at all: each has to read as "nothing droppable",
        never as a path, because a path is the one thing the caller acts
        on. Returning [] is also what makes the drag fall through
        un-accepted, so Windows shows its no-entry cursor instead of
        promising a drop this window cannot honour.
        """
        return drop_target.local_paths(event.mimeData())

    def eventFilter(self, watched, event):
        """Keep drop_overlay the size of the central widget.

        Filters the central widget's resize rather than overriding
        MainWindow.resizeEvent, which runs before the layout has moved the
        central widget, so an overlay sized there would lag by one resize.
        """
        if watched is self.centralWidget() and event.type() == QEvent.Resize:
            self.drop_overlay.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def _show_drop_feedback(self, paths):
        """Show what letting go would do, while the drag is in progress.

        Safe during the drag because drop_target decides by name and reads
        nothing (isdir, splitext, one listdir per dropped folder).

        A refusal is shown in drop_target's own words, so the prompt and
        the status-bar message that follows give the same reason.
        """
        if self._drop_pending or not self.open_evidence_action.isEnabled():
            self.drop_overlay.show_for("refused", self.BUSY_DROP_REFUSAL)
            return
        verdict = drop_target.classify(paths)
        if verdict.path:
            self.drop_overlay.show_for(
                "ready", "Open %s" % os.path.basename(verdict.path),
                OPEN_PROMISE)
        else:
            self.drop_overlay.show_for("refused", verdict.reason)

    def dragEnterEvent(self, event):
        """Say whether the window will take this drag at all.

        Accepted for any drag carrying local files, INCLUDING ones that
        will turn out to be refused (a .png, five databases at once). A
        refusal an examiner can read is worth more than a no-entry cursor
        that says only "no", and being accepted here is what lets the
        window put the reason on screen at all.
        """
        paths = self._dropped_paths(event)
        if not paths:
            event.ignore()
            return
        self._show_drop_feedback(paths)
        # setDropAction(CopyAction), never acceptProposedAction(): the
        # proposed action is the source's, and for an external drag Qt
        # proposes MoveAction while Shift is held. Accepting a Move tells the
        # Windows shell the target took the data, and the shell then deletes
        # the source file. This window only reads a dropped path, so Copy is
        # the only correct answer.
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dragMoveEvent(self, event):
        """Re-confirmed on every move, because Qt asks again.

        A drag that is accepted on enter but not on move ends with the
        platform showing a no-entry cursor and never delivering the drop
        -- the same dead target, one event later. The verdict is NOT
        recomputed here: this fires continuously for the whole of a drag,
        and nothing about what is being dragged changes between enter and
        drop.
        """
        if not self._dropped_paths(event):
            event.ignore()
            return
        # setDropAction(CopyAction), never acceptProposedAction(): the
        # proposed action is the source's, and for an external drag Qt
        # proposes MoveAction while Shift is held. Accepting a Move tells the
        # Windows shell the target took the data, and the shell then deletes
        # the source file. This window only reads a dropped path, so Copy is
        # the only correct answer.
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event):
        """The drag went elsewhere; the prompt goes with it."""
        self.drop_overlay.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        """The drop itself: name an exhibit, then hand it to the gate."""
        # Hidden first, before the Open Evidence dialog opens: on the
        # accepted path this method does not return while the window is
        # idle, and a prompt left up would sit over the dialog's parent
        # window and then over the opened exhibit.
        self.drop_overlay.hide()
        paths = self._dropped_paths(event)
        if not paths:
            event.ignore()
            return
        # setDropAction(CopyAction), never acceptProposedAction(): the
        # proposed action is the source's, and for an external drag Qt
        # proposes MoveAction while Shift is held. Accepting a Move tells the
        # Windows shell the target took the data, and the shell then deletes
        # the source file. This window only reads a dropped path, so Copy is
        # the only correct answer.
        event.setDropAction(Qt.CopyAction)
        event.accept()
        # Tested in the same order as _show_drop_feedback, so the status bar
        # shows what the prompt showed when the examiner let go. During a
        # load that is the busy refusal, whatever was dropped.
        if self._drop_pending or not self.open_evidence_action.isEnabled():
            self._set_status_message(self.BUSY_DROP_REFUSAL)
            # ignore(), not the accept above: a refusal must reach the drag
            # source as "nothing happened here". Left accepted, a shift-drag
            # of a file this window just turned down would still have the
            # shell delete it.
            event.ignore()
            return
        verdict = drop_target.classify(paths)
        if not verdict.path:
            # Refused with a stated reason rather than passed to the
            # parser.
            self._set_status_message(verdict.reason)
            event.ignore()
            return
        # The directory is remembered when a file is chosen, whatever the
        # dialog's answer, as open_evidence() does for the file dialog, so
        # the next Ctrl+O starts there.
        settings.save(last_evidence_dir=os.path.dirname(verdict.path))
        # THE GATE OPENS ON THE NEXT TURN OF THE LOOP, NOT HERE. On
        # Windows this method is called synchronously from inside
        # IDropTarget::Drop, which is itself inside the SOURCE
        # application's DoDragDrop -- Explorer, whose own message loop is
        # in that call and does not resume until this returns. A modal
        # OpenEvidenceDialog here freezes Explorer for as long as the examiner
        # spends on the gate plus the SHA-256 of the exhibit: minutes of a
        # dead File Explorer window on a large one, and it reads as
        # Windows' fault rather than this application's. Deferring costs
        # the examiner nothing perceivable and changes only who waits.
        #
        # _drop_pending is the guard that deferral would otherwise
        # remove. Refusing a second drop mid-open leans on
        # open_evidence_action being disabled, and _open_evidence_at only
        # does that once the dialog has been ACCEPTED -- so between this
        # line and the deferred call there is a window in which a second
        # drop would find every guard still open. The flag closes it
        # synchronously, here, where the second drop is delivered.
        self._drop_pending = True
        QTimer.singleShot(0, lambda: self._open_dropped_evidence(verdict.path))

    def _open_dropped_evidence(self, path):
        """The deferred half of dropEvent -- see its comment for why.

        try/finally, not a clear at the end: _open_evidence_at can raise
        (an OpenEvidenceDialog that fails to build, a settings path that
        has gone away), and a _drop_pending left set would refuse every
        further drop for the life of the window with a message about a
        load that is not running.
        """
        try:
            self._open_evidence_at(path)
        finally:
            self._drop_pending = False

    # --- busy state: progress bar, elapsed time, cancel -------------------

    def _begin_load_busy_ui(self, message):
        """Called once, right as a load starts. See __init__ for why the
        progress bar is indeterminate rather than a fabricated percentage."""
        self._busy_for = "load"
        self._load_elapsed.start()
        self._load_last_message = message
        self._set_status_message(message)
        self._load_progress.setVisible(True)
        self._load_cancel_button.setVisible(True)
        self._load_cancel_button.setEnabled(True)
        self._load_status_timer.start()

    def _end_load_busy_ui(self):
        """Called on EVERY exit path -- success, failure, and cancel -- so
        none of them can leave a stale progress bar or Cancel button
        showing for an operation that already ended."""
        self._load_status_timer.stop()
        self._load_progress.setVisible(False)
        self._load_cancel_button.setVisible(False)
        self.first_run.set_idle()
        if self._busy_for == "load":
            self._busy_for = None

    def _on_load_progress(self, message):
        """The worker's own progress text -- see
        EvidenceLoadWorker._check_progress's docstring for what it does
        and does not report. Routed through _refresh_load_elapsed rather
        than straight to the status bar so the elapsed-time suffix is
        never stale the instant a new message arrives."""
        self._load_last_message = message
        self._refresh_load_elapsed()

    def _refresh_load_elapsed(self):
        """Ticks on its own 500 ms timer, independent of the worker's
        progress signal, so the elapsed time keeps moving while the parser
        is quiet (see EvidenceLoadWorker on the modern-tables and
        count_all_tables phases)."""
        seconds = max(0, self._load_elapsed.elapsed() // 1000)
        self._set_status_message(
            "%s (%dm%02ds elapsed)"
            % (self._load_last_message, seconds // 60, seconds % 60))
        self.first_run.set_elapsed(
            "%dm%02ds elapsed" % (seconds // 60, seconds % 60))

    def _cancel_current_busy_operation(self):
        """The status bar's one Cancel button, shared by the evidence load,
        the recovery scan and exports (see __init__), routed to whichever is
        using it. self._busy_for is set whenever _begin_load_busy_ui,
        _begin_recovery_busy_ui or _start_export shows the button."""
        if self._busy_for == "recovery":
            self._cancel_current_recovery()
        elif self._busy_for == "export":
            self._cancel_current_export()
        elif self._busy_for == "search":
            self._cancel_current_search()
        else:
            self._cancel_current_load()

    def _cancel_current_load(self):
        """Cancel the load through _cancel_pending_load(), which requests
        interruption and disconnects every loader signal, so a result
        arriving after the cancel (cancel is a best-effort request; see
        EvidenceLoader.cancel) delivers no rows or status message.
        """
        self._cancel_pending_load()
        self._end_load_busy_ui()
        self.open_evidence_action.setEnabled(True)
        self._set_status_message(
            "Evidence load cancelled — nothing was parsed to completion.")

    def _cancel_pending_load(self):
        """Stop whatever a previous _open_evidence_at call left running,
        before a new load starts. Safe on the first open and when the
        previous load has finished: cancelling a stopped worker and
        disconnecting fired signals do nothing."""
        old = getattr(self, "_loader", None)
        if old is None:
            return
        old.cancel()
        for sig in (old.loaded, old.failed, old.progress):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                # Nothing connected any more, or the loader's C++ side is
                # already gone -- either way there is nothing left to cut.
                pass

    # --- pushing evidence/recovery state into a view -----------------------
    #
    # One method per view, each deriving the view's current state from
    # self._parser/self._recovery_engine and the cached self._live_*/
    # self._dashboard_live_stats/self._location_* fields, so the same method
    # gives the same result whether it runs after a load, after a recovery
    # scan, or for a view built later by _ensure_view_built. Each does
    # nothing (_built_widget) for a view not yet built, so loading evidence
    # never builds views no one has opened.

    def _push_dashboard_state(self):
        widget = self._built_widget("dashboard")
        if widget is None:
            return
        live = self._dashboard_live_stats
        engine = self._recovery_engine
        recovery_rows = (derived.deleted_records(self._parser, engine)
                         if engine is not None else None)
        cached = (live is not None and self._parser is not None
                  and hasattr(self._parser, "all_entries")
                  and live is derived.dashboard_live(self._parser))
        if live is None:
            summary = None
        elif cached:
            summary = derived.case_summary(self._parser, engine,
                                           self._recovery_state)
        else:
            summary = dashboard_data.case_summary(
                self._parser, recovery_rows,
                recovery_state=self._recovery_state)
        if recovery_rows is not None and live is not None:
            merged = (derived.dashboard_merged(self._parser, engine) if cached
                      else dashboard_data.merge_recovered_into_stats(
                          live, recovery_rows))
            if merged is not None:
                widget.set_data(merged, summary=summary)
                return
        widget.set_data(live, summary=summary)

    def _push_integrity_state(self):
        widget = self._built_widget("integrity")
        if widget is not None:
            widget.set_data(self._db_summary_info)

    def _push_history_state(self):
        widget = self._built_widget("history")
        if widget is None:
            return
        if self._recovery_engine is not None:
            carved_rows = derived.carved_history(self._parser, self._recovery_engine)
            merged = self._live_history_rows + carved_rows
            note = "%s live, %s recovered" % (
                format(len(self._live_history_rows), ","), format(len(carved_rows), ","))
            widget.set_records(merged, note=note)
        else:
            widget.set_records(self._live_history_rows,
                               note=self._not_scanned(LIVE_ONLY_NOTE))
        self._restore_column_state("history", widget.table)

    def _push_downloads_state(self):
        widget = self._built_widget("downloads")
        if widget is None:
            return
        if self._recovery_engine is not None:
            carved_fa_rows = derived.carved_file_access(self._parser, self._recovery_engine)
            carved_dl_rows = derived.carved_downloads(self._parser, self._recovery_engine)
            merged_fa = self._live_file_access_rows + carved_fa_rows
            merged_dl = self._live_download_rows + carved_dl_rows
            fa_note = file_access_note(
                len(self._live_file_access_rows), len(carved_fa_rows),
                derived.file_text_only(self._parser, self._recovery_engine))
            dl_note = "%s live, %s recovered" % (
                format(len(self._live_download_rows), ","),
                format(len(carved_dl_rows), ","))
        else:
            merged_fa = self._live_file_access_rows
            merged_dl = self._live_download_rows
            fa_note = dl_note = self._not_scanned(LIVE_ONLY_NOTE)
        widget.set_records_for("file_access", merged_fa, note=fa_note)
        widget.set_records_for("downloads", merged_dl, note=dl_note)
        self._restore_column_state("downloads", widget.table)

    def _push_headers_state(self):
        widget = self._built_widget("headers")
        if widget is None:
            return
        if self._recovery_engine is not None:
            carved_hdr_rows = derived.carved_headers(self._parser, self._recovery_engine)
            merged_hdr = self._live_header_rows + carved_hdr_rows
            note = "%s live, %s recovered" % (
                format(len(self._live_header_rows), ","),
                format(len(carved_hdr_rows), ","))
        else:
            merged_hdr = self._live_header_rows
            note = self._not_scanned(LIVE_ONLY_NOTE)
        widget.set_records(merged_hdr, note=note)
        self._restore_column_state("headers", widget.table)

    def _stub_count(self):
        """Deleted-record stubs in the recovery scan (0 before one runs)."""
        return len(getattr(self._recovery_engine, "tombstones", None) or ())

    def _domains_carved_entries(self):
        """The SAME union domain_rows()/indicator_rows()/deleted_records_
        rows() all read -- engine.structured_records + engine.all_
        artifacts() -- or () before any scan has run. One formula, so a
        push method built late can never disagree with one that ran at
        scan time about what "the carved set" means."""
        if self._recovery_engine is None:
            return ()
        return derived.carved_entries(self._parser, self._recovery_engine)

    def _push_domains_state(self):
        widget = self._built_widget("domains")
        if widget is None:
            return
        if self._parser is None or not hasattr(self._parser, "all_entries"):
            widget.set_records([], note=DOMAIN_CARVED_NOT_SCANNED_NOTE)
            self._restore_column_state("domains", widget.table)
            return
        carved_entries = self._domains_carved_entries()
        if self._recovery_engine is not None:
            # Counted from what was profiled: deleted-record stubs carry no
            # URL, so they are not passed in.
            rows = derived.domains(self._parser, self._recovery_engine)
            note = "%s live, %s recovered records%s" % (
                format(len(self._parser.all_entries), ","),
                format(len(carved_entries), ","),
                _stub_suffix(self._stub_count()))
        else:
            rows = derived.domains(self._parser)
            note = DOMAIN_CARVED_NOT_SCANNED_NOTE
        widget.set_records(rows, note=note)
        self._restore_column_state("domains", widget.table)

    def _push_tagged_state(self):
        """Every record carrying a tag or comment, live and recovered, and
        the sidebar's count of them."""
        live = list(getattr(self._parser, "all_entries", None) or [])
        rows = tagged_loader.tagged_rows(self._case, live,
                                         self._recovered_artifacts())
        if "tagged" in self._index:
            self.sidebar.set_count("tagged", len(rows))
        widget = self._built_widget("tagged")
        if widget is None:
            return
        widget.set_records(rows)
        self._restore_column_state("tagged", widget.table)

    def _push_indicators_state(self):
        widget = self._built_widget("indicators")
        if widget is None:
            return
        if self._parser is None or not hasattr(self._parser, "all_entries"):
            widget.set_records(
                [], note=self._not_scanned(INDICATOR_NOT_SCANNED_NOTE))
            self._restore_column_state("indicators", widget.table)
            return
        carved_entries = self._domains_carved_entries()
        if self._recovery_engine is not None:
            # What was scanned (see _push_domains_state).
            rows = derived.indicators(self._parser, self._recovery_engine)
            note = "%s live record(s), %s recovered record(s) scanned%s" % (
                format(len(self._parser.all_entries), ","),
                format(len(carved_entries), ","),
                _stub_suffix(self._stub_count()))
        else:
            rows = derived.indicators(self._parser)
            note = self._not_scanned(INDICATOR_NOT_SCANNED_NOTE)
        widget.set_records(rows, note=note)
        self._restore_column_state("indicators", widget.table)

    def _push_iocs_state(self):
        """All six Findings segments, recomputed from self._parser and
        self._recovery_engine like every _push_*_state method, so a view
        built late shows the same state.

        The watchlist is read, not reset: whatever is in
        FindingsView.watchlist_box (empty on a first load, the last text on
        a later Open Evidence in the same session) is what ioc_hits is
        scored against.
        """
        widget = self._built_widget("iocs")
        if self._parser is None or not hasattr(self._parser, "all_entries"):
            self._set_findings_badge(0)
            if widget is None:
                return
            for seg_key in ("ioc_hits", "entryid_gaps", "time_voids",
                            "beaconing", "deceptive_hostnames",
                            "redirect_chains"):
                widget.set_records_for(seg_key, [])
            widget.set_corpus_note(IOCS_CORPUS_LIVE_ONLY)
            self._restore_column_state("iocs", widget.table)
            return
        live_entries = self._parser.all_entries
        scanned = self._recovery_engine is not None
        carved_entries = self._domains_carved_entries() if scanned else ()
        # The stubs are named once, in the corpus banner above the switcher;
        # repeating them on every segment's count line crushed it into the
        # narrow column beside the chip.
        note = (_iocs_scan_note(len(carved_entries)) if scanned
                else self._not_scanned(IOCS_NOT_SCANNED_NOTE))
        terms = (split_watchlist(widget.watchlist_box.text())
                 if widget is not None else [])
        # A silence withheld because an MSHist visit with no recovered zone
        # may fall inside it is stated on the count line, never dropped
        # quietly (engine/local_clock.py; analyze_time_voids).
        engine = self._recovery_engine if scanned else None
        void_rows, void_note = derived.finding(self._parser, engine,
                                               "time_voids")
        # Computed ONCE: the same lists feed the badge and the view.
        sets = [
            ("ioc_hits", derived.finding(self._parser, engine, "ioc_hits",
                                         tuple(terms)),
             note),
            ("entryid_gaps",
             derived.finding(self._parser, engine, "entryid_gaps"),
             note),
            ("time_voids", void_rows,
             ("%s. %s" % (note, void_note)) if void_note else note),
            ("beaconing", derived.finding(self._parser, engine, "beaconing"),
             IOCS_BEACON_NOTE),
            ("deceptive_hostnames",
             derived.finding(self._parser, engine, "deceptive_hostnames"),
             note),
            ("redirect_chains",
             derived.finding(self._parser, engine, "redirect_chains"),
             note),
        ]
        self._set_findings_badge(sum(len(rows) for _k, rows, _n in sets))
        if widget is None:
            return
        for seg_key, rows, seg_note in sets:
            widget.set_records_for(seg_key, rows, note=seg_note)
        widget.set_corpus_note(
            _iocs_corpus_recovered(len(carved_entries), self._stub_count())
            if scanned
            else IOCS_CORPUS_LIVE_ONLY)
        # open where the findings are.
        widget.open_first_non_empty()
        self._restore_column_state("iocs", widget.table)

    def _set_findings_badge(self, total):
        self.sidebar.set_count(
            "iocs", total, unit=record_counts.BADGE_UNITS["iocs"])

    def _push_timeline_state(self):
        """Apply Timeline results to a Timeline view built after evidence
        loaded. Called only from _replay_view_state. (_fill_timeline runs at
        every load and scan whether or not the view exists.)

        self._timeline_results holds the last completed build's
        (inputs, rows_by_grain, notes_by_grain). If its `inputs` is
        self._timeline_inputs (by identity; no load or scan has superseded
        it), the result is applied to the new widget without a second
        build. Otherwise _fill_timeline starts a build for this widget, and
        the view shows its building state until it finishes
        (test_the_view_says_it_is_building_until_the_worker_lands).
        """
        # _restore_column_state needs a model to restore onto
        # (RecordsTable._fit_columns reads self.model().columns), and a new
        # table has none until its first set_records_for call, which both
        # branches below make, so it runs afterwards, as in every push
        # method.
        widget = self._built_widget("timeline")
        results = self._timeline_results
        if results is not None and results[0] is self._timeline_inputs:
            inputs, rows_by_grain, notes_by_grain = results
            widget.set_inputs(inputs)
            self._sync_timeline_clock(widget)
            for grain, _label, _plural in timeline_loader.GRAINS:
                widget.set_records_for(
                    grain, rows_by_grain[grain], note=notes_by_grain[grain])
        else:
            self._sync_timeline_clock(widget)
            self._fill_timeline(scan_run=self._recovery_engine is not None)
        self._restore_column_state("timeline", widget.table)

    def _push_search_state(self):
        """Search's state: the scope combo, and what the last completed
        search of this exhibit found.

        Called from _on_evidence_loaded like every push method, and from
        _replay_view_state when the view is built later.

        The db_path check ensures a result from another database is never
        shown under the current one; _on_evidence_loaded also clears it on
        every new exhibit.

        _restore_column_state runs last (see _push_timeline_state): it
        needs the model both branches below create.
        """
        widget = self._built_widget("search")
        if widget is None:
            return
        widget.set_parser(self._parser)
        widget.set_scope_options(
            search_loader.scope_options(self._parser,
                                        self._recovered_count_or_none())
            if self._parser is not None else None)
        results = self._search_results
        if results is not None and results[0].db_path == self._exhibit_path():
            widget.show_results(results[0], results[1])
        else:
            widget.set_idle()
        self._restore_column_state("search", widget.table)

    def _push_location_state(self):
        widget = self._built_widget("location")
        if widget is None:
            return
        widget.set_records_for(
            "fixes", self._location_fixes,
            note=location_loader.fixes_note(
                self._location_fixes, scan_run=self._recovery_engine is not None))
        widget.set_records_for(
            "places", self._location_places,
            note=location_loader.places_note(
                self._location_fixes, self._location_places,
                grouping=self._location_grouping))
        widget.set_records_for(
            "records", location_loader.source_records(self._location_fixes),
            note=location_loader.records_note(self._location_fixes))
        self._restore_column_state("location", widget.table)

    def _push_cookies_state(self):
        widget = self._built_widget("cookies")
        if widget is None:
            return
        parser_has_cookies = (self._parser is not None
                              and hasattr(self._parser, "cookie_entries"))
        parser_has_hsts = (self._parser is not None
                           and hasattr(self._parser, "hsts_entries")
                           and hasattr(self._parser, "all_entries"))
        parser_has_certs = (self._parser is not None
                            and hasattr(self._parser, "cert_entries"))
        widget.set_records_for(
            "cookies", cookie_rows_from_parser(self._parser) if parser_has_cookies else [])
        widget.set_records_for(
            "hsts", hsts_rows_from_parser(self._parser) if parser_has_hsts else [])
        widget.set_records_for(
            "certs", cert_rows_from_parser(self._parser) if parser_has_certs else [])
        self._restore_column_state("cookies", widget.table)

    def _push_containers_state(self):
        widget = self._built_widget("containers")
        if widget is None:
            return
        parser_has_containers = (self._parser is not None
                                 and hasattr(self._parser, "containers_meta")
                                 and hasattr(self._parser, "get_container_type"))
        rows = container_rows_from_parser(self._parser) if parser_has_containers else []
        widget.set_records(rows)
        self._restore_column_state("containers", widget.table)

    def _push_browser_state(self):
        widget = self._built_widget("browser")
        if widget is None:
            return
        parser_has_tables = (self._parser is not None
                             and hasattr(self._parser, "get_tables_grouped"))
        widget.set_parser(self._parser if parser_has_tables else None)

    def _push_recovery_state(self):
        widget = self._built_widget("recovery")
        if widget is None:
            return
        if self._recovery_engine is not None:
            recovery_rows = derived.deleted_records(self._parser, self._recovery_engine)
            carved_rows = derived.carved_history(self._parser, self._recovery_engine)
            note = None
            if recovery_rows:
                # Stubs are counted on their own: they
                # are not carves at all, so "a different container, or none
                # a string carve can supply" is not their reason.
                stubs = sum(1 for r in recovery_rows
                            if r.get("_kind") == K_TOMBSTONE)
                note = (
                    "%s merged into History; %s did not (another "
                    "container, or no container recorded)"
                    % (format(len(carved_rows), ","),
                      format(len(recovery_rows) - len(carved_rows) - stubs,
                             ",")))
                if stubs:
                    note += "; %s deleted-record stubs (key only)" % format(
                        stubs, ",")
            widget.set_records(recovery_rows, note=note)
        else:
            widget.set_records([], note=NOT_SCANNED_NOTE)
        self._restore_column_state("recovery", widget.table)
        widget.set_scanning(False)

    def _recovered_count_or_none(self):
        """None before any scan has run for this exhibit, rather than 0,
        as LIVE_ONLY_NOTE states for History."""
        if self._recovery_engine is None:
            return None
        return len(derived.deleted_records(self._parser, self._recovery_engine))

    def _push_export_state(self):
        widget = self._built_widget("export")
        if widget is None:
            return
        if self._case is not None:
            widget.set_case_meta(self._case.all_meta())
            widget.set_case_enabled(True)
        elif self._case_opened_ever:
            widget.set_case_meta({})
            widget.set_case_enabled(False)
        self._push_export_coverage()

    def _push_export_coverage(self):
        """Coverage and format availability -- split from _push_export_
        state's case-metadata half because _refresh_export_page (run on
        every load AND every completed scan) only ever needs to change
        this half; case metadata is a per-exhibit fact set once, by
        _open_case_file, not something a recovery scan touches."""
        widget = self._built_widget("export")
        if widget is None:
            return
        artifacts = self._artifacts()
        records = (self._dashboard_live_stats or {}).get(
            "total_records", len(getattr(self._parser, "all_entries", None) or []))
        widget.set_coverage({
            "records": records,
            "cookies": len(artifacts.get("cookies", [])),
            "hsts": len(artifacts.get("hsts", [])),
            "certs": len(artifacts.get("certs", [])),
            "leaks": len(artifacts.get("leaks", [])),
            "recovered": self._recovered_count_or_none(),
        })
        widget.set_availability(export_formats.availability(self._capabilities()))

    def _on_evidence_loaded(self, result, evidence_set):
        # This handler can only ever be reached by the CURRENT loader --
        # _cancel_pending_load() disconnects every earlier one before a
        # new load starts -- so re-enabling here is always correct, never
        # a premature re-enable for a load that a newer one has already
        # superseded.
        self.open_evidence_action.setEnabled(True)
        self._end_load_busy_ui()
        rows = result.get("rows", [])
        # Before self._parser is replaced: open detail dialogs hold record
        # references into the outgoing parser (see _close_record_dialogs).
        self._close_record_dialogs()
        self._parser = result.get("parser")
        # The status bar's right-hand summary: table and container counts
        # and the dirty-shutdown state from the parser that opened this
        # exhibit (see _db_summary_html on why total_entries differs from
        # the History row count). Guarded with hasattr: some tests pass a
        # minimal stand-in parser (test_recovery_wiring.py's _FakeParser)
        # without the full ESE surface, which then reads as unknown, as
        # before evidence is open.
        self._db_summary_info = (
            self._parser.get_database_info()
            if self._parser is not None and hasattr(self._parser, "get_database_info")
            else None)
        self._refresh_db_summary_widget()
        # Integrity reads the same dict: get_database_info() carries what
        # its three cards need (source hashes, db_state_text, parse_stats,
        # decision_log, derived_tz; see integrity_loader.py). None shows
        # IntegrityView's no-evidence state. Pushed through
        # _push_integrity_state, since Integrity may not be built yet; if
        # not, _ensure_view_built replays it from self._db_summary_info.
        self._push_integrity_state()
        # Recovery results belong to one exhibit, so both are reset on every
        # successful load, whether or not a scan ran.
        self._recovery_engine = None
        self._recovery_state = "not_run"
        self._recovery_pages = ""
        # A search result belongs to a database: its rows name tables and
        # row ordinals in the exhibit it ran against. Reset on every
        # successful load; _push_search_state's db_path check is a second
        # guard.
        self._search_results = None
        # Position fixes belong to this exhibit; reset on every successful
        # load.
        self._location_fixes = []
        self._location_places = []
        # Dashboard: live-only figures from the parser (not `rows`, which is
        # History alone; Total Records is a whole-database sum, see
        # dashboard_data.py). None when the parser cannot support it (no
        # parser, or a stand-in without all_entries/get_database_info), which
        # DashboardView.set_data(None, ...) shows as "-", not zero.
        self._dashboard_live_stats = (
            derived.dashboard_live(self._parser)
            if self._parser is not None and hasattr(self._parser, "all_entries")
            else dashboard_data.compute_dashboard_stats(self._parser))
        self._push_dashboard_state()
        self._live_history_rows = rows
        self.recover_action.setEnabled(self._parser is not None)
        # No carve runs at open, so this row set is live records only, and
        # the count line says so (see evidence_loader.py).
        self._push_history_state()
        # File Access: computed here (EvidenceLoadWorker builds History's
        # row set). hasattr-guarded like _db_summary_info above: a stand-in
        # parser without all_entries, or no parser, shows nothing yet rather
        # than failing.
        parser_has_entries = (self._parser is not None
                              and hasattr(self._parser, "all_entries"))
        fa_rows = (derived.file_access_rows(self._parser)
                  if parser_has_entries else [])
        dl_rows = (derived.download_rows(self._parser)
                  if parser_has_entries else [])
        self._live_file_access_rows = fa_rows
        self._live_download_rows = dl_rows
        # Live records only, as for History above.
        self._push_downloads_state()
        self.sidebar.set_count(
            "downloads", len(fa_rows) + len(dl_rows),
            unit=record_counts.BADGE_UNITS["downloads"])

        # HTTP Headers: the records that carry a decoded header dict, far
        # fewer than the entry count; the view's subtitle says why (a History
        # record's ResponseHeaders blob is usually a property store; see
        # headers_loader.py). Live records only, as for History.
        header_row_list = (derived.header_rows(self._parser)
                           if parser_has_entries else [])
        self._live_header_rows = header_row_list
        self._push_headers_state()
        self.sidebar.set_count(
            "headers", len(header_row_list),
            unit=record_counts.BADGE_UNITS["headers"])

        # Domains: one row per host, from the same live entries as File
        # Access and Cookies (not `rows`, which is History alone). Before a
        # scan the carved columns read 0/False (domain_loader.py), and
        # DOMAIN_CARVED_NOT_SCANNED_NOTE says no scan has run. The sidebar
        # count is computed here whether or not Domains is built;
        # _push_domains_state recomputes the same rows from self._parser, so
        # the same formula runs from here, from the recovery merge below,
        # and from _ensure_view_built.
        domain_row_list = (derived.domains(self._parser)
                           if parser_has_entries else [])
        self._push_domains_state()
        self.sidebar.set_count(
            "domains", len(domain_row_list),
            unit=record_counts.BADGE_UNITS["domains"])

        # Indicators: url_intel.py over the same live entries, live only at
        # open.
        indicator_row_list = (derived.indicators(self._parser)
                              if parser_has_entries else [])
        self._push_indicators_state()
        self._push_tagged_state()
        self.sidebar.set_count(
            "indicators", len(indicator_row_list),
            unit=record_counts.BADGE_UNITS["indicators"])

        # Timeline: the same live entries, bucketed four ways. The inputs are
        # computed once and shared by all four grains, so the admission rule
        # (does this record carry a usable timestamp?) is applied once.
        # _fill_timeline is called whether or not Timeline is built: the
        # build runs on a worker thread, and
        # test_opening_evidence_starts_a_background_build_not_a_synchronous_one
        # expects self._timeline_builder to exist when this method returns.
        # Only the widget updates wait for the view (_fill_timeline and
        # _on_timeline_built check _built_widget); a Timeline built later
        # gets its rows from _push_timeline_state (via
        # _replay_view_state).
        self._timeline_clock = "utc"
        self._timeline_inputs = (derived.timeline_inputs(self._parser)
                                 if parser_has_entries
                                 else timeline_loader.timeline_inputs([]))
        self._fill_timeline(scan_run=False)

        # Location: positions read from the same live entries, live only at
        # open. A position is often present only in a deleted or unflushed
        # URL, so the live database may hold none. _fill_location computes
        # the fixes and places, sets the nav badge, and updates the Location
        # view if it is built.
        self._fill_location(self._parser.all_entries if parser_has_entries else [])

        # Cookies & HSTS and Containers: read from the parser's
        # modern-table attributes (cookie_entries/hsts_entries/cert_entries/
        # containers_meta), not from `rows`. These tables and the Containers
        # table are parsed in full at open (ese_parser._parse_modern_tables/
        # _load_containers), so neither view has a live-only note.
        #
        # Guarded per attribute: some tests pass a minimal parser
        # (test_recovery_wiring.py's _FakeParser) without cookie_entries/
        # hsts_entries/cert_entries/get_container_type. Each row set is
        # computed only when its attributes exist, as parser_has_entries does
        # for File Access; otherwise it is empty.
        parser_has_cookies = (self._parser is not None
                              and hasattr(self._parser, "cookie_entries"))
        parser_has_hsts = (self._parser is not None
                           and hasattr(self._parser, "hsts_entries")
                           and hasattr(self._parser, "all_entries"))
        parser_has_certs = (self._parser is not None
                            and hasattr(self._parser, "cert_entries"))
        parser_has_containers = (self._parser is not None
                                 and hasattr(self._parser, "containers_meta")
                                 and hasattr(self._parser, "get_container_type"))
        cookie_row_list = (cookie_rows_from_parser(self._parser)
                           if parser_has_cookies else [])
        hsts_row_list = (hsts_rows_from_parser(self._parser)
                         if parser_has_hsts else [])
        cert_row_list = (cert_rows_from_parser(self._parser)
                         if parser_has_certs else [])
        self._push_cookies_state()
        # The nav badge is the WHOLE view's own total across all three
        # segments, not just whichever one happens to be on screen --
        # matching how "downloads" (File Access, two segments) already
        # combines file_access + downloads above.
        self.sidebar.set_count(
            "cookies", len(cookie_row_list) + len(hsts_row_list)
            + len(cert_row_list),
            unit="items: %s cookie%s, %s HSTS pin%s, %s certificate%s" % (
                format(len(cookie_row_list), ","),
                "" if len(cookie_row_list) == 1 else "s",
                format(len(hsts_row_list), ","),
                "" if len(hsts_row_list) == 1 else "s",
                format(len(cert_row_list), ","),
                "" if len(cert_row_list) == 1 else "s"))
        container_row_list = (container_rows_from_parser(self._parser)
                              if parser_has_containers else [])
        self._push_containers_state()
        # Search: the scope combo is refilled from this exhibit's tables, and
        # a built view drops the previous exhibit's hits. Nothing happens
        # (_built_widget) when Search has never been opened.
        self._push_search_state()
        self.sidebar.set_count(
            "containers", len(container_row_list),
            unit=record_counts.BADGE_UNITS["containers"])

        # Findings: all six segments over the same live entries, and the
        # sidebar badge (the total of the six) whether or not the view is
        # built; _push_iocs_state computes the rows once and does both.
        # Placed after _fill_timeline above: its six engine calls are
        # synchronous, and doing them first would delay the start of the
        # Timeline worker, which test_timeline_wiring.py's _wait_for_timeline
        # is sensitive to.
        self._push_iocs_state()

        # Table Browser: given the parser itself rather than a row list; its
        # rows are paged and fetched on demand (table_browser_loader.
        # table_page, on every table selection and Prev/Next). Guarded on
        # get_tables_grouped, as parser_has_containers is above: a minimal
        # stand-in parser shows TableBrowserView's no-evidence state.
        parser_has_tables = (self._parser is not None
                             and hasattr(self._parser, "get_tables_grouped"))
        self._push_browser_state()
        # The Table Browser's nav figure is the number of raw tables, from
        # the same grouping table_browser_loader.grouped_tables() computed for
        # the left panel above.
        table_total = (sum(len(tables) for _, tables
                          in browser_grouped_tables(self._parser))
                      if parser_has_tables else 0)
        self.sidebar.set_count(
            "browser", table_total,
            unit=record_counts.BADGE_UNITS["browser"])

        # Recovery's own COLUMNS never change regardless of whether a scan
        # has run yet, so this table already has a real header to restore
        # widths onto even before the first Recover deleted records click.
        self._push_recovery_state()
        # Set from the moment evidence loads: 0 is a real count here (the
        # view's count line says "0 recovered record(s)"), and
        # _on_recovery_loaded updates it when a scan finds records.
        self.sidebar.set_count(
            "recovery", 0,
            unit=record_counts.BADGE_UNITS["recovery"])
        # The case file: in the app-local cases folder (paths.cases_dir()),
        # keyed by the evidence SHA-256, never beside the exhibit. Opened
        # here so the Export page's case fields can be saved, and so tags
        # and comments recorded for this exhibit go into every export that
        # accepts them.
        self._open_case_file(evidence_set)
        # Coverage and format availability, pushed with every other view. No
        # scan has run for this exhibit yet, so _recovered_count_or_none()
        # reads self._recovery_engine (reset to None above) and reports None,
        # not 0.
        self._refresh_export_page()
        self.sidebar.set_count(
            "history", len(rows),
            unit=record_counts.BADGE_UNITS["history"])
        # Total Records (dashboard_data.py), not History's own count --
        # see that module's docstring: a whole-database sum, not a
        # single container type. Falls back to History's count only when
        # dashboard stats could not be computed at all, the same
        # degrade-gracefully contract every hasattr guard above already
        # keeps for a minimal stand-in parser.
        self.sidebar.set_count(
            "dashboard",
            self._dashboard_live_stats["total_records"]
            if self._dashboard_live_stats else len(rows),
            unit="live records (recovery not run)")
        if not self._ever_loaded:
            # Only on the first successful open this session (see
            # _ever_loaded: a later failure never reverts it).
            self._ever_loaded = True
            self.sidebar.set_loaded(True)
            self.content_stack.setCurrentIndex(1)
        self.go_to("history")
        # A newly opened exhibit puts focus on a grid, so the first arrow key
        # moves through it.
        self._focus_view(self.stack.currentWidget())
        # A new exhibit clears Back history, which refers to the previous
        # one.
        self._nav_history.clear()
        self._sync_back_controls()

        fname = os.path.basename(evidence_set.files[0]) if evidence_set.files else ""
        sha = next(iter(evidence_set.hashes.values()), "")
        self._set_status_message(
            "Opened %s — SHA-256 %s — %d live History record(s); %s"
            % (fname, sha, len(rows), LIVE_ONLY_NOTE))

        # As if Recover had been clicked: the same _start_recovery, one
        # event-loop turn later, so the views just filled are painted before
        # the scan's busy UI replaces the status line. The parser is
        # captured now: a second open completing before that turn (see
        # _cancel_pending_load) replaces self._parser, and the queued scan
        # must not run against the new exhibit.
        if self._recover_after_load and self._parser is not None:
            QTimer.singleShot(
                0, lambda parser=self._parser:
                    self._start_recovery_if_current(parser))
        self._recover_after_load = False

    def _on_evidence_failed(self, message):
        self._recover_after_load = False
        self.open_evidence_action.setEnabled(True)
        self._end_load_busy_ui()
        self._set_status_message(
            "Could not parse the evidence: %s. Select another file to "
            "continue." % message)

    # --- recovery: Evidence > Recover deleted records ----------------------
    #
    # Runs automatically when the Open evidence box is ticked, and can be
    # run again from self.recover_action or the Deleted Records view's
    # button (RecoveryView.recoverRequested); every route arrives here.

    def _start_recovery_if_current(self, parser):
        """The queued automatic recovery, one event-loop turn after
        _on_evidence_loaded queued it. Starts the scan only if the parser it
        was queued for is still the one open (a second open may have
        replaced self._parser); otherwise does nothing."""
        if self._parser is parser:
            self._start_recovery()

    def _start_recovery(self):
        if self._parser is None:
            return
        # Called unconditionally, as _cancel_pending_load is at the start of
        # every load: cancelling a stopped worker and disconnecting fired
        # signals do nothing.
        self._cancel_pending_recovery()
        self.recover_action.setEnabled(False)
        # Forced, not _built_widget: reachable straight from Evidence >
        # Recover deleted records… (recover_action), which is enabled the
        # moment a parser loads regardless of whether the Deleted Records
        # page has ever been opened this session.
        recovery_view = self._ensure_view_built("recovery")
        recovery_view.set_scanning(True)
        self._set_recovery_state("running")
        self._begin_recovery_busy_ui("Recovering deleted records…")
        loader = RecoveryLoader(self)
        self._recovery_loader = loader
        loader.progress.connect(self._on_recovery_progress)
        loader.loaded.connect(self._on_recovery_loaded)
        loader.failed.connect(self._on_recovery_failed)
        loader.start(self._parser)

    def _begin_recovery_busy_ui(self, message):
        """Shares _load_elapsed/_load_status_timer/_load_progress/
        _load_cancel_button with the evidence load -- see __init__'s
        comment on why one pair, not two. Setting self._busy_for BEFORE
        making the pair visible is what lets _cancel_current_busy_
        operation route a click correctly the instant it can be clicked
        at all."""
        self._busy_for = "recovery"
        self._load_elapsed.start()
        self._load_last_message = message
        self._set_status_message(message)
        self._load_progress.setVisible(True)
        self._load_cancel_button.setVisible(True)
        self._load_cancel_button.setEnabled(True)
        self._load_status_timer.start()

    def _end_recovery_busy_ui(self):
        """Called on every exit path (success, failure and cancel), as
        _end_load_busy_ui is."""
        self._load_status_timer.stop()
        self._load_progress.setVisible(False)
        self._load_cancel_button.setVisible(False)
        if self._busy_for == "recovery":
            self._busy_for = None

    def _on_recovery_progress(self, message):
        self._load_last_message = message
        self._refresh_load_elapsed()
        match = _PAGES_DONE.search(message or "")
        if match and self._recovery_state == "running":
            self._recovery_pages = "%s pages" % match.group(1)
            self._show_recovery_running()

    def _not_scanned(self, note):
        """`note` (a "deleted records not yet recovered" sentence), or the
        running sentence while a scan is in flight."""
        if getattr(self, "_recovery_state", "not_run") == "running":
            return RECOVERY_RUNNING_NOTE
        return note

    def _show_recovery_running(self):
        """The surfaces updated on every progress report: the status summary
        and the Deleted Records badge, which shows "…" rather than a 0 that
        would read as "nothing recovered"."""
        self._refresh_db_summary_widget()
        self._set_live_dashboard_badge("live records (recovery running)")
        self.sidebar.set_count(
            "recovery", "…",
            unit="recovery running%s" % (
                " (%s)" % self._recovery_pages if self._recovery_pages
                else ""))

    def _set_live_dashboard_badge(self, unit):
        """The Dashboard badge's live-only count, worded for the recovery
        state. A no-op once a scan has merged."""
        if self._recovery_engine is not None or self._parser is None:
            return
        stats = self._dashboard_live_stats
        self.sidebar.set_count(
            "dashboard", stats["total_records"] if stats
            else len(getattr(self, "_live_history_rows", None) or ()),
            unit=unit)

    def _set_recovery_state(self, state):
        """One place the recovery state changes, and every surface that
        words it is restated from it: the status summary, the badge, the
        Dashboard's case summary, and the live-only count lines."""
        self._recovery_state = state
        self._recovery_pages = ""
        if state == "running":
            self._show_recovery_running()
        else:
            self._refresh_db_summary_widget()
            if self._recovery_engine is None:
                self.sidebar.set_count(
                    "recovery", 0,
                    unit=record_counts.BADGE_UNITS["recovery"])
                self._set_live_dashboard_badge(
                    "live records (recovery not run)")
        if self._parser is None:
            return
        self._push_dashboard_state()
        if self._recovery_engine is not None:
            return
        # The words change, not the records: each live-only count line is
        # restated in place, so no model is rebuilt under the examiner.
        note = self._not_scanned(LIVE_ONLY_NOTE)
        for key, segments in (("history", None), ("headers", None),
                              ("downloads", ("file_access", "downloads"))):
            widget = self._built_widget(key)
            if widget is None or not hasattr(widget, "set_note_for"):
                continue
            for segment in segments or (widget._active_key,):
                widget.set_note_for(segment, note)

    def _cancel_current_recovery(self):
        """Cancel the scan through _cancel_pending_recovery() (see
        _cancel_current_load)."""
        self._cancel_pending_recovery()
        self._end_recovery_busy_ui()
        self.recover_action.setEnabled(True)
        # Already built by the _start_recovery call this is cancelling --
        # _ensure_view_built here is just a lookup, never a fresh build.
        recovery_view = self._ensure_view_built("recovery")
        recovery_view.set_scanning(False)
        self._set_recovery_state(
            "done" if self._recovery_engine is not None else "not_run")
        self._set_status_message(
            "Recovery scan cancelled — nothing was recovered.")

    def _cancel_pending_recovery(self):
        """Stop whatever a previous _start_recovery left running, as
        _cancel_pending_load does for a load, so a superseded worker's late
        result is never applied."""
        old = getattr(self, "_recovery_loader", None)
        if old is None:
            return
        old.cancel()
        for sig in (old.loaded, old.failed, old.progress):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass

    # --- the cross-table search -------------------------------------------

    def _start_search(self, keyword, table_filter=""):
        """Run one search, from the view's searchRequested.

        _cancel_pending_search runs first, so a slow earlier search's hits
        never arrive under a later keyword's count line.

        Refused, with a message, when there is no exhibit, when the keyword
        is blank (it would read every table and match nothing), and when
        another long operation holds the shared status-bar Cancel button.

        A new search replaces one in progress rather than being refused, so
        a mistyped keyword can be corrected at once. A load, a scan or an
        export is still refused, since they share the one Cancel button.

        The two refusals that change nothing are checked before anything is
        cancelled, so Return on an empty box never stops a running search.
        Cancellation happens before the new runner exists, which prevents a
        late result from the old one.
        """
        if self._parser is None:
            self._set_status_message(_LOAD_FIRST_MESSAGE)
            return
        keyword = str(keyword or "").strip()
        if not keyword:
            self._set_status_message(
                "Enter a keyword to search.")
            return
        if self._busy_for is not None and self._busy_for != "search":
            self._set_status_message(
                "Another operation is already running. Wait for it to "
                "finish, or cancel it, before starting a search.")
            return
        self._cancel_pending_search()
        if self._busy_for == "search":
            # The superseded search's own busy state ends here; the new
            # one begins its own two lines down. Guarded on the value so
            # this can never hide another operation's progress bar.
            self._end_search_busy_ui()
        view = self._ensure_view_built("search")
        query = self._search_query_for(keyword, table_filter)
        view.show_searching(query)
        self._begin_search_busy_ui("Searching for '%s'…" % keyword)
        if table_filter == search_loader.RECOVERED_SCOPE:
            # Nothing in the database is read: the recovered records are
            # already in memory.
            self._on_search_found(query, {"rows": [], "tables": 0,
                                          "rows_scanned": 0, "skipped": []})
            return
        runner = SearchRunner(self)
        self._search_runner = runner
        runner.progress.connect(self._on_search_progress)
        # `query` is CAPTURED, never re-read from an attribute: a second
        # search started since would already have disconnected this
        # handler, but closing over the value means a result can never
        # render under a different query's label even in principle.
        runner.found.connect(
            lambda _q, result, q=query: self._on_search_found(q, result))
        runner.failed.connect(self._on_search_failed)
        runner.start(query)

    def _search_query_for(self, keyword, table_filter):
        """One SearchQuery, with the recovered records it covers:
        every Deleted Records row when the scope is All or Recovered, and
        a stated count of those NOT searched when the scope is one table.
        None rows when no scan has run.

        THE RECOVERED ROWS ARE CAPTURED HERE, when the search is asked
        for. A search started before a recovery scan finishes covers the
        database only; _on_search_found says so in the count line, and
        the scope combo gains "Recovered records (N)" the moment the scan
        lands."""
        view = self._ensure_view_built("search")
        recovered = (derived.deleted_records(self._parser, self._recovery_engine)
                     if self._recovery_engine is not None else None)
        table_filter = table_filter or ""
        return search_loader.SearchQuery(
            keyword,
            table_filter=("" if table_filter == search_loader.RECOVERED_SCOPE
                          else table_filter),
            scope_label=view.scope_label(),
            db_path=self._exhibit_path(),
            # Computed by the Open dialog. The worker opens its own parser
            # (see search_runner.py), which would otherwise hash the exhibit
            # again.
            known_hashes=dict(getattr(getattr(self, "_evidence_set", None),
                                      "hashes", None) or {}),
            recovered_rows=recovered,
            include_recovered=table_filter in ("", search_loader.RECOVERED_SCOPE),
            # the worker's parser never parses entries;
            # the MSHist clock travels with the query.
            clock=(local_clock.clock_snapshot(
                getattr(self._parser, "all_entries", None),
                getattr(self._parser, "derived_tz_offset_seconds", None))
                   if self._parser is not None else None))

    def _refresh_search_scope(self):
        """Refill Search's scope combo -- keeping the examiner's current
        choice -- without touching its results or its running state."""
        widget = self._built_widget("search")
        if widget is None or self._parser is None:
            return
        widget.set_scope_options(
            search_loader.scope_options(self._parser,
                                        self._recovered_count_or_none()),
            keep_current=True)

    def _on_search_found(self, query, result):
        """A completed search. The result is cached whether or not Search is
        built (as _on_timeline_built caches its own), so a view built later
        applies it without a second scan.

        The recovered records captured with the query are searched here, on
        the GUI thread (a pass over in-memory dicts), and their hits are
        appended. The result dict is copied, never modified in place."""
        result = dict(result or {})
        recovered = getattr(query, "recovered_rows", None)
        if recovered is None and self._recovery_engine is not None:
            # A scan finished during this search: recovered records exist
            # and were not searched, which the note states.
            result["recovered"] = (
                len(derived.deleted_records(self._parser, self._recovery_engine)), False,
                "recovery finished after this search began; search again "
                "to include them")
        elif recovered is None:
            result["recovered"] = None
        elif query.include_recovered:
            result["rows"] = (list(result.get("rows") or ())
                              + search_loader.recovered_hits(query.keyword,
                                                             recovered))
            result["recovered"] = (len(recovered), True, "")
        else:
            result["recovered"] = (len(recovered), False,
                                   "the scope is one table")
        self._search_results = (query, result)
        self._end_search_busy_ui()
        view = self._built_widget("search")
        if view is not None:
            view.show_results(query, result)
        hits = len(result.get("rows") or ())
        message = ("%s hit(s) for '%s' across %s table(s), %s row(s) scanned."
                   % (format(hits, ","), query.keyword,
                      format(result.get("tables") or 0, ","),
                      format(result.get("rows_scanned") or 0, ",")))
        message += " " + search_loader.as_sentence(
            search_loader.recovered_sentence(result))
        sentence = search_loader.skipped_sentence(result.get("skipped"))
        if sentence:
            message += " " + sentence
        self._set_status_message(message)

    def _on_search_failed(self, message):
        self._end_search_busy_ui()
        view = self._built_widget("search")
        if view is not None:
            view.set_idle()
        self._set_status_message(
            "Search failed: %s. The search did not complete, so no "
            "result is shown." % message)

    def _on_search_progress(self, message):
        """Routed through _refresh_load_elapsed, as _on_load_progress and
        _on_recovery_progress are, so the elapsed-time suffix stays
        current."""
        self._load_last_message = message
        self._refresh_load_elapsed()

    def _begin_search_busy_ui(self, message):
        """Shares the one status-bar progress bar and Cancel button with
        the load, the scan and the export -- see __init__'s comment on
        why one pair, not four. self._busy_for is set BEFORE the pair
        becomes visible so _cancel_current_busy_operation can never be
        clickable while this dispatch does not know whose it is."""
        self._busy_for = "search"
        self._load_elapsed.start()
        self._load_last_message = message
        self._set_status_message(message)
        self._load_progress.setVisible(True)
        self._load_cancel_button.setVisible(True)
        self._load_cancel_button.setEnabled(True)
        self._load_status_timer.start()

    def _end_search_busy_ui(self):
        """Every exit path (found, failed and cancelled), as
        _end_load_busy_ui and _end_recovery_busy_ui."""
        self._load_status_timer.stop()
        self._load_progress.setVisible(False)
        self._load_cancel_button.setVisible(False)
        if self._busy_for == "search":
            self._busy_for = None

    def _cancel_current_search(self):
        """Cancel the search through _cancel_pending_search (see
        _cancel_current_load). The view shows its CANCELLED_TEXT on the grid,
        and the status bar says the same, so a cancelled search is never
        read as one that found nothing."""
        self._cancel_pending_search()
        self._end_search_busy_ui()
        view = self._built_widget("search")
        if view is not None:
            view.show_cancelled()
        self._set_status_message(
            "Search cancelled — no partial results are reported.")

    def _cancel_pending_search(self):
        """Stop whatever a previous _start_search left running, as
        _cancel_pending_load, _cancel_pending_recovery and
        _cancel_pending_timeline_build do: cancel() is a best-effort request,
        so the signals are disconnected as well.
        """
        old = getattr(self, "_search_runner", None)
        if old is None:
            return
        old.cancel()
        for sig in (old.found, old.failed, old.progress):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                # Nothing connected any more, or the runner's C++ side is
                # already gone -- either way there is nothing left to cut.
                pass

    def _cancel_pending_timeline_build(self):
        """Stop whatever a previous _fill_timeline left running, as
        _cancel_pending_load and _cancel_pending_recovery do. The build runs
        on its own thread and can outlast _on_evidence_loaded, so a second
        Open Evidence (or scan) can start while one is in progress."""
        old = getattr(self, "_timeline_builder", None)
        if old is None:
            return
        old.cancel()
        try:
            old.built.disconnect()
        except (RuntimeError, TypeError):
            pass

    def _on_recovery_loaded(self, engine):
        self.recover_action.setEnabled(True)
        self._end_recovery_busy_ui()
        # Deleted-record stubs arrive attached (engine.tombstones), computed
        # by RecoveryWorker.run on its own thread, so walking every table
        # does not stall the GUI thread and an unreadable page cannot lose
        # the scan. Consumers read getattr(engine, "tombstones", None), so an
        # engine without the attribute has none.
        self._recovery_engine = engine
        self._recovery_state = "done"
        self._recovery_pages = ""
        # Integrity gains the scan's own decisions (missing logs, files
        # left out at open): the engine kept them and nothing showed them.
        if self._db_summary_info is not None:
            self._db_summary_info["recovery_log"] = list(
                getattr(engine, "decision_log", None) or ())
            if (self._parser is not None
                    and hasattr(self._parser, "all_entries")):
                self._db_summary_info["clock_offsets"] = (
                    derived.clock_offsets(self._parser, engine))
            self._push_integrity_state()
        # the status bar's split gains its recovered half.
        self._refresh_db_summary_widget()
        self._push_recovery_state()
        # the scope gains "Recovered records (N)". The scope ONLY:
        # a search may be running, and replaying Search's whole state
        # here would paint it idle under a live scan.
        self._refresh_search_scope()

        carved_rows = derived.carved_history(self._parser, engine)
        merged = self._live_history_rows + carved_rows
        # The count line states what is on screen, and is kept across
        # filtering and navigation (HistoryView carries `note` on every
        # set_records() call). _push_history_state derives the same merge
        # from self._recovery_engine (set above), so the same formula runs
        # here, at open (_on_evidence_loaded), and when History is first
        # built after a scan.
        self._push_history_state()
        self.sidebar.set_count(
            "history", len(merged),
            unit=record_counts.BADGE_UNITS["history"])

        # File Access: the same merge, for both segments.
        # carved_file_access_rows/carved_downloads_rows rely on the same
        # normalise_record() pass as carved_history_rows (see
        # recovery_loader.py).
        carved_fa_rows = derived.carved_file_access(self._parser, engine)
        carved_dl_rows = derived.carved_downloads(self._parser, engine)
        merged_fa = self._live_file_access_rows + carved_fa_rows
        merged_dl = self._live_download_rows + carved_dl_rows
        self._push_downloads_state()
        self.sidebar.set_count(
            "downloads", len(merged_fa) + len(merged_dl),
            unit=record_counts.BADGE_UNITS["downloads"])

        # HTTP Headers: the same merge. A carved structured record went
        # through the same normalise_record() as a live entry, so a carved
        # blob of class "http" has its decoded header dict. Merged onto the
        # original live list.
        carved_hdr_rows = derived.carved_headers(self._parser, engine)
        merged_hdr = self._live_header_rows + carved_hdr_rows
        self._push_headers_state()
        self.sidebar.set_count(
            "headers", len(merged_hdr),
            unit=record_counts.BADGE_UNITS["headers"])

        recovery_rows = derived.deleted_records(self._parser, engine)
        # `carved_rows` above is the subset of `recovery_rows` whose
        # ContainerType resolved to "History"; other recovered rows (another
        # container, or CONTAINER_NOT_DETERMINABLE for a string carve) are
        # not in HistoryView. This line states that both counts come from
        # the same scan, naming only the merge this application performs.
        # (_push_recovery_state, called above, builds the same note from
        # self._recovery_engine.)
        self.sidebar.set_count(
            "recovery", len(recovery_rows),
            unit=record_counts.BADGE_UNITS["recovery"])

        # Domains: re-profiled with the two carved sources deleted_records_
        # rows() drew from (structured_records + all_artifacts()), not that
        # function's output rows, which are shaped for the Deleted Records
        # grid and lack the fields domain_rows() aggregates.
        # len(recovery_rows) is the figure the count line above states as
        # recovered, so the two screens agree.
        if self._parser is not None and hasattr(self._parser, "all_entries"):
            carved_entries = derived.carved_entries(self._parser, engine)
            merged_domain_rows = derived.domains(self._parser, engine)
            self._push_domains_state()
            # A merge can add hosts that exist only in carved data, so the
            # nav badge is recounted.
            self.sidebar.set_count(
                "domains", len(merged_domain_rows),
                unit=record_counts.BADGE_UNITS["domains"])

            # Indicators: re-scanned with the same carved_entries union, so
            # indicators in deleted URLs are included.
            merged_indicator_rows = derived.indicators(self._parser, engine)
            self._push_indicators_state()
            self._push_tagged_state()
            self.sidebar.set_count(
                "indicators", len(merged_indicator_rows),
                unit=record_counts.BADGE_UNITS["indicators"])

            # Timeline: re-bucketed from the same carved_entries union: a
            # deleted record still happened when it says. Every grain is
            # rebuilt, so switching grain after a scan shows current rows.
            # _fill_timeline runs whether or not the view is built, as at
            # open.
            self._timeline_inputs = derived.timeline_inputs(self._parser, engine)
            self._fill_timeline(scan_run=True)

            # Location: re-read from the same carved_entries union. A
            # position is often found only in a deleted URL.
            self._fill_location(self._parser.all_entries, carved_entries=carved_entries)

            # Findings: all six segments re-run over the same carved_entries
            # union, which five of them use (see iocs_loader.py). After
            # _fill_timeline, for the reason given in _on_evidence_loaded.
            self._push_iocs_state()

        # Dashboard: `recovery_rows` is the full recovered set (both
        # mechanisms, every container type, CONTAINER_NOT_DETERMINABLE
        # included), the list given to Deleted Records above. Merged onto
        # self._dashboard_live_stats (this exhibit's live figures), never
        # onto what the dashboard already shows. None when the load
        # produced no dashboard figures (no parser, or a minimal one); the
        # dashboard is then left as it is.
        merged_dashboard_stats = (
            derived.dashboard_merged(self._parser, engine)
            if (self._dashboard_live_stats is not None
                and self._parser is not None
                and hasattr(self._parser, "all_entries")
                and self._dashboard_live_stats
                is derived.dashboard_live(self._parser))
            else dashboard_data.merge_recovered_into_stats(
                self._dashboard_live_stats, recovery_rows))
        if merged_dashboard_stats is not None:
            self._push_dashboard_state()
            self.sidebar.set_count(
                "dashboard", merged_dashboard_stats["total_records"],
                unit=record_counts.BADGE_UNITS["dashboard"])

        # The Export page's coverage line and its Raw-ESE availability change
        # once a scan has run. _refresh_export_page's
        # _recovered_count_or_none() reads self._recovery_engine (set at the
        # top of this method) and reports len(recovery_rows).
        self._refresh_export_page()

        self._set_status_message(
            "Recovery scan complete — %s deleted record(s) recovered "
            "(%s merged into History)"
            % (format(len(recovery_rows), ","), format(len(carved_rows), ",")))


    def _on_recovery_failed(self, message):
        self.recover_action.setEnabled(True)
        self._end_recovery_busy_ui()
        recovery_view = self._page_at(self._index["recovery"])
        recovery_view.set_scanning(False)
        self._set_recovery_state(
            "done" if self._recovery_engine is not None else "not_run")
        self._set_status_message(
            "Recovery scan failed: %s. History still shows live records "
            "only; try again." % message)


    # --- export ------------------------------------------------------------
    #
    # One entry point: the nine format cards, the bundle card, the menu items
    # and every per-view button go through _start_export, the only place
    # that passes a chosen path to a writer. Refusing the evidence folder is
    # therefore checked in one place.

    def _export_view(self, view, key):
        """One "Export view (N)" button.

        The button's text, set by RecordsView._update_count() when the row
        set last changed, is compared with the model's current count; if
        the rows changed in between (a recovery merge, say), the export is
        refused rather than writing a file with a different count from the
        one shown.

        Refuses first when an export is already running (see
        _refuse_if_export_busy).
        """
        if self._refuse_if_export_busy():
            return
        model = view.table.model()
        if model is None:
            self._set_status_message(
                "There is nothing to export from this view.")
            return
        rows = list(model.filter.visible())
        promised = _button_promised_count(view.export_button.text())
        if promised is not None and promised != len(rows):
            self._set_status_message(
                "Export not started: the view changed from %s to %s rows "
                "while the export was being prepared. Try again."
                % (format(promised, ","), format(len(rows), ",")))
            return
        if not rows and not self._confirm_empty_export(self._labels[key]):
            self._set_status_message(
                "Export cancelled: the %s view holds 0 rows under the "
                "filters in force." % self._labels[key])
            return
        scope = export_formats.scope_from_view(
            view, key, self._labels[key], model)
        scope["recovery_scan_run"] = self._recovery_engine is not None
        if key == "search":
            # The facts a search export needs: what was searched for, over
            # what scope, how much was read, and what could not be read.
            # Added only for this view, and write_view_provenance writes its
            # SEARCH section only when present, so other sidecars are
            # unchanged.
            scope.update(search_loader.export_scope(self._search_results))
        suggested = self._suggest_export_name(
            _export_name_part(view, self._labels[key]), ".csv",
            scope["is_subset"])
        path = self._choose_export_path(
            suggested, "Save %s %s of %s as CSV or Excel workbook"
            % (format(len(rows), ","), "row" if len(rows) == 1 else "rows",
               self._labels[key]),
            "CSV (*.csv);;Excel workbook (*.xlsx);;All files (*)")
        if not path:
            return
        # Kept for the status line the write handler builds: it names
        # three things a format export's own line does not -- how many
        # rows are in the file, how many the record set holds, and where
        # the filter record went.
        self._last_view_scope = scope
        job = ExportJob(
            key="view_xlsx" if path.lower().endswith(".xlsx") else "view_csv",
            path=path, rows=rows,
            columns=list(model.columns), scope=scope,
            tags_map=self._tags_map(), comments_map=self._comments_map(),
            stamp=provenance.export_stamp(
                self._evidence_or_empty(),
                provenance.view_state(model, key),
                model.rowCount(), model.filter.total_count),
            label=self._labels[key])
        self._start_export(job, card_key=None)

    def _fill_timeline(self, scan_run):
        """Every grain, from one TimelineInput, plus the nav badge.

        One function for the open-time and post-scan paths, which differ
        only in what timeline_loader.timeline_inputs was given.

        The badge counts dated records, not table rows, which change with
        the grain. It uses the key_timestamp predicate the buckets use, and
        the count line states both numbers.

        This starts a TimelineBuilder and returns; the view is told a build
        is in progress (show_building()), and _on_timeline_built finishes
        when the worker's `built` signal arrives. _cancel_pending_timeline_
        build runs first, as _open_evidence_at cancels a pending load or
        scan: a second exhibit or scan can start while a build runs.

        Called at every open and scan whether or not Timeline has been built
        (the build is off the GUI thread). Only the widget update is
        guarded: show_building() needs the real view, not the stand-in an
        unvisited Timeline still is (see _ensure_view_built), and
        _on_timeline_built has the same guard.
        """
        self._cancel_pending_timeline_build()
        view = self._built_widget("timeline")
        if view is not None:
            view.show_building()
        inputs = self._timeline_inputs
        builder = TimelineBuilder(self)
        self._timeline_builder = builder
        builder.built.connect(
            lambda rows_by_grain, notes_by_grain: self._on_timeline_built(
                inputs, rows_by_grain, notes_by_grain))
        offset = self._timeline_zone_offset()
        local = self._timeline_clock == "local" and offset is not None
        builder.build(inputs, scan_run,
                      offset_seconds=offset if local else 0,
                      clock_label=(local_clock.zone_label(offset) if local
                                   else "UTC"),
                      local=local)

    def _timeline_zone_offset(self):
        return getattr(self._parser, "derived_tz_offset_seconds", None)

    def _timeline_clock_changed(self, clock):
        """The examiner switched UTC/Local: rebuild on the background
        builder, on the new clock."""
        self._timeline_clock = clock
        if self._timeline_inputs is not None:
            self._fill_timeline(scan_run=self._recovery_engine is not None)

    def _sync_timeline_clock(self, view):
        """State the recovered zone in the header and show the clock the
        rows were built on."""
        offset = self._timeline_zone_offset()
        view.set_zone(offset, local_clock.zone_label(offset))
        view.show_clock(self._timeline_clock
                        if offset is not None else "utc")

    def _on_timeline_built(self, inputs, rows_by_grain, notes_by_grain):
        """TimelineBuilder.built's handler, run when the background build
        finishes. `inputs` is the TimelineInput the build started with
        (captured in _fill_timeline), not self._timeline_inputs, so rows and
        a badge are never applied under another exhibit's inputs.

        The nav badge is set and the result cached (self._timeline_results)
        whether or not Timeline is built: counts do not depend on a view
        existing, and the cache lets a Timeline built later
        (_push_timeline_state, from _replay_view_state) apply this result
        without another build. The four grains are pushed into the widget
        only if it is built.
        """
        self.sidebar.set_count(
            "timeline", timeline_loader.dated_record_count(inputs),
            unit=record_counts.BADGE_UNITS["timeline"])
        self._timeline_results = (inputs, rows_by_grain, notes_by_grain)
        view = self._built_widget("timeline")
        if view is None:
            return
        view.set_inputs(inputs)
        self._sync_timeline_clock(view)
        for grain, _label, _plural in timeline_loader.GRAINS:
            view.set_records_for(
                grain, rows_by_grain[grain], note=notes_by_grain[grain])

    def _fill_location(self, live_entries, carved_entries=()):
        """The nav badge, from one pass over the entries, always set, and
        the two segments, pushed into the Location view if it is built
        (_push_location_state).

        One function for the open-time and post-scan paths, which differ
        only in the carved set available (_push_location_state reads
        self._recovery_engine).

        The badge counts fixes, not places; the switcher button states the
        places ("Places (7)").
        """
        if (self._parser is not None
                and getattr(self._parser, "all_entries", None) is live_entries):
            fixes, places = derived.location(
                self._parser, self._recovery_engine if carved_entries else None,
                self._location_grouping)
        else:
            fixes = location_loader.position_fixes(
                live_entries, carved_entries, grouping=self._location_grouping)
            places = location_loader.places(fixes,
                                            grouping=self._location_grouping)
        self._location_fixes = fixes
        self._location_places = places
        self.sidebar.set_count(
            "location", len(fixes),
            unit=record_counts.BADGE_UNITS["location"])
        self._push_location_state()

    def _location_grouping_changed(self, grouping):
        """The examiner chose another grouping scale: relabel each fix's
        Place and regroup. Nothing is re-read, and the badge (fixes) does
        not change."""
        self._location_grouping = grouping
        location_loader.label_fixes(self._location_fixes, grouping)
        self._location_places = location_loader.places(
            self._location_fixes, grouping=grouping)
        self._push_location_state()

    def _copy_link(self, text, what):
        """Copy, never Open: opening a map link would send its position to
        the provider. Separate from _copy_path so the status line can name
        which kind of link was copied."""
        QGuiApplication.clipboard().setText(text)
        label = (what[:1].upper() + what[1:]) if what else "Text"
        self._set_status_message(
            "%s copied to the clipboard." % label)

    def _export_period_records(self, view):
        """The Timeline screen's second export: the records inside one
        period rather than one row per period.

        The same path as _export_header_pairs: the busy refusal first, the
        check against the button's own count, the chooser, and
        _start_export. The scope names which period the file holds.
        """
        if self._refuse_if_export_busy():
            return
        pane = getattr(view, "pane", None)
        rows = pane.visible_rows() if pane is not None else []
        if not rows:
            # pane.visible_rows() is empty in
            # TWO different states: nothing selected above, or a period
            # IS selected and the pane's own filter removed every one of
            # its rows. selected_period() re-reads the period TABLE's
            # current index, which the pane's own filter never touches --
            # so it still names the period when that is what happened,
            # and stays "" only when nothing above is selected at all.
            period = view.selected_period() if hasattr(view, "selected_period") else ""
            if period:
                self._set_status_message(
                    "The filter on this pane has removed every record in "
                    "%s — clear it and try again." % period)
            else:
                self._set_status_message(
                    "Select a period first — there are no records to export.")
            return
        promised = _button_promised_count(pane.export_button.text())
        if promised is not None and promised != len(rows):
            self._set_status_message(
                "Export not started: the list changed from %s to %s "
                "records while the export was being prepared. Try again."
                % (format(promised, ","), format(len(rows), ",")))
            return
        model = view.table.model()
        scope = export_formats.scope_from_view(
            view, "timeline", self._labels["timeline"], model)
        scope["recovery_scan_run"] = self._recovery_engine is not None
        columns = list(view.PERIOD_RECORD_COLUMNS)
        scope["columns"] = [c.label for c in columns]
        scope["column_keys"] = [c.key for c in columns]
        scope["hidden_columns"] = []
        # Set HERE, on the GUI thread, where both are already known and
        # where the status line reads them back -- the worker snapshots
        # the dict, so leaving these at scope_from_view's PERIOD counts
        # would make the sidecar describe a different file.
        scope["unit"] = "records in one period"
        # Asked of the VIEW, which re-reads it from the model at the
        # current index -- the same read _resync_pane makes, so the
        # sidecar cannot name a period the file does not hold.
        scope["period"] = view.selected_period()
        scope["picked"] = _picked_from(scope["period"], model.rowCount(),
                                       "period")
        scope["records_in_file"] = len(rows)
        scope["rows_in_file"] = len(rows)
        suggested = self._suggest_export_name(
            "webcache_period_records", ".csv", scope["is_subset"])
        path = self._choose_export_path(
            suggested, "Export the records in this period",
            "CSV (*.csv);;All files (*)")
        if not path:
            return
        self._last_view_scope = scope
        job = ExportJob(
            key="view_csv", path=path, rows=rows, columns=columns,
            scope=scope,
            tags_map=self._tags_map(), comments_map=self._comments_map(),
            stamp=provenance.export_stamp(
                self._evidence_or_empty(),
                provenance.view_state(model, "timeline"),
                len(rows), model.filter.total_count if model else len(rows)),
            label="Records in one period")
        self._start_export(job, card_key=None)

    def _export_domain_records(self, view):
        """The Domains pane's export: the records of the ONE selected
        domain, live and carved, from every container. Modelled on
        _export_period_records -- same busy refusal, same check against
        the BUTTON's promised count, same chooser and chokepoint. The rows
        carry `_record`, so write_view_csv appends each record's own raw
        fields (EntryId/Offset/Page/Confidence...) after the pane columns."""
        if self._refuse_if_export_busy():
            return
        pane = getattr(view, "pane", None)
        rows = pane.visible_rows() if pane is not None else []
        if not rows:
            domain = view.selected_domain()
            if domain:
                self._set_status_message(
                    "The filter on this pane has removed every record of "
                    "%s — clear it and try again." % domain)
            else:
                self._set_status_message(
                    "Select a domain first — there are no records to export.")
            return
        promised = _button_promised_count(pane.export_button.text())
        if promised is not None and promised != len(rows):
            self._set_status_message(
                "Export not started: the list changed from %s to %s "
                "records while the export was being prepared. Try again."
                % (format(promised, ","), format(len(rows), ",")))
            return
        model = view.table.model()
        scope = export_formats.scope_from_view(
            view, "domains", self._labels["domains"], model)
        scope["recovery_scan_run"] = self._recovery_engine is not None
        columns = list(view.MEMBER_COLUMNS)
        scope["columns"] = [c.label for c in columns]
        scope["column_keys"] = [c.key for c in columns]
        scope["hidden_columns"] = []
        scope["unit"] = "records of one domain (%s)" % view.selected_domain()
        scope["picked"] = _picked_from(None, model.rowCount(), "domain")
        scope["records_in_file"] = len(rows)
        scope["rows_in_file"] = len(rows)
        suggested = self._suggest_export_name(
            "webcache_domain_records", ".csv", scope["is_subset"])
        path = self._choose_export_path(
            suggested, "Export the records of this domain",
            "CSV (*.csv);;All files (*)")
        if not path:
            return
        self._last_view_scope = scope
        job = ExportJob(
            key="view_csv", path=path, rows=rows, columns=columns,
            scope=scope,
            tags_map=self._tags_map(), comments_map=self._comments_map(),
            stamp=provenance.export_stamp(
                self._evidence_or_empty(),
                provenance.view_state(model, "domains"),
                len(rows), model.filter.total_count if model else len(rows)),
            label="Records of one domain")
        self._start_export(job, card_key=None)

    def _export_hit_fields(self, view):
        """The Search screen's second export: every column of the one row a
        hit was found in, decoded and as stored, rather than one row per
        hit.

        The same path as _export_period_records: the busy refusal first, the
        check against the pane button's own count, the chooser, and
        _start_export. The scope names which row the file holds.
        """
        if self._refuse_if_export_busy():
            return
        pane = getattr(view, "pane", None)
        rows = pane.visible_rows() if pane is not None else []
        if not rows:
            # Two states, as in _export_period_records: nothing selected
            # above, or a hit selected and the pane's filter removed every
            # column. selected_hit_label() reads the hit table's current
            # index, which the pane's filter does not affect.
            hit = view.selected_hit_label() if hasattr(
                view, "selected_hit_label") else ""
            if hit:
                self._set_status_message(
                    "The filter on this pane has removed every column of "
                    "%s — clear it and try again." % hit)
            else:
                self._set_status_message(
                    "Select a hit first — there are no fields to export.")
            return
        promised = _button_promised_count(pane.export_button.text())
        if promised is not None and promised != len(rows):
            self._set_status_message(
                "Export not started: the list changed from %s to %s rows "
                "while the export was being prepared. Try again."
                % (format(promised, ","), format(len(rows), ",")))
            return
        model = view.table.model()
        scope = export_formats.scope_from_view(
            view, "search", self._labels["search"], model)
        scope["recovery_scan_run"] = self._recovery_engine is not None
        scope.update(search_loader.export_scope(self._search_results))
        columns = list(view.HIT_FIELD_COLUMNS)
        scope["columns"] = [c.label for c in columns]
        scope["column_keys"] = [c.key for c in columns]
        scope["hidden_columns"] = []
        # Set HERE, on the GUI thread, where both are known and where the
        # status line reads them back -- the worker snapshots the dict, so
        # leaving these at scope_from_view's HIT counts would make the
        # sidecar describe a different file.
        scope["unit"] = "columns of one table row"
        scope["searched_row"] = view.selected_hit_label()
        scope["rows_in_file"] = len(rows)
        suggested = self._suggest_export_name(
            "webcache_search_row", ".csv", scope["is_subset"])
        path = self._choose_export_path(
            suggested, "Export this row's fields",
            "CSV (*.csv);;All files (*)")
        if not path:
            return
        self._last_view_scope = scope
        job = ExportJob(
            key="view_csv", path=path, rows=rows, columns=columns,
            scope=scope,
            tags_map=self._tags_map(), comments_map=self._comments_map(),
            stamp=provenance.export_stamp(
                self._evidence_or_empty(),
                provenance.view_state(model, "search"),
                len(rows), model.filter.total_count if model else len(rows)),
            label="Fields of one searched row")
        self._start_export(job, card_key=None)

    def _export_header_pairs(self, view):
        """The HTTP Headers screen's second export: one row per header pair
        rather than one per record.

        scope["unit"] is header pairs and rows_in_file counts pairs, and the
        sidecar states both. Otherwise the same path as _export_view: the
        visible rows, the count check, the chooser, and _start_export.

        pair_export_rows() builds the pair lists here, for the visible rows
        only (see headers_loader.py on why pairs are not a row key).

        The check compares with pairs_export_button's own text, which
        promises a pair count (headers_total_pairs).

        Refuses first when an export is already running (see
        _refuse_if_export_busy).
        """
        if self._refuse_if_export_busy():
            return
        model = view.table.model()
        if model is None:
            self._set_status_message(
                "There is nothing to export from this view.")
            return
        rows = list(model.filter.visible())
        pairs = headers_total_pairs(rows)
        button = getattr(view, "pairs_export_button", None)
        promised = (_button_promised_count(button.text())
                   if button is not None else None)
        if promised is not None and promised != pairs:
            self._set_status_message(
                "Export not started: the view changed from %s to %s header "
                "pairs while the export was being prepared. Try again."
                % (format(promised, ","), format(pairs, ",")))
            return
        if not pairs and not self._confirm_empty_export(
                self._labels["headers"]):
            self._set_status_message(
                "Export cancelled: the %s view holds 0 header pairs under "
                "the filters in force." % self._labels["headers"])
            return
        scope = export_formats.scope_from_view(
            view, "headers", self._labels["headers"], model)
        scope["recovery_scan_run"] = self._recovery_engine is not None
        scope["columns"] = list(export_formats.HEADER_PAIR_COLUMNS)
        scope["column_keys"] = list(export_formats.HEADER_PAIR_COLUMNS)
        scope["hidden_columns"] = []
        # The unit and the count are set HERE, on the GUI thread, where
        # both are already known and where the status line will read them
        # back. The worker sets rows_in_file again on its own copy of the
        # scope (ExportJob snapshots the dict), so leaving it at
        # scope_from_view's record count meant the file held 7,202 pairs
        # and the status bar said "546 of 546 rows".
        scope["unit"] = "header pairs"
        scope["records_in_file"] = model.rowCount()
        scope["rows_in_file"] = pairs
        suggested = self._suggest_export_name(
            "webcache_header_pairs", ".csv", scope["is_subset"])
        path = self._choose_export_path(
            suggested, "Export header pairs", "CSV (*.csv);;All files (*)")
        if not path:
            return
        self._last_view_scope = scope
        job = ExportJob(
            key="header_pairs", path=path, rows=pair_export_rows(rows),
            scope=scope,
            stamp=provenance.export_stamp(
                self._evidence_or_empty(),
                provenance.view_state(model, "headers"),
                model.rowCount(), model.filter.total_count),
            label="HTTP header pairs")
        self._start_export(job, card_key=None)

    def _export_current_view(self):
        """Ctrl+E / Export > Export this view... -- the SAME path a click
        on the button takes, never a second one."""
        key = getattr(self, "_current", None)
        if key is None:
            return
        view = self._page_at(self._index[key])
        if getattr(view, "table", None) is None:
            self._set_status_message(
                "This view has no record table to export.")
            return
        self._export_view(view, key)

    def _export_format(self, key):
        """One format card, the bundle card, or the bundle menu item.

        Refuses first when an export is already running (see
        _refuse_if_export_busy).
        """
        if self._refuse_if_export_busy():
            return
        fmt = export_formats.BY_KEY.get(key)
        if fmt is None:
            return
        ok, reason = export_formats.availability(self._capabilities())[key]
        if not ok:
            # The card already carries this sentence; repeating it in the
            # status bar is what covers the MENU route, which has no card
            # for an examiner to read.
            self._export_view_widget().report_failed(key, reason)
            self._set_status_message(reason)
            return
        if fmt.writes == "directory":
            path = self._choose_export_directory()
        else:
            path = self._choose_export_path(
                self._suggest_export_name(fmt.default_basename,
                                           fmt.extension, False),
                "Export %s" % fmt.title,
                "%s (*%s);;All files (*)" % (fmt.title, fmt.extension))
        if not path:
            return
        try:
            job = self._format_job(fmt, path)
        except Exception as exc:  # noqa: BLE001 -- shown, never swallowed
            # A failure building the offline report's snapshot is reported
            # on screen; the bundle continues without it (see _format_job).
            reason = "The offline report could not be prepared: %s" % exc
            self._export_view_widget().report_failed(key, reason)
            self._set_status_message(reason)
            return
        self._start_export(job, card_key=key)

    def _package_snapshot(self):
        """Everything the offline HTML report carries, read from the views
        as they stand. Builds any record view not yet built, which takes a
        moment, so the cursor waits and the status bar says why before the
        work starts."""
        from ..views.records_view import RecordsView, member_record_columns
        columns = member_record_columns()
        RecordsView.annotate_basis(columns)
        previous = self.status_message()
        self._set_status_message(
            "Preparing the offline report: reading every view…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return package_snapshot.snapshot_from_window(
                self, [html_package.PackageColumn.from_column(c)
                       for c in columns])
        finally:
            QApplication.restoreOverrideCursor()
            self._set_status_message(previous)

    def _format_job(self, fmt, path):
        entries = list(getattr(self._parser, "all_entries", None) or [])
        return ExportJob(
            key=fmt.key, path=path, entries=entries,
            recovered=self._recovered_artifacts(),
            artifacts=self._artifacts(), stats=self._report_statistics(),
            parser=self._parser, case_meta=self._case_meta(),
            db_info=self._db_summary_info or {},
            tags_map=self._tags_map(), comments_map=self._comments_map(),
            evidence_set=getattr(self, "_evidence_set", None),
            # WITHOUT THESE AN ENABLED CARD WRITES AN EMPTY FILE, which is
            # worse than a greyed one: a greyed card says it cannot run,
            # an empty file looks like an answer. _rows_written already
            # special-cases the location formats to len(job.location_fixes),
            # and loc_csv is sidecar=False because the engine writes its
            # own.
            location_fixes=self._location_fixes,
            places=self._location_places,
            caps=self._capabilities(), label=fmt.title,
            scope={"recovery_scan_run": self._recovery_engine is not None},
            package=self._job_package(fmt.key))

    def _job_package(self, key):
        """The offline report's snapshot for the formats that write it. For
        the HTML card a failure propagates to the card's handler, which
        reports it; for the bundle the report member is SKIPPED with
        HTML_NO_SNAPSHOT and every other format is still written."""
        if key == "html":
            return self._package_snapshot()
        if key == "bundle":
            try:
                return self._package_snapshot()
            except Exception:  # noqa: BLE001 -- the manifest says SKIPPED
                return None
        return None

    # --- choosing where it goes --------------------------------------------

    def _choose_export_path(self, suggested, title, name_filter):
        """The save chooser plus the refusal. Returns "" when nothing should
        be written.

        A loop: "Choose another folder..." reopens the chooser at the safe
        path with the job kept, so a second folder inside the evidence
        directory is refused too.
        """
        start = os.path.join(export_target.default_export_dir(), suggested)
        files, dirs = export_target.evidence_paths(
            getattr(self, "_evidence_set", None), self._parser)
        while True:
            path, chosen = QFileDialog.getSaveFileName(
                self, title, start, name_filter)
            if not path:
                return ""
            path = _suffix_for_filter(path, chosen)
            reason = export_target.refuse_reason(path, files, dirs)
            if not reason:
                return path
            safe = export_target.safe_alternative(path, dirs)
            outcome, chosen = self._ask_for_a_safe_folder(reason, safe)
            if outcome == SafeFolderDialog.CHOSE_SAFE:
                return chosen
            if outcome == SafeFolderDialog.CANCELLED:
                return ""
            start = safe

    def _choose_export_directory(self):
        files, dirs = export_target.evidence_paths(
            getattr(self, "_evidence_set", None), self._parser)
        start = export_target.default_export_dir()
        while True:
            path = QFileDialog.getExistingDirectory(
                self, "Choose a folder for the case bundle", start)
            if not path:
                return ""
            reason = export_target.refuse_reason(path, files, dirs)
            if not reason:
                return path
            safe = export_target.safe_alternative(
                os.path.join(path, "webcache_case_bundle"), dirs)
            outcome, chosen = self._ask_for_a_safe_folder(reason, safe)
            if outcome == SafeFolderDialog.CHOSE_SAFE:
                return chosen
            if outcome == SafeFolderDialog.CANCELLED:
                return ""
            start = os.path.dirname(safe)

    def _ask_for_a_safe_folder(self, reason, safe):
        """A dialog, never only a status line, so a refusal is never
        mistaken for a button that did nothing (see export_dialogs.py)."""
        dialog = SafeFolderDialog(self, reason, safe)
        dialog.exec()
        outcome, chosen = dialog.outcome(), dialog.path()
        dialog.deleteLater()
        if outcome == SafeFolderDialog.CANCELLED:
            self._set_status_message(
                "Export cancelled - nothing was written.")
        return outcome, chosen

    # --- running it ---------------------------------------------------------

    def _refuse_if_export_busy(self):
        """The busy refusal, checked at the top of every export entry point
        (_export_format, _export_view, _export_header_pairs) before any
        chooser opens, and again in _start_export for its direct callers.
        """
        if self._busy_for is None:
            return False
        self._set_status_message(
            "Another operation is already running. Wait for it to "
            "finish, or cancel it, before starting an export.")
        return True

    def _export_entry_point_widgets(self):
        """Every button that can start a new export, collected on each
        call: every record view's "Export view (N)" button and HeadersView's
        "Export header pairs" button. The format cards and the bundle button
        on the Export & Report page are handled by
        ExportView.set_export_running, which adds this condition to each
        card's _sync_button.
        """
        widgets = []
        for i in range(self.stack.count()):
            view = self._page_at(i)
            btn = getattr(view, "export_button", None)
            if btn is not None:
                widgets.append(btn)
            pairs_btn = getattr(view, "pairs_export_button", None)
            if pairs_btn is not None:
                widgets.append(pairs_btn)
        return widgets

    def _start_export(self, job, card_key=None):
        """THE one chokepoint. Every export in this application arrives
        here, and nothing else anywhere hands a chosen path to a writer."""
        if self._refuse_if_export_busy():
            return
        # Set before the shared progress pair becomes visible, as in
        # _begin_load_busy_ui and _begin_recovery_busy_ui, so Cancel always
        # knows which operation it belongs to.
        self._busy_for = "export"
        self._export_key = card_key
        if card_key:
            self._export_view_widget().set_busy(card_key, True, "Writing...")
        # Every export entry point is disabled while this export runs, not
        # only the card writing.
        self._export_view_widget().set_export_running(True)
        for btn in self._export_entry_point_widgets():
            btn.setEnabled(False)
        self._load_elapsed.start()
        self._load_last_message = "Exporting %s..." % os.path.basename(job.path)
        self._set_status_message(self._load_last_message)
        self._load_progress.setVisible(True)
        self._load_cancel_button.setVisible(True)
        self._load_cancel_button.setEnabled(True)
        self._load_status_timer.start()
        runner = ExportRunner(self)
        self._export_runner = runner
        runner.progress.connect(self._on_export_progress)
        runner.written.connect(self._on_export_written)
        runner.failed.connect(self._on_export_failed)
        runner.start(job)

    def _end_export_busy_ui(self):
        """Every exit path (success, failure and cancel), so none leaves a
        progress bar showing or a card stuck on "Writing".

        The shared progress/Cancel pair is hidden only while this export
        still owns it (self._busy_for == "export"). An export does not
        prevent Open Evidence, so by the time an uninterruptible write
        finishes, a load may hold the pair; hiding it then would remove that
        load's progress bar and Cancel button.
        """
        if self._busy_for == "export":
            self._load_status_timer.stop()
            self._load_progress.setVisible(False)
            self._load_cancel_button.setVisible(False)
            self._busy_for = None
        if self._export_key:
            self._export_view_widget().set_busy(self._export_key, False)
        self._export_key = None
        # Restored unconditionally, unlike the shared progress pair above:
        # only an export disables these entry points, so no other operation
        # can have taken them over.
        self._export_view_widget().set_export_running(False)
        for btn in self._export_entry_point_widgets():
            btn.setEnabled(True)

    def _on_export_progress(self, message):
        self._load_last_message = message
        self._refresh_load_elapsed()
        if self._export_key:
            self._export_view_widget().set_busy(
                self._export_key, True, message)

    def _on_export_written(self, paths):
        paths = list(paths)
        key = self._export_key
        self._end_export_busy_ui()
        if not paths:
            self._set_status_message("Export finished but wrote nothing.")
            return
        first = paths[0]
        # Remembered only after a successful write, and the directory the
        # examiner chose (as hex_view.write_blob does).
        settings.save(last_export_dir=os.path.dirname(os.path.abspath(first)))
        if key == "bundle":
            # A bundle is a folder of files; paths[0] is the manifest, one
            # member, so the folder is what is named.
            folder = os.path.dirname(first)
            summary = ("Bundle written: %s file(s) in %s"
                       % (len(paths), os.path.basename(folder) or folder))
        else:
            count = _written_count(key, paths)
            summary = "Exported %sto %s" % (count + " " if count else "",
                                            os.path.basename(first))
            if len(paths) > 1:
                summary += " - beside it: %s" % _companions_written(paths[1:])
        if key is None:
            summary = self._view_export_summary(paths)
        self._export_view_widget().report_written(paths, summary)
        # the FULL path, in the status message and in the result bar
        # (with Copy path and Show in folder). A bundle is its folder.
        full = (os.path.dirname(os.path.abspath(first)) if key == "bundle"
                else os.path.abspath(first))
        self._set_status_message("%s — full path: %s" % (summary, full))
        self.export_result_bar.show_result(summary, full)

    def _export_bar_shown(self, shown):
        self._status_message.setVisible(not shown)
        self._db_summary_label.setVisible(not shown)

    def _show_export_folder(self, path):
        """Show in folder: the examiner's own export folder only.
        export_folder refuses anything inside an evidence folder; it is the
        one module allowed to open anything (tests/test_no_open_paths)."""
        _files, dirs = export_target.evidence_paths(
            getattr(self, "_evidence_set", None), self._parser)
        reason = export_folder.show_in_folder(path, dirs)
        if reason:
            self._set_status_message(reason)

    def _confirm_empty_export(self, label):
        """A filtered view with no rows is usually a mistake, so the
        examiner is asked before a file with no rows is written."""
        answer = QMessageBox.question(
            self, "Export 0 rows?",
            "The %s view holds 0 rows under the filters in force. Write an "
            "export (and its sidecar) that contains no rows?" % label,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _view_export_summary(self, paths):
        """The per-view line, which has to name three things a format
        export does not: how many rows went in the file, how many the view
        holds, and where the filter record went.

        A file whose unit is not records names BOTH numbers, and says
        which is which. The HTTP Headers pair export writes one row per
        header pair, so "7,202 header pairs from 546 of 546 records" is
        the only phrasing that cannot be misread as a record count -- see
        _export_header_pairs.
        """
        scope = getattr(self, "_last_view_scope", None) or {}
        sidecar = [p for p in paths if p.endswith(".provenance.txt")]
        rows = scope.get("rows_in_file", 0)
        total = scope.get("rows_in_record_set", rows)
        unit = scope.get("unit") or "rows"
        where = (" - filters recorded in %s" % os.path.basename(sidecar[0])
                 if sidecar else "")
        if scope.get("picked"):
            # One row picked from a summary list (a period, a domain): the
            # list's own size counts periods or domains, never records.
            return ("Exported %s %s (%s) to %s%s"
                    % (format(rows, ","), unit, scope["picked"],
                       os.path.basename(paths[0]), where))
        if unit != "rows":
            records = scope.get("records_in_file", total)
            return ("Exported %s %s from %s of %s records to %s%s"
                    % (format(rows, ","), unit, format(records, ","),
                       format(total, ","), os.path.basename(paths[0]), where))
        return ("Exported %s of %s rows to %s%s"
                % (format(rows, ","), format(total, ","),
                   os.path.basename(paths[0]), where))

    def _on_export_failed(self, message):
        key = self._export_key
        self._end_export_busy_ui()
        view = self._export_view_widget()
        if key:
            # The card takes the failure as its unavailable reason so the
            # text stays on screen. A message that vanishes is a message
            # that did not happen.
            view.report_failed(key, message)
        else:
            view.result_line.setText(message)
        self._set_status_message("Export failed: %s" % message)

    def _cancel_current_export(self):
        # Read BEFORE _end_export_busy_ui(), which sets self._export_key
        # to None -- this is the one fact that tells the two cancel
        # sentences below apart, and it is gone the instant that call
        # returns.
        is_bundle = self._export_key == "bundle"
        self._cancel_pending_export()
        self._end_export_busy_ui()
        if is_bundle:
            # The bundle can be interrupted between members (_run_bundle
            # checks stopping() before each; export_runner.py), so what was
            # complete is kept and the manifest records what did not run.
            # A cancelled recovery scan reports nothing, since a partial
            # scan is not the scan; a cancelled bundle keeps its complete
            # files, and says so.
            self._set_status_message(
                "Export cancelled - anything already complete was kept, "
                "and the bundle manifest records what was not written.")
        else:
            # Not interruptible: a single-format write (and a per-view CSV
            # or header-pairs export) has no interruption point inside the
            # library call (see export_runner.py), so the worker finishes
            # and the file is completed. _cancel_pending_export has
            # disconnected this runner's signals, so the outcome is stated
            # now rather than waiting for a signal that will not arrive.
            self._set_status_message(
                "Export cancel requested - this format cannot be "
                "interrupted once writing has started, so the file "
                "already in progress will finish and be kept.")

    def _cancel_pending_export(self):
        """Forget the export in progress, as _cancel_pending_load and
        _cancel_pending_recovery do. A single-format write has no
        interruption point inside its library call (export_runner.py), so
        the worker will still emit written/failed; its signals are
        disconnected and the reference dropped, so that late signal reaches
        nothing.
        """
        old = getattr(self, "_export_runner", None)
        self._export_runner = None
        if old is None:
            return
        old.cancel()
        for sig in (old.progress, old.written, old.failed):
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass

    # --- what the export page is told ---------------------------------------

    def _export_view_widget(self):
        """The Export view, built if necessary. Its callers (report_failed,
        set_busy, set_export_running, report_written) belong to an export in
        progress, which can be started from the Export menu without the page
        having been opened. _open_case_file and _refresh_export_page, which
        run on every load and scan, use the non-building
        _built_widget("export") instead (see _push_export_state)."""
        return self._ensure_view_built("export")

    def _evidence_or_empty(self):
        evidence = getattr(self, "_evidence_set", None)
        if evidence is not None:
            return evidence
        return provenance.EvidenceSet([], {}, {})

    def _capabilities(self):
        """What is loaded now, as capability tokens.

        location_fixes is passed explicitly; the parameter defaults to (),
        which would make the position formats unavailable whatever the
        exhibit holds.
        """
        return export_formats.capabilities(
            self._parser,
            list(getattr(self._parser, "all_entries", None) or []),
            self._statistics_are_available(), self._recovery_engine,
            location_fixes=self._location_fixes)

    def _compute_report_statistics(self):
        """ForensicEngine.get_statistics() over this exhibit's entries,
        computed once per load and cached.

        Not the dashboard's dict: dashboard_data.compute_dashboard_stats()
        and get_statistics() answer different questions with different
        keys (total_records against total_entries/container_types/
        top_domains) and are not interchangeable; the xlsx and PDF writers
        need these.

        Computed here, so the capability token behind
        UNAVAILABLE_REASON["stats"] reflects a real attempt.
        """
        entries = list(getattr(self._parser, "all_entries", None) or [])
        if not entries:
            return None
        # None when the statistics pass fails on a damaged exhibit: the PDF
        # and HTML cards then grey out with their own reason, and every
        # other format still works.
        return derived.report_statistics(self._parser)

    def _report_statistics(self):
        return self._report_stats

    def _statistics_are_available(self):
        return self._report_stats

    def _artifacts(self):
        if self._parser is None:
            return {}
        return forensic_engine.collect_artifacts(self._parser)

    def _recovered_artifacts(self):
        """What every engine export means by `recovered`: the carved
        artifacts, the structured records with a resolved container, and
        the deleted-record stubs shown in Deleted Records, which
        `engine.all_artifacts()` and `engine.structured_records` alone do
        not include.

        Empty before a scan; the bundle manifest states that no scan ran."""
        engine = self._recovery_engine
        if engine is None:
            return []
        recovered = list(engine.all_artifacts()) + list(engine.structured_records)
        # One builder with the Deleted Records screen (stub_artifact), so a
        # stub's File, Offset, Page, Confidence and container cannot read
        # differently on screen and in a file.
        for stub in getattr(engine, "tombstones", None) or ():
            recovered.append(stub_artifact(stub))
        return recovered

    # --- the user guide ---------------------------------------------------

    def show_user_guide(self, key=None):
        """The guide, at `key`'s section when it has one. One window,
        raised again rather than opened twice."""
        from .user_guide import BY_KEY, UserGuideWindow
        if getattr(self, "_guide_window", None) is None:
            self._guide_window = UserGuideWindow(self)
            self._guide_window.openScreenRequested.connect(
                self._open_screen_from_guide)
        if key in BY_KEY:
            self._guide_window.show_topic(key)
        self._guide_window.show()
        self._guide_window.raise_()
        self._guide_window.activateWindow()
        return self._guide_window

    def _save_integrity_text(self, text):
        """The Integrity screen's report, saved where the examiner chooses
        (never inside the evidence folder; see _choose_export_path). UTF-8
        with a byte-order mark, so Notepad and Excel read it as UTF-8."""
        if not text:
            return
        path = self._choose_export_path(
            self._suggest_export_name("webcache_integrity_report", ".txt",
                                      False),
            "Save integrity report", "Text (*.txt);;All files (*)")
        if not path:
            return
        try:
            with forensic_engine.atomic_write(path, encoding="utf-8-sig") as fh:
                fh.write(text)
        except OSError as exc:
            self._set_status_message(
                "The integrity report could not be saved: %s" % exc)
            return
        self._set_status_message(
            "Integrity report saved to %s — full path: %s"
            % (os.path.basename(path), path))

    def _open_screen_from_guide(self, key):
        """The guide's "Open this screen": navigate and bring the main
        window forward; the guide stays open beside it."""
        self._guarded_go_to(key)
        self.raise_()
        self.activateWindow()

    def _current_key(self):
        index = self.stack.currentIndex()
        for key, i in self._index.items():
            if i == index:
                return key
        return None

    # --- the examiner's notes: tags and comments -------------------------

    def _wire_case_notes(self, widget):
        """Every record grid a view holds offers Tag and Add a comment on
        a right-click, over the rows it acts on."""
        for table in widget.findChildren(RecordsTable):
            table.notes_provider = self._notes_for_rows
            table.tagRequested.connect(self._tag_rows)
            table.commentRequested.connect(self._comment_rows)
        pane = getattr(widget, "details_pane", None)
        if pane is not None:
            pane.case_provider = lambda: (
                self._case, self._case_meta().get("examiner", ""))
            pane.openRequested.connect(self._show_record_detail)
            pane.caseNotesChanged.connect(self._case_notes_changed)
            widget.set_details_visible(settings.get("details_pane", True))
            widget.detailsToggled.connect(self.set_details_pane)

    def _notes_for_rows(self, rows):
        if self._case is None:
            return None
        taggable = [r for r in rows if case_notes.is_taggable(r)]
        return (case_notes.known_tags(self._case),
                case_notes.tag_counts(self._case, taggable), len(taggable))

    def _tag_rows(self, rows, tag, on):
        if self._case is None:
            self._set_status_message(case_notes_bar.NO_CASE_TEXT)
            return 0
        if not tag:
            tag, ok = QInputDialog.getText(
                self, "New tag", "Tag the selected records as:")
            if not ok or not tag.strip():
                return 0
        changed = case_notes.set_tag(self._case, rows, tag, on)
        n = len([r for r in rows if case_notes.is_taggable(r)])
        noun = "record" if n == 1 else "records"
        self._set_status_message(
            ("Tagged %s %s “%s”." if on else "Removed “%s” from %s %s.")
            % ((format(n, ","), noun, tag.strip()) if on
               else (tag.strip(), format(n, ","), noun)))
        self._case_notes_changed()
        return changed

    def _comment_rows(self, rows):
        if self._case is None:
            self._set_status_message(case_notes_bar.NO_CASE_TEXT)
            return 0
        n = len([r for r in rows if case_notes.is_taggable(r)])
        text, ok = QInputDialog.getMultiLineText(
            self, "Add a comment",
            "Comment on the %s selected %s:" % (
                format(n, ","), "record" if n == 1 else "records"))
        if not ok or not text.strip():
            return 0
        added = case_notes.add_comment(self._case, rows, text,
                                       self._case_meta().get("examiner", ""))
        self._set_status_message("Comment added to %s %s." % (
            format(added, ","), "record" if added == 1 else "records"))
        self._case_notes_changed()
        return added

    def _case_notes_changed(self):
        """A tag or comment was saved somewhere. Views that show notes
        re-read them; the next export carries them."""
        self._push_tagged_state()

    def _suggest_export_name(self, basename, extension, is_subset):
        """export_target.suggest_name with this case's number."""
        return export_target.suggest_name(
            basename, extension, is_subset,
            case_number=self._case_meta().get("case_number", ""))

    def _case_meta(self):
        return dict(self._case.all_meta()) if self._case is not None else {}

    def _tags_map(self):
        """Passed into every export that accepts it, so build_entry_row's
        Tags and Analyst comments columns are filled."""
        return self._case.all_tags() if self._case is not None else {}

    def _comments_map(self):
        return self._case.all_comments() if self._case is not None else {}

    def _case_meta_changed(self, key, value):
        if self._case is not None:
            self._case.set_meta(key, value)

    def _copy_path(self, path):
        """Copy, never Open: a path this application shows names a location
        on the examined machine."""
        QGuiApplication.clipboard().setText(path)
        self._set_status_message("Path copied to the clipboard.")

    def _open_case_file(self, evidence_set):
        """Close the previous exhibit's case file, open this one's, and set
        the Export page's state if the page is built (_push_export_state; the
        non-building lookup, so Export is not built on every Open Evidence).
        If Export is built later, _ensure_view_built applies the same state
        from self._case/self._case_opened_ever.

        A None case file (unwritable app directory, corrupt file) is not an
        error: the page says metadata is stored in the case file, and the
        fields stay disabled.
        """
        if self._case is not None:
            try:
                self._case.close()
            except Exception:                          # noqa: BLE001
                pass
            self._case = None
        self._case = case_store.open_case(evidence_set)
        case_store.record_open(self._case, evidence_set)
        self._case_opened_ever = True
        self._push_export_state()

    def show_case_folder(self):
        """File > Case files folder (shell/case_folder.py). A folder change
        closes the open case file first -- a copy of an open database can
        be torn -- and opens this exhibit's case file in the new folder."""
        from .case_folder import CaseFolderDialog
        evidence = getattr(self, "_evidence_set", None)
        dirs = sorted({str(pathlib.Path(f).parent)
                       for f in (getattr(evidence, "files", None) or [])})
        dialog = CaseFolderDialog(evidence_dirs=dirs,
                                  before_change=self._close_case_file,
                                  on_changed=self._reopen_case_file,
                                  parent=self)
        self._case_folder_dialog = dialog
        dialog.exec()

    def _close_case_file(self):
        export_view = self._page_at(self._index["export"])
        flush = getattr(export_view, "flush_case_meta", None)
        if callable(flush) and self._case is not None:
            flush()
        if self._case is not None:
            try:
                self._case.close()
            except Exception:                          # noqa: BLE001
                pass
            self._case = None

    def _reopen_case_file(self):
        evidence = getattr(self, "_evidence_set", None)
        if evidence is not None:
            self._open_case_file(evidence)

    def _refresh_export_page(self):
        """Coverage and availability, recomputed in the same pass that
        updates every other view, never on a timer or on paint.
        self._report_stats is recomputed whether or not the Export page is
        built, because _capabilities()/_recovered_artifacts() and every
        format-availability check read it. _push_export_coverage updates the
        page if it is built, reading the recovered count from
        self._recovery_engine.
        """
        self._report_stats = self._compute_report_statistics()
        self._push_export_coverage()

    # --- column state ------------------------------------------------------

    def _restore_column_state(self, key, table):
        """Apply a saved column layout the first time `key`'s records are
        set, not again, so widths changed this session are kept when a
        second exhibit opens. self._column_state_restored is the one-shot
        gate, empty at construction.

        Guarded like _restore_geometry: a truncated or hand-edited entry
        leaves the table's auto-fit widths (from RecordsTable.set_records)
        in place. The entry also carries the column signature saved with it
        (see _collect_column_state), passed to
        RecordsTable.restore_column_state(), so a layout saved for a
        different column set is not applied (see that method). An entry
        without a "columns" signature is skipped.
        """
        if key in self._column_state_restored:
            return
        self._column_state_restored.add(key)
        stored = settings.get("column_state", {})
        entry = stored.get(key) if isinstance(stored, dict) else None
        if not isinstance(entry, dict):
            return
        raw, columns = entry.get("state"), entry.get("columns")
        if not raw or not isinstance(columns, list):
            return
        try:
            state = bytes.fromhex(raw)
        except (ValueError, TypeError):
            return
        table.restore_column_state(state, signature=tuple(columns))

    def _collect_column_state(self):
        """Per view, keyed by view name, since each view has its own columns.
        Only a real RecordsTable's state is captured: an unopened view is a
        stand-in with no header, and Export & Report and Integrity have no
        record table.

        Each entry carries the column signature (RecordsTable.
        column_signature(): the columns showing at close, for whichever
        segment was last shown) with the header state, so a later restore
        can refuse a differently shaped header (see _restore_column_state).

        Starts from the settings on disk, so a view not opened this session
        keeps its saved layout. settings.load() deep-copies DEFAULTS (see
        settings.py), so modifying the dict cannot change
        DEFAULTS["column_state"].
        """
        state = settings.get("column_state", {})
        state = dict(state) if isinstance(state, dict) else {}
        for key, index in self._index.items():
            table = getattr(self._page_at(index), "table", None)
            save = getattr(table, "save_column_state", None)
            if callable(save):
                state[key] = {"state": save().hex(),
                              "columns": list(table.column_signature())}
        return state

    # --- lifecycle -------------------------------------------------------

    def closeEvent(self, event):
        # window_maximized is saved separately from the geometry blob: Qt
        # refuses a whole blob whose stored screen width differs from the
        # current screen (common when docking a laptop), and the maximized
        # state is still meaningful on any screen.
        settings.save(window_geometry=bytes(self.saveGeometry()).hex(),
                       window_maximized=self.isMaximized(),
                       column_state=self._collect_column_state())
        # A pending case-metadata keystroke must not be lost to a 400ms
        # timer that never fired because the window closed first -- the
        # same reason settings.save() is called here unconditionally.
        export_view = self._page_at(self._index["export"])
        flush = getattr(export_view, "flush_case_meta", None)
        if callable(flush) and self._case is not None:
            flush()
        if self._case is not None:
            try:
                self._case.close()
            except Exception:                          # noqa: BLE001
                # Closing a SQLite handle never stops the window closing, as
                # settings.save() above ignores an unwritable settings path.
                pass
            self._case = None
        # Parked views have no parent; they go with the window.
        for page, _stand in self._parked.values():
            page.deleteLater()
        self._parked.clear()
        super().closeEvent(event)
