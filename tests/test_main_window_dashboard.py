"""Wiring: the Dashboard is a real view, receives real
figures when evidence loads, every figure drills through, and a
completed recovery scan folds carved rows into it -- the same end-to-end
discipline test_main_window_records_views.py/test_recovery_wiring.py
already prove for the other views, kept in its own file for the same
"additive diff" reason test_main_window_records_views.py's own docstring
gives.
"""
import pytest

from webcache.provenance import CONTAINER_NOT_DETERMINABLE, EvidenceSet
from webcache.shell.main_window import MainWindow
from webcache.views.dashboard import DashboardView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def _dashboard(win):
    return win._ensure_view_built("dashboard")


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                       {_EVIDENCE_PATH: "a" * 64})


class _FullParser:
    """Enough of WebCacheParser's surface for get_statistics() to compute
    real figures: two live History entries (one InPrivate) sharing a
    domain, one Cookies entry on a second domain."""

    def __init__(self):
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.all_entries = [
            {"Url": "https://example.com/a", "CleanUrl": "https://example.com/a",
             "ContainerType": "History", "IsInPrivate": True,
             "FileSize": 1000, "AccessCount": 2, "IsLocalFile": False},
            {"Url": "https://example.com/b", "CleanUrl": "https://example.com/b",
             "ContainerType": "History", "IsInPrivate": False,
             "FileSize": 2000, "AccessCount": 5, "IsLocalFile": False},
            {"Url": "https://other.example/c", "CleanUrl": "https://other.example/c",
             "ContainerType": "Cookies", "IsInPrivate": False,
             "FileSize": 0, "AccessCount": 0, "IsLocalFile": False},
        ]
        self.containers_meta = [
            {"ContainerId": 1, "Name": "History", "HasTable": True, "RecordCount": 2},
            {"ContainerId": 2, "Name": "Cookies", "HasTable": True, "RecordCount": 1},
        ]
        self.container_type_map = {1: "History", 2: "Cookies"}

    def get_container_type(self, cid):
        return self.container_type_map.get(cid, "Unknown")

    def get_database_info(self):
        return {"path": self.db_path, "file_size": 4096,
               "table_count": 10, "container_count": 2,
               "total_entries": len(self.all_entries)}


class _MinimalParser:
    """No all_entries/get_database_info at all -- mirrors
    test_main_window_records_views.py's own _MinimalParser: proves the
    wiring degrades to the honest no-evidence state instead of crashing."""

    def __init__(self):
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.all_entries = []
        self.containers_meta = []
        self.container_type_map = {}


class _FakeRecoveryEngine:
    """Mirrors test_recovery_wiring.py's own _FakeEngine -- the two
    attributes carved_history_rows()/deleted_records_rows() actually
    read."""

    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = structured_records or []
        self._artifacts = artifacts or []

    def all_artifacts(self):
        return self._artifacts


def _history_carved_record(url):
    return {
        "Url": url, "CleanUrl": url, "ContainerType": "History",
        "SPS_PageTitle": "", "ModifiedTime_raw": 0, "AccessedTime_raw": 0,
        "CreationTime_raw": 0, "SPS_LastVisitLocal_raw": None,
        "SPS_VisitCount": None, "AccessCount": 1, "Flags": 0,
        "Source": "WebCacheV01.dat", "Offset": 1024, "Page": 3,
        "RecoverySource": "Structured record reconstruction",
        "Confidence": "high",
    }


# --- the nav key itself: a real view, not the placeholder -----------------

def test_dashboard_nav_shows_a_real_view_not_the_placeholder(win):
    assert isinstance(_dashboard(win), DashboardView)


def test_caveat_is_set_from_nav_sections(win):
    assert _dashboard(win).caveat._text.text() == win.caveat_for("dashboard")


# --- before any exhibit: the honest empty state, not fabricated zeros -----

def test_dashboard_starts_at_dashes_before_any_exhibit_is_open(win):
    assert _dashboard(win).chip_records.value() == "—"


# --- evidence load reaches the dashboard end to end ------------------------

def test_evidence_load_populates_the_five_chips(win):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    dash = _dashboard(win)
    assert dash.chip_records.value() == "3"
    assert dash.chip_tables.value() == "10"
    assert dash.chip_containers.value() == "2"
    assert dash.chip_inprivate.value() == "1"
    assert dash.chip_cache_size.value() == "2.9 KB"


def test_evidence_load_says_recovery_has_not_run(win):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    dash = _dashboard(win)
    assert dash.chip_recovered.value() == "—"
    assert "recovery not run" in dash.header._subtitle.text()


def test_evidence_load_populates_container_types_and_top_domains(win):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    dash = _dashboard(win)
    types = [r.container_type for r in dash._container_type_rows]
    assert "History" in types and "Cookies" in types
    domains = [r.domain for r in dash._domain_rows]
    assert "example.com" in domains


def test_a_parser_missing_the_modern_surface_leaves_dashboard_at_dashes_not_crashed(win):
    win._on_evidence_loaded({"rows": [], "parser": _MinimalParser()},
                            _fake_evidence_set())
    assert _dashboard(win).chip_records.value() == "—"


def test_a_parser_that_is_none_leaves_dashboard_at_dashes(win):
    win._on_evidence_loaded({"rows": [], "parser": None}, _fake_evidence_set())
    assert _dashboard(win).chip_records.value() == "—"


def test_sidebar_dashboard_count_reflects_total_records(win):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    assert win.sidebar._rows["dashboard"].count_label.text() == "3"


# --- every figure drills through, for real, through go_to ------------------

@pytest.mark.parametrize("chip_attr,target", [
    ("chip_records", "browser"),
    ("chip_tables", "browser"),
    ("chip_containers", "containers"),
    ("chip_inprivate", "history"),
    ("chip_cache_size", "downloads"),
])
def test_each_chip_click_navigates_there(win, qtbot, chip_attr, target):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    win.go_to("dashboard")
    chip = getattr(_dashboard(win), chip_attr)
    with qtbot.waitSignal(_dashboard(win).drillRequested, timeout=1000):
        chip.clicked.emit()
    assert win.current_key == target


def test_a_container_types_row_click_navigates_to_containers(win, qtbot):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    win.go_to("dashboard")
    row = _dashboard(win)._container_type_rows[0]
    with qtbot.waitSignal(_dashboard(win).drillRequested, timeout=1000):
        row.clicked.emit()
    assert win.current_key == "containers"


def test_a_top_domains_row_click_navigates_to_domains(win, qtbot):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    win.go_to("dashboard")
    row = _dashboard(win)._domain_rows[0]
    with qtbot.waitSignal(_dashboard(win).drillRequested, timeout=1000):
        row.clicked.emit()
    assert win.current_key == "domains"


# --- a completed recovery scan folds carved rows into the dashboard -------

def test_recovery_scan_adds_the_recovered_total_and_updates_the_note(win):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    engine = _FakeRecoveryEngine(
        structured_records=[
            _history_carved_record("https://deleted.example/x"),
            _history_carved_record("https://deleted.example/y"),
        ],
        artifacts=[{"CleanUrl": "https://carved-string.example/z",
                   "Source": "V0100123.log", "Offset": 10,
                   "RecoverySource": "log-replay", "Confidence": "low"}])
    win._on_recovery_loaded(engine)
    dash = _dashboard(win)
    assert dash.chip_records.value() == "3"      # live only
    assert dash.chip_recovered.value() == "3"    # recovered, its own chip
    assert "3 live + 3 recovered = 6" in dash.header._subtitle.text()


def test_recovery_scan_adds_a_not_determinable_container_type_row(win):
    """The one raw string carve in this scan has no resolvable
    ContainerId at all -- provenance.CONTAINER_NOT_DETERMINABLE, not a
    fabricated container name, must show up as its own Container Types
    row once the scan completes."""
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    engine = _FakeRecoveryEngine(
        artifacts=[{"CleanUrl": "https://carved-string.example/z",
                   "Source": "V0100123.log", "Offset": 10,
                   "RecoverySource": "log-replay", "Confidence": "low"}])
    win._on_recovery_loaded(engine)
    types = [r.container_type for r in _dashboard(win)._container_type_rows]
    assert CONTAINER_NOT_DETERMINABLE in types


def test_recovery_scan_never_changes_inprivate_or_cache_size(win):
    """See dashboard_data.py's own module docstring: a carved row never
    carries FileSize or an InPrivate flag, so these two chips must read
    exactly as they did right after the live-only load."""
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    dash = _dashboard(win)
    inprivate_before = dash.chip_inprivate.value()
    cache_before = dash.chip_cache_size.value()
    engine = _FakeRecoveryEngine(
        structured_records=[_history_carved_record("https://deleted.example/x")])
    win._on_recovery_loaded(engine)
    assert dash.chip_inprivate.value() == inprivate_before
    assert dash.chip_cache_size.value() == cache_before


def test_sidebar_dashboard_count_reflects_the_merge_too(win):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    engine = _FakeRecoveryEngine(
        structured_records=[_history_carved_record("https://deleted.example/x")])
    win._on_recovery_loaded(engine)
    assert win.sidebar._rows["dashboard"].count_label.text() == "4"
