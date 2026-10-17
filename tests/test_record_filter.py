"""The filter and sort engine.

QSortFilterProxyModel is banned here on measured grounds: 20,624 ms to sort
100k rows against 30.3 ms for rows.sort(), and 10,320 ms for a filter
keystroke against 384 ms. This module is what replaces it.
"""
import datetime

import pytest

from webcache.widgets.record_filter import (OPERATORS_BY_KIND, Condition,
                                            RecordFilter)
from webcache.widgets.column_spec import Column
from tests.fixtures import FIXTURE_COLUMNS, make_rows


@pytest.fixture
def rf():
    return RecordFilter(make_rows(2_000), list(FIXTURE_COLUMNS))


# --- text search ---------------------------------------------------------

def test_no_filter_shows_everything(rf):
    assert rf.visible_count == rf.total_count == 2_000
    assert rf.emptied_by() is None


def test_text_search_is_case_insensitive_and_spans_columns(rf):
    rf.set_text("NIMBUS")
    assert 0 < rf.visible_count < 2_000
    assert all("nimbus" in r["CleanUrl"].lower() or "nimbus" in r["Title"].lower()
               for r in rf.visible())


def test_clearing_the_text_restores_every_row(rf):
    """The bug reported against the earlier version: 'if u search and remove in
    filter, it is not resetting at all'."""
    rf.set_text("nimbus")
    assert rf.visible_count < 2_000
    rf.set_text("")
    assert rf.visible_count == 2_000


def test_a_search_matching_nothing_reports_what_emptied_it(rf):
    rf.set_text("zzzzz-no-such-value")
    assert rf.visible_count == 0
    assert rf.emptied_by() == "the search box"


# --- operators -----------------------------------------------------------

@pytest.mark.parametrize("op,operand,value,expected", [
    ("contains", "msn", "www.msn.com", True),
    ("contains", "msn", "www.bing.com", False),
    ("does not contain", "msn", "www.bing.com", True),
    ("begins with", "https", "https://x", True),
    ("begins with", "https", "http://x", False),
    ("ends with", ".com", "www.msn.com", True),
    ("ends with", ".com", "www.msn.org", False),
    ("equals", "msn.com", "msn.com", True),
    ("does not equal", "msn.com", "bing.com", True),
    ("is blank", None, "", True),
    ("is blank", None, "x", False),
    ("is not blank", None, "x", True),
    ("matches regex", r"^https://\w+\.msn", "https://www.msn.com", True),
    ("matches regex", r"^zzz", "https://www.msn.com", False),
])
def test_text_operators(op, operand, value, expected):
    assert Condition(op, operand).matches(value) is expected


@pytest.mark.parametrize("op,a,b,value,expected", [
    ("=", 5, None, 5, True),
    ("!=", 5, None, 6, True),
    (">", 5, None, 6, True),
    (">=", 5, None, 5, True),
    ("<", 5, None, 4, True),
    ("<=", 5, None, 5, True),
    ("between", 5, 10, 7, True),
    ("between", 5, 10, 11, False),
    ("is blank", None, None, None, True),
])
def test_numeric_operators(op, a, b, value, expected):
    assert Condition(op, a, b).matches(value) is expected


def test_case_sensitivity_is_off_by_default_and_can_be_turned_on():
    assert Condition("contains", "MSN").matches("www.msn.com") is True
    assert Condition("contains", "MSN", case_sensitive=True).matches("www.msn.com") is False


def test_invalid_regex_is_reported_not_raised():
    c = Condition("matches regex", "([unclosed")
    assert c.error is not None
    assert c.matches("anything") is False


def test_every_kind_offers_operators_and_they_all_exist():
    """Every operator OPERATORS_BY_KIND advertises for a kind must actually
    discriminate a real match from a real non-match on a value of that
    kind -- not merely construct without raising.

    The weaker version of this test (construct with generic operands "x"
    and "y", assert no .error) let four time operators -- before, after,
    on, in the last N days -- pass while doing nothing at all: they fell
    through to a text-comparison branch that never matched, and "no
    exception at construction" is just as true of a dead branch as a live
    one. This version proves each operator actually works.
    """
    for kind, ops in OPERATORS_BY_KIND.items():
        assert ops, "kind %s offers no operators" % kind

    text_value = "hello world"
    text_operands = {
        "contains": ("hello", "zzz"),
        "does not contain": ("zzz", "hello"),
        "begins with": ("hello", "world"),
        "ends with": ("world", "hello"),
        "equals": ("hello world", "nope"),
        "does not equal": ("nope", "hello world"),
        "matches regex": (r"^hello", r"^zzz"),
        "matches pattern": ("hello*", "zzz*"),
        "does not match pattern": ("zzz*", "hello*"),
    }
    for kind in ("text", "url", "flag", "domain", "types", "carved",
                "only_carved", "path"):
        for op in OPERATORS_BY_KIND[kind]:
            if op == "is blank":
                assert Condition(op).matches("") is True
                assert Condition(op).matches(text_value) is False
            elif op == "is not blank":
                assert Condition(op).matches(text_value) is True
                assert Condition(op).matches("") is False
            else:
                a_true, a_false = text_operands[op]
                assert Condition(op, a_true).matches(text_value) is True
                assert Condition(op, a_false).matches(text_value) is False

    num_value = 7
    num_operands = {
        "=": (7, 8), "!=": (8, 7), ">": (5, 9), ">=": (7, 8),
        "<": (9, 5), "<=": (7, 5),
    }
    for kind in ("num", "count", "size"):
        for op in OPERATORS_BY_KIND[kind]:
            if op == "is blank":
                assert Condition(op).matches(None) is True
                assert Condition(op).matches(num_value) is False
            elif op == "between":
                assert Condition(op, 5, 10).matches(num_value) is True
                assert Condition(op, 100, 200).matches(num_value) is False
            else:
                a_true, a_false = num_operands[op]
                assert Condition(op, a_true).matches(num_value) is True
                assert Condition(op, a_false).matches(num_value) is False

    time_value = datetime.datetime(2024, 6, 15, 12, 0, 0,
                                    tzinfo=datetime.timezone.utc)
    for kind in ("time", "time_local"):
        for op in OPERATORS_BY_KIND[kind]:
            if op == "is blank":
                assert Condition(op).matches(None) is True
                assert Condition(op).matches(time_value) is False
            elif op == "before":
                assert Condition(op, "2024-06-16").matches(time_value) is True
                assert Condition(op, "2024-06-01").matches(time_value) is False
            elif op == "after":
                assert Condition(op, "2024-06-01").matches(time_value) is True
                assert Condition(op, "2024-06-20").matches(time_value) is False
            elif op == "on":
                assert Condition(op, "2024-06-15").matches(time_value) is True
                assert Condition(op, "2024-06-16").matches(time_value) is False
            elif op == "between":
                assert Condition(op, "2024-06-01", "2024-06-30").matches(time_value) is True
                assert Condition(op, "2023-01-01", "2023-12-31").matches(time_value) is False
            elif op == "in the last N days":
                near_anchor = time_value
                far_anchor = time_value - datetime.timedelta(days=100)
                assert Condition(op, 1, anchor=near_anchor).matches(time_value) is True
                assert Condition(op, 1, anchor=far_anchor).matches(time_value) is False
            else:
                # A future operator added to _TIME_OPS without a matching
                # branch here would otherwise just be skipped -- zero
                # assertions run, the loop moves on, and the test still
                # goes green. That is the exact "constructs fine, verifies
                # nothing" shape this test was written to catch in the
                # first place, just one level up.
                pytest.fail("kind %s op %s not covered" % (kind, op))


# --- time operators --------------------------------------------------------

def test_on_matches_regardless_of_time_of_day():
    morning = datetime.datetime(2024, 6, 15, 6, 0, 0, tzinfo=datetime.timezone.utc)
    evening = datetime.datetime(2024, 6, 15, 23, 59, 0, tzinfo=datetime.timezone.utc)
    next_day = datetime.datetime(2024, 6, 16, 0, 1, 0, tzinfo=datetime.timezone.utc)
    c = Condition("on", "2024-06-15")
    assert c.matches(morning) is True
    assert c.matches(evening) is True
    assert c.matches(next_day) is False


def test_time_between_is_inclusive_at_both_ends():
    lo = datetime.datetime(2024, 6, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    hi = datetime.datetime(2024, 6, 30, 0, 0, 0, tzinfo=datetime.timezone.utc)
    c = Condition("between", "2024-06-01", "2024-06-30")
    assert c.matches(lo) is True
    assert c.matches(hi) is True
    assert c.matches(lo - datetime.timedelta(seconds=1)) is False
    assert c.matches(hi + datetime.timedelta(seconds=1)) is False


def test_naive_operand_is_treated_as_utc_against_aware_values():
    """Fixture timestamps are timezone-aware UTC. A naive operand parsed
    from a plain 'YYYY-MM-DD' string must not raise TypeError when
    compared against them, and must mean the same instant a UTC-labelled
    operand would."""
    aware_value = datetime.datetime(2024, 6, 20, 10, 0, tzinfo=datetime.timezone.utc)
    naive_condition = Condition("after", "2024-06-15")  # no offset in the string
    assert naive_condition.error is None
    assert naive_condition.matches(aware_value) is True


def test_unparseable_time_operand_sets_error_and_matches_nothing():
    c = Condition("before", "not-a-date")
    assert c.error is not None
    assert c.matches(datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)) is False


def test_time_condition_via_recordfilter_restricts_rows(rf):
    """The predicate is only half the feature; it has to be wired into
    RecordFilter the same way every other condition is."""
    rf.set_condition("AccessedUtc", Condition("after", "2024-06-01"))
    assert rf.visible_count > 0
    cutoff = datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)
    for r in rf.visible():
        assert r["AccessedUtc"] is not None
        assert r["AccessedUtc"] > cutoff


def test_in_the_last_n_days_anchors_to_newest_record_not_today(rf):
    """The fixture rows are dated in 2024; 'today' is nowhere near them.
    Anchoring to today would return zero rows, which reads as 'no activity
    in that window' -- a false negative an examiner could act on wrongly.
    Anchoring to the newest record in the (unfiltered) column means what an
    analyst actually intends: the last N days of activity in the evidence."""
    rf.set_condition("AccessedUtc", Condition("in the last N days", 7))
    assert rf.visible_count > 0
    newest = max(r["AccessedUtc"] for r in rf.rows if r["AccessedUtc"])
    for r in rf.visible():
        assert r["AccessedUtc"] is not None
        assert (newest - r["AccessedUtc"]).total_seconds() <= 7 * 86400


def test_in_the_last_n_days_re_anchors_after_set_rows(rf):
    """set_rows can replace the data underneath an attached condition --
    this application does exactly that when a recovery scan merges carved
    records into the view after the analyst has already filtered, and
    carved timestamps can be newer or older than the live ones already on
    screen. The anchor must track the CURRENT row set, not the one that
    existed when the condition was attached."""
    rf.set_condition("AccessedUtc", Condition("in the last N days", 30))
    old_anchor = max(r["AccessedUtc"] for r in rf.rows if r["AccessedUtc"])
    assert rf.visible_count > 0
    for r in rf.visible():
        assert (old_anchor - r["AccessedUtc"]).total_seconds() <= 30 * 86400

    # A fresh row set whose newest timestamp is roughly 400 days later. If
    # the anchor were still the old one -- captured once, at attachment,
    # rather than resolved fresh -- every row here would look far outside
    # "the last 30 days" and the table would go empty.
    later_rows = make_rows(2_000, seed=123)
    for r in later_rows:
        if r["AccessedUtc"] is not None:
            r["AccessedUtc"] += datetime.timedelta(days=400)
        if r["AccessedLocal"] is not None:
            r["AccessedLocal"] += datetime.timedelta(days=400)

    rf.set_rows(later_rows)
    new_anchor = max(r["AccessedUtc"] for r in rf.rows if r["AccessedUtc"])
    assert new_anchor > old_anchor + datetime.timedelta(days=300)
    assert rf.visible_count > 0
    for r in rf.visible():
        assert r["AccessedUtc"] is not None
        assert (new_anchor - r["AccessedUtc"]).total_seconds() <= 30 * 86400
        # None of the surviving rows are anywhere near the OLD anchor's
        # window -- proof the anchor actually moved, not that some rows
        # happened to satisfy both windows by coincidence.
        assert (r["AccessedUtc"] - old_anchor).total_seconds() > 200 * 86400


# --- ambiguous operators: numeric vs. time, decided by the value ---------

def test_compact_numeric_date_operand_matches_like_iso_form():
    """20240101 parses as a number AND is a valid date -- only the value
    being compared against can tell you which one an examiner meant. If
    the operand's own shape decided it, this would take the numeric
    branch, compare a float against a datetime, and silently return
    nothing."""
    iso = Condition("between", "2024-06-01", "2024-06-30")
    compact = Condition("between", "20240601", "20240630")
    inside = datetime.datetime(2024, 6, 15, 9, 0, tzinfo=datetime.timezone.utc)
    outside = datetime.datetime(2024, 7, 1, 9, 0, tzinfo=datetime.timezone.utc)
    assert compact.matches(inside) is True
    assert iso.matches(inside) is True
    assert compact.matches(outside) is False
    assert iso.matches(outside) is False


def test_compact_date_operand_returns_same_rows_as_iso_form(rf):
    """The same proof, wired through RecordFilter against the fixture
    column rather than asserted on Condition in isolation."""
    rf.set_condition("AccessedUtc", Condition("between", "20240101", "20240601"))
    compact_rows = {id(r) for r in rf.visible()}
    rf.set_condition("AccessedUtc", Condition("between", "2024-01-01", "2024-06-01"))
    iso_rows = {id(r) for r in rf.visible()}
    assert compact_rows == iso_rows
    assert len(compact_rows) > 0


def test_ambiguous_operator_with_unparseable_operand_sets_error():
    """An operand that is neither a number nor a date, given to an operator
    offered for both kinds of column, is a genuine problem -- not
    ambiguity to resolve later against a value."""
    c = Condition(">", "not-a-number-or-date")
    assert c.error is not None
    assert c.matches(7) is False
    assert c.matches(datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)) is False


def test_ambiguous_operator_does_not_poison_other_rows_in_a_mixed_type_column():
    """A column carved out of a damaged database can hold both numbers and
    dates in different rows (see _sort_key's docstring). An operand
    written for one of those types must not silently blank out rows of the
    other type it never claimed to describe -- .error is a single flag
    shared by the whole condition, so setting it the moment a mismatched
    row is seen would disable every row evaluated afterward, including the
    ones the operand was actually written for."""
    c = Condition(">", "2024-06-01")  # a date operand; not a number
    # The date-typed row this operand was written for:
    assert c.matches(datetime.datetime(2024, 12, 1, tzinfo=datetime.timezone.utc)) is True
    # A numeric-typed row elsewhere in the same carved column simply does
    # not match -- and, critically, does not poison the condition:
    assert c.matches(42) is False
    assert c.error is None
    assert c.matches(datetime.datetime(2024, 12, 2, tzinfo=datetime.timezone.utc)) is True


def test_between_with_type_disagreeing_operands_sets_error_and_matches_nothing():
    """5 reads only as a number; "2024-01-01" reads only as a date. Between
    needs both bounds read the SAME way -- a number can't be "between" a
    number and a date. Validating each operand independently and accepting
    any combination that individually passed was the bug: .error stayed
    None while the condition matched nothing at all, for any value,
    forever, with no way for a caller to notice."""
    c = Condition("between", 5, "2024-01-01")
    assert c.error is not None
    assert c.matches(7) is False
    assert c.matches(datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)) is False


def test_between_with_int_compact_dates_matches_like_string_form():
    """A compact date can arrive as a plain int -- a YYYYMMDD spinbox, or a
    value round-tripped through JSON -- not just a string. It must work
    exactly like the string form, not merely fail loudly (or worse, fail
    silently: _parse_dt previously rejected any int outright)."""
    string_form = Condition("between", "20240601", "20240630")
    int_form = Condition("between", 20240601, 20240630)
    assert int_form.error is None
    inside = datetime.datetime(2024, 6, 15, 9, 0, tzinfo=datetime.timezone.utc)
    outside = datetime.datetime(2024, 7, 1, 9, 0, tzinfo=datetime.timezone.utc)
    assert int_form.matches(inside) == string_form.matches(inside) == True
    assert int_form.matches(outside) == string_form.matches(outside) == False


def test_between_int_compact_dates_via_recordfilter_matches_string_form(rf):
    """Same proof, wired through RecordFilter against the fixture column."""
    rf.set_condition("AccessedUtc", Condition("between", 20240101, 20240601))
    int_rows = {id(r) for r in rf.visible()}
    rf.set_condition("AccessedUtc", Condition("between", "2024-01-01", "2024-06-01"))
    string_rows = {id(r) for r in rf.visible()}
    assert int_rows == string_rows
    assert len(int_rows) > 0


def test_unknown_operator_sets_error_and_matches_nothing():
    """A typo'd or otherwise unrecognised operator string must not fall
    through to matches()'s text-comparison tail, which would return True
    unconditionally -- every row looking like a match is a far harder
    failure for an examiner to notice than an empty table."""
    c = Condition("is somewhere near", "whatever")
    assert c.error is not None
    assert c.matches("whatever") is False
    assert c.matches(None) is False


# --- values panel --------------------------------------------------------

def test_value_selection_restricts_rows(rf):
    rf.set_values("Domain", {"msn.com"})
    assert rf.visible_count > 0
    assert {r["Domain"] for r in rf.visible()} == {"msn.com"}


def test_empty_value_set_means_none_selected_not_no_filter(rf):
    """'None' must mean none. An empty set that silently meant 'everything'
    was a real bug in the earlier version."""
    rf.set_values("Domain", set())
    assert rf.visible_count == 0
    assert rf.emptied_by() == "Domain"


def test_clearing_a_value_filter_with_None_restores_rows(rf):
    rf.set_values("Domain", set())
    rf.set_values("Domain", None)
    assert rf.visible_count == 2_000


def test_value_counts_cover_every_distinct_value(rf):
    counts = rf.value_counts("Domain")
    assert sum(n for _v, n in counts) == 2_000
    assert len(counts) == len({r["Domain"] for r in rf.rows})


# --- values AND condition together ---------------------------------------

def test_values_and_condition_combine_rather_than_replace(rf):
    """Excel discards ticked values when a text condition is applied. For
    evidence work that is dangerous: you cannot afterwards be certain what
    produced the rows in front of you. Both apply."""
    rf.set_values("Domain", {"msn.com", "bing.com"})
    rf.set_condition("CleanUrl", Condition("contains", "login"))
    for r in rf.visible():
        assert r["Domain"] in ("msn.com", "bing.com")
        assert "login" in r["CleanUrl"]


def test_chip_text_states_both_parts(rf):
    rf.set_values("Domain", {"msn.com"})
    rf.set_condition("CleanUrl", Condition("contains", "whatsapp"))
    chip = rf.chip_text()
    assert "contains" in chip and "whatsapp" in chip
    assert "Domain: Is msn.com" in chip


def test_emptied_by_identifies_the_condition_when_both_are_on_one_column(rf):
    """A column can carry a values-panel filter AND a condition at once --
    set_values and set_condition combine, not replace (see
    test_values_and_condition_combine_rather_than_replace) -- and chip_text
    renders them as two SEPARATE chips. If both are attached to the SAME
    key and together they empty the table, emptied_by must say which ONE
    of the two is responsible, not just the column name: the old loop
    walked list(self._values) + list(self._conditions), so "Domain"
    appeared twice, and both comprehensions stripped it from BOTH dicts at
    once -- it could only ever test "remove both together", never isolate
    either one."""
    rf.set_values("Domain", {"msn.com"})
    # A condition no Domain value can ever satisfy, combined with the
    # values filter, empties the table -- but the values filter alone
    # would not (msn.com rows exist).
    rf.set_condition("Domain", Condition("equals", "no-such-domain-anywhere"))
    assert rf.visible_count == 0
    assert rf.emptied_by() == "Domain (condition)"


def test_emptied_by_identifies_the_values_filter_when_both_are_on_one_column(rf):
    """Same column, opposite culprit: the condition alone would leave rows
    (Domain is never blank in the fixture), the ticked values are what
    empties the table."""
    rf.set_values("Domain", {"totally-unused-domain.example"})
    rf.set_condition("Domain", Condition("is not blank"))
    assert rf.visible_count == 0
    assert rf.emptied_by() == "Domain (values)"


def test_emptied_by_stays_a_bare_key_when_only_one_filter_is_on_the_column(rf):
    """Backward compatibility: a column with only a condition (no values
    filter attached at all) still reports the bare key, exactly as before
    -- the "(condition)"/"(values)" suffix only appears when there is
    something to disambiguate."""
    rf.set_condition("VisitCount", Condition(">", 100000))
    assert rf.visible_count == 0
    assert rf.emptied_by() == "VisitCount"


def test_emptied_by_names_both_filters_when_dropping_either_alone_still_empties_it(rf):
    """The dead end the emptied_by split (above) introduced as a
    regression: a column can carry a values filter AND a condition where
    NEITHER alone restores any rows -- each, tried on its own, still
    matches zero -- but dropping BOTH together would. Before the
    last-resort pass in emptied_by(), both single-drop loops failed here
    and the function fell through to `return None`: a genuine dead end,
    in exactly the shape the filter popup produces (it applies values and
    a condition together), and the case an examiner is most likely to hit
    right after using it."""
    # Neither the ticked value nor the condition's operand matches any
    # real Domain in the fixture -- each is independently a 0-row filter.
    rf.set_values("Domain", {"totally-unused-domain.example"})
    rf.set_condition("Domain", Condition("equals", "also-not-a-real-domain"))
    assert rf.visible_count == 0
    assert rf.emptied_by() == "Domain (values + condition)"


def test_emptied_by_agrees_with_recompute_about_a_text_op_on_a_flag_column(rf):
    """_recompute matches a TEXT_OPS condition against
    column_spec.display_text(...) (a flag column's grid cell reads "Yes"/
    "No", never the raw bool) -- see test_display_text.py. emptied_by()'s
    own recount, _count_matching, must resolve a condition's value the
    SAME way, or the two can disagree about what an empty table means.

    IsInPrivate is a flag column. "equals Yes" only ever matches through
    the DISPLAY spelling -- str(True) is "True", not "Yes" -- so by itself
    it still lets every True row through; it does not, on its own, empty
    anything. The Domain condition below matches no real domain in the
    fixture at all, and is the ONLY thing actually emptying the table.
    Dropping the IsInPrivate condition changes nothing (the Domain
    condition alone still matches zero); dropping the Domain condition
    restores the True rows. emptied_by() must say "Domain".

    Before the fix, _count_matching still compared this condition against
    the RAW bool (never "Yes"), so its own recount showed the IsInPrivate
    condition matching NOTHING by itself, and "dropping Domain" also
    looked like zero rows -- neither single-drop candidate looked like it
    restored anything, and the last-resort/search-box checks don't apply
    here either, so the old code fell all the way through to `return
    None`: a genuine dead end, in the exact shape the filter popup
    produces (two conditions, on two columns, one of them a flag)."""
    rf.set_condition("IsInPrivate", Condition("equals", "Yes"))
    rf.set_condition("Domain", Condition("equals", "no-such-domain-anywhere"))
    assert rf.visible_count == 0
    assert rf.emptied_by() == "Domain"


def test_clear_all_really_clears_everything(rf):
    rf.set_text("msn")
    rf.set_values("Domain", {"msn.com"})
    rf.set_condition("VisitCount", Condition(">", 100))
    rf.clear_all()
    assert rf.visible_count == 2_000
    assert rf.chip_text() == ""


# --- sorting -------------------------------------------------------------

def test_sort_by_text_ascending_and_descending(rf):
    rf.sort("Domain")
    asc = [r["Domain"] for r in rf.visible()]
    assert asc == sorted(asc)
    rf.sort("Domain", descending=True)
    assert [r["Domain"] for r in rf.visible()] == sorted(asc, reverse=True)


def test_numeric_column_sorts_numerically_not_lexically(rf):
    rf.sort("VisitCount")
    vals = [r["VisitCount"] for r in rf.visible()]
    assert vals == sorted(vals)
    assert vals[0] <= 10 and vals[-1] >= 100


def test_datetime_column_sorts_chronologically(rf):
    """The bug the proxy route carried: sorting a datetime column through
    UserRole silently mis-orders it."""
    rf.sort("AccessedUtc")
    stamps = [r["AccessedUtc"] for r in rf.visible() if r["AccessedUtc"]]
    assert stamps == sorted(stamps)
    assert all(isinstance(s, datetime.datetime) for s in stamps)


def test_blanks_sort_last_in_both_directions(rf):
    """A block of blanks at the top of a 'last visit' sort is useless."""
    rf.sort("AccessedUtc")
    vis = rf.visible()
    first_blank = next(i for i, r in enumerate(vis) if r["AccessedUtc"] is None)
    assert all(v["AccessedUtc"] is None for v in vis[first_blank:])
    rf.sort("AccessedUtc", descending=True)
    vis = rf.visible()
    first_blank = next(i for i, r in enumerate(vis) if r["AccessedUtc"] is None)
    assert all(v["AccessedUtc"] is None for v in vis[first_blank:])


def test_sorting_mixed_types_does_not_raise():
    rows = [{"X": 1}, {"X": "a"}, {"X": None}, {"X": 2.5}]
    cols = [c for c in FIXTURE_COLUMNS if c.key == "Title"]
    rf = RecordFilter(rows, cols)
    rf.sort("X")
    assert len(rf.visible()) == 4


def test_descending_sort_keeps_numeric_group_before_text_group():
    """A plain reverse=True over a mixed-type column would flip the GROUP
    order along with each group's internal order: ascending puts numbers
    before text, so a naive reverse puts text before numbers on
    descending. That is a surprising, undocumented asymmetry for a carved
    column that legitimately mixes types in one field (see _sort_key's
    docstring): an analyst scanning for "the numbers" would find them in a
    different region of the list depending only on which way they last
    clicked the header. The numeric block stays first in both directions;
    only the order WITHIN each block reverses."""
    rows = [{"X": 1}, {"X": 5}, {"X": "banana"}, {"X": "apple"}, {"X": None}]
    cols = [c for c in FIXTURE_COLUMNS if c.key == "Title"]
    rf = RecordFilter(rows, cols)

    rf.sort("X")
    assert [r["X"] for r in rf.visible()] == [1, 5, "apple", "banana", None]

    rf.sort("X", descending=True)
    # Numeric block still first (now largest-to-smallest); text block
    # still second (now Z-to-A); blank still last.
    assert [r["X"] for r in rf.visible()] == [5, 1, "banana", "apple", None]


def test_sort_survives_a_filter_change(rf):
    rf.sort("VisitCount", descending=True)
    rf.set_text("msn")
    vals = [r["VisitCount"] for r in rf.visible()]
    assert vals == sorted(vals, reverse=True)


def test_set_rows_rebuilds_the_haystack(rf):
    rf.set_text("nimbus")
    before = rf.visible_count
    rf.set_rows(make_rows(2_000, seed=99))
    rf.set_text("nimbus")
    assert rf.visible_count != before or rf.total_count == 2_000


def test_sort_key_cache_is_invalidated_by_set_rows():
    """Pins the sort-key cache's invalidation contract (RecordFilter._keys_for
    / set_rows). A sort against keys built for rows that are gone is exactly
    the class of bug this module has already produced more than once (see
    emptied_by's docstring and Condition's anchor-recompute note) -- this
    time against a cache instead of a filter or an anchor, so it needs its
    own pin rather than trusting the existing ones to cover it.

    Sorts the SAME column before and after set_rows swaps in entirely
    different data, and asserts the second sort reflects the NEW rows. If
    the cache were stale, this either orders by values that no longer exist
    (silent, wrong) or raises KeyError on a row id the stale cache never
    saw (loud, also wrong) -- either way, a real failure. See below for a
    demonstration that it actually does fail when invalidation is disabled.
    """
    cols = [c for c in FIXTURE_COLUMNS if c.key == "VisitCount"]

    first = [{"VisitCount": 50}, {"VisitCount": 10}, {"VisitCount": 30}]
    rf = RecordFilter(first, cols)
    rf.sort("VisitCount")  # warms the VisitCount cache against `first`
    assert [r["VisitCount"] for r in rf.visible()] == [10, 30, 50]

    second = [{"VisitCount": 5}, {"VisitCount": 100}, {"VisitCount": 1}]
    rf.set_rows(second)
    rf.sort("VisitCount")  # same column key again -- must not reuse `first`'s cache
    assert [r["VisitCount"] for r in rf.visible()] == [1, 5, 100]


def test_every_declared_kind_has_filter_operators():
    """GENERIC on purpose, so a future kind cannot be added without them.

    filter_popup.py indexes OPERATORS_BY_KIND[col.kind] directly: a kind
    with no entry raises KeyError the first time an examiner right-clicks
    that heading, and the funnel is this application's whole
    per-column filter. Written against KINDS rather than against a
    hand-copied list, because a hand-copied list is exactly what goes
    stale.
    """
    from webcache.widgets.column_spec import KINDS

    missing = [k for k in KINDS if k not in OPERATORS_BY_KIND]
    assert not missing, (
        "these column kinds have no filter operators, so right-clicking "
        "one of their headings raises: %s" % ", ".join(missing))
    for kind in KINDS:
        assert OPERATORS_BY_KIND[kind], kind


# --- a formatted value that must sort by what it measures ------------------
#
# Location's "Times differ by" column holds strings a person can read --
# "+1 d 2 h (device ahead)", "-3 h (device behind)", "none". Sorted as text
# they order lexically, so a descending sort put "-3 h" above "+5 d" and the
# column could not answer the only question it exists to answer: which fixes
# disagree most with the record that carried them.
#
# The fix is a hook, not a special case: a Column may name a SIBLING row key
# to sort on while continuing to display its own. Any column whose display
# form is not its magnitude can use it.

def test_a_column_may_sort_on_a_sibling_key_while_displaying_its_own():
    cols = [Column("Shown", "Times differ by", kind="text",
                   sort_by="Magnitude")]
    rows = [{"Shown": "-3 h (behind)", "Magnitude": -10800},
            {"Shown": "+5 d (ahead)", "Magnitude": 432000},
            {"Shown": "none", "Magnitude": 0},
            {"Shown": "+41 s (ahead)", "Magnitude": 41}]
    rf = RecordFilter(rows, cols)
    rf.sort("Shown", descending=True)
    got = [r["Shown"] for r in rf.visible()]
    assert got[0] == "+5 d (ahead)", (
        "descending order is %r -- sorted as text, not by what the text "
        "measures" % (got,))
    assert [r["Magnitude"] for r in rf.visible()] == [432000, 41, 0, -10800]


def test_a_column_without_the_hook_is_unaffected():
    cols = [Column("Shown", "Shown", kind="text")]
    rows = [{"Shown": "b"}, {"Shown": "a"}, {"Shown": "c"}]
    rf = RecordFilter(rows, cols)
    rf.sort("Shown")
    assert [r["Shown"] for r in rf.visible()] == ["a", "b", "c"]
