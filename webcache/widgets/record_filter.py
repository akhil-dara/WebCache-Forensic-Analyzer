"""Filtering and sorting, in Python, over plain lists.

QSortFilterProxyModel is not used: it calls back into model.data() for
every row and column on each invalidation, and again inside its sort
comparator, across the Python/C++ boundary. Measured with PySide6 6.11.0
and Python 3.14 on 20 columns:

    sort 100k rows      proxy 20,624 ms     rows.sort()  30.3 ms   (680x)
    filter keystroke    proxy 10,320 ms     predicate   384 ms

No Qt import: the behaviour is testable without a QApplication, and the
model layer above stays thin.
"""
import datetime

from .time_format import format_dt
import math
import re

from ..spellings import might_have_other_spellings, other_spellings
from .column_spec import SEARCH_SEP, blank_label, display_text, searchable_text, split_multi

#: Above this many rows a keystroke costs more than a 60 Hz frame
#: (16.67 ms), so the filter box debounces instead of running live.
#: Measured with tests/test_perf.py (PySide6 6.11.0, Python 3.14.4,
#: offscreen): a filter keystroke costs about 0.2 ms per 1,000 rows,
#: linearly; 80k rows measured 15.5 ms and 100k rows 19.6 ms. 80,000 is
#: the last measured point within one frame.
LIVE_FILTER_MAX_ROWS = 80_000
#: How long the filter box waits after the last keystroke before applying,
#: once debouncing. A UX constant, not derived from the timing measurement
#: above: it only needs to outlast a human's inter-keystroke gap (~100 ms
#: for a fast typist) so the filter doesn't run mid-word, while staying
#: short enough to feel responsive once it does fire.
DEBOUNCE_MS = 180

#: Which operators each column kind offers. The popup reads this, and a
#: test checks that every offered operator works on that kind.
_TEXT_OPS = ("contains", "does not contain", "begins with", "ends with",
             "equals", "does not equal", "matches pattern",
             "does not match pattern", "is blank", "is not blank",
             "matches regex")
#: The text operators that keep a row only when the text does NOT match.
_NEGATED_TEXT_OPS = ("does not contain", "does not equal",
                     "does not match pattern")

#: Spreadsheet-style wildcards: * any run of characters, ? exactly one;
#: every other character literal; the pattern matches the whole value as
#: shown, ignoring case.
_PATTERN_OPS = ("matches pattern", "does not match pattern")


def wildcard_regex(pattern, case_sensitive=False):
    """The compiled full-match regex for an Excel-style wildcard pattern."""
    parts = []
    for ch in str(pattern):
        if ch == "*":
            parts.append(".*")
        elif ch == "?":
            parts.append(".")
        else:
            parts.append(re.escape(ch))
    flags = re.S | (0 if case_sensitive else re.I)
    return re.compile("".join(parts), flags)
_NUM_OPS = ("=", "!=", ">", ">=", "<", "<=", "between", "is blank")
_TIME_OPS = ("before", "after", "on", "between", "in the last N days",
             "is blank")

#: "=", "!=", ">", ">=", "<", "<=", and "between" are the operators shared
#: between _NUM_OPS and _TIME_OPS. Condition is never told which kind a
#: column is -- only the operator name and the operands -- so these seven
#: are resolved dynamically, per value, in Condition._match_ambiguous.
_AMBIGUOUS_OPS = ("=", "!=", ">", ">=", "<", "<=", "between")

#: Every operator this class can evaluate. Used only to reject an unknown
#: op string at construction (see Condition.__init__); matching is done by
#: the explicit branches below.
#: A flag column whose values are booleans filters by Yes/No, never by text
#: operators matching "True"/"False".
FLAG_OPS = ("is yes", "is no", "is blank", "is not blank")

#: what an operand box says before anything is typed.
OPERAND_PLACEHOLDERS = {
    "time": "YYYY-MM-DD or YYYY-MM-DD HH:MM:SS (UTC)",
    "time_local": "YYYY-MM-DD or YYYY-MM-DD HH:MM:SS (local)",
    "num": "a number", "count": "a number", "size": "bytes",
    "offset": "a number or 0x hex", "bar": "0 to 1",
}

_ALL_OPS = (frozenset(_TEXT_OPS) | frozenset(_NUM_OPS) | frozenset(_TIME_OPS)
            | frozenset(FLAG_OPS))

OPERATORS_BY_KIND = {
    "text": _TEXT_OPS, "url": _TEXT_OPS, "flag": _TEXT_OPS,
    "domain": _TEXT_OPS, "types": _TEXT_OPS, "path": _TEXT_OPS,
    "num": _NUM_OPS, "count": _NUM_OPS, "size": _NUM_OPS, "offset": _NUM_OPS,
    "carved": _TEXT_OPS, "only_carved": _TEXT_OPS,
    "time": _TIME_OPS, "time_local": _TIME_OPS,
    # A share is a number that happens to be drawn rather than printed
    # (see column_spec's "bar"), so it takes the numeric operators: ">=
    # 0.5" on a relative-volume column is a real, useful filter. Without
    # an entry here, filter_popup.py's OPERATORS_BY_KIND[col.kind] raises
    # KeyError the first time the heading is right-clicked -- which is
    # what tests/test_record_filter.py's generic coverage test exists to
    # stop happening again for the NEXT kind.
    "bar": _NUM_OPS,
}


#: The filter popup's two sort buttons, worded for what the column holds,
#: as Excel words them. The offline report's sortLabels mirrors this.
_SORT_LABELS = {
    "num": ("Sort smallest first", "Sort largest first"),
    "time": ("Sort oldest first", "Sort newest first"),
}
_SORT_FAMILY = {"num": "num", "count": "num", "size": "num", "offset": "num",
                "bar": "num", "time": "time", "time_local": "time"}


def sort_labels(column):
    """(ascending, descending) button text for COLUMN's filter popup."""
    return _SORT_LABELS.get(_SORT_FAMILY.get(column.kind),
                            ("Sort A to Z", "Sort Z to A"))


def operators_for(column, value_counts):
    """The operators the popup offers for this column. A flag column whose
    every non-blank value is a bool gets FLAG_OPS; everything else keeps
    OPERATORS_BY_KIND."""
    if column.kind == "flag":
        values = [v for v, _n in value_counts if v not in (None, "")]
        if values and all(isinstance(v, bool) for v in values):
            return FLAG_OPS
    return OPERATORS_BY_KIND[column.kind]


def _blank(value):
    return value is None or value == ""


#: An operand's text -> the length of the unit it names, for an end
#: bound: "2026-02-16" names a whole day, "2026-02-16 12:00" a minute.
_UNIT_SPANS = (
    (re.compile(r"\d{4}-\d{2}-\d{2}|\d{8}"), datetime.timedelta(days=1)),
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}"), datetime.timedelta(hours=1)),
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"),
     datetime.timedelta(minutes=1)),
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"),
     datetime.timedelta(seconds=1)),
)


def _unit_end(text):
    """How far past an operand's instant its unit runs, as an inclusive
    end ("2026-02-16" -> 23:59:59.999999 later), or None for an operand
    that names an exact instant (a fraction, an offset) or no date."""
    if isinstance(text, int) and not isinstance(text, bool):
        text = str(text)              # a compact YYYYMMDD from a spinbox
    s = str(text).strip() if isinstance(text, str) else ""
    for pattern, span in _UNIT_SPANS:
        if pattern.fullmatch(s):
            return span - datetime.timedelta(microseconds=1)
    return None


def _parse_dt(value):
    """Turn an operand into an aware UTC datetime, or raise ValueError.

    Accepts a datetime/date object, an int or float in the compact
    YYYYMMDD shape (a spinbox or a JSON round-trip yields a number), or a
    string: "YYYY-MM-DD", "YYYY-MM-DD HH:MM:SS", "YYYY-MM-DDTHH:MM:SS",
    the compact "YYYYMMDD" (handled explicitly, not left to
    fromisoformat's version-dependent support), or anything else
    datetime.fromisoformat understands.

    A naive value (no offset) is treated as UTC, never as local time:
    every stored timestamp here is UTC or in an explicitly labelled local
    column, so "2024-06-15" compares predictably with the aware UTC values
    in the rows.

    Callers decide what an unparseable value means: Condition.__init__
    sets .error (as for an invalid regex); a value read from a row goes
    through _safe_parse_dt below, which makes it "no match".
    """
    if isinstance(value, datetime.datetime):
        dt = value
    elif isinstance(value, datetime.date):
        dt = datetime.datetime(value.year, value.month, value.day)
    elif isinstance(value, bool):
        raise ValueError("not a recognisable date/time: %r" % value)
    elif isinstance(value, (int, float)):
        # Only the 8-digit YYYYMMDD shape is attempted. A fractional float
        # (20240601.5) has no YYYYMMDD reading and is rejected rather than
        # truncated.
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("not a recognisable date/time: %r" % value)
        return _parse_dt(str(int(value)))
    elif isinstance(value, str):
        s = value.strip()
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
                    "%Y%m%d"):
            try:
                dt = datetime.datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            try:
                dt = datetime.datetime.fromisoformat(s)
            except ValueError:
                raise ValueError("not a recognisable date/time: %r" % value)
    else:
        raise ValueError("not a recognisable date/time: %r" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _is_naive_operand(value):
    """True when an operand names a wall-clock time with no offset of its
    own -- a typed "2024-06-30" -- rather than an instant."""
    if isinstance(value, datetime.datetime):
        return value.tzinfo is None
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value.strip()).tzinfo is None
        except ValueError:
            return True
    return True


def _in_frame(operand, naive, value):
    """`operand` read on `value`'s clock. A Timeline
    period in Local mode is an aware value at the zone's offset; a date
    the examiner types against it is a date on THAT clock, so its digits
    are kept and the value's offset is put on them. A UTC or naive value,
    or an operand with its own offset, is left as it is."""
    tz = value.tzinfo
    if (not naive or tz is None
            or value.utcoffset() in (None, datetime.timedelta(0))):
        return operand
    return operand.replace(tzinfo=tz)


def _safe_parse_dt(value):
    """Same parsing as _parse_dt, but for a row's raw value during a live
    filter pass: blank or unparseable data is simply "does not match",
    never an exception that would take the whole view down with it."""
    if _blank(value):
        return None
    try:
        return _parse_dt(value)
    except (ValueError, TypeError):
        return None


class Condition:
    """One operator plus up to two operands.

    An invalid regex, an unparseable date operand (see _parse_dt) or an
    unknown operator is recorded in .error, and the condition then matches
    nothing; nothing raises, so a half-typed pattern in a live filter box
    is harmless. An unknown operator never falls through to matching every
    row.

    "=", "!=", ">", ">=", "<", "<=" and "between" are offered for numeric
    and time columns (OPERATORS_BY_KIND), and Condition is not told its
    column's kind. The value decides at match time: a datetime/date value
    uses the date reading of the operands, anything else the numeric
    reading. The operand's shape cannot decide it, because a compact date
    such as 20240101 is also a valid number.

    If neither reading of an operand parses, .error is set at
    construction. If one reading parses, the condition is valid for that
    kind of column, and a row holding the other kind simply does not
    match; .error is not set, since a carved column can mix kinds across
    rows (see _sort_key) and .error applies to the whole condition.

    "between" needs both operands read the same way. If `a` and `b` parse
    only under different readings (one only as a number, the other only as
    a date), .error is set at construction, naming both operands and how
    each was read.

    "in the last N days" is measured back from the newest non-blank value
    in the column across the unfiltered rows, not from today: an exhibit
    is examined after it was collected, and anchoring to today would
    return no rows. A RecordFilter keeps .anchor current on every
    recompute (RecordFilter.set_condition / _recompute), because set_rows
    can replace the data (a recovery scan merging carved records) while
    the condition stays attached. A standalone Condition can be given an
    anchor in the constructor, which is then fixed.

    Condition is deliberately not given a declared kind: a carved column
    can mix numbers and dates in one field (see _sort_key and
    OPERATORS_BY_KIND's "carved" kind), and the value at match time is the
    information that decides the reading. tests/test_condition_invariants.py
    holds the properties this design must keep.
    """

    __slots__ = ("op", "a", "b", "case_sensitive", "error", "_rx",
                 "anchor", "_a_dt", "_b_dt", "_a_num", "_b_num",
                 "_a_naive", "_b_naive", "_end_whole")

    def __init__(self, op, a=None, b=None, case_sensitive=False, anchor=None):
        self.op = op
        self.a = a
        self.b = b
        self.case_sensitive = case_sensitive
        self.error = None
        self._rx = None
        self.anchor = anchor
        self._a_dt = None
        self._b_dt = None
        self._a_num = None
        self._b_num = None
        self._a_naive = _is_naive_operand(a)
        self._b_naive = _is_naive_operand(b)
        #: True when the end bound was widened to the end of its unit.
        self._end_whole = False

        if op == "matches regex" and a:
            try:
                self._rx = re.compile(a, 0 if case_sensitive else re.I)
            except re.error as exc:
                self.error = str(exc)
        elif op in _PATTERN_OPS and a is not None:
            self._rx = wildcard_regex(a, case_sensitive)
        elif op in ("before", "after", "on"):
            if a is not None:
                try:
                    self._a_dt = _parse_dt(a)
                except (ValueError, TypeError):
                    self.error = "unparseable date/time: %r" % (a,)
        elif op in _AMBIGUOUS_OPS:
            # Both readings of each operand are tried; matches() chooses by
            # the value it compares. .error is set only for an operand that
            # fits neither reading.
            a_num_ok = a_dt_ok = False
            if a is not None:
                try:
                    self._a_num = float(a)
                    a_num_ok = True
                except (TypeError, ValueError):
                    pass
                try:
                    self._a_dt = _parse_dt(a)
                    a_dt_ok = True
                except (ValueError, TypeError):
                    pass
                if not a_num_ok and not a_dt_ok:
                    self.error = "not a number or a date/time: %r" % (a,)
            if op == "between" and b is not None:
                b_num_ok = b_dt_ok = False
                try:
                    self._b_num = float(b)
                    b_num_ok = True
                except (TypeError, ValueError):
                    pass
                try:
                    self._b_dt = _parse_dt(b)
                    b_dt_ok = True
                except (ValueError, TypeError):
                    pass
                if not b_num_ok and not b_dt_ok:
                    self.error = "not a number or a date/time: %r" % (b,)
                elif self.error is None and a is not None:
                    # Each operand parses, but "between" needs them to
                    # parse the same way: a number is never between a
                    # number and a date.
                    if not ((a_num_ok and b_num_ok) or (a_dt_ok and b_dt_ok)):
                        a_kind = "a number" if a_num_ok else "a date/time"
                        b_kind = "a number" if b_num_ok else "a date/time"
                        self.error = (
                            "between needs both operands read the same "
                            "way: %r reads as %s, %r reads as %s"
                            % (a, a_kind, b, b_kind))

            # "between 100 and 10" is read as the range it means. The
            # operands are swapped only within one reading (a mismatched
            # reading is an error, handled above). Both readings are checked
            # independently, because a compact operand like "20240101"
            # parses as both a number and a date, and the numeric and
            # calendar orders agree for it. self.a/self.b are swapped too, so
            # describe() reports the range as applied (low -> high).
            if self.error is None:
                swap_num = (self._a_num is not None and self._b_num is not None
                            and self._a_num > self._b_num)
                swap_dt = (self._a_dt is not None and self._b_dt is not None
                           and self._a_dt > self._b_dt)
                if swap_num:
                    self._a_num, self._b_num = self._b_num, self._a_num
                if swap_dt:
                    self._a_dt, self._b_dt = self._b_dt, self._a_dt
                    self._a_naive, self._b_naive = self._b_naive, self._a_naive
                if swap_num or swap_dt:
                    self.a, self.b = self.b, self.a
            # An end bound covers the whole unit it names: "and
            # 2026-02-16" runs to the end of that day, not its first
            # instant.
            end_bound = (self.b if op == "between"
                         else self.a if op == "<=" else None)
            span = _unit_end(end_bound) if self.error is None else None
            if span is not None:
                if op == "between" and self._b_dt is not None:
                    self._b_dt = self._b_dt + span
                    self._end_whole = True
                elif op == "<=" and self._a_dt is not None:
                    self._a_dt = self._a_dt + span
                    self._end_whole = True
        elif op == "in the last N days":
            if a is not None:
                try:
                    n = float(a)
                except (TypeError, ValueError):
                    n = None
                # n < 0 is rejected ("the last -3 days" means nothing), and
                # n > 36500 (100 years) is capped so the window stays within
                # what any evidence file spans. nan, inf and values such as
                # "1e400" (which float() reads as inf) are rejected with
                # math.isfinite, since timedelta(days=nan) would raise in
                # matches().
                if n is None or not math.isfinite(n) or n < 0 or n > 36500:
                    self.error = "N must be a number of days, got %r" % (a,)

        if self.error is None and op not in _ALL_OPS:
            # An operator string with no matching branch. Rejected here so
            # it can never fall through to matching every row.
            self.error = "unknown operator: %r" % (op,)

    def _text(self, value):
        s = "" if value is None else str(value)
        return s if self.case_sensitive else s.lower()

    def _operand(self):
        s = "" if self.a is None else str(self.a)
        return s if self.case_sensitive else s.lower()

    def _match_ambiguous(self, op, value):
        """=, !=, >, >=, <, <=, and between: which comparison this performs
        depends on the type of `value`, not on how the operand happens to
        parse. See the class docstring for why, and for why a reading that
        failed to parse for THIS operand returns False for just this one
        value rather than setting .error."""
        if isinstance(value, (datetime.datetime, datetime.date)):
            dt = _safe_parse_dt(value)
            if dt is None or self._a_dt is None:
                return False
            if op == "between":
                if self._b_dt is None:
                    return False
                return (_in_frame(self._a_dt, self._a_naive, dt) <= dt
                        <= _in_frame(self._b_dt, self._b_naive, dt))
            a = _in_frame(self._a_dt, self._a_naive, dt)
            return {"=": dt == a, "!=": dt != a, ">": dt > a, ">=": dt >= a,
                    "<": dt < a, "<=": dt <= a}[op]

        if value is None:
            return False
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        if self._a_num is None:
            return False
        if op == "between":
            if self._b_num is None:
                return False
            return self._a_num <= v <= self._b_num
        a = self._a_num
        return {"=": v == a, "!=": v != a, ">": v > a, ">=": v >= a,
                "<": v < a, "<=": v <= a}[op]

    def matches(self, value):
        op = self.op
        if op == "is yes":
            return value is True
        if op == "is no":
            return value is False
        if op == "is blank":
            return _blank(value)
        if op == "is not blank":
            return not _blank(value)
        if self.error:
            return False

        if op in ("before", "after", "on"):
            if self._a_dt is None:
                return False
            dt = _safe_parse_dt(value)
            if dt is None:
                return False
            a = _in_frame(self._a_dt, self._a_naive, dt)
            if op == "before":
                return dt < a
            if op == "after":
                return dt > a
            if a is not self._a_dt:
                # "on" a date typed against a value on a local clock: that
                # clock's calendar date on both sides -- the day the
                # period is labelled with.
                return dt.date() == a.date()
            # "on": same calendar date, independent of time-of-day. Both
            # sides are normalised to UTC before comparing .date() so "the
            # 15th" means the same day regardless of which timezone either
            # value happened to arrive labelled in.
            return (dt.astimezone(datetime.timezone.utc).date()
                    == self._a_dt.astimezone(datetime.timezone.utc).date())

        if op == "in the last N days":
            if self.anchor is None or self.a is None:
                return False
            dt = _safe_parse_dt(value)
            if dt is None:
                return False
            # __init__ bounds N, but an anchor near datetime.min or
            # datetime.max (possible from a carved record) can still put
            # `anchor - timedelta(days=n)` outside datetime's range. That is
            # a property of the data, caught here where the subtraction
            # happens, and treated as "no match" rather than raised.
            try:
                window_start = self.anchor - datetime.timedelta(days=float(self.a))
            except OverflowError:
                return False
            return window_start <= dt <= self.anchor

        if op in _AMBIGUOUS_OPS:
            return self._match_ambiguous(op, value)

        s, a = self._text(value), self._operand()
        if op == "contains":
            return a in s
        if op == "does not contain":
            return a not in s
        if op == "begins with":
            return s.startswith(a)
        if op == "ends with":
            return s.endswith(a)
        if op == "equals":
            return s == a
        if op == "does not equal":
            return s != a
        if op == "matches regex":
            return bool(self._rx and self._rx.search("" if value is None else str(value)))
        if op in _PATTERN_OPS:
            hit = bool(self._rx and self._rx.fullmatch(
                "" if value is None else str(value)))
            return hit if op == "matches pattern" else not hit
        # Reachable only for an unknown operator, which __init__ already
        # turns into .error; False, so the fallback matches nothing.
        return False

    #: How a boolean operand reads on a flag column.
    _FLAG_WORDS = {"true": "Yes", "yes": "Yes", "1": "Yes",
                   "false": "No", "no": "No", "0": "No"}

    def describe(self, column=None):
        """The condition in the grid's own words. On a flag column an
        equality reads "Is Yes"/"Is No" -- never '= "False"'."""
        if (column is not None and getattr(column, "kind", None) == "flag"
                and self.op in ("equals", "does not equal")
                and str(self.a).strip().lower() in self._FLAG_WORDS):
            word = self._FLAG_WORDS[str(self.a).strip().lower()]
            return ("Is %s" if self.op == "equals" else "Is not %s") % word
        if self.op in ("is yes", "is no"):
            return "Is %s" % ("Yes" if self.op == "is yes" else "No")
        if self.op in ("is blank", "is not blank"):
            return self.op
        if self.op == "between":
            return "between %s and %s%s" % (
                self.a, "the end of " if self._end_whole else "", self.b)
        if self.op == "<=" and self._end_whole:
            return '<= the end of "%s"' % (self.a,)
        if self.op == "in the last N days":
            return "in the last %s days" % (self.a,)
        return '%s "%s"' % (self.op, self.a)


#: How two conditions on one column combine (Excel's Custom AutoFilter).
JOINS = ("and", "or")


class JoinedCondition:
    """Two Conditions on one column, joined by "and" or "or".

    Each half reads the cell as it would alone -- a text operator the
    shown text, a number or date operator the stored value -- so the join
    is matched by RecordFilter._condition_matches, not by .matches(),
    which only serves a caller that already has the one value both halves
    read. .op is None: no single operator describes the pair."""

    op = None

    def __init__(self, first, join, second):
        if join not in JOINS:
            raise ValueError("a join is 'and' or 'or', not %r" % (join,))
        self.first = first
        self.join = join
        self.second = second
        self.error = first.error or second.error
        self.case_sensitive = first.case_sensitive

    @property
    def parts(self):
        return (self.first, self.second)

    def matches(self, value):
        return self.matches_each(lambda _half: value)

    def matches_each(self, value_for):
        """VALUE_FOR(condition) is the value that half reads."""
        return self.matches_halves(lambda half: half.matches(value_for(half)))

    def matches_halves(self, half_matches):
        """HALF_MATCHES(condition) says whether one half keeps the row;
        the two are joined with And / Or, short-circuited."""
        if self.error:
            return False
        first = half_matches(self.first)
        if self.join == "and" and not first:
            return False
        if self.join == "or" and first:
            return True
        return half_matches(self.second)

    def describe(self, column=None):
        return "%s %s %s" % (self.first.describe(column), self.join,
                             self.second.describe(column))


def _sort_key(value):
    """A key that orders mixed types without raising, blanks always last.

    Python 3 refuses to compare str with int, and a carved column can hold
    both. The rank puts real values first and blanks last, and keeps like
    with like. value_counts() uses the whole key; RecordFilter._apply_sort
    uses the rank (element 0) to group rows before sorting each group (see
    its docstring).
    """
    if value is None or value == "":
        return (3, 0.0, "")
    if isinstance(value, bool):
        return (1, float(value), "")
    if isinstance(value, (int, float)):
        return (1, float(value), "")
    if isinstance(value, datetime.datetime):
        # An ordinal, not .timestamp(): a NAIVE pre-1970 datetime makes
        # timestamp() go through the platform mktime and raise OSError on
        # Windows (confirmed: value.timestamp() on datetime(1601, 1, 1)
        # raises OSError, not just on old Windows C runtimes -- this is
        # reachable from two real loaders, e.g. a carved FILETIME record
        # or an evidence file with a bad clock).
        #
        # This app's convention (see _parse_dt's docstring and
        # ese_parser.filetime_to_dt): a NAIVE datetime/date value in a row
        # means UTC, never local time -- there is no ambiguous "system
        # local time" reading for it to carry. So a naive value is already
        # in the right frame and its wall-clock ordinal IS its UTC
        # ordinal. An AWARE value must first be converted to UTC
        # (.astimezone -- safe, no mktime/OSError) so it sorts by INSTANT
        # rather than by local wall clock: two aware values an hour apart
        # under different UTC offsets could otherwise swap order, and an
        # aware value would sort in a different frame than the naive ones
        # that mean the same instant.
        dt = value.astimezone(datetime.timezone.utc) if value.tzinfo is not None else value
        return (2, dt.toordinal() * 86400.0 + dt.hour * 3600
                + dt.minute * 60 + dt.second + dt.microsecond / 1e6, "")
    if isinstance(value, datetime.date):
        return (2, value.toordinal() * 86400.0, "")
    try:
        # Anything else orderable against its own kind.
        return (2, value.timestamp(), "")
    except AttributeError:
        pass
    return (2, 0.0, natural_key(str(value)))


_DIGITS = re.compile(r"\d+")


def natural_key(text):
    """A string that sorts naturally under plain comparison: every run of
    digits is written as its length (4 digits) then its digits without
    leading zeros, so "file2" orders before "file10". The lower-cased text
    follows a NUL as the tie-break, so "02" and "2" have a fixed order. The
    offline report's naturalKey implements the same rule."""
    lower = text.lower()

    def run(m):
        digits = m.group().lstrip("0") or "0"
        return "0%04d%s" % (len(digits), digits)
    return _DIGITS.sub(run, lower) + "\x00" + lower


#: Joins one row's cells in the haystack -- column_spec's own separator,
#: which cannot occur in typed text, so a search never matches across two
#: cells.
_HAY_SEP = SEARCH_SEP


def _str_text(v):
    """searchable_text for a plain str cell, without the call: the value,
    plus its other spellings (webcache/spellings.py) when it has any."""
    if not might_have_other_spellings(v):
        return v
    others = other_spellings(v)
    return _HAY_SEP.join([v] + others) if others else v


def _column_texts(col, rows):
    """One column's haystack cells for `rows`, built in one pass.

    Every cell equals column_spec.searchable_text(value, col), the rule the
    value picker's search uses too. The inline branches only short-cut
    cases searchable_text handles the same way: a str is its own display
    text in every kind (display_text rewrites only None/"", bools,
    datetimes, ints and floats); None is ""; a bool is "Yes"/"No"; an exact
    int on a numeric, non-offset column is "{:,}" plus its digits; an exact
    datetime uses display_text's fixed spelling. Anything else goes
    through searchable_text."""
    key = col.key
    vals = [r.get(key) for r in rows]
    str_cls, bool_cls, int_cls = str, bool, int
    dt_cls = datetime.datetime
    sep = _HAY_SEP
    if (bool(getattr(col, "numeric", False))
            and getattr(col, "kind", None) != "offset"):
        # Counts repeat heavily (a visit count, a zero offset), so each
        # distinct int is spelled once.
        spelled = {v: format(v, ",") + sep + repr(v)
                   for v in {v for v in vals if v.__class__ is int_cls}}
        return [_str_text(v) if v.__class__ is str_cls
                else spelled[v] if v.__class__ is int_cls
                else "" if v is None
                else ("Yes" if v else "No") if v.__class__ is bool_cls
                else searchable_text(v, col)
                for v in vals]
    return [_str_text(v) if v.__class__ is str_cls
            else "" if v is None
            else format_dt(v)
            if v.__class__ is dt_cls
            else ("Yes" if v else "No") if v.__class__ is bool_cls
            else searchable_text(v, col)
            for v in vals]


class RecordFilter:
    """Holds the rows, the active filters, and the visible order.

    Text search uses a haystack: one lowercase string per row, joined with
    a separator that cannot occur in the data, so a keystroke is a
    substring test rather than a walk over every column. It is built once
    per row set, lazily (see _ensure_haystack), never per keystroke.
    """

    def __init__(self, rows, columns):
        self.columns = list(columns)
        #: Keys whose cells are MULTI_SEPARATOR-joined lists.
        self._multi_keys = {c.key for c in self.columns
                            if getattr(c, "multi", False)}
        #: key -> the row key holding that column's PRE-SPLIT value list,
        #: for the columns that declared one (Column.multi_source). Absent
        #: for any multi key that didn't -- see _multi_values' docstring.
        self._multi_source = {c.key: c.multi_source for c in self.columns
                              if getattr(c, "multi", False)
                              and getattr(c, "multi_source", None)}
        #: A display label for a key no column declares -- a quick-filter
        #: chip's own name. RecordsView fills it.
        self.extra_labels = {}
        #: key -> (the filter a quick-filter chip put in force, the
        #: chip's own sentence). chip_text says the sentence while THAT
        #: filter is the one in force -- never a chip's implementation
        #: RecordsView fills it.
        self.sentences = {}
        self._text = ""
        self._values = {}
        self._conditions = {}
        #: key -> fn(visible rows) -> the rows kept: a filter that needs to
        #: see which OTHER rows are shown (an MSHist row is hidden only
        #: while its History twin is on screen). Applied last.
        self._posts = {}
        #: key -> how many rows that post filter removed on the last pass.
        self.post_removed = {}
        self._sort_key = None
        self._sort_desc = False
        #: Lazy per-column sort-key cache: {column_key: {id(row): sort_key}}.
        #: See _keys_for and set_rows for the invalidation contract.
        self._sort_key_cache = {}
        #: (rows, key, desc, order): every row's index in sorted order, built
        #: once per (row set, sort) so a FILTER only walks it -- filtering a
        #: sorted list keeps it sorted. See _master_order.
        self._master = None
        self.set_rows(rows)

    # --- data ------------------------------------------------------------

    def set_rows(self, rows):
        """Replace the row set wholesale (a recovery scan merging carved
        records in, e.g.) and recompute.

        Rolls back to the previous rows/haystack/sort-key-cache and
        re-raises if _recompute fails partway -- same shape as
        set_condition/set_values, and for the same reason: this is the
        riskiest of the three, since it hands every already-attached
        Condition brand-new data it has never seen matches() run against.
        At the very first call (from __init__), there is no previous row
        set to roll back to -- self._conditions is still empty at that
        point, so nothing can raise, and the attributes below simply don't
        exist yet.
        """
        previous_rows = getattr(self, "rows", None)
        previous_haystack = getattr(self, "_haystack", None)
        previous_cache = self._sort_key_cache
        self.rows = list(rows)
        # Invalidated, not rebuilt: the haystack is built the first time
        # something needs it (the first non-empty set_text, or emptied_by()
        # while a search is active), so a view that is never searched never
        # pays for it. None tells _ensure_haystack it has not been built for
        # these rows.
        self._haystack = None
        #: The part of the haystack the idle prebuild (build_haystack_chunk)
        #: has built so far for THESE rows; invalidated with the haystack.
        previous_prefix = getattr(self, "_hay_prefix", None)
        self._hay_prefix = []
        # The whole cache is replaced: set_rows replaces the row objects
        # (a recovery merge, for instance), so every cached column is stale.
        # Kept beside the haystack reset, so both are invalidated in one
        # place.
        self._sort_key_cache = {}
        try:
            self._recompute()
        except Exception:
            if previous_rows is not None:
                self.rows = previous_rows
                self._haystack = previous_haystack
                self._hay_prefix = previous_prefix or []
                self._sort_key_cache = previous_cache
                self._recompute()
            raise

    def _ensure_haystack(self):
        """Build the haystack the first time something needs it, and not
        again for the same row set (set_rows sets self._haystack to None).

        Building it in set_rows would cost about a second on the GUI
        thread at every view open for 100k rows; built lazily, an examiner
        who never searches pays nothing, and one who does pays once.

        Safe to call any number of times: only the first call after a
        set_rows does the work.
        """
        if self._haystack is None:
            # Whatever the idle prebuild (build_haystack_chunk) already
            # built is kept; only the remainder is built here.
            prefix = self._hay_prefix
            if len(prefix) < len(self.rows):
                prefix.extend(self._haystack_rows(len(prefix), len(self.rows)))
            self._haystack = prefix
            self._hay_prefix = []
        return self._haystack

    #: Rows per idle prebuild step: about 3-5 ms per 1,000 rows of 12
    #: columns, so a step stays well under 10 ms.
    HAYSTACK_CHUNK = 1000

    def build_haystack_chunk(self, start, n=HAYSTACK_CHUNK):
        """Build haystack rows [start, start + n) ahead of need.

        A lazy haystack would put its whole cost on the first keystroke.
        RecordTableModel drives this in zero-delay timer steps after
        construction and after set_rows, so the first keystroke normally
        finds it built; _ensure_haystack finishes any remainder.

        Qt-free: the caller schedules it. `start` must be where the
        previous step ended; a chain begun for an earlier row set no longer
        matches and stops. Returns the next start, or None when there is
        nothing left to do (complete, already built, or stale)."""
        if self._haystack is not None:
            return None
        prefix = self._hay_prefix
        if start != len(prefix):
            return None
        end = min(len(self.rows), start + max(1, int(n)))
        if start < end:
            prefix.extend(self._haystack_rows(start, end))
        if end >= len(self.rows):
            self._haystack = prefix
            self._hay_prefix = []
            return None
        return end

    def _haystack_rows(self, start, end):
        """One lowercase search string per row in [start, end), from the
        text the grid paints (column_spec.display_text), so a search
        matches what the examiner can see.

        Built column by column (see _column_texts), so each column's kind
        is decided once rather than per cell.

        Numeric columns (kind "num"/"count"/"size", not "offset", which is
        shown as hex) also carry the plain digits, so "12345" finds
        "12,345". Nothing else gets a hidden spelling: a flag column shows
        "Yes", so "true" does not match it.
        """
        rows = self.rows[start:end]
        if not rows:
            return []
        per_column = [_column_texts(col, rows) for col in self.columns]
        sep = _HAY_SEP
        return [sep.join(parts).lower() for parts in zip(*per_column)]

    def _sort_source(self, key):
        """The row key this column's ORDER is read from."""
        for col in self.columns:
            if col.key == key:
                return getattr(col, "sort_by", None) or key
        return key

    def _keys_for(self, key):
        """The {id(row): _sort_key(value)} cache for one column, built once.

        Keyed by id(row): self._visible is a subset of self.rows (the same
        dict objects), so id() finds a row's key in any subset or order. It
        is built from self.rows, so every row _apply_sort can return is
        covered.

        This relies on one convention: a row in self.rows is not modified
        in place while it remains there. Row values change only by
        replacing the row set through set_rows, which replaces
        self._sort_key_cache. A row modified in place (followed by
        RecordTableModel.refresh()) would keep its old cached key; the
        haystack depends on the same convention.
        """
        cache = self._sort_key_cache.get(key)
        if cache is None:
            cache = {id(r): _sort_key(r.get(key)) for r in self.rows}
            self._sort_key_cache[key] = cache
        return cache

    @property
    def total_count(self):
        return len(self.rows)

    @property
    def visible_count(self):
        return len(self._visible)

    def visible(self):
        return self._visible

    # --- filters ---------------------------------------------------------

    def set_text(self, text):
        self._text = (text or "").strip().lower()
        self._recompute()

    def set_values(self, key, allowed):
        """allowed is a set of permitted values, or None to clear the filter.

        An empty set means none selected and shows nothing; it never means
        "no filter".

        Rolls back to the previous values filter and re-raises if
        _recompute fails (see set_condition).
        """
        previous = self._values.get(key)
        had_previous = key in self._values
        if allowed is None:
            self._values.pop(key, None)
        else:
            self._values[key] = set(allowed)
        try:
            self._recompute()
        except Exception:
            if had_previous:
                self._values[key] = previous
            else:
                self._values.pop(key, None)
            self._recompute()
            raise

    def set_condition(self, key, condition):
        """Attach (or clear) a Condition for one column.

        An "in the last N days" condition's .anchor is resolved on every
        _recompute, not here (see _recompute and Condition).

        Commits only if _recompute succeeds. A Condition can raise while
        matching even if it validated (a subclass override, say), and
        _recompute assigns self._visible only at its end, so a failure
        would leave the new condition recorded beside the old visible rows.
        On failure the previous condition is restored, the recompute is
        repeated (it succeeded before with that state), and the exception
        is re-raised for the caller to handle.
        """
        previous = self._conditions.get(key)
        had_previous = key in self._conditions
        if condition is None:
            self._conditions.pop(key, None)
        else:
            self._conditions[key] = condition
        try:
            self._recompute()
        except Exception:
            # Roll back, so the chip can never describe a filter the grid
            # is not showing.
            if had_previous:
                self._conditions[key] = previous
            else:
                self._conditions.pop(key, None)
            self._recompute()
            raise

    def set_column_filter(self, key, values, condition):
        """Set one column's values filter and its condition as one step:
        one _recompute, and on failure both are restored before re-raising,
        so a filter is never half applied.

        `values`: a set of permitted values, or None for no values filter
        (see set_values). `condition`: a Condition, or None (see
        set_condition)."""
        had_values = key in self._values
        previous_values = self._values.get(key)
        had_condition = key in self._conditions
        previous_condition = self._conditions.get(key)
        if values is None:
            self._values.pop(key, None)
        else:
            self._values[key] = set(values)
        if condition is None:
            self._conditions.pop(key, None)
        else:
            self._conditions[key] = condition
        try:
            self._recompute()
        except Exception:
            if had_values:
                self._values[key] = previous_values
            else:
                self._values.pop(key, None)
            if had_condition:
                self._conditions[key] = previous_condition
            else:
                self._conditions.pop(key, None)
            self._recompute()
            raise

    def allowed_values(self, key):
        """The set of values currently permitted for one column, or None if
        no values filter is active on it. Used by the filter popup on
        reopen to show what is ticked."""
        return self._values.get(key)

    def condition_for(self, key):
        """The Condition attached to one column, or None. Used by the filter
        popup on reopen to seed its fields from what is applied."""
        return self._conditions.get(key)

    def clear_all(self):
        self._text = ""
        self._values.clear()
        self._conditions.clear()
        self._posts.clear()
        self._recompute()

    def set_post(self, key, fn):
        """Attach (or clear, with None) a post filter -- see _posts."""
        if fn is None:
            self._posts.pop(key, None)
        else:
            self._posts[key] = fn
        self._recompute()

    def post_for(self, key):
        """Read-only: the post filter held under `key`, or None."""
        return self._posts.get(key)

    def has_filters(self):
        return bool(self._text or self._values or self._conditions
                    or self._posts)

    # --- sorting ---------------------------------------------------------

    def sort(self, key, descending=False):
        """A stable sort of the order shown just before it: ties keep the
        previous display order (the view's default sort first, then loader
        order), and keep it across later filter changes.

        It sorts the previous master order (every row, not only those on
        screen) and stores the result as the new master, so ties are stable
        however filters change. Repeated stable sorts are what a multi-key
        sort (records_table._apply_sort) relies on."""
        previous = self._master_order()
        rows = self.rows
        self._sort_key = key
        self._sort_desc = descending
        # _apply_sort is the one place the partition (numbers, other
        # values, blanks last in both directions) and the key cache live;
        # it sorts self._visible, so it is handed every row in the
        # previous order and the result becomes the master.
        self._visible = (list(rows) if previous is None
                         else [rows[i] for i in previous])
        self._apply_sort()
        index = {id(r): i for i, r in enumerate(rows)}
        self._master = (rows, key, descending,
                        [index[id(r)] for r in self._visible])
        if self.has_filters():
            self._recompute()
        else:
            # Nothing is filtered out: every row, just sorted, IS the view.
            self.post_removed = {}

    def _master_order(self):
        """Indices into self.rows in the current sort order, or None when
        no sort is in force. Built once per (row set, sort key, direction);
        _recompute filters THIS, so a keystroke never re-sorts."""
        if self._sort_key is None:
            return None
        m = self._master
        if (m is not None and m[0] is self.rows and m[1] == self._sort_key
                and m[2] == self._sort_desc):
            return m[3]
        saved = self._visible
        self._visible = list(self.rows)
        try:
            self._apply_sort()
            index = {id(r): i for i, r in enumerate(self.rows)}
            order = [index[id(r)] for r in self._visible]
        finally:
            self._visible = saved
        self._master = (self.rows, self._sort_key, self._sort_desc, order)
        return order

    def _apply_sort(self):
        if self._sort_key is None:
            return
        k = self._sort_key
        desc = self._sort_desc
        # A column may order by a SIBLING key while displaying its own --
        # see Column.sort_by. Resolved here, at the one place the sort
        # reads a value, so the cache, the blank-partitioning and the
        # group ordering below all operate on the same key.
        keys = self._keys_for(self._sort_source(k))

        # _sort_key ranks blanks as 3, the same test _blank() makes, so
        # partitioning by keys[id(r)][0] needs no separate blank check. The
        # key is computed once per row and cached, so re-sorting a column
        # (toggling direction, re-clicking the header) pays only for the
        # sort.
        numeric = [r for r in self._visible if keys[id(r)][0] == 1]
        other = [r for r in self._visible if keys[id(r)][0] == 2]
        blank = [r for r in self._visible if keys[id(r)][0] == 3]

        numeric.sort(key=lambda r: keys[id(r)], reverse=desc)
        other.sort(key=lambda r: keys[id(r)], reverse=desc)

        # The group order (numbers, then text and dates) stays fixed in
        # both directions; only the order within each group reverses. A
        # single reverse=True would also flip the groups, so numbers in a
        # carved mixed-type column would move to the other end of the list
        # depending on direction. Text and datetimes within the "other"
        # group are reversed together.
        self._visible = numeric + other + blank

    @staticmethod
    def _condition_value(row, key, cond, cols):
        """The value one Condition is matched against for one row.

        Text operators (_TEXT_OPS) read what the grid shows
        (column_spec.display_text), so "equals Yes" on a flag column matches
        the spelling on screen, not str(True). Numeric and time operators
        compare the raw value, which their readings parse themselves
        (Condition._match_ambiguous / _parse_dt).

        Used by both _recompute (the filter pass) and _count_matching
        (emptied_by()'s recount), so the two always agree about whether a
        condition matches.
        """
        value = row.get(key)
        if cond.op in _TEXT_OPS:
            return display_text(value, cols.get(key))
        return value

    @classmethod
    def _condition_matches(cls, row, key, cond, cols):
        """Whether COND keeps ROW: each half of a JoinedCondition reads
        its own value through _condition_value, as it would alone."""
        if isinstance(cond, JoinedCondition):
            return cond.matches_halves(
                lambda half: cls._half_matches(row, key, half, cols))
        return cls._half_matches(row, key, cond, cols)

    @classmethod
    def _half_matches(cls, row, key, cond, cols):
        """One Condition against one row. A text operator also reads the
        value's other spellings (webcache/spellings.py): a positive one
        keeps the row if ANY spelling matches, a negated one only if ALL
        do -- so "does not contain tax docs" really excludes "Tax%20docs"."""
        value = cls._condition_value(row, key, cond, cols)
        if cond.op in _TEXT_OPS:
            others = other_spellings(value)
            if others:
                spellings = [value] + others
                if cond.op in _NEGATED_TEXT_OPS:
                    return all(cond.matches(s) for s in spellings)
                return any(cond.matches(s) for s in spellings)
        return cond.matches(value)

    def label_for(self, key):
        for column in self.columns:
            if column.key == key:
                return column.label
        return self.extra_labels.get(key, key)

    def _column(self, key):
        return next((c for c in self.columns if c.key == key), None)

    def _multi_values(self, row, key):
        """The individual values row[key] holds, for a multi column.

        Prefers the loader's pre-split list (row[column.multi_source]) when
        the column declares one, returned as is. Joined elements from
        outside this tool's control (a device-reported provider string) may
        themselves contain ", ", so they are never re-split. Only a
        comma-free vocabulary this tool generates (container-type names,
        ESE schema column names) falls back to split_multi() on the joined
        text (see Column.multi_source)."""
        source_key = self._multi_source.get(key)
        if source_key is not None:
            raw = row.get(source_key)
            if raw is not None:
                return list(raw)
        return split_multi(row.get(key))

    def _passes_values(self, row, value_items):
        """value_items: [(key, allowed, is_multi)]. A multi-value cell
        passes when ANY of its values is allowed."""
        for key, allowed, multi in value_items:
            if multi:
                if not any(v in allowed for v in self._multi_values(row, key)):
                    return False
            elif row.get(key) not in allowed:
                return False
        return True

    # --- the pass itself -------------------------------------------------

    def _recompute(self):
        # "in the last N days" anchors are resolved here on every
        # recompute, never once at attachment: set_rows can replace the
        # data under an attached condition (a recovery scan merging carved
        # records into a filtered view), and carved timestamps can be newer
        # or older than the live ones, so the window always describes the
        # rows now held.
        for key, cond in self._conditions.items():
            for half in getattr(cond, "parts", (cond,)):
                if half.op == "in the last N days":
                    half.anchor = self.newest_value(key)

        text = self._text
        hay = self._ensure_haystack() if text else self._haystack
        # Resolved ONCE, outside the row loop -- not per row, and not per
        # condition per row. A dict {c.key: c for c in self.columns} rather
        # than the per-condition column, so a filter over 100,000 rows does
        # not pay for the lookup on every value that reaches display_text.
        cols = {c.key: c for c in self.columns}
        value_items = [(k, a, k in self._multi_keys)
                       for k, a in self._values.items()]
        out = []
        rows = self.rows
        order = self._master_order()
        for i in (range(len(rows)) if order is None else order):
            row = rows[i]
            if text and text not in hay[i]:
                continue
            if value_items and not self._passes_values(row, value_items):
                continue
            ok = True
            for key, cond in self._conditions.items():
                if not self._condition_matches(row, key, cond, cols):
                    ok = False
                    break
            if ok:
                out.append(row)
        self.post_removed = {}
        for key, fn in self._posts.items():
            kept = fn(out)
            self.post_removed[key] = len(out) - len(kept)
            out = kept
        self._visible = out

    # --- reporting -------------------------------------------------------

    def emptied_by(self):
        """Which filter emptied the table, so the view can name it and offer
        a way back.

        A column can carry both a values filter and a condition (they
        combine), so each is tested as a separate candidate.

        Return values:
          - None                    nothing emptied the table (it is not
                                    empty, or no filter is active)
          - "the search box"        the free-text search emptied it
          - "<key>"                 one of {values filter, condition} is
                                    active on column <key>, and it is the
                                    one responsible
          - "<key> (values)"        column <key> carries both; the values
                                    filter is responsible
          - "<key> (condition)"     column <key> carries both; the
                                    condition is responsible
          - "<key> (values + condition)"  column <key> carries both, and
                                    only dropping both restores rows (tried
                                    after every single-filter candidate)
        A caller can test the suffixes " (values)", " (condition)" and
        " (values + condition)"; a value with none of them, other than the
        two special cases above, is a column key.
        """
        if self._visible or not self.has_filters():
            return None
        # An explicitly emptied value list is the obvious culprit; name it
        # without doing any work.
        for key, allowed in self._values.items():
            if not allowed:
                return key
        # Drop one filter at a time, where one filter is one values panel
        # or one condition, walked in separate loops, so a column carrying
        # both is never removed from both at once here.
        for key in list(self._values):
            values = {k: v for k, v in self._values.items() if k != key}
            if self._count_matching(self._text, values, self._conditions):
                return ("%s (values)" % key) if key in self._conditions else key
        for key in list(self._conditions):
            conds = {k: v for k, v in self._conditions.items() if k != key}
            if self._count_matching(self._text, self._values, conds):
                return ("%s (condition)" % key) if key in self._values else key
        # A column carrying both a values filter and a condition (what the
        # filter popup applies) can empty the table in a way neither single
        # drop explains: each alone still leaves zero rows. Dropping both
        # together is tried last, only for keys carrying both, so this case
        # is explained too.
        for key in list(self._values):
            if key not in self._conditions:
                continue
            values = {k: v for k, v in self._values.items() if k != key}
            conds = {k: v for k, v in self._conditions.items() if k != key}
            if self._count_matching(self._text, values, conds):
                return "%s (values + condition)" % key
        if self._text and self._count_matching("", self._values, self._conditions):
            return "the search box"
        return None

    def _count_matching(self, text, values, conditions):
        """How many rows survive this combination. Reads nothing from self
        except the rows, the haystack and the columns, so it is safe to
        call mid-query.

        Resolves each condition's value through the SAME
        _condition_value helper _recompute uses -- see that method's
        docstring for why this must never be done independently again."""
        hay = self._ensure_haystack() if text else None
        cols = {c.key: c for c in self.columns}
        value_items = [(k, a, k in self._multi_keys)
                       for k, a in values.items()]
        n = 0
        for i, row in enumerate(self.rows):
            if text and text not in hay[i]:
                continue
            if value_items and not self._passes_values(row, value_items):
                continue
            if any(not self._condition_matches(row, k, c, cols)
                   for k, c in conditions.items()):
                continue
            n += 1
        return n

    def newest_value(self, key):
        """The newest parseable timestamp this column holds across every
        row, ignoring current filters: the anchor for "in the last N days"
        (see _recompute and Condition). None if the column has no parseable
        timestamp. Public, so the filter popup can preview the anchor
        before Apply."""
        newest = None
        for r in self.rows:
            dt = _safe_parse_dt(r.get(key))
            if dt is not None and (newest is None or dt > newest):
                newest = dt
        return newest

    def value_counts(self, key):
        """Every distinct value and how many rows carry it -- for a multi
        column, every individual value and how many rows CONTAIN it.
        No cap: a partial list in a forensic filter is a way to miss
        evidence."""
        counts = {}
        if key in self._multi_keys:
            for r in self.rows:
                for v in set(self._multi_values(r, key)):
                    counts[v] = counts.get(v, 0) + 1
        else:
            for r in self.rows:
                v = r.get(key)
                counts[v] = counts.get(v, 0) + 1
        return sorted(counts.items(), key=lambda kv: _sort_key(kv[0]))

    #: Up to this many ticked values are named; more are counted.
    CHIP_VALUES_NAMED = 3

    def chip_text(self):
        """One readable line stating everything in force, in the column's
        label and the grid's own words."""
        parts = []
        if self._text:
            parts.append('search "%s"' % self._text)
        for key, cond in self._conditions.items():
            said = self.sentences.get(key)
            if said is not None and said[0] is cond:
                parts.append(said[1])
                continue
            parts.append("%s: %s" % (self.label_for(key),
                                     cond.describe(self._column(key))))
        for key, fn in self._posts.items():
            said = self.sentences.get(key)
            parts.append(said[1] if said is not None and said[0] is fn
                         else self.label_for(key))
        for key, allowed in self._values.items():
            column = self._column(key)
            said = self.sentences.get(key)
            if (said is not None and isinstance(said[0], frozenset)
                    and allowed is not None
                    and said[0] == frozenset(allowed)):
                parts.append(said[1])
                continue
            if not allowed:
                # Select-none then OK: a real choice that matches nothing.
                parts.append("%s: no values selected (matches nothing)"
                             % self.label_for(key))
            elif len(allowed) <= self.CHIP_VALUES_NAMED:
                shown = sorted(display_text(v, column) or blank_label(column)
                               for v in allowed)
                parts.append("%s: Is %s" % (self.label_for(key),
                                            " or ".join(shown)))
            else:
                total = len({v for v, _n in self.value_counts(key)})
                parts.append("%s: %d of %d values"
                             % (self.label_for(key), len(allowed), total))
        return " + ".join(parts)
