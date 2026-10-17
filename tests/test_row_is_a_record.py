"""A row is a record: one pointer to the engine dict, not a copy of it.

Every row builder in webcache/shell/ produces a small dict shaped for one
view's declared columns, and everything the engine knows that no column
declares -- 41 fields on a History record alone -- stops there. Nothing
downstream can reach it, which is why an examiner can see that a URL was
visited but not the cached file it produced, the property store it came
with, or the headers it was served with.

THE RULE THIS FILE PINS. The fix is ONE key, `_record`, holding the engine
dict BY REFERENCE, plus the handful of values the row builder itself
decided that the engine dict does not contain. Never a copy of the engine's
fields into the row.

WHY IT MUST BE A REFERENCE, measured on this interpreter (CPython 3.14.4):
sys.getsizeof for a dict steps at 1-5 -> 184 B, 6-10 -> 272 B, 11-21 ->
464 B, 22-42 -> 832 B, 43-85 -> 1584 B. Copying all 55 engine fields into
a History row lands it in the 43-85 bucket -- 1584 B against 464 B, which
is +107 MB at 100,000 rows, to duplicate values MainWindow._parser already
holds for the whole session. Adding five keys to an 11-key row costs
exactly nothing: the table does not grow again until the 22nd key.

So the budget rule this file enforces is not "keep rows small" but "keep
each row inside the size bucket it is already in". test_row_key_count_
stays_inside_its_size_bucket fails loudly the day someone adds the key
that crosses a boundary -- at which point the field belongs on `_record`,
which costs nothing, rather than on the row.

WHY THE `_`-PREFIXED KEYS ARE INVISIBLE, verified against the code rather
than assumed: RecordFilter.set_rows builds its search haystack from the
DECLARED COLUMNS only (record_filter.py), RecordTableModel.data reads
row.get(col.key) only, and _copy_row/_copy_column/copy_selection_as_tsv
all walk model.columnCount(). An added key cannot leak into a filter, a
sort, a copy or an export.
"""
import sys

import pytest

from webcache.engine import forensic_engine
from webcache.shell import evidence_loader, record_kinds

#: A real-looking FILETIME: 2024-03-11 09:14:02 UTC.
FT = 133546220420000000
#: The FILETIME sentinel IE stores for an HSTS pin that never expires.
NEVER = 0x7FFFFFFFFFFFFFFF

#: A response-headers blob shared by every entry that has one, so an
#: identity assertion below proves the row points at the SAME bytes
#: rather than at an equal copy.
BLOB = b"\x01\x00\x00\x00" + b"HTTP/1.1 200 OK\r\nServer: test\r\n\r\n" * 4


def _history_entry(**overrides):
    entry = {
        "ContainerType": "History",
        "ContainerId": 3,
        "ContainerName": "History",
        "EntryId": 11,
        "Url": "Visited: user@https://example.test/a",
        "CleanUrl": "https://example.test/a",
        "SPS_PageTitle": "Example",
        "ModifiedTime_raw": FT,
        "AccessedTime_raw": 0,
        "CreationTime_raw": 0,
        "SPS_LastVisitLocal_raw": None,
        "SPS_VisitCount": 3,
        "AccessCount": 9,
        "IsInPrivate": False,
        "SearchTerms": "",
        "IsLocalFile": False,
        "ResponseHeaders_raw": BLOB,
        "CachedFilePath": r"C:\Users\x\INetCache\IE\ABCD1234\a[1].htm",
        "Flags": 0,
        "SPS_Properties": {6: 3, 13: 1, 24: FT},
    }
    entry.update(overrides)
    return entry


def _file_entry(**overrides):
    entry = _history_entry(
        IsLocalFile=True, CleanUrl="file:///C:/Users/x/report.docx",
        Url="file:///C:/Users/x/report.docx", FileSize=4096,
        Filename="report.docx", FileExtension=".docx")
    entry.update(overrides)
    return entry


class _StubParser:
    """Only the attributes each builder actually reads, so nothing here
    needs a real WebCacheParser or a real database (see the existing
    tests/test_evidence_loader.py for the same contract)."""

    def __init__(self, **attrs):
        self.all_entries = []
        self.cookie_entries = []
        self.hsts_entries = []
        self.cert_entries = []
        self.containers_meta = []
        for name, value in attrs.items():
            setattr(self, name, value)

    def get_container_type(self, cid):
        return "History" if cid == 3 else "Content"


# --- the builders, and the engine object each row must point back at ------

def _cookie_entry():
    return {"Domain": "example.test", "RDomain": "tset.elpmaxe",
            "Name": "sid", "Value": "abc", "Path": "/", "Flags": 0x1,
            "IsSecure": True, "Expires_raw": FT, "LastModified_raw": FT,
            "EntryId": 2, "Table": "CookieEntryEx_1", "PartitionId": "p1"}


def _cert_entry():
    return {"HostPort": "example.test:443", "IsCertificate": True,
            "Thumbprint": "aa" * 20, "BlobSize": len(BLOB),
            "ModifiedTime_raw": FT, "Blob_raw": BLOB}


def _container_meta():
    return {"ContainerId": 3, "Name": "History", "Directory": "",
            "PartitionId": "", "Flags": 0, "Size": 4096, "Limit": 0,
            "LastScavengeTime": "", "LastAccessTime": "2024-03-11 09:14:02 UTC",
            "LastScavengeTime_raw": 0, "LastAccessTime_raw": FT,
            "EntryMaxAge": 0, "TableName": "Container_3", "RecordCount": 46,
            "HasTable": True, "SecureDirectoryNames": ["ABCD1234"]}


def _hsts_pin():
    return {"Domain": "example.test", "LastTimeUsed": "", "LastTimeUsed_raw": FT,
            "Expires": "2024-03-11 09:14:02 UTC", "Expires_raw": FT,
            "IncludeSubdomains": True, "Table": "HstsEntryEx_1",
            "PartitionId": "p1", "EntryId": 7}


#: (builder name, callable(parser) -> rows, parser factory, the engine
#: object row 0 must point back at, the row's declared key ceiling).
#:
#: The ceiling is the top of the dict size bucket the row is already in,
#: NOT a wish: 10 keys is the top of the 272 B bucket, 21 the top of the
#: 464 B bucket, 5 the top of the 184 B bucket. Crossing one is what this
#: file is here to catch.
def _cases():
    hist = _history_entry()
    fa = _file_entry()
    dl = _history_entry(ContainerType="Downloads")
    cookie = _cookie_entry()
    cert = _cert_entry()
    meta = _container_meta()
    pin = _hsts_pin()
    return [
        ("history", evidence_loader.history_rows_from_parser,
         _StubParser(all_entries=[hist]), hist, 21),
        ("file_access", evidence_loader.file_access_rows_from_parser,
         _StubParser(all_entries=[fa]), fa, 21),
        ("downloads", evidence_loader.downloads_rows_from_parser,
         _StubParser(all_entries=[dl]), dl, 10),
        ("cookies", evidence_loader.cookie_rows_from_parser,
         _StubParser(cookie_entries=[cookie]), cookie, 10),
        ("hsts", evidence_loader.hsts_rows_from_parser,
         _StubParser(hsts_entries=[pin], all_entries=[]), pin, 10),
        ("certs", evidence_loader.cert_rows_from_parser,
         _StubParser(cert_entries=[cert]), cert, 10),
        ("containers", evidence_loader.container_rows_from_parser,
         _StubParser(containers_meta=[meta]), meta, 21),
    ]


CASES = _cases()
IDS = [c[0] for c in CASES]


@pytest.mark.parametrize("name,builder,parser,engine_obj,ceiling", CASES,
                         ids=IDS)
def test_every_row_carries_a_reference_to_its_engine_record(
        name, builder, parser, engine_obj, ceiling):
    """`is`, not `==`. Equality would pass for a copy, and a copy is the
    one thing this design forbids: it doubles the memory of every record
    on screen and lets the row and the record drift out of agreement."""
    rows = builder(parser)
    assert rows, "%s produced no row to check" % name
    assert rows[0]["_record"] is engine_obj, (
        "%s must carry the engine dict itself, by reference" % name)


@pytest.mark.parametrize("name,builder,parser,engine_obj,ceiling", CASES,
                         ids=IDS)
def test_every_row_names_its_kind_with_an_interned_constant(
        name, builder, parser, engine_obj, ceiling):
    """`is`, again, and for a measurable reason: a fresh str per row is a
    fresh allocation per row. A module constant is one object shared by
    every row in the set."""
    rows = builder(parser)
    kind = rows[0]["_kind"]
    assert kind in record_kinds.ALL, "%s: %r is not a declared kind" % (
        name, kind)
    assert any(kind is k for k in record_kinds.ALL), (
        "%s built a new string instead of referencing the module constant"
        % name)


@pytest.mark.parametrize("name,builder,parser,engine_obj,ceiling", CASES,
                         ids=IDS)
def test_row_key_count_stays_inside_its_size_bucket(
        name, builder, parser, engine_obj, ceiling):
    """The regression guard for the memory budget.

    Both halves matter. The key count is the readable rule; getsizeof is
    the one that actually measures what the rule is about, and it is what
    fails on an interpreter whose growth boundaries differ from the ones
    this budget was measured against.
    """
    row = builder(parser)[0]
    assert len(row) <= ceiling, (
        "%s has %d keys, past its declared ceiling of %d -- the next key "
        "crosses a dict size boundary and belongs on _record, which costs "
        "nothing" % (name, len(row), ceiling))
    baseline = {("k%03d" % i): i for i in range(ceiling)}
    assert sys.getsizeof(row) == sys.getsizeof(baseline), (
        "%s: %d keys no longer sizes the same as a %d-key dict on this "
        "interpreter" % (name, len(row), ceiling))


@pytest.mark.parametrize("name,builder,parser,engine_obj,ceiling", CASES,
                         ids=IDS)
def test_no_row_builder_copies_a_blob(
        name, builder, parser, engine_obj, ceiling):
    """A blob reaches the dialog through _record, as the SAME bytes
    object. bytes(b), b[:] and bytearray(b) are all forbidden: response
    headers alone are 370 KB across 577 blobs on the sample exhibit, and
    the parser owns them for the whole session either way."""
    row = builder(parser)[0]
    for key in ("ResponseHeaders_raw", "RequestHeaders_raw", "Blob_raw"):
        original = engine_obj.get(key)
        if original is None:
            continue
        assert row["_record"].get(key) is original, (
            "%s copied %s instead of pointing at it" % (name, key))


# --- the values the row builder itself decided ----------------------------

def test_the_timestamp_basis_survives_into_the_history_row():
    """key_timestamp() returns (raw, WHICH COLUMN WON) and the loader
    threw the second half away. "The visit was written" and "the cache
    entry was touched" are different claims, and AccessedUtc collapses
    both into one undifferentiated time."""
    descriptions = {d for _f, d in forensic_engine.KEY_TIMESTAMP_ORDER}

    rows = evidence_loader.history_rows_from_parser(
        _StubParser(all_entries=[_history_entry()]))
    assert rows[0]["AccessedUtcBasis"] == "ModifiedTime (visit written)"
    assert rows[0]["AccessedUtcBasis"] in descriptions

    rows = evidence_loader.history_rows_from_parser(_StubParser(all_entries=[
        _history_entry(ModifiedTime_raw=0, AccessedTime_raw=FT)]))
    assert rows[0]["AccessedUtcBasis"] == "AccessedTime (cache touch)"


def test_a_record_with_no_timestamp_at_all_states_no_basis():
    """"" is only ever the honest answer when the record genuinely
    carries no timestamp -- never a stand-in for one that was not
    looked up."""
    rows = evidence_loader.history_rows_from_parser(_StubParser(all_entries=[
        _history_entry(ModifiedTime_raw=0, AccessedTime_raw=0,
                       CreationTime_raw=0)]))
    assert rows[0]["AccessedUtc"] is None
    assert rows[0]["AccessedUtcBasis"] == ""


def test_the_visit_count_source_is_the_engines_own_wording():
    """Never re-typed at this layer -- forensic_engine's constants, so
    the screen and the export cannot say it two ways."""
    rows = evidence_loader.history_rows_from_parser(
        _StubParser(all_entries=[_history_entry()]))
    assert rows[0]["VisitCountSource"] is forensic_engine.VISIT_SOURCE_SPS

    rows = evidence_loader.history_rows_from_parser(_StubParser(all_entries=[
        _history_entry(SPS_VisitCount=None)]))
    assert rows[0]["VisitCount"] == 9
    assert rows[0]["VisitCountSource"] is (
        forensic_engine.VISIT_SOURCE_ACCESS_COUNT)


def test_a_live_history_row_states_the_container_it_is_in():
    """The loop's own `continue` already proved this. Without the key,
    provenance.describe_origin() has nothing but the words "Live record"
    to show an examiner who pressed F1."""
    from webcache import provenance

    rows = evidence_loader.history_rows_from_parser(
        _StubParser(all_entries=[_history_entry()]))
    assert rows[0]["ContainerType"] == "History"
    assert provenance.describe_origin(rows[0]) == "Live record in History"


def test_a_download_row_grades_itself_and_names_its_join_key():
    """Every other carved or derived surface in this application states
    its own confidence; Downloads was the one that did not."""
    rows = evidence_loader.downloads_rows_from_parser(_StubParser(
        all_entries=[_history_entry(ContainerType="Downloads")]))
    assert rows[0]["DownloadConfidence"] in ("high", "medium", "low", "none")
    assert isinstance(rows[0]["DownloadGuid"], str)


def test_a_cookie_row_carries_the_secure_bit_the_engine_already_decoded():
    """IsSecure is bit 0x1, decoded by ese_parser for every cookie and
    displayed nowhere."""
    rows = evidence_loader.cookie_rows_from_parser(
        _StubParser(cookie_entries=[_cookie_entry()]))
    assert rows[0]["IsSecure"] is True

    plain = _cookie_entry()
    plain["IsSecure"] = False
    rows = evidence_loader.cookie_rows_from_parser(
        _StubParser(cookie_entries=[plain]))
    assert rows[0]["IsSecure"] is False


def test_an_hsts_expiry_becomes_a_real_datetime():
    """views/cookies.py declares Expires kind="time" and the loader fed
    it a pre-formatted string, so every time operator on that column
    compared nothing."""
    import datetime

    rows = evidence_loader.hsts_rows_from_parser(
        _StubParser(hsts_entries=[_hsts_pin()], all_entries=[]))
    assert isinstance(rows[0]["Expires"], datetime.datetime)


def test_a_pin_that_never_expires_still_says_so_in_words():
    """0x7FFFFFFFFFFFFFFF is not a date. It must not decode to a
    far-future year and it must not go blank -- a blank reads as "no
    expiry was recorded", which is a different fact from "this pin does
    not expire"."""
    pin = _hsts_pin()
    pin["Expires"] = "never"
    pin["Expires_raw"] = NEVER
    rows = evidence_loader.hsts_rows_from_parser(
        _StubParser(hsts_entries=[pin], all_entries=[]))
    assert rows[0]["Expires"] == "never"


def test_a_certificate_row_says_a_blob_exists_without_carrying_it():
    """An int, not the DER. 220-258 KB of certificate across 24-34
    entries stays exactly where it already is -- on the parser."""
    rows = evidence_loader.cert_rows_from_parser(
        _StubParser(cert_entries=[_cert_entry()]))
    assert rows[0]["BlobBytes"] == len(BLOB)
    assert not isinstance(rows[0].get("BlobBytes"), (bytes, bytearray))
    assert rows[0]["_record"]["Blob_raw"] is BLOB


def test_a_certificate_with_no_blob_reports_zero_not_a_guess():
    entry = _cert_entry()
    entry["Blob_raw"] = None
    rows = evidence_loader.cert_rows_from_parser(
        _StubParser(cert_entries=[entry]))
    assert rows[0]["BlobBytes"] == 0


def test_container_times_become_real_datetimes():
    """Both columns are already declared kind="time" in
    views/containers.py, and both held a pre-formatted string."""
    import datetime

    rows = evidence_loader.container_rows_from_parser(
        _StubParser(containers_meta=[_container_meta()]))
    assert isinstance(rows[0]["LastAccess"], datetime.datetime)
    assert rows[0]["LastScavenge"] is None, (
        "a container never scavenged has no scavenge instant; None is what "
        "a time column renders as blank, not a fabricated 1601")


def test_the_record_count_sentinel_is_untouched_by_the_widening():
    """A container whose own table is gone was never counted. Adding keys
    to this row must not disturb the one field that already refuses to
    report a bare 0."""
    from webcache import provenance

    meta = _container_meta()
    meta["HasTable"] = False
    rows = evidence_loader.container_rows_from_parser(
        _StubParser(containers_meta=[meta]))
    assert rows[0]["Records"] == provenance.CONTAINER_NOT_DETERMINABLE


# --- the kinds themselves --------------------------------------------------

def test_record_kinds_declares_every_kind_exactly_once():
    assert len(record_kinds.ALL) == len(set(record_kinds.ALL))
    assert all(isinstance(k, str) and k for k in record_kinds.ALL)


def test_record_kinds_imports_neither_qt_nor_the_engine():
    """It is referenced by the shell and will be referenced by the field
    catalogue, which must stay testable with no QApplication."""
    import ast
    import pathlib

    path = (pathlib.Path(record_kinds.__file__))
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [a.name for a in node.names]
        for name in names:
            parts = name.split(".")
            assert "engine" not in parts and "PySide6" not in parts, name


# --- the carved side -------------------------------------------------------
#
# TWO KINDS, and recovery_loader.deleted_records_rows is where the shell
# currently flattens away the difference. A structured record is a whole
# reconstructed database row with a ContainerId, Flags and columns; a
# string artifact is text that looks like a URL, plus where it was found.
# They can answer completely different sets of questions, and a row set
# that cannot tell them apart will eventually answer one with the other.

def _struct_record(**overrides):
    entry = {
        "ContainerType": "History",
        "ContainerId": 3,
        "ContainerName": "History",
        "EntryId": 12,
        "Url": "https://example.test/deleted",
        "CleanUrl": "https://example.test/deleted",
        "SPS_PageTitle": "",
        "ModifiedTime_raw": FT,
        "AccessedTime_raw": 0,
        "CreationTime_raw": 0,
        "SPS_LastVisitLocal_raw": None,
        "SPS_VisitCount": None,
        "AccessCount": 4,
        "Flags": 0x08,
        "FileSize": 0,
        "SearchTerms": "",
        "IsLocalFile": False,
        "Source": "WebCacheV01.dat",
        "Offset": 0,
        "Page": 0,
        "RecoverySource": "Structured record reconstruction",
        "Confidence": "high",
        "Region": "deleted-record",
        "RecordEndMode": "terminated",
        "InLiveDb": False,
        "UrlHealth": "intact",
        "UrlHealthNote": "",
        "ResponseHeaders_raw": BLOB,
    }
    entry.update(overrides)
    return entry


def _string_artifact(**overrides):
    artifact = {
        "Url": "ttps://example.test/slack",
        "CleanUrl": "ttps://example.test/slack",
        "Source": "V01.log",
        "Offset": 4096,
        "Page": 2,
        "RecoverySource": "Transaction-log string carve",
        "Confidence": "medium",
        "Region": "page-slack",
        "Encoding": "utf-16-le",
        "NearbyFiletime": None,
        "UrlHealth": "repairable",
        "UrlHealthNote": "1 stray byte(s) before the scheme",
        "AlsoSeenIn": "empty-page",
        "FragmentCount": 2,
        "IsLocalFile": False,
    }
    artifact.update(overrides)
    return artifact


class _StubEngine:
    """recovery_loader's builders read exactly two things off the engine:
    structured_records, and all_artifacts()."""

    def __init__(self, structured=(), artifacts=()):
        self.structured_records = list(structured)
        self._artifacts = list(artifacts)

    def all_artifacts(self):
        return self._artifacts


# carved_history is 24: the Copies key crosses into
# the 832 B bucket, +368 B per CARVED History row -- 82 KB on the 136.5 MB
# sample's 222. Carved rows are bounded by the recovered set, never by the
# live row count this ceiling guards. Container and SameVisit stay inside that same 832 B bucket: the size assertion below still
# compares against a baseline of exactly this many keys.
def _carved_cases():
    from webcache.shell import recovery_loader

    hist = _struct_record()
    fa = _struct_record(IsLocalFile=True,
                        CleanUrl="file:///C:/Users/x/gone.docx",
                        Url="file:///C:/Users/x/gone.docx")
    dl = _struct_record(ContainerType="Downloads")
    return [
        ("carved_history", recovery_loader.carved_history_rows,
         _StubEngine([hist]), hist, 24),
        # 22: Copies, as carved_history above -- +368 B per carved File
        # Access row, ~490 KB on a real machine's 1,338, where 360 were
        # copies of a record already listed.
        # 24: Drive and FileType. Free: 22 already crossed into the
        # bucket that holds up to 42 keys at the same 832 bytes
        # (measured), so two more keys cost nothing per row.
        ("carved_file_access", recovery_loader.carved_file_access_rows,
         _StubEngine([fa]), fa, 24),
        ("carved_downloads", recovery_loader.carved_downloads_rows,
         _StubEngine([dl]), dl, 10),
        ("deleted_structured", recovery_loader.deleted_records_rows,
         _StubEngine([hist]), hist, 21),
    ]


CARVED_CASES = _carved_cases()
CARVED_IDS = [c[0] for c in CARVED_CASES]


@pytest.mark.parametrize("name,builder,engine,engine_obj,ceiling",
                         CARVED_CASES, ids=CARVED_IDS)
def test_every_carved_row_carries_a_reference_to_its_engine_record(
        name, builder, engine, engine_obj, ceiling):
    rows = builder(engine)
    assert rows, "%s produced no row" % name
    assert rows[0]["_record"] is engine_obj


@pytest.mark.parametrize("name,builder,engine,engine_obj,ceiling",
                         CARVED_CASES, ids=CARVED_IDS)
def test_carved_row_key_count_stays_inside_its_size_bucket(
        name, builder, engine, engine_obj, ceiling):
    row = builder(engine)[0]
    assert len(row) <= ceiling, "%s has %d keys, ceiling %d" % (
        name, len(row), ceiling)
    baseline = {("k%03d" % i): i for i in range(ceiling)}
    assert sys.getsizeof(row) == sys.getsizeof(baseline)


def test_a_carved_row_states_the_health_of_the_url_it_recovered():
    """normalise_record computes UrlHealth for EVERY carved record -- the
    field that exists to stop damaged bytes reading as a recorded URL --
    and it is displayed nowhere. On the sample exhibit structured records
    are all "intact" and string carves include "repairable" ones, so this
    is a real distinction on real evidence, not a hypothetical."""
    from webcache.shell import recovery_loader

    rows = recovery_loader.carved_history_rows(_StubEngine([_struct_record()]))
    assert rows[0]["UrlHealth"] == "intact"

    rows = recovery_loader.deleted_records_rows(
        _StubEngine(artifacts=[_string_artifact()]))
    assert rows[0]["UrlHealth"] == "repairable"


def test_the_two_carved_kinds_are_told_apart_not_flattened_together():
    from webcache.shell import record_kinds, recovery_loader

    rows = recovery_loader.deleted_records_rows(
        _StubEngine([_struct_record()], [_string_artifact()]))
    assert rows[0]["_kind"] is record_kinds.K_CARVED_STRUCT
    assert rows[1]["_kind"] is record_kinds.K_CARVED_STRING
    assert rows[1]["_record"] is not None


def test_a_carved_string_artifact_never_claims_inprivate_false():
    """A string pulled out of page slack has no Flags column, so whether
    the visit was InPrivate is not merely absent -- it cannot be known.
    False is a claim; the sentinel is the fact."""
    from webcache import provenance
    from webcache.shell import recovery_loader

    rows = recovery_loader.deleted_records_rows(
        _StubEngine(artifacts=[_string_artifact()]))
    assert rows[0]["IsInPrivate"] is provenance.ABSENCE_NOT_DETERMINABLE
    assert rows[0]["IsInPrivate"] is not False


def test_a_carved_structured_record_recomputes_inprivate_from_its_flags():
    """carved_history_rows already does this; deleted_records_rows did
    not, so a carved InPrivate visit was invisible in the one view that
    shows the full yield of a scan. On the sample exhibit 221 of 270
    structured records carry bit 0x08 and NONE of them carries an
    IsInPrivate key -- the engine never sets one for a carved record."""
    from webcache.shell import recovery_loader

    rows = recovery_loader.deleted_records_rows(
        _StubEngine([_struct_record(Flags=0x08)]))
    assert rows[0]["IsInPrivate"] is True

    rows = recovery_loader.deleted_records_rows(
        _StubEngine([_struct_record(Flags=0)]))
    assert rows[0]["IsInPrivate"] is False


def test_a_string_carve_states_which_region_and_encoding_it_came_from():
    """page-slack, empty-page or a log region, and ascii or utf-16-le.
    Both are real, both are recorded by the carver, both were dropped."""
    from webcache.shell import recovery_loader

    rows = recovery_loader.deleted_records_rows(
        _StubEngine([_struct_record()], [_string_artifact()]))
    assert rows[0]["Region"] == "deleted-record"
    assert rows[0]["Encoding"] == ""
    assert rows[1]["Region"] == "page-slack"
    assert rows[1]["Encoding"] == "utf-16-le"


def test_a_zero_offset_and_a_zero_page_survive_the_widening():
    """0 is the first byte of a file and the first page of unallocated
    space. provenance.describe_origin already refuses to treat either as
    absent; the row must not start doing so either."""
    from webcache import provenance
    from webcache.shell import recovery_loader

    rows = recovery_loader.deleted_records_rows(
        _StubEngine([_struct_record(Offset=0, Page=0)]))
    assert rows[0]["Offset"] == 0
    assert rows[0]["Page"] == 0
    line = provenance.describe_origin(rows[0])
    assert "@ 0x00000000" in line
    assert "(page 0)" in line


# --- the two aggregates, which must say that is what they are -------------
#
# A Domains row and an Indicators row are NOT records. Every value on one
# is a sum, a count or an extremum computed across N records, and a
# surface that renders one without saying so lets an aggregate read as a
# thing that happened once. `_kind` is how a consumer knows, `_record` is
# None because there is no single record to point at, and `_members` /
# `_records` are what make the "Records: N" cell reachable instead of a
# dead number.

def test_a_domain_row_says_it_is_an_aggregate_and_names_its_members():
    from webcache.shell import domain_loader, record_kinds

    a = _history_entry(Url="https://example.test/a")
    b = _history_entry(Url="https://example.test/b")
    rows = domain_loader.domain_rows([a, b])

    assert len(rows) == 1
    assert rows[0]["_kind"] is record_kinds.K_DOMAIN
    assert rows[0]["_record"] is None, (
        "an aggregate has no single record to point at, and a key that is "
        "present and None says that; a missing key only says nobody set it")
    assert rows[0]["Records"] == 2
    members = rows[0]["_members"]
    assert len(members) == 2
    assert any(m is a for m in members) and any(m is b for m in members), (
        "references to entries already resident -- the total across all "
        "domains is one pointer per record, not a second copy of the set")


def test_a_carved_inprivate_visit_reaches_the_domains_aggregate():
    """carved_history_rows recomputes InPrivate from Flags & 0x08; this
    aggregator did not, and the engine never sets IsInPrivate on a carved
    record at all -- so a domain visited only in InPrivate, only in
    deleted records, reported No."""
    from webcache.shell import domain_loader

    carved = _struct_record(Url="https://carved.test/x", Flags=0x08)
    carved.pop("IsInPrivate", None)
    rows = domain_loader.domain_rows([], [carved])

    assert len(rows) == 1
    assert rows[0]["IsInPrivate"] is True


def test_an_unknowable_inprivate_is_not_counted_as_a_yes_or_a_no():
    """A string carve has no Flags. The aggregate must not report Yes off
    a truthy sentinel, and must not report it as a confirmed No either --
    it simply contributes nothing to this question."""
    from webcache.shell import domain_loader

    artifact = _string_artifact(Url="https://example.test/slack",
                                CleanUrl="https://example.test/slack")
    rows = domain_loader.domain_rows([], [artifact])
    assert len(rows) == 1
    assert rows[0]["IsInPrivate"] is False, (
        "not True -- a non-empty sentinel string is truthy, and reading it "
        "as a flag would assert an InPrivate visit the evidence cannot "
        "support")


def test_an_indicator_row_says_it_is_an_aggregate_and_names_its_records():
    from webcache.shell import indicator_loader, record_kinds

    mac = "00-1A-2B-3C-4D-5E"
    a = {"Url": "https://example.test/%s/a" % mac}
    b = {"Url": "https://other.test/%s/b" % mac}
    rows = [r for r in indicator_loader.indicator_rows([a, b])
            if r["Kind"] == "MAC address"]

    assert rows, "the calibrated MAC extractor should have fired"
    assert rows[0]["_kind"] is record_kinds.K_INDICATOR
    assert rows[0]["_record"] is None
    assert rows[0]["Records"] == 2
    assert len(rows[0]["_records"]) == 2
    assert any(r is a for r in rows[0]["_records"])


def test_an_indicator_states_which_field_it_was_found_in():
    """url_intel.SCANNED_FIELDS covers five fields and the view named
    none of them. An examiner cannot weigh a MAC address without knowing
    whether it came out of a URL or out of a cached filename."""
    from webcache.shell import indicator_loader

    mac = "00-1A-2B-3C-4D-5E"
    rows = [r for r in indicator_loader.indicator_rows(
        [{"Url": "https://example.test/%s/a" % mac},
         {"Url": "https://other.test/b", "Filename": "log-%s.txt" % mac}])
        if r["Kind"] == "MAC address"]

    assert rows
    assert rows[0]["Fields"] == "File name, URL", (
        "sorted and joined once per aggregate row, not per record")


def test_an_indicator_with_no_named_field_says_nothing_rather_than_guessing():
    from webcache.engine import url_intel
    from webcache.shell import indicator_loader

    tally = url_intel.summarise([url_intel.Finding(
        "Made up", "x", "", url_intel.LOW, "because")])
    assert next(iter(tally["Made up"].values()))["fields"] == set()


def test_a_period_row_says_it_is_an_aggregate_and_names_its_members():
    """A Timeline row is every record that fell in one bucket, counted.
    It shares K_DOMAIN's failure mode exactly: shown without saying so, it
    reads as one thing that happened."""
    from webcache.shell import record_kinds, timeline_loader

    a = _history_entry(Url="https://example.test/a")
    b = _history_entry(Url="https://example.test/b")
    rows = timeline_loader.period_rows(
        timeline_loader.timeline_inputs([a, b]), "day")

    assert len(rows) == 1
    assert rows[0]["_kind"] is record_kinds.K_PERIOD
    assert record_kinds.K_PERIOD in record_kinds.AGGREGATES
    assert rows[0]["Records"] == 2
    members = rows[0]["_members"]
    assert any(m is a for m in members) and any(m is b for m in members)
    assert "_record" not in rows[0], (
        "the ELEVENTH key crosses a dict size step, and the minute grain "
        "on a large exhibit produces tens of thousands of these rows -- "
        "detail_fields reads _record with .get() and tolerates its absence")


@pytest.mark.parametrize("builder_name", ["domains", "indicators", "timeline"])
def test_an_aggregate_row_stays_inside_its_size_bucket(builder_name):
    """Domains crosses from the 272 B bucket to the 464 B one, on purpose
    and with the cost stated: a Domains row set is bounded by the number
    of DISTINCT HOSTS (51 on the sample exhibit, 63 in the earlier version's
    own measurement), not by the record count, so +192 B per row is
    around 10 KB in total -- and _members is what turns "Records: N" from
    a dead number into something an examiner can open. Indicators stays
    inside the 272 B bucket at exactly its ceiling of ten."""
    from webcache.shell import domain_loader, indicator_loader, timeline_loader

    mac = "00-1A-2B-3C-4D-5E"
    if builder_name == "domains":
        row = domain_loader.domain_rows([_history_entry()])[0]
        ceiling = 21
    elif builder_name == "timeline":
        row = timeline_loader.period_rows(
            timeline_loader.timeline_inputs([_history_entry()]), "day")[0]
        ceiling = 10
    else:
        row = indicator_loader.indicator_rows(
            [{"Url": "https://example.test/%s/a" % mac}])[0]
        ceiling = 10

    assert len(row) <= ceiling, "%s has %d keys, ceiling %d" % (
        builder_name, len(row), ceiling)
    baseline = {("k%03d" % i): i for i in range(ceiling)}
    assert sys.getsizeof(row) == sys.getsizeof(baseline)


# --- the Table Browser, the one place raw bytes were destroyed ------------

class _StubTableParser:
    """table_page reads five methods off the parser and nothing else."""

    def __init__(self, columns, rows):
        self._columns = columns
        self._rows = rows
        self.containers_meta = []

    def get_table_rows_raw(self, name, limit=200, offset=0):
        return self._columns, self._rows[offset:offset + limit]

    def raw_type_name(self, v):
        return type(v).__name__

    def raw_rendering(self, v, truncate=True):
        # `truncate` mirrors the real WebCacheParser.raw_rendering: the
        # loader asks for the untruncated rendering of a text cell so the
        # row view can show the whole value, and a stand-in that cannot be
        # asked would make this stub the only parser in the application
        # with that signature.
        return repr(v)

    def get_table_row_count(self, name):
        return len(self._rows)

    def get_table_type(self, name):
        return "Container"

    def get_table_display_name(self, name):
        return name


def test_a_binary_cell_keeps_the_bytes_it_rendered():
    """table_page rendered every cell to {"type", "text"} and dropped the
    value, so no binary column of any ESE table could ever reach a blob
    viewer -- including columns nobody has written a decoder for, which
    is exactly where a hex-and-strings view is worth the most."""
    from webcache.shell import table_browser_loader

    page = table_browser_loader.table_page(
        _StubTableParser(["Blob", "Name"], [[BLOB, "a"]]), "Container_3")

    cell = page["rows"][0][0]
    assert cell["raw"] is BLOB, "by reference, never a copy"
    assert cell["text"], "the rendering an examiner reads is unchanged"


def test_a_non_binary_cell_carries_no_raw_value():
    """Only bytes. Keeping every int and string twice would double a
    page's cost for values the rendering already carries losslessly."""
    from webcache.shell import table_browser_loader

    page = table_browser_loader.table_page(
        _StubTableParser(["Blob", "Name", "Id"], [[BLOB, "a", 7]]),
        "Container_3")

    assert page["rows"][0][1]["raw"] is None
    assert page["rows"][0][2]["raw"] is None


def test_a_bytearray_cell_is_kept_too():
    from webcache.shell import table_browser_loader

    buf = bytearray(BLOB)
    page = table_browser_loader.table_page(
        _StubTableParser(["Blob"], [[buf]]), "Container_3")
    assert page["rows"][0][0]["raw"] is buf
