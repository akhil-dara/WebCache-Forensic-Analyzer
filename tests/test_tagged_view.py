"""Tagged: every record the examiner has tagged or commented on, in one
list, with the tags and comments beside it -- the case's own work
product, filterable, exportable and openable like any record view."""
import pytest

from webcache.engine.case_db import CaseDb
from webcache.shell import case_notes, tagged_loader


def _entry(i, **extra):
    e = {"ContainerId": 6, "EntryId": i, "ContainerType": "History",
         "Url": "https://example.test/%d" % i,
         "CleanUrl": "https://example.test/%d" % i,
         "AccessedTime_raw": 133843382090000000}
    e.update(extra)
    return e


def _carved(i):
    return {"RecoverySource": "DB unallocated space", "Offset": 900 + i,
            "Page": 3, "Region": "page-slack", "Source": "WebCacheV01.dat",
            "Url": "https://c.test/%d" % i, "CleanUrl": "https://c.test/%d" % i}


@pytest.fixture
def case(tmp_path):
    db = CaseDb().open(str(tmp_path / "case.wccase"))
    yield db
    db.close()


def test_only_records_with_notes_are_listed(case):
    live = [_entry(1), _entry(2), _entry(3)]
    carved = [_carved(1)]
    case_notes.set_tag(case, [{"_record": live[1]}], "Relevant", True)
    case_notes.add_comment(case, [{"_record": carved[0]}], "From slack")
    rows = tagged_loader.tagged_rows(case, live, carved)
    assert sorted(r["CleanUrl"] for r in rows) == [
        "https://c.test/1", "https://example.test/2"]
    by_url = {r["CleanUrl"]: r for r in rows}
    assert by_url["https://example.test/2"]["Tags"] == "Relevant"
    assert by_url["https://c.test/1"]["Comments"] == "From slack"
    assert str(by_url["https://c.test/1"]["Origin"]).startswith("Carved")


def test_no_case_no_rows(case):
    assert tagged_loader.tagged_rows(None, [_entry(1)], []) == []


def test_the_view_shows_tags_and_comments_first(qtbot):
    from webcache.views.tagged import TaggedView
    v = TaggedView()
    qtbot.addWidget(v)
    keys = [c.key for c in v._segments_by_key["tagged"].columns]
    assert keys[:2] == ["Tags", "Comments"]
    assert "CleanUrl" in keys


def test_an_empty_list_says_how_to_tag(qtbot):
    from webcache.views.tagged import TaggedView, EMPTY_TEXT
    v = TaggedView()
    qtbot.addWidget(v)
    assert "Right-click" in EMPTY_TEXT


def test_tagging_in_any_view_updates_the_tagged_list(qtbot, tmp_path):
    from webcache.shell import main_window as mw

    class _Parser:
        all_entries = [_entry(1), _entry(2)]

    win = mw.MainWindow()
    qtbot.addWidget(win)
    win._parser = _Parser()
    win._case = CaseDb().open(str(tmp_path / "c.wccase"))
    try:
        win.go_to("tagged")
        win._push_tagged_state()      # what a finished load does
        view = win._built_widget("tagged")
        assert view.table.model().rowCount() == 0
        win._tag_rows([{"_record": _Parser.all_entries[0]}], "Relevant", True)
        assert view.table.model().rowCount() == 1
    finally:
        win._case.close()


def test_one_record_is_counted_in_the_singular(qtbot):
    """"1 tagged records" -- seen on screen the first time a record was
    tagged. Every count line reads one in the singular."""
    from webcache.views.tagged import TaggedView
    v = TaggedView()
    qtbot.addWidget(v)
    rows = tagged_loader.tagged_rows(None, [], [])
    v.set_records([{"CleanUrl": "https://a.test/", "Tags": "Relevant",
                    "Comments": "", "_record": _entry(1)}])
    assert v.count_label.text().startswith("1 tagged record")
    assert not v.count_label.text().startswith("1 tagged records")
