import csv
import hashlib
import json

import pytest

from webcache import provenance
from webcache.engine import evidence_model, forensic_engine
from tests.fixtures import make_rows


def test_the_schema_now_carries_carve_provenance():
    """The confirmed defect: 73 fields, none of them provenance. Every
    export of a carved record silently lost where it came from, and the
    'no format can drop a column' test could not catch it because the
    columns were never in the schema to drop."""
    keys = set(forensic_engine.ENTRY_FIELD_KEYS)
    for needed in provenance.PROVENANCE_FIELDS:
        assert needed in keys, "%s missing from the canonical export schema" % needed


def test_field_provenance_grades_every_provenance_column_as_carved():
    """A field being CATALOGUED is not the same as it being catalogued
    CORRECTLY. evidence_model.basis_of() defaults to DERIVED for anything
    uncatalogued, so a test that only checked 'an entry exists' would pass
    even if these four were silently mis-graded as DERIVED -- which is
    exactly what happened: Origin, Source, Page and Method had no
    FIELD_PROVENANCE entry at all, so basis_of() silently returned DERIVED
    ("Computed by this tool ... using documented, reproducible arithmetic")
    for data that was carved from unallocated disk. Offset and Confidence
    already had correct CARVED entries; this asserts all six explicitly, so
    the two that were already right cannot mask the four that were not."""
    for key in provenance.PROVENANCE_FIELDS:
        assert evidence_model.basis_of(key) == evidence_model.CARVED, (
            "%s is graded %s, not CARVED" % (key, evidence_model.basis_of(key)))


def test_no_export_format_can_drop_provenance(tmp_path):
    """There is no per-format column list in forensic_engine (no
    ``EXPORT_FORMATS`` / ``columns_for_format``): every format renders from
    the one ENTRY_FIELDS schema.

    What actually guarantees "no format can drop a column" in this codebase
    is architectural: every export renders its columns from the single
    ENTRY_FIELD_KEYS / ENTRY_FIELD_HEADERS lists (see the module docstring
    above ENTRY_FIELDS). This test exercises that guarantee directly against
    three real exporters spanning the plain CSV, the KAPE/Timeline-Explorer
    CSV (which prepends its own RecordSource column) and the Timesketch
    JSONL (which drops empty fields per-row, so it is checked over a batch
    of rows rather than any single one) -- rather than a fabricated
    per-format lookup that no code in this repository provides.
    """
    entries = make_rows(50)
    carved = next(r for r in entries if r["Origin"].startswith("Carved"))
    engine = forensic_engine.ForensicEngine()

    # Checking that the HEADER ROW contains the right text (as an earlier
    # version of this test did) only proves the column exists -- headers
    # come from ENTRY_FIELD_HEADERS, built once at import from the static
    # schema list, entirely decoupled from what build_entry_row puts in a
    # given DATA row. A carver that populated the column with an empty
    # string on every row would still pass a header-only check. Read the
    # rows back with csv.DictReader and compare the real cell values
    # against the source fixture row instead.
    def _header_for(key):
        return forensic_engine.ENTRY_FIELD_HEADERS[
            forensic_engine.ENTRY_FIELD_KEYS.index(key)]

    def _assert_row_carries_provenance(written_row, label):
        for key in provenance.PROVENANCE_FIELDS:
            cell = written_row[_header_for(key)]
            assert cell == str(carved[key]), (
                "%s drops or blanks %s: wrote %r, expected %r"
                % (label, key, cell, str(carved[key])))

    csv_path = tmp_path / "export.csv"
    engine.export_csv(entries, str(csv_path))
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    written = next(r for r in rows if r[_header_for("CleanUrl")] == carved["CleanUrl"])
    _assert_row_carries_provenance(written, "csv")


def test_carved_rows_describe_their_source_file_and_offset():
    """"if we recover, we should give source which file we got it"."""
    carved = next(r for r in make_rows(100) if r["Origin"].startswith("Carved"))
    text = provenance.describe_origin(carved)
    assert carved["Source"] in text
    assert "0x%08X" % carved["Offset"] in text


def test_live_rows_describe_their_container():
    live = next(r for r in make_rows(100) if r["Origin"] == "Live record")
    assert "Live record" in provenance.describe_origin(live)


def test_carved_rows_with_a_resolved_container_name_it():
    """A structured record (carve_structured_records) always resolved a
    real ContainerType before recovery_loader.py ever built this row --
    describe_origin() must say what it is, the same way it already says
    Source/Offset/Method/Confidence, not silently drop the one field that
    happens to answer "what container was this in"."""
    carved = next(r for r in make_rows(100) if r["Origin"].startswith("Carved"))
    assert carved["ContainerType"] == "History"  # fixtures.py's own value
    text = provenance.describe_origin(carved)
    assert "in History" in text
    assert "not determinable" not in text.lower()


def test_carved_rows_with_no_determinable_container_say_so_plainly():
    """The finding this task fixes: a raw string carve (page slack, a
    transaction log) never had a ContainerId to resolve, so its
    ContainerType is CONTAINER_NOT_DETERMINABLE (see recovery_loader.py's
    normalisation). Explain must state that plainly -- not omit the
    container and leave an examiner assuming it simply was not shown."""
    row = {
        "Origin": "Carved (deleted/unflushed)",
        "ContainerType": provenance.CONTAINER_NOT_DETERMINABLE,
        "Source": "V01.log",
        "Offset": 777,
        "Page": None,
        "Method": "Transaction log",
        "Confidence": "medium",
    }
    text = provenance.describe_origin(row)
    assert "not determinable" in text.lower()
    assert row["Source"] in text


def test_describe_origin_treats_a_missing_containertype_key_the_same_way():
    """A row built before this fix, or by a caller that never normalised
    ContainerType at all, must degrade to the same honest statement as the
    sentinel -- not raise, and not silently say nothing about the
    container."""
    row = {
        "Origin": "Carved (deleted/unflushed)",
        "Source": "V01.log",
        "Offset": 12,
        "Page": 1,
        "Method": "DB unallocated space",
        "Confidence": "low",
    }
    assert "ContainerType" not in row
    text = provenance.describe_origin(row)
    assert "not determinable" in text.lower()


def test_describe_origin_does_not_drop_a_zero_offset_or_page():
    """`if row.get("Offset"):` treats 0 as falsy and silently omits it -- the
    same bug class as `str(value or "")`, which turns a live
    record's Offset: 0 into an empty cell. A record genuinely carved at byte
    offset 0 of page 0 is not rare (the very first page of a file, or of
    unallocated space), and this line's entire job is to say which file, at
    what offset -- dropping a real zero is dropping real evidence."""
    row = {
        "Origin": "Carved (deleted/unflushed)",
        "Source": "V01.log",
        "Offset": 0,
        "Page": 0,
        "Method": "page-scan",
        "Confidence": "high",
    }
    text = provenance.describe_origin(row)
    assert "0x00000000" in text, text
    assert "(page 0)" in text, text


def test_describe_origin_tolerates_a_non_numeric_offset():
    """Carved data is damaged data; a byte offset that failed to parse as an
    int must degrade the display, not raise out of a report-building call."""
    row = {
        "Origin": "Carved (deleted/unflushed)",
        "Source": "V01.log",
        "Offset": "unknown",
        "Page": 4,
        "Method": "page-scan",
        "Confidence": "low",
    }
    text = provenance.describe_origin(row)  # must not raise
    assert "unknown" in text


def test_every_row_has_an_origin():
    assert all(provenance.origin_of(r) for r in make_rows(200))


def test_evidence_set_hashes_each_file(tmp_path):
    f = tmp_path / "WebCacheV01.dat"
    f.write_bytes(b"evidence bytes")
    ev = provenance.EvidenceSet.from_paths([str(f)])
    assert ev.hashes[str(f)] == hashlib.sha256(b"evidence bytes").hexdigest()


def test_evidence_set_reports_a_file_that_changed_since_opening(tmp_path):
    f = tmp_path / "WebCacheV01.dat"
    f.write_bytes(b"original")
    ev = provenance.EvidenceSet.from_paths([str(f)])
    assert ev.verify() == []
    f.write_bytes(b"tampered")
    assert str(f) in ev.verify()[0]


def test_evidence_set_reports_every_changed_file_not_just_the_first(tmp_path):
    """For evidence integrity, stopping at the first problem and staying
    silent about the rest is a serious gap: an examiner reading verify() ==
    [one message] would have no way to know a second file was also
    compromised. This pins the current (correct) behaviour of surfacing
    every problem, over a tampered + deleted + untouched mix."""
    tampered = tmp_path / "tampered.dat"
    deleted = tmp_path / "deleted.dat"
    untouched = tmp_path / "untouched.dat"
    tampered.write_bytes(b"original")
    deleted.write_bytes(b"original")
    untouched.write_bytes(b"original")

    ev = provenance.EvidenceSet.from_paths(
        [str(tampered), str(deleted), str(untouched)])
    assert ev.verify() == []

    tampered.write_bytes(b"tampered")
    deleted.unlink()

    problems = ev.verify()
    assert len(problems) == 2, problems
    assert any(str(tampered) in p for p in problems), problems
    assert any(str(deleted) in p for p in problems), problems
    assert not any(str(untouched) in p for p in problems), problems


def test_export_stamp_carries_hashes_counts_and_filters(tmp_path):
    f = tmp_path / "WebCacheV01.dat"
    f.write_bytes(b"x")
    ev = provenance.EvidenceSet.from_paths([str(f)])
    stamp = provenance.export_stamp(ev, {"view": "History", "filters": 'contains "msn"'},
                                    shown=12, total=1924)
    assert stamp["shown"] == 12 and stamp["total"] == 1924
    assert stamp["evidence"][str(f)] == ev.hashes[str(f)]
    assert "History" in stamp["view_state"]["view"]
    assert stamp["tool_version"]
    assert stamp["exported_utc"].endswith("Z")
