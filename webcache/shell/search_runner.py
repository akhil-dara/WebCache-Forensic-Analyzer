"""Running a cross-table search off the GUI thread.

search_all_tables reads every column of every row of every table; its
duration grows with the exhibit, so it runs on a worker thread.

The worker opens its own parser: the GUI's parser has one file handle,
which Table Browser and the blob viewer keep using during a search. The
query carries the evidence hashes, so the exhibit is not hashed again, and
parser.close() runs on every path.

A cancelled search reports nothing: a partial hit list would read like a
complete one. _SearchCancelled subclasses the engine's SearchCancelled, so
the engine's per-table error handling re-raises it instead of continuing.

Every hit keeps its matched row, so memory grows with the number of hits
(about 2.5 KB a hit). There is no result limit, because a search that
stops early hides evidence; a new search replaces the previous one.
"""
import logging

from PySide6.QtCore import QObject, QThread, Signal

from ..engine import ese_parser
from . import search_loader
from .consent import _RUNNING_WORKERS

_LOG = logging.getLogger(__name__)


class _SearchCancelled(ese_parser.SearchCancelled):
    """This module's cancellation, raised from the progress callback.
    Subclasses the engine's exception so search_all_tables re-raises it.
    """


class SearchWorker(QThread):
    """One search, on its own thread and file handle.

    Unparented (see consent.py) and interruptible at every progress tick.
    """
    progress = Signal(str)
    #: (SearchQuery, payload dict). The query travels with the result so
    #: hits are never shown under another keyword's count line.
    found = Signal(object, object)
    failed = Signal(str)

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self._query = query
        self._rows_scanned = 0
        self._tables_done = 0
        self._tables_total = 0
        #: How many distinct tables the scan has reached, and the latest
        #: one's name, so the count and the name describe the same table
        #: (the engine reports tables completed).
        self._tables_seen = 0
        self._last_table = None

    def run(self):
        query = self._query
        parser = None
        try:
            parser = ese_parser.WebCacheParser()
            parser.open(query.db_path, known_hashes=query.known_hashes)
            # The exhibit's clock from the parse on screen: this parser
            # parses no entries, so it has no time-zone data of its own.
            clock = getattr(query, "clock", None)
            if clock is not None and hasattr(parser, "adopt_clock"):
                parser.adopt_clock(clock)
            results = parser.search_all_tables(
                query.keyword, query.table_filter, 0,
                progress_callback=self._check_progress)
            payload = {
                # Rows are shaped on the worker (search_rows is pure).
                "rows": search_loader.search_rows(results, keyword=query.keyword),
                "skipped": list(getattr(parser, "search_skipped_tables", None)
                                or ()),
                "rows_scanned": self._rows_scanned,
                "tables": self._tables_done,
            }
        except _SearchCancelled:
            # A search that did not finish reports nothing.
            return
        except Exception as exc:
            _LOG.warning("Search failed: %s", exc)
            self.failed.emit(str(exc))
            return
        finally:
            if parser is not None:
                try:
                    parser.close()
                except Exception:  # pragma: no cover - defensive
                    pass
        self.found.emit(query, payload)

    def _check_progress(self, rows_scanned, tables_done, tables_total, tname):
        """The engine's progress callback and the cancellation point.

        Reports real counts only; no percentage is computed, because a few
        tables hold most of the rows.
        """
        self._rows_scanned = rows_scanned
        self._tables_done = tables_done
        self._tables_total = tables_total
        if tname != self._last_table:
            self._last_table = tname
            self._tables_seen += 1
        if self.isInterruptionRequested():
            raise _SearchCancelled()
        self.progress.emit(
            "Searching '%s': table %d of %d (%s) — %s row(s) scanned"
            % (self._query.keyword, self._tables_seen, tables_total, tname,
               format(rows_scanned, ",")))


class SearchRunner(QObject):
    """The GUI-thread handle, like TimelineBuilder and RecoveryLoader."""
    progress = Signal(str)
    found = Signal(object, object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None

    def start(self, query):
        worker = SearchWorker(query)
        self._worker = worker
        _RUNNING_WORKERS.add(worker)
        worker.progress.connect(self.progress)
        worker.found.connect(self.found)
        worker.failed.connect(self.failed)
        worker.finished.connect(lambda: _RUNNING_WORKERS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def cancel(self):
        """Request interruption without waiting. The caller also
        disconnects the signals, so a late result is never applied."""
        if self._worker is not None:
            try:
                self._worker.requestInterruption()
            except RuntimeError:
                # The worker has already deleted itself.
                pass
