"""A deleted-record stub's dialog never says its
bytes were carved -- the key survived, nothing was carved -- and its
strip says where the key was found."""
from webcache.shell import detail_fields, recovery_loader
from webcache.shell.record_kinds import K_TOMBSTONE
from tests.test_copies_and_deleted_records import STUB, _engine


def _stub_row():
    return next(r for r in recovery_loader.deleted_records_rows(
        _engine([], [STUB])) if r["_kind"] == K_TOMBSTONE)


def test_a_stub_origin_line_says_nothing_was_carved():
    line = detail_fields.origin_line(_stub_row())
    assert line == ("Deleted-record stub: the b-tree key survived; no "
                    "record bytes were carved")


def test_a_stub_strip_says_found_in_not_carved_from():
    labels = [label for label, _v in detail_fields.provenance_facts(
        _stub_row())]
    assert "Found in" in labels
    assert "Carved from" not in labels
