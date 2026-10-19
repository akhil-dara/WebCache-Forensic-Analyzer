"""WHICH fields, in WHAT order, with WHAT wording, and what a missing one
says. The part of the record detail dialog with forensic consequences.

Deliberately Qt-free -- no QApplication, no qtbot, nothing painted.
detail_fields.fields_for() is a pure function from a row dict to a list of
groups, and record_detail.py only paints what it returns. Splitting it out
is what makes the consequential half testable at all: a test that has to
construct a dialog to ask "does a carved string artifact claim it was not
InPrivate?" is a test nobody writes.

The three properties these lean on hardest:

  NOTHING RECOVERED IS EVER HIDDEN. After the named groups, every
  remaining key is swept into "Other recovered values". A fixed handful of
  fields would make carving read as though it had recovered almost
  nothing.

  A BLANK IS NEVER A VALUE. Every field's display_value is a non-empty
  string, always -- one of four absence sentences when there is no value.

  NO BADGE IS GUESSED. DetailField.field is an explicit provenance key or
  None. A lookup that defaulted to the LABEL would silently give every
  prose label no badge; here evidence_model.basis_of()'s default=DERIVED
  would silently paint DER on a typo, so a declared key must be real.
"""
import datetime

import pytest

from webcache import provenance
from webcache.engine import evidence_model
from webcache.shell import detail_fields as df
from webcache.shell.record_kinds import (K_CARVED_STRING, K_CARVED_STRUCT,
                                         K_CERT, K_CONTAINER, K_COOKIE,
                                         K_DOMAIN, K_FILE_ACCESS, K_HISTORY,
                                         K_HSTS, K_INDICATOR, K_PERIOD,
                                         K_PLACE)

UTC = datetime.timezone.utc


# --- rows, shaped exactly as the Unit 1 loaders build them ---------------

def history_row(**over):
    entry = {
        "EntryId": 12, "ContainerId": 4, "ContainerName": "History",
        "ContainerType": "History", "CacheId": 0, "UrlHash": 99887766,
        "SecureDirectory": 3, "Url": "Visited: user@https://example.test/a",
        "CleanUrl": "https://example.test/a", "UrlUsername": "user",
        "MSHistFrom": "", "MSHistTo": "", "RedirectUrl": "", "IsLeak": False,
        "AccessCount": 0, "SyncCount": 0, "ExemptionDelta": 0,
        "ModifiedTime": "2024-03-11 09:14:02 UTC",
        "ModifiedTime_raw": 133544180420000000,
        "AccessedTime": "", "AccessedTime_raw": 0,
        "CreationTime": "", "CreationTime_raw": 0,
        "Flags": 0x08, "FlagsDecoded": "InPrivate", "Type": 1,
        "IsInPrivate": True, "Filename": "", "FileExtension": "",
        "FileSize": None, "CacheFolder": "", "CachedFilePath": "",
        "SecureDirectoryName": "", "BlobClass": "sps",
        "SPS_Properties": {6: 4, 9: "unnamed-value", 24: 133544180420000000},
        "SPS_VisitCount": 4, "SPS_PageTitle": "Example page",
        "SPS_LastVisitLocal": "2024-03-11 14:44:02 LOCAL",
        "SPS_LastVisitLocal_raw": 133544360420000000,
        "ResponseHeaders": {}, "RequestHeaders": {},
        "ResponseHeaders_raw": b"1SPS" + b"\x00" * 60,
        "RequestHeaders_raw": None,
        "SearchTerms": "", "IsLocalFile": False,
    }
    row = {
        "CleanUrl": "https://example.test/a", "Title": "Example page",
        "AccessedUtc": datetime.datetime(2024, 3, 11, 9, 14, 2, tzinfo=UTC),
        "AccessedLocal": datetime.datetime(2024, 3, 11, 14, 44, 2),
        "VisitCount": 4, "Domain": "example.test", "IsInPrivate": True,
        "Origin": "Live record", "Source": "", "SearchTerms": "",
        "IsLocalFile": False, "_record": entry, "_kind": K_HISTORY,
        "AccessedUtcBasis": "ModifiedTime (visit written)",
        "VisitCountSource": "SPS id6 (property store: user visits)",
        "ContainerType": "History",
    }
    row.update(over)
    return row


def file_access_row(**over):
    entry = {
        "EntryId": 5, "ContainerId": 2, "ContainerName": "Content",
        "ContainerType": "Content", "Url": "file:///C:/Users/x/report.docx",
        "CleanUrl": "file:///C:/Users/x/report.docx",
        "CachedFilePath": r"C:\Users\x\INetCache\IE\ABC123\report[1].docx",
        "CacheFolder": r"C:\Users\x\INetCache\IE",
        "SecureDirectoryName": "ABC123", "SecureDirectory": 1,
        "Filename": "report[1].docx", "FileExtension": "docx",
        "FileSize": 20480, "IsLocalFile": True, "Flags": 0,
        "ModifiedTime_raw": 133544180420000000, "AccessCount": 2,
        "ResponseHeaders_raw": None, "RequestHeaders_raw": None,
    }
    row = {
        "ModifiedTime": datetime.datetime(2024, 3, 11, 9, 14, 2, tzinfo=UTC),
        "AccessedLocal": None, "VisitCountBest": 2,
        "CleanUrl": "file:///C:/Users/x/report.docx",
        "Origin": "Live record", "Source": "", "FileSize": 20480,
        "ContainerId": 2, "ContainerName": "Content", "EntryId": 5,
        "AccessedTime": None, "CreationTime": None,
        "_record": entry, "_kind": K_FILE_ACCESS,
        "VisitCountSource": "AccessCount column (cache touches, not user visits)",
        "ModifiedTimeBasis": "ModifiedTime (visit written)",
    }
    row.update(over)
    return row


def carved_struct_row(**over):
    """Shaped as recovery_loader.deleted_records_rows' STRUCTURED loop
    builds it -- which is why it carries Encoding: "". A structured carve
    reconstructs real database columns and has no character encoding to
    state; only a raw string carve does. That "" is therefore "not
    applicable to this kind of row", not "the carve missed it", and the
    dialog has to tell those two apart."""
    entry = {
        "EntryId": 77, "ContainerId": 4, "ContainerName": "History",
        "ContainerType": "History", "Url": "https://example.test/deleted",
        "CleanUrl": "https://example.test/deleted", "Flags": 0x08,
        "UrlHealth": "intact", "UrlHealthNote": "", "UrlSalvaged": False,
        "UrlSalvageNote": "", "CarvedFieldsDerived": True,
        "Region": "page-slack", "RecordEndMode": "clean", "InLiveDb": False,
        "NearbyFiletime_raw": 133544180420000000,
        "Source": "WebCacheV01.dat", "Offset": 0, "Page": 0,
        "RecoverySource": "unallocated page", "Confidence": "medium",
        "ModifiedTime_raw": 133544180420000000, "AccessCount": 1,
        "CacheId": 0, "UrlHash": 5, "SecureDirectory": 0, "Type": 1,
        "SyncCount": 0, "ExemptionDelta": 0, "Filename": "",
        "SPS_Properties": {}, "ResponseHeaders_raw": None,
        "RequestHeaders_raw": None, "SearchTerms": "", "IsLocalFile": False,
        "SPS_PageTitle": "",
    }
    row = {
        "CleanUrl": "https://example.test/deleted", "Title": "",
        "AccessedUtc": datetime.datetime(2024, 3, 11, 9, 14, 2, tzinfo=UTC),
        "AccessedLocal": None, "VisitCount": 1, "Domain": "example.test",
        "IsInPrivate": True, "ContainerType": "History",
        "Origin": "Carved (unallocated page)", "Source": "WebCacheV01.dat",
        "Offset": 0, "Page": 0, "Method": "unallocated page",
        "Confidence": "medium", "SearchTerms": "", "IsLocalFile": False,
        "_record": entry, "_kind": K_CARVED_STRUCT,
        "AccessedUtcBasis": "ModifiedTime (visit written)",
        "VisitCountSource": "AccessCount column (cache touches, not user visits)",
        "UrlHealth": "intact",
        "Region": "page-slack",
        "Encoding": "",
    }
    row.update(over)
    return row


def carved_string_row(**over):
    artifact = {
        "CleanUrl": "ttp://example.test/frag", "Url": "ttp://example.test/frag",
        "UrlHealth": "repairable", "UrlHealthNote": "carve began mid-token",
        "UrlSalvaged": True, "UrlSalvageNote": "leading 'h' restored",
        "Region": "page-slack", "Encoding": "utf-16-le",
        "Source": "V01.log", "Offset": 107760, "Page": 26,
        "RecoverySource": "transaction log", "Confidence": "low",
        "AlsoSeenIn": "page-slack, transaction log",
        "FragmentCount": 2, "FragmentOffsets": [107760, 108020],
        "FragmentTexts": ["ttp://example", ".test/frag"],
        "NearbyFiletime": None, "ContainerType": "",
    }
    row = {
        "CleanUrl": "ttp://example.test/frag", "Title": "",
        "Timestamp": None,
        "ContainerType": provenance.CONTAINER_NOT_DETERMINABLE,
        "Origin": "Carved (transaction log)", "Source": "V01.log",
        "Offset": 107760, "Page": 26, "Method": "transaction log",
        "Confidence": "low", "_record": artifact, "_kind": K_CARVED_STRING,
        "UrlHealth": "repairable",
        "IsInPrivate": provenance.ABSENCE_NOT_DETERMINABLE,
        "Region": "page-slack", "Encoding": "utf-16-le",
    }
    row.update(over)
    return row


def cookie_row(**over):
    entry = {"Domain": "example.test", "RDomain": "test.example", "Name": "sid",
             "Value": "abc", "Path": "/", "Flags": 1, "IsSecure": True,
             "EntryId": 3, "Table": "CookieEntryEx_1", "PartitionId": "0",
             "AppDirectory": "", "Expires_raw": 133544180420000000,
             "LastModified_raw": 133544180420000000}
    row = {"Domain": "example.test", "Name": "sid", "Value": "abc", "Path": "/",
           "Expires": datetime.datetime(2024, 3, 11, 9, 14, 2, tzinfo=UTC),
           "LastModified": datetime.datetime(2024, 3, 11, 9, 14, 2, tzinfo=UTC),
           "_record": entry, "_kind": K_COOKIE, "IsSecure": True}
    row.update(over)
    return row


def hsts_row(**over):
    entry = {"Domain": "example.test", "EntryId": 1, "Table": "HstsEntryEx_1",
             "PartitionId": "0", "Expires_raw": 0}
    row = {"Domain": "example.test", "Corroborated": "yes",
           "Significance": "TLS connection", "HostAttribution": "exact host",
           "LastTimeUsed": None, "Expires": None, "IncludeSubdomains": "Yes",
           "_record": entry, "_kind": K_HSTS}
    row.update(over)
    return row


def cert_row(**over):
    entry = {"HostPort": "example.test:443", "IsCertificate": True,
             "Thumbprint": "aabb", "BlobSize": 1200,
             "Blob_raw": b"\x30\x82" + b"\x00" * 200,
             "ModifiedTime_raw": 133544180420000000}
    row = {"HostPort": "example.test:443", "IsCertificate": True,
           "Thumbprint": "aabb", "BlobSize": 1200,
           "ModifiedTime": datetime.datetime(2024, 3, 11, 9, 14, 2, tzinfo=UTC),
           "_record": entry, "_kind": K_CERT, "BlobBytes": 202}
    row.update(over)
    return row


def container_row(**over):
    meta = {"ContainerId": 4, "Name": "History", "Size": 4096,
            "PartitionId": "0", "Directory": r"C:\Users\x\INetCache\IE",
            "TableName": "Container_4", "Flags": 0, "Limit": 100,
            "EntryMaxAge": 30, "HasTable": True, "RecordCount": 610,
            "SecureDirectoryNames": ["AAA", "BBB", "CCC"],
            "LastAccessTime_raw": 133544180420000000,
            "LastScavengeTime_raw": 0}
    row = {"Id": 4, "Name": "History", "Type": "History", "Records": 610,
           "Size": 4096, "Partition": "0",
           "Directory": r"C:\Users\x\INetCache\IE",
           "LastAccess": datetime.datetime(2024, 3, 11, 9, 14, 2, tzinfo=UTC),
           "LastScavenge": None, "_record": meta, "_kind": K_CONTAINER}
    row.update(over)
    return row


def domain_row(**over):
    members = [history_row()["_record"], carved_struct_row()["_record"]]
    row = {"Domain": "example.test", "Records": 2, "Carved": 1,
           "OnlyCarved": False, "FileSize": 0, "FirstSeen": None,
           "LastSeen": None, "ContainerType": "History", "AccessCount": 1.0,
           "IsInPrivate": True, "_kind": K_DOMAIN, "_record": None,
           "_members": members}
    row.update(over)
    return row


def indicator_row(**over):
    row = {"Kind": "MAC address", "Value": "00:11:22:33:44:55",
           "Decoded": "", "Conf": "High", "Records": 2,
           "Why": "colon-separated hex octets", "_kind": K_INDICATOR,
           "_record": None, "_records": [history_row()["_record"]],
           "Fields": "File name, URL"}
    row.update(over)
    return row


def period_row(**over):
    members = [history_row()["_record"], carved_struct_row()["_record"]]
    row = {"Period": "2024-06-15",
           "PeriodStart": datetime.datetime(2024, 6, 15,
                                            tzinfo=datetime.timezone.utc),
           "Records": 2, "Share": 1.0, "Carved": 1, "GapBefore": 0,
           "Types": "History:2", "Domains": "example.test (2)",
           "_kind": K_PERIOD, "_members": members}
    row.update(over)
    return row


def place_row(**over):
    """A Location place, shaped exactly as location_loader.places builds
    one. Its members are FIXES -- already-shaped rows carrying their own
    _kind and _record -- not raw engine dicts, which is what every other
    aggregate's members are."""
    from webcache.shell import location_loader

    def entry(lat, accuracy):
        url = ("https://tiles.example.test/v1?clientlocation=%s|-0.1278"
               "&clientlocationaccuracy=%s" % (lat, accuracy))
        return {"Url": url, "CleanUrl": url, "ContainerType": "History",
                "EntryId": 41, "ContainerId": 3,
                "ModifiedTime": "2024-06-15 09:00:01 UTC"}

    # TWO fixes: a place holding one is the degenerate case, and the
    # aggregate sentence's plural is exactly what these tests are about.
    fixes = location_loader.position_fixes(
        [entry("51.50741", 12), entry("51.50739", 140)], grouping="11m")
    row = location_loader.places(fixes, grouping="11m")[0]
    row.update(over)
    return row


def fix_row(**over):
    """A single Location FIX (not a place), shaped exactly as
    location_loader.position_fixes builds one. Its `_kind` is the kind of
    the RECORD it came from (K_HISTORY here) -- never a fix-specific kind
    -- see location_loader._shape's own `fix["_kind"]` line."""
    from webcache.shell import location_loader

    url = ("https://tiles.example.test/v1?clientlocation=51.50741|-0.1278"
           "&clientlocationaccuracy=12")
    entry = {"Url": url, "CleanUrl": url, "ContainerType": "History",
             "EntryId": 41, "ContainerId": 3,
             "ModifiedTime": "2024-06-15 09:00:01 UTC"}
    row = location_loader.position_fixes([entry])[0]
    row.update(over)
    return row


ALL_ROWS = [
    ("history", history_row), ("file_access", file_access_row),
    ("carved_struct", carved_struct_row), ("carved_string", carved_string_row),
    ("cookie", cookie_row), ("hsts", hsts_row), ("cert", cert_row),
    ("container", container_row), ("domain", domain_row),
    ("indicator", indicator_row),
]


def _labels(groups):
    return [f.label for g in groups for f in g.fields]


def _by_label(groups, label):
    for g in groups:
        for f in g.fields:
            if f.label == label:
                return f
    raise AssertionError("no field labelled %r in %s"
                         % (label, [g.name for g in groups]))


# --- order --------------------------------------------------------------

@pytest.mark.parametrize("name,builder", ALL_ROWS)
def test_group_order_is_identical_for_every_record_kind(name, builder):
    """An examiner learns the order once. Every kind emits a SUBSEQUENCE of
    the one canonical GROUPS tuple -- WITH ONE DELIBERATE EXCEPTION: a carved row promotes "How it was recovered" to the front (right
    after "Carve quality", if a damaged carve put that there too), because
    where a recovered record came from is the first question about it, not
    the eleventh. Every other kind keeps the one canonical order in full,
    and a carved kind keeps it too once G_HOW is set aside."""
    names = [g.name for g in df.fields_for(builder())]
    assert names, name
    assert len(names) == len(set(names)), names
    carved = name in ("carved_struct", "carved_string")
    rest = [n for n in names if not (carved and n == df.G_HOW)]
    positions = [df.GROUPS.index(n) for n in rest]
    assert positions == sorted(positions), (name, names)
    if carved and df.G_HOW in names:
        ahead = names[:names.index(df.G_HOW)]
        assert set(ahead) <= {df.G_QUALITY}, (name, names)


@pytest.mark.parametrize("name,builder", ALL_ROWS)
def test_other_recovered_values_is_always_last_and_always_present(name, builder):
    """The sweep is what guarantees nothing recovered is hidden, so it is
    not allowed to be conditional."""
    groups = df.fields_for(builder())
    assert groups[-1].name == df.G_OTHER, [g.name for g in groups]


def test_a_carved_record_puts_carve_quality_first():
    groups = df.fields_for(carved_string_row())
    assert groups[0].name == df.G_QUALITY
    assert any("repairable" in f.display_value for f in groups[0].fields)


def test_an_intact_carve_gets_no_quality_banner():
    """The banner means "do not read this as a recorded URL". Painting it
    on an intact carve would make it noise, and noise gets ignored."""
    groups = df.fields_for(carved_struct_row())
    assert groups[0].name != df.G_QUALITY
    # but the health verdict itself is still stated, under recovery.
    assert _by_label(groups, "URL health").display_value == "intact"


def test_a_live_record_has_no_carve_quality_group_at_all():
    assert df.G_QUALITY not in [g.name for g in df.fields_for(history_row())]


# --- the sweep ----------------------------------------------------------

def test_the_sweep_emits_every_key_no_group_claimed():
    """The regression guard for "nothing recovered is ever hidden". A field
    added to the engine appears in the dialog with no UI change at all."""
    row = history_row()
    row["_record"]["SomeFieldNobodyNamed"] = "a recovered value"
    groups = df.fields_for(row)
    other = [g for g in groups if g.name == df.G_OTHER][0]
    field = [f for f in other.fields if f.key == "SomeFieldNobodyNamed"]
    assert field, [f.key for f in other.fields]
    assert field[0].display_value == "a recovered value"


def test_the_sweep_never_emits_a_private_key():
    """_record, _kind, _members and _records are plumbing, not evidence."""
    for _name, builder in ALL_ROWS:
        for g in df.fields_for(builder()):
            for f in g.fields:
                assert not str(f.key).startswith("_"), (f.key, g.name)


def test_the_sweep_never_dumps_raw_bytes_as_a_value():
    """A 379 KB blob rendered as str(bytes) is not a field value; it is a
    denial of service against the person reading it. Blobs are stated in
    the Binary group by size, type and hash instead."""
    for _name, builder in ALL_ROWS:
        for g in df.fields_for(builder()):
            for f in g.fields:
                assert not isinstance(f.value, (bytes, bytearray)), f.label


# --- absence ------------------------------------------------------------

@pytest.mark.parametrize("name,builder", ALL_ROWS)
def test_no_field_ever_has_an_empty_display_value(name, builder):
    """At the layer that decides it. The dialog test asserts the same
    thing on screen; this one asserts it can never get there."""
    for g in df.fields_for(builder()):
        for f in g.fields:
            assert isinstance(f.display_value, str), (name, f.label)
            assert f.display_value.strip(), (name, g.name, f.label)


def test_absence_states_are_distinguishable():
    """Four records, four different sentences behind the four states."""
    live_blank = _by_label(df.fields_for(history_row()), "Search terms")
    assert live_blank.absence == provenance.ABSENCE_EMPTY

    carved = carved_struct_row()
    carved["_record"]["Filename"] = ""
    not_recovered = _by_label(df.fields_for(carved), "Cached file name")
    assert not_recovered.absence == provenance.ABSENCE_NOT_RECOVERED

    string_carve = df.fields_for(carved_string_row())
    unknowable = _by_label(string_carve, "InPrivate")
    assert unknowable.absence == provenance.ABSENCE_NOT_DETERMINABLE

    not_applicable = _by_label(df.fields_for(carved_struct_row()), "Encoding")
    assert not_applicable.absence == provenance.ABSENCE_NOT_APPLICABLE

    seen = {live_blank.absence, not_recovered.absence, unknowable.absence,
            not_applicable.absence}
    assert len(seen) == 4
    sentences = {provenance.absence_reason(a) for a in seen}
    assert len(sentences) == 4


def test_a_zero_offset_renders_as_zero_not_as_absent():
    """Offset 0 is the first byte of a file, Page 0 is a real page and
    AccessCount 0 is a real count. describe_origin already got this right;
    this must match it."""
    groups = df.fields_for(carved_struct_row())
    offset = _by_label(groups, "Byte offset")
    assert offset.absence is None
    assert "0" in offset.display_value
    page = _by_label(groups, "Page")
    assert page.absence is None
    assert page.display_value == "0"


def test_false_is_a_value_not_an_absence():
    groups = df.fields_for(history_row())
    leak = _by_label(groups, "Leak record")
    assert leak.absence is None
    assert leak.display_value == "No"


def test_a_whitespace_only_value_renders_as_itself_not_as_empty():
    """_render() re-decided a value _absence_for had already
    classified as REAL (a string of non-zero length is present, per
    _absence_for's own len()-based rule) by silently stripping it and
    substituting ABSENCE_EMPTY when the stripped text was blank. The cell
    then asserted the database stores nothing where it actually stores
    spaces, while field.absence -- and therefore counts() -- still, and
    correctly, reported this field as present."""
    groups = df.fields_for(history_row(Url="   "))
    field = _by_label(groups, "Raw URL (as stored)")
    assert field.absence is None, "_absence_for already classified this as real"
    assert field.display_value == "   ", field.display_value


def test_a_carved_string_artifact_never_reads_as_not_inprivate():
    """The dialog must not turn provenance.ABSENCE_NOT_DETERMINABLE into
    "No". It is a non-empty string, so a naive bool() reads it as True and
    a naive "or" reads it as a value -- both wrong in opposite ways."""
    field = _by_label(df.fields_for(carved_string_row()), "InPrivate")
    assert field.display_value == provenance.ABSENCE_NOT_DETERMINABLE
    assert field.display_value not in ("No", "Yes")


def test_absence_for_is_a_single_function_with_a_stated_table():
    """One function, so the four states cannot drift apart across the
    dozen places a value is rendered."""
    A = provenance
    # live record: present-but-empty is (empty); absent key is not emitted
    assert df._absence_for(False, "X", True, None) == A.ABSENCE_EMPTY
    assert df._absence_for(False, "X", True, "") == A.ABSENCE_EMPTY
    assert df._absence_for(False, "X", False, None) is df.NOT_EMITTED
    # real values, in every falsy disguise
    assert df._absence_for(False, "X", True, 0) is None
    assert df._absence_for(False, "X", True, False) is None
    assert df._absence_for(True, "X", True, 0) is None
    # carved: both "present and empty" and "key missing" are not-recovered
    assert df._absence_for(True, "X", True, None) == A.ABSENCE_NOT_RECOVERED
    assert df._absence_for(True, "X", False, None) == A.ABSENCE_NOT_RECOVERED
    # the sentinel survives whatever else is true
    assert (df._absence_for(True, "X", True, A.ABSENCE_NOT_DETERMINABLE)
            == A.ABSENCE_NOT_DETERMINABLE)


# --- provenance badges --------------------------------------------------

def test_every_declared_field_key_is_either_catalogued_or_explicitly_none():
    """basis_of() defaults to DERIVED for an unknown key, so a typo in a
    field= would paint a confident DER badge on an uncatalogued field.
    field=None means "not in the catalogue" and paints NO badge, which is
    the honest degradation."""
    bad = []
    for _name, builder in ALL_ROWS:
        for g in df.fields_for(builder()):
            for f in g.fields:
                if f.field is not None and f.field not in evidence_model.FIELD_PROVENANCE:
                    bad.append((g.name, f.label, f.field))
    assert not bad, bad


def test_an_uncatalogued_field_gets_no_badge_rather_than_a_guessed_one():
    row = history_row()
    row["_record"]["UrlHealth"] = "intact"
    field = _by_label(df.fields_for(row), "URL health")
    assert field.field is None


def test_a_catalogued_field_carries_its_real_key_not_its_label():
    """Provenance looked up by LABEL would silently find nothing for
    every prose label. The key is explicit here."""
    field = _by_label(df.fields_for(history_row()), "Clean URL")
    assert field.field == "CleanUrl"
    assert evidence_model.basis_of(field.field) == evidence_model.DERIVED


# --- paths ---------------------------------------------------------

def test_a_path_field_is_never_a_link():
    """Copy, never Open. Every value naming a location on the EXAMINED
    machine is kind="path" and carries no click target of any kind."""
    groups = df.fields_for(file_access_row())
    machine = [g for g in groups if g.name == df.G_MACHINE]
    assert machine, [g.name for g in groups]
    assert machine[0].fields
    for f in machine[0].fields:
        assert f.kind == "path", f.label
        assert f.target is None, f.label


def test_the_cached_file_path_reaches_the_dialog_at_all():
    """Resolved for 554/610 entries on one exhibit and displayed nowhere
    before this."""
    field = _by_label(df.fields_for(file_access_row()), "Cached file path")
    assert field.display_value.endswith("report[1].docx")
    assert field.kind == "path"


# --- timestamps ---------------------------------------------------------

def test_a_timestamp_shows_its_decoded_form_and_its_raw_filetime_together():
    """The pretty form and the number an examiner types into another tool
    must never be separated by a scroll."""
    field = _by_label(df.fields_for(file_access_row()), "Modified (UTC)")
    assert "2024-03-11 09:14:02" in field.display_value
    assert "133544180420000000" in field.display_value
    assert field.raw_value == 133544180420000000


def test_the_raw_filetime_is_not_also_emitted_as_its_own_row():
    """One field row, not two -- otherwise every record grows a second,
    duplicate time section made of bare integers."""
    labels = _labels(df.fields_for(file_access_row()))
    assert not [l for l in labels if l.endswith("_raw")]


def test_the_timestamp_basis_is_the_sub_line_under_the_time_it_explains():
    field = _by_label(df.fields_for(history_row()), "Last visit (UTC)")
    assert "ModifiedTime (visit written)" in field.note


def test_the_visit_count_says_which_counter_it_came_from():
    """The label names the counter; cache touches are never offered under
    it (test_visits_and_cache_touches_never_merged.py)."""
    field = _by_label(df.fields_for(history_row()), "Visits (property store)")
    _short, tooltip = df.basis_badge(field.field)
    assert "property ID 6" in tooltip


# --- flattening: stated, never joined into one opaque string ------------

def test_sps_properties_flatten_one_row_per_id_and_never_guess_a_name():
    """Property ids 9, 13, 23, 28, 32 and 33 are decoded, stored, and
    displayed nowhere in the application. KNOWN_HISTORY_PROPS names only 6
    and 24, so every other id must render with NO invented name."""
    groups = df.fields_for(history_row())
    sps = [f for g in groups for f in g.fields
           if f.label.startswith("SPS property")]
    ids = sorted(int(f.label.split()[2]) for f in sps)
    assert ids == [6, 9, 24], ids
    named = _by_label(groups, [f.label for f in sps if " 6" in f.label][0])
    assert "VisitCount" in named.label
    unnamed = [f for f in sps if f.label.startswith("SPS property 9")][0]
    assert "not documented" in unnamed.note.lower()
    for token in ("VisitCount", "LastVisit", "PageTitle"):
        assert token not in unnamed.label, unnamed.label


def test_secure_directory_names_are_one_row_each_with_their_index():
    groups = df.fields_for(container_row())
    subs = [f for g in groups for f in g.fields
            if f.label.startswith("Cache subdirectory")]
    assert [f.label for f in subs] == ["Cache subdirectory 1 of 3",
                                       "Cache subdirectory 2 of 3",
                                       "Cache subdirectory 3 of 3"]
    assert [f.display_value for f in subs] == ["AAA", "BBB", "CCC"]


def test_fragments_are_one_row_each_naming_their_own_offset():
    """Every discarded partial reading, kept precisely so nothing becomes
    unverifiable -- and then surfaced nowhere until now."""
    groups = df.fields_for(carved_string_row())
    frags = [f for g in groups for f in g.fields
             if f.label.startswith("Fragment")]
    assert len(frags) == 2
    assert "0x0001A4F0" in frags[0].label
    assert frags[0].display_value == "ttp://example"


def test_a_container_whose_record_count_is_not_determinable_says_so():
    row = container_row(Records=provenance.CONTAINER_NOT_DETERMINABLE)
    field = _by_label(df.fields_for(row), "Records")
    assert field.absence == provenance.ABSENCE_NOT_DETERMINABLE
    assert provenance.absence_reason(field.absence)


# --- binary -------------------------------------------------------------

def test_a_blob_is_stated_by_size_type_and_hash_not_by_its_bytes():
    groups = df.fields_for(cert_row())
    binary = [g for g in groups if g.name == df.G_BINARY]
    assert binary, [g.name for g in groups]
    field = binary[0].fields[0]
    assert "202" in field.display_value          # size
    assert "SHA-256" in field.display_value      # this tool's hash
    assert field.blob_key == "Blob_raw"


def test_a_record_with_no_blob_has_no_binary_group():
    """No empty box where nothing applies."""
    assert df.G_BINARY not in [g.name for g in df.fields_for(cookie_row())]


def test_the_blob_hash_is_labelled_as_this_tools_hash_not_a_stored_value():
    """Nothing establishes a relationship between this and a cert
    record's stored Thumbprint, so no such relationship is implied."""
    field = [g for g in df.fields_for(cert_row())
             if g.name == df.G_BINARY][0].fields[0]
    assert "SHA-256 computed by this tool" in (field.note or "")


# --- aggregates ---------------------------------------------------------

@pytest.mark.parametrize("builder",
                         [domain_row, indicator_row, period_row, place_row])
def test_an_aggregate_says_it_is_an_aggregate_before_it_shows_a_number(builder):
    groups = df.fields_for(builder())
    assert groups[0].name == df.G_AGGREGATE
    text = groups[0].fields[0].display_value
    assert "not itself a record" in text
    assert "2" in text or "1" in text


def test_an_aggregate_lists_its_members_as_openable_rows():
    """A summary that copies instead of opening reads as "that is all there
    is". Each member row carries the record it opens."""
    groups = df.fields_for(domain_row())
    records = [g for g in groups if g.name == df.G_RECORDS]
    assert records, [g.name for g in groups]
    assert len(records[0].fields) == 2
    for f in records[0].fields:
        assert isinstance(f.target, dict)
        assert f.display_value.strip()


def test_member_rows_are_capped_so_a_huge_aggregate_cannot_block_the_gui():
    """_members() emitted one DetailField per aggregate member
    with no cap, calling row_for_record() and materialising three
    QTableWidgetItems each -- opening a Domains or Indicators record on a
    large exhibit blocked the GUI thread. Capped here, not made lazy: a
    QTableWidget row list is not virtualised the way RecordsTable's own
    grid rows are, so a bound on how many are BUILT is what actually stops
    the block; a truncation row states the real total rather than hiding
    it, since G_AGGREGATE's own statement already promises that count."""
    members = [{"CleanUrl": "https://example.test/%d" % i} for i in range(900)]
    row = domain_row(_members=members, Records=900)
    groups = df.fields_for(row)
    records_group = [g for g in groups if g.name == df.G_RECORDS][0]
    openable = [f for f in records_group.fields if f.target is not None]
    assert len(openable) <= df._MAX_MEMBER_ROWS
    assert len(openable) < 900, "an unbounded aggregate must not be fully built"
    # The truncation is STATED, never silent -- "nothing recovered is ever
    # hidden" (this module's own first guarantee) applies here too: the
    # full count must still be findable on this same surface.
    assert any("900" in f.display_value for f in records_group.fields)


def test_a_record_is_never_given_an_aggregate_group():
    for name in ("history", "carved_struct", "cookie"):
        builder = dict(ALL_ROWS)[name]
        names = [g.name for g in df.fields_for(builder())]
        assert df.G_AGGREGATE not in names, name
        assert df.G_RECORDS not in names, name


# --- a position fix -------------------------------------------------------

def test_a_fix_gets_its_own_curated_fields_not_the_sweep():
    """A fix's `_kind` is K_HISTORY/K_CARVED_* (the kind of the
    RECORD it came from -- never a fix-specific kind), so `_BY_KIND` had
    an entry for K_PLACE (the aggregate) but nothing keyed to any of the
    kinds a fix's own `_kind` actually is. Its fifteen curated
    Location-specific facts fell through to "Other recovered values"
    under their raw key names instead of the labels LocationView's own
    grid gives them."""
    groups = df.fields_for(fix_row())
    labels = _labels(groups)
    for label in ("Fix time — device said (UTC)", "Fix time read as",
                  "Cache wrote (UTC)", "Times differ by",
                  "Latitude, Longitude (as stored)", "Place (as grouped)",
                  "Accuracy claimed (m)", "Reported source",
                  "What this fix is worth"):
        assert label in labels, (label, labels)
    other = [g for g in groups if g.name == df.G_OTHER]
    other_labels = [f.label for g in other for f in g.fields]
    for stray in ("Coords", "Place", "Assessment", "FixTimeFormat"):
        assert stray not in other_labels, (
            "a curated field must not ALSO be swept under its raw key",
            stray, other_labels)


def test_a_fixs_cache_wrote_time_cites_the_column_it_was_read_from():
    """The grid cites field="ModifiedTime" for RecordTimeUtc (see
    views/location.py's _fix_columns) so the basis badge and the detail
    dialog agree on where the value came from."""
    field = _by_label(df.fields_for(fix_row()), "Cache wrote (UTC)")
    assert field.field == "ModifiedTime"


# --- counts, identity, flatten ------------------------------------------

def test_counts_report_the_total_and_how_many_state_an_absence():
    groups = df.fields_for(history_row())
    total, absent = df.counts(groups)
    assert total == len(df.flatten(groups))
    assert absent == len([f for f in df.flatten(groups) if f.absence])
    assert total > absent > 0


def test_identity_of_names_the_record_without_inventing_one():
    assert df.identity_of(history_row()) == "https://example.test/a"
    assert df.identity_of(cookie_row()) == "sid — example.test"
    assert df.identity_of(cert_row()) == "example.test:443"
    assert df.identity_of(container_row()) == "History"
    assert df.identity_of(domain_row()) == "example.test"
    # A record with nothing nameable gets a stated fallback, never "".
    assert df.identity_of({"_kind": K_HISTORY, "_record": {}}).strip()


def test_flatten_preserves_group_order():
    groups = df.fields_for(history_row())
    assert [f.label for f in df.flatten(groups)] == _labels(groups)


# --- robustness ---------------------------------------------------------

def test_a_row_with_no_record_at_all_still_renders():
    """Carved data is damaged data and a hand-built row is a real caller.
    fields_for must degrade, never raise."""
    for row in ({}, {"_kind": K_HISTORY}, {"_record": None},
                {"_kind": "not-a-kind", "_record": {"X": 1}}):
        groups = df.fields_for(row)
        assert groups[-1].name == df.G_OTHER
        for f in df.flatten(groups):
            assert f.display_value.strip()


# --- the origin line ----------------------------------------------------
#
# Found by looking at a real exhibit, not by the suite: the dialog headed a
# Domains aggregate with provenance.describe_origin()'s answer, which for a
# row carrying ContainerType is "Live record in Content". That is a false
# statement about a row summarising 345 records, printed ABOVE the line
# that correctly says it is not a record.

def test_an_aggregates_origin_line_never_calls_it_a_live_record():
    line = df.origin_line(domain_row())
    assert not line.startswith("Live record"), line
    assert "summary of" in line.lower() and "not a single record" in line
    assert "2" in line


def test_an_indicators_origin_line_says_the_same_thing():
    line = df.origin_line(indicator_row())
    assert not line.startswith("Live record"), line
    assert "summary of" in line.lower() and "not a single record" in line


@pytest.mark.parametrize("builder", [history_row, cookie_row, cert_row,
                                     carved_struct_row, carved_string_row])
def test_a_real_record_keeps_describe_origins_exact_wording(builder):
    """One sentence for where a record came from, everywhere. The dialog
    must not grow a second, differently-worded provenance line beside the
    one Explain and every export already use."""
    row = builder()
    assert df.origin_line(row) == provenance.describe_origin(row)


# --- row_for_record: carved-ness without an Origin key to read ----------
#
# row_for_record decided carved-ness from entry.get("Origin"), but
# the ENGINE never writes an Origin key onto a raw record at all -- only
# recovery_loader.py's own row builders (carved_history_rows,
# deleted_records_rows, ...) add one, on the SHAPED rows they hand back.
# domain_row()/indicator_row()'s own _members/_records here are built from
# carved_struct_row()["_record"] and carved_string_row()["_record"] --
# the RAW engine dicts, exactly as main_window.py's real carved_entries
# union (engine.structured_records + engine.all_artifacts()) is: never
# deleted_records_rows()'s shaped output. Confirmed by the reviewer on a
# real exhibit: a transaction-log string carve reached through an
# Indicators member row opened the dialog headed "Live record", _kind
# read back as K_HISTORY.

def test_row_for_record_never_reads_a_raw_structured_carve_as_live():
    entry = carved_struct_row()["_record"]
    assert "Origin" not in entry, "the fixture must mirror a raw engine dict"
    assert entry.get("RecoverySource"), "the engine's own carved-only marker"
    row = df.row_for_record(entry)
    assert row["_kind"] == K_CARVED_STRUCT
    assert not df.origin_line(row).startswith("Live record"), df.origin_line(row)


def test_row_for_record_never_reads_a_raw_string_carve_as_live():
    """The reviewer's exact repro: an Indicators aggregate member built
    from a raw transaction-log string carve."""
    entry = carved_string_row()["_record"]
    assert "Origin" not in entry
    assert entry.get("RecoverySource")
    row = df.row_for_record(entry)
    assert not df.origin_line(row).startswith("Live record"), df.origin_line(row)


def test_row_for_record_still_reads_a_genuinely_live_entry_as_live():
    """The fallback must not turn EVERY entry carved -- a live record's own
    raw dict carries no RecoverySource key at all, because it was never
    carved."""
    entry = history_row()["_record"]
    assert "Origin" not in entry
    assert not entry.get("RecoverySource")
    row = df.row_for_record(entry)
    assert row["_kind"] == K_HISTORY
    assert df.origin_line(row).startswith("Live record")


def test_a_domains_aggregate_member_reached_through_a_carved_struct_never_reads_live():
    """The end-to-end shape the reviewer actually opened: domain_row()'s
    own _members, exactly as main_window.py's real carved_entries union
    populates it."""
    row = domain_row()
    member = [m for m in row["_members"] if m.get("RecoverySource")][0]
    target = df.row_for_record(member)
    assert not df.origin_line(target).startswith("Live record")


# --- HTTP headers in the detail dialog (Unit 2) --------------------------
#
# Three defects an earlier version shipped and never named, all of them
# in the same six lines of _flatten_headers:
#
#   * the header rows were emitted in sorted(headers) order, throwing away
#     the wire order the decoded dict's own insertion order preserved --
#     and header order can itself be evidence;
#   * the synthetic status-line key rendered as a header literally named
#     "_status_line", which is the tool showing its own plumbing in a
#     document that leaves the building;
#   * a repeated name (Set-Cookie, most often) was collapsed by the dict
#     with nothing anywhere saying so.

HEADER_BLOB = (b"HTTP/1.1 200 OK\r\n"
               b"Server: nginx\r\n"
               b"Content-Type: text/html\r\n"
               b"Set-Cookie: a=1\r\n"
               b"Set-Cookie: b=2\r\n"
               b"X-Forwarded-For: 203.0.113.7\r\n\r\n")


def headers_row(**over):
    """A record carrying real HTTP headers, shaped the way ese_parser
    produces one -- decoded dict AND the raw blob it came from."""
    from webcache.engine import ese_parser
    entry = history_row()["_record"].copy()
    entry.update({
        "BlobClass": "http",
        "ResponseHeaders_raw": HEADER_BLOB,
        "RequestHeaders_raw": b"Accept: */*\r\n\r\n",
        "ResponseHeaders": ese_parser.decode_content_headers(HEADER_BLOB),
        "RequestHeaders": ese_parser.decode_content_headers(
            b"Accept: */*\r\n\r\n"),
    })
    entry.pop("SPS_Properties", None)
    row = {"CleanUrl": entry["CleanUrl"], "Origin": "Live record",
           "Source": "", "_record": entry, "_kind": K_HISTORY}
    row.update(over)
    return row


def _header_fields(row=None):
    groups = df.fields_for(row or headers_row())
    return [f for g in groups for f in g.fields
            if str(f.key) in ("ResponseHeaders", "RequestHeaders")]


def test_header_rows_come_back_in_wire_order_not_alphabetical():
    """sorted(headers) threw away the one thing a plain dict still had."""
    labels = [f.label for f in _header_fields()
              if f.key == "ResponseHeaders"]
    assert labels == ["Status line",
                      "Response header: Server",
                      "Response header: Content-Type",
                      "Response header: Set-Cookie",
                      "Response header: X-Forwarded-For"], labels


def test_the_status_line_comes_first_and_is_named_in_words():
    fields = [f for f in _header_fields() if f.key == "ResponseHeaders"]
    assert fields[0].label == "Status line"
    assert fields[0].value == "HTTP/1.1 200 OK"


def test_no_field_leaks_the_synthetic_underscore_key_as_a_header_name():
    for f in _header_fields():
        assert "_status_line" not in f.label, f.label


def test_a_client_ip_header_carries_its_limit_as_a_note():
    """Colour alone is not a finding. The amber styling stays as
    reinforcement of a fact that is now also written down."""
    from webcache.shell.headers_loader import CLIENT_IP_NOTE
    field = [f for f in _header_fields()
             if f.label.endswith("X-Forwarded-For")][0]
    assert CLIENT_IP_NOTE in field.note


def test_an_ordinary_header_carries_no_such_note():
    field = [f for f in _header_fields() if f.label.endswith("Server")][0]
    assert "client IP" not in field.note


def test_the_collapse_a_repeated_name_caused_is_stated_in_words():
    """The decoded dict kept one Set-Cookie. Nothing anywhere said so
    until this field existed."""
    groups = df.fields_for(headers_row())
    text = " ".join(f.display_value for g in groups for f in g.fields)
    assert "overwritten by a later line with the same name" in text


def test_the_statement_names_where_every_value_still_is():
    groups = df.fields_for(headers_row())
    said = [f.display_value for g in groups for f in g.fields
            if "overwritten" in f.display_value][0]
    assert "pair export" in said


def test_a_record_with_no_repeated_header_says_nothing_about_repeats():
    from webcache.engine import ese_parser
    blob = b"HTTP/1.1 200 OK\r\nServer: nginx\r\n\r\n"
    row = headers_row()
    row["_record"]["ResponseHeaders_raw"] = blob
    row["_record"]["ResponseHeaders"] = ese_parser.decode_content_headers(blob)
    row["_record"]["RequestHeaders_raw"] = None
    row["_record"]["RequestHeaders"] = {}
    groups = df.fields_for(row)
    text = " ".join(f.display_value for g in groups for f in g.fields)
    assert "overwritten by a later line" not in text


def test_the_request_side_keeps_its_own_prefix():
    labels = [f.label for f in _header_fields() if f.key == "RequestHeaders"]
    assert labels == ["Request header: Accept"]


def test_a_record_with_no_headers_at_all_emits_none_of_this():
    assert _header_fields(history_row()) == []
    groups = df.fields_for(history_row())
    text = " ".join(f.display_value for g in groups for f in g.fields)
    assert "overwritten by a later line" not in text


# --- the Timeline period aggregate ---------------------------------------

def test_a_period_row_is_named_by_its_period_not_by_a_fabricated_title():
    """Nothing on a period row is a URL, a domain or a name, so the
    generic identity walk finds nothing and the dialog would open with
    "(this record carries no value that names it)" over a row that has a
    perfectly good name."""
    assert df.identity_of(period_row()) == "2024-06-15"


def test_a_period_row_renders_its_declared_fields_not_a_bare_sweep():
    labels = [f.label for g in df.fields_for(period_row()) for f in g.fields]
    for expected in ("Period", "Records in this period", "Record types"):
        assert expected in labels, labels


def test_the_record_types_tally_is_grouped_with_what_happened():
    """Looked at on screen: "Record types" sat under "Where it lives in
    the database", which is where a container id belongs. A tally of what
    KINDS of record fell in this bucket is a statement about what the
    period holds, not about where anything is stored."""
    groups = {g.name: [f.label for f in g.fields]
              for g in df.fields_for(period_row())}
    assert "Record types" in groups.get(df.G_SAYS, [])


def test_a_period_rows_origin_line_never_calls_it_a_live_record():
    line = df.origin_line(period_row())
    assert "Summary of" in line and "not a single record" in line
    assert "not a single record" in line


def test_a_period_row_lists_its_members_as_openable_rows():
    groups = df.fields_for(period_row())
    records = [g for g in groups if g.name == df.G_RECORDS]
    assert records, [g.name for g in groups]
    assert len(records[0].fields) == 2
    for f in records[0].fields:
        assert isinstance(f.target, dict)


def test_a_period_row_with_no_record_key_still_renders():
    """`_record` is deliberately ABSENT from a period row -- the eleventh
    key crosses a dict size step. Every reader has to tolerate that."""
    row = period_row()
    assert "_record" not in row
    assert df.fields_for(row)


# --- the Location place aggregate ----------------------------------------

def test_a_place_row_is_named_by_its_coordinates():
    """Nothing on a place row is a URL, a title or a name. Without its own
    branch the dialog opens with "(this record carries no value that names
    it)" over a row whose whole identity is where it is."""
    assert df.identity_of(place_row()) == "51.5074, -0.1278"


def test_a_place_row_renders_its_declared_fields_not_a_bare_sweep():
    labels = [f.label for g in df.fields_for(place_row()) for f in g.fields]
    for expected in ("Latitude, Longitude (as grouped)",
                     "Grouped by",
                     "Position fixes at this place",
                     "Accuracy claimed across these fixes",
                     "Reported source"):
        assert expected in labels, labels


def test_a_place_says_it_summarises_fixes_not_records():
    """A place groups FIXES, and two fixes can come out of one record -- a
    single URL can report a position in more than one parameter. Calling
    them records would be a count of the wrong thing, in the one sentence
    whose whole job is stating what the row is."""
    groups = df.fields_for(place_row())
    assert groups[0].name == df.G_AGGREGATE
    text = groups[0].fields[0].display_value
    assert "position fixes" in text
    assert "not itself a record" in text


def test_a_place_rows_origin_line_never_calls_it_a_live_record():
    line = df.origin_line(place_row())
    assert "Summary of" in line and "not a single record" in line
    assert "not a single record" in line


def test_a_place_lists_its_fixes_as_openable_rows_shaped_as_the_grid_shaped_them():
    """A fix reached through a place must open exactly as the same fix
    reached through the Position fixes grid -- same _kind, same _record.
    Re-wrapping an already-shaped row would put the FIX in the _record
    slot and lose the record behind it."""
    row = place_row()
    groups = df.fields_for(row)
    records = [g for g in groups if g.name == df.G_RECORDS]
    assert records, [g.name for g in groups]
    assert len(records[0].fields) == 2
    target = records[0].fields[0].target
    assert target is row["_members"][0]
    assert target["_record"] is row["_members"][0]["_record"]


def test_an_aggregate_of_raw_engine_dicts_is_still_wrapped():
    """The guard above must be a no-op for every aggregate that existed
    before it: Domains, Indicators and Timeline members are RAW engine
    dicts with no _kind of their own, and those still get a row built
    around them."""
    row = domain_row()
    groups = df.fields_for(row)
    records = [g for g in groups if g.name == df.G_RECORDS][0]
    target = records.fields[0].target
    assert target is not row["_members"][0]
    assert target["_record"] is row["_members"][0]


# --- a row that is NOT a parsed record, and not an aggregate either -------
#
# K_TABLE_ROW is one row of a raw ESE table matched by a cross-table
# search. It is not in AGGREGATES (it is one row, not a population), so
# the aggregate branch cannot answer for it -- and without a branch of
# its own, describe_origin's `row.get("Origin") or "Live record"` default
# asserts "Live record" over an MSysObjects catalogue row, which is a
# claim about a record that is not one.

def _table_row():
    from webcache.shell import record_kinds
    return {"Table": "MSysObjects", "Row": 12,
            "MatchedColumns": "Name", "_kind": record_kinds.K_TABLE_ROW}


def test_a_searched_table_rows_origin_line_never_calls_it_a_live_record():
    line = df.origin_line(_table_row())
    assert not line.startswith("Live record"), line


def test_a_searched_table_row_says_what_it_actually_is():
    from webcache.shell import record_kinds
    line = df.origin_line(_table_row())
    assert line == record_kinds.ORIGIN_SENTENCE[record_kinds.K_TABLE_ROW]
    assert "raw ESE table" in line
    assert "Table" in line and "Row" in line, (
        "the sentence must name the two columns that say WHICH row")


def test_a_table_row_is_not_an_aggregate():
    """One row, not a population -- so "Aggregate over N records" would
    be as wrong as "Live record"."""
    from webcache.shell import record_kinds
    assert record_kinds.K_TABLE_ROW in record_kinds.ALL
    assert record_kinds.K_TABLE_ROW not in record_kinds.AGGREGATES


def test_the_origin_sentence_branch_runs_before_the_aggregate_branch():
    """A kind with a declared sentence gets it, whatever else it is --
    Unit 2 puts two non-record, non-population kinds through the same
    door and "Aggregate over 0 records" for a silence is nonsense."""
    from webcache.shell import record_kinds
    import inspect
    source = inspect.getsource(df.origin_line)
    assert source.index("ORIGIN_SENTENCE") < source.index("AGGREGATES"), (
        "the declared-sentence branch must be reached first")


def test_an_ordinary_record_is_untouched_by_the_new_branch():
    """No kind that existed before this has an ORIGIN_SENTENCE entry, so
    every existing origin line is byte-for-byte what it was. Findings
    (K_TIME_VOID, K_REDIRECT_HOP) is a legitimate, later addition to the
    same set -- pinned by name here rather than left open-ended, so a
    THIRD one still has to justify itself the same way these two did."""
    from webcache.shell import record_kinds
    row = {"_kind": K_HISTORY, "ContainerType": "History"}
    assert df.origin_line(row) == provenance.describe_origin(row)
    assert set(record_kinds.ORIGIN_SENTENCE) == {
        record_kinds.K_TABLE_ROW, record_kinds.K_TIME_VOID,
        record_kinds.K_REDIRECT_HOP}


def test_a_blob_summary_states_the_whole_sha256():
    """The dialog's bytes summary showed the first 16 hex
    digits and an ellipsis; the hex viewer shows all 64. A digest is only
    checkable whole, and the two surfaces must agree."""
    import hashlib
    data = b"synthetic blob bytes" * 7
    summary = df._blob_summary("Blob", data)
    digest = hashlib.sha256(data).hexdigest()
    assert digest in summary, summary
    assert "…" not in summary, summary


def test_every_member_is_listed_on_request():
    """The first rows are built at once; the rest are one action away, not
    left out: fields_for(all_members=True) builds every member."""
    members = [{"CleanUrl": "https://example.test/%d" % i} for i in range(900)]
    row = domain_row(_members=members, Records=900)
    first = [g for g in df.fields_for(row) if g.name == df.G_RECORDS][0]
    more = [f for f in first.fields if f.key == "aggregate:member_overflow"]
    assert more and "Show all 900 records" in more[0].display_value
    every = [g for g in df.fields_for(row, all_members=True)
             if g.name == df.G_RECORDS][0]
    assert len([f for f in every.fields if f.target is not None]) == 900
    assert not [f for f in every.fields
                if f.key == "aggregate:member_overflow"]


def test_a_container_summary_is_named_by_its_container():
    """An EntryId-gap row carries no URL or name; its identity is the
    container it summarises, not "(this record carries no value...)"."""
    row = {"ContainerId": 7, "ContainerName": "BackgroundTransferApi",
           "Live": 16, "Missing": 2753, "_record": None}
    assert df.identity_of(row) == "Container 7 \u00b7 BackgroundTransferApi"
