"""Running the carve: deliberate, cancellable, off the GUI thread.

recovery_engine.py carves deleted records by transaction-log replay and
unallocated-page structure carving. This module provides the worker that
runs a scan and the functions that turn its results into the row shapes
the record views draw.

WHEN A SCAN RUNS. A scan reads every unallocated page of the database and
every transaction log. It starts after an open when the Open evidence
dialog's recovery box is ticked (the default), and can be run again from
Evidence > Recover deleted records or the Deleted Records view's button.
Every route goes through MainWindow._start_recovery and one
RecoveryLoader.

RecoveryWorker is an unparented QThread tracked in
consent._RUNNING_WORKERS (the set consent.shutdown_workers() sweeps at
exit), and cooperative: isInterruptionRequested() is checked between
phases and from each phase's progress_callback, since each of the three
passes (transaction logs, database slack, structured reconstruction) is
itself expensive.

CANCEL DISCARDS. An interrupted scan reports nothing (no `loaded`
signal), as a cancelled load does. Partial results would be
indistinguishable on screen from a completed scan, and a partial record
set must never read as complete. An interrupted scan can be run again.

NO PERCENTAGE. carve_database_slack knows its page count in advance, but
carve_transaction_logs and carve_structured_records do not, so the scan
shows an indeterminate bar (owned by MainWindow) with real counts in the
status text: pages scanned, log files processed, candidate records
scanned.
"""
import logging

from PySide6.QtCore import QObject, QThread, Signal

from ..engine import (download_decoder, forensic_engine, local_clock,
                      recovery_engine, url_intel)
from ..engine.ese_parser import filetime_to_dt, format_cell
from ..provenance import (ABSENCE_NOT_DETERMINABLE, ABSENCE_NOT_RECOVERED,
                          CARVED_ORIGIN, CONTAINER_NOT_DETERMINABLE,
                          is_absence)
from .consent import _RUNNING_WORKERS
from .record_kinds import K_CARVED_STRING, K_CARVED_STRUCT, K_TOMBSTONE

_LOG = logging.getLogger(__name__)

#: The Origin every carved row carries. record_model.py and
#: provenance.describe_origin() treat any value starting with "Carved" as
#: carved. Defined in provenance.py, which detail_fields.py can import
#: (this module imports PySide6), and re-exported here under this name.


def carved_history_rows(engine):
    """Carved History records, with the same keys as
    evidence_loader.history_rows_from_parser()'s live rows, so MainWindow
    merges the two into one row set for HistoryView.

    Only engine.structured_records are candidates: a structured record is
    a whole reconstructed row whose ContainerId resolves to a real
    ContainerType (RecoveryEngine.set_container_metadata()). A string
    carved from page slack or a transaction log has no ContainerId, so it
    cannot be filed under History; it is shown in Deleted Records
    (deleted_records_rows below).
    """
    rows = []
    for entry in engine.structured_records:
        if entry.get("ContainerType") != "History":
            continue
        raw_ts, basis = forensic_engine.key_timestamp(entry)
        accessed_utc = filetime_to_dt(raw_ts) if raw_ts else None

        # SPS id 24, or an MSHist record's stored (LOCAL) ModifiedTime --
        # engine/local_clock.py.
        accessed_local = local_clock.local_naive(entry)


        # forensic_engine.carved_inprivate: the live bit rule, and not
        # "No" when the carve did not recover Flags.
        known = forensic_engine.carved_inprivate(entry)

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
            "Domain": forensic_engine.extract_domain(
                entry.get("Url") or entry.get("CleanUrl") or ""),
            # The same bit test _parse_record() uses for a live record --
            # see ese_parser.py: bit 0x08 is InPrivate only on a History
            # record, which every row here already is.
            "IsInPrivate": (ABSENCE_NOT_DETERMINABLE if known is None
                            else known),
            # "History" is established by the check above (only a record
            # whose resolved ContainerType is History reaches here), so
            # provenance.describe_origin() states the container as known
            # (see CONTAINER_NOT_DETERMINABLE in provenance.py).
            "ContainerType": "History",
            "Origin": CARVED_ORIGIN,
            "Source": entry.get("Source") or "",
            "Offset": entry.get("Offset"),
            "Page": entry.get("Page"),
            "Method": entry.get("RecoverySource") or "",
            "Confidence": entry.get("Confidence") or "",
            # carve_structured_records() builds every entry through the
            # same normalise_record() as a live row (recovery_engine.py), so
            # SearchTerms/IsLocalFile are decoded from this row's CleanUrl
            # and History's quick-filter chips apply to carved rows too.
            "SearchTerms": entry.get("SearchTerms") or "",
            "IsLocalFile": bool(entry.get("IsLocalFile")),
            # The carved record itself, by reference. UrlHealthNote,
            # UrlSalvaged, UrlSalvageNote, CarvedFieldsDerived,
            # RecordEndMode, InLiveDb, NearbyFiletime_raw and the
            # reconstructed columns all arrive through it.
            "_record": entry,
            "_kind": K_CARVED_STRUCT,
            "AccessedUtcBasis": basis,
            # A row key rather than left on _record: it decides whether
            # this row's URL can be read as a recorded URL at all.
            # normalise_record computes it for every carved record
            # ("intact", or the reason it is not).
            "UrlHealth": entry.get("UrlHealth") or "",
            # The container, and the other carved
            # record of the same visit (stamp_recovered_clock pairs them).
            "Container": entry.get("ContainerName") or "",
            "SameVisit": local_clock.same_visit_text(entry),
        })
    # Carved copies (same clean URL, same key timestamp, same container)
    # are counted on every member and never merged: each is its own
    # finding at its own offset. The first says how many; the rest say
    # which copy they are, which is what "Hide duplicate copies" hides.
    # The container is part of the key: an MSHist record and its History
    # twin share a URL and, once the MSHist UTC is derived, a time, and are
    # one visit in two containers (linked by SameVisit), not copies. A
    # record with no usable time is never grouped on its URL alone, and
    # the label says what was compared; no bytes were compared.
    return mark_copies(rows, "AccessedUtc")


def mark_copies(rows, time_key):
    """Label carved copies (same clean URL, same `time_key`, same
    container) on every member (see carved_history_rows). History and File
    Access both use it, so one rule decides what "Hide duplicate copies"
    hides."""
    groups = {}
    for row in rows:
        row["Copies"] = ""
        if row.get(time_key) is None:
            continue
        record = row["_record"]
        where = (record.get("ContainerName")
                 or (record.get("MSHistFrom"), record.get("MSHistTo")))
        groups.setdefault((row["CleanUrl"], row[time_key], where),
                          []).append(row)
    for members in groups.values():
        if len(members) == 1:
            continue
        members[0]["Copies"] = COPIES_FIRST % len(members)
        for index, row in enumerate(members[1:], 2):
            row["Copies"] = "copy %d of %d" % (index, len(members))
    return rows


def carved_file_access_rows(engine):
    """Carved File Access records (the file-access segment), with the same
    keys as evidence_loader.file_access_rows_from_parser()'s live rows, so
    MainWindow merges the two as it does for History.

    carve_structured_records() runs every structured record through the
    same normalise_record() as a live entry (recovery_engine.
    _normalise_carved), so IsLocalFile is resolved on a carved row exactly
    as on a live one, from the same CleanUrl test.
    """
    rows = []
    for entry in engine.structured_records:
        if not entry.get("IsLocalFile"):
            continue

        _raw_ts, basis = forensic_engine.key_timestamp(entry)

        rows.append({
            # UTC, derived for an MSHist record (engine/local_clock.py).
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
            "Origin": CARVED_ORIGIN,
            "Source": entry.get("Source") or "",
            # the carve location on the row itself, for the optional
            # Offset/Page/Method grid columns (19 keys; the ceiling is 21).
            "Offset": entry.get("Offset"),
            "Page": entry.get("Page"),
            "Method": entry.get("RecoverySource") or "",
            "FileSize": entry.get("FileSize"),
            "ContainerId": entry.get("ContainerId"),
            "ContainerName": entry.get("ContainerName") or "",
            "EntryId": entry.get("EntryId"),
            "AccessedTime": filetime_to_dt(entry.get("AccessedTime_raw")),
            "CreationTime": filetime_to_dt(entry.get("CreationTime_raw")),
            # The same four keys file_access_rows_from_parser adds, in the
            # same order and meaning, so a merged set behaves the same
            # whichever half a row came from. UrlHealth is not a row key
            # here: it reaches a detail surface through _record, as on the
            # live side.
            "_record": entry,
            "_kind": K_CARVED_STRUCT,
            "ModifiedTimeBasis": basis,
            "SameVisit": local_clock.same_visit_text(entry),
        })
    # Later copies of an already listed record are labelled, keyed on the
    # cache-write time, the key timestamp History's copies are grouped on.
    return mark_copies(rows, "ModifiedTime")


def file_text_only_count(engine):
    """Local-file addresses carved as TEXT alone: whole stored addresses
    ("Visited: user@file:///...") with no record around them, so no time
    or container to place them by. Domains counts them (1,957 on a real
    machine); File Access, which lists records, cannot (1,573) -- this is
    the number between, for the count line to state."""
    count = 0
    for artifact in engine.all_artifacts():
        url = forensic_engine.clean_url(str(artifact.get("Url") or ""))
        if (url or "").lower().startswith("file:///"):
            count += 1
    return count


def file_access_note(live, recovered, text_only):
    """File Access's count line after a recovery scan."""
    note = "%s live, %s recovered" % (format(live, ","), format(recovered, ","))
    if text_only:
        note += (" — %s more local-file address%s recovered as text alone, "
                 "with no record to place %s by, %s listed in Deleted Records"
                 % (format(text_only, ","), "" if text_only == 1 else "es",
                    "it" if text_only == 1 else "them",
                    "is" if text_only == 1 else "are"))
    return note


#: The first member of a carved copy group.
COPIES_FIRST = "%d copies (same URL, time and container)"


def stamp_recovered_clock(engine, parser):
    """Stamp every structured carved MSHist record with the offset its UTC
    is derived with, as parse_all_entries stamps the live ones: same zone,
    same History observations, same per-record choice (see
    engine/local_clock.py). Returns the count.

    Structured carves only: a string carve has no ModifiedTime, and
    engine.all_artifacts() builds fresh dicts on every call."""
    return local_clock.stamp_local_clock(
        getattr(engine, "structured_records", None) or (),
        getattr(parser, "derived_tz_offset_seconds", None),
        getattr(parser, "zone_observations", None))


def carved_downloads_rows(engine):
    """Carved File Access records (the downloads segment), shaped like
    evidence_loader.downloads_rows_from_parser()'s live rows: structured
    records whose resolved ContainerType is "Downloads".

    Decoded from entry["ResponseHeaders_raw"] with download_decoder.
    decode_download_blob(), as on the live side. A carved Downloads entry
    has only the raw blob (struct_carver.carve_records() does not run
    ese_parser's decode pass), so decoding it is the only source of these
    values.
    """
    rows = []
    for entry in engine.structured_records:
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
            "Origin": CARVED_ORIGIN,
            "Source": entry.get("Source") or "",
            "_record": entry,
            "_kind": K_CARVED_STRUCT,
            # The same two decoder values the live side copies onto its
            # rows (see evidence_loader.downloads_rows_from_parser). At most
            # ten keys: the dict table steps at the eleventh.
            "DownloadConfidence": decoded.get("confidence") or "",
            "DownloadGuid": decoded.get("guid") or "",
        })
    return rows


#: A stub's Method: always this literal, never a per-row string --
#: unlike carved_history_rows/carved_history_rows (RecoverySource, the
#: engine's own words), a tombstone has no engine-supplied method to
#: report. It merely names what the row IS, so the sample-of-one
#: allocation cost is the same argument record_kinds.py's own module
#: docstring already makes for K_HISTORY et al.
TOMBSTONE_METHOD = "Deleted-record stub (b-tree key only)"


def stub_artifact(stub):
    """The one export and screen dict for a deleted-record stub.

    deleted_records_rows (the screen) and MainWindow._recovered_artifacts
    (every export) both build from this, so a stub's File, Offset, Page,
    Confidence and container read the same everywhere.

    Confidence names the key the stub proves ("exact key: UrlHash X,
    EntryId Y"), so writers without key columns (the xlsx Recovered
    sheet, recovered_csv, the PDF) still state which row was deleted.
    Source is the evidence file (WebCacheParser.tombstones() supplies it);
    TableName and ContainerName are the table.
    """
    stub = stub or {}
    table = stub.get("Table") or ""
    columns = tuple(stub.get("KeyColumns") or ())
    values = tuple(stub.get("KeyValues") or ())
    named = ", ".join("%s %s" % (c, v) for c, v in zip(columns, values))
    art = {
        "TableName": table,
        "ContainerName": table,
        "Source": stub.get("Source") or "",
        "Offset": stub.get("Offset"),
        "Page": stub.get("Page"),
        "ContainerType": stub.get("ContainerType") or CONTAINER_NOT_DETERMINABLE,
        "RecoverySource": TOMBSTONE_METHOD,
        "Confidence": ("exact key: " + named) if named else "key not decoded",
        "Url": "",
    }
    if stub.get("ContainerId") is not None:
        art["ContainerId"] = stub["ContainerId"]
    art.update(dict(zip(columns, values)))
    return art


#: SEARCHED_FIELDS and searched_values live in recovered_search.py (Qt-free,
#: so the offline report reads the same list) and are imported back here.
from .recovered_search import (  # noqa: E402,F401
    _FILETIME_FIELDS, SEARCHED_FIELDS, searched_values)


#: What each Deleted Records Timestamp cell is, on hover: the column holds
#: two kinds of evidence by design (views/recovery.py), and the cell has
#: to say which one it is.
STRUCT_TIME_BASIS = "The recovered record's own %s."
NEARBY_TIME_BASIS = ("A FILETIME found near the carved bytes: context for "
                     "when the string was written, not a visit time.")


def deleted_records_rows(engine):
    """Every recovered artifact, all three kinds, shaped for the Deleted
    Records view (views/recovery.py), which shows the full yield of a
    scan.

    Structured records (whole reconstructed rows, real ContainerType) come
    first; the URL-string carves from engine.all_artifacts() (page slack
    and transaction-log text, the only sources that read inside a
    transaction log) follow; deleted-record stubs (WebCacheParser.
    tombstones(): b-tree leaf nodes too short to hold a record, left after
    a row's data was deleted but its key entry was not) come last. All
    three carry CARVED_ORIGIN; Method (RecoverySource, or
    TOMBSTONE_METHOD for a stub) and Confidence tell them apart on screen.

    `_kind` tells them apart to code: a structured record has a
    ContainerId, Flags and real columns; a string carve is URL-shaped text
    and where it was found; a stub has only the key (its table, and the
    EntryId/UrlHash the table is keyed on). K_CARVED_STRUCT,
    K_CARVED_STRING and K_TOMBSTONE name those differences.

    Sixteen keys on every kind (at most twenty-one), the same key set for
    all three. A stub's CleanUrl is ABSENCE_NOT_RECOVERED and its
    Timestamp is None, so a stub-specific check must test
    `row["_kind"] == K_TOMBSTONE`, never the text of either token.

    engine.tombstones is read with getattr, defaulting to (): stubs come
    from WebCacheParser and are attached in
    main_window._on_recovery_loaded, so an engine without them still works.
    """
    rows = []
    for entry in engine.structured_records:
        raw_ts, ts_basis = forensic_engine.key_timestamp(entry)
        # The same bit test as carved_history_rows and
        # ese_parser._parse_record, gated the same way: bit 0x08 means
        # InPrivate only on a History record (elsewhere it is
        # EDITED_CACHE_ENTRY). On any other container the bit cannot answer
        # the InPrivate question, so the value is ABSENCE_NOT_DETERMINABLE,
        # neither Yes nor No; a History record whose Flags were not
        # recovered is not determinable either.
        # forensic_engine.carved_inprivate is the one rule.
        known = forensic_engine.carved_inprivate(entry)
        is_inprivate = ABSENCE_NOT_DETERMINABLE if known is None else known
        rows.append({
            "CleanUrl": entry.get("CleanUrl") or entry.get("Url") or "",
            "Title": entry.get("SPS_PageTitle") or "",
            "Timestamp": filetime_to_dt(raw_ts) if raw_ts else None,
            "TimestampBasis": (STRUCT_TIME_BASIS % ts_basis) if raw_ts else "",
            # A structured record always resolved a real ContainerType (see
            # recovery_engine.py's _normalise_carved, run for every row
            # carve_structured_records produces) -- this `or` is defensive,
            # not the normal path. NOT `or ""`: an empty string and a
            # missing value are the same fact ("this cell cannot say what
            # its container is"), and rendering them two different ways
            # made downstream code -- and record_model.py's styling -- have
            # to handle both. One sentinel, one thing to check for.
            "ContainerType": entry.get("ContainerType") or CONTAINER_NOT_DETERMINABLE,
            "Origin": CARVED_ORIGIN,
            "Source": entry.get("Source") or "",
            "Offset": entry.get("Offset"),
            "Page": entry.get("Page"),
            "Method": entry.get("RecoverySource") or "",
            "Confidence": entry.get("Confidence") or "",
            "_record": entry,
            "_kind": K_CARVED_STRUCT,
            "UrlHealth": entry.get("UrlHealth") or "",
            "IsInPrivate": is_inprivate,
            "Region": entry.get("Region") or "",
            # A structured record is reconstructed from a fixed binary
            # layout, not decoded from text, so it has no character
            # encoding: "" (not applicable), which keeps the key sets of
            # all kinds identical.
            "Encoding": "",
            "Key": "",
        })
    for artifact in engine.all_artifacts():
        rows.append({
            "CleanUrl": artifact.get("CleanUrl") or artifact.get("Url") or "",
            "Title": "",
            # A string carve's only time is a FILETIME found near the
            # bytes: context, not a visit time (recovery_engine's
            # NearbyFiletime). It is shown in the same Timestamp column as
            # a structured record's AccessedTime, and TimestampBasis,
            # Method and Confidence say what each is.
            "Timestamp": artifact.get("NearbyFiletime"),
            "TimestampBasis": (NEARBY_TIME_BASIS
                               if artifact.get("NearbyFiletime") else ""),
            # _carve_strings() (recovery_engine.py) produces no
            # ContainerType: a string from page slack or a transaction log
            # has no ContainerId. CONTAINER_NOT_DETERMINABLE states that,
            # rather than a blank cell that would read as a failed read.
            "ContainerType": artifact.get("ContainerType") or CONTAINER_NOT_DETERMINABLE,
            "Origin": CARVED_ORIGIN,
            "Source": artifact.get("Source") or "",
            "Offset": artifact.get("Offset"),
            "Page": artifact.get("Page"),
            "Method": artifact.get("RecoverySource") or "",
            "Confidence": artifact.get("Confidence") or "",
            "_record": artifact,
            "_kind": K_CARVED_STRING,
            # carved_url_health() runs over this text too; string carves
            # are where a carve that began mid-token is found, with the
            # stray bytes named, so it is not read as a recorded URL.
            "UrlHealth": artifact.get("UrlHealth") or "",
            # Not False: a string carved from page slack has no Flags
            # column, so whether the visit was InPrivate is unknowable.
            # Consumers test for the sentinel, never truthiness: it is a
            # non-empty string.
            "IsInPrivate": ABSENCE_NOT_DETERMINABLE,
            # Where in the file the text was found: page-slack,
            # empty-page, or a transaction-log region (recorded by
            # _carve_strings for every artifact).
            "Region": artifact.get("Region") or "",
            # ascii or utf-16-le: how the bytes were read. Carves of the same
            # URL in the two encodings are separate findings.
            "Encoding": artifact.get("Encoding") or "",
            "Key": "",
        })
    for stub in getattr(engine, "tombstones", None) or ():
        art = stub_artifact(stub)
        rows.append({
            "CleanUrl": ABSENCE_NOT_RECOVERED,
            "Title": "",
            "Timestamp": None,
            "TimestampBasis": "",
            "ContainerType": art["ContainerType"],
            "Origin": CARVED_ORIGIN,
            "Source": art["Source"],
            "Offset": art["Offset"],
            "Page": art["Page"],
            "Method": TOMBSTONE_METHOD,
            # a stub's Confidence is the one word "exact" and its key
            # is its own fact in its own column (stub_artifact keeps the
            # combined "exact key: ..." for writers with no key column).
            "Confidence": "exact",
            "Key": ", ".join("%s %s" % (c, v) for c, v in zip(
                stub.get("KeyColumns") or (), stub.get("KeyValues") or ()))
                   or "key not decoded",
            "_record": dict(stub, **art),
            "_kind": K_TOMBSTONE,
            "UrlHealth": "",
            "IsInPrivate": ABSENCE_NOT_DETERMINABLE,
            "Region": "",
            "Encoding": "",
        })
    return rows


class _RecoveryCancelled(Exception):
    """Raised from _check_progress inside one of the engine's carving
    loops (through each carve_* method's progress_callback) to unwind it
    when interruption is requested. Caught in run() and handled like the
    isInterruptionRequested() checks between phases: nothing is
    reported."""


class RecoveryWorker(QThread):
    """Runs one recovery scan against an open, parsed WebCacheParser, off
    the GUI thread.

    `parser` needs `db`, `db_path`, `containers_meta`, `container_type_map`
    and `all_entries`, as MainWindow._parser has after Open Evidence.
    Unparented, like EvidenceLoadWorker, so a caller that closes its owner
    mid-scan cannot destroy a running QThread.
    """
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, parser, parent=None):
        super().__init__(parent)
        self.parser = parser

    def _check_progress(self, message):
        if self.isInterruptionRequested():
            raise _RecoveryCancelled()
        self.progress.emit(message)

    def _log_progress(self, done, total):
        self._check_progress(
            "Recovering deleted records: transaction log %d of %d…"
            % (done, total))

    def _page_progress(self, page_num, total_pages):
        self._check_progress(
            "Recovering deleted records: %s of %s database pages scanned…"
            % (format(page_num, ","), format(total_pages, ",")))

    def _struct_progress(self, scanned, _total):
        # _total is always 0: carve_structured_records cannot know how many
        # candidates the file holds without the scan it is reporting on (as
        # for parse_all_entries()). `scanned` is real.
        self._check_progress(
            "Recovering deleted records: %s candidate record(s) scanned…"
            % format(scanned, ","))

    def run(self):
        parser = self.parser
        engine = recovery_engine.RecoveryEngine()
        try:
            engine.set_container_metadata(
                parser.containers_meta, parser.container_type_map)
            live_urls = {e.get("Url") for e in parser.all_entries if e.get("Url")}

            self.progress.emit(
                "Recovering deleted records: scanning transaction logs…")
            # Only the files chosen and hashed at open: the parser holds
            # their names (source_hashes). An open with no choice hashed
            # every sibling, so this is every log then.
            chosen = set(getattr(parser, "source_hashes", None) or ())
            engine.carve_transaction_logs(
                parser.db_path, live_urls, progress_callback=self._log_progress,
                **({"allowed_names": chosen} if chosen else {}))

            if self.isInterruptionRequested():
                return

            self.progress.emit(
                "Recovering deleted records: scanning unallocated database "
                "pages…")
            engine.carve_database_slack(
                parser.db, parser.db_path, live_urls,
                progress_callback=self._page_progress)

            if self.isInterruptionRequested():
                return

            self.progress.emit(
                "Recovering deleted records: reconstructing deleted "
                "records…")
            engine.carve_structured_records(
                parser.db, parser.db_path, progress_callback=self._struct_progress)
            # A string carved from a database page takes the container its
            # page belongs to (stated as inferred, with how).
            engine.attribute_carved_pages(parser.db)

            if self.isInterruptionRequested():
                return

            # A carved MSHist record's ModifiedTime is LOCAL, like a live
            # one's: stamp the zone the live parse recovered.
            stamp_recovered_clock(engine, parser)

            # Deleted-record stubs come from the live
            # b-tree, not from carving, but walking every leaf of every
            # table is a full pass over parser.db (166 ms on the 30 MB
            # sample) -- so it runs HERE, on this thread, beside the other
            # walks of the same db, and the engine arrives carrying them.
            # getattr: a parser stand-in without tombstones() has none.
            self.progress.emit(
                "Recovering deleted records: listing deleted-record stubs…")
            find_stubs = getattr(parser, "tombstones", None)
            engine.tombstones = list(find_stubs()) if find_stubs else []
        except _RecoveryCancelled:
            return
        except Exception as exc:
            _LOG.warning("Recovery scan failed for %s: %s", parser.db_path, exc)
            self.failed.emit(str(exc))
            return

        if self.isInterruptionRequested():
            return

        # The merged row sets every view reads, computed here so the GUI
        # thread only fills grids (see derived.py).
        self.progress.emit("Recovering deleted records: merging into views…")
        from . import derived
        derived.precompute_recovery(
            parser, engine, stopping=self.isInterruptionRequested,
            progress=lambda what: self.progress.emit(
                "Recovering deleted records: merging into %s…" % what))
        if self.isInterruptionRequested():
            return

        self.loaded.emit(engine)


class RecoveryLoader(QObject):
    """The GUI-thread handle. Owns no widgets and relays a
    RecoveryWorker's signals, like EvidenceLoader; the worker is tracked
    in consent._RUNNING_WORKERS."""
    progress = Signal(str)
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None

    def start(self, parser):
        worker = RecoveryWorker(parser)
        self._worker = worker
        _RUNNING_WORKERS.add(worker)
        worker.progress.connect(self.progress)
        worker.loaded.connect(self.loaded)
        worker.failed.connect(self.failed)
        worker.finished.connect(lambda: _RUNNING_WORKERS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def cancel(self):
        """Best-effort, as EvidenceLoader.cancel."""
        if self._worker is not None:
            try:
                self._worker.requestInterruption()
            except RuntimeError:
                pass
