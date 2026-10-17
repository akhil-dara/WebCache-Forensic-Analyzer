"""The wiring for Domains -- the nav key "domains" now builds a real
DomainsView instead of a placeholder, MainWindow._on_evidence_loaded
populates it from live entries at open, a completed recovery scan
re-profiles it with carved entries folded in, and a Domain-column click
drills to History FILTERED to that domain (not just a navigate-and-
discard, unlike most existing single-target drills -- see domains.py's
own module docstring for why this one is different).

Mirrors test_file_access_wiring.py's own shape and stub classes.
"""
import datetime

import pytest

from webcache.provenance import EvidenceSet
from webcache.shell.main_window import MainWindow
from webcache.views.domains import DomainsView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def _domains_view(win):
    return win._ensure_view_built("domains")


def _history_view(win):
    return win._ensure_view_built("history")


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                       {_EVIDENCE_PATH: "a" * 64})


def _filetime(dt):
    epoch = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
    return int((dt - epoch).total_seconds() * 10_000_000)


_SOME_FILETIME = _filetime(datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc))


class _FakeParser:
    def __init__(self, entries):
        self.all_entries = entries
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.containers_meta = []
        self.container_type_map = {}


def _entry(**overrides):
    base = {
        "Url": "https://a.example/page",
        "ContainerType": "History",
        "FileSize": 100,
        "AccessCount": 2,
        "IsInPrivate": False,
        "ModifiedTime_raw": _SOME_FILETIME,
    }
    base.update(overrides)
    return base


class _StubEngine:
    """Mirrors test_file_access_wiring.py's own _StubEngine -- just
    .structured_records and .all_artifacts()."""

    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = structured_records or []
        self._artifacts = artifacts or []

    def all_artifacts(self):
        return self._artifacts


def _carved_entry(**overrides):
    base = {
        "Url": "https://gone.example/deleted",
        "CleanUrl": "https://gone.example/deleted",
        "ContainerType": "History",
        "FileSize": 50,
        "AccessCount": 1,
        "IsInPrivate": False,
        "ModifiedTime_raw": _SOME_FILETIME,
        "Source": "WebCacheV01.dat",
    }
    base.update(overrides)
    return base


# --- the nav key itself: real view, not a placeholder ----------------------

def test_domains_nav_key_is_a_real_domainsview(win):
    assert isinstance(_domains_view(win), DomainsView)


def test_the_view_is_reachable(win):
    win.go_to("domains")
    assert win.current_key == "domains"


# --- opening evidence populates it from live entries ------------------------

def test_opening_evidence_populates_domains(win):
    parser = _FakeParser([_entry(Url="https://a.example/1"),
                          _entry(Url="https://a.example/2"),
                          _entry(Url="https://b.example/1")])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    domains = _domains_view(win)
    assert domains.table.model().rowCount() == 2


def test_a_parser_without_all_entries_leaves_domains_empty_not_crashed(win):
    win._on_evidence_loaded({"rows": [], "parser": object()}, _fake_evidence_set())
    domains = _domains_view(win)
    assert domains.table.model().rowCount() == 0


def test_the_count_line_says_no_recovery_scan_before_one_has_run(win):
    parser = _FakeParser([_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    text = _domains_view(win).line_text().lower()
    assert "no recovery scan" in text


# --- a completed recovery scan re-profiles with carved entries folded in ---

def test_a_completed_scan_folds_carved_entries_into_domains(win):
    parser = _FakeParser([_entry(Url="https://a.example/1")])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())

    win._on_recovery_loaded(_StubEngine(
        structured_records=[_carved_entry(Url="https://gone.example/1")]))

    domains = _domains_view(win)
    assert domains.table.model().rowCount() == 2
    row = next(domains.table.model().row_at(i)
              for i in range(domains.table.model().rowCount())
              if domains.table.model().row_at(i)["Domain"] == "gone.example")
    assert row["Carved"] == 1
    assert row["OnlyCarved"] is True


def test_the_count_line_states_the_live_and_recovered_split_after_a_scan(win):
    parser = _FakeParser([_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())

    win._on_recovery_loaded(_StubEngine(
        structured_records=[_carved_entry()]))

    text = _domains_view(win).line_text().lower()
    assert "1" in text and "live" in text
    assert "1" in text and "recovered" in text


# --- drill-through: a Domain click lists that domain's records ------

def test_clicking_a_domain_selects_it_and_fills_the_records_pane(win):
    parser = _FakeParser([_entry(Url="https://a.example/1"),
                          _entry(Url="https://a.example/2"),
                          _entry(Url="https://b.example/1")])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())

    domains = _domains_view(win)
    win.go_to("domains")
    model = domains.table.model()
    row = next(i for i in range(model.rowCount())
               if model.row_at(i)["Domain"] == "a.example")
    col = [c.key for c in model.columns].index("Domain")
    domains.table.activate_cell(row, col)

    assert win.current_key == "domains"
    assert domains.selected_domain() == "a.example"
    pane = domains.pane.table.model()
    assert pane.rowCount() == model.row_at(row)["Records"] == 2


def test_a_drill_clears_a_filter_that_hides_the_domain(win):
    win._on_evidence_loaded(
        {"rows": [], "parser": _FakeParser([_entry(Url="https://a.example/1"),
                                            _entry(Url="https://b.example/1")])},
        _fake_evidence_set())
    domains = _domains_view(win)
    domains.table.model().set_text("b.example")
    win._drill_to_domain("domains", {"Domain": "a.example"})
    assert domains.selected_domain() == "a.example"
    assert domains.pane.table.model().rowCount() == 1


def test_a_non_history_drill_target_still_just_navigates(win):
    """The special-cased handler must not break drills to any OTHER
    target -- Domains has only the one Domain column today, but the
    handler is written generically on `key`, not hard-coded to assume
    History is the only destination it will ever see."""
    _domains_view(win).drillRequested.emit("browser", {"Domain": "a.example"})
    assert win.current_key == "browser"
