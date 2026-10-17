"""The wiring for Location: the nav key builds a real view with a real
count, opening evidence fills both segments, a recovery scan re-profiles
them with carved fixes folded in, and the three position exports become
available -- behind an acknowledgement, asked BEFORE the file chooser.

THE BADGE COUNTS FIXES, NOT PLACES. The switcher button already shows the
place count as "Places (7)", and a nav figure that quietly counted
something else from the one beside it is how two screens come to disagree.

THE ACKNOWLEDGEMENT IS ASKED FIRST. _refuse_if_export_busy's own note
records why: a question asked after an examiner has already chosen a
destination is a question asked too late. The same reasoning gates the
Location view's OWN "Export view" button -- that CSV carries the same
coordinates and the same map links, and gating three formats while a
fourth writes the identical data unasked is a hole, not a policy.
"""
import csv

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QFileDialog

from webcache.provenance import EvidenceSet
from webcache.shell import location_loader
from webcache.shell.export_runner import ExportWorker
from webcache.shell.main_window import MainWindow, _NO_COUNT_KEYS
from webcache.views.location import LocationView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"


def _geo_entry(entry_id=1, lat="51.5074", lon="-0.1278", **params):
    query = "clientlocation=%s|%s" % (lat, lon)
    for key, value in params.items():
        query += "&%s=%s" % (key, value)
    url = "https://tiles.example.test/v%d?%s" % (entry_id, query)
    return {"ContainerType": "History", "ContainerId": 3, "EntryId": entry_id,
            "ContainerName": "History", "Url": url, "CleanUrl": url,
            "ModifiedTime": "2024-06-15 09:00:01 UTC"}


def _plain_entry(entry_id=9):
    url = "https://www.example.test/search?q=%d" % entry_id
    return {"ContainerType": "History", "ContainerId": 3, "EntryId": entry_id,
            "ContainerName": "History", "Url": url, "CleanUrl": url,
            "ModifiedTime": "2024-06-15 09:00:01 UTC"}


class _FakeParser:
    db_path = _EVIDENCE_PATH
    source_hashes = {"WebCacheV01.dat": "0" * 64}

    def __init__(self, entries=()):
        self.all_entries = list(entries)
        self.db = None
        self.containers_meta = []
        self.container_type_map = {}


class _StubEngine:
    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = list(structured_records or [])
        self._artifacts = list(artifacts or [])

    def all_artifacts(self):
        return self._artifacts


class _FakeConsentDialog:
    recover_deleted = False
    def __init__(self, path, parent=None):
        import hashlib
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
        self.evidence_set = EvidenceSet([path], {path: 1}, {path: digest})

    def exec(self):
        return QDialog.Accepted

    def deleteLater(self):
        pass


class _SyncExportRunner(QObject):
    progress = Signal(str)
    written = Signal(list)
    failed = Signal(str)
    jobs = []

    def start(self, job):
        _SyncExportRunner.jobs.append(job)
        worker = ExportWorker(job)
        worker.progress.connect(self.progress)
        worker.written.connect(self.written)
        worker.failed.connect(self.failed)
        worker.run()

    def cancel(self):
        pass


@pytest.fixture(autouse=True)
def _reset_jobs():
    _SyncExportRunner.jobs = []
    yield


@pytest.fixture(autouse=True)
def _sync_export_runner(monkeypatch):
    """The acknowledgement gate that used to patch ExportRunner as a
    side effect of its own `ack` fixture is gone; every test in this file
    still needs a synchronous runner so a write actually happens inline."""
    from webcache.shell import main_window as mw
    monkeypatch.setattr(mw, "ExportRunner", _SyncExportRunner)


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    from webcache import paths
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    monkeypatch.setattr(paths, "cases_dir", lambda: case_dir)
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    return w


@pytest.fixture
def outbox(tmp_path):
    d = tmp_path / "exports"
    d.mkdir()
    return d


def _view(win):
    return win._ensure_view_built("location")


def _nav_count(win):
    text = win.sidebar._rows["location"].count_label.text()
    return int(text.replace(",", "")) if text.strip("-–") else None


def _open(win, entries):
    win._on_evidence_loaded(
        {"rows": [], "parser": _FakeParser(entries)},
        EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                    {_EVIDENCE_PATH: "a" * 64}))


def _chooser(monkeypatch, path):
    """Records every time the destination chooser is opened."""
    opened = []

    def choose(*args, **kwargs):
        opened.append(path)
        return (path, "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(choose))
    return opened


# --- a real view with a real count ---------------------------------------

def test_location_is_a_real_view_not_a_placeholder(win):
    assert isinstance(_view(win), LocationView)


def test_location_left_the_no_count_set(win):
    """A record-set view with a real number belongs in the badge column.
    Leaving it in _NO_COUNT_KEYS would paint a permanent dash over a
    figure this view can state exactly."""
    assert "location" not in _NO_COUNT_KEYS


def test_opening_evidence_fills_both_segments(win):
    _open(win, [_geo_entry(1), _geo_entry(2, lat="48.8566", lon="2.3522"),
                _plain_entry()])
    view = _view(win)
    assert len(view._segment_rows["fixes"]) == 2
    assert len(view._segment_rows["places"]) == 2


def test_the_badge_counts_fixes_not_places(win):
    """Two fixes at one place is one place and two fixes. The switcher
    button already states the place count, and a badge counting something
    else from the button beside it is two screens disagreeing."""
    _open(win, [_geo_entry(1), _geo_entry(2)])
    assert len(_view(win)._segment_rows["places"]) == 1
    assert _nav_count(win) == 2


def test_an_exhibit_with_no_position_at_all_reports_zero_not_a_dash(win):
    """The ordinary case, and what the real exhibit turned out to be. Zero
    is a real answer here and the empty state says why it is legitimate."""
    _open(win, [_plain_entry(1), _plain_entry(2)])
    assert _nav_count(win) == 0
    assert _view(win)._segment_rows["fixes"] == []


def test_before_a_scan_the_count_line_says_nobody_has_looked_for_carved_ones(win):
    _open(win, [_geo_entry(1)])
    assert location_loader.CARVED_NOT_SCANNED_NOTE in _view(win).line_text()


def test_the_not_scanned_note_has_one_spelling(win):
    from webcache.shell import main_window as mw
    assert (mw.LOCATION_CARVED_NOT_SCANNED_NOTE
            is location_loader.CARVED_NOT_SCANNED_NOTE)


# --- a recovery scan folds carved fixes in --------------------------------

def test_a_recovery_scan_adds_positions_that_only_ever_existed_in_deleted_urls(win):
    """A position that only ever existed in a deleted URL is worth more,
    not less."""
    _open(win, [_geo_entry(1)])
    assert _nav_count(win) == 1
    carved = {"Url": _geo_entry(7, lat="48.8566", lon="2.3522")["Url"],
              "Source": "V01.log", "Offset": 4096, "Encoding": "ascii"}
    win._on_recovery_loaded(_StubEngine(artifacts=[carved]))
    view = _view(win)
    assert _nav_count(win) == 2
    assert len(view._segment_rows["places"]) == 2
    assert sum(p["Carved"] for p in view._segment_rows["places"]) == 1
    assert location_loader.CARVED_NOT_SCANNED_NOTE not in view.count_label.text()


def test_a_recovery_scan_writes_no_origin_onto_the_engine_dicts(win):
    _open(win, [_geo_entry(1)])
    carved = {"Url": _geo_entry(7)["Url"], "Source": "V01.log",
              "Offset": 4096, "Encoding": "ascii"}
    win._on_recovery_loaded(_StubEngine(artifacts=[carved]))
    assert "Origin" not in carved


def test_fixes_are_exhibit_scoped_and_reset_on_the_next_open(win):
    """A position found in one exhibit must never be attributed to the
    next one -- the same rule _recovery_engine = None already keeps."""
    _open(win, [_geo_entry(1)])
    assert win._location_fixes
    _open(win, [_plain_entry()])
    assert win._location_fixes == []
    assert win._location_places == []


# --- the three cards ------------------------------------------------------

def test_an_exhibit_with_no_fixes_leaves_the_three_cards_unavailable(win):
    _open(win, [_plain_entry()])
    view = win._ensure_view_built("export")
    for key in ("loc_csv", "loc_kml"):
        assert view.cards[key].available is False, key


def test_one_position_fix_makes_the_cards_available(win):
    _open(win, [_geo_entry(1)])
    view = win._ensure_view_built("export")
    assert view.cards["loc_csv"].available is True
    assert view.cards["loc_kml"].available is True


def test_a_recovery_scan_alone_can_make_them_available(win):
    """On two of the three sample databases every position was in a
    deleted or unflushed URL. A card that stayed grey after the scan that
    found them would be a card lying about the exhibit."""
    _open(win, [_plain_entry()])
    view = win._ensure_view_built("export")
    assert view.cards["loc_kml"].available is False
    carved = {"Url": _geo_entry(7)["Url"], "Source": "V01.log",
              "Offset": 4096, "Encoding": "ascii"}
    win._on_recovery_loaded(_StubEngine(artifacts=[carved]))
    assert view.cards["loc_kml"].available is True


# --- the position gate is gone, the writes still work ------------------

def test_a_position_export_opens_the_chooser_without_asking(win, monkeypatch,
                                                           outbox):
    """The position acknowledgement is gone. The chooser is the first
    thing a position export shows."""
    _open(win, [_geo_entry(1)])
    opened = _chooser(monkeypatch, str(outbox / "fixes.kml"))
    win._export_format("loc_kml")
    assert opened, "the chooser never ran"
    assert len(_SyncExportRunner.jobs) == 1


def test_the_location_views_own_csv_is_not_gated(win, monkeypatch, outbox):
    _open(win, [_geo_entry(1)])
    opened = _chooser(monkeypatch, str(outbox / "view.csv"))
    win.go_to("location")
    _view(win).export_button.click()
    assert opened


# --- the job actually carries the fixes -----------------------------------

def test_the_job_carries_the_fixes_and_the_places(win, monkeypatch,
                                                  outbox):
    """Without these an ENABLED card writes an empty file, which is worse
    than a greyed one: it looks like an answer."""
    _open(win, [_geo_entry(1), _geo_entry(2, lat="48.8566", lon="2.3522")])
    _chooser(monkeypatch, str(outbox / "fixes.kml"))
    win._export_format("loc_kml")
    job = _SyncExportRunner.jobs[0]
    assert len(job.location_fixes) == 2
    assert isinstance(job.places, list) and len(job.places) == 2


def test_a_position_csv_written_through_the_card_holds_the_fixes(
        win, monkeypatch, outbox):
    _open(win, [_geo_entry(1), _geo_entry(2, lat="48.8566", lon="2.3522")])
    out = outbox / "fixes.csv"
    _chooser(monkeypatch, str(out))
    win._export_format("loc_csv")
    with open(out, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert len(rows) == 3          # heading plus two fixes
    assert "Fix time — device said (UTC)" in rows[0]


# --- copy, never open -----------------------------------------------------

def test_a_map_link_click_copies_and_says_what_it_copied(win):
    _open(win, [_geo_entry(1)])
    view = _view(win)
    fix = view._segment_rows["fixes"][0]
    view.copyRequested.emit(fix["MapsUrl"], "Google Maps link")
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == fix["MapsUrl"]
    assert "Google Maps link" in win._status_message.full_text()
