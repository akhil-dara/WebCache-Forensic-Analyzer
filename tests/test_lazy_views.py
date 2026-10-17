"""MainWindow.__init__ used to build all sixteen views into the
QStackedWidget unconditionally, before an examiner had looked at
anything. Profiled directly: 71% of MainWindow() construction time (6.49
of 9.17 seconds) is Qt style-matching every one of those widgets against
the application stylesheet as it is created -- cost proportional to how
many widgets exist, not to how many an examiner will ever open.

This pins the fix: a view is constructed the first time ANY caller asks
for it -- go_to(), a drill-through, a menu action that reaches straight
for a page nobody has visited -- and kept from then on. Two things must
both be true for that to be safe:

1. Everything MainWindow did to a view at evidence-load time or
  recovery-scan time (populate its rows, merge carved records, restore
  column widths) must still happen for a view built LATER, so it ends up
  in exactly the state it would have been in had it existed the whole
  time -- never silently empty.
2. The nav rail's own counts must not depend on whether a view happens
  to be built -- they already come from data the shell holds. Two keys
  ("search", "iocs") show a deliberate dash instead of a number, and
  that is now a statement about what a count would MEAN there rather
  than about the view being unbuilt: both are ordinary lazy views like
  every other key on this rail (see tests/test_sidebar_counts.py's
  _NO_SINGLE_FIGURE_KEYS for why each keeps its dash).
"""
import pytest

from webcache.provenance import EvidenceSet
from webcache.shell.evidence_loader import history_rows_from_parser
from webcache.shell.main_window import MainWindow, NAV_SECTIONS
from webcache.views.dashboard import DashboardView
from webcache.views.domains import DomainsView
from webcache.views.history import HistoryView
from webcache.views.indicators import IndicatorsView
from webcache.views.timeline import TimelineView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"

_ALL_KEYS = [k for _s, items in NAV_SECTIONS for k, _l, _c in items]
#: The two keys whose nav row shows a dash rather than a number. NOT a
#: statement about whether they are built: both are ordinary lazy views.
#: See tests/test_sidebar_counts.py's _NO_SINGLE_FIGURE_KEYS.
_NO_COUNT_KEYS = ("search",)
#: Every view EXCEPT dashboard -- dashboard is built at construction
#: because MainWindow.__init__ itself navigates there
#: (`self.go_to("dashboard")`, its very last line) before an examiner
#: ever touches the nav rail; that is the one destination laziness
#: cannot defer, not an exception carved out of it.
_LAZY_KEYS = [k for k in _ALL_KEYS if k != "dashboard"]


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


class _FullParser:
    """Enough of WebCacheParser's own surface for every real record view
    on this nav to compute a genuine, non-empty result: two distinct
    hosts (one entry embeds a Windows SID an indicator scan will catch,
    and carries decoded HTTP headers), one cookie row, one HSTS row, two
    containers, and one raw ESE table group."""

    def __init__(self, entries=None):
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.all_entries = entries if entries is not None else [
            {"Url": "https://a.example/x?u=S-1-5-21-1-2-3-500",
             "CleanUrl": "https://a.example/x?u=S-1-5-21-1-2-3-500",
             "ContainerType": "History", "FileSize": 10, "AccessCount": 1,
             "IsInPrivate": False,
             "ResponseHeaders_raw": b"HTTP/1.1 200 OK\r\nServer: x\r\n\r\n",
             "ResponseHeaders": {"_status_line": "HTTP/1.1 200 OK",
                                 "Server": "x"}},
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
             "RecordCount": 2, "Size": 100, "PartitionId": "p1",
             "Directory": "C:\\x", "LastAccessTime": "", "LastScavengeTime": ""},
        ]
        self.container_type_map = {1: "History"}

    def get_container_type(self, cid):
        return self.container_type_map.get(cid, "Unknown")

    def get_tables_grouped(self):
        return {"History": [{"name": "Container_1",
                             "display_name": "Container_1",
                             "type": "History", "count": 2}]}

    def get_database_info(self):
        return {"tables": 1, "containers": 1, "dirty_shutdown": False,
                "parse_log": [], "decision_log": [], "derived_tz": None}


class _StubEngine:
    """recovery_engine.RecoveryEngine's own surface, as far as the
    push-state functions read it."""

    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = structured_records or []
        self._artifacts = artifacts or []

    def all_artifacts(self):
        return self._artifacts


def _carved_entry(**overrides):
    base = {"Url": "https://gone.example/?u=S-1-5-21-1-2-3-501",
           "CleanUrl": "https://gone.example/?u=S-1-5-21-1-2-3-501",
           "Source": "WebCacheV01.dat", "ContainerType": "History"}
    base.update(overrides)
    return base


# --- construction is deferred to first navigation --------------------------

def test_only_dashboard_is_built_at_construction(win):
    """Every other real view is some stand-in, never the actual view
    class -- checked by class identity, not just `.table`, so a stand-in
    that happens to grow a `.table` later could not fake a pass."""
    for key in _LAZY_KEYS:
        widget = win.stack.widget(win._index[key])
        assert not isinstance(widget, (DomainsView, HistoryView, IndicatorsView)), (
            "%r was built eagerly, defeating the whole point" % key)


def test_dashboard_is_already_real_because_init_navigates_there(win):
    assert isinstance(win.stack.widget(win._index["dashboard"]), DashboardView)


def test_the_sixteen_nav_destinations_are_still_all_present_in_order(win):
    """The nav rail itself must not thin out just because the views
    behind it are not all built yet."""
    assert win.nav_keys == _ALL_KEYS
    assert len(_ALL_KEYS) == 17


def test_navigating_to_a_view_builds_it(win):
    assert not isinstance(win.stack.widget(win._index["indicators"]), IndicatorsView)
    win.go_to("indicators")
    assert isinstance(win.stack.widget(win._index["indicators"]), IndicatorsView)


def test_a_built_view_is_never_rebuilt(win):
    """State preservation (filter/sort/scroll/column widths) depends on
    the SAME object surviving every future go_to() -- see
    _ensure_view_built's own docstring: a second ask is a plain lookup."""
    win.go_to("indicators")
    first = win.stack.widget(win._index["indicators"])
    win.go_to("dashboard")
    win.go_to("indicators")
    assert win.stack.widget(win._index["indicators"]) is first


def test_filter_text_survives_navigating_away_and_back(win):
    """The property an earlier audit specifically praised this port for
    keeping (views built once and kept, unlike the earlier version which
    rebuilt and lost this) -- must not regress just because construction
    now happens later."""
    win.go_to("indicators")
    view = win.stack.widget(win._index["indicators"])
    view.filter_box.setText("example")
    win.go_to("dashboard")
    win.go_to("indicators")
    assert win.stack.widget(win._index["indicators"]).filter_box.text() == "example"


# --- sidebar counts never depend on the view existing -----------------------

def _row_text(win, key):
    return win.sidebar._rows[key].count_label.text()


def test_sidebar_counts_a_never_visited_view_from_evidence_alone(win):
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    for key in ("domains", "indicators", "cookies", "containers", "browser",
               "headers", "location"):
        assert not isinstance(win.stack.widget(win._index[key]),
                              (DomainsView, IndicatorsView)), (
            "%r must not have been built just to count it" % key)
        text = _row_text(win, key)
        assert text not in ("", "–"), "%r should show a live count" % key


def test_timeline_count_lands_from_the_background_build_without_the_view(win):
    """Timeline is the one count that is not synchronous even at open
    time (see main_window._fill_timeline's own docstring: the build runs
    off the GUI thread whether or not the view is built) -- proved
    separately from every other synchronous count above, by pumping the
    event loop for the SAME background build test_sidebar_counts.py's
    own _wait_for_timeline waits for, never by building the view."""
    from PySide6.QtTest import QTest
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    builder = win._timeline_builder
    assert builder is not None, "the background build must start at open time"
    worker = builder._worker
    elapsed = 0
    while worker.isRunning() and elapsed < 10_000:
        QTest.qWait(10)
        elapsed += 10
    QTest.qWait(10)
    assert not isinstance(win.stack.widget(win._index["timeline"]), TimelineView), (
        "timeline must not have been built just to count it")
    text = _row_text(win, "timeline")
    assert text not in ("", "–"), "timeline should show a live count once built"


def test_the_two_dashed_rows_keep_their_dash_across_a_load(win):
    """The dash is a claim about what a single number would MEAN on
    those two rows, not about whether the view behind them exists -- so
    it has to survive a load exactly as it did when they were unbuilt
    stubs. See tests/test_sidebar_counts.py for each row's own reason."""
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    for key in _NO_COUNT_KEYS:
        assert _row_text(win, key) == "–"
    # Findings left the dashed set; it carries the total of its six
    # segments whether or not the view has been built.
    assert _row_text(win, "iocs") != "–"


# --- a view built AFTER evidence loaded gets the SAME data it would have --
# --- gotten had it existed the whole time -----------------------------------

def test_a_view_built_after_evidence_loaded_shows_the_live_rows(win):
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    win.go_to("indicators")
    view = win.stack.widget(win._index["indicators"])
    assert view.table.model().rowCount() >= 1
    row = next(view.table.model().row_at(i)
              for i in range(view.table.model().rowCount())
              if view.table.model().row_at(i)["Kind"] == "Windows SID")
    assert row["Value"] == "S-1-5-21-1-2-3-500"


def test_a_view_built_after_evidence_loaded_matches_the_sidebar_count(win):
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    win.go_to("domains")
    view = win.stack.widget(win._index["domains"])
    assert _row_text(win, "domains") == format(view.table.model().rowCount(), ",")
    assert view.table.model().rowCount() == 2


def test_integrity_built_after_evidence_loaded_carries_the_database_info(win):
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    win.go_to("integrity")
    view = win.stack.widget(win._index["integrity"])
    assert view._info == parser.get_database_info()


# --- a view built AFTER a completed recovery scan shows the merged set ----

def test_a_view_built_after_a_scan_shows_merged_carved_records(win):
    """The carved-data risk: a view built after BOTH evidence-load and a recovery scan already ran
    must land in exactly the state it would have if it had existed for
    both events, not just the more recent one."""
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    carved = _carved_entry()
    engine = _StubEngine(artifacts=[carved])
    win._on_recovery_loaded(engine)
    # "indicators" was never visited before, during, or after the scan.
    win.go_to("indicators")
    view = win.stack.widget(win._index["indicators"])
    values = {view.table.model().row_at(i)["Value"]
             for i in range(view.table.model().rowCount())}
    assert "S-1-5-21-1-2-3-500" in values  # the live one
    assert "S-1-5-21-1-2-3-501" in values  # the carved one


def test_domains_built_after_a_scan_grows_by_the_carved_host(win):
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    carved = _carved_entry(Url="https://gone.example/", CleanUrl="https://gone.example/")
    engine = _StubEngine(artifacts=[carved])
    win._on_recovery_loaded(engine)
    win.go_to("domains")
    view = win.stack.widget(win._index["domains"])
    hosts = {view.table.model().row_at(i)["Domain"]
            for i in range(view.table.model().rowCount())}
    assert "gone.example" in hosts


def test_recovery_view_built_after_a_scan_shows_the_recovered_rows(win):
    parser = _FullParser()
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    carved = _carved_entry()
    engine = _StubEngine(structured_records=[carved])
    win._on_recovery_loaded(engine)
    win.go_to("recovery")
    view = win.stack.widget(win._index["recovery"])
    assert view.table.model().rowCount() >= 1
    assert view.recover_button.text() != "Recovering…"


# --- a drill-through that targets an unbuilt view builds it -----------------

def test_a_domain_drill_builds_history_if_it_was_never_visited(win):
    parser = _FullParser()
    rows = history_rows_from_parser(parser)
    win._on_evidence_loaded({"rows": rows, "parser": parser}, _fake_evidence_set())
    win.go_to("dashboard")
    assert not isinstance(win.stack.widget(win._index["domains"]), DomainsView)
    win.go_to("domains")
    domains_view = win.stack.widget(win._index["domains"])
    domains_view.drillRequested.emit("history", {"Domain": "a.example"})
    assert win.current_key == "history"
    history_view = win.stack.widget(win._index["history"])
    assert isinstance(history_view, HistoryView)
    assert history_view.table.model().rowCount() >= 1
