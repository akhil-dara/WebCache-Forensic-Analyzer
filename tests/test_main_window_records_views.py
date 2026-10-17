"""Wiring: Cookies & HSTS and Containers are real views and receive real
rows when evidence loads -- the same thing
test_file_access_wiring.py already proves for File Access, kept in its
own file (rather than appended to test_wiring.py/test_main_window.py) so
this task's diff stays additive to files a concurrent branch may also be
touching.
"""
import pytest
from PySide6.QtWidgets import QFileDialog

from webcache.provenance import EvidenceSet
from webcache.shell.main_window import MainWindow
from webcache.views.containers import ContainersView
from webcache.views.cookies import CookiesView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def _cookies_view(win):
    return win._ensure_view_built("cookies")


def _containers_view(win):
    return win._ensure_view_built("containers")


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                       {_EVIDENCE_PATH: "a" * 64})


class _FullParser:
    """Just enough of WebCacheParser's surface for all four new row
    builders -- see test_evidence_loader_cookies.py/
    test_evidence_loader_containers.py for the same shape used in
    isolation."""

    def __init__(self):
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.all_entries = [{"CleanUrl": "https://example.com/a"}]
        self.cookie_entries = [{
            "Domain": "example.com", "RDomain": "com.example",
            "Name": "sid", "Value": "abc", "Path": "/",
            "Expires_raw": 133535904000000000,
            "LastModified_raw": 133535904000000000,
        }]
        self.hsts_entries = [{
            "Domain": "example.com", "IncludeSubdomains": False,
            "Expires": "never", "LastTimeUsed": "", "LastTimeUsed_raw": 0,
        }]
        self.cert_entries = [{
            "HostPort": "example.com:443", "IsCertificate": True,
            "Thumbprint": "aa", "BlobSize": 10, "ModifiedTime_raw": 0,
        }]
        self.containers_meta = [{
            "ContainerId": 1, "Name": "Cookies", "HasTable": True,
            "RecordCount": 1, "Size": 100, "PartitionId": "p1",
            "Directory": "C:\\x", "LastAccessTime": "", "LastScavengeTime": "",
        }]
        self.container_type_map = {1: "Cookies"}

    def get_container_type(self, cid):
        return self.container_type_map.get(cid, "Unknown")


class _MinimalParser:
    """Mirrors the minimal stand-ins test_file_access_wiring.py/
    test_recovery_wiring.py already use elsewhere in this suite: only
    all_entries/containers_meta/container_type_map, none of
    cookie_entries/hsts_entries/cert_entries/get_container_type. Real
    WebCacheParser always has all of these; this exists only to prove
    the wiring degrades to "nothing to show yet" instead of crashing,
    the same defensive contract _db_summary_info already has."""

    def __init__(self):
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.all_entries = []
        self.containers_meta = []
        self.container_type_map = {}


# --- the nav keys themselves: real views, not placeholders -----------------

def test_cookies_nav_shows_a_real_view_not_the_placeholder(win):
    assert isinstance(_cookies_view(win), CookiesView)


def test_containers_nav_shows_a_real_view_not_the_placeholder(win):
    assert isinstance(_containers_view(win), ContainersView)


# --- evidence load reaches both new views, end to end -----------------------

def test_evidence_load_populates_all_three_cookie_segments(win):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    cookies = _cookies_view(win)
    assert cookies._segment_rows["cookies"]
    assert cookies._segment_rows["hsts"]
    assert cookies._segment_rows["certs"]


def test_evidence_load_populates_containers(win):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    containers = _containers_view(win)
    assert containers.table.model().rowCount() == 1
    assert containers.table.model().row_at(0)["Type"] == "Cookies"


def test_a_parser_missing_the_modern_table_attrs_leaves_both_views_empty_not_crashed(win):
    """Several existing tests hand _on_evidence_loaded a minimal parser
    stand-in with no cookie_entries/hsts_entries/cert_entries/
    get_container_type at all (identity only) -- this must never crash,
    the same defensive contract file_access_rows_from_parser's own
    parser_has_entries guard already has for the identical situation."""
    win._on_evidence_loaded({"rows": [], "parser": _MinimalParser()},
                            _fake_evidence_set())
    cookies = _cookies_view(win)
    assert cookies.table.model().rowCount() == 0
    containers = _containers_view(win)
    assert containers.table.model().rowCount() == 0


def test_a_parser_that_is_none_leaves_both_views_at_zero_records(win):
    """Mirrors File Access's own established contract for the identical
    situation (fa_rows/dl_rows default to [] and set_records_for is
    still called) rather than leaving the table's model as None -- one
    discipline for every view a completed-but-parser-less load reaches."""
    win._on_evidence_loaded({"rows": [], "parser": None}, _fake_evidence_set())
    cookies = _cookies_view(win)
    assert cookies.table.model().rowCount() == 0
    containers = _containers_view(win)
    assert containers.table.model().rowCount() == 0


# --- the containers drill lands somewhere real -------------------------

def test_container_name_click_emits_drill_and_navigates_there(win, qtbot):
    containers = _containers_view(win)
    containers.set_records([{
        "Id": 1, "Name": "Container_1", "Type": "Content", "Records": 5,
        "Size": 10, "Partition": "", "Directory": "", "LastAccess": "",
        "LastScavenge": "",
    }])
    col = next(c for c in containers.COLUMNS if c.key == "Name")
    with qtbot.waitSignal(containers.drillRequested, timeout=1000) as sig:
        col.on_click(containers.table.model().row_at(0))
    assert sig.args[0] == "browser"
    assert win.current_key == "browser"


# --- explainRequested / exportRequested / caveat ----------------------------

def _export_without_writing(monkeypatch):
    """Stubs the save chooser to a cancel and records that it opened.

    Both tests below used to assert `current_key == "export"` -- that the
    button NAVIGATED to a placeholder rather than exporting anything.
    That was the defect. What is pinned now is that the button reaches
    the export path at all, and that it leaves the examiner on the view
    they were exporting.
    """
    asked = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (asked.append(a), ("", ""))[1]))
    return asked


def test_export_button_exports_rather_than_navigating_for_cookies(
        win, monkeypatch):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    win.go_to("cookies")
    asked = _export_without_writing(monkeypatch)
    _cookies_view(win).export_button.click()
    assert asked, "the button never reached the export path"
    assert win.current_key == "cookies"


def test_export_button_exports_rather_than_navigating_for_containers(
        win, monkeypatch):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    win.go_to("containers")
    asked = _export_without_writing(monkeypatch)
    _containers_view(win).export_button.click()
    assert asked, "the button never reached the export path"
    assert win.current_key == "containers"


def test_caveats_are_set_from_nav_sections(win):
    # Cookies & HSTS states its caveat per segment, so the visible
    # line is the active segment's own; the nav caveat is the fallback a
    # segment without one shows.
    cookies = _cookies_view(win)
    assert cookies._view_caveat == win.caveat_for("cookies")
    assert cookies.caveat._text.text() ==         cookies._segments_by_key[cookies._active_key].caveat
    assert _containers_view(win).caveat._text.text() == win.caveat_for("containers")
