"""An MSHist daily record and its History-container
twin are two records of ONE visit in two containers. Both are evidence and
neither is a copy, so neither is hidden or merged silently: the pair is
linked, each side says what the other is, and a chip (off by default)
shows one row per visit while still counting both.

Synthetic exhibits from test_mshist_local_clock.py: five visits held in
the History container and again in a daily MSHist container.
"""
import csv
import datetime

from webcache.engine import forensic_engine, local_clock
from webcache.shell import detail_fields
from webcache.shell.evidence_loader import (file_access_rows_from_parser,
                                             history_rows_from_parser)
from webcache.views.file_access import FILE_ACCESS_COLUMNS
from webcache.views.history import HistoryView
from tests.test_mshist_local_clock import (DAILY, VISITS, _container, _Db,
                                           _history_row, _mshist_row,
                                           build_parser)
from webcache.engine.ese_parser import WebCacheParser


def _chip(view):
    """The chip, or a stand-in that does nothing -- so a missing chip
    fails on what is on screen, not on an attribute lookup."""
    class _Absent:
        def isChecked(self):
            return False

        def click(self):
            pass
    return getattr(view, "chip_one_row_per_visit", None) or _Absent()


def _twin_line(row):
    return getattr(detail_fields, "twin_line", lambda _r: "")(row)


def _by_container(rows):
    mshist = [r for r in rows if r["_record"].get("MSHistFrom")]
    history = [r for r in rows if not r["_record"].get("MSHistFrom")]
    return mshist, history


def test_the_engine_links_each_mshist_record_to_its_history_twin():
    parser = build_parser()
    for entry in parser.all_entries:
        if entry.get("ContainerId") == 2:
            assert entry.get("VisitTwin") == [("History", entry["EntryId"] - 40)]
        elif entry.get("ContainerId") == 1:
            assert entry.get("VisitTwin") == [(DAILY, entry["EntryId"] + 40)]


def test_twins_are_linked_even_when_no_zone_was_recovered():
    """Two visits are too few to recover a zone; the pair is still one
    visit, and says so."""
    tables = {"Containers": [_container(1, "History"), _container(2, DAILY)],
              "Container_1": [_history_row(i, t)
                              for i, t in enumerate(VISITS[:2])],
              "Container_2": [_mshist_row(i, t)
                              for i, t in enumerate(VISITS[:2])]}
    parser = WebCacheParser()
    parser.db = _Db(tables)
    parser.table_names = list(tables)
    parser._load_containers()
    parser.parse_all_entries()
    assert parser.derived_tz_offset_seconds is None
    mshist = [e for e in parser.all_entries if e.get("ContainerId") == 2]
    assert [e.get("VisitTwin") for e in mshist] == [[("History", 10)],
                                                [("History", 11)]]


def test_an_unpaired_record_carries_no_twin():
    parser = build_parser(mshist_urls={0: ":2024063020240701: alice@"
                                          "https://example.test/only"})
    lone = next(e for e in parser.all_entries
                if e.get("ContainerId") == 2 and e["EntryId"] == 50)
    assert not lone.get("VisitTwin")


def test_history_rows_say_which_record_is_the_same_visit():
    mshist, history = _by_container(history_rows_from_parser(build_parser()))
    assert mshist[0].get("SameVisit") == (
        "History record History #10 (this is its MSHist daily copy)")
    # Said, with the raw container name beside it: the bare name made the
    # examiner decode "MSHist012024063020240701" by hand.
    assert history[0].get("SameVisit") == (
        "also in its MSHist daily copy for 2024-06-30 (%s)" % DAILY)
    assert history[0].get("Container") == "History"
    assert mshist[0].get("Container") == DAILY


def test_file_access_rows_carry_the_same_link():
    keys = [c.key for c in FILE_ACCESS_COLUMNS]
    # Right after the path group (stored, decoded, and the drive and
    # file type read off it).
    assert keys[keys.index("FileType") + 1] == "SameVisit"


def test_history_shows_the_link_and_the_container_by_default(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(history_rows_from_parser(build_parser()))
    columns = view.table.model().columns
    keys = [c.key for c in columns]
    assert keys[keys.index("CleanUrl") + 1] == "SameVisit"
    shown = {c.key for c in columns if not c.hidden and not c.optional}
    assert {"SameVisit", "Container"} <= shown


def test_one_row_per_visit_hides_exactly_the_mshist_half(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    rows = history_rows_from_parser(build_parser())
    view.set_records(rows)
    assert view.table.model().rowCount() == 10
    assert not _chip(view).isChecked()
    _chip(view).click()
    model = view.table.model()
    assert model.rowCount() == 5
    shown = [model.row_at(i) for i in range(model.rowCount())]
    assert not any(r["_record"].get("MSHistFrom") for r in shown)
    assert model.filter.total_count == 10
    assert ("5 MSHist rows hidden — each is the same visit as a "
            "History row shown (left out of Export view; kept in the full case exports)"
            in view.count_label.text())


def test_an_unpaired_mshist_row_survives_the_chip(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    parser = build_parser(mshist_urls={0: ":2024063020240701: alice@"
                                          "https://example.test/only"})
    view.set_records(history_rows_from_parser(parser))
    _chip(view).click()
    # Visit 0 is unpaired on both sides: its History row and its MSHist
    # row both stay. The other four MSHist rows go.
    assert view.table.model().rowCount() == 6


def test_both_records_of_a_visit_are_still_exported(tmp_path):
    parser = build_parser()
    path = str(tmp_path / "all.csv")
    forensic_engine.ForensicEngine().export_csv(parser.all_entries, path)
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 10


def test_the_record_dialog_names_the_twin_as_plain_text():
    mshist, history = _by_container(history_rows_from_parser(build_parser()))
    line = _twin_line(mshist[0])
    assert line == ("Same visit as: History record History #10 (this is "
                    "its MSHist daily copy)")
    assert _twin_line(history[0]) == (
        "Same visit as: also in its MSHist daily copy for 2024-06-30 (%s)"
        % DAILY)
    assert "<a" not in line and "href" not in line


def test_an_mshist_row_whose_twin_is_filtered_out_stays_visible(qtbot):
    """The chip hides an MSHist row only while its History twin is on
    screen; another filter that removes the twin brings the MSHist row
    back, and the count line counts only the rows actually hidden."""
    from webcache.widgets.record_filter import Condition
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(history_rows_from_parser(build_parser()))
    _chip(view).click()
    model = view.table.model()
    assert model.rowCount() == 5
    # Every History-container row filtered out: their MSHist partners have
    # no twin shown, so none of them may stay hidden.
    model.set_condition("Container", Condition("does not contain", "History"))
    shown = [model.row_at(i) for i in range(model.rowCount())]
    assert len(shown) == 5
    assert all(r["_record"].get("MSHistFrom") for r in shown)
    assert "MSHist row" not in view.count_label.text()
    model.set_condition("Container", None)
    assert model.rowCount() == 5
    assert ("5 MSHist rows hidden" in view.count_label.text())


# --- a recovered twin has no container name --------------------------------

def test_a_twin_recovered_without_its_container_is_named_as_such():
    """A carved MSHist copy is known by its URL's date range, but string
    carving cannot say which container held it: "also in " followed by
    nothing read as a missing value."""
    history_row = {local_clock.TWIN_KEY: [("", None)]}
    said = local_clock.same_visit_text(history_row)
    assert said.startswith("also in ") and said != "also in "
    assert "recovered" in said and "container not recorded" in said


def test_an_mshist_row_whose_history_twin_was_recovered_says_so():
    mshist_row = {"MSHistFrom": "20260803", "ContainerName": "",
                  local_clock.TWIN_KEY: [("", None)]}
    said = local_clock.same_visit_text(mshist_row)
    assert "#None" not in said and "  " not in said
    assert "recovered" in said
