"""container_rows_from_parser: the row set ContainersView expects, tested
against a stub parser the same way history_rows_from_parser is (see
test_evidence_loader.py's own docstring for why: there is no real
WebCacheV01.dat on this machine for CI to parse).

Kept in its own file rather than appended to test_evidence_loader.py so
this task's diff stays additive to a file it did not need to touch.
"""
import datetime

from webcache.provenance import CONTAINER_NOT_DETERMINABLE
from webcache.shell.evidence_loader import container_rows_from_parser


class _StubContainerParser:
    """Just enough of WebCacheParser's surface: containers_meta (the
    parser's own Containers-table rows) and get_container_type(), the
    same classification method parse_all_entries() uses to stamp every
    live record's ContainerType."""

    def __init__(self, containers_meta, types=None):
        self.containers_meta = containers_meta
        self._types = types or {}

    def get_container_type(self, cid):
        return self._types.get(cid, "Unknown")


def _meta(**overrides):
    base = {
        "ContainerId": 1, "Name": "Cookies", "HasTable": True,
        "RecordCount": 42, "Size": 2048, "PartitionId": "p0",
        "Directory": "C:\\Users\\x\\AppData\\Cookies",
        "LastAccessTime": "2026-01-01 00:00:00 UTC",
        "LastScavengeTime": "2026-01-02 00:00:00 UTC",
        # The raw FILETIMEs _load_containers now keeps beside the strings
        # (2026-01-01 and 2026-01-02 00:00:00 UTC respectively).
        "LastAccessTime_raw": 134116992000000000,
        "LastScavengeTime_raw": 134117856000000000,
    }
    base.update(overrides)
    return base


def test_container_rows_carry_every_key_the_view_reads():
    rows = container_rows_from_parser(
        _StubContainerParser([_meta()], {1: "Cookies"}))
    row = rows[0]
    for key in ("Id", "Name", "Type", "Records", "Size", "Partition",
               "Directory", "LastAccess", "LastScavenge"):
        assert key in row, "ContainersView.COLUMNS reads %r" % key


def test_type_comes_from_the_parsers_own_classification():
    """get_container_type() is the SAME method every live record's own
    ContainerType is stamped with (see ese_parser.parse_all_entries) --
    calling it here rather than re-deriving the classification keeps a
    container's Type always in agreement with what its own records show
    elsewhere in the application."""
    rows = container_rows_from_parser(
        _StubContainerParser([_meta(ContainerId=7)], {7: "History"}))
    assert rows[0]["Type"] == "History"


def test_records_is_the_real_count_when_the_containers_table_exists():
    rows = container_rows_from_parser(
        _StubContainerParser([_meta(HasTable=True, RecordCount=99)]))
    assert rows[0]["Records"] == 99


def test_records_is_not_determinable_when_the_containers_table_is_gone():
    """meta['RecordCount'] stays at its initialised 0 for a container whose
    Container_<id> table was never walked (HasTable False, per
    ese_parser._load_containers/parse_all_entries) -- showing a bare 0
    would misreport 'zero records' when the truth is 'never counted'. This
    application already has a named sentinel for exactly this fact --
    provenance.CONTAINER_NOT_DETERMINABLE -- reused here rather than a
    second, differently-worded one."""
    rows = container_rows_from_parser(
        _StubContainerParser([_meta(HasTable=False, RecordCount=0)]))
    assert rows[0]["Records"] == CONTAINER_NOT_DETERMINABLE


def test_last_access_and_last_scavenge_are_real_datetimes():
    """REPLACES an assertion whose own premise stopped being true.

    This used to assert both fields were passed through as the parser's
    pre-formatted strings, "because _load_containers() keeps no raw
    FILETIME for either timestamp". It does now -- and both columns are
    declared kind="time" in views/containers.py, so a string in them was
    something record_filter's before/after/between/on/last-N-days
    operators could not compare and a sort ordered by its own characters.

    The premise, not the assertion, was the thing that changed; leaving
    the old test in place would have pinned a limitation that no longer
    exists and made removing it look like a regression.
    """
    rows = container_rows_from_parser(_StubContainerParser([_meta()]))
    assert rows[0]["LastAccess"] == datetime.datetime(
        2026, 1, 1, tzinfo=datetime.timezone.utc)
    assert rows[0]["LastScavenge"] == datetime.datetime(
        2026, 1, 2, tzinfo=datetime.timezone.utc)


def test_the_raw_filetime_is_what_is_read_not_the_formatted_string():
    """Teeth for the test above: if the loader ever fell back to parsing
    the string, these two disagreeing would go unnoticed."""
    rows = container_rows_from_parser(_StubContainerParser([_meta(
        LastAccessTime="this is not a date at all")]))
    assert rows[0]["LastAccess"] == datetime.datetime(
        2026, 1, 1, tzinfo=datetime.timezone.utc)


def test_a_container_never_scavenged_reports_no_instant_not_a_1601():
    """0 is what the Containers table stores for a container that has
    never been scavenged. filetime_to_dt refuses to read it as a time,
    which is what a time column renders blank -- the alternative is a
    fabricated 1601-01-01 that reads as a real event."""
    rows = container_rows_from_parser(_StubContainerParser(
        [_meta(LastScavengeTime="", LastScavengeTime_raw=0)]))
    assert rows[0]["LastScavenge"] is None


def test_size_is_the_raw_byte_count_not_a_preformatted_string():
    rows = container_rows_from_parser(_StubContainerParser([_meta(Size=123456)]))
    assert rows[0]["Size"] == 123456
