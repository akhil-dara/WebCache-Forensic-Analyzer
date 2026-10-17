"""Tagging and comments: the examiner's own work product on a record.

The case file always kept tags and comments, and every export has carried
Tags and Comments columns -- but nothing in the application could ADD
one, so those columns were empty in every file ever written. These pin
the rules the whole interface uses:

  * what can carry a note: a record, live or recovered -- never an
    aggregate (a domain, a period) or a raw table row, which have no
    record identity to key it to;
  * a tag applied to a selection reaches every record in it, once;
  * the counts a menu shows are counted over the selection;
  * a comment is stored with its author and time.
"""
import pytest

from webcache.engine.case_db import CaseDb
from webcache.shell import case_notes


def _live(i):
    entry = {"ContainerId": 6, "EntryId": i, "Url": "https://example.test/%d" % i}
    return {"CleanUrl": entry["Url"], "_record": entry}


def _carved(i):
    entry = {"RecoverySource": "DB unallocated space", "Offset": 4096 + i,
             "Page": 2, "Region": "page-slack", "Url": "https://c.test/%d" % i}
    return {"CleanUrl": entry["Url"], "_record": entry}


@pytest.fixture
def case(tmp_path):
    db = CaseDb().open(str(tmp_path / "case.wccase"))
    yield db
    db.close()


def test_records_carry_notes_aggregates_and_raw_rows_do_not():
    assert case_notes.is_taggable(_live(1))
    assert case_notes.is_taggable(_carved(1))
    assert not case_notes.is_taggable({"Domain": "a.test", "_members": []})
    assert not case_notes.is_taggable({"_kind": "table_row", "_record": None})
    assert not case_notes.is_taggable(None)


def test_a_tag_reaches_every_record_of_a_selection_once(case):
    rows = [_live(1), _live(2), _carved(3), {"Domain": "x"}]
    assert case_notes.set_tag(case, rows, "Relevant", True) == 3
    assert case_notes.set_tag(case, rows, "Relevant", True) == 0
    assert case_notes.tags_of(case, rows[0]) == ["Relevant"]
    assert case_notes.tag_counts(case, rows) == {"Relevant": 3}
    assert case_notes.set_tag(case, rows[:1], "Relevant", False) == 1
    assert case_notes.tag_counts(case, rows) == {"Relevant": 2}


def test_a_tag_is_trimmed_and_an_empty_one_refused(case):
    assert case_notes.set_tag(case, [_live(1)], "  Follow up  ", True) == 1
    assert case_notes.tags_of(case, _live(1)) == ["Follow up"]
    with pytest.raises(ValueError):
        case_notes.set_tag(case, [_live(1)], "   ", True)


def test_a_comment_is_kept_with_its_author_and_time(case):
    assert case_notes.add_comment(case, [_live(1)], "Seen in two logs",
                                  author="J. Examiner") == 1
    (comment,) = case_notes.comments_of(case, _live(1))
    assert comment["comment"] == "Seen in two logs"
    assert comment["author"] == "J. Examiner"
    assert comment["created"].endswith("Z")


def test_the_presets_are_the_words_an_examiner_reaches_for():
    assert case_notes.PRESET_TAGS == ("Relevant", "Suspicious", "Follow up",
                                      "Not relevant")


def test_every_tag_in_the_case_is_offered_presets_first(case):
    case_notes.set_tag(case, [_live(1)], "Exfil", True)
    offered = case_notes.known_tags(case)
    assert offered[:4] == list(case_notes.PRESET_TAGS)
    assert "Exfil" in offered
