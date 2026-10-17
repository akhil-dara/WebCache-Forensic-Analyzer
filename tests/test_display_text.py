"""One display_text() is the single source for the grid, the search box,
the value picker and every text filter operator -- see the module docstring
in webcache/widgets/column_spec.py. Before this, the grid painted "Yes",
"12,345" and "0x003B0523" while the search haystack and every text operator
in record_filter.py compared against str(value) instead -- a search for
what was on screen returned zero rows, or worse, a non-zero count matched
through a column the examiner was not reading at all.
"""
import datetime

from webcache.widgets.column_spec import Column, display_text
from webcache.widgets.record_filter import Condition, RecordFilter


def test_display_text_is_what_the_grid_paints():
    assert display_text(True, Column("s", "S", 60, kind="flag")) == "Yes"
    assert display_text(False, Column("s", "S", 60, kind="flag")) == "No"
    assert display_text(12345, Column("n", "N", 60, kind="num")) == "12,345"
    assert display_text(0x3B0523, Column("o", "O", 60, kind="offset")) == "0x003B0523"


def test_display_text_blank_and_datetime():
    assert display_text(None, Column("s", "S", 60)) == ""
    assert display_text("", Column("s", "S", 60)) == ""
    dt = datetime.datetime(2024, 6, 15, 9, 30, 0)
    assert display_text(dt, Column("t", "T", 60, kind="time")) == "2024-06-15 09:30:00"
    assert display_text("plain", Column("s", "S", 60, kind="text")) == "plain"


def test_searching_for_what_is_on_screen_finds_it():
    cols = [Column("s", "Secure", 60, kind="flag")]
    f = RecordFilter([{"s": True}, {"s": False}], cols)
    f.set_text("yes")
    assert len(f.visible()) == 1


def test_a_text_condition_matches_the_displayed_number():
    cols = [Column("n", "N", 60, kind="num")]
    f = RecordFilter([{"n": 12345}], cols)
    f.set_condition("n", Condition("contains", "12,345"))
    assert len(f.visible()) == 1


# --- Binding requirement 1: no search that works today may stop working ---

def test_search_finds_both_spellings_of_a_numeric_cell():
    """The grid shows FileSize as "12,345". An examiner who has always
    typed the plain digits must keep finding it -- becoming display-text-
    only would silently break every saved habit of typing unseparated
    numbers into the search box."""
    cols = [Column("FileSize", "Size", 90, kind="num")]
    f = RecordFilter([{"FileSize": 12345}, {"FileSize": 999}], cols)

    f.set_text("12345")
    assert len(f.visible()) == 1

    f.set_text("12,345")
    assert len(f.visible()) == 1


def test_search_does_not_match_a_boolean_hidden_spelling():
    """An examiner never sees the word "true" -- the grid paints "Yes".
    Matching a hidden str(value) spelling for a boolean is exactly the
    wrong-count defect this task removes, so "true" must find nothing
    unless another VISIBLE cell actually contains "true"."""
    cols = [Column("Secure", "Secure", 60, kind="flag"),
            Column("Title", "Title", 200, kind="text")]
    f = RecordFilter([{"Secure": True, "Title": "no mention here"}], cols)
    f.set_text("true")
    assert len(f.visible()) == 0


def test_search_does_not_match_offsets_hidden_decimal_spelling():
    """An "offset" column paints hex ("0x003B0523"). Its underlying int
    also has a decimal string spelling that is never shown on screen --
    adding that hidden spelling to the haystack would reintroduce the same
    class of bug the boolean case above guards against, just for a
    different kind."""
    cols = [Column("Offset", "Offset", 90, kind="offset")]
    f = RecordFilter([{"Offset": 0x3B0523}], cols)
    f.set_text(str(0x3B0523))  # "3866403", the decimal spelling, never shown
    assert len(f.visible()) == 0
    f.set_text("3B0523")  # the hex digits actually painted (case-insensitive)
    assert len(f.visible()) == 1


# --- Binding requirement 3: is blank / is not blank still agree ----------

def test_is_blank_and_is_not_blank_always_disagree():
    values = [None, "", "   ", 0, False, True, "x"]
    for value in values:
        blank = Condition("is blank").matches(value)
        not_blank = Condition("is not blank").matches(value)
        assert blank != not_blank, (
            "is blank/is not blank agreed for %r: blank=%s not_blank=%s"
            % (value, blank, not_blank))
    # "   " (whitespace) is intentionally NOT blank under this class's own
    # _blank() rule (only None or "" count) -- pinned here so a future
    # change to what counts as blank cannot silently break the invariant
    # above without a test noticing what changed.
    assert Condition("is not blank").matches("   ") is True
