"""Evidence to rows: parsing off the GUI thread, and the History row set.

Turns an opened database into the rows the record views expect, without
blocking the window.

The parsing QThread (EvidenceLoadWorker) is never parented, so a caller
that closes its owner mid-parse cannot destroy a running QThread. It is
tracked in consent._RUNNING_WORKERS, the set consent.shutdown_workers()
sweeps at exit, so a worker still reading a database when the window
closes is asked to stop and given a bounded wait.

LIVE RECORDS ONLY. No carve runs at open: history_rows_from_parser()
returns only entries the live database holds, each with
Origin="Live record". The caller tells HistoryView, through
set_records' `note`, to state in the count line that these are live
records and deleted ones have not yet been recovered (see
main_window.py).
"""
import logging
from urllib.parse import unquote

from PySide6.QtCore import QObject, QThread, Signal

from .. import provenance
from ..engine import (download_decoder, forensic_engine, local_clock,
                      url_intel)
from ..engine.analysis_extra import hsts_visit_evidence
from ..engine.ese_parser import WebCacheParser, filetime_to_dt
from .consent import _RUNNING_WORKERS
from .record_kinds import (K_CERT, K_CONTAINER, K_COOKIE, K_DOWNLOAD,
                           K_FILE_ACCESS, K_HISTORY, K_HSTS)

_LOG = logging.getLogger(__name__)


def history_rows_from_parser(parser):
    """The History row set HistoryView.COLUMNS expects, live records only.

    `parser` needs only an `all_entries` attribute (a list of dicts shaped
    as WebCacheParser._parse_record()/normalise_record() produce them), so
    this is testable against a stub.

    Live History records are those with ContainerType == "History"; each
    has Origin="Live record", which can never be read as carved
    (record_model.py treats a value starting with "Carved" as carved).

    Sixteen keys; at most twenty-one. On CPython 3.14.4 a dict's table
    steps at 11 and at 22 keys (11-21 keys all cost 464 B), so a
    twenty-second key would cost +368 B per row and belongs on `_record`.
    tests/test_row_is_a_record.py enforces this.

    `_record` is the engine's entry dict by reference, never a copy: every
    field History does not show (the *_raw times, the SPS property store,
    the cached file's path, both header blobs) reaches a detail surface
    through it at the cost of one pointer.
    """
    rows = []
    for entry in parser.all_entries:
        if entry.get("ContainerType") != "History":
            continue

        raw_ts, basis = forensic_engine.key_timestamp(entry)
        accessed_utc = filetime_to_dt(raw_ts) if raw_ts else None

        # SPS id 24, or an MSHist record's stored (LOCAL) ModifiedTime --
        # engine/local_clock.py.
        accessed_local = local_clock.local_naive(entry)


        rows.append({
            "CleanUrl": entry.get("CleanUrl") or entry.get("Url") or "",
            "Title": entry.get("SPS_PageTitle") or "",
            "AccessedUtc": accessed_utc,
            "AccessedLocal": accessed_local,
            # The browser's visit counter (SPS id 6) only, None when the
            # record stores none; cache touches are their own column and
            # are never offered as visits.
            "VisitCount": entry.get("SPS_VisitCount"),
            "CacheTouches": entry.get("AccessCount"),
            "Domain": forensic_engine.extract_domain(entry.get("Url") or ""),
            "IsInPrivate": bool(entry.get("IsInPrivate")),
            "Origin": provenance.LIVE_ORIGIN,
            # Only a carved row has a source log; a live row's "Carved
            # from" cell is blank.
            "Source": "",
            # Already decoded by the engine for every parsed record (see
            # ese_parser.normalise_record) -- carried through here so
            # HistoryView's "Has search terms" / "Local files only" quick
            # filter chips have a real field to test, not something
            # invented at the view layer with no data behind it.
            "SearchTerms": entry.get("SearchTerms") or "",
            "IsLocalFile": bool(entry.get("IsLocalFile")),
            # The engine record itself, by reference.
            "_record": entry,
            "_kind": K_HISTORY,
            # Which column the time came from. key_timestamp() falls back
            # from ModifiedTime to AccessedTime to CreationTime and names
            # the one used: "the visit was written" and "the cache entry
            # was touched" are different claims. "" only when the record
            # carries no timestamp.
            "AccessedUtcBasis": basis,
            # Established by the `continue` above rather than read from the
            # entry, so provenance.describe_origin() can explain a live
            # record (as recovery_loader.carved_history_rows does for a
            # carved one).
            "ContainerType": "History",
            # which container holds this record, and the
            # other record of the same visit when one exists (an MSHist
            # record and its History twin) -- 18 keys, inside the bucket.
            "Container": entry.get("ContainerName") or "",
            "SameVisit": local_clock.same_visit_text(entry),
        })
    return rows


def file_access_rows_from_parser(parser):
    """The File Access row set (file-access segment) FileAccessView.
    FILE_ACCESS_COLUMNS expects, live records only. `parser` needs only an
    `all_entries` attribute.

    A row is a local file opened through the browser: entries where
    IsLocalFile is true (decoded for every entry from whether CleanUrl
    starts with "file:", whatever the ContainerType). Local-file accesses
    are logged under the History container, so filtering on ContainerType
    would miss them.

    Every row has Origin="Live record" and Source="", as in
    history_rows_from_parser, so recovered rows
    (recovery_loader.carved_file_access_rows) concatenate directly.

    Sixteen keys; at most twenty-one (see history_rows_from_parser).
    `_record` carries CachedFilePath, CacheFolder, SecureDirectoryName,
    Filename and FileExtension to a detail surface. Each names a location
    on the examined machine, so it is offered for Copy, never Open.
    """
    rows = []
    for entry in parser.all_entries:
        if not entry.get("IsLocalFile"):
            continue

        _raw_ts, basis = forensic_engine.key_timestamp(entry)

        rows.append({
            # UTC, derived for an MSHist record (engine/local_clock.py);
            # None -- a blank cell -- when no zone was recovered, and
            # ModifiedTimeBasis below then carries the reason.
            "ModifiedTime": filetime_to_dt(
                local_clock.utc_raw(entry, "ModifiedTime_raw")),
            "AccessedLocal": local_clock.local_naive(entry),
            # Each counter under its own name, never merged: the browser's
            # visit counter (SPS id 6) and the cache entry's touches.
            "VisitCount": entry.get("SPS_VisitCount"),
            "CacheTouches": entry.get("AccessCount"),
            "CleanUrl": entry.get("CleanUrl") or entry.get("Url") or "",
            # derived, beside the stored value.
            "LocalPath": url_intel.windows_path_from_file_url(
                entry.get("CleanUrl") or entry.get("Url") or ""),
            # Which volume, and what kind of file: both read off the
            # decoded path, so an examiner can filter on them.
            "Drive": url_intel.path_volume(url_intel.windows_path_from_file_url(
                entry.get("CleanUrl") or entry.get("Url") or "")),
            "FileType": url_intel.path_file_type(
                url_intel.windows_path_from_file_url(
                    entry.get("CleanUrl") or entry.get("Url") or "")),
            "Origin": provenance.LIVE_ORIGIN,
            "Source": "",
            "FileSize": entry.get("FileSize"),
            "ContainerId": entry.get("ContainerId"),
            "ContainerName": entry.get("ContainerName") or "",
            "EntryId": entry.get("EntryId"),
            "AccessedTime": filetime_to_dt(entry.get("AccessedTime_raw")),
            "CreationTime": filetime_to_dt(entry.get("CreationTime_raw")),
            "_record": entry,
            "_kind": K_FILE_ACCESS,
            # WHICH COLUMN THE RECORD'S CANONICAL INSTANT CAME FROM, in
            # key_timestamp()'s own words. Read the VALUE, not the key
            # name, for what it asserts: it names the column that won the
            # three-way fallback, which for a file-access record is
            # usually ModifiedTime but is "AccessedTime (cache touch)"
            # whenever ModifiedTime_raw is absent. Unlike History, this
            # row shows all three times in their own columns, so this is
            # the extra fact of which one the engine treats as canonical
            # -- never a claim about the Modified column specifically.
            "ModifiedTimeBasis": basis,
            # the other record of the same visit.
            "SameVisit": local_clock.same_visit_text(entry),
        })
    return rows


def downloads_rows_from_parser(parser):
    """The File Access row set (downloads segment) FileAccessView.
    DOWNLOAD_COLUMNS expects, live records only.

    Entries with ContainerType == "Downloads" (the iedownload container),
    decoded from the entry's ResponseHeaders_raw blob with
    download_decoder.decode_download_blob(), the function ese_parser.
    _parse_record() uses at parse time, rather than read from the entry's
    precomputed Download* fields. DownloadTime there is a formatted string,
    which time filters and sorts cannot compare, and a carved Downloads
    record (recovery_loader.carved_downloads_rows) has only the raw blob,
    so decoding from the blob gives live and carved records the same
    output.

    At most ten keys: a dict's table steps at 11 keys (272 B -> 464 B on
    CPython 3.14.4), so an eleventh belongs on `_record`.

    The reference exhibits held no live Downloads-container records; the
    decode is exercised by unit tests and by carved rows.

    Only the decoder's confidence and GUID are copied onto the row. A
    detail surface can re-run decode_download_blob on `_record`'s blob for
    one record to get every decoded value (guid_offset, download_time_raw,
    notes and strings included).
    """
    rows = []
    for entry in parser.all_entries:
        if entry.get("ContainerType") != "Downloads":
            continue
        blob = entry.get("ResponseHeaders_raw")
        decoded = download_decoder.decode_download_blob(
            blob if isinstance(blob, (bytes, bytearray)) else None)
        rows.append({
            "DownloadTime": decoded.get("download_time_utc"),
            "DownloadPath": decoded.get("local_path") or "",
            "DownloadSize": decoded.get("file_size"),
            "DownloadSourceUrl": decoded.get("source_url") or "",
            "Origin": provenance.LIVE_ORIGIN,
            "Source": "",
            "_record": entry,
            "_kind": K_DOWNLOAD,
            # The decoder's grade ("high"/"medium"/"low"/"none", by how
            # many of the four fields were recovered), shown as its own
            # column like every other graded value.
            "DownloadConfidence": decoded.get("confidence") or "",
            # The join key back from the download record to the URL that
            # produced it.
            "DownloadGuid": decoded.get("guid") or "",
        })
    return rows


def cookie_rows_from_parser(parser):
    """The Cookies row set CookiesView's Cookies segment expects.

    `parser` needs only a `cookie_entries` attribute (dicts shaped as
    WebCacheParser._parse_cookie_table() produces them), so this is
    testable against a stub.

    Expires and LastModified are converted from the *_raw FILETIME ints
    with filetime_to_dt(), so the columns hold datetimes that the time
    operators (before/after/between/on/in the last N days) and sorting can
    compare. filetime_to_dt() returns None for a missing, zero or negative
    FILETIME.

    Domain is the readable, unreversed form; the stored, reversed RDomain
    column is what the Domain column's provenance badge names (see
    cookies.py).

    Nine keys; at most ten (the dict table steps at the 11th). RDomain,
    Flags, EntryId, Table, PartitionId, AppDirectory and both raw
    FILETIMEs reach a detail surface through `_record`.
    """
    rows = []
    for entry in parser.cookie_entries:
        row = {
            "Domain": entry.get("Domain") or "",
            "Name": entry.get("Name") or "",
            "Value": entry.get("Value") or "",
            "Path": entry.get("Path") or "",
            "Expires": filetime_to_dt(entry.get("Expires_raw")),
            "LastModified": filetime_to_dt(entry.get("LastModified_raw")),
            "_record": entry,
            "_kind": K_COOKIE,
            # Bit 0x1 of the cookie's Flags, decoded by ese_parser: whether
            # a cookie was restricted to HTTPS.
            "IsSecure": bool(entry.get("IsSecure")),
        }
        # The value with its percent-escapes decoded, beside the stored
        # one; only when decoding changes it.
        decoded = unquote(row["Value"]) if "%" in row["Value"] else row["Value"]
        if decoded != row["Value"]:
            row["ValueDecoded"] = decoded
        rows.append(row)
    return rows


def hsts_rows_from_parser(parser):
    """The HSTS row set CookiesView's HSTS Pins segment expects.

    `parser` needs `hsts_entries` and `all_entries`.
    hsts_visit_evidence() (engine/analysis_extra.py) decides Corroborated,
    Significance and HostAttribution; this function reshapes its output.

    LastTimeUsed and Expires are converted from the raw FILETIMEs to
    datetimes, since views/cookies.py declares both columns kind="time".

    Expires falls back to the engine's word "never": a pin with no expiry
    stores 0x7FFFFFFFFFFFFFFF, which filetime_to_dt refuses to read as a
    time, and a blank cell would read as "no expiry was recorded" rather
    than "does not expire". record_filter._sort_key orders a mixed column
    without raising.

    Nine keys; at most ten. `_record` is the hsts_entries pin itself, by
    reference, which carries its EntryId, Table and PartitionId.
    """
    rows = []
    for row in hsts_visit_evidence(parser.hsts_entries, parser.all_entries):
        expires = filetime_to_dt(row.get("Expires_raw"))
        rows.append({
            "Domain": row.get("Domain") or "",
            # flags on the row, so the grid says Yes / No
            # in one form and the funnel offers Is Yes / Is No. The
            # engine's own "yes"/"NO" strings stay for the exports.
            "Corroborated": row.get("Corroborated") == "yes",
            "Significance": row.get("Significance") or "",
            "HostAttribution": row.get("HostAttribution") or "",
            "LastTimeUsed": filetime_to_dt(row.get("LastTimeUsed_raw")),
            "Expires": expires if expires is not None
                       else (row.get("Expires") or ""),
            "IncludeSubdomains": row.get("IncludeSubdomains") == "yes",
            "_record": row.get("SourceEntry"),
            "_kind": K_HSTS,
        })
    return rows


def cert_rows_from_parser(parser):
    """The Certificates row set CookiesView's Certificates segment
    expects.

    `parser` needs only a `cert_entries` attribute. ModifiedTime is
    converted from the raw FILETIME as in cookie_rows_from_parser.

    Eight keys; at most ten. The DER certificate (Blob_raw) stays on the
    parser and reaches a detail surface through `_record` as the same
    bytes object. BlobBytes is its measured length, so a column can show
    that a blob exists without copying it.
    """
    rows = []
    for entry in parser.cert_entries:
        blob = entry.get("Blob_raw")
        rows.append({
            "HostPort": entry.get("HostPort") or "",
            "IsCertificate": bool(entry.get("IsCertificate")),
            "Thumbprint": entry.get("Thumbprint") or "",
            "BlobSize": entry.get("BlobSize") or 0,
            "ModifiedTime": filetime_to_dt(entry.get("ModifiedTime_raw")),
            "_record": entry,
            "_kind": K_CERT,
            # len() of the reachable blob. BlobSize above is the engine's
            # recorded figure; a disagreement between the two is itself
            # visible.
            "BlobBytes": len(blob) if isinstance(
                blob, (bytes, bytearray)) else 0,
        })
    return rows


def container_rows_from_parser(parser):
    """The Containers row set ContainersView expects.

    `parser` needs `containers_meta` (the parser's Containers-table rows)
    and `get_container_type(container_id)`, the classification
    parse_all_entries() uses to set every live record's ContainerType, so
    a container's Type here agrees with its records.

    Records is never shown as a bare 0 when the count is unknown:
    meta["RecordCount"] is updated only for a container whose
    Container_<id> table was walked. A container the Containers table
    registers but whose table is absent (HasTable False) was never
    counted, so its count is provenance.CONTAINER_NOT_DETERMINABLE.

    LastAccess and LastScavenge are datetimes converted from the raw
    FILETIMEs _load_containers() keeps, so they sort and filter as times.
    filetime_to_dt() returns None for the 0 a never-scavenged container
    stores, shown blank.

    Eleven keys; at most twenty-one. TableName, Flags, Limit, EntryMaxAge
    and SecureDirectoryNames (which resolve_cache_location uses to place
    a cached file on disk) reach a detail surface through `_record`.
    """
    rows = []
    for meta in parser.containers_meta:
        cid = meta.get("ContainerId")
        has_table = bool(meta.get("HasTable"))
        rows.append({
            "Id": cid,
            "Name": meta.get("Name") or "",
            "Type": parser.get_container_type(cid),
            "Records": (meta.get("RecordCount", 0) if has_table
                       else provenance.CONTAINER_NOT_DETERMINABLE),
            "Size": meta.get("Size"),
            "Partition": meta.get("PartitionId") or "",
            "Directory": meta.get("Directory") or "",
            "LastAccess": filetime_to_dt(meta.get("LastAccessTime_raw")),
            "LastScavenge": filetime_to_dt(meta.get("LastScavengeTime_raw")),
            "_record": meta,
            "_kind": K_CONTAINER,
        })
    return rows


class _LoadCancelled(Exception):
    """Raised from _check_progress inside parser.parse_all_entries()'s
    container loop, to unwind it when interruption is requested. Caught in
    run() and handled like the isInterruptionRequested() checks between
    phases: nothing is reported."""


class EvidenceLoadWorker(QThread):
    """Opens and parses one database, off the GUI thread.

    Unparented (see the module docstring) and cooperative:
    isInterruptionRequested() is checked between open and parse. A
    cancelled load reports nothing; whatever was parsed is incomplete.

    The parse itself is interruptible: parse_all_entries() calls
    `progress_callback` about every 200 records from its container loop,
    and _check_progress below is that callback and the interruption point.

    _parse_modern_tables() (Cookies, HSTS, certificate-store, leak-file
    and AppCache tables) and count_all_tables() run after the container
    loop and do not call it, so interruption during those phases takes
    effect when they finish.
    """
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path, known_hashes=None, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.known_hashes = known_hashes

    def _check_progress(self, parsed, _total):
        """`_total` is 0 while the container loop runs: the parser cannot
        know its total record count in advance without reading every table
        (see WebCacheParser.count_all_tables), so no percentage is
        computed. `parsed` is real: one unit per record parsed."""
        if self.isInterruptionRequested():
            raise _LoadCancelled()
        self.progress.emit(
            "Parsing evidence… %s record(s) parsed so far" % format(parsed, ","))

    def run(self):
        try:
            self.progress.emit("Opening %s…" % self.db_path)
            parser = WebCacheParser()
            parser.open(self.db_path, known_hashes=self.known_hashes)
        except Exception as exc:
            _LOG.warning("Evidence open failed for %s: %s", self.db_path, exc)
            self.failed.emit(str(exc))
            return

        if self.isInterruptionRequested():
            return

        try:
            self.progress.emit("Parsing evidence…")
            parser.parse_all_entries(progress_callback=self._check_progress)
        except _LoadCancelled:
            return
        except Exception as exc:
            _LOG.warning("Evidence parse failed for %s: %s", self.db_path, exc)
            self.failed.emit(str(exc))
            return

        if self.isInterruptionRequested():
            return

        rows = history_rows_from_parser(parser)
        # The derived row sets the views read, computed here so the GUI
        # thread only fills grids (see derived.py).
        self.progress.emit("Preparing views…")
        from . import derived
        derived.precompute_live(
            parser, stopping=self.isInterruptionRequested,
            progress=lambda what: self.progress.emit(
                "Preparing %s…" % what))
        if self.isInterruptionRequested():
            return
        self.loaded.emit({"rows": rows, "parser": parser})


class EvidenceLoader(QObject):
    """The GUI-thread handle. Owns no widgets; connects the worker's
    signals to whoever requested the load, so the shell keeps its
    connect/disconnect bookkeeping in one place per load.

    The worker QThread is unparented and registered in
    consent._RUNNING_WORKERS, like HashWorker (see the module docstring).
    """
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None

    def load(self, db_path, known_hashes=None):
        worker = EvidenceLoadWorker(db_path, known_hashes)
        self._worker = worker
        _RUNNING_WORKERS.add(worker)
        worker.progress.connect(self.progress)
        worker.loaded.connect(self.loaded)
        worker.failed.connect(self.failed)
        worker.finished.connect(lambda: _RUNNING_WORKERS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def cancel(self):
        """Requests interruption only -- never waits. A bounded wait, if
        one is ever needed (application exit), is consent.shutdown_workers'
        job, which this worker is already registered for."""
        if self._worker is not None:
            try:
                self._worker.requestInterruption()
            except RuntimeError:
                # Already gone -- self-deleted via finished -> deleteLater.
                pass
