"""Wiring: Integrity and Table Browser are real views and receive real
data when evidence loads -- the same thing
test_main_window_records_views.py already proves for Cookies & HSTS and
Containers, kept in its own file for the identical reason that one is:
"this task's diff stays additive to files a concurrent branch may also be
touching."

Also proves the Containers-drill fix: main_window.py used to wire
ContainersView.drillRequested through the generic `lambda k, _row:
self.go_to(k)` every other single-target drill uses -- correct for
navigation, but a container's own name must land the Table Browser ON THAT CONTAINER'S TABLE, not merely open the
view at whatever was last selected (see containers.py's own "A CLICK ON A
CONTAINER'S NAME DRILLS THROUGH").
"""
import pytest

from webcache.provenance import EvidenceSet
from webcache.shell.main_window import MainWindow
from webcache.views.browser import TableBrowserView
from webcache.views.containers import ContainersView
from webcache.views.headers import HeadersView
from webcache.views.integrity import IntegrityView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def _integrity_view(win):
    return win._ensure_view_built("integrity")


def _browser_view(win):
    return win._ensure_view_built("browser")


def _containers_view(win):
    return win._ensure_view_built("containers")


def _headers_view(win):
    return win._ensure_view_built("headers")


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                       {_EVIDENCE_PATH: "a" * 64})


class _FullParser:
    """Just enough of WebCacheParser's surface for get_database_info() AND
    the Table Browser's own methods -- mirrors test_main_window_records_
    views.py's own _FullParser, extended with the raw-table surface this
    file additionally needs."""

    def __init__(self):
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.all_entries = [{"CleanUrl": "https://example.com/a"}]
        self.table_names = ["Container_1", "MSysObjects"]
        self.containers_meta = [
            {"ContainerId": 1, "Name": "Cookies", "HasTable": True,
             "RecordCount": 1, "Size": 100, "PartitionId": "p1",
             "Directory": "C:\\x", "LastAccessTime": "", "LastScavengeTime": "",
             "TableName": "Container_1"},
        ]
        self.container_type_map = {1: "Cookies"}
        self.source_hashes = {"WebCacheV01.dat": "a" * 64}
        self.db_state = 2
        self.parse_stats = {"parsed": 1, "skipped": 0, "errors": 0}
        self.decision_log = ["Opened read-only: WebCacheV01.dat (DIRTY shutdown)"]
        self.derived_tz_label = "UTC+00:00"

    def get_container_type(self, cid):
        return self.container_type_map.get(cid, "Unknown")

    def get_database_info(self):
        return {
            "path": self.db_path, "table_count": 2, "container_count": 1,
            "total_entries": 1, "db_state": self.db_state,
            "db_state_text": "Dirty shutdown",
            "source_hashes": dict(self.source_hashes),
            "parse_stats": dict(self.parse_stats),
            "decision_log": list(self.decision_log),
            "derived_tz": self.derived_tz_label,
        }

    def get_tables_grouped(self):
        return {
            "Cookies": [{"name": "Container_1", "display_name": "Container_1",
                        "type": "Cookies", "count": 1}],
            "System": [{"name": "MSysObjects", "display_name": "MSysObjects",
                       "type": "System", "count": 0}],
        }

    def get_table_rows_raw(self, table_name, limit=500, offset=0):
        if table_name == "Container_1":
            return ["Domain"], [["example.com"]]
        return ["Name"], []

    def get_table_row_count(self, table_name):
        return 1 if table_name == "Container_1" else 0

    def get_table_display_name(self, table_name):
        return table_name

    def get_table_type(self, table_name):
        return "Cookies" if table_name == "Container_1" else "System"

    @staticmethod
    def raw_type_name(value):
        return "text" if isinstance(value, str) else "unknown"

    @staticmethod
    def raw_rendering(value, truncate=True):
        # `truncate` mirrors the real WebCacheParser.raw_rendering -- see
        # that method: the loader asks a text cell for its untruncated
        # rendering so the row view can show the value in full.
        return str(value)


class _MinimalParser:
    """No get_database_info/get_tables_grouped at all -- mirrors the
    minimal stand-ins test_file_access_wiring.py/test_recovery_wiring.py
    already use, proving the wiring degrades to the honest no-evidence
    state instead of crashing."""

    def __init__(self):
        self.db = None
        self.db_path = _EVIDENCE_PATH
        self.all_entries = []
        self.containers_meta = []
        self.container_type_map = {}


# --- the nav keys themselves: real views, not placeholders -----------------

def test_integrity_nav_shows_a_real_view_not_the_placeholder(win):
    assert isinstance(_integrity_view(win), IntegrityView)


def test_browser_nav_shows_a_real_view_not_the_placeholder(win):
    assert isinstance(_browser_view(win), TableBrowserView)


# --- evidence load reaches both new views -----------------------------------

def test_evidence_load_populates_integrity(win):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    integrity = _integrity_view(win)
    assert len(integrity._hash_rows) == 1
    assert integrity._hash_rows[0]["hash"].text() == "a" * 64


def test_evidence_load_populates_the_table_browser_list(win):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    browser = _browser_view(win)
    assert browser._parser is not None
    assert browser.table_list.count() > 0


def test_a_parser_that_is_none_leaves_both_views_in_the_no_evidence_state(win):
    win._on_evidence_loaded({"rows": [], "parser": None}, _fake_evidence_set())
    integrity = _integrity_view(win)
    assert integrity._hash_rows == []
    browser = _browser_view(win)
    assert browser._parser is None
    assert browser.table_list.count() == 0


def test_a_minimal_parser_leaves_both_views_empty_not_crashed(win):
    win._on_evidence_loaded({"rows": [], "parser": _MinimalParser()},
                            _fake_evidence_set())
    integrity = _integrity_view(win)
    assert integrity._hash_rows == []
    browser = _browser_view(win)
    assert browser._parser is None
    assert browser.table_list.count() == 0


# --- the Containers drill lands on the right table --------------------------

def test_container_name_click_lands_the_table_browser_on_that_containers_table(win, qtbot):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    containers = _containers_view(win)
    col = next(c for c in containers.COLUMNS if c.key == "Name")
    row = containers.table.model().row_at(0)
    assert row["Id"] == 1

    col.on_click(row)

    assert win.current_key == "browser"
    browser = _browser_view(win)
    assert browser._current_table == "Container_1"
    assert browser.grid.rowCount() == 1


def test_the_drill_still_navigates_even_though_it_is_no_longer_the_generic_lambda(win, qtbot):
    """The generic `lambda k, _row: self.go_to(k)` every OTHER single-
    target drill in this file uses is replaced, for containers, by a
    dedicated handler -- this proves that handler still does the ordinary
    "navigate there" half every other drill does, not just the new
    table-selection half."""
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    win.go_to("dashboard")
    assert win.current_key == "dashboard"
    containers = _containers_view(win)
    col = next(c for c in containers.COLUMNS if c.key == "Name")
    col.on_click(containers.table.model().row_at(0))
    assert win.current_key == "browser"


# --- [6] the Headers drill must read ITS OWN container key -----------------
#
# _drill_container_to_browser read row.get("Id") unconditionally --
# ContainersView's own row key (evidence_loader.container_rows_from_
# parser). Headers rows carry ContainerId instead (headers_loader.py's own
# row builder), so a drill from either of the Headers screen's two
# container affordances -- the Container CELL and the pane's own "Browse
# Container_N" button -- never reached select_table at all: row.get("Id")
# read None off a Headers row and the whole branch was skipped.
#
# select_table is STUBBED here rather than driven to a real render: the
# fact under test is which table NAME the drill computes and passes, not
# what TableBrowserView then paints -- test_container_name_click_lands_
# the_table_browser_on_that_containers_table above already proves
# select_table itself works end to end.

def _header_row():
    return {"ContainerId": 1, "ContainerName": "Cookies",
           "CleanUrl": "https://example.com/a"}


def test_headers_container_cell_click_lands_on_that_container(
        win, qtbot, monkeypatch):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    browser = _browser_view(win)
    calls = []
    monkeypatch.setattr(browser, "select_table",
                        lambda name: calls.append(name))
    headers = _headers_view(win)
    col = next(c for c in headers.COLUMNS if c.key == "ContainerId")

    col.on_click(_header_row())

    assert calls == ["Container_1"], (
        "the Container CELL drill must reach select_table with the "
        "row's ContainerId, not a missing 'Id' key")
    assert win.current_key == "browser"


def test_headers_browse_container_button_lands_on_that_container(
        win, qtbot, monkeypatch):
    win._on_evidence_loaded({"rows": [], "parser": _FullParser()},
                            _fake_evidence_set())
    browser = _browser_view(win)
    calls = []
    monkeypatch.setattr(browser, "select_table",
                        lambda name: calls.append(name))
    headers = _headers_view(win)
    headers.detail_pane.set_row(_header_row())

    headers.detail_pane.container_button.click()

    assert calls == ["Container_1"], (
        "the pane's own 'Browse Container_N' button must reach "
        "select_table with the row's ContainerId too")
    assert win.current_key == "browser"


# --- caveats -----------------------------------------------------------------

def test_caveats_are_set_from_nav_sections(win):
    assert _integrity_view(win).caveat._text.text() == win.caveat_for("integrity")
    assert _browser_view(win).caveat._text.text() == win.caveat_for("browser")


# --- the row view is reached from the shell, not just constructible -------
#
# table_row_detail.py was built, tested standalone, and imported by
# nothing: the same shape as every dead end this project has shipped and
# then had to be told about. These prove the signal arrives, the dialog
# that opens carries THIS row, and it is tracked like every other detail
# dialog so a second exhibit closes it.


def _loaded_browser(win):
    win._parser = _FullParser()
    win._evidence_set = _fake_evidence_set()
    view = _browser_view(win)
    view.set_parser(win._parser)
    view.select_table("Container_1")
    return view


def test_a_row_request_from_the_browser_opens_the_row_dialog(win):
    view = _loaded_browser(win)
    dialog = win._show_table_row({
        "table": "Container_1", "row_number": 2, "row_count": 9,
        "columns": list(view._page_columns), "cells": view._page_rows[0]})
    assert dialog is not None
    assert dialog.table_name == "Container_1"
    assert dialog.row_number == 2
    assert dialog.row_count == 9
    assert dialog.columns == view._page_columns
    dialog.close()


def test_the_browsers_row_signal_is_connected_to_it(win):
    view = _loaded_browser(win)
    view.grid.setCurrentCell(0, 0)
    view.view_row_button.click()
    opened = [d for d in win._detail_dialogs
              if type(d).__name__ == "TableRowDialog"]
    assert len(opened) == 1
    assert opened[0].table_name == "Container_1"
    assert opened[0].row_number == 1
    for d in opened:
        d.close()


def test_an_open_row_dialog_is_closed_when_the_next_exhibit_loads(win):
    """It holds cells by reference out of the parser that is about to be
    replaced -- the same reason _close_record_dialogs exists at all."""
    view = _loaded_browser(win)
    view.grid.setCurrentCell(0, 0)
    view.view_row_button.click()
    assert win._detail_dialogs
    win._close_record_dialogs()
    assert win._detail_dialogs == []
