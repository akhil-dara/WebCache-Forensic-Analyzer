"""Writing an export, off the GUI thread.

Export cost grows with the exhibit: export_xlsx writes N rows x 80 fields
plus up to CONTAINER_SHEET_LIMIT per-container sheets, export_sqlite_raw
walks every ESE table and re-serialises every column, and the bundle runs
ten writers in sequence including the PDF. Run on the GUI thread, a large
export would freeze the window.

The worker follows recovery_loader.RecoveryWorker: an unparented QThread,
registered in consent._RUNNING_WORKERS (one shutdown sweep for every
worker), cancelled cooperatively between units of work.

CANCEL. QThread.requestInterruption() has no effect on a thread that is
not yet running, so a Cancel in the same event-loop turn as the start
would be lost. cancel() therefore also sets a boolean, written on the GUI
thread and read on the worker: a single assignment, with no
read-modify-write.

A cancelled carve reports nothing, because a partial carve is not the
recovery scan (recovery_loader's cancel rule). A cancelled bundle keeps
what is already on disk: each file is whole, because atomic_write only
publishes a completed file, and the manifest is still written, recording
"cancelled": true and "not attempted (cancelled)" for each format that did
not run. A single-format export has no interruption point inside one
library call, so Cancel stops the next job and the status bar says the
finished file was kept.

PROGRESS. The bar is indeterminate (MainWindow owns it); the text gives
real counts, and for the bundle the member list is fixed and known.
"""
import logging
import os

from PySide6.QtCore import QObject, QThread, Signal

from ..engine import forensic_engine
from . import export_formats, html_package
from .consent import _RUNNING_WORKERS

_LOG = logging.getLogger(__name__)

#: The four statuses a bundle member can carry into the manifest.
S_WRITTEN = "written"
S_FAILED = "failed"
S_SKIPPED = "skipped"
S_CANCELLED = "not attempted (cancelled)"

#: The recovered_csv member's two skip reasons, kept distinct: no scan has
#: run, or a scan ran and recovered nothing.
RECOVERED_CSV_NO_SCAN = ("No recovery scan has run for this exhibit, so "
                         "there are no carved records to write.")
RECOVERED_CSV_SCAN_FOUND_NOTHING = (
    "A recovery scan ran for this exhibit and found no carved records.")

#: Why the offline report was not written: the job carries no snapshot of
#: the views (MainWindow._package_snapshot, taken on the GUI thread).
HTML_NO_SNAPSHOT = ("No offline-report snapshot was taken for this job, so "
                    "the offline HTML report could not be written.")


#: What the offline report's rows_written counts.
HTML_ROWS_UNIT = "rows across every view's segments"

#: Formats whose rows_written counts live entries only, with the recovered
#: records written to a section of their own: format key -> that section.
RECOVERED_SECTIONS = {"xlsx": "Recovered sheet",
                      "json": "recovered_artifacts"}


def _write_html_package(job, path):
    if job.package is None:
        raise ValueError(HTML_NO_SNAPSHOT)
    return html_package.write_package(job.package, path)


class ExportJob:
    """Everything one write needs, snapshotted on the GUI thread.

    Every list is copied here, before the worker exists, so a recovery
    merge during the write cannot change the set being written. Nothing
    here is a widget; `scope` and `stamp` are plain dicts.

    Also carried, so the worker never reads MainWindow from another
    thread: `evidence_set` (the bundle manifest re-runs verify() at export
    time), `location_fixes`/`places` (the position formats' inputs),
    `recovery_summary` (the PDF's EntryId-gap section), and `caps`
    (which formats the bundle may skip, with the reason for each).
    """
    __slots__ = ("key", "path", "rows", "columns", "entries", "recovered",
                 "artifacts", "stats", "parser", "case_meta", "db_info",
                 "tags_map", "comments_map", "scope", "stamp", "label",
                 "evidence_set", "location_fixes", "places",
                 "recovery_summary", "caps", "package")

    def __init__(self, key, path, rows=(), columns=(), entries=(),
                 recovered=(), artifacts=None, stats=None, parser=None,
                 case_meta=None, db_info=None, tags_map=None,
                 comments_map=None, scope=None, stamp=None, label="",
                 evidence_set=None, location_fixes=(), places=None,
                 recovery_summary=None, caps=None, package=None):
        self.key = key
        self.path = path
        self.rows = list(rows or ())
        self.columns = list(columns or ())
        self.entries = list(entries or ())
        self.recovered = list(recovered or ())
        self.artifacts = dict(artifacts or {})
        self.stats = dict(stats) if isinstance(stats, dict) else stats
        self.parser = parser
        self.case_meta = dict(case_meta or {})
        self.db_info = dict(db_info or {})
        self.tags_map = dict(tags_map or {})
        self.comments_map = dict(comments_map or {})
        self.scope = dict(scope or {})
        self.stamp = dict(stamp or {})
        self.label = label or key
        self.evidence_set = evidence_set
        self.location_fixes = list(location_fixes or ())
        # A LIST, like location_fixes one line above -- not dict(places).
        # export_location_csv/_pdf both iterate this as a sequence of
        # cluster dicts (`for p in places:` ... `p.get("Latitude")`), and
        # dict([{...}]) raises ValueError at job construction, before a
        # single byte is written. The empty case matters too: {} and []
        # are both falsy where the engine tests them, but iterating a dict
        # yields its KEYS, so a non-empty one would feed strings where
        # dicts belong rather than failing loudly.
        self.places = list(places or ())
        self.recovery_summary = recovery_summary
        self.caps = dict(caps or {})
        #: The offline report's PackageSnapshot (html and bundle only),
        #: taken on the GUI thread; its rows are only read here.
        self.package = package


class ExportWorker(QThread):
    """One write, off the GUI thread. See the module docstring."""
    progress = Signal(str)
    #: Every path now on disk because of this job, sidecars included.
    written = Signal(list)
    failed = Signal(str)

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        self._cancelled = False

    # --- cancel ---------------------------------------------------------

    def cancel(self):
        """Best-effort, like every other worker. Sets a boolean as well as
        calling requestInterruption() (see the module docstring)."""
        self._cancelled = True
        try:
            self.requestInterruption()
        except RuntimeError:
            pass

    def stopping(self):
        return self._cancelled or self.isInterruptionRequested()

    # --- the work -------------------------------------------------------

    def run(self):
        job = self.job
        try:
            if job.key == "bundle":
                paths = self._run_bundle(job)
            elif job.key in ("view_csv", "view_xlsx"):
                paths = self._run_view_csv(job)
            elif job.key == "header_pairs":
                paths = self._run_header_pairs(job)
            else:
                paths = self._run_single(job)
        except Exception as exc:                       # noqa: BLE001
            # Every failure is reported to the GUI: an exception raised
            # out of QThread.run() would otherwise not be seen.
            _LOG.warning("Export %s failed: %s", job.key, exc)
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))
            return
        self.written.emit(list(paths))

    # --- one format -----------------------------------------------------

    def _engine(self, job):
        engine = forensic_engine.ForensicEngine()
        engine.load_entries(list(job.entries))
        return engine

    def _stats(self, job, engine):
        return job.stats if job.stats else engine.get_statistics()

    def _writer_for(self, key, job, engine):
        """key -> a callable(path) that writes it. One table, so the
        bundle loop and a single-format export can never disagree about
        what a format name means."""
        stats = lambda: self._stats(job, engine)          # noqa: E731
        return {
            "pdf": lambda p: engine.export_pdf_report(
                job.entries, stats(), p, job.case_meta, job.db_info,
                job.recovery_summary, job.recovered,
                job.scope.get("recovery_scan_run")),
            "sqlite_raw": lambda p: engine.export_sqlite_raw(
                job.parser, p, job.case_meta, job.recovered),
            "xlsx": lambda p: engine.export_xlsx(
                job.entries, p, True, job.case_meta, job.db_info,
                job.artifacts, job.recovered, job.tags_map, job.comments_map,
                stats()),
            "csv": lambda p: engine.export_csv(
                job.entries, p, job.tags_map, job.comments_map, job.recovered),
            "json": lambda p: engine.export_json(
                job.entries, p, job.case_meta, job.db_info, job.artifacts,
                job.recovered, job.tags_map, job.comments_map),
            "sqlite": lambda p: engine.export_sqlite(
                job.entries, p, job.case_meta, job.db_info, job.artifacts,
                job.recovered, job.tags_map, job.comments_map),
            "html": lambda p: _write_html_package(job, p),
            "loc_csv": lambda p: engine.export_location_csv(
                job.location_fixes, p, job.case_meta, job.db_info, job.places),
            "loc_kml": lambda p: engine.export_location_kml(
                job.location_fixes, p, job.case_meta),
            "loc_json": lambda p: engine.export_location_json(
                job.location_fixes, p, job.case_meta),
            "loc_xlsx": lambda p: engine.export_location_xlsx(
                job.location_fixes, p),
            "recovered_csv": lambda p: engine._write_recovered_csv(
                job.recovered, p),
        }.get(key)

    def _run_single(self, job):
        fmt = export_formats.BY_KEY.get(job.key)
        engine = self._engine(job)
        write = self._writer_for(job.key, job, engine)
        if fmt is None or write is None:
            raise ValueError(
                "%r is not a format this build can write" % job.key)
        self.progress.emit("Writing %s…" % os.path.basename(job.path))
        result = write(job.path)
        paths = [job.path]
        if fmt.sidecar:
            # "A provenance sidecar on every export" has to be true rather
            # than nearly true: loc_csv writes its own
            # through the engine (fmt.sidecar False), every other format
            # gets one here, through the SAME _write_metadata_sidecar so
            # there is one shape of sidecar in the world, not two.
            engine._write_metadata_sidecar(
                job.path, job.case_meta, job.db_info,
                rows_written=self._rows_written(job, result),
                extra=self._sidecar_extra(job, result))
        for side in (job.path + ".metadata.json", job.path + ".sha256"):
            if os.path.exists(side):
                paths.append(side)
        return paths

    def _rows_written(self, job, result=None):
        """The number of records the file this write produced holds,
        which is not always len(job.entries):

        export_sqlite writes one "records" table holding live entries and
        recovered records together, labelled by source, so its count is
        len(entries) + len(recovered). export_csv likewise writes carved
        rows (deleted-record stubs included) after the live rows, labelled
        by Origin.

        loc_kml/loc_json/loc_xlsx write job.location_fixes, not
        job.entries.

        sqlite_raw copies whole ESE tables and does not read job.entries;
        `result` is its return value, {table_name: row_count}, so the
        total is the sum of its values.

        Every other single-format writer puts recovered records in a
        separately labelled section (xlsx's "Recovered" sheet, json's
        "recovered" array and "counts" block, the PDF's "Recovered
        Artifacts"), so len(job.entries) matches what each calls its entry
        count.
        """
        if job.key == "sqlite_raw":
            return sum(result.values()) if result else 0
        if job.key == "html":
            # The page holds every view's rows, not job.entries.
            return result.counts["rows_total"]
        if job.key in ("csv", "sqlite"):
            return len(job.entries) + len(job.recovered or ())
        if job.key in ("loc_kml", "loc_json", "loc_xlsx"):
            return len(job.location_fixes)
        return len(job.entries)

    @staticmethod
    def _sidecar_extra(job, result):
        """What a sidecar states beyond rows_written. The offline report
        holds many units at once (rows per segment, distinct records,
        raw table rows, members), so its sidecar names each by its unit,
        as the page's own "Records in this report" table does. A format
        that keeps recovered records in a section of their own states
        how many it wrote there, and where."""
        if job.key in RECOVERED_SECTIONS:
            return {"recovered_rows_written": len(job.recovered or ()),
                    "recovered_rows_section": RECOVERED_SECTIONS[job.key]}
        if job.key != "html":
            return None
        return {"rows_written_unit": HTML_ROWS_UNIT,
                "page_contents": result.counts}

    # --- the view CSV ----------------------------------------------------

    def _run_view_csv(self, job):
        self.progress.emit("Writing %s…" % os.path.basename(job.path))
        writer = (export_formats.write_view_xlsx if job.key == "view_xlsx"
                  else export_formats.write_view_csv)
        rows = writer(
            job.rows, job.columns, job.path, job.scope,
            tags_map=job.tags_map, comments_map=job.comments_map)
        job.scope["rows_in_file"] = rows
        paths = [job.path]
        side = export_formats.write_view_provenance(
            job.path, job.stamp, job.scope,
            job.scope.get("formula_values", 0))
        if side:
            paths.append(side)
        return paths

    def _run_header_pairs(self, job):
        self.progress.emit("Writing %s…" % os.path.basename(job.path))
        pairs = export_formats.write_header_pairs_csv(
            job.rows, job.path, job.scope)
        job.scope["rows_in_file"] = pairs
        job.scope["unit"] = "header pairs"
        paths = [job.path]
        side = export_formats.write_view_provenance(
            job.path, job.stamp, job.scope,
            job.scope.get("formula_values", 0))
        if side:
            paths.append(side)
        return paths

    # --- the bundle ------------------------------------------------------

    def _run_bundle(self, job):
        """Ten writers, one directory, one manifest.

        The member loop is here rather than in export_full_bundle so that
        progress text, an interruption point between members, and a
        per-member status and reason in the manifest are possible. See
        export_formats.BUNDLE_MEMBERS, whose filenames a test checks
        against that method's source.
        """
        out_dir = job.path
        os.makedirs(out_dir, exist_ok=True)
        engine = self._engine(job)
        avail = export_formats.availability(job.caps) if job.caps else {}
        total = len(export_formats.BUNDLE_MEMBERS)
        results = []
        cancelled = False

        for index, (key, label, filename) in enumerate(
                export_formats.BUNDLE_MEMBERS, start=1):
            if cancelled or self.stopping():
                cancelled = True
                results.append((filename, label, S_CANCELLED,
                                "Cancelled before this format was written."))
                continue
            ok, reason = avail.get(key, (True, ""))
            if key == "recovered_csv":
                ok = bool(job.recovered)
                if not ok:
                    reason = (RECOVERED_CSV_SCAN_FOUND_NOTHING
                              if job.scope.get("recovery_scan_run")
                              else RECOVERED_CSV_NO_SCAN)
            elif key == "sqlite_raw":
                ok = job.parser is not None
                reason = export_formats.UNAVAILABLE_REASON["parser"]
            elif key == "html" and ok:
                ok = job.package is not None
                reason = HTML_NO_SNAPSHOT
            if not ok:
                results.append((filename, label, S_SKIPPED, reason))
                continue
            self.progress.emit(
                "Writing %s (%d of %d)…" % (filename, index, total))
            write = self._writer_for(key, job, engine)
            path = os.path.join(out_dir, filename)
            try:
                write(path)
            except Exception as exc:                   # noqa: BLE001
                # One failing format never aborts the bundle (as in
                # export_full_bundle); the failure is recorded in the
                # manifest.
                _LOG.warning("Bundle member %s failed: %s", filename, exc)
                results.append((filename, label, S_FAILED,
                                "%s: %s" % (type(exc).__name__, exc)))
                continue
            results.append((filename, label, S_WRITTEN, ""))

        manifest = export_formats.finalise_bundle_manifest(
            out_dir, job, results, cancelled)
        # Enumerated from disk, not from the member list: some members
        # write a companion file of their own (loc_csv writes a
        # .metadata.json), and the count shown must match the folder. The
        # manifest is enumerated the same way.
        written = [manifest]
        try:
            for name in sorted(os.listdir(out_dir)):
                full = os.path.join(out_dir, name)
                if os.path.isfile(full) and name != export_formats.MANIFEST_NAME:
                    written.append(full)
        except OSError:
            # The directory went away under us -- report the members this
            # loop knows it wrote rather than nothing at all.
            written.extend(os.path.join(out_dir, filename)
                           for filename, _l, status, _r in results
                           if status == S_WRITTEN)
        return written


class ExportRunner(QObject):
    """The GUI-thread handle. Owns no widgets and relays the worker's
    signals, like RecoveryLoader; the worker is tracked in
    consent._RUNNING_WORKERS."""
    progress = Signal(str)
    written = Signal(list)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None

    def start(self, job):
        worker = ExportWorker(job)
        self._worker = worker
        _RUNNING_WORKERS.add(worker)
        worker.progress.connect(self.progress)
        worker.written.connect(self.written)
        worker.failed.connect(self.failed)
        worker.finished.connect(lambda: _RUNNING_WORKERS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def cancel(self):
        if self._worker is not None:
            try:
                self._worker.cancel()
            except RuntimeError:
                pass
