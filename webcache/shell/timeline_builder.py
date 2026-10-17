"""Building the four Timeline grains off the GUI thread.

The cost of period_rows() grows with the size of the exhibit and has no
fixed bound, so all four grains are built on a worker thread and handed
back in one signal; the window stays usable throughout.

The worker is an unparented QThread tracked in consent._RUNNING_WORKERS,
like every other worker, and checks for interruption before each grain.
period_rows() and grain_note() are pure functions over plain data, so the
worker reads and writes no GUI state. What the grains mean is decided in
timeline_loader.py.
"""
import logging

from PySide6.QtCore import QObject, QThread, Signal

from . import timeline_loader
from .consent import _RUNNING_WORKERS

_LOG = logging.getLogger(__name__)


class TimelineBuildWorker(QThread):
    """Builds the four grains' rows and notes from one TimelineInput.

    Checks isInterruptionRequested() before each grain, so a superseded
    build stops at the next grain boundary.
    """
    built = Signal(object, object)

    def __init__(self, inputs, scan_run, offset_seconds=0, clock_label="UTC",
                 local=None, parent=None):
        super().__init__(parent)
        self._inputs = inputs
        self._scan_run = scan_run
        self._offset = offset_seconds
        self._clock_label = clock_label
        self._local = bool(offset_seconds) if local is None else local

    def run(self):
        rows_by_grain = {}
        notes_by_grain = {}
        for grain, _label, _plural in timeline_loader.GRAINS:
            if self.isInterruptionRequested():
                return
            try:
                rows = timeline_loader.period_rows(
                    self._inputs, grain, offset_seconds=self._offset,
                    local=self._local)
            except Exception as exc:  # pragma: no cover - defensive
                _LOG.warning("Timeline build failed at grain %s: %s",
                             grain, exc)
                return
            rows_by_grain[grain] = rows
            notes_by_grain[grain] = timeline_loader.grain_note(
                self._inputs, rows, grain, scan_run=self._scan_run,
                clock_label=self._clock_label)
        if self.isInterruptionRequested():
            return
        self.built.emit(rows_by_grain, notes_by_grain)


class TimelineBuilder(QObject):
    """The GUI-thread handle, like EvidenceLoader and RecoveryLoader."""
    built = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None

    def build(self, inputs, scan_run, offset_seconds=0, clock_label="UTC",
              local=None):
        worker = TimelineBuildWorker(inputs, scan_run, offset_seconds,
                                     clock_label, local)
        self._worker = worker
        _RUNNING_WORKERS.add(worker)
        worker.built.connect(self.built)
        worker.finished.connect(lambda: _RUNNING_WORKERS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def cancel(self):
        """Request interruption without waiting. The caller also
        disconnects `built`, so a late result is never applied."""
        if self._worker is not None:
            try:
                self._worker.requestInterruption()
            except RuntimeError:
                # The worker has already deleted itself.
                pass
