"""Detects a frozen GUI thread from the timer that stops firing.

A QTimer on the GUI thread fires every 16 ms; while the thread is blocked
it cannot fire, so the gap between ticks is the length of the freeze. The
measurement comes from the symptom itself rather than from asking the
window whether it is responsive.
"""
import time

from PySide6.QtCore import QObject, Qt, QTimer

#: A frame at 60 Hz. Ticking faster measures nothing extra and costs more.
TICK_MS = 16
#: Below this, a gap is scheduling noise rather than a freeze an analyst
#: would notice.
DEFAULT_THRESHOLD_MS = 150


class StallDetector(QObject):
    """Must be constructed, started and stopped on the GUI thread: it
    measures the thread that owns it, and does not check which that is.
    """

    def __init__(self, threshold_ms=DEFAULT_THRESHOLD_MS, parent=None,
                 cpu=False):
        """`cpu=True` also measures the GUI thread's own CPU time within
        each gap (worst_busy_gap_ms, busy_stalls), which excludes time
        taken by other processes on a loaded machine."""
        super().__init__(parent)
        self.threshold_ms = threshold_ms
        self.stalls = []
        self.worst_gap_ms = 0.0
        self.cpu = bool(cpu)
        self.busy_stalls = []
        self.worst_busy_gap_ms = 0.0
        self._last = None
        self._last_cpu = None
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        now = time.perf_counter()
        cpu_now = time.thread_time() if self.cpu else None
        if self._last is not None:
            self._observe(now, cpu_now)
        self._last = now
        self._last_cpu = cpu_now

    def _observe(self, now, cpu_now=None):
        """Record the gap from self._last to now if it exceeds the
        threshold. Used by _tick() and by stop()'s final reading."""
        gap = (now - self._last) * 1000.0
        self.worst_gap_ms = max(self.worst_gap_ms, gap)
        if gap > self.threshold_ms:
            self.stalls.append(gap)
        if cpu_now is not None and self._last_cpu is not None:
            busy = (cpu_now - self._last_cpu) * 1000.0
            self.worst_busy_gap_ms = max(self.worst_busy_gap_ms, busy)
            if busy > self.threshold_ms:
                self.busy_stalls.append(busy)

    def start(self):
        self.stalls.clear()
        self.worst_gap_ms = 0.0
        self.busy_stalls.clear()
        self.worst_busy_gap_ms = 0.0
        self._last_cpu = time.thread_time() if self.cpu else None
        # Seeded with the current time, so a block that starts the
        # moment the detector is armed is measured too.
        self._last = time.perf_counter()
        self._timer.start()
        return self

    def stop(self):
        # A final reading, so a block that ends just before stop() is
        # counted even if its pending timer tick never ran. Only while
        # the timer is active: a stopped detector has nothing to measure.
        if self._timer.isActive():
            self._observe(time.perf_counter(),
                          time.thread_time() if self.cpu else None)
        self._timer.stop()
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False
