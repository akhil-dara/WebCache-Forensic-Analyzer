"""Every domain drill reaches that domain's records, wherever they
live and however they survived."""
import datetime

import pytest

from webcache.provenance import EvidenceSet
from webcache.shell import domain_loader
from webcache.shell.main_window import MainWindow
from webcache.views.domains import DomainsView

UTC = datetime.timezone.utc
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=UTC)
FT = int((datetime.datetime(2024, 3, 1, 10, tzinfo=UTC) - _EPOCH)
         .total_seconds()) * 10_000_000
_PATH = "C:/case/WebCacheV01.dat"


def live(url, ctype="History", cid=1):
    return {"Url": url, "CleanUrl": url, "ContainerType": ctype,
            "ContainerId": cid, "EntryId": 7, "ModifiedTime_raw": FT,
            "AccessCount": 1, "FileSize": 0}


def carved(url):
    e = live(url)
    e.pop("EntryId")
    e.update(RecoverySource="unallocated page", Source="WebCacheV01.dat",
             Offset=4096, Page=1, Confidence="high")
    return e


LIVE = [live("https://kept.example.test/a"),
        live("https://kept.example.test/b", ctype="Content", cid=2)]
CARVED = [carved("https://gone.example.test/%d" % i) for i in range(3)]


def _pane_rows(view):
    model = view.pane.table.model()
    return [model.row_at(i) for i in range(model.rowCount())]


def test_the_pane_lists_every_member_live_and_carved_from_every_container(qtbot):
    view = DomainsView()
    qtbot.addWidget(view)
    view.set_records(domain_loader.domain_rows(LIVE, CARVED))
    assert view.show_domain("kept.example.test")
    assert {r["ContainerType"] for r in _pane_rows(view)} == \
        {"History", "Content"}
    assert view.show_domain("gone.example.test")
    rows = _pane_rows(view)
    assert len(rows) == 3
    assert all(r["Origin"].startswith("Carved") for r in rows)


def test_a_domain_hidden_by_a_filter_is_still_found(qtbot):
    view = DomainsView()
    qtbot.addWidget(view)
    view.set_records(domain_loader.domain_rows(LIVE, CARVED))
    view.table.model().set_text("kept")
    assert view.show_domain("gone.example.test")
    assert view.selected_domain() == "gone.example.test"


class _Parser:
    def __init__(self):
        self.all_entries = list(LIVE)
        self.db = None
        self.db_path = _PATH
        self.containers_meta = []
        self.container_type_map = {}


class _Engine:
    structured_records = CARVED
    tombstones = []

    def all_artifacts(self):
        return []


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    w._on_evidence_loaded({"rows": [], "parser": _Parser()},
                          EvidenceSet([_PATH], {_PATH: 1}, {_PATH: "a" * 64}))
    w._on_recovery_loaded(_Engine())
    return w


def test_a_carved_only_domain_drill_is_not_a_dead_end(win):
    win._drill_to_domain("domains", {"Domain": "gone.example.test"})
    domains = win._ensure_view_built("domains")
    assert win.current_key == "domains"
    assert domains.selected_domain() == "gone.example.test"
    assert domains.pane.table.model().rowCount() == 3


def test_the_domains_grid_click_selects_the_domain_instead_of_leaving(win):
    domains = win._ensure_view_built("domains")
    win.go_to("domains")
    model = domains.table.model()
    row = next(i for i in range(model.rowCount())
               if model.row_at(i)["Domain"] == "gone.example.test")
    col = [c.key for c in model.columns].index("Domain")
    domains.table.activate_cell(row, col)
    assert win.current_key == "domains"
    assert domains.pane.table.model().rowCount() == 3


def test_the_dashboard_top_domain_drills_to_the_domains_records(win):
    dashboard = win._ensure_view_built("dashboard")
    dashboard.drillRequested.emit("domains", {"Domain": "gone.example.test",
                                              "Count": 3})
    assert win.current_key == "domains"
    assert win._ensure_view_built("domains").selected_domain() == \
        "gone.example.test"


def _artifact_without_recovery_source(url):
    """A carved entry the engine did not stamp with RecoverySource: the
    grid counts it as carved because of the LIST it came from."""
    e = live(url)
    e.pop("EntryId")
    return e


def test_every_domain_pane_agrees_with_its_grid_row(qtbot):
    """The pane lists exactly the records the row counted, and
    labels them Live/Carved exactly as the row's From-deleted cell counted
    them -- for EVERY domain, not three hand-picked ones."""
    lives = LIVE + [live("https://mixed.example.test/x")]
    carveds = CARVED + [
        _artifact_without_recovery_source("https://mixed.example.test/y"),
        _artifact_without_recovery_source("https://bare.example.test/z")]
    view = DomainsView()
    qtbot.addWidget(view)
    rows = domain_loader.domain_rows(lives, carveds)
    view.set_records(rows)
    assert len(rows) == 4
    for row in rows:
        assert view.show_domain(row["Domain"])
        pane = _pane_rows(view)
        assert row["Records"] == len(row["_members"]) == len(pane), row["Domain"]
        shown_carved = sum(1 for r in pane if r["Origin"].startswith("Carved"))
        assert shown_carved == row["Carved"], row["Domain"]


def test_a_rerender_keeps_the_selected_domain_and_its_pane(qtbot):
    """A recovery merge or segment refresh re-renders the grid;
    it must not blank the pane the examiner is reading."""
    view = DomainsView()
    qtbot.addWidget(view)
    view.set_records(domain_loader.domain_rows(LIVE, CARVED))
    assert view.show_domain("gone.example.test")
    view.set_records(domain_loader.domain_rows(LIVE, CARVED))
    assert view.selected_domain() == "gone.example.test"
    assert len(_pane_rows(view)) == 3


def test_a_rerender_without_the_domain_falls_back_to_the_prompt(qtbot):
    view = DomainsView()
    qtbot.addWidget(view)
    view.set_records(domain_loader.domain_rows(LIVE, CARVED))
    assert view.show_domain("gone.example.test")
    view.set_records(domain_loader.domain_rows(LIVE, []))
    assert view.selected_domain() == ""


def _shares(view):
    sizes = view._splitter.sizes()
    return sizes[1] / float(sum(sizes))


def test_the_pane_takes_most_of_the_height_once_a_domain_is_selected(qtbot):
    """A fixed 3:2 split left ~3 pane rows at 816 px. Idle the
    grid is tall and the pane is one line; selected, the pane takes the
    larger share (Timeline's mechanism)."""
    view = DomainsView()
    qtbot.addWidget(view)
    view.resize(1536, 700)
    view.set_records(domain_loader.domain_rows(LIVE, CARVED))
    view.show()
    qtbot.waitExposed(view)
    assert _shares(view) <= 0.2
    assert view.show_domain("gone.example.test")
    assert _shares(view) >= 0.6


def test_the_pane_has_one_line_above_it_not_two(qtbot):
    view = DomainsView()
    qtbot.addWidget(view)
    view.set_records(domain_loader.domain_rows(LIVE, CARVED))
    view.show()
    qtbot.waitExposed(view)
    assert view.show_domain("gone.example.test")
    assert not view.pane.note.isVisible()
    assert "3 records for gone.example.test" in view.pane.heading.text()


def test_the_pane_export_button_writes_the_panes_records(win, tmp_path,
                                                         monkeypatch):
    """'Export these records (N)' was never connected. The file
    holds exactly the pane's rows and carries each record's own raw
    fields (from _record), not only the derived columns."""
    import csv
    domains = win._ensure_view_built("domains")
    win._drill_to_domain("domains", {"Domain": "gone.example.test"})
    out = tmp_path / "domain_records.csv"
    jobs = []
    monkeypatch.setattr(win, "_choose_export_path", lambda *a: str(out))
    real_start = win._start_export

    def start(job, card_key=None):
        jobs.append(job)
        return real_start(job, card_key=card_key)
    monkeypatch.setattr(win, "_start_export", start)
    domains.pane.export_button.click()
    assert len(jobs) == 1
    import time
    end = time.monotonic() + 20
    while not out.exists() and time.monotonic() < end:
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        time.sleep(0.02)
    assert out.exists()
    with open(out, encoding="utf-8-sig", newline="") as fh:
        table = list(csv.reader(fh))
    header, body = table[0], table[1:]
    assert len(body) == domains.pane.table.model().rowCount() == 3
    assert "Carved at offset" in header and "EntryId" in header
