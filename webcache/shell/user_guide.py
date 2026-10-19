"""The user guide, inside the application: what each screen is for and
how the work that spans screens is done.

Opened from Help > User guide, and from the "?" in every screen's header
at that screen's own section. A window of its own, not a modal dialog, so
it can stay open beside the screen it describes.
"""
from collections import namedtuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from . import glyphs, help_texts, sidebar, theme

Topic = namedtuple("Topic", "key title html")


def _p(*paras):
    return "".join("<p>%s</p>" % p for p in paras)


def _ul(*items):
    return "<ul>%s</ul>" % "".join("<li>%s</li>" % i for i in items)


def _shortcuts():
    rows = "".join("<tr><td><b>%s</b></td><td>%s</td></tr>" % (k, a)
                   for k, a in help_texts.SHORTCUTS)
    return "<table cellpadding='4'>%s</table>" % rows


TOPICS = [
    Topic("start", "Getting started", _p(
        "WebCache Forensic Analyzer reads a <b>WebCacheV01.dat</b> database "
        "&mdash; the cache, history and cookie store that Windows keeps for "
        "Internet Explorer, Edge Legacy and every application that uses the "
        "WinINet stack &mdash; and presents what it holds as screens an "
        "examiner can filter, open, tag and export.",
        "<b>Open the evidence.</b> Use <i>Open Database</i> (Ctrl+O) and "
        "choose the WebCacheV01.dat. Its transaction logs (V01*.log) and "
        "checkpoint file beside it are read too. The tool states the SHA-256 "
        "of every file it reads and never writes to the evidence folder.",
        "<b>Recover deleted records.</b> When the evidence opens you are "
        "asked whether to scan for deleted records; the default is yes. The "
        "scan carves unallocated database pages and the transaction logs. "
        "It can be run again at any time from <i>Deleted Records</i>.",
        "<b>Work through the screens.</b> The left rail groups them: user "
        "activity, analysis, artifacts, recovery, the raw database, and the "
        "case. Every number in the rail is the number of rows that screen "
        "holds.")),

    Topic("dashboard", "Dashboard", _p(
        "The headline figures for the exhibit: how many live and recovered "
        "records it holds, the container types, the busiest domains and the "
        "database's own state (clean or dirty shutdown).",
        "Every figure is reproduced in the screen it came from; click a "
        "domain or a count to go there.")),

    Topic("history", "History", _p(
        "Every page or file the cache recorded as visited, one row per "
        "record, live and recovered together. Each row shows the address, "
        "the visit count and the last visit, in UTC and on the machine's "
        "local clock.",
        "<b>Quick filters</b> above the grid narrow it in one click: "
        "InPrivate only, Has search terms, Local files only, Hide duplicate "
        "copies and One row per visit. The number on each chip is how many "
        "records it keeps, so you know before clicking.",
        "A record of a page being loaded is not proof that a person read "
        "it: background refreshes and redirects load pages too.")),

    Topic("downloads", "File Access", _p(
        "Local files opened through the browser stack (file:// addresses), "
        "and, in the Downloads segment, the download records the database "
        "holds.",
        "Each file shows its path as stored and decoded, the <b>Drive</b> it "
        "was on (a letter, or the server and share of a network path) and "
        "its <b>File type</b>. Filter those two columns to answer "
        "&ldquo;was anything opened from removable media?&rdquo; or "
        "&ldquo;which documents?&rdquo;.",
        "This shows files opened through the browser, not every file opened "
        "on the machine.")),

    Topic("search", "Search", _p(
        "Searches every table and every column of the database, including "
        "tables no other screen interprets, and the recovered records. "
        "Binary values are searched as hex, ASCII/UTF-8 and UTF-16.",
        "Type a keyword and press <i>Search</i>. The scope list limits it "
        "to fewer tables; the file:// and http(s):// buttons search for "
        "those address types. Each hit shows the table, the row and the "
        "keyword in context; select a hit to see every column of its row, "
        "and double-click it to open the row in Table Browser.",
        "Search reads what the database stored, not what was typed and "
        "abandoned.")),

    Topic("timeline", "Timeline", _p(
        "Activity counted by minute, hour, day or month, on UTC or on the "
        "machine's local clock (recovered from the database itself). Each "
        "period shows its record count, a volume bar, how many records came "
        "from deleted data, the record types and the top domains.",
        "Select a period to list its records below; double-click one to "
        "open it, or use <i>Export these records</i>. <i>Go to date</i> "
        "jumps to a day.",
        "A period with no records means no cached activity, which is not "
        "the same as no activity.")),

    Topic("domains", "Domains", _p(
        "Records grouped by host: how many each domain holds, first and "
        "last seen, and the record types. Select a domain to list its "
        "records below, and export just those.",
        "One host can serve many unrelated services; a domain is a grouping, "
        "not a finding.")),

    Topic("location", "Location", _p(
        "Positions the device reported to servers, read from parameters in "
        "the stored request URLs (for example a feed request carrying "
        "latitude, longitude, accuracy and the fix time).",
        "<b>Position fixes</b> lists each position; <b>Places</b> groups "
        "them by distance (Exact, ~11 m, ~110 m, ~1.1 km); <b>Raw records</b> "
        "shows the requests they came from. Map links are copied, never "
        "opened: opening one sends the position to that provider.",
        "A device can be told to report a false position. See "
        "<i>how-location-is-found.md</i> in the documentation for the "
        "method in full.")),

    Topic("indicators", "Indicators", _p(
        "Values carried inside URLs and file paths that no column shows: a "
        "client clock in a cache-busting parameter, a GUID that names a "
        "network adapter, an account name in a profile path, a drive letter "
        "that marks removable media. Each row states the value, what it "
        "means, a confidence and why it was reported.",
        "Presence is not intent.")),

    Topic("iocs", "Findings", _p(
        "Heuristic checks across the exhibit, each in its own segment:",
        "") + _ul(
        "<b>IOC matches</b> &mdash; your watchlist terms (comma-separated, "
        "then <i>Scan</i>) and built-in rules such as .onion addresses.",
        "<b>EntryId gaps</b> &mdash; containers with holes in their EntryId "
        "sequence: consistent with deletion, with routine cache scavenging, "
        "or with an uncommitted transaction.",
        "<b>Silences</b> &mdash; long gaps in which no record holds any "
        "time this machine wrote: a visit, a cache use, a cache write or a "
        "re-check with the server.",
        "<b>Beaconing</b> &mdash; domains contacted at regular intervals.",
        "<b>Deceptive domains</b> &mdash; look-alike host names.",
        "<b>Redirect chains</b> &mdash; one address handing on to another.") +
        _p("These raise questions; none of them is a conclusion.")),

    Topic("cookies", "Cookies & HSTS", _p(
        "Cookies, HSTS entries and cached certificates, each in its own "
        "segment. A cookie shows that a site stored state in this profile, "
        "not that a page was read; an HSTS entry shows that a site asked to "
        "be reached over HTTPS.")),

    Topic("headers", "HTTP Headers", _p(
        "Records that carry stored HTTP headers, with the status, content "
        "type and server. Select a record to read its request and response "
        "headers in the pane beside the grid. <i>Export header pairs</i> "
        "writes one row per header.",
        "Headers are stored as the cache kept them, which may be a partial "
        "record.")),

    Topic("containers", "Containers", _p(
        "The database's container index. A container is one store inside "
        "the database, each with its own table: the main History, the "
        "daily and weekly MSHist history copies, Content (the cache of "
        "downloaded page resources), Cookies, DOMStore, download records "
        "and others that applications register.",
        "Each row gives the container's name, type, directory on the "
        "examined machine, last access and record count. Containers whose "
        "table no longer exists are listed too, as the index still names "
        "them. Click a container's name to open its table in Table "
        "Browser.")),

    Topic("recovery", "Deleted Records", _p(
        "Every record recovered from unallocated database pages and the "
        "transaction logs. Each row states the file it came from, the byte "
        "offset and page, the method, and a confidence.",
        "Three kinds appear: <b>structured</b> records rebuilt with their "
        "fields; <b>string carves</b>, an address found in free space with a "
        "time found near it (context, not a visit time &mdash; the "
        "Timestamp cell says which on hover); and <b>deleted-record "
        "stubs</b>, which keep only their key.",
        "<i>Run recovery again</i> repeats the scan. <i>Show bytes at the "
        "carve offset</i> in a record lets you read the source bytes and "
        "check the claim in any hex editor.")),

    Topic("browser", "Table Browser", _p(
        "Every table of the database exactly as stored, with no "
        "interpretation applied. Pick a table on the left; its rows appear "
        "on the right, 200 to a page.",
        "<b>Filter rows</b> searches the whole table, every column as "
        "shown; a time column also matches its decoded date, so typing a "
        "date finds the rows of that day. Choose a column in the list beside "
        "it to search that column only. <b>Right-click a heading</b> to "
        "filter that column as on any record grid: pick values from its "
        "list or set conditions. <b>Click a heading</b> to sort the whole "
        "table by it; click again for the other direction. Every table is "
        "filtered and sorted whole, however large. Row numbers are always "
        "the table's own.",
        "Press Enter or double-click a row to read every column of it; "
        "right-click a binary cell to view its bytes.")),

    Topic("tagged", "Tagged", _p(
        "Every record you have tagged or commented on, live and recovered, "
        "with its tags and comments first. It filters, sorts, opens and "
        "exports like any record screen; filter the Tags column to list one "
        "tag.",
        "See <i>Tags and comments</i> for how to add them.")),

    Topic("integrity", "Integrity", _p(
        "The SHA-256 of every file read, the database's own state, and the "
        "parse log: what was read, what could not be, and why. A clean parse "
        "is not a complete database: deleted data is only what recovery "
        "finds.",
        "<b>Copy report</b> and <b>Save as text&hellip;</b> take every card "
        "and the whole decision log as plain text, every hash in full. "
        "Select lines of the log and press Ctrl+C to copy just those.")),

    Topic("export", "Export & Report", _p(
        "Every format the tool writes, with a card for each. A card that "
        "cannot run says why. <i>Complete case bundle</i> writes every "
        "format into one folder with a manifest of their hashes.",
        "See <i>Exports and file formats</i> for what each file holds.")),

    Topic("filtering", "Filtering, sorting and columns", _p(
        "Every record grid works the same way.") + _ul(
        "<b>Filter these records</b> searches every column as shown "
        "(Ctrl+F).",
        "<b>The funnel on a heading</b> (or right-click the heading) filters "
        "that column: pick values from its list, or set up to two "
        "conditions. Typing in its search box selects exactly the values "
        "it finds; once you tick or untick by hand, your picks are kept "
        "through every later search, and the line under the list says how "
        "many are ticked and how many the search hides.",
        "<b>A date field's calendar</b> shows how many records each day "
        "holds, shaded by that count.",
        "<b>Click a heading</b> to sort; the arrow shows the order.",
        "<b>Columns</b> shows or hides columns; <b>Hide identical "
        "columns</b> folds away columns with one value in every row and "
        "says which.",
        "<b>Wrap</b> shows long values on several lines; a cell that holds "
        "more ends in &ldquo;+N more lines&rdquo; &mdash; click it for the "
        "whole value.",
        "<b>Clear all filters</b> (Esc) returns every row.") +
        _p("The line above the grid always states which filters are in "
           "force and how many rows they leave.")),

    Topic("record", "A record in full", _p(
        "Double-click a row, or select it and press Ctrl+Enter, to open the "
        "record: every field it carries, grouped, each with its basis badge "
        "and nothing truncated.",
        "<i>Copy field</i>, <i>Copy all fields</i> and <i>Copy as TSV</i> "
        "copy values; <i>Explain this record</i> says what each value means; "
        "<i>Show in database table</i> opens the raw row. <i>Hide empty "
        "fields</i> folds away fields with no value and says how many. "
        "Binary values open in a hex and strings viewer below the fields.")),

    Topic("notes", "Tags and comments", _p(
        "Tags and comments are your own notes on a record, kept in this "
        "exhibit's case file and carried into every export.") + _ul(
        "<b>In a record</b>: the Tags row under its title &mdash; click "
        "Relevant, Suspicious, Follow up or Not relevant to add or remove "
        "one, type a new tag and press Enter, or type a comment and press "
        "Enter. Each is saved as it is made.",
        "<b>In any grid</b>: right-click a row, or a selection of rows, and "
        "choose <i>Tag</i> or <i>Add a comment</i>.",
        "<b>All of them</b>: the <i>Tagged</i> screen lists every tagged or "
        "commented record.") +
        _p("A summary row (a domain, a period, a place) and a raw table row "
           "are not records and cannot carry a tag.")),

    Topic("formats", "Exports and file formats", _p(
        "<b>Export view</b> on any screen saves the rows shown, in the order "
        "shown, as CSV or an Excel workbook: every column, including hidden "
        "ones, then every field each record carries. A provenance file "
        "beside it records the evidence hash, the filters in force and the "
        "time.",
        "File names lead with the case number (or WebCache when none is "
        "set), name the record set they hold, and end with the UTC time of "
        "the export, for example CASE-7_History_20261017-101522Z.csv or "
        "CASE-7_File-access_20261017-101522Z.csv.",
        "From <i>Export &amp; Report</i>:") + _ul(
        "<b>Signed-report PDF</b> &mdash; provenance, method, findings and "
        "selected records; every page names the case and the evidence hash.",
        "<b>Forensic workbook</b> &mdash; every record and artifact, one "
        "sheet each, with real dates.",
        "<b>Flat CSV</b> &mdash; every field of every record, live and "
        "recovered.",
        "<b>Complete JSON</b> and <b>Case SQLite</b> &mdash; the same, for "
        "scripts and queries.",
        "<b>Raw ESE &rarr; SQLite</b> &mdash; every table copied as stored.",
        "<b>Offline HTML report</b> &mdash; every screen in one file that "
        "opens in any browser, filterable, with no network access.",
        "<b>Position fixes</b> &mdash; CSV, KML, JSON and workbook.",
        "<b>Complete case bundle</b> &mdash; all of the above in one folder "
        "with a manifest of hashes.") +
        _p("A value that begins with =, +, - or @ is written as stored; "
           "each file's provenance says how many there are, because Excel "
           "would treat them as formulas.")),

    Topic("evidence", "Evidence handling", _p(
        "The evidence is opened read-only and never written to. Nothing is "
        "saved in its folder: exports refuse it, and the case file lives "
        "with the application (File &gt; Case files folder shows where), "
        "keyed by the evidence's SHA-256.",
        "Paths shown belong to the examined machine. They are copied, never "
        "opened, and the tool makes no network request.",
        "A database left in a dirty-shutdown state is read as it is; no "
        "repair is run, because a repair writes to the evidence file.",
        "Records Windows had not yet written into the database file exist "
        "only in its transaction logs (V01.log and V01*.log). The Open "
        "dialog states when no log is beside the database.")),

    Topic("badges", "Basis badges and Origin", _p(
        help_texts.badge_legend_text().replace("\n", "<br>"))),

    Topic("shortcuts", "Keyboard shortcuts", _shortcuts()),
]

BY_KEY = {t.key: t for t in TOPICS}

#: The guide's sections, in the sidebar's order, then the work that spans
#: screens. Every topic belongs to exactly one.
GROUPS = [
    ("START HERE", ["start", "dashboard"]),
    ("USER ACTIVITY", ["history", "downloads", "search"]),
    ("ANALYSIS", ["timeline", "domains", "location", "indicators", "iocs"]),
    ("ARTIFACTS", ["cookies", "headers", "containers"]),
    ("RECOVERY", ["recovery"]),
    ("DATABASE", ["browser"]),
    ("CASE", ["tagged", "integrity", "export"]),
    ("HOW TO", ["filtering", "record", "notes", "formats", "evidence",
                "badges", "shortcuts"]),
]

#: Topics that describe a screen, with the glyph the sidebar uses for it.
SCREEN_ICONS = sidebar.NAV_ICONS

_HEADING = Qt.UserRole + 1


def _style():
    """The page's style, in the current theme's colours."""
    return ("<style>"
            "body { font-size: 11pt; color: %(text)s; }"
            "p, li { line-height: 150%%; margin: 0 0 10px 0; }"
            "ul { margin-left: 14px; }"
            "a { color: %(link)s; }"
            "td { vertical-align: top; padding: 4px 12px 4px 0; }"
            "</style>" % {"text": theme.color("text").name(),
                          "link": theme.color("primary").name()})


class UserGuideWindow(QWidget):
    """Grouped topics on the left with a search box; the page on the right,
    with a way to open the screen it describes and to step through the
    topics."""

    #: The examiner asked to open the screen a topic describes (a nav key).
    openScreenRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("WebCache Forensic Analyzer — User guide")
        self.resize(1080, 720)
        self.search_box = QLineEdit(placeholderText="Search the guide…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._filter)
        self.topic_list = QListWidget()
        self._order = []
        for group, keys in GROUPS:
            heading = QListWidgetItem(group)
            heading.setFlags(Qt.NoItemFlags)
            heading.setData(_HEADING, True)
            font = heading.font()
            font.setPointSizeF(font.pointSizeF() * 0.85)
            font.setBold(True)
            heading.setFont(font)
            heading.setForeground(theme.color("muted"))
            self.topic_list.addItem(heading)
            for key in keys:
                topic = BY_KEY[key]
                item = QListWidgetItem(topic.title)
                item.setData(Qt.UserRole, key)
                icon = SCREEN_ICONS.get(key)
                if icon:
                    item.setIcon(QIcon(glyphs.pixmap(
                        icon, theme.color("muted"), 16)))
                self.topic_list.addItem(item)
                self._order.append(key)
        self.topic_list.currentItemChanged.connect(self._show_item)

        self.title_label = QLabel()
        self.title_label.setTextFormat(Qt.PlainText)
        font = self.title_label.font()
        font.setPointSizeF(font.pointSizeF() * 1.5)
        font.setBold(True)
        self.title_label.setFont(font)
        self.open_screen_button = QPushButton("Open this screen")
        theme.mark_accent(self.open_screen_button)
        self.open_screen_button.clicked.connect(self._open_screen)
        head = QHBoxLayout()
        head.addWidget(self.title_label, 1)
        head.addWidget(self.open_screen_button)

        self.page = QTextBrowser()
        self.page.setOpenExternalLinks(False)
        self.page.setFrameShape(QFrame.NoFrame)

        self.previous_button = QPushButton("‹ Previous")
        self.next_button = QPushButton("Next ›")
        self.previous_button.clicked.connect(lambda: self._step(-1))
        self.next_button.clicked.connect(lambda: self._step(1))
        steps = QHBoxLayout()
        steps.addWidget(self.previous_button)
        steps.addStretch(1)
        steps.addWidget(self.next_button)

        right = QWidget()
        rcol = QVBoxLayout(right)
        rcol.setContentsMargins(20, 8, 20, 8)
        rcol.setSpacing(10)
        rcol.addLayout(head)
        rcol.addWidget(self.page, 1)
        rcol.addLayout(steps)

        left = QWidget()
        col = QVBoxLayout(left)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(self.search_box)
        col.addWidget(self.topic_list, 1)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([270, 810])
        root = QHBoxLayout(self)
        root.addWidget(split)
        self.show_topic(TOPICS[0].key)

    def group_titles(self):
        return [group for group, _keys in GROUPS]

    def show_topic(self, key):
        for i in range(self.topic_list.count()):
            item = self.topic_list.item(i)
            if item.data(Qt.UserRole) == key:
                item.setHidden(False)
                self.topic_list.setCurrentItem(item)
                return True
        return False

    def current_key(self):
        item = self.topic_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _open_screen(self):
        key = self.current_key()
        if key in SCREEN_ICONS:
            self.openScreenRequested.emit(key)

    def page_text(self):
        return "%s\n%s" % (self.title_label.text(), self.page.toPlainText())

    def _step(self, delta):
        key = self.current_key()
        if key in self._order:
            index = self._order.index(key) + delta
            if 0 <= index < len(self._order):
                self.show_topic(self._order[index])

    def _show_item(self, item, _previous=None):
        if item is None or item.data(Qt.UserRole) is None:
            return
        topic = BY_KEY[item.data(Qt.UserRole)]
        self.title_label.setText(topic.title)
        self.page.setHtml(_style() + topic.html)
        self.open_screen_button.setVisible(topic.key in SCREEN_ICONS)
        index = self._order.index(topic.key)
        self.previous_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(self._order) - 1)
        self.previous_button.setText(
            "‹ %s" % BY_KEY[self._order[index - 1]].title if index > 0
            else "‹ Previous")
        self.next_button.setText(
            "%s ›" % BY_KEY[self._order[index + 1]].title
            if index + 1 < len(self._order) else "Next ›")

    def _filter(self, text):
        needle = (text or "").strip().lower()
        heading, any_shown = None, False
        for i in range(self.topic_list.count()):
            item = self.topic_list.item(i)
            if item.data(_HEADING):
                if heading is not None:
                    heading.setHidden(not any_shown)
                heading, any_shown = item, False
                continue
            topic = BY_KEY[item.data(Qt.UserRole)]
            hit = (not needle or needle in topic.title.lower()
                   or needle in topic.html.lower())
            item.setHidden(not hit)
            any_shown = any_shown or hit
        if heading is not None:
            heading.setHidden(not any_shown)

