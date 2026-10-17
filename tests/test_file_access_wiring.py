"""The wiring for File Access -- the nav key "downloads" now builds a
real FileAccessView instead of a placeholder, MainWindow._on_evidence_
loaded lands live rows in both its segments, and a completed recovery
scan merges carved rows into both, mirroring exactly what
test_wiring.py/test_recovery_wiring.py already prove for History.

Deliberately a separate file from those two (both already large) rather
than appended to either -- the same "beside, not inside" discipline
evidence_loader.py/recovery_loader.py's own row builders follow.
"""
import datetime
import uuid

import pytest
from PySide6.QtWidgets import QFileDialog

from webcache.provenance import EvidenceSet
from webcache.shell.main_window import ExplainDialog, MainWindow
from webcache.views.file_access import FileAccessView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"
#: A fixed GUID, not uuid.uuid4() -- see test_recovery_loader.py's own
#: _FIXED_GUID comment for why a random one is a rare, non-deterministic
#: flake in a synthetic download blob, not genuine test coverage.
_FIXED_GUID = uuid.UUID("12345678-1234-5678-1234-567812345678").bytes_le


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def _file_access_view(win):
    return win._ensure_view_built("downloads")


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                       {_EVIDENCE_PATH: "a" * 64})


def _filetime(dt):
    epoch = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
    return int((dt - epoch).total_seconds() * 10_000_000)


_SOME_FILETIME = _filetime(datetime.datetime(2024, 6, 1, 12, 0, 0,
                                             tzinfo=datetime.timezone.utc))


class _FakeParser:
    """Just enough of WebCacheParser's surface for file_access_rows_from_
    parser/downloads_rows_from_parser -- a hand-built all_entries list,
    exactly the stub shape test_evidence_loader.py already pins."""

    def __init__(self, entries):
        self.all_entries = entries
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.containers_meta = []
        self.container_type_map = {}


def _fa_entry(**overrides):
    base = {
        "ContainerType": "History",
        "IsLocalFile": True,
        "CleanUrl": "file:///C:/Users/alice/Desktop/notes.txt",
        "ModifiedTime_raw": _SOME_FILETIME,
        "AccessedTime_raw": _SOME_FILETIME,
        "CreationTime_raw": 0,
        "SPS_LastVisitLocal_raw": None,
        "SPS_VisitCount": 2,
        "AccessCount": 5,
        "FileSize": 1024,
        "ContainerId": 3,
        "ContainerName": "Content",
        "EntryId": 7,
    }
    base.update(overrides)
    return base


def _dl_entry(**overrides):
    import struct

    when = datetime.datetime(2024, 3, 2, 9, 0, 0, tzinfo=datetime.timezone.utc)
    epoch = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
    ft = int((when - epoch).total_seconds() * 10_000_000)
    header = _FIXED_GUID + struct.pack("<Q", ft) + struct.pack("<I", 555)
    strings = (r"D:\evidence\bill.pdf".encode("ascii") + b"\x00"
              + b"https://portal.example/bill.pdf\x00")
    base = {
        "ContainerType": "Downloads",
        "ResponseHeaders_raw": header + strings,
    }
    base.update(overrides)
    return base


class _StubEngine:
    """Mirrors test_recovery_loader.py's own _StubEngine / test_recovery_
    wiring.py's own _FakeEngine -- just .structured_records and
    .all_artifacts()."""

    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = structured_records or []
        self._artifacts = artifacts or []

    def all_artifacts(self):
        return self._artifacts


def _carved_fa_record(**overrides):
    base = {
        "Url": "file:///C:/deleted/photo.jpg",
        "CleanUrl": "file:///C:/deleted/photo.jpg",
        "ContainerType": "Content",
        "IsLocalFile": True,
        "ModifiedTime_raw": _SOME_FILETIME,
        "AccessedTime_raw": 0,
        "CreationTime_raw": 0,
        "SPS_LastVisitLocal_raw": None,
        "SPS_VisitCount": None,
        "AccessCount": 1,
        "FileSize": 2048,
        "ContainerId": 3,
        "ContainerName": "Content",
        "EntryId": 41,
        "Source": "WebCacheV01.dat",
    }
    base.update(overrides)
    return base


def _carved_dl_record(**overrides):
    import struct

    when = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    epoch = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
    ft = int((when - epoch).total_seconds() * 10_000_000)
    header = _FIXED_GUID + struct.pack("<Q", ft) + struct.pack("<I", 333)
    strings = (r"E:\deleted\out.zip".encode("ascii") + b"\x00"
              + b"https://cdn.example/out.zip\x00")
    base = {
        "ContainerType": "Downloads",
        "ResponseHeaders_raw": header + strings,
        "Source": "V01.log",
    }
    base.update(overrides)
    return base


# --- the nav key itself: real view, not a placeholder ----------------------

def test_downloads_nav_key_is_a_real_fileaccessview(win):
    assert isinstance(_file_access_view(win), FileAccessView)


def test_the_view_is_reachable_and_shows_the_file_access_segment_by_default(win):
    win.go_to("downloads")
    assert win.current_key == "downloads"
    fa = _file_access_view(win)
    assert [c.key for c in fa.COLUMNS][0] == "ModifiedTime"


# --- opening evidence lands live rows in both segments ----------------------

def test_opening_evidence_populates_the_file_access_segment(win):
    parser = _FakeParser([_fa_entry(), _fa_entry(IsLocalFile=False)])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    fa = _file_access_view(win)
    assert fa.table.model().rowCount() == 1


def test_opening_evidence_populates_the_downloads_segment(win):
    parser = _FakeParser([_dl_entry(), _dl_entry(ContainerType="Content")])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    fa = _file_access_view(win)
    fa._switch_segment("downloads")
    assert fa.table.model().rowCount() == 1
    assert fa.table.model().row_at(0)["DownloadPath"] == r"D:\evidence\bill.pdf"


def test_a_parser_without_all_entries_leaves_file_access_empty_not_crashed(win):
    """Several existing tests hand _on_evidence_loaded a minimal parser
    stand-in with no all_entries at all (identity only) -- this must
    never crash, the same defensive contract _db_summary_info already
    has for the identical situation."""
    win._on_evidence_loaded({"rows": [], "parser": object()}, _fake_evidence_set())
    fa = _file_access_view(win)
    assert fa.table.model().rowCount() == 0


def test_the_count_line_says_live_only_before_a_scan(win):
    parser = _FakeParser([_fa_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    text = _file_access_view(win).line_text().lower()
    assert "not yet recovered" in text


def test_sidebar_count_is_the_combined_row_count_of_both_segments(win):
    parser = _FakeParser([_fa_entry(), _fa_entry(), _dl_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    row = win.sidebar._rows["downloads"]
    assert "3" in row._count_text


# --- a completed recovery scan merges carved rows into both segments -------

def test_a_completed_scan_merges_carved_rows_into_file_access(win):
    parser = _FakeParser([_fa_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())

    win._recovery_engine = None
    win._on_recovery_loaded(_StubEngine(structured_records=[_carved_fa_record()]))

    fa = _file_access_view(win)
    assert fa.table.model().rowCount() == 2
    origins = {fa.table.model().row_at(i)["Origin"]
              for i in range(fa.table.model().rowCount())}
    assert any(o.startswith("Carved") for o in origins)


def test_a_completed_scan_merges_carved_rows_into_downloads(win):
    parser = _FakeParser([_dl_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())

    win._on_recovery_loaded(_StubEngine(structured_records=[_carved_dl_record()]))

    fa = _file_access_view(win)
    fa._switch_segment("downloads")
    assert fa.table.model().rowCount() == 2
    origins = {fa.table.model().row_at(i)["Origin"]
              for i in range(fa.table.model().rowCount())}
    assert any(o.startswith("Carved") for o in origins)


def test_the_count_line_states_the_live_and_recovered_split(win):
    parser = _FakeParser([_fa_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())

    win._on_recovery_loaded(_StubEngine(structured_records=[_carved_fa_record()]))

    text = _file_access_view(win).line_text().lower()
    assert "1" in text and "live" in text
    assert "1" in text and "recovered" in text


def test_sidebar_count_updates_after_a_scan(win):
    parser = _FakeParser([_fa_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())

    win._on_recovery_loaded(_StubEngine(structured_records=[
        _carved_fa_record(), _carved_dl_record()]))

    row = win.sidebar._rows["downloads"]
    assert "3" in row._count_text


# --- explainRequested / exportRequested / drillRequested -------------------

def test_export_button_exports_rather_than_navigating(win, monkeypatch):
    """It used to assert `current_key == "export"` -- that the button
    NAVIGATED to a placeholder. That was the defect, not the contract:
    a button labelled "Export view (20)" that moves the screen and writes
    nothing is a control that looks alive and is not.

    The chooser is stubbed to a cancel here, so this pins the two things
    that matter without writing a file: the button reaches the export
    path (the chooser opened at all), and it does NOT navigate away from
    the view the examiner is exporting.
    """
    parser = _FakeParser([_fa_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    win.go_to("downloads")
    asked = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (asked.append(a), ("", ""))[1]))
    _file_access_view(win).export_button.click()
    assert asked, "the button never reached the export path"
    assert win.current_key == "downloads", (
        "exporting a view must not move the examiner off it")


def test_drill_requested_routes_through_go_to(win):
    fa = _file_access_view(win)
    fa.drillRequested.emit("history", {})
    assert win.current_key == "history"


def test_f1_on_a_file_access_cell_reaches_a_real_explain_handler(win, monkeypatch):
    import webcache.shell.main_window as mw

    parser = _FakeParser([_fa_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    fa = _file_access_view(win)
    win.go_to("downloads")

    shown = []

    class _NonModalExplainDialog(ExplainDialog):
        def exec(self):
            shown.append(self._text)
            return 1

    monkeypatch.setattr(mw, "ExplainDialog", _NonModalExplainDialog)

    ix = fa.table.model().index(0, 0)
    fa.table.setCurrentIndex(ix)
    fa.table._explain_current_cell()

    assert shown, "explainRequested must reach a real handler end to end"


def test_the_count_line_says_where_text_only_file_addresses_are(win):
    """Addresses carved as text alone count in Domains but cannot be File
    Access rows; the count line says how many, and where they are."""
    parser = _FakeParser([_fa_entry()])
    win._on_evidence_loaded({"rows": [], "parser": parser}, _fake_evidence_set())
    win._on_recovery_loaded(_StubEngine(
        structured_records=[_carved_fa_record()],
        artifacts=[{"Url": "Visited: a@file:///C:/only-text.txt",
                    "RecoverySource": "DB unallocated space"}]))
    text = _file_access_view(win).line_text()
    assert "1 more local-file address recovered as text alone" in text, text
    assert "Deleted Records" in text, text
