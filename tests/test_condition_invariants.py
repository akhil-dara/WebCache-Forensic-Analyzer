"""A structural test for the bug class record_filter.py kept reproducing.

Four separate bugs, found across three review rounds, all had the exact
same shape: a Condition that reported no .error and yet could never match
anything, for any row, ever --

  1. before/after/on/between/"in the last N days" were declared in
     OPERATORS_BY_KIND with no matching branch in matches() at all.
  2. numeric-vs-time ambiguity for between/=/!=/etc. was resolved by
     trying to parse the OPERAND, so a compact date that also happened to
     parse as a plain number silently took the wrong branch.
  3. "in the last N days"'s anchor was captured once at attachment instead
     of resolved against the live row set.
  4. between(a, b) validated a and b independently, so a condition where
     they resolved to disagreeing kinds passed construction with
     .error is None and then matched nothing, forever.

Each was caught by a human writing a specific example-based test for the
specific broken combination -- after a reviewer had already found it by
running the code. The common root cause: this module never had a test for
the underlying INVARIANT ("a Condition that reports no .error should be
satisfiable by at least one plausible value"), only for specific instances
of it. The filter popup constructs Condition objects from live user
input, which is exactly where another instance of this bug class would
appear -- so this file tests the invariant directly,
generally, across every (kind, op) pair the module declares, rather than
waiting for a fifth reviewer to find a fifth specific case.

Two properties, both parametrized over every (kind, op) pair in
OPERATORS_BY_KIND:

  1. SATISFIABILITY. If .error is None, the condition must match at least
     one representative value of its own kind. A condition that
     constructs cleanly and then matches nothing is the bug.
  2. NEVER RAISES. matches() must return a plain bool -- never raise --
     for every representative value of EVERY kind, including the hostile
     cross-kind combinations a carved, damaged database really produces:
     a string in a numeric column, an int in a time column, a naive
     datetime compared against aware data, a bool where a real number was
     expected, blanks everywhere.

The representative-value tables below are written by hand, as literals,
independently of fixtures.py and of record_filter.py's own internals --
a table derived from the code under test is exactly how the ORIGINAL,
weaker version of test_every_kind_offers_operators_and_they_all_exist
passed while four time operators were dead. The one thing necessarily
imported from record_filter.py is OPERATORS_BY_KIND itself: it is the
module's declared public contract, and the whole point of this file is to
check every (kind, op) pair IT lists, not a hand-picked subset of them.
_KIND_FAMILY below is also written by hand, from what each kind name
actually means (a "count" is a number; a "domain" is text), not by
inspecting how record_filter.py happens to group them today -- so a
future accidental mis-grouping in OPERATORS_BY_KIND (e.g. "count" wired to
the wrong operator tuple) would itself surface as a KeyError here, not
just silently reuse whatever grouping the code under test asserts.
"""
import datetime

import pytest

from webcache.widgets.record_filter import Condition, OPERATORS_BY_KIND

# --- representative values, one small hand-written table per family ------

_TEXT_VALUES = [
    "https://www.msn.com/search?q=hello",
    "MSN.COM",
    "",
    "2024-06-01",   # a date-shaped string -- carved text columns hold these
    "12345",        # a number-shaped string -- ditto
    None,
]

_NUM_VALUES = [100, 0, -7, 3.14, 999999, None, True, False]

_TIME_ANCHOR = datetime.datetime(2024, 6, 15, 12, 0, 0,
                                  tzinfo=datetime.timezone.utc)
_TIME_VALUES = [
    _TIME_ANCHOR,
    datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc),
    datetime.datetime(2024, 6, 15, 23, 59, tzinfo=datetime.timezone.utc),
    datetime.datetime(2024, 6, 15, 12, 0, 0),   # naive -- treated as UTC
    datetime.date(2024, 6, 15),
    None,
]

_VALUES_BY_FAMILY = {
    "text": _TEXT_VALUES,
    "num": _NUM_VALUES,
    "time": _TIME_VALUES,
}

#: Every representative value across every family, for the never-raises
#: check: a Condition built for one kind gets thrown every OTHER kind's
#: values too, on purpose -- that is what actually exercises "a string in
#: a numeric column" and "an int in a time column".
_ALL_VALUES = _TEXT_VALUES + _NUM_VALUES + _TIME_VALUES

# --- plausible operands, one small hand-written table per family ---------
#
# These are not tuned to guarantee a pass -- they are what a real user (or
# the filter popup) would plausibly type for that operator, decided once, by
# hand, independently of how record_filter.py implements matching. Compact
# int dates (20240615 rather than "2024-06-15") are used deliberately for
# the time family: that is the realistic shape Finding 1's second bug case
# was about (a YYYYMMDD spinbox, or an operand round-tripped through
# JSON), and it is what the sanity check below reverts to prove this file
# actually has teeth.

_TEXT_OPERANDS = {
    "contains": ("msn.com", None),
    "does not contain": ("zzz-nowhere-zzz", None),
    "begins with": ("https://", None),
    "ends with": ("hello", None),
    "equals": ("msn.com", None),            # matches "MSN.COM", case-fold
    "does not equal": ("zzz-nowhere-zzz", None),
    "matches regex": (r"^https://", None),
    "matches pattern": ("https://*", None),
    "does not match pattern": ("zzz-nowhere-*", None),
}

_NUM_OPERANDS = {
    "=": (100, None),
    "!=": (999, None),
    ">": (50, None),
    ">=": (100, None),
    "<": (200, None),
    "<=": (100, None),
    "between": (50, 150),
}

_TIME_OPERANDS = {
    "before": (20240616, None),
    "after": (20240601, None),
    "on": (20240615, None),
    "between": (20240601, 20240630),
    "in the last N days": (2, None),   # anchor supplied separately below
}

_OPERANDS_BY_FAMILY = {
    "text": _TEXT_OPERANDS,
    "num": _NUM_OPERANDS,
    "time": _TIME_OPERANDS,
}

#: "is blank" and "is not blank" take no operand at all -- self.a plays no
#: part in their matching logic, so there is no operand shape for this bug
#: class to hide in. Whether they are satisfiable depends entirely on
#: whether a representative-value table happens to contain a blank / a
#: non-blank value, which is a property of the DATA, not of whether the
#: operator itself is correctly implemented. Named explicitly here, rather
#: than silently skipped inside a loop, so a reader (and a future add to
#: this set) sees exactly what is excluded and why -- and so a genuinely
#: new operator that ISN'T operand-less has to be deliberately added here
#: to be excused, instead of quietly falling through some unrelated check.
_SATISFIABILITY_EXEMPT = frozenset({"is blank", "is not blank"})

#: Every (kind, op) pair OPERATORS_BY_KIND actually declares -- the full
#: combinatorial space both properties below are checked against.
_ALL_PAIRS = [(kind, op) for kind, ops in OPERATORS_BY_KIND.items()
              for op in ops]

#: kind -> which representative-value / operand table applies. Written by
#: hand from what each kind name means, not derived from _TEXT_OPS /
#: _NUM_OPS / _TIME_OPS in record_filter.py -- see the module docstring.
_KIND_FAMILY = {
    "text": "text", "url": "text", "flag": "text", "domain": "text",
    "types": "text", "carved": "text", "only_carved": "text", "path": "text",
    "num": "num", "count": "num", "size": "num",
    # A byte position -- numeric for sort and filter exactly like "num",
    # just displayed as hex (see column_spec.KINDS's "offset" comment).
    "offset": "num",
    # A share is a number -- it is DRAWN rather than printed (see
    # widgets/bar_delegate.py), but nothing about how a cell is painted
    # changes which operand a filter on it takes.
    "bar": "num",
    "time": "time", "time_local": "time",
}


def _build_condition(op, family):
    """One Condition, using that family's hand-written plausible operand
    for `op`. "in the last N days" additionally needs an anchor -- there
    is no RecordFilter here to supply one automatically, so it is passed
    directly, the same way a Condition used standalone always must."""
    a, b = _OPERANDS_BY_FAMILY[family][op]
    kwargs = {"anchor": _TIME_ANCHOR} if op == "in the last N days" else {}
    return Condition(op, a, b, **kwargs), a, b


# --- property 1: satisfiability -------------------------------------------

@pytest.mark.parametrize("kind,op", _ALL_PAIRS,
                          ids=["%s-%s" % p for p in _ALL_PAIRS])
def test_condition_is_satisfiable_when_it_reports_no_error(kind, op):
    """If construction reported no .error, the condition must be able to
    match SOMETHING of its own kind. A condition that constructs cleanly
    and then matches nothing, for any value, forever, is exactly the bug
    class this file exists to catch -- see the module docstring for all
    four times that already happened here."""
    if op in _SATISFIABILITY_EXEMPT:
        pytest.skip("%s takes no operand; nothing about ITS correctness "
                     "can be expressed as an operand-satisfiability check "
                     "-- see _SATISFIABILITY_EXEMPT's comment" % op)

    family = _KIND_FAMILY[kind]
    cond, a, b = _build_condition(op, family)
    if cond.error is not None:
        # A reported error is the honest, visible outcome this whole file
        # exists to make the ONLY way a condition can fail to match
        # anything -- not a silent False. Nothing further to check here.
        return

    rep_values = _VALUES_BY_FAMILY[family]
    assert any(cond.matches(v) for v in rep_values), (
        "%s/%s with operands (%r, %r) can never match any representative "
        "value of its own kind %r even though construction reported no "
        "error (.error is None) -- this is the silent-match-nothing bug "
        "class record_filter.py has already produced four times."
        % (kind, op, a, b, rep_values))


# --- property 2: matches() never raises ------------------------------------

@pytest.mark.parametrize("kind,op", _ALL_PAIRS,
                          ids=["%s-%s" % p for p in _ALL_PAIRS])
def test_condition_matches_never_raises(kind, op):
    """matches() must return a plain bool for every representative value
    of every kind -- not just the values its own kind expects. Carved data
    from a damaged database really does put a string where a number
    belongs, an int where a datetime belongs, and a naive datetime next to
    aware ones; this is what actually exercises those combinations rather
    than trusting that they were imagined."""
    family = _KIND_FAMILY[kind]
    if op in _SATISFIABILITY_EXEMPT:
        cond, a, b = Condition(op), None, None
    else:
        cond, a, b = _build_condition(op, family)

    for value in _ALL_VALUES:
        try:
            result = cond.matches(value)
        except Exception as exc:
            pytest.fail(
                "%s/%s with operands (%r, %r) raised %r for value %r -- "
                "matches() must never raise; carved data from a damaged "
                "database really does contain values shaped like this."
                % (kind, op, a, b, exc, value))
        assert isinstance(result, bool), (
            "%s/%s with operands (%r, %r) returned %r (not a bool) for "
            "value %r" % (kind, op, a, b, result, value))
