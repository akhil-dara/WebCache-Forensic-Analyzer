"""Locating a record's raw row off the GUI thread.

WebCacheParser.find_row_ordinal walks a table in page order until the key
matches (about 15 µs a record), and reaching that row's page walks the
same distance again. Both run here, and the GUI thread only renders the
page that comes back.

The worker opens its own parser: the GUI's parser has one file handle,
which Table Browser keeps using meanwhile. The evidence hashes travel with
the request, so the exhibit is not hashed again.

A table of at most SYNC_MAX_ROWS rows is walked on the GUI thread: a second
parser open would cost more than the walk.
"""
import logging

from PySide6.QtCore import QObject, QThread, Signal

from ..engine import ese_parser
from . import table_browser_loader
from .consent import _RUNNING_WORKERS

_LOG = logging.getLogger(__name__)

#: About 45 ms a walk at this size, 90 ms for the two.
SYNC_MAX_ROWS = 3000


def open_parser(db_path, known_hashes=None):
    parser = ese_parser.WebCacheParser()
    if not parser.open(db_path, known_hashes=known_hashes):
        return None
    return parser


def needs_worker(parser, table_name):
    """True when locating a row in `table_name` belongs off the GUI thread."""
    if not (getattr(parser, "db_path", "") or ""):
        return False
    try:
        count = parser.get_table_row_count(table_name)
    except Exception:  # noqa: BLE001
        return False
    return count > SYNC_MAX_ROWS


class RowLocateWorker(QThread):
    #: (request, ordinal or None, page dict or None)
    located = Signal(object, object, object)

    def __init__(self, request, db_path, known_hashes, page_size, parent=None,
                 clock=None):
        super().__init__(parent)
        #: local_clock.clock_snapshot of the parse on screen: this
        #: worker's parser never parses entries.
        self._clock = clock
        self._request = request
        self._db_path = db_path
        self._known_hashes = known_hashes
        self._page_size = page_size

    def run(self):
        ref = self._request
        parser = None
        ordinal = page = None
        try:
            parser = open_parser(self._db_path, self._known_hashes)
            if (parser is not None and self._clock is not None
                    and hasattr(parser, "adopt_clock")):
                parser.adopt_clock(self._clock)
            if parser is not None and not self.isInterruptionRequested():
                ordinal = parser.find_row_ordinal(ref.table, ref.key)
                if ordinal is not None and not self.isInterruptionRequested():
                    offset = (ordinal // self._page_size) * self._page_size
                    page = table_browser_loader.table_page(
                        parser, ref.table, offset=offset,
                        limit=self._page_size)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("Row locate failed: %s", exc)
            ordinal = page = None
        finally:
            if parser is not None:
                try:
                    parser.close()
                except Exception:  # noqa: BLE001
                    pass
        if not self.isInterruptionRequested():
            self.located.emit(ref, ordinal, page)


class RowLocateRunner(QObject):
    """The GUI-thread handle; mirrors SearchRunner. A newer request
    supersedes an older one: the old worker is asked to stop and its
    answer is dropped by the caller's identity check."""
    located = Signal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None

    def start(self, request, db_path, known_hashes, page_size, clock=None):
        self.cancel()
        worker = RowLocateWorker(request, db_path, known_hashes, page_size,
                                 clock=clock)
        self._worker = worker
        _RUNNING_WORKERS.add(worker)
        worker.located.connect(self.located)
        worker.finished.connect(lambda: _RUNNING_WORKERS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def cancel(self):
        if self._worker is not None:
            try:
                self._worker.requestInterruption()
            except RuntimeError:
                pass
            self._worker = None
