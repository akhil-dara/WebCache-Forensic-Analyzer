"""dashboard_data.py: shaping a parser (and, after a scan, a recovery
engine's carved rows) into the numbers views/dashboard.py renders --
mirroring evidence_loader.py/recovery_loader.py's own row-shaping
functions, and their same stub-testable contract (a fake parser needs
only the attributes the function actually reads).

THE CARVED-RECORDS RULE, tested directly: compute_dashboard_stats() only
ever reads parser.all_entries, so its own figures are always live-only.
merge_recovered_into_stats() is the other half -- Total Records/Container
Types/Top Domains fold in the carved set; InPrivate/Cache Size/Tables/
Containers do not, because deleted_records_rows() (recovery_loader.py)
never carries FileSize or an InPrivate flag for the shared, every-
container-type shape it builds, and table/container counts are schema
facts a carve cannot change. See dashboard_data.py's own module docstring
for the full reasoning.
"""
from collections import Counter

from webcache.provenance import CONTAINER_NOT_DETERMINABLE
from webcache.shell.dashboard_data import (apportioned_percentages,
                                           compute_dashboard_stats,
                                           database_info_rows, format_size,
                                           merge_recovered_into_stats)


class _FullParser:
    def __init__(self):
        self.db_path = "C:/case/WebCacheV01.dat"
        self.all_entries = [
            {"Url": "https://example.com/a", "ContainerType": "History",
             "IsInPrivate": True, "FileSize": 1000, "AccessCount": 3},
            {"Url": "https://example.com/b", "ContainerType": "History",
             "IsInPrivate": False, "FileSize": 2000, "AccessCount": 1},
            {"Url": "https://other.example/c", "ContainerType": "Cookies",
             "IsInPrivate": False, "FileSize": 0, "AccessCount": 0},
        ]
        self.containers_meta = [{"ContainerId": 1}, {"ContainerId": 2}]

    def get_database_info(self):
        return {"path": self.db_path, "file_size": 4096,
               "table_count": 12, "container_count": 2,
               "total_entries": len(self.all_entries)}


class _MinimalParser:
    """No all_entries/get_database_info at all -- the identical stand-in
    shape test_main_window_records_views.py's own _MinimalParser already
    uses for the same "nothing to show yet, not a crash" contract."""


def test_none_parser_returns_none():
    assert compute_dashboard_stats(None) is None


def test_parser_missing_all_entries_returns_none():
    assert compute_dashboard_stats(_MinimalParser()) is None


def test_full_parser_computes_every_figure():
    stats = compute_dashboard_stats(_FullParser())
    assert stats["total_records"] == 3
    assert stats["table_count"] == 12
    assert stats["container_count"] == 2
    assert stats["inprivate_count"] == 1
    assert stats["total_file_size"] == 3000
    assert stats["container_types"] == Counter({"History": 2, "Cookies": 1})
    assert stats["top_domains"] == Counter({"example.com": 2, "other.example": 1})
    assert stats["db_path"] == "C:/case/WebCacheV01.dat"
    assert stats["db_file_size"] == 4096
    assert stats["recovered_count"] == 0


def test_merge_of_none_stats_is_none():
    assert merge_recovered_into_stats(None, []) is None


def test_merge_with_no_recovered_rows_leaves_stats_unchanged_in_value():
    stats = compute_dashboard_stats(_FullParser())
    merged = merge_recovered_into_stats(stats, [])
    assert merged["total_records"] == stats["total_records"]
    assert merged["container_types"] == stats["container_types"]
    assert merged["top_domains"] == stats["top_domains"]
    assert merged["recovered_count"] == 0


def test_merge_folds_recovered_rows_into_total_and_container_types():
    stats = compute_dashboard_stats(_FullParser())
    recovered = [
        {"CleanUrl": "https://deleted.example/x", "ContainerType": "History"},
        {"CleanUrl": "https://deleted.example/y", "ContainerType": "History"},
        # A raw string carve: no resolvable container at all.
        {"CleanUrl": "https://carved-string.example/z", "ContainerType": None},
    ]
    merged = merge_recovered_into_stats(stats, recovered)
    assert merged["total_records"] == stats["total_records"] + 3
    assert merged["recovered_count"] == 3
    assert merged["container_types"]["History"] == 4  # 2 live + 2 carved
    assert merged["container_types"][CONTAINER_NOT_DETERMINABLE] == 1
    assert merged["top_domains"]["deleted.example"] == 2


def test_merge_never_extends_inprivate_cache_size_tables_or_containers():
    """These four figures cannot honestly be extended by a carve -- see
    the module docstring. A merge must leave them exactly as computed at
    open time."""
    stats = compute_dashboard_stats(_FullParser())
    recovered = [{"CleanUrl": "https://deleted.example/x",
                 "ContainerType": "History"}]
    merged = merge_recovered_into_stats(stats, recovered)
    assert merged["inprivate_count"] == stats["inprivate_count"]
    assert merged["total_file_size"] == stats["total_file_size"]
    assert merged["table_count"] == stats["table_count"]
    assert merged["container_count"] == stats["container_count"]


def test_merge_does_not_mutate_the_original_stats_dict():
    """The caller (main_window._on_recovery_loaded) always merges from the
    ORIGINAL live stats, never a previously-merged one -- the same
    discipline MainWindow._live_history_rows already keeps for History.
    That only works if merge_recovered_into_stats never mutates its input."""
    stats = compute_dashboard_stats(_FullParser())
    before = Counter(stats["container_types"])
    merge_recovered_into_stats(
        stats, [{"CleanUrl": "https://x/y", "ContainerType": "History"}])
    assert stats["container_types"] == before


def test_database_info_rows_states_the_four_facts():
    stats = compute_dashboard_stats(_FullParser())
    rows = database_info_rows(stats)
    assert rows == [
        ("File", "WebCacheV01.dat"),
        ("Size", 4096),
        ("Tables", 12),
        ("Containers", 2),
    ]


def test_database_info_rows_of_none_is_empty():
    assert database_info_rows(None) == []


def test_format_size_boundaries():
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(2048) == "2.0 KB"
    assert format_size(5 * 1024 * 1024) == "5.0 MB"
    assert format_size(3 * 1024 * 1024 * 1024) == "3.00 GB"


# --- apportioned_percentages: Container Types must sum to exactly 100 -----
#
# Independent per-row rounding (round(count/total*100)) is what made the
# Container Types card read 90/8/2/1 for 546/46/10/8 of 610 records -- four
# honest numbers that add up to 101, which in a forensic report invites the
# one question this tool exists to make unnecessary. Largest-remainder
# (Hamilton) apportionment is the fix: give every share its floor, then hand
# the leftover percentage points to whichever shares had the largest
# fractional remainder, one point each, until the leftover is exhausted.

def test_apportioned_percentages_sum_to_a_hundred_on_a_real_example():
    """546/46/10/8 of 610 rounds independently to 90/8/2/1 (101, not
    100)."""
    result = apportioned_percentages([546, 46, 10, 8])
    assert sum(result) == 100
    assert result == [89, 8, 2, 1]


def test_apportioned_percentages_always_sums_to_a_hundred_when_nonzero():
    for counts in ([1, 1, 1], [7, 7, 7, 7, 7, 7, 7], [1, 2, 3, 4, 5],
                   [100], [33, 33, 34], [1] * 17):
        result = apportioned_percentages(counts)
        assert sum(result) == 100, counts
        assert len(result) == len(counts)


def test_apportioned_percentages_of_all_zeros_is_all_zeros():
    assert apportioned_percentages([0, 0, 0]) == [0, 0, 0]


def test_apportioned_percentages_of_empty_is_empty():
    assert apportioned_percentages([]) == []


def test_apportioned_percentages_preserves_input_order():
    """The result lines up positionally with the input -- the caller (a
    Counter.most_common() list) is already count-descending, and this must
    not silently re-sort it."""
    result = apportioned_percentages([10, 0, 90])
    assert result[1] == 0
    assert result[2] > result[0]


def test_recovered_domains_are_counted_by_the_domains_views_own_rule():
    """One host list, two screens: a recovered launcher address
    ("microsoft-edge:?url=https://...") is filed by its stored URL, as the
    Domains view files it, not by the target its cleaned form unwraps to;
    otherwise the Dashboard named a host the Domains view had no row for."""
    from collections import Counter
    from webcache.engine import forensic_engine
    from webcache.shell import dashboard_data, domain_loader
    from webcache.shell.detail_fields import K_CARVED_STRUCT
    stored = "Visited: u@microsoft-edge:?url=https://launch.example/"
    record = {"Url": stored, "CleanUrl": "https://launch.example/",
              "RecoverySource": domain_loader.STRUCTURED_METHOD}
    row = {"_kind": K_CARVED_STRUCT, "_record": record,
           "CleanUrl": "https://launch.example/", "ContainerType": "History"}
    stats = {"total_records": 0, "container_types": Counter(),
             "top_domains": Counter()}
    merged = dashboard_data.merge_recovered_into_stats(stats, [row])
    domains = {r["Domain"] for r in domain_loader.domain_rows([], [record])}
    assert set(merged["top_domains"]) == domains
    assert forensic_engine.extract_domain(stored) in domains
