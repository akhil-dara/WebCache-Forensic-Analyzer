"""A deleted-record stub is shown as recovered material, never dropped
and never presented as live."""
import types

from webcache.provenance import ABSENCE_NOT_RECOVERED, CARVED_ORIGIN
from webcache.shell import detail_fields, record_kinds
from webcache.shell.recovery_loader import deleted_records_rows


def _engine(tombstones):
    return types.SimpleNamespace(structured_records=[], all_artifacts=lambda: [],
                                 tombstones=tombstones)


_STUB = {"Table": "Container_4", "KeyColumns": ("UrlHash", "EntryId"),
         "KeyValues": (111, 7), "Source": "WebCacheV01.dat"}


def test_a_stub_appears_in_deleted_records():
    rows = deleted_records_rows(_engine([_STUB]))
    assert len(rows) == 1
    row = rows[0]
    assert row["_kind"] == record_kinds.K_TOMBSTONE
    assert row["Origin"] == CARVED_ORIGIN
    assert row["Source"] == "WebCacheV01.dat"
    assert row["CleanUrl"] == ABSENCE_NOT_RECOVERED
    assert "stub" in row["Method"].lower()


def test_a_stub_row_has_the_same_keys_as_a_carve_row():
    carve = {"Url": "u", "RecoverySource": "slack", "Confidence": "low"}
    eng = types.SimpleNamespace(structured_records=[], all_artifacts=lambda: [carve],
                                tombstones=[_STUB])
    carve_row, stub_row = deleted_records_rows(eng)
    assert set(stub_row) == set(carve_row)


def test_an_engine_without_stubs_is_unchanged():
    eng = types.SimpleNamespace(structured_records=[], all_artifacts=lambda: [])
    assert deleted_records_rows(eng) == []


def test_the_dashboard_does_not_count_a_stub_as_a_domain():
    """merge_recovered_into_stats iterates deleted_records_rows() output
    directly (main_window._push_dashboard_state hands it recovery_rows
    straight through) -- the one consumer, besides the Deleted Records
    grid itself and the detail dialog, that reads a stub row's CONTENT
    rather than merely its length. ContainerType is a real fact and stays
    counted; CleanUrl is ABSENCE_NOT_RECOVERED and must never be run
    through extract_domain and tallied into Top Domains."""
    from webcache.shell import dashboard_data

    rows = deleted_records_rows(_engine([_STUB]))
    stats = {"total_records": 0, "container_types": {}, "top_domains": {}}
    merged = dashboard_data.merge_recovered_into_stats(stats, rows)
    assert merged["container_types"]["Not determinable"] == 1
    assert sum(merged["top_domains"].values()) == 0


def test_domain_loader_produces_no_domain_from_a_stub_row():
    """domain_rows() is never actually handed deleted_records_rows()
    output in this application -- main_window._domains_carved_entries()
    draws straight from engine.structured_records/all_artifacts(), which
    never include tombstones (see recovery_loader.deleted_records_rows'
    own docstring: tombstones are appended by THIS function, from
    engine.tombstones, a separate attribute _domains_carved_entries never
    reads). This nails that down: even a stub-SHAPED row fed to it
    directly produces no domain, because its CleanUrl (ABSENCE_NOT_
    RECOVERED) never starts with http:// or https://."""
    from webcache.shell.domain_loader import domain_rows

    stub_row = deleted_records_rows(_engine([_STUB]))[0]
    assert domain_rows([], [stub_row]) == []


def test_the_record_dialog_treats_a_stub_as_recovered_and_names_its_key():
    row = deleted_records_rows(_engine([_STUB]))[0]
    groups = detail_fields.fields_for(row)
    # NOT repr(groups): FieldGroup.__repr__ deliberately prints only a
    # field COUNT per group ("FieldGroup('...', 4 fields)") -- that is
    # what an examiner never sees, and asserting against it would pass or
    # fail by accident, never by checking what the dialog actually shows.
    # The dialog shows DetailField.label/.display_value (and carries .key
    # for tests); walk those instead.
    fields = [f for g in groups for f in g.fields]
    text = repr([(f.key, f.label, f.display_value) for f in fields])
    assert "Live record" not in text
    assert "EntryId" in text and "7" in text
