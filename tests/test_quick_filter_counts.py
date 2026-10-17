"""A selective chip says how many records it would keep, before it is
clicked.

Found working a case ("what did this user search for?") on a real
exhibit: the only way to learn that NO record carried search terms was to
tick "Has search terms" and read an emptied grid whose message spelled the
filter's internals ("Has search terms: is not blank"). The answer was
known the moment the records loaded; the chip now says it.

Counts are over the segment's whole record set, not after the other
filters -- a count that changes when a neighbouring chip is ticked reads
as the chip's own data changing.
"""
import pytest

from webcache.views.history import HistoryView
from tests.fixtures import make_rows


@pytest.fixture
def view(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    rows = make_rows(40)
    for i, r in enumerate(rows):
        r["SearchTerms"] = "x" if i < 3 else ""
        r["IsInPrivate"] = False
        r["IsLocalFile"] = i < 5
    v.set_records(rows)
    return v


def test_each_selective_chip_names_its_count(view):
    assert view.chip_search_terms.text() == "Has search terms · 3"
    assert view.chip_local_files.text() == "Local files only · 5"
    assert view.chip_inprivate.text() == "InPrivate only · 0"


def test_the_count_is_explained_on_hover(view):
    tip = view.chip_search_terms.toolTip()
    assert "3 of 40" in tip


def test_a_chip_that_hides_rows_carries_no_count(view):
    """"Hide duplicate copies" removes rows; a number beside it would read
    as how many it keeps."""
    for chip in (view.chip_hide_copies, view.chip_one_row_per_visit):
        assert "·" not in chip.text()


def test_the_count_does_not_move_when_another_chip_is_ticked(view):
    view.chip_local_files.click()
    assert view.chip_search_terms.text() == "Has search terms · 3"


def test_a_chip_that_would_show_nothing_says_why_and_its_count(qtbot):
    """Every row blank: the chip is disabled with the existing reason, and
    its label still says 0 -- the answer to "were there any?"."""
    v = HistoryView()
    qtbot.addWidget(v)
    rows = make_rows(10)
    for r in rows:
        r["SearchTerms"] = ""
    v.set_records(rows)
    assert v.chip_search_terms.text() == "Has search terms · 0"
    assert not v.chip_search_terms.isEnabled()
    assert "show nothing" in v.chip_search_terms.toolTip()
    rows[0]["SearchTerms"] = "x"
    v.set_records(rows)
    assert v.chip_search_terms.isEnabled()
    assert "1 of 10" in v.chip_search_terms.toolTip()


def test_the_export_button_says_what_it_saves_and_in_what_format(view):
    """"Export view" did not say what would be saved, or as what. The
    tooltip names the rows, the columns, both formats and the provenance
    file written beside it."""
    tip = view.export_button.toolTip()
    assert "40" in tip
    assert "CSV" in tip and "Excel" in tip
    assert "provenance" in tip.lower()
