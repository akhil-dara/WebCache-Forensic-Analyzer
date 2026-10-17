"""The wiring for Findings -- the nav key "iocs" now builds a real
FindingsView instead of a placeholder, MainWindow._on_evidence_loaded
populates all six segments from live entries at open, and a completed
recovery scan re-scans with carved entries folded in.

Mirrors test_indicators_wiring.py/test_domains_wiring.py's own shape and
stub classes; test_lazy_views.py's own late-build checks for the same
risk on this specific view (a view built AFTER evidence, or AFTER a
scan, must land in the identical state an early-built one would have).
"""
import datetime

import pytest
from PySide6.QtWidgets import QWidget

from webcache.provenance import EvidenceSet
from webcache.shell.main_window import NAV_SECTIONS, MainWindow
from webcache.views.iocs import FindingsView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
_ALL_KEYS = [k for _s, items in NAV_SECTIONS for k, _l, _c in items]


def _filetime(dt):
    return int((dt - _EPOCH).total_seconds() * 10_000_000)


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def _iocs_view(win):
    return win._ensure_view_built("iocs")


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                       {_EVIDENCE_PATH: "a" * 64})


class _FakeParser:
    def __init__(self, entries):
        self.all_entries = entries
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.containers_meta = []
        self.container_type_map = {}


def _onion_entry(**overrides):
    base = {"Url": "http://a.onion/x", "CleanUrl": "http://a.onion/x",
           "ContainerType": "History", "ContainerId": 3, "EntryId": 1}
    base.update(overrides)
    return base


def _gap_entries():
    return [_onion_entry(EntryId=1), _onion_entry(
        Url="http://a.onion/y", CleanUrl="http://a.onion/y", EntryId=3)]


class _StubEngine:
    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = structured_records or []
        self._artifacts = artifacts or []

    def all_artifacts(self):
        return self._artifacts


def _carved_hit(**overrides):
    base = {"Url": "http://b.onion/z", "CleanUrl": "http://b.onion/z",
           "Source": "WebCacheV01.dat", "ContainerId": 3, "EntryId": 2,
           "Flags": 0}
    base.update(overrides)
    return base


# --- the nav key itself: real view, not a placeholder -----------------------

def test_iocs_nav_key_is_a_real_findingsview(win):
    assert isinstance(_iocs_view(win), FindingsView)


def test_the_view_is_reachable(win):
    win.go_to("iocs")
    assert win.current_key == "iocs"


def test_none_of_the_sixteen_destinations_render_the_fallback_stub(win):
    """_make_placeholder builds a bare QWidget -- checked by EXACT type,
    not isinstance, because every real view is itself a QWidget
    subclass and isinstance would pass for either."""
    assert len(_ALL_KEYS) == 17
    for key in _ALL_KEYS:
        widget = win._ensure_view_built(key)
        assert type(widget) is not QWidget, (
            "%r still renders the placeholder fallback" % key)


# --- opening evidence populates every segment from live entries ------------

def test_opening_evidence_populates_ioc_hits(win):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser([_onion_entry()])},
                            _fake_evidence_set())
    view = _iocs_view(win)
    view._switch_segment("ioc_hits")
    assert view.table.model().rowCount() == 1
    row = view.table.model().row_at(0)
    assert "tor-onion" in row["Reasons"]
    assert row["Source"] == "live"


def test_opening_evidence_populates_entryid_gaps(win):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser(_gap_entries())},
                            _fake_evidence_set())
    view = _iocs_view(win)
    view._switch_segment("entryid_gaps")
    assert view.table.model().rowCount() == 1
    row = view.table.model().row_at(0)
    assert row["Missing"] == 1
    assert row["ContainerId"] == 3


def test_a_parser_without_all_entries_leaves_every_segment_empty_not_crashed(win):
    win._on_evidence_loaded({"rows": [], "parser": object()}, _fake_evidence_set())
    view = _iocs_view(win)
    for key in view._segments_by_key:
        view._switch_segment(key)
        assert view.table.model().rowCount() == 0


def test_the_corpus_note_mentions_live_records_before_a_scan(win):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser([_onion_entry()])},
                            _fake_evidence_set())
    text = _iocs_view(win).corpus_label.text().lower()
    assert "live" in text


# --- a completed recovery scan re-scans with carved entries folded in ------

def test_a_completed_scan_folds_a_carved_hit_into_ioc_hits(win):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser([_onion_entry()])},
                            _fake_evidence_set())
    win._on_recovery_loaded(_StubEngine(structured_records=[_carved_hit()]))

    view = _iocs_view(win)
    view._switch_segment("ioc_hits")
    sources = {view.table.model().row_at(i)["Source"]
              for i in range(view.table.model().rowCount())}
    assert sources == {"live", "carved"}


def test_a_completed_scan_updates_the_recovered_column_on_a_gap(win):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser(_gap_entries())},
                            _fake_evidence_set())
    # EntryId 2 -- inside the 1..3 gap -- shows up recovered.
    win._on_recovery_loaded(_StubEngine(structured_records=[
        _carved_hit(Url="http://a.onion/mid", CleanUrl="http://a.onion/mid",
                   EntryId=2)]))

    view = _iocs_view(win)
    view._switch_segment("entryid_gaps")
    assert view.table.model().row_at(0)["Recovered"] == 1


def test_the_corpus_note_mentions_recovered_records_after_a_scan(win):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser([_onion_entry()])},
                            _fake_evidence_set())
    win._on_recovery_loaded(_StubEngine(artifacts=[_carved_hit()]))
    text = _iocs_view(win).corpus_label.text().lower()
    assert "recovered" in text


# --- a view built late lands in the identical state an early one would ----

def test_a_view_built_after_evidence_loaded_shows_the_live_rows(win):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser([_onion_entry()])},
                            _fake_evidence_set())
    win.go_to("iocs")
    view = win.stack.widget(win._index["iocs"])
    view._switch_segment("ioc_hits")
    assert view.table.model().rowCount() == 1


def test_a_view_built_after_a_scan_shows_the_merged_set(win):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser([_onion_entry()])},
                            _fake_evidence_set())
    win._on_recovery_loaded(_StubEngine(structured_records=[_carved_hit()]))
    # never visited before, during or after the scan
    win.go_to("iocs")
    view = win.stack.widget(win._index["iocs"])
    view._switch_segment("ioc_hits")
    assert view.table.model().rowCount() == 2


# --- the watchlist scan re-runs only the ioc_hits segment ------------------

def test_typing_a_watchlist_term_and_scanning_adds_a_hit(win):
    win._on_evidence_loaded(
        {"rows": [], "parser": _FakeParser([
            {"Url": "https://tracker.example/beacon", "CleanUrl":
             "https://tracker.example/beacon", "ContainerType": "History"}])},
        _fake_evidence_set())
    view = _iocs_view(win)
    view._switch_segment("ioc_hits")
    assert view.table.model().rowCount() == 0

    view.watchlist_box.setText("tracker.example")
    view.scan_button.click()

    view._switch_segment("ioc_hits")
    assert view.table.model().rowCount() == 1
    assert "watchlist:tracker.example" in view.table.model().row_at(0)["Reasons"]


def test_scanning_does_not_disturb_the_other_five_segments(win):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser(_gap_entries())},
                            _fake_evidence_set())
    view = _iocs_view(win)
    view._switch_segment("entryid_gaps")
    before = view.table.model().rowCount()

    view.watchlist_box.setText("something-else.example")
    view.scan_button.click()

    view._switch_segment("entryid_gaps")
    assert view.table.model().rowCount() == before


# --- the two real drills ----------------------------------------------------

def test_the_container_column_drills_to_the_table_browser(win):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser(_gap_entries())},
                            _fake_evidence_set())
    view = _iocs_view(win)
    view._switch_segment("entryid_gaps")
    view.drillRequested.emit("browser", view.table.model().row_at(0))
    assert win.current_key == "browser"


def test_the_domain_column_lands_on_that_domains_records(win):
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    beacon_entries = [
        {"Url": "https://beacon.example/%d" % i,
         "CleanUrl": "https://beacon.example/%d" % i,
         "ContainerType": "History",
         "ModifiedTime_raw": _filetime(start + datetime.timedelta(seconds=300 * i))}
        for i in range(8)]
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser(beacon_entries)},
                            _fake_evidence_set())
    view = _iocs_view(win)
    view._switch_segment("beaconing")
    assert view.table.model().rowCount() == 1
    view.drillRequested.emit("domains", view.table.model().row_at(0))
    assert win.current_key == "domains"
    domains = win.stack.widget(win._index["domains"])
    assert domains.selected_domain() == "beacon.example"
    assert domains.pane.table.model().rowCount() == 8
