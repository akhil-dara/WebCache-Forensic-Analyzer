"""The wiring for Indicators -- the nav key "indicators" now builds a
real IndicatorsView instead of a placeholder, MainWindow._on_evidence_
loaded populates it from live entries at open, and a completed recovery
scan re-scans with carved entries folded in.

Mirrors test_domains_wiring.py's own shape and stub classes.
"""
import datetime

import pytest

from webcache.provenance import EvidenceSet
from webcache.shell.main_window import MainWindow
from webcache.views.indicators import IndicatorsView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def _indicators_view(win):
    return win._ensure_view_built("indicators")


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                       {_EVIDENCE_PATH: "a" * 64})


def _filetime(dt):
    epoch = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
    return int((dt - epoch).total_seconds() * 10_000_000)


class _FakeParser:
    def __init__(self, entries):
        self.all_entries = entries
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.containers_meta = []
        self.container_type_map = {}


def _entry(**overrides):
    base = {"Url": "https://example.com/?u=S-1-5-21-1-2-3-500",
           "CleanUrl": "https://example.com/?u=S-1-5-21-1-2-3-500"}
    base.update(overrides)
    return base


class _StubEngine:
    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = structured_records or []
        self._artifacts = artifacts or []

    def all_artifacts(self):
        return self._artifacts


def _carved_entry(**overrides):
    base = {"Url": "https://gone.example/?u=S-1-5-21-1-2-3-501",
           "CleanUrl": "https://gone.example/?u=S-1-5-21-1-2-3-501",
           "Source": "WebCacheV01.dat"}
    base.update(overrides)
    return base


# --- the nav key itself: real view, not a placeholder ----------------------

def test_indicators_nav_key_is_a_real_indicatorsview(win):
    assert isinstance(_indicators_view(win), IndicatorsView)


def test_the_view_is_reachable(win):
    win.go_to("indicators")
    assert win.current_key == "indicators"


# --- opening evidence populates it from live entries ------------------------

def test_opening_evidence_populates_indicators(win):
    parser = _FakeParser([_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    indicators = _indicators_view(win)
    assert indicators.table.model().rowCount() >= 1
    row = next(indicators.table.model().row_at(i)
              for i in range(indicators.table.model().rowCount())
              if indicators.table.model().row_at(i)["Kind"] == "Windows SID")
    assert row["Value"] == "S-1-5-21-1-2-3-500"


def test_a_parser_without_all_entries_leaves_indicators_empty_not_crashed(win):
    win._on_evidence_loaded({"rows": [], "parser": object()}, _fake_evidence_set())
    indicators = _indicators_view(win)
    assert indicators.table.model().rowCount() == 0


def test_the_count_line_mentions_live_records_before_a_scan(win):
    parser = _FakeParser([_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    text = _indicators_view(win).line_text().lower()
    assert "not yet recovered" in text or "live" in text


# --- a completed recovery scan re-scans with carved entries folded in ------

def test_a_completed_scan_folds_carved_entries_into_indicators(win):
    parser = _FakeParser([_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())

    win._on_recovery_loaded(_StubEngine(structured_records=[_carved_entry()]))

    indicators = _indicators_view(win)
    values = {indicators.table.model().row_at(i)["Value"]
             for i in range(indicators.table.model().rowCount())}
    assert "S-1-5-21-1-2-3-500" in values
    assert "S-1-5-21-1-2-3-501" in values
