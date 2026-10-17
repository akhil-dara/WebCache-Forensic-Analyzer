"""The evidence-hashing worker and the shutdown sweep every worker uses.

HashWorker decides what "hashed" means; _RUNNING_WORKERS keeps every
unparented worker thread referenced until it finishes; shutdown_workers()
is the bounded sweep run at application exit.
"""
import logging
import time

from PySide6.QtCore import QThread, Signal

from ..provenance import EvidenceSet

#: Running workers, referenced here until their finished() signal removes
#: them, so a worker outlives a closed dialog without being collected.
_RUNNING_WORKERS = set()


_LOG = logging.getLogger(__name__)


def shutdown_workers(timeout_ms=3000):
    """Bound every still-running worker at application exit.

    Interruption is requested on every worker first, then each is waited
    on within one shared deadline (time.monotonic), so total shutdown
    time stays near timeout_ms however many workers are running. A worker
    that does not stop in time is logged as a warning and returned rather
    than waited on indefinitely; application exit never hangs on a device
    that stopped responding.
    """
    workers = list(_RUNNING_WORKERS)
    for worker in workers:
        try:
            worker.requestInterruption()
        except RuntimeError:
            # Already finished and deleted.
            continue

    stuck = []
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    for worker in workers:
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        try:
            if not worker.wait(remaining_ms):
                stuck.append(worker)
        except RuntimeError:
            continue

    if stuck:
        # Logged as a warning: a worker still running at exit means the
        # exhibit was still being read.
        _LOG.warning(
            "%d evidence-hashing worker(s) did not stop within %dms at "
            "shutdown", len(stuck), timeout_ms)
    return stuck


#: A file Windows holds open: the database on a running system.
_LOCKED_WINERRORS = (32, 33)


def open_failure_text(exc):
    """Why a file of the evidence could not be read, in plain words."""
    name = getattr(exc, "filename", None)
    which = (" (%s)" % name) if name else ""
    text = str(exc)
    locked = (getattr(exc, "winerror", None) in _LOCKED_WINERRORS
              or "used by another process" in text
              or isinstance(exc, PermissionError))
    if isinstance(exc, FileNotFoundError):
        return ("A file of the evidence is no longer there%s." % which)
    if locked:
        return ("A file of the evidence is in use by another program and "
                "could not be read%s." % which)
    return "A file of the evidence could not be read%s: %s" % (which, text)


class HashWorker(QThread):
    """Reads and hashes every file off the GUI thread, through
    EvidenceSet.from_paths()."""
    done = Signal(object)
    #: A file could not be read: the examiner-facing reason.
    failed = Signal(str)
    progress = Signal(int, int)
    #: (bytes hashed, bytes in total), as objects: an exhibit can exceed
    #: a 32-bit int.
    bytesProgress = Signal(object, object)

    def __init__(self, files, parent=None):
        super().__init__(parent)
        self.files = files

    def run(self):
        total = len(self.files)
        self.progress.emit(0, total)
        try:
            evidence = EvidenceSet.from_paths(
                self.files, should_stop=self.isInterruptionRequested,
                on_bytes=self.bytesProgress.emit)
        except OSError as exc:
            # Reported, so the dialog does not wait indefinitely.
            self.failed.emit(open_failure_text(exc))
            return
        if self.isInterruptionRequested():
            # Cancelled mid-read: the partial result is not reported.
            return
        self.progress.emit(total, total)
        self.done.emit(evidence)

