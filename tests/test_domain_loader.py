"""domain_loader.domain_rows(): one row per domain, live entries plus
whatever a recovery scan found -- see domain_loader.py's own module
docstring for why a domain that exists only in carved data has to be told apart from an ordinary one.

Pure-function tests, no Qt needed -- mirrors test_dashboard_data.py's own
stub-testable contract: entries are plain dicts shaped the way parser.
all_entries/RecoveryEngine.structured_records/all_artifacts() actually
produce them, not a real WebCacheParser.
"""
import datetime

from webcache.shell.domain_loader import domain_rows

_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


def _filetime(dt):
    return int((dt - _EPOCH).total_seconds() * 10_000_000)


def _entry(**overrides):
    base = {
        "Url": "https://example.com/a",
        "ContainerType": "History",
        "FileSize": 100,
        "AccessCount": 4,
        "IsInPrivate": False,
        "ModifiedTime_raw": _filetime(
            datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)),
    }
    base.update(overrides)
    return base


# --- basic aggregation -----------------------------------------------------

def test_one_row_per_distinct_domain():
    rows = domain_rows([_entry(Url="https://a.example/1"),
                        _entry(Url="https://a.example/2"),
                        _entry(Url="https://b.example/1")])
    domains = {r["Domain"] for r in rows}
    assert domains == {"a.example", "b.example"}


def test_records_counts_every_entry_for_that_domain():
    rows = domain_rows([_entry(Url="https://a.example/1"),
                        _entry(Url="https://a.example/2")])
    row = next(r for r in rows if r["Domain"] == "a.example")
    assert row["Records"] == 2


def test_file_size_is_summed():
    rows = domain_rows([_entry(Url="https://a.example/1", FileSize=100),
                        _entry(Url="https://a.example/2", FileSize=250)])
    row = next(r for r in rows if r["Domain"] == "a.example")
    assert row["FileSize"] == 350


def test_container_types_are_joined_sorted_and_unique():
    rows = domain_rows([_entry(Url="https://a.example/1", ContainerType="History"),
                        _entry(Url="https://a.example/2", ContainerType="Content"),
                        _entry(Url="https://a.example/3", ContainerType="History")])
    row = next(r for r in rows if r["Domain"] == "a.example")
    assert row["ContainerType"] == "Content, History"


def test_access_count_is_averaged_and_rounded_to_one_decimal():
    rows = domain_rows([_entry(Url="https://a.example/1", AccessCount=1),
                        _entry(Url="https://a.example/2", AccessCount=2)])
    row = next(r for r in rows if r["Domain"] == "a.example")
    assert row["AccessCount"] == 1.5


def test_inprivate_is_true_if_any_entry_was():
    rows = domain_rows([_entry(Url="https://a.example/1", IsInPrivate=False),
                        _entry(Url="https://a.example/2", IsInPrivate=True)])
    row = next(r for r in rows if r["Domain"] == "a.example")
    assert row["IsInPrivate"] is True


def test_a_url_with_no_domain_contributes_no_row_for_it():
    rows = domain_rows([_entry(Url="")])
    assert rows == []


# --- first/last seen: real datetimes, not pre-formatted strings ------------

def test_first_and_last_seen_are_real_datetimes():
    early = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    late = datetime.datetime(2024, 12, 1, tzinfo=datetime.timezone.utc)
    rows = domain_rows([_entry(Url="https://a.example/1",
                               ModifiedTime_raw=_filetime(early)),
                        _entry(Url="https://a.example/2",
                               ModifiedTime_raw=_filetime(late))])
    row = next(r for r in rows if r["Domain"] == "a.example")
    assert isinstance(row["FirstSeen"], datetime.datetime)
    assert isinstance(row["LastSeen"], datetime.datetime)
    assert row["FirstSeen"] == early
    assert row["LastSeen"] == late


def test_an_entry_with_no_timestamp_at_all_leaves_first_seen_none():
    rows = domain_rows([_entry(Url="https://a.example/1", ModifiedTime_raw=0)])
    row = next(r for r in rows if r["Domain"] == "a.example")
    assert row["FirstSeen"] is None
    assert row["LastSeen"] is None


# --- carved records: the "From deleted" / "Deleted only" columns -----------

def test_carved_entries_are_counted_separately_from_live():
    live = [_entry(Url="https://a.example/1")]
    carved = [_entry(Url="https://a.example/2")]
    rows = domain_rows(live, carved)
    row = next(r for r in rows if r["Domain"] == "a.example")
    assert row["Records"] == 2
    assert row["Carved"] == 1
    assert row["OnlyCarved"] is False


def test_a_domain_seen_only_in_carved_data_is_flagged_deleted_only():
    rows = domain_rows([], [_entry(Url="https://gone.example/1"),
                            _entry(Url="https://gone.example/2")])
    row = next(r for r in rows if r["Domain"] == "gone.example")
    assert row["Records"] == 2
    assert row["Carved"] == 2
    assert row["OnlyCarved"] is True


def test_no_carved_entries_means_carved_columns_read_as_honest_zero():
    rows = domain_rows([_entry(Url="https://a.example/1")], [])
    row = next(r for r in rows if r["Domain"] == "a.example")
    assert row["Carved"] == 0
    assert row["OnlyCarved"] is False


def test_a_carved_candidate_with_no_clean_scheme_is_not_counted():
    """A raw string carve with no clean scheme is not close enough to a URL
    to deserve a Domain row (see _counts_as_a_url). A carved file:/// IS
    counted -- live local files already have their [Local File] row, and
    leaving the recovered ones out made it understate."""
    rows = domain_rows([], [_entry(Url="C:/deleted/local.txt"),
                            _entry(Url="xhttps://torn.example/1")])
    assert rows == []


# --- sort order: Records descending, matching the earlier version ------------

def test_rows_are_sorted_by_records_descending():
    rows = domain_rows([
        _entry(Url="https://small.example/1"),
        _entry(Url="https://big.example/1"),
        _entry(Url="https://big.example/2"),
        _entry(Url="https://big.example/3"),
    ])
    assert [r["Domain"] for r in rows] == ["big.example", "small.example"]


# --- which recovered records count -------------------------------------------

from webcache.engine.recovery_engine import STRUCTURED_METHOD


def _domain(rows, name):
    return next((r for r in rows if r["Domain"] == name), None)


def test_a_reconstructed_local_file_record_is_counted():
    """On a real machine Domains showed [Local File] 235, none recovered,
    while the Dashboard said 1,957: every reconstructed file: record (1,338)
    was dropped by a check that read the stored URL -- ":2026...: user@
    file:///..." -- for a leading http://. A reconstructed record is a
    whole record, never text noise."""
    carved = [_entry(Url=":2026060820260615: alice@file:///C:/Users/a/x.docx",
                     RecoverySource=STRUCTURED_METHOD),
              _entry(Url="Visited: alice@https://kept.example/p",
                     RecoverySource=STRUCTURED_METHOD)]
    rows = domain_rows([], carved)
    assert _domain(rows, "[Local File]")["Carved"] == 1
    assert _domain(rows, "kept.example")["Carved"] == 1


def test_a_carved_string_counts_only_with_a_clean_scheme():
    """Text carved from free pages is kept to what is plainly a URL: once
    the cache's own "Visited: user@" prefix is read off, http(s):// or
    file:///. On a real machine 384 such carves were whole stored URLs
    ("Visited: akhil@file:///..."), counted by the Dashboard and dropped
    here. "bhttp://" is a fragment with a stray byte in front, and stays
    out."""
    carved = [_entry(Url="Visited: alice@file:///C:/Users/a/y.txt",
                     RecoverySource="page slack"),
              _entry(Url="https://a.example/1", RecoverySource="page slack"),
              _entry(Url="bhttp://a.example/2", RecoverySource="page slack")]
    rows = domain_rows([], carved)
    assert _domain(rows, "[Local File]")["Carved"] == 1
    assert _domain(rows, "a.example")["Carved"] == 1
    assert not any(r["Domain"].startswith("[App") for r in rows), rows
