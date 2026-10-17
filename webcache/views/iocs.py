"""Findings: six heuristics that raise questions, never conclusions.

A RecordsView with six RecordSets, one per engine analysis (see
iocs_loader.py for which call feeds which segment):

  IOC Matches          a watchlist term, or a built-in rule.
  EntryId gaps         a hole in a container's EntryId sequence.
  Silences             a period with no recorded activity.
  Beaconing            a domain contacted at low-jitter regular
                       intervals.
  Deceptive Domains    a punycode, non-ASCII or mixed-script hostname.
  Redirect Chains      a reconstructed navigation/redirect chain, one row
                       per hop (count noun "hops").

The sidebar badge is the total of the six ("findings across six
heuristics (not records)"); each segment's count is on its switcher button
with its own noun. open_first_non_empty() opens the first segment that
holds anything.

Every "Why", "Interpretation" and "Assessment" column is the engine's own
sentence, unmodified.

Drill-downs: EntryId gaps' Container column opens the Table Browser
(_drill_container_to_browser); Beaconing's Domain column opens Domains
with that domain selected (_drill_to_domain). The other segments have no
column link:

  IOC Matches        each row is the matching record, opened with Enter
                     or a double-click like any record.
  Silences           a silence is the absence between two records; there
                     is no record to open.
  Deceptive Domains  the hostname is normalised differently from
                     History's Domain field, so a filter on it could match
                     nothing. The context menu's "Search the database for
                     this value" searches the raw tables instead.
  Redirect Chains    a hop is not linked to a record (record_kinds.
                     K_REDIRECT_HOP).

Above the switcher (_header_extra): a line stating whether this scan
covered live records only or live and recovered (set_corpus_note), and the
watchlist box. Scan emits watchlistScanRequested with the raw text;
MainWindow runs the match.
"""
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)
from PySide6.QtCore import Qt, Signal

from ..shell import glyphs, theme
from ..widgets import copyable
from ..widgets.note_line import NoteLine
from ..engine.analysis_extra import (HOST_ASSESSMENT_LOOKALIKE,
                                     HOST_ASSESSMENT_NON_LATIN)
from ..engine.forensic_engine import ENTRYID_GAP_INTERPRETATION
from ..widgets.column_spec import Column
from .records_view import RecordSet, RecordsView


def _hits_subtitle(count):
    return ("%s IOC match%s — a watchlist term, or a built-in rule "
           "(elevated-abuse-registry TLD, .onion address)."
           % (format(count, ","), "" if count == 1 else "es"))


def _gaps_subtitle(count):
    return ("%s container%s with a hole in its EntryId sequence. "
           "Consistent with deletion, with cache scavenging, or with an "
           "uncommitted transaction — this does not distinguish between "
           "them."
           % (format(count, ","), "" if count == 1 else "s"))


def _voids_subtitle(count):
    return ("%s gap%s of 24 hours or more between consecutive records. "
           "Timeline counts empty periods instead, so the totals differ. "
           "A gap describes the records, not the user's activity."
           % (format(count, ","), "" if count == 1 else "s"))


def _beacons_subtitle(count):
    return ("%s domain%s contacted at low-jitter, regular intervals — "
           "computed from live records only."
           % (format(count, ","), "" if count == 1 else "s"))


def _hosts_subtitle(count):
    return ("%s hostname%s flagged as punycode, non-ASCII or mixed-"
           "script. Each is a lead to review, not a finding."
           % (format(count, ","), "" if count == 1 else "s"))


def _hops_subtitle(count):
    return ("%s hop%s across every reconstructed redirect chain in this "
           "exhibit's URLs and headers."
           % (format(count, ","), "" if count == 1 else "s"))


#: IOC Matches before any watchlist was scanned: built-in rules have run,
#: no watchlist has.
IOC_NO_WATCHLIST_TEXT = ("No built-in rule fired on any URL here, and no "
                         "watchlist has been scanned yet: type domains or "
                         "keywords above and press Scan.")


class FindingsView(RecordsView):
    #: The typed watchlist text, sent up whenever Scan is pressed or
    #: Enter is struck in the box -- an examiner asked; MainWindow calls
    #: iocs_loader.split_watchlist()/ioc_hit_rows() with it and pushes
    #: the result back through set_records_for("ioc_hits", ...), the same
    #: "the view only says an examiner asked" split every other signal on
    #: this base already keeps.
    watchlistScanRequested = Signal(str)
    #: The watchlist text at the last Scan, or None before any.
    _scanned_watchlist = None

    #: A class default: _header_extra() runs from the base constructor,
    #: before this class's __init__ body, and PySide6 refuses an instance
    #: attribute on a QWidget whose base __init__ has not run.
    _corpus_card = None

    def __init__(self, parent=None):
        hit_columns = [
            Column("Reasons", "Reasons", 220, kind="text"),
            Column("Source", "Source", 70, kind="flag"),
            Column("CleanUrl", "URL", 380, kind="url", field="CleanUrl"),
            Column("AccessedUtc", "Time (UTC)", 165, kind="time",
                  field="KeyTimestampUTC"),
            Column("Why", "Why this was reported", 380, kind="text"),
        ]
        gap_columns = [
            Column("ContainerId", "Container ID", 100, kind="num",
                  field="ContainerId"),
            Column("ContainerName", "Container", 200, kind="text",
                  field="ContainerName",
                  on_click=lambda row: self.drillRequested.emit("browser", row)),
            Column("Live", "Live", 70, kind="num"),
            Column("Missing", "Missing", 80, kind="num"),
            Column("Recovered", "Recovered", 90, kind="num"),
            # the same sentence on every row -- stated once, here; the
            # per-row column is optional (hidden) and every export writes it.
            Column("GapRuns", "Gap runs", 80, kind="num",
                  note="Interpretation: " + ENTRYID_GAP_INTERPRETATION),
            Column("Interpretation", "Interpretation", 380, kind="text",
                  optional=True),
        ]
        void_columns = [
            Column("From", "From", 165, kind="text"),
            Column("To", "To", 165, kind="text"),
            Column("Length", "Length", 110, kind="text", sort_by="GapHours"),
            Column("GapHours", "Gap (hours)", 110, kind="num"),
        ]
        beacon_columns = [
            Column("Domain", "Domain", 220, kind="url", field="Domain",
                  on_click=lambda row: self.drillRequested.emit("domains", row)),
            Column("Events", "Events", 70, kind="num"),
            Column("MeanIntervalSec", "Mean interval (s)", 140, kind="num"),
            Column("IntervalCV", "Jitter (CV)", 100, kind="num"),
            Column("FirstSeen", "First seen", 165, kind="text"),
            Column("LastSeen", "Last seen", 165, kind="text"),
        ]
        host_columns = [
            Column("Host", "Hostname as stored", 260, kind="text"),
            Column("Decoded", "Decoded (real characters)", 240, kind="text"),
            Column("Skeleton", "Looks like", 200, kind="text"),
            Column("Records", "Records", 80, kind="num"),
            Column("Why", "Why it was flagged", 320, kind="text",
                  note=("Assessment, when something indicates imitation: "
                        + HOST_ASSESSMENT_LOOKALIKE + "\n\n"
                        "Assessment, when the name is only not Latin "
                        "script: " + HOST_ASSESSMENT_NON_LATIN)),
            Column("Assessment", "Assessment", 320, kind="text",
                  optional=True),
        ]
        hop_columns = [
            Column("Chain", "Chain", 60, kind="num"),
            Column("Step", "Step", 60, kind="num"),
            Column("Url", "URL", 380, kind="text"),
            Column("Source", "How it was recorded", 220, kind="text"),
            Column("InDb", "In this database", 130, kind="flag"),
        ]
        super().__init__(
            record_sets=[
                RecordSet("ioc_hits", "IOC Matches", hit_columns,
                          subtitle=_hits_subtitle, count_noun="hits",
                          empty_text=("No IOC matches — no built-in rule "
                                      "fired and no watchlist term matched "
                                      "any URL here.")),
                RecordSet("entryid_gaps", "EntryId gaps", gap_columns,
                          subtitle=_gaps_subtitle, count_noun="containers",
                          empty_text=("No EntryId gaps in this exhibit — "
                                      "every container's EntryId sequence "
                                      "is unbroken.")),
                RecordSet("time_voids", "Silences", void_columns,
                          subtitle=_voids_subtitle, count_noun="silences",
                          empty_text=("No silences of 24 hours or more in "
                                      "this exhibit.")),
                RecordSet("beaconing", "Beaconing", beacon_columns,
                          subtitle=_beacons_subtitle, count_noun="domains",
                          empty_text=("No low-jitter periodic domains "
                                      "found in this exhibit's live "
                                      "records.")),
                RecordSet("deceptive_hostnames", "Deceptive Domains",
                          host_columns, subtitle=_hosts_subtitle,
                          count_noun="hostnames",
                          empty_text=("No punycode, non-ASCII or "
                                      "mixed-script hostnames found in "
                                      "this exhibit.")),
                RecordSet("redirect_chains", "Redirect Chains", hop_columns,
                          subtitle=_hops_subtitle, count_noun="hops",
                          empty_text=("No recorded redirects found in "
                                      "this exhibit's URLs or headers.")),
            ],
            header_icon="shield", header_title="Findings",
            parent=parent)

    def open_first_non_empty(self):
        """Open on the first segment that holds anything, in declared
        order; stay put when every segment is empty. Returns its key."""
        for rs in self._record_sets:
            if self._segment_rows.get(rs.key):
                if rs.key != self._active_key:
                    self._switch_segment(rs.key)
                return rs.key
        return self._active_key

    # --- the corpus banner + watchlist, above the switcher ----------------

    def _header_extra(self):
        if self._corpus_card is not None:
            return self._corpus_card

        # One row and one muted line rather than a titled card, so the
        # grid starts near the top of the window.
        card = QWidget()
        column = QVBoxLayout(card)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.watchlist_box = QLineEdit(
            placeholderText="Watchlist scan: comma-separated domains or "
                            "keywords…")
        self.watchlist_box.addAction(
            glyphs.icon("search", theme.color("primary"), 15),
            QLineEdit.LeadingPosition)
        self.watchlist_box.returnPressed.connect(self._emit_scan)
        self.scan_button = QPushButton("Scan")
        theme.mark_accent(self.scan_button)
        self.scan_button.clicked.connect(self._emit_scan)
        row.addWidget(self.watchlist_box, 1)
        row.addWidget(self.scan_button)
        column.addLayout(row)

        self.corpus_label = copyable.selectable(QLabel(""))
        self.corpus_label.setWordWrap(True)
        self.corpus_label.setStyleSheet(
            "font-size: 12px; background: transparent; color: %s;"
            % theme.color("muted").name())
        self.corpus_note_line = NoteLine(self.corpus_label, card,
                                         key="corpus:IocsView")
        corpus_row = QHBoxLayout()
        corpus_row.addWidget(self.corpus_label, 1)
        corpus_row.addWidget(self.corpus_note_line.toggle, 0, Qt.AlignTop)
        column.addLayout(corpus_row)

        self._corpus_card = card
        return card

    def _emit_scan(self):
        self._scanned_watchlist = self.watchlist_box.text()
        self.watchlistScanRequested.emit(self._scanned_watchlist)

    def empty_text_for(self, rs):
        # Before any watchlist is scanned, "no watchlist term matched" is
        # vacuous: say so, and how to run one.
        if rs.key == "ioc_hits" and not (self._scanned_watchlist or "").strip():
            return IOC_NO_WATCHLIST_TEXT
        return super().empty_text_for(rs)

    def set_corpus_note(self, text):
        """State whether the segments searched live records only, or live
        and recovered. Called on every push (evidence load, and after a
        recovery scan), so a zero is never read as "not looked yet"."""
        self.corpus_label.setText(text or "")
        self.corpus_note_line._sync()

    def refresh_theme(self):
        super().refresh_theme()
        if self._corpus_card is not None:
            p = theme.PALETTES[theme.current_name()]
            self.corpus_label.setStyleSheet(
                "background: transparent; font-size: 12px; color: %s;"
                % p["muted"])
