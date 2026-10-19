"""EvidenceLoader: parsing off the GUI thread, and the row set it hands to
History.

Two things pinned here that nothing else in the suite touches:

1. The row-building logic itself (history_rows_from_parser) -- which
   entries become History rows, that every one is stamped Origin="Live
   record", and that the fields HistoryView.COLUMNS actually reads are all
   present -- tested against a stub parser object rather than a real
   WebCacheParser, because no real WebCacheV01.dat is part of the suite for
   CI to parse.

2. The worker's shutdown discipline -- unparented, tracked in the SAME
   consent._RUNNING_WORKERS set consent.shutdown_workers() already bounds
   at application exit, and self-cleaning via finished -> deleteLater --
   exercised against a real (but not-a-real-ESE-database) file, so
   parser.open() genuinely fails on the worker thread rather than a
   simulated failure standing in for it.
"""
import datetime
import uuid

import pytest
from PySide6.QtCore import QThread

from webcache.shell import consent
from webcache.shell.evidence_loader import (EvidenceLoader,
                                             EvidenceLoadWorker,
                                             downloads_rows_from_parser,
                                             file_access_rows_from_parser,
                                             history_rows_from_parser)


class _StubParser:
    """Just enough of WebCacheParser's surface for history_rows_from_parser
    -- a list of already-parsed entry dicts, shaped the way
    _parse_record()/normalise_record() actually produce them."""

    def __init__(self, entries):
        self.all_entries = entries


def _entry(container_type="History", **overrides):
    base = {
        "ContainerType": container_type,
        "Url": "https://example.com/a",
        "CleanUrl": "https://example.com/a",
        "SPS_PageTitle": "Example",
        "ModifiedTime_raw": 133535904000000000,  # a real-looking FILETIME
        "AccessedTime_raw": 0,
        "CreationTime_raw": 0,
        "SPS_LastVisitLocal_raw": None,
        "SPS_VisitCount": 3,
        "AccessCount": 9,
        "IsInPrivate": False,
    }
    base.update(overrides)
    return base


# --- the row set: History container only, always stamped Live --------------

def test_only_history_container_records_become_rows():
    """A page visited and then deleted was still visited -- but that is the
    carve's job, not this one. What this loader must get right on the LIVE
    side is not pulling in Content/Cookies/other container rows that are
    not History at all."""
    entries = [_entry(container_type="History"),
              _entry(container_type="Content"),
              _entry(container_type="Cookies")]
    rows = history_rows_from_parser(_StubParser(entries))
    assert len(rows) == 1


def test_every_row_is_stamped_live_record():
    rows = history_rows_from_parser(_StubParser([_entry(), _entry()]))
    assert rows
    assert all(r["Origin"] == "Live record" for r in rows)


def test_rows_carry_every_key_historyview_columns_reads():
    """HistoryView.COLUMNS declares CleanUrl, Title, AccessedUtc,
    AccessedLocal, VisitCount, Domain, IsInPrivate, Origin, Source -- a row
    missing any of these renders as a blank cell with nothing on screen to
    say why."""
    rows = history_rows_from_parser(_StubParser([_entry()]))
    row = rows[0]
    for key in ("CleanUrl", "Title", "AccessedUtc", "AccessedLocal",
               "VisitCount", "Domain", "IsInPrivate", "Origin", "Source"):
        assert key in row, "HistoryView.COLUMNS reads %r" % key


def test_rows_carry_search_terms_and_local_file_for_the_quick_filter_chips():
    """History's "Has search terms" / "Local files only" quick-filter
    chips (main_window.py wires them through HistoryView) read these two
    keys -- ese_parser.normalise_record() already decodes both for every
    parsed entry (see evidence_model.py's FIELD_PROVENANCE), this loader
    just has to carry them through rather than drop them on the floor the
    way it did before this test existed."""
    rows = history_rows_from_parser(_StubParser(
        [_entry(SearchTerms="cats", IsLocalFile=True),
         _entry(SearchTerms="", IsLocalFile=False)]))
    assert rows[0]["SearchTerms"] == "cats"
    assert rows[0]["IsLocalFile"] is True
    assert rows[1]["SearchTerms"] == ""
    assert rows[1]["IsLocalFile"] is False


def test_missing_search_terms_and_local_file_read_as_blank_not_a_crash():
    """A stub/legacy entry with neither key must still produce a row --
    absence reads as "no search terms" / "not a local file", the same
    honest-blank convention every other optional field in this row already
    follows (see AccessedLocal, Source)."""
    rows = history_rows_from_parser(_StubParser([_entry()]))
    assert rows[0]["SearchTerms"] == ""
    assert rows[0]["IsLocalFile"] is False


def test_domain_is_derived_from_the_url():
    rows = history_rows_from_parser(_StubParser(
        [_entry(Url="https://msn.com/x", CleanUrl="https://msn.com/x")]))
    assert rows[0]["Domain"] == "msn.com"


def test_title_comes_from_the_sps_page_title():
    rows = history_rows_from_parser(_StubParser(
        [_entry(SPS_PageTitle="My Page Title")]))
    assert rows[0]["Title"] == "My Page Title"


def test_visit_count_prefers_the_sps_id6_count_over_access_count():
    """SPS id6 is what the user actually visited; AccessCount is cache
    touches, a different and noisier claim -- forensic_engine.build_entry_row
    makes the same choice for the same reason."""
    rows = history_rows_from_parser(_StubParser(
        [_entry(SPS_VisitCount=7, AccessCount=99)]))
    assert rows[0]["VisitCount"] == 7


def test_cache_touches_are_never_offered_as_visits():
    """Without the browser's visit counter there is no visit count; the
    AccessCount is shown as cache touches, under its own name."""
    rows = history_rows_from_parser(_StubParser(
        [_entry(SPS_VisitCount=None, AccessCount=42)]))
    assert rows[0]["VisitCount"] is None
    assert rows[0]["CacheTouches"] == 42


def test_accessed_utc_is_a_real_datetime_not_a_preformatted_string():
    """HistoryView's AccessedUtc column is kind="time"; record_filter.py's
    time operators compare actual datetime objects. A pre-formatted string
    (filetime_to_str's own output) would silently break every date-based
    filter and sort on this column instead of raising anywhere visible."""
    rows = history_rows_from_parser(_StubParser([_entry()]))
    assert isinstance(rows[0]["AccessedUtc"], datetime.datetime)


def test_a_record_with_no_usable_timestamp_gets_none_not_a_crash():
    rows = history_rows_from_parser(_StubParser(
        [_entry(ModifiedTime_raw=0, AccessedTime_raw=0, CreationTime_raw=0)]))
    assert rows[0]["AccessedUtc"] is None


def test_accessed_local_comes_from_the_sps_id24_local_timestamp():
    rows = history_rows_from_parser(_StubParser(
        [_entry(SPS_LastVisitLocal_raw=133535925000000000)]))
    assert isinstance(rows[0]["AccessedLocal"], datetime.datetime)


def test_accessed_local_is_none_when_no_sps_blob_was_present():
    rows = history_rows_from_parser(_StubParser(
        [_entry(SPS_LastVisitLocal_raw=None)]))
    assert rows[0]["AccessedLocal"] is None


def test_source_is_blank_for_a_live_record():
    """'Carved from' only means something for a carved row; a live record
    must not show a fabricated source file."""
    rows = history_rows_from_parser(_StubParser([_entry()]))
    assert rows[0]["Source"] == ""


# --- the worker: unparented, tracked in the shared shutdown set ------------

def test_worker_is_never_parented(qtbot):
    """See consent.py's own docstring: a parented QThread destroyed while
    still running is undefined behaviour, not a clean abort. The same
    cancel-safe pattern applies here."""
    worker = EvidenceLoadWorker("nonexistent.dat")
    assert worker.parent() is None


def test_cancel_requests_interruption_on_the_worker(qtbot):
    """EvidenceLoader.cancel() must call requestInterruption() on its
    worker. Proved with a spy rather than the real QThread's own
    isInterruptionRequested(): Qt's requestInterruption() is a documented
    no-op on a thread that was never started (QThreadPrivate bails out
    when `!running`), which a real, never-started EvidenceLoadWorker
    always is here -- that would make the assertion pass or fail on an
    accident of Qt's internal thread state rather than on whether
    cancel() actually calls through to the worker at all."""
    calls = []

    class _SpyWorker:
        def requestInterruption(self):
            calls.append(1)

    loader = EvidenceLoader()
    loader._worker = _SpyWorker()
    loader.cancel()
    assert calls == [1]


def test_cancel_before_any_load_does_not_raise(qtbot):
    """No worker has ever been started -- cancel() must be a safe no-op,
    not an AttributeError waiting for the first click of a Cancel button
    that has nothing to cancel yet."""
    loader = EvidenceLoader()
    loader.cancel()  # must not raise


def test_a_bogus_database_fails_cleanly_off_the_gui_thread(qtbot, tmp_path):
    """No real WebCacheV01.dat is part of the test suite; a file that is not a real ESE database is the deterministic, always
    available way to exercise the real failure path end to end --
    parser.open() raises for real, on the worker thread, and .failed
    carries an actual message rather than a simulated one."""
    bogus = tmp_path / "garbage.dat"
    bogus.write_bytes(b"\x00" * 128)
    loader = EvidenceLoader()
    messages = []
    loader.failed.connect(messages.append)
    with qtbot.waitSignal(loader.failed, timeout=10_000):
        loader.load(str(bogus))
    assert messages and messages[0]


def test_a_bogus_database_never_emits_loaded(qtbot, tmp_path):
    bogus = tmp_path / "garbage_2.dat"
    bogus.write_bytes(b"\x00" * 128)
    loader = EvidenceLoader()
    loaded_calls = []
    loader.loaded.connect(loaded_calls.append)
    with qtbot.waitSignal(loader.failed, timeout=10_000):
        loader.load(str(bogus))
    assert loaded_calls == []


def test_load_registers_the_worker_in_the_shared_shutdown_set_and_self_cleans(
        qtbot, tmp_path):
    """The loader worker is registered with consent.shutdown_workers, so
    application exit bounds it. consent.shutdown_workers() only ever
    iterates consent._RUNNING_WORKERS -- so a loader worker that never
    lands in that set would silently outlive application exit, as the
    hashing worker would. Proved against the
    same real failure path as the tests above, not simulated."""
    bogus = tmp_path / "not_really_a_database.dat"
    bogus.write_bytes(b"not an ese database")
    loader = EvidenceLoader()
    with qtbot.waitSignal(loader.failed, timeout=10_000):
        loader.load(str(bogus))
        qtbot.waitUntil(lambda: loader._worker is not None, timeout=2_000)
        assert loader._worker in consent._RUNNING_WORKERS
    worker = loader._worker
    qtbot.waitUntil(lambda: worker not in consent._RUNNING_WORKERS, timeout=5_000)


def test_shutdown_workers_reaches_a_registered_loader_worker(qtbot, tmp_path):
    """Not re-proving shutdown_workers' own bounded-exit mechanics end to
    end (test_shutdown.py already does that exhaustively, for cooperative
    AND stubborn workers) -- proving only that consent.shutdown_workers()
    genuinely sees an EvidenceLoader worker as one of its own, by calling
    it directly rather than waiting for a real application exit."""
    bogus = tmp_path / "not_really_a_database_2.dat"
    bogus.write_bytes(b"not an ese database")
    loader = EvidenceLoader()
    loader.load(str(bogus))
    qtbot.waitUntil(lambda: loader._worker is not None, timeout=2_000)
    worker = loader._worker
    # This tiny file fails almost immediately; give it a moment to land in
    # the set before sweeping, without depending on .failed having fired
    # yet (shutdown_workers must work regardless of that race).
    stuck = consent.shutdown_workers(timeout_ms=3_000)
    assert worker not in stuck


# --- a failure AFTER a successful open ------------------
# parser.open() succeeding is not the whole story -- a table that breaks
# partway through parse_all_entries() (a corrupt catalog, a column that
# does not decode, anything) must surface exactly the same way `.failed`
# already does for an open failure. Cheap to prove without a real,
# corrupt-but-openable ESE exhibit (there is none on this machine, and
# constructing a byte-exact one that opens but breaks mid-parse is not a
# reasonable ask): stub WebCacheParser itself, at the name
# evidence_loader.py actually imports it under, rather than constructing
# such a file.

def test_a_parse_time_failure_after_a_successful_open_also_reaches_failed(
        qtbot, monkeypatch, tmp_path):
    from webcache.shell import evidence_loader as mod

    class _OpensOkButParseFails:
        def open(self, path, known_hashes=None):
            return True

        def parse_all_entries(self, progress_callback=None):
            raise RuntimeError("Container_7: table catalog is corrupt")

    monkeypatch.setattr(mod, "WebCacheParser", _OpensOkButParseFails)
    loader = EvidenceLoader()
    messages = []
    loaded_calls = []
    loader.failed.connect(messages.append)
    loader.loaded.connect(loaded_calls.append)
    with qtbot.waitSignal(loader.failed, timeout=5_000):
        loader.load(str(tmp_path / "whatever.dat"))
    assert messages and "corrupt" in messages[0]
    assert loaded_calls == []


# --- granular progress: the parser's own progress_callback, wired ----------
# WebCacheParser.parse_all_entries() already accepted an optional
# progress_callback -- called every ~200 records from inside its container
# loop -- before this task started. Nothing ever passed one in: the
# component built and never wired. These tests prove the wiring, not the parser's own
# looping (that belongs to ese_parser's own suite).

def test_progress_callback_is_actually_passed_to_parse_all_entries(
        qtbot, monkeypatch, tmp_path):
    """If EvidenceLoadWorker stopped passing progress_callback through,
    parse_all_entries would receive None and this assertion would fail --
    proving the wiring exists, not just that a message eventually shows up
    from something else."""
    from webcache.shell import evidence_loader as mod

    seen = {}

    class _RecordsWhetherACallbackArrived:
        def open(self, path, known_hashes=None):
            return True

        def parse_all_entries(self, progress_callback=None):
            seen["callback"] = progress_callback
            self.all_entries = []

    monkeypatch.setattr(mod, "WebCacheParser", _RecordsWhetherACallbackArrived)
    loader = mod.EvidenceLoader()
    with qtbot.waitSignal(loader.loaded, timeout=5_000):
        loader.load(str(tmp_path / "whatever.dat"))
    assert seen.get("callback") is not None


def test_progress_messages_report_a_genuine_running_record_count(
        qtbot, monkeypatch, tmp_path):
    """The status text must carry a REAL number -- one that actually grows
    with records genuinely parsed -- never a fabricated percentage (there
    is no cheap total record count available up front; see
    _check_progress's own docstring)."""
    from webcache.shell import evidence_loader as mod

    class _ReportsTwice:
        def open(self, path, known_hashes=None):
            return True

        def parse_all_entries(self, progress_callback=None):
            progress_callback(200, 0)
            progress_callback(400, 0)
            self.all_entries = []

    monkeypatch.setattr(mod, "WebCacheParser", _ReportsTwice)
    loader = mod.EvidenceLoader()
    messages = []
    loader.progress.connect(messages.append)
    with qtbot.waitSignal(loader.loaded, timeout=5_000):
        loader.load(str(tmp_path / "whatever.dat"))

    parse_messages = [m for m in messages if "parsed so far" in m]
    assert "200" in parse_messages[0]
    assert "400" in parse_messages[1]
    # No invented "%" or "of NNNN" anywhere -- total record count is never
    # known up front (see the docstring on _check_progress).
    assert not any("%" in m for m in messages)


def test_cancelling_mid_parse_stops_the_container_loop_and_emits_nothing(
        qtbot, monkeypatch):
    """Before this fix, isInterruptionRequested() was only checked BETWEEN
    open() and parse_all_entries() -- never DURING it -- so Cancel on a
    multi-million-record exhibit had no effect until the whole parse
    finished on its own. This proves the callback now doubles as the
    interruption point, genuinely unwinding the loop mid-parse rather than
    only hiding a result the parser went on computing anyway.

    A threading.Event makes the timing deterministic instead of racing a
    fast fake loop to completion before cancel() gets a chance to run --
    the same technique test_consent.py's
    test_cancelling_mid_hash_does_not_accept uses for the identical
    problem on HashWorker.
    """
    import threading

    from webcache.shell import consent
    from webcache.shell import evidence_loader as mod

    reached_first_callback = threading.Event()
    release = threading.Event()
    ran_past_the_interruption_check = []

    class _SlowParser:
        def open(self, path, known_hashes=None):
            return True

        def parse_all_entries(self, progress_callback=None):
            progress_callback(200, 0)  # proves the loop genuinely started
            reached_first_callback.set()
            release.wait(5)
            # If cancel() actually reached the worker, THIS call must raise
            # and unwind the loop right here -- not run to completion.
            progress_callback(400, 0)
            ran_past_the_interruption_check.append(1)  # must never execute
            self.all_entries = []

    monkeypatch.setattr(mod, "WebCacheParser", _SlowParser)
    loader = mod.EvidenceLoader()
    loaded_calls = []
    failed_calls = []
    loader.loaded.connect(loaded_calls.append)
    loader.failed.connect(failed_calls.append)
    loader.load("whatever.dat")

    assert reached_first_callback.wait(5), \
        "parse never reached its first progress callback"
    loader.cancel()
    release.set()

    worker = loader._worker
    qtbot.waitUntil(lambda: worker not in consent._RUNNING_WORKERS, timeout=5_000)
    qtbot.wait(100)  # let any already-posted signals flush

    assert loaded_calls == [], "a cancelled load must never emit rows"
    assert failed_calls == [], "cancellation must not be reported as a failure"
    assert ran_past_the_interruption_check == [], (
        "the parse loop kept running past the interruption check -- "
        "Cancel only stopped it between phases, not mid-parse")


# --- file_access_rows_from_parser: IsLocalFile records, live, stamped ------
#
# File Access shows files OPENED THROUGH THE BROWSER -- entries whose
# CleanUrl is a file:// reference (IsLocalFile, decoded by ese_parser.
# normalise_record/_parse_record for every entry regardless of which
# container it lives in). On the sample exhibit these are all logged
# under the History container (a file:// page visited through the
# browser still gets a History row) -- filtering on IsLocalFile directly,
# not on any one ContainerType, is what makes this work regardless of
# which container a given exhibit happens to file them under.

def _fa_entry(is_local_file=True, **overrides):
    base = {
        "ContainerType": "History",
        "IsLocalFile": is_local_file,
        "CleanUrl": "file:///C:/Users/alice/Desktop/notes.txt",
        "ModifiedTime_raw": 133535904000000000,
        "AccessedTime_raw": 133535904000000000,
        "CreationTime_raw": 0,
        "SPS_LastVisitLocal_raw": None,
        "SPS_VisitCount": 2,
        "AccessCount": 5,
        "FileSize": 1024,
        "ContainerId": 3,
        "ContainerName": "Content",
        "EntryId": 7,
    }
    base.update(overrides)
    return base


def test_only_local_file_entries_become_file_access_rows():
    entries = [_fa_entry(is_local_file=True), _fa_entry(is_local_file=False)]
    rows = file_access_rows_from_parser(_StubParser(entries))
    assert len(rows) == 1


def test_a_local_file_entry_becomes_a_row_regardless_of_container_type():
    """The sample exhibit files every observed local-file access under the
    History container -- IsLocalFile, not ContainerType, is the real
    criterion (see the section docstring above)."""
    entries = [_fa_entry(is_local_file=True, ContainerType="Content"),
              _fa_entry(is_local_file=True, ContainerType="History")]
    rows = file_access_rows_from_parser(_StubParser(entries))
    assert len(rows) == 2


def test_every_file_access_row_is_stamped_live_record():
    rows = file_access_rows_from_parser(_StubParser([_fa_entry(), _fa_entry()]))
    assert rows
    assert all(r["Origin"] == "Live record" for r in rows)


def test_source_is_blank_for_a_live_file_access_record():
    rows = file_access_rows_from_parser(_StubParser([_fa_entry()]))
    assert rows[0]["Source"] == ""


def test_file_access_rows_carry_every_key_the_view_reads():
    rows = file_access_rows_from_parser(_StubParser([_fa_entry()]))
    row = rows[0]
    for key in ("ModifiedTime", "AccessedLocal", "VisitCount", "CacheTouches",
                "CleanUrl",
               "Origin", "Source", "FileSize", "ContainerId", "ContainerName",
               "EntryId", "AccessedTime", "CreationTime"):
        assert key in row, "FileAccessView's file-access columns read %r" % key


def test_modified_time_is_a_real_datetime_not_a_preformatted_string():
    rows = file_access_rows_from_parser(_StubParser([_fa_entry()]))
    assert isinstance(rows[0]["ModifiedTime"], datetime.datetime)


def test_accessed_and_created_time_are_real_datetimes_too():
    rows = file_access_rows_from_parser(_StubParser([_fa_entry(
        AccessedTime_raw=133535904000000000, CreationTime_raw=133535904000000000)]))
    assert isinstance(rows[0]["AccessedTime"], datetime.datetime)
    assert isinstance(rows[0]["CreationTime"], datetime.datetime)


def test_a_record_with_no_usable_modified_time_gets_none_not_a_crash():
    rows = file_access_rows_from_parser(_StubParser([_fa_entry(ModifiedTime_raw=0)]))
    assert rows[0]["ModifiedTime"] is None


def test_accessed_local_comes_from_the_sps_id24_local_timestamp():
    rows = file_access_rows_from_parser(_StubParser(
        [_fa_entry(SPS_LastVisitLocal_raw=133535925000000000)]))
    assert isinstance(rows[0]["AccessedLocal"], datetime.datetime)


def test_accessed_local_is_none_when_no_sps_blob_was_present():
    rows = file_access_rows_from_parser(_StubParser(
        [_fa_entry(SPS_LastVisitLocal_raw=None)]))
    assert rows[0]["AccessedLocal"] is None


def test_opens_and_cache_touches_are_separate_counters():
    rows = file_access_rows_from_parser(_StubParser(
        [_fa_entry(SPS_VisitCount=7, AccessCount=99)]))
    assert (rows[0]["VisitCount"], rows[0]["CacheTouches"]) == (7, 99)


def test_cache_touches_are_never_offered_as_opens():
    rows = file_access_rows_from_parser(_StubParser(
        [_fa_entry(SPS_VisitCount=None, AccessCount=42)]))
    assert (rows[0]["VisitCount"], rows[0]["CacheTouches"]) == (None, 42)


def test_clean_url_is_the_local_file_path():
    rows = file_access_rows_from_parser(_StubParser(
        [_fa_entry(CleanUrl="file:///D:/case/evidence.jpg")]))
    assert rows[0]["CleanUrl"] == "file:///D:/case/evidence.jpg"


def test_file_size_container_and_entry_identity_pass_through():
    rows = file_access_rows_from_parser(_StubParser([_fa_entry(
        FileSize=2048, ContainerId=9, ContainerName="Content", EntryId=41)]))
    row = rows[0]
    assert row["FileSize"] == 2048
    assert row["ContainerId"] == 9
    assert row["ContainerName"] == "Content"
    assert row["EntryId"] == 41


def test_no_local_file_entries_means_no_file_access_rows():
    rows = file_access_rows_from_parser(_StubParser(
        [_fa_entry(is_local_file=False)]))
    assert rows == []


# --- downloads_rows_from_parser: Downloads container, decoded fresh --------
#
# Live ese_parser entries already carry pre-decoded DownloadPath/
# DownloadSourceUrl/DownloadSize/DownloadTime -- but DownloadTime there is
# a preformatted UTC-suffixed STRING (ese_parser.stamp_str), not a real
# datetime, and a carved Downloads record (recovery_loader.py's own
# counterpart) never gets those pre-decoded fields at all (struct_carver
# only recovers the raw ResponseHeaders blob). Decoding straight from
# ResponseHeaders_raw here -- the same blob ese_parser itself decoded
# once already -- gives ONE code path that works identically for a live
# entry and a carved one, rather than two that silently diverge.

#: A fixed GUID, not uuid.uuid4() -- see test_recovery_loader.py's own
#: _FIXED_GUID comment for why a random one is a rare, non-deterministic
#: flake here rather than genuine test coverage.
_FIXED_GUID = uuid.UUID("12345678-1234-5678-1234-567812345678").bytes_le


def _download_blob(path=r"C:\Users\alice\Downloads\report.pdf",
                   url="https://example.com/report.pdf", size=45678,
                   when=None):
    import struct

    when = when or datetime.datetime(2024, 6, 1, 10, 30, 0,
                                     tzinfo=datetime.timezone.utc)
    epoch = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
    ft = int((when - epoch).total_seconds() * 10_000_000)
    header = _FIXED_GUID + struct.pack("<Q", ft) + struct.pack("<I", size)
    strings = path.encode("ascii") + b"\x00" + url.encode("ascii") + b"\x00"
    return header + strings


def _dl_entry(container_type="Downloads", **overrides):
    base = {
        "ContainerType": container_type,
        "ResponseHeaders_raw": _download_blob(),
    }
    base.update(overrides)
    return base


def test_only_downloads_container_entries_become_download_rows():
    entries = [_dl_entry(container_type="Downloads"),
              _dl_entry(container_type="Content"),
              _dl_entry(container_type="History")]
    rows = downloads_rows_from_parser(_StubParser(entries))
    assert len(rows) == 1


def test_every_download_row_is_stamped_live_record():
    rows = downloads_rows_from_parser(_StubParser([_dl_entry(), _dl_entry()]))
    assert rows
    assert all(r["Origin"] == "Live record" for r in rows)
    assert all(r["Source"] == "" for r in rows)


def test_download_rows_carry_every_key_the_view_reads():
    rows = downloads_rows_from_parser(_StubParser([_dl_entry()]))
    row = rows[0]
    for key in ("DownloadTime", "DownloadPath", "DownloadSize",
               "DownloadSourceUrl", "Origin", "Source"):
        assert key in row, "FileAccessView's downloads columns read %r" % key


def test_download_time_decodes_to_a_real_datetime():
    when = datetime.datetime(2023, 11, 4, 8, 15, 0, tzinfo=datetime.timezone.utc)
    rows = downloads_rows_from_parser(_StubParser(
        [_dl_entry(ResponseHeaders_raw=_download_blob(when=when))]))
    assert isinstance(rows[0]["DownloadTime"], datetime.datetime)
    assert rows[0]["DownloadTime"] == when


def test_download_path_and_source_and_size_decode_from_the_blob():
    rows = downloads_rows_from_parser(_StubParser([_dl_entry(
        ResponseHeaders_raw=_download_blob(
            path=r"D:\evidence\case12\bill.pdf",
            url="https://portal.example/bill.pdf", size=9001))]))
    row = rows[0]
    assert row["DownloadPath"] == r"D:\evidence\case12\bill.pdf"
    assert row["DownloadSourceUrl"] == "https://portal.example/bill.pdf"
    assert row["DownloadSize"] == 9001


def test_a_missing_or_undecodable_blob_gives_blanks_not_a_crash():
    rows = downloads_rows_from_parser(_StubParser(
        [_dl_entry(ResponseHeaders_raw=None)]))
    row = rows[0]
    assert row["DownloadTime"] is None
    assert row["DownloadPath"] == ""
    assert row["DownloadSourceUrl"] == ""
    assert row["DownloadSize"] is None


def test_no_downloads_entries_means_no_download_rows():
    rows = downloads_rows_from_parser(_StubParser([_dl_entry(container_type="Content")]))
    assert rows == []
