"""Nav counts: every destination that CAN show a live count must get one
once evidence loads, and every destination that genuinely cannot (a
Phase-2 placeholder with no data source at all, or Integrity -- a real,
built view whose own content is source hashes and a decision log, not a
countable record set) must keep a deliberate dash rather than collapse
into a blank gap.

Before this fix, Sidebar.set_count() was only ever called for four of
the sixteen nav keys (dashboard, history, downloads, and recovery -- and
even recovery only after a scan completed, never at the moment evidence
itself loads). The other twelve rows went from an honest "nothing open
yet" dash straight to a blank the instant Sidebar.set_loaded(True) ran,
which reads as "counted, and it's zero" rather than "nobody has counted
this yet" -- see NavRow._repaint_count/set_dormant in sidebar.py.
"""
import pytest
from PySide6.QtTest import QTest

from webcache.provenance import EvidenceSet
from webcache.shell.main_window import MainWindow

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"

#: The twelve keys that were never wired at all before this fix (dashboard/
#: history/downloads/recovery are the pre-existing four).
_PREVIOUSLY_BLANK_KEYS = ["search", "timeline", "domains", "location",
                         "indicators", "iocs", "cookies", "headers",
                         "containers", "browser", "integrity", "export"]

#: Of those twelve, the ones with no SINGLE FIGURE that would mean what a
#: row count means everywhere else on this rail -- must keep showing a
#: dash, never a fabricated number.
#:
#: "search" is a real, built view and stays here anyway. A hit count
#: belongs to a KEYWORD, not to an exhibit: it is undefined until an
#: examiner types one, it changes when a text box changes rather than
#: when evidence changes, and it is already stated in the two places it
#: means something (the count line, and the "Export view (N)" button). A
#: badge would be blank before the first search, which reads as zero.
#:
#: "iocs" LEFT this list: Findings is badged with
#: the total of its six segments and the tooltip says what the number is
#: ("findings across six heuristics (not records)").
#:
#: "headers" LEFT THIS LIST when HTTP Headers became a real record-set
#: view. Keeping it here would have been the same fabrication from the
#: opposite direction: a permanent dash on a view that can count its own
#: rows says there is nothing here to count.
#:
#: "timeline" LEFT this list when the Timeline became a real view. It
#: counts the records that carry a usable timestamp -- not its own row
#: count, which changes with the grain -- so a permanent dash would say
#: there is nothing here to count.
#:
#: "location" LEFT it for the same reason. It counts the position FIXES
#: this exhibit reported -- deliberately not the places, which the
#: switcher button already states -- and ZERO is a real answer there, not
#: a dash: an exhibit whose URLs never carried a coordinate is the
#: ordinary case, and the view's own empty state says why that is a
#: legitimate result rather than a failure to parse.
_NO_SINGLE_FIGURE_KEYS = ["search", "export"]

#: Of those twelve, the ones that DO have a real, live count available --
#: must show a real number once evidence loads.
_COUNTABLE_KEYS = ["domains", "indicators", "cookies", "containers",
                   "browser", "headers", "timeline", "location"]


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                       {_EVIDENCE_PATH: "a" * 64})


def _row_text(win, key):
    return win.sidebar._rows[key].count_label.text()


def _wait_for_timeline(win, timeout_ms=10_000):
    """The Timeline badge is no longer set
    synchronously inside _on_evidence_loaded -- _fill_timeline only
    STARTS a background TimelineBuilder now (see main_window.py), and
    the badge is set from _on_timeline_built once its `built` signal
    actually lands. Pumps the real Qt event loop until that worker has
    finished, exactly like test_timeline_wiring.py's own helper of the
    same name."""
    builder = win._timeline_builder
    if builder is None or builder._worker is None:
        return
    worker = builder._worker
    elapsed = 0
    step = 10
    while worker.isRunning() and elapsed < timeout_ms:
        QTest.qWait(step)
        elapsed += step
    assert not worker.isRunning(), "timed out waiting for the timeline build"
    QTest.qWait(10)


class _FullParser:
    """Enough of WebCacheParser's own surface for every real record view
    on this nav to compute a genuine, non-zero count: two distinct
    domains (one entry also embeds a Windows SID an indicator scan will
    catch, and carries decoded HTTP headers), one cookie row and one HSTS
    row, two containers, and three raw ESE tables spread across two
    groups."""

    def __init__(self):
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.all_entries = [
            # The one entry carrying decoded HTTP headers, so the
            # HeadersView count below is a real number rather than an
            # honest zero that would prove nothing about the wiring.
            {"Url": "https://a.example/x?u=S-1-5-21-1-2-3-500",
             "CleanUrl": "https://a.example/x?u=S-1-5-21-1-2-3-500",
             "ContainerType": "History", "FileSize": 10, "AccessCount": 1,
             "IsInPrivate": False,
             "ResponseHeaders_raw": (b"HTTP/1.1 200 OK\r\n"
                                     b"Server: x\r\n\r\n"),
             "ResponseHeaders": {"_status_line": "HTTP/1.1 200 OK",
                                 "Server": "x"}},
            {"Url": "https://a.example/y", "CleanUrl": "https://a.example/y",
             "ContainerType": "History", "FileSize": 10, "AccessCount": 1,
             "IsInPrivate": False},
            {"Url": "https://b.example/z", "CleanUrl": "https://b.example/z",
             "ContainerType": "History", "FileSize": 10, "AccessCount": 1,
             "IsInPrivate": False},
        ]
        self.cookie_entries = [{
            "Domain": "a.example", "RDomain": "example.a",
            "Name": "sid", "Value": "abc", "Path": "/",
            "Expires_raw": 0, "LastModified_raw": 0,
        }]
        self.hsts_entries = [{
            "Domain": "a.example", "IncludeSubdomains": False,
            "Expires": "never", "LastTimeUsed": "", "LastTimeUsed_raw": 0,
        }]
        self.cert_entries = []
        self.containers_meta = [
            {"ContainerId": 1, "Name": "History", "HasTable": True,
             "RecordCount": 3, "Size": 100, "PartitionId": "p1",
             "Directory": "C:\\x", "LastAccessTime": "", "LastScavengeTime": ""},
            {"ContainerId": 2, "Name": "Cookies", "HasTable": True,
             "RecordCount": 1, "Size": 50, "PartitionId": "p1",
             "Directory": "C:\\x", "LastAccessTime": "", "LastScavengeTime": ""},
        ]
        self.container_type_map = {1: "History", 2: "Cookies"}

    def get_container_type(self, cid):
        return self.container_type_map.get(cid, "Unknown")

    def get_tables_grouped(self):
        return {
            "History": [{"name": "Container_1", "display_name": "Container_1",
                        "type": "History", "count": 3}],
            "Cookies": [{"name": "Container_2", "display_name": "Container_2",
                        "type": "Cookies", "count": 1},
                       {"name": "MSysObjects", "display_name": "MSysObjects",
                        "type": "System", "count": 0}],
        }


# --- before any evidence is open: every row shows the ordinary dash --------

def test_every_row_shows_a_dash_before_evidence_is_open(win):
    for key in _PREVIOUSLY_BLANK_KEYS + _NO_SINGLE_FIGURE_KEYS:
        assert _row_text(win, key) == "–"


# --- destinations that CAN have a count get a real one once loaded ---------

def test_previously_unwired_views_show_a_real_count_once_evidence_loads(win):
    """The regression this defect names: dashboard/history/downloads/
    recovery were already wired; domains, indicators, cookies, containers
    and browser were not, despite each having real live data by the time
    _on_evidence_loaded returns."""
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    # "timeline" is the one countable key
    # whose badge is no longer set synchronously here -- see
    # _wait_for_timeline's own docstring.
    _wait_for_timeline(win)
    for key in _COUNTABLE_KEYS:
        text = _row_text(win, key)
        assert text != "–", "%r should show a live count, not the dormant dash" % key
        assert text != "", "%r must not go blank once evidence has loaded" % key


def test_domains_count_matches_the_number_of_distinct_hosts(win):
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    domains_view = win._ensure_view_built("domains")
    assert _row_text(win, "domains") == format(domains_view.table.model().rowCount(), ",")
    assert domains_view.table.model().rowCount() == 2  # a.example, b.example


def test_indicators_count_matches_the_number_of_indicator_hits(win):
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    indicators_view = win._ensure_view_built("indicators")
    assert _row_text(win, "indicators") == format(
        indicators_view.table.model().rowCount(), ",")
    assert indicators_view.table.model().rowCount() >= 1  # the embedded SID


def test_cookies_count_is_the_sum_of_all_three_segments(win):
    """Cookies & HSTS is a three-segment view (cookies/hsts/certs); the
    nav badge is the WHOLE view's own total, not just whichever segment
    happens to be on screen."""
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    assert _row_text(win, "cookies") == "2"  # 1 cookie + 1 hsts + 0 certs


def test_containers_count_matches_the_number_of_containers(win):
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    assert _row_text(win, "containers") == "2"


def test_browser_count_is_the_total_number_of_raw_tables(win):
    """Table Browser has no single "row set" the way every other view
    does (its own rows are paginated per table on demand) -- the nav
    count that actually means something here is how many raw tables
    there are to look at, get_tables_grouped()'s own total."""
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    assert _row_text(win, "browser") == "3"


def test_recovery_count_is_live_from_the_moment_evidence_loads_not_only_after_a_scan(win):
    """Before this fix, "recovery" only ever got a sidebar.set_count()
    call from the recovery-merge handler -- right after Open Evidence,
    before any scan has run, its nav row was blank exactly like the
    twelve never-wired keys, even though 0 is a perfectly real, live
    count at that point (the view's own count line already says "0
    recovered record(s)")."""
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    assert _row_text(win, "recovery") == "0"


# --- destinations that genuinely have no count keep a deliberate dash ------

def test_views_with_no_single_figure_keep_the_dash_once_evidence_loads(win):
    """A destination with no one number that means what a row count means
    must never have one invented for it -- the dash has to survive going
    from dormant to loaded, not collapse into an equally-wrong blank."""
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    for key in _NO_SINGLE_FIGURE_KEYS:
        assert _row_text(win, key) == "–"
    # Findings is badged with the total of its six segments.
    assert _row_text(win, "iocs") != "–"


def test_integrity_keeps_the_dash_too_despite_being_a_real_built_view(win):
    """Integrity IS built and DOES get real data (main_window.
    _on_evidence_loaded calls integrity_view.set_data(...)) -- but hashes
    and a decision log are not a countable record set, so it belongs with
    Search and Findings for nav-count purposes specifically, not with
    domains/indicators/cookies/containers/browser. All four are real,
    built views; none of them has one number that means what a row count
    means everywhere else on this rail."""
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    assert _row_text(win, "integrity") == "–"


# --- a badge's figure is copyable -----------------------------------------

def _badge_menu(row):
    build = getattr(row, "build_context_menu", None)
    assert build is not None, "NavRow offers no right-click menu"
    return build()


def test_right_click_copies_a_badges_displayed_count(qtbot):
    from PySide6.QtGui import QGuiApplication
    from webcache.shell.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    w.sidebar.set_loaded(True)
    w.sidebar.set_count("recovery", 2742)
    row = w.sidebar._rows["recovery"]
    menu = _badge_menu(row)
    assert menu is not None
    copy_action = next(a for a in menu.actions() if "copy" in a.text().lower())
    copy_action.trigger()
    assert QGuiApplication.clipboard().text() == "2,742"


def test_a_dash_is_not_offered_as_a_figure_to_copy(qtbot):
    from webcache.shell.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    row = w.sidebar._rows["recovery"]          # dormant: shows a dash
    assert _badge_menu(row) is None
