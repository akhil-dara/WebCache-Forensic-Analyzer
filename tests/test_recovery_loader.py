"""recovery_loader.py: the wiring that runs recovery_engine.RecoveryEngine
for real, and the two pure functions that turn what it finds into row
shapes the GUI layer already knows how to draw.

Three things pinned here, mirroring test_evidence_loader.py's own structure
for the identical reason it gives: no real WebCacheV01.dat exists on this
machine, so the row-building functions are tested against stub/fake
"engine" objects rather than a real RecoveryEngine tied to file I/O, and the
worker's call-order/cancellation contract is proved against a fake
RecoveryEngine class rather than the real carving math (recovery_engine.py
already documents that math as empirically validated elsewhere; this file's
job is only to prove the wiring around it, which is the thing that was
entirely missing before this task).

1. carved_history_rows / deleted_records_rows -- which structured records
   become History rows (ContainerType == "History" only) versus which
   become Deleted Records rows (every recovered artifact, both kinds), and
   that every field the two views actually read is present.
2. RecoveryWorker's shutdown discipline -- unparented, tracked in the SAME
   consent._RUNNING_WORKERS set every other worker in this codebase uses.
3. The scan itself: RecoveryEngine's three carve_* methods are called in
   the documented order with the documented arguments, progress carries
   real counts and never a fabricated percentage, and cancellation --
   requested either between phases or from inside one, exactly the two
   places production code checks -- stops the scan and emits nothing.
"""
import datetime
import uuid

import pytest

from webcache.provenance import CONTAINER_NOT_DETERMINABLE
from webcache.shell import consent
from webcache.shell.recovery_loader import (CARVED_ORIGIN, RecoveryLoader,
                                            RecoveryWorker,
                                            carved_downloads_rows,
                                            carved_file_access_rows,
                                            carved_history_rows,
                                            deleted_records_rows)

_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


def _filetime(dt):
    return int((dt - _EPOCH).total_seconds() * 10_000_000)


_SOME_TIME = datetime.datetime(2024, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_SOME_FILETIME = _filetime(_SOME_TIME)


class _StubEngine:
    """Just enough of RecoveryEngine's surface for the two row-building
    functions -- a real RecoveryEngine's own attribute/method names,
    populated by hand rather than by a real carve."""

    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = structured_records or []
        self._artifacts = artifacts or []

    def all_artifacts(self):
        return self._artifacts


def _structured(container_type="History", **overrides):
    base = {
        "Url": "https://example.com/a",
        "CleanUrl": "https://example.com/a",
        "ContainerType": container_type,
        "SPS_PageTitle": "Example",
        "ModifiedTime_raw": _SOME_FILETIME,
        "AccessedTime_raw": 0,
        "CreationTime_raw": 0,
        "SPS_LastVisitLocal_raw": None,
        "SPS_VisitCount": 3,
        "AccessCount": 9,
        "Flags": 0,
        "Source": "WebCacheV01.dat",
        "Offset": 4096,
        "Page": 2,
        "RecoverySource": "Structured record reconstruction",
        "Confidence": "high",
    }
    base.update(overrides)
    return base


def _artifact(**overrides):
    base = {
        "Url": "Visited: alice@https://msn.com/x",
        "CleanUrl": "https://msn.com/x",
        "ContainerType": "",
        "NearbyFiletime": _SOME_TIME,
        "Source": "V01.log",
        "Offset": 777,
        "Page": None,
        "RecoverySource": "Transaction log",
        "Confidence": "medium",
    }
    base.update(overrides)
    return base


# --- carved_history_rows: History container only, always stamped Carved ---

def test_only_history_container_structured_records_become_rows():
    """The rule: only a structured record with a resolved
    ContainerType == 'History' can honestly be filed under History. A raw
    URL-string carve (no ContainerId, no resolvable container) never
    reaches this function's output at all -- see deleted_records_rows for
    where it DOES show up."""
    engine = _StubEngine(structured_records=[
        _structured(container_type="History"),
        _structured(container_type="Content"),
        _structured(container_type="Cookies"),
    ])
    rows = carved_history_rows(engine)
    assert len(rows) == 1


def test_every_carved_history_row_is_stamped_carved():
    engine = _StubEngine(structured_records=[_structured(), _structured()])
    rows = carved_history_rows(engine)
    assert rows
    assert all(r["Origin"] == CARVED_ORIGIN for r in rows)
    assert all(r["Origin"].startswith("Carved") for r in rows)


def test_carved_history_rows_carry_every_key_historyview_columns_reads():
    engine = _StubEngine(structured_records=[_structured()])
    row = carved_history_rows(engine)[0]
    for key in ("CleanUrl", "Title", "AccessedUtc", "AccessedLocal",
               "VisitCount", "Domain", "IsInPrivate", "Origin", "Source"):
        assert key in row, "HistoryView.COLUMNS reads %r" % key


def test_carved_history_rows_also_carry_the_provenance_fields_explain_needs():
    """Not columns HistoryView.COLUMNS declares today, but
    provenance.describe_origin() reads them straight off the row dict
    regardless of whether a column displays them -- F1/Explain on a merged
    carved History row must not go blank just because these are not
    (yet) their own columns."""
    engine = _StubEngine(structured_records=[_structured()])
    row = carved_history_rows(engine)[0]
    for key in ("Source", "Offset", "Page", "Method", "Confidence"):
        assert key in row


def test_carved_history_rows_carry_search_terms_and_local_file():
    """History's quick-filter chips must keep working honestly on a carved
    row too -- carve_structured_records() builds every structured record
    through the SAME normalise_record() a live row goes through (see
    recovery_engine.py), so these are real decoded values, not a live-only
    convenience silently dropped the moment a scan merges carved rows in."""
    engine = _StubEngine(structured_records=[
        _structured(SearchTerms="login", IsLocalFile=True)])
    row = carved_history_rows(engine)[0]
    assert row["SearchTerms"] == "login"
    assert row["IsLocalFile"] is True


def test_visit_count_prefers_sps_over_access_count():
    engine = _StubEngine(structured_records=[
        _structured(SPS_VisitCount=7, AccessCount=99)])
    assert carved_history_rows(engine)[0]["VisitCount"] == 7


def test_cache_touches_are_never_offered_as_visits():
    engine = _StubEngine(structured_records=[
        _structured(SPS_VisitCount=None, AccessCount=42)])
    row = carved_history_rows(engine)[0]
    assert row["VisitCount"] is None
    assert row["CacheTouches"] == 42


def test_accessed_utc_is_a_real_datetime():
    engine = _StubEngine(structured_records=[_structured()])
    assert isinstance(carved_history_rows(engine)[0]["AccessedUtc"],
                      datetime.datetime)


def test_a_record_with_no_usable_timestamp_gets_none_not_a_crash():
    engine = _StubEngine(structured_records=[_structured(
        ModifiedTime_raw=0, AccessedTime_raw=0, CreationTime_raw=0)])
    assert carved_history_rows(engine)[0]["AccessedUtc"] is None


def test_accessed_local_comes_from_the_sps_id24_local_timestamp():
    engine = _StubEngine(structured_records=[_structured(
        SPS_LastVisitLocal_raw=_SOME_FILETIME)])
    assert isinstance(carved_history_rows(engine)[0]["AccessedLocal"],
                      datetime.datetime)


def test_is_in_private_true_only_when_the_bit_is_set_on_a_history_record():
    """The identical bit test ese_parser._parse_record() uses for a live
    record -- bit 0x08, meaningful only on History-type records."""
    engine = _StubEngine(structured_records=[_structured(Flags=0x08)])
    assert carved_history_rows(engine)[0]["IsInPrivate"] is True


def test_is_in_private_false_when_the_bit_is_clear():
    engine = _StubEngine(structured_records=[_structured(Flags=0x00)])
    assert carved_history_rows(engine)[0]["IsInPrivate"] is False


def test_source_and_offset_and_method_and_confidence_pass_through():
    engine = _StubEngine(structured_records=[_structured(
        Source="WebCacheV01.dat", Offset=12345, Page=6,
        RecoverySource="Structured record reconstruction", Confidence="medium")])
    row = carved_history_rows(engine)[0]
    assert row["Source"] == "WebCacheV01.dat"
    assert row["Offset"] == 12345
    assert row["Page"] == 6
    assert row["Method"] == "Structured record reconstruction"
    assert row["Confidence"] == "medium"


def test_no_structured_records_means_no_carved_history_rows():
    assert carved_history_rows(_StubEngine()) == []


def test_carved_history_rows_are_stamped_with_the_container_they_were_filtered_on():
    """Every row this function emits already passed `ContainerType ==
    "History"` two lines above (see the function's own docstring) -- that
    is a known fact, not a value invented for display, and dropping it
    from the row dict would make provenance.describe_origin() (which now
    reads ContainerType to say whether a carved record's container is
    known) read a merged History row as "not determinable" even though
    this function just proved it was History."""
    engine = _StubEngine(structured_records=[_structured(container_type="History")])
    row = carved_history_rows(engine)[0]
    assert row["ContainerType"] == "History"


# --- carved_file_access_rows / carved_downloads_rows -----------------------
#
# carve_structured_records() runs every structured record through the
# SAME normalise_record() a live one goes through (see recovery_engine.py
# and ese_parser.py) -- IsLocalFile and ContainerType are real, resolved
# fields on a carved row exactly the way they are on a live one, so
# carved File Access/Downloads rows are genuinely attributable the same
# way carved_history_rows already proves for History; there is no "the
# engine cannot say" caveat to fall back on here.

def test_carved_file_access_rows_select_local_file_structured_records():
    engine = _StubEngine(structured_records=[
        _structured(container_type="Content", IsLocalFile=True),
        _structured(container_type="Content", IsLocalFile=False),
        _structured(container_type="History", IsLocalFile=True),
    ])
    rows = carved_file_access_rows(engine)
    assert len(rows) == 2


def test_every_carved_file_access_row_is_stamped_carved():
    engine = _StubEngine(structured_records=[
        _structured(IsLocalFile=True), _structured(IsLocalFile=True)])
    rows = carved_file_access_rows(engine)
    assert rows
    assert all(r["Origin"] == CARVED_ORIGIN for r in rows)


def test_carved_file_access_rows_state_their_source_file():
    engine = _StubEngine(structured_records=[_structured(
        IsLocalFile=True, Source="V010023E.log")])
    row = carved_file_access_rows(engine)[0]
    assert row["Source"] == "V010023E.log"


def test_carved_file_access_rows_carry_every_key_the_view_reads():
    engine = _StubEngine(structured_records=[_structured(
        IsLocalFile=True, FileSize=512, ContainerId=4, ContainerName="Content",
        EntryId=12)])
    row = carved_file_access_rows(engine)[0]
    for key in ("ModifiedTime", "AccessedLocal", "VisitCount", "CacheTouches", "CleanUrl",
               "Origin", "Source", "FileSize", "ContainerId", "ContainerName",
               "EntryId", "AccessedTime", "CreationTime"):
        assert key in row, "FileAccessView's file-access columns read %r" % key


def test_carved_file_access_never_offers_cache_touches_as_opens():
    engine = _StubEngine(structured_records=[_structured(
        IsLocalFile=True, SPS_VisitCount=None, AccessCount=13)])
    row = carved_file_access_rows(engine)[0]
    assert (row["VisitCount"], row["CacheTouches"]) == (None, 13)


def test_no_local_file_structured_records_means_no_carved_file_access_rows():
    engine = _StubEngine(structured_records=[_structured(IsLocalFile=False)])
    assert carved_file_access_rows(engine) == []


#: A fixed GUID, not uuid.uuid4() -- decode_download_blob() scans for a
#: plausible FILETIME across every byte offset in the header region
#: (see that function's own docstring), and a genuinely random 16-byte
#: GUID occasionally produces a false match inside itself, breaking the
#: intended offset -- observed directly as a rare, non-deterministic
#: failure of this fixture, not of the decoder or the row builder it
#: exercises. A fixed value removes that flake entirely.
_FIXED_GUID = uuid.UUID("12345678-1234-5678-1234-567812345678").bytes_le


def _download_blob(path=r"C:\case\evidence\bill.pdf",
                   url="https://portal.example/bill.pdf", size=9001,
                   when=None):
    import struct

    when = when or datetime.datetime(2024, 3, 2, 9, 0, 0,
                                     tzinfo=datetime.timezone.utc)
    epoch = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
    ft = int((when - epoch).total_seconds() * 10_000_000)
    header = _FIXED_GUID + struct.pack("<Q", ft) + struct.pack("<I", size)
    strings = path.encode("ascii") + b"\x00" + url.encode("ascii") + b"\x00"
    return header + strings


def test_carved_downloads_rows_select_downloads_container_structured_records():
    engine = _StubEngine(structured_records=[
        _structured(container_type="Downloads", ResponseHeaders_raw=_download_blob()),
        _structured(container_type="History"),
    ])
    rows = carved_downloads_rows(engine)
    assert len(rows) == 1


def test_every_carved_download_row_is_stamped_carved():
    engine = _StubEngine(structured_records=[
        _structured(container_type="Downloads", ResponseHeaders_raw=_download_blob())])
    rows = carved_downloads_rows(engine)
    assert rows
    assert all(r["Origin"] == CARVED_ORIGIN for r in rows)


def test_carved_download_rows_decode_the_response_headers_blob():
    """A carved Downloads record never gets ese_parser's own pre-computed
    DownloadPath/DownloadSourceUrl/DownloadSize/DownloadTime -- struct_
    carver only recovers the raw blob -- so this must decode it fresh,
    the identical mechanism downloads_rows_from_parser uses for a live
    record (see evidence_loader.py's own docstring)."""
    engine = _StubEngine(structured_records=[_structured(
        container_type="Downloads",
        ResponseHeaders_raw=_download_blob(
            path=r"D:\evidence\case9\photo.jpg",
            url="https://cdn.example/photo.jpg", size=2048))])
    row = carved_downloads_rows(engine)[0]
    assert row["DownloadPath"] == r"D:\evidence\case9\photo.jpg"
    assert row["DownloadSourceUrl"] == "https://cdn.example/photo.jpg"
    assert row["DownloadSize"] == 2048
    assert isinstance(row["DownloadTime"], datetime.datetime)


def test_carved_download_rows_state_their_source_file():
    engine = _StubEngine(structured_records=[_structured(
        container_type="Downloads", ResponseHeaders_raw=_download_blob(),
        Source="V01.log")])
    assert carved_downloads_rows(engine)[0]["Source"] == "V01.log"


def test_no_downloads_structured_records_means_no_carved_download_rows():
    engine = _StubEngine(structured_records=[_structured(container_type="Content")])
    assert carved_downloads_rows(engine) == []


# --- deleted_records_rows: everything recovered, both mechanisms ----------

def test_deleted_records_rows_include_structured_records_of_any_container():
    """Unlike carved_history_rows, the Deleted Records view is not
    filtered to History -- an examiner needs to see the FULL yield of a
    scan, not just the slice that could be filed under History."""
    engine = _StubEngine(structured_records=[
        _structured(container_type="History"),
        _structured(container_type="Content")])
    rows = deleted_records_rows(engine)
    assert len(rows) == 2


def test_deleted_records_rows_include_raw_string_carves_too():
    engine = _StubEngine(artifacts=[_artifact()])
    rows = deleted_records_rows(engine)
    assert len(rows) == 1
    assert rows[0]["CleanUrl"] == "https://msn.com/x"


def test_deleted_records_rows_combine_both_sources():
    engine = _StubEngine(structured_records=[_structured()],
                         artifacts=[_artifact()])
    rows = deleted_records_rows(engine)
    assert len(rows) == 2


def test_every_deleted_record_row_is_stamped_carved():
    engine = _StubEngine(structured_records=[_structured()],
                         artifacts=[_artifact()])
    rows = deleted_records_rows(engine)
    assert rows
    assert all(r["Origin"].startswith("Carved") for r in rows)


# --- IsInPrivate: bit 0x08 means InPrivate on History records ONLY -------
#
# deleted_records_rows applied the SAME bit test carved_history_
# rows uses -- bool(flags_val & 0x08) -- to every structured record, no
# matter its container. carved_history_rows is safe because it already
# filtered to ContainerType == "History" two lines above; this function
# never filters at all. On the sample exhibit 221 of 270 structured carves
# carrying the bit were Content-container records, none of them History,
# so opening any one of them asserted a fabricated "InPrivate: Yes" -- a
# claim about a person's browsing this application has no evidence for.

def test_deleted_records_rows_never_asserts_inprivate_on_a_content_record():
    """Bit 0x08 on a Content-container record is EDITED_CACHE_ENTRY, not
    InPrivate (see ese_parser.py's own flag-name table). Rendering it as
    True is a fabricated finding; rendering it as False is an equally
    confident, equally unsupported claim in the other direction."""
    engine = _StubEngine(structured_records=[
        _structured(container_type="Content", Flags=0x08)])
    row = deleted_records_rows(engine)[0]
    assert row["IsInPrivate"] is not True
    assert row["IsInPrivate"] is not False


def test_deleted_records_rows_never_asserts_inprivate_on_an_unresolved_container():
    """A container this engine could not resolve at all is exactly as
    unable to support an InPrivate claim as one it resolved to something
    other than History."""
    engine = _StubEngine(structured_records=[
        _structured(container_type=None, Flags=0x08)])
    row = deleted_records_rows(engine)[0]
    assert row["IsInPrivate"] is not True
    assert row["IsInPrivate"] is not False


def test_deleted_records_rows_still_asserts_inprivate_on_a_history_record():
    """The one container where the bit genuinely means InPrivate must keep
    saying so plainly -- gating this must not turn into hiding it."""
    engine = _StubEngine(structured_records=[
        _structured(container_type="History", Flags=0x08)])
    assert deleted_records_rows(engine)[0]["IsInPrivate"] is True


def test_deleted_records_rows_still_reports_false_on_a_clear_history_bit():
    engine = _StubEngine(structured_records=[
        _structured(container_type="History", Flags=0x00)])
    assert deleted_records_rows(engine)[0]["IsInPrivate"] is False


def test_a_structured_records_method_is_its_recovery_source():
    engine = _StubEngine(structured_records=[_structured(
        RecoverySource="Structured record reconstruction")])
    assert deleted_records_rows(engine)[0]["Method"] == (
        "Structured record reconstruction")


def test_an_artifacts_method_is_its_recovery_source():
    engine = _StubEngine(artifacts=[_artifact(RecoverySource="DB unallocated space")])
    assert deleted_records_rows(engine)[0]["Method"] == "DB unallocated space"


def test_a_structured_records_timestamp_is_derived_from_its_real_time_fields():
    engine = _StubEngine(structured_records=[
        _structured(ModifiedTime_raw=_SOME_FILETIME)])
    ts = deleted_records_rows(engine)[0]["Timestamp"]
    assert isinstance(ts, datetime.datetime)


def test_an_artifacts_timestamp_is_its_nearby_filetime_context_hint():
    """A string carve's only temporal evidence is context, never an
    established visit time -- see recovery_engine.py's NearbyFiletime
    naming. Still surfaced in the same Timestamp column: Method and
    Confidence are what say how sure this application actually is."""
    engine = _StubEngine(artifacts=[_artifact(NearbyFiletime=_SOME_TIME)])
    assert deleted_records_rows(engine)[0]["Timestamp"] == _SOME_TIME


def test_no_recovered_artifacts_means_an_empty_deleted_records_view():
    assert deleted_records_rows(_StubEngine()) == []


# --- ContainerType normalisation: one sentinel, not two spellings ---------

def test_a_string_carve_with_no_containertype_key_gets_the_sentinel():
    """recovery_engine.py's _carve_strings() (behind both
    carve_transaction_logs and carve_database_slack) never produces a
    ContainerType key at all -- .get() returns None, and the confirmed
    defect was rendering that as a blank cell, indistinguishable from a
    field the tool simply failed to read."""
    engine = _StubEngine(artifacts=[_artifact(ContainerType=None)])
    row = deleted_records_rows(engine)[0]
    assert row["ContainerType"] == CONTAINER_NOT_DETERMINABLE


def test_a_string_carve_with_an_empty_string_containertype_gets_the_same_sentinel():
    """The other spelling of the same unknown -- some carved records
    carried ContainerType: "" instead of a missing key. Both must
    normalise to the ONE sentinel, so nothing downstream has to handle two
    spellings of "cannot be determined"."""
    engine = _StubEngine(artifacts=[_artifact(ContainerType="")])
    row = deleted_records_rows(engine)[0]
    assert row["ContainerType"] == CONTAINER_NOT_DETERMINABLE


def test_a_structured_records_real_container_is_never_replaced_by_the_sentinel():
    """The sentinel is for when there is genuinely nothing to resolve --
    a structured record that resolved a real, non-History container (e.g.
    "Cookies") must keep it verbatim, not have it overwritten."""
    engine = _StubEngine(structured_records=[_structured(container_type="Cookies")])
    row = deleted_records_rows(engine)[0]
    assert row["ContainerType"] == "Cookies"


def test_a_structured_record_missing_containertype_entirely_also_gets_the_sentinel():
    """Defensive: _normalise_carved() has always resolved a real
    ContainerType for every structured record in practice, but this
    function must not fabricate one if that ever stops being true --
    falling back to the same honest sentinel, not a blank cell."""
    engine = _StubEngine(structured_records=[_structured(container_type=None)])
    row = deleted_records_rows(engine)[0]
    assert row["ContainerType"] == CONTAINER_NOT_DETERMINABLE


# --- RecoveryWorker: unparented, tracked in the shared shutdown set -------

class _StubParser:
    def __init__(self, db=None, db_path="C:/case/WebCacheV01.dat",
                containers_meta=None, container_type_map=None,
                all_entries=None):
        self.db = db
        self.db_path = db_path
        self.containers_meta = containers_meta or []
        self.container_type_map = container_type_map or {}
        self.all_entries = all_entries or []


def test_worker_is_never_parented():
    worker = RecoveryWorker(_StubParser())
    assert worker.parent() is None


def test_loader_cancel_before_any_scan_does_not_raise():
    loader = RecoveryLoader()
    loader.cancel()  # must not raise


def test_loader_cancel_requests_interruption_on_the_worker():
    calls = []

    class _SpyWorker:
        def requestInterruption(self):
            calls.append(1)

    loader = RecoveryLoader()
    loader._worker = _SpyWorker()
    loader.cancel()
    assert calls == [1]


class _FakeRecoveryEngine:
    """Records every call it receives, in order, standing in for the real
    RecoveryEngine so this file can prove the WIRING (call order,
    arguments, cancellation) without the real carving math -- see the
    module docstring."""

    #: Reset by the fixture below before every test that uses it.
    calls = []

    def __init__(self):
        pass

    def set_container_metadata(self, containers_meta, container_types):
        _FakeRecoveryEngine.calls.append(
            ("set_container_metadata", containers_meta, container_types))

    def carve_transaction_logs(self, db_path, live_urls, progress_callback=None):
        _FakeRecoveryEngine.calls.append(
            ("carve_transaction_logs", db_path, live_urls))
        if progress_callback:
            progress_callback(1, 2)
        return []

    def carve_database_slack(self, db, db_path, live_urls, progress_callback=None):
        _FakeRecoveryEngine.calls.append(
            ("carve_database_slack", db, db_path, live_urls))
        if progress_callback:
            progress_callback(100, 500)
        return []

    def carve_structured_records(self, db, db_path, progress_callback=None):
        _FakeRecoveryEngine.calls.append(
            ("carve_structured_records", db, db_path))
        if progress_callback:
            progress_callback(200, 0)
        return []

    def attribute_carved_pages(self, db):
        _FakeRecoveryEngine.calls.append(("attribute_carved_pages", db))


@pytest.fixture(autouse=True)
def _reset_fake_engine_calls():
    _FakeRecoveryEngine.calls = []
    yield


def test_the_three_carve_phases_run_in_order_with_the_right_arguments(
        qtbot, monkeypatch):
    """If any phase were dropped, reordered, or called with the wrong
    parser attribute (db vs db_path, or the live-URL set built wrong),
    this assertion on the exact call sequence would fail."""
    from webcache.shell import recovery_loader as mod
    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine", _FakeRecoveryEngine)

    db = object()
    parser = _StubParser(
        db=db, db_path="C:/case/WebCacheV01.dat",
        containers_meta=[{"ContainerId": 6, "Name": "History"}],
        container_type_map={6: "History"},
        all_entries=[{"Url": "https://live.example.com/"}, {"Url": None}])

    loader = RecoveryLoader()
    with qtbot.waitSignal(loader.loaded, timeout=5_000):
        loader.start(parser)

    kinds = [c[0] for c in _FakeRecoveryEngine.calls]
    # Attribution reads the pages and the reconstructed records, so it
    # comes after both.
    assert kinds == ["set_container_metadata", "carve_transaction_logs",
                     "carve_database_slack", "carve_structured_records",
                     "attribute_carved_pages"]

    _, containers_meta, container_types = _FakeRecoveryEngine.calls[0]
    assert containers_meta == parser.containers_meta
    assert container_types == parser.container_type_map

    _, log_db_path, live_urls = _FakeRecoveryEngine.calls[1]
    assert log_db_path == parser.db_path
    assert live_urls == {"https://live.example.com/"}, (
        "a None Url in a live entry must not become a literal None member "
        "of the live-URL set")

    _, slack_db, slack_db_path, slack_live_urls = _FakeRecoveryEngine.calls[2]
    assert slack_db is db
    assert slack_db_path == parser.db_path
    assert slack_live_urls == {"https://live.example.com/"}

    _, struct_db, struct_db_path = _FakeRecoveryEngine.calls[3]
    assert struct_db is db
    assert struct_db_path == parser.db_path


def test_loaded_emits_the_engine_instance(qtbot, monkeypatch):
    from webcache.shell import recovery_loader as mod
    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine", _FakeRecoveryEngine)

    loader = RecoveryLoader()
    received = []
    loader.loaded.connect(received.append)
    with qtbot.waitSignal(loader.loaded, timeout=5_000):
        loader.start(_StubParser())
    assert len(received) == 1
    assert isinstance(received[0], _FakeRecoveryEngine)


def test_progress_messages_report_real_counts_never_a_fabricated_percentage(
        qtbot, monkeypatch):
    from webcache.shell import recovery_loader as mod
    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine", _FakeRecoveryEngine)

    loader = RecoveryLoader()
    messages = []
    loader.progress.connect(messages.append)
    with qtbot.waitSignal(loader.loaded, timeout=5_000):
        loader.start(_StubParser())

    joined = " ".join(messages)
    assert "1" in joined and "2" in joined  # the log-file progress
    assert "100" in joined and "500" in joined  # the page-scan progress
    assert "200" in joined  # the structured-carve progress
    assert not any("%" in m for m in messages)


def test_a_failure_in_any_phase_reaches_failed_and_never_loaded(qtbot, monkeypatch):
    from webcache.shell import recovery_loader as mod

    class _BlowsUpOnPageSlack(_FakeRecoveryEngine):
        def carve_database_slack(self, db, db_path, live_urls, progress_callback=None):
            _FakeRecoveryEngine.calls.append(("carve_database_slack", "boom"))
            raise RuntimeError("page 4021 is corrupt")

    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine", _BlowsUpOnPageSlack)
    loader = RecoveryLoader()
    messages = []
    loaded_calls = []
    loader.failed.connect(messages.append)
    loader.loaded.connect(loaded_calls.append)
    with qtbot.waitSignal(loader.failed, timeout=5_000):
        loader.start(_StubParser())
    assert messages and "corrupt" in messages[0]
    assert loaded_calls == []
    # The phase AFTER the one that raised must never have run.
    kinds = [c[0] for c in _FakeRecoveryEngine.calls]
    assert "carve_structured_records" not in kinds


def test_worker_registers_in_the_shared_shutdown_set_and_self_cleans(
        qtbot, monkeypatch):
    """The same wiring fact evidence_loader.py's own suite pins:
    consent.shutdown_workers() only ever sweeps consent._RUNNING_WORKERS,
    so a recovery worker that never lands there would silently outlive
    application exit."""
    from webcache.shell import recovery_loader as mod
    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine", _FakeRecoveryEngine)

    loader = RecoveryLoader()
    loader.start(_StubParser())
    qtbot.waitUntil(lambda: loader._worker is not None, timeout=2_000)
    worker = loader._worker
    assert worker in consent._RUNNING_WORKERS
    qtbot.waitUntil(lambda: worker not in consent._RUNNING_WORKERS, timeout=5_000)


# --- cancellation: between phases, and from inside one ---------------------

def test_cancelling_between_phases_stops_the_scan_and_emits_nothing(
        qtbot, monkeypatch):
    """Interruption requested right after the first phase returns -- the
    isInterruptionRequested() checks between engine.carve_* calls in
    RecoveryWorker.run() are what must catch this. Cutting THOSE checks
    would make this test fail: carve_database_slack and
    carve_structured_records would both still run.

    A threading.Event makes the timing deterministic instead of racing a
    fast fake loop to completion before cancel() gets a chance to run --
    the same technique test_evidence_loader.py's own
    test_cancelling_mid_parse_stops_the_container_loop_and_emits_nothing
    uses for the identical problem on EvidenceLoadWorker. Critically, the
    cancel request comes from THIS (main) thread calling loader.cancel(),
    never from inside the fake engine itself -- reaching into
    loader._worker from the worker thread would race the main thread's own
    assignment of it.
    """
    import threading
    from webcache.shell import recovery_loader as mod

    reached_after_log_phase = threading.Event()
    release = threading.Event()

    class _PausesAfterLogPhase(_FakeRecoveryEngine):
        def carve_transaction_logs(self, db_path, live_urls, progress_callback=None):
            result = super().carve_transaction_logs(
                db_path, live_urls, progress_callback=progress_callback)
            reached_after_log_phase.set()
            release.wait(5)
            return result

    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine", _PausesAfterLogPhase)
    loader = RecoveryLoader()
    loaded_calls = []
    failed_calls = []
    loader.loaded.connect(loaded_calls.append)
    loader.failed.connect(failed_calls.append)

    loader.start(_StubParser())
    assert reached_after_log_phase.wait(5), "the log phase never ran"
    loader.cancel()
    release.set()

    worker = loader._worker
    # Checked against consent._RUNNING_WORKERS, not worker.isFinished()
    # directly -- finished -> deleteLater() can run the C++ object's
    # actual deletion during qtbot's own event-loop pumping while this
    # waits, and touching a possibly-already-deleted QThread wrapper
    # raises. The shared shutdown set is exactly what the worker itself
    # is removed from on finished -- see recovery_loader.RecoveryLoader.
    qtbot.waitUntil(lambda: worker not in consent._RUNNING_WORKERS, timeout=5_000)

    assert loaded_calls == [], "a cancelled scan must never emit rows"
    assert failed_calls == [], "cancellation must not be reported as a failure"
    kinds = [c[0] for c in _FakeRecoveryEngine.calls]
    assert "carve_database_slack" not in kinds
    assert "carve_structured_records" not in kinds


def test_cancelling_mid_phase_stops_the_engines_own_loop(qtbot, monkeypatch):
    """Interruption requested DURING carve_database_slack's own progress
    callback -- the exact mechanism that makes Cancel take effect mid-scan
    rather than only between phases (RecoveryWorker._page_progress calls
    _check_progress, which raises the moment isInterruptionRequested() is
    true). If _check_progress stopped checking, the engine's fake loop
    below would run to its second callback and record it -- this test
    would then fail on the final assertion. Same deterministic
    threading.Event handoff as the test above, for the same reason.
    """
    import threading
    from webcache.shell import recovery_loader as mod

    reached_first_page_callback = threading.Event()
    release = threading.Event()
    ran_past_the_interruption_check = []

    class _PausesDuringPageScan(_FakeRecoveryEngine):
        def carve_database_slack(self, db, db_path, live_urls, progress_callback=None):
            _FakeRecoveryEngine.calls.append(("carve_database_slack",))
            progress_callback(50, 500)
            reached_first_page_callback.set()
            release.wait(5)
            # If cancel() actually reached the worker, THIS call must raise
            # and unwind the loop right here -- not run to completion.
            progress_callback(100, 500)
            ran_past_the_interruption_check.append(1)  # must never execute
            return []

    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine", _PausesDuringPageScan)
    loader = RecoveryLoader()
    loaded_calls = []
    loader.loaded.connect(loaded_calls.append)

    loader.start(_StubParser())
    assert reached_first_page_callback.wait(5), "the page-scan phase never ran"
    loader.cancel()
    release.set()

    worker = loader._worker
    # Checked against consent._RUNNING_WORKERS, not worker.isFinished()
    # directly -- finished -> deleteLater() can run the C++ object's
    # actual deletion during qtbot's own event-loop pumping while this
    # waits, and touching a possibly-already-deleted QThread wrapper
    # raises. The shared shutdown set is exactly what the worker itself
    # is removed from on finished -- see recovery_loader.RecoveryLoader.
    qtbot.waitUntil(lambda: worker not in consent._RUNNING_WORKERS, timeout=5_000)

    assert loaded_calls == []
    assert ran_past_the_interruption_check == [], (
        "the page-scan phase kept running past the interruption check")
    kinds = [c[0] for c in _FakeRecoveryEngine.calls]
    assert "carve_structured_records" not in kinds


# --- stubs are computed on the worker, not the GUI thread -

def test_the_worker_attaches_the_parsers_stubs_to_the_engine_off_the_gui_thread(
        qtbot, monkeypatch):
    """parser.tombstones() walks every leaf of every table -- 166 ms on
    the 30 MB sample. It belongs on the recovery worker, which already
    walks the same parser.db, and the engine must arrive carrying them."""
    import threading
    from webcache.shell import recovery_loader as mod
    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine", _FakeRecoveryEngine)

    stub = {"Table": "Container_4", "KeyColumns": ("EntryId",),
            "KeyValues": (7,)}
    seen_threads = []

    class _ParserWithStubs(_StubParser):
        def tombstones(self):
            seen_threads.append(threading.current_thread())
            return [stub]

    loader = RecoveryLoader()
    received = []
    loader.loaded.connect(received.append)
    with qtbot.waitSignal(loader.loaded, timeout=5_000):
        loader.start(_ParserWithStubs())
    assert getattr(received[0], "tombstones", None) == [stub]
    assert seen_threads and seen_threads[0] is not threading.main_thread()


def test_a_parser_without_tombstones_still_loads(qtbot, monkeypatch):
    from webcache.shell import recovery_loader as mod
    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine", _FakeRecoveryEngine)
    loader = RecoveryLoader()
    received = []
    loader.loaded.connect(received.append)
    with qtbot.waitSignal(loader.loaded, timeout=5_000):
        loader.start(_StubParser())
    assert getattr(received[0], "tombstones", None) == []


def test_the_gui_slot_never_walks_the_tables_itself(qtbot):
    """A raise inside _on_recovery_loaded used to land after the busy UI
    ended and before the engine was kept, discarding the whole scan with
    no message. The slot must not call parser.tombstones() at all."""
    import types
    from webcache.shell.main_window import MainWindow

    calls = []

    class _Parser:
        all_entries = []

        def tombstones(self):
            calls.append(1)
            raise ValueError("unreadable page")

    w = MainWindow()
    qtbot.addWidget(w)
    w._parser = _Parser()
    engine = types.SimpleNamespace(structured_records=[], tombstones=[],
                                   all_artifacts=lambda: [])
    try:
        w._on_recovery_loaded(engine)
    except Exception as exc:                          # noqa: BLE001
        pytest.fail("the GUI slot walked the tables and raised: %r" % exc)
    assert calls == []
    assert w._recovery_engine is engine


# --- the worker stamps carved MSHist records with the zone ----------

def _mshist_engine(rec):
    class _Eng(_FakeRecoveryEngine):
        structured_records = []

        def carve_structured_records(self, db, db_path, progress_callback=None):
            super().carve_structured_records(db, db_path, progress_callback)
            self.structured_records = [rec]

        def all_artifacts(self):
            return []
    return _Eng


def test_the_worker_stamps_carved_mshist_records_with_the_parsers_zone(
        qtbot, monkeypatch):
    from webcache.shell import recovery_loader as mod
    rec = {"MSHistFrom": "2024-06-30", "ModifiedTime_raw": 133641846000000000,
           "ContainerType": "History"}
    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine",
                        _mshist_engine(rec))
    parser = _StubParser()
    parser.derived_tz_offset_seconds = 19800
    loader = RecoveryLoader()
    with qtbot.waitSignal(loader.loaded, timeout=5_000):
        loader.start(parser)
    assert rec.get("TzOffsetSeconds") == 19800
    assert rec["ModifiedTime"] == "2024-06-29 20:00:00 UTC"
    assert rec["ModifiedTimeLocal"] == "2024-06-30 01:30:00 LOCAL"


def test_the_worker_marks_carved_mshist_records_unplaced_without_a_zone(
        qtbot, monkeypatch):
    from webcache.shell import recovery_loader as mod
    rec = {"MSHistFrom": "2024-06-30", "ModifiedTime_raw": 133641846000000000,
           "ContainerType": "History"}
    monkeypatch.setattr(mod.recovery_engine, "RecoveryEngine",
                        _mshist_engine(rec))
    loader = RecoveryLoader()
    with qtbot.waitSignal(loader.loaded, timeout=5_000):
        loader.start(_StubParser())
    assert "TzOffsetSeconds" in rec and rec["TzOffsetSeconds"] is None
    assert rec["ModifiedTime"] == ""
    assert rec["ModifiedTimeLocal"] == "2024-06-30 01:30:00 LOCAL"
