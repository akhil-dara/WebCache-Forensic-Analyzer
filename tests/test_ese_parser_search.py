"""search_all_tables, as the Search view has to be able to use it.

Three things the engine did not say, and a view cannot invent:

HOW FAR IT HAS GOT. A cross-table search reads every column of every row
of every table -- measured at 6.5-7.8 s on the sample exhibit -- and
before this it reported nothing at all until it was completely finished.
A progress callback fires with REAL counts (rows scanned, tables done,
tables total); no percentage is computed anywhere, because three tables
hold 73% of this exhibit's rows and "table 40 of 83" would be a
fabricated 48%.

THAT IT CAN BE STOPPED. SearchCancelled is declared in the ENGINE, not
in the shell, for one reason this file pins directly: the per-table
`except Exception: continue` would otherwise swallow a shell-defined
cancellation and calmly move on to the next table -- a "cancelled"
search that runs to completion. The ordering of the two except clauses
is the whole point, so it gets its own test.

WHAT IT DID NOT SEARCH. A table that raises is skipped, and it used to
be skipped SILENTLY. A view that has to state "these tables could not be
read, so a keyword absent from this result may still be present in them"
cannot get that from a swallowed exception, so the names land in
parser.search_skipped_tables.
"""
import types

import pytest

from webcache.engine import ese_parser
from webcache.engine.ese_parser import SearchCancelled, WebCacheParser


def _live_node():
    """A `_node` shaped like dissect's real one: long enough to pass
    ese_records.is_record_node, which is what every fake row here needs
    to be enumerated by live_records() instead of silently dropped as a
    1-byte stub."""
    return types.SimpleNamespace(data=b"\x00" * 16, key=b"")


class _Rec(dict):
    """A fake ESE record: dict-like .get(column_name), plus dissect's
    own `_node` attribute."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._node = _live_node()


class _Column:
    def __init__(self, name):
        self.name = name


class _Table:
    """dissect's table surface, as far as search_all_tables reads it."""

    def __init__(self, columns, rows, raises=None):
        self.columns = [_Column(c) for c in columns]
        self._names = list(columns)
        self._rows = rows
        self._raises = raises

    def records(self):
        if self._raises is not None:
            raise self._raises
        for row in self._rows:
            yield _Rec(zip(self._names, row))


class _Db:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return self._tables[name]


def _parser(tables):
    """A real WebCacheParser with a fake db bolted on.

    Real, deliberately: _format_raw_value/_searchable_text/_match_context/
    raw_rendering/raw_type_name are the decode path the hits are actually
    shaped by, and a stub of them would test a different function.
    """
    parser = WebCacheParser()
    parser.db = _Db(tables)
    parser.table_names = list(tables)
    return parser


def _three_tables(rows_each=250):
    rows = [["https://example%d.test/a" % i] for i in range(rows_each)]
    hit = [["https://needle%d.test/a" % i] for i in range(3)]
    return {
        "T1": _Table(["Url"], rows + hit),
        "T2": _Table(["Url"], rows + hit),
        "T3": _Table(["Url"], rows + hit),
    }


# --- progress -------------------------------------------------------------

def test_the_progress_callback_reports_real_counts_and_an_exact_table_total():
    calls = []
    parser = _parser(_three_tables())
    parser.search_all_tables("needle", progress_callback=lambda *a: calls.append(a))

    assert calls, "a search over 759 rows reported nothing at all"
    assert all(total == 3 for _rows, _done, total, _name in calls), (
        "tables_total is len(tables) and is known up front -- it must never "
        "be estimated")
    scanned = [rows for rows, _done, _total, _name in calls]
    assert scanned == sorted(scanned), "rows_scanned must be a running count"
    assert scanned[-1] == 759, (
        "the final call must state every row actually read, got %r"
        % scanned[-1])
    assert calls[-1][1] == 3, "every table boundary must be reported"


def test_progress_fires_on_the_declared_row_cadence():
    """Mirrors parse_all_entries' own every-200-records cadence rather
    than inventing a second one."""
    assert ese_parser._SEARCH_PROGRESS_ROWS == 200
    calls = []
    parser = _parser({"T1": _Table(["Url"], [["x"]] * 600)})
    parser.search_all_tables("zzz", progress_callback=lambda *a: calls.append(a))
    scanned = [rows for rows, _d, _t, _n in calls]
    assert scanned[:3] == [200, 400, 600]


def test_the_table_being_read_is_named_in_every_progress_call():
    calls = []
    parser = _parser(_three_tables())
    parser.search_all_tables("needle", progress_callback=lambda *a: calls.append(a))
    assert {name for _r, _d, _t, name in calls} == {"T1", "T2", "T3"}


# --- cancellation ---------------------------------------------------------

def test_a_cancellation_raised_by_the_callback_never_reaches_the_next_table():
    """THE ordering test. `except SearchCancelled: raise` must come
    BEFORE `except Exception:` -- otherwise the per-table handler eats
    the cancellation and the search calmly carries on into table 2."""
    seen = []

    def cancel_in_table_one(_rows, _done, _total, name):
        seen.append(name)
        raise SearchCancelled()

    parser = _parser(_three_tables())
    with pytest.raises(SearchCancelled):
        parser.search_all_tables("needle",
                                 progress_callback=cancel_in_table_one)
    assert seen == ["T1"], (
        "the cancellation was swallowed and the scan continued into %r"
        % (seen[1:],))


def test_search_cancelled_is_the_engines_own_exception():
    """Declared here, not in the shell -- see this module's docstring.
    A shell subclass of it is what makes the re-raise work at all."""
    assert issubclass(SearchCancelled, Exception)
    assert SearchCancelled.__module__ == ese_parser.__name__


# --- tables that could not be read ---------------------------------------

def test_a_table_that_cannot_be_read_is_named_rather_than_vanishing():
    tables = _three_tables()
    tables["T2"] = _Table(["Url"], [], raises=OSError("page checksum"))
    parser = _parser(tables)
    parser.search_all_tables("needle")

    assert [name for name, _reason in parser.search_skipped_tables] == ["T2"]
    reason = parser.search_skipped_tables[0][1]
    assert "page checksum" in reason, (
        "the reason a table could not be read is part of the fact")


def test_skipped_tables_are_reset_at_the_start_of_every_search():
    tables = _three_tables()
    tables["T2"] = _Table(["Url"], [], raises=OSError("page checksum"))
    parser = _parser(tables)
    parser.search_all_tables("needle")
    assert len(parser.search_skipped_tables) == 1
    parser.search_all_tables("needle")
    assert len(parser.search_skipped_tables) == 1, (
        "a second search must not inherit the first search's skipped list")


def test_a_clean_search_reports_an_empty_skipped_list_not_a_missing_one():
    parser = _parser(_three_tables())
    parser.search_all_tables("needle")
    assert parser.search_skipped_tables == []


# --- what did NOT change --------------------------------------------------

def test_max_results_zero_still_returns_every_hit():
    """A forensic search must never silently stop early and hide
    matching evidence -- unchanged, and pinned here because the progress
    work runs inside the same loop."""
    parser = _parser(_three_tables())
    results = parser.search_all_tables("needle", max_results=0)
    assert len(results) == 9


def test_a_search_with_no_callback_still_works():
    parser = _parser(_three_tables())
    assert len(parser.search_all_tables("needle")) == 9


def test_a_table_filter_searches_only_that_table():
    parser = _parser(_three_tables())
    results = parser.search_all_tables("needle", table_filter="T2")
    assert {r["table"] for r in results} == {"T2"}
