"""File Access listed every local file twice -- the History record and its
MSHist daily copy, same path, same times -- with nothing on screen saying
why: "Same visit as" sat past the right edge, and History's own "One row
per visit" chip was not offered here. Seen on a real machine: 1,573 rows
in pairs. The chip is the same filter, the same wording and the same
promise as History's: hidden from the list, left out of Export view,
kept in the full case exports."""
from webcache.engine.ese_parser import WebCacheParser
from webcache.shell.evidence_loader import file_access_rows_from_parser
from webcache.views.file_access import FileAccessView

from tests.test_mshist_local_clock import (DAILY, VISITS, _container, _Db,
                                           _history_row, _mshist_row)

PATHS = ["file:///C:/Users/alice/Documents/report%d.docx" % i
         for i in range(len(VISITS))]


def _parser():
    tables = {
        "Containers": [_container(1, "History"), _container(2, DAILY)],
        "Container_1": [_history_row(i, t, "Visited: alice@" + PATHS[i])
                        for i, t in enumerate(VISITS)],
        "Container_2": [_mshist_row(i, t, ":2024063020240701: alice@" + PATHS[i])
                        for i, t in enumerate(VISITS)],
    }
    parser = WebCacheParser()
    parser.db = _Db(tables)
    parser.table_names = list(tables)
    parser._load_containers()
    parser.parse_all_entries()
    return parser


def _view(qtbot):
    view = FileAccessView()
    qtbot.addWidget(view)
    view.set_records_for("file_access", file_access_rows_from_parser(_parser()))
    return view


def test_the_exhibit_holds_each_visit_twice(qtbot):
    view = _view(qtbot)
    assert view.table.model().rowCount() == 2 * len(VISITS)


def test_one_row_per_visit_shows_each_file_once(qtbot):
    view = _view(qtbot)
    view.chip_one_row_per_visit.click()
    assert view.table.model().rowCount() == len(VISITS)
    text = view.count_label.text()
    assert "left out of Export view; kept in the full case exports" in text, text


def test_the_chip_is_off_by_default(qtbot):
    assert not _view(qtbot).chip_one_row_per_visit.isChecked()


# --- repeated carves: the same Copies column and chip as History -----------

from webcache.shell import recovery_loader
from tests.test_copies_and_deleted_records import _engine, carved

def _file(url, offset):
    """A carved record as normalise_record leaves it: IsLocalFile set."""
    return dict(carved(url, offset), IsLocalFile=True)


FILE_COPIES = [_file("file:///C:/Users/alice/Documents/plan.docx", 4096 * i)
               for i in (1, 2, 3)]
FILE_UNIQUE = _file("file:///C:/Users/alice/Documents/once.docx", 4096 * 9)


def test_repeated_carves_of_one_file_record_are_labelled():
    """On a real machine 360 of 1,338 recovered file-access rows were later
    copies of a record already listed, with nothing saying so."""
    rows = recovery_loader.carved_file_access_rows(
        _engine(FILE_COPIES + [FILE_UNIQUE]))
    copies = [r["Copies"] for r in rows if "plan" in r["CleanUrl"]]
    assert copies == ["3 copies (same URL, time and container)",
                      "copy 2 of 3", "copy 3 of 3"]
    assert next(r for r in rows if "once" in r["CleanUrl"])["Copies"] == ""


def test_hide_duplicate_copies_keeps_one_of_each_file(qtbot):
    view = FileAccessView()
    qtbot.addWidget(view)
    view.set_records_for("file_access", recovery_loader.carved_file_access_rows(
        _engine(FILE_COPIES + [FILE_UNIQUE])))
    assert not view.chip_hide_copies.isChecked()
    view.chip_hide_copies.click()
    assert view.table.model().rowCount() == 2
    assert "left out of Export view; kept in the full case exports" in view.count_label.text()


# --- addresses recovered as text alone ---------------------------------------

import types


def test_file_addresses_recovered_as_text_alone_are_counted_and_placed():
    """Domains counts every recovered file: address (1,957 on a real
    machine); File Access lists records (1,573). The 384 between them were
    whole stored addresses carved as text, with no record to place them
    by -- said beside the count, not left as two numbers that disagree."""
    engine = types.SimpleNamespace(
        structured_records=[],
        all_artifacts=lambda: [
            {"Url": "Visited: a@file:///C:/x.txt"},
            {"Url": ":2026051120260518: a@file:///C:/y.txt"},
            {"Url": "https://a.example/"},
            {"Url": "bfile:///torn"}])
    assert recovery_loader.file_text_only_count(engine) == 2
    note = recovery_loader.file_access_note(235, 1338, 384)
    assert note.startswith("235 live, 1,338 recovered"), note
    assert "384 more" in note and "Deleted Records" in note, note
    assert recovery_loader.file_access_note(1, 2, 0) == "1 live, 2 recovered"
