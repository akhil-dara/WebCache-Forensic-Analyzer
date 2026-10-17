"""Bounding the consent dialog's hashing worker at application exit.

consent.py deliberately never blocks: cancelling the dialog calls
requestInterruption() and returns immediately, and the worker is
unparented so it can outlive a destroyed dialog. Nothing there bounds it at
process exit, and a QThread's OS thread is not a threading.Thread -- the
interpreter does not wait for it on its own. A worker blocked reading a
failing device would otherwise sit in consent._RUNNING_WORKERS forever.

This is what wires and proves the fix: consent.shutdown_workers() is the
one public entry point (nothing here or in webcache.__main__ reaches into
_RUNNING_WORKERS directly), and the tests measure wall-clock time to prove
the shutdown path is actually bounded, not just eventually correct.

test_shutdown_bounds_total_time_across_multiple_stubborn_workers guards
against interleaving "request, wait, request the
next", so a later worker's interruption request was delayed by however
long an earlier worker's wait() blocked -- N stubborn workers cost roughly
N * timeout_ms, not one timeout_ms shared across all of them.
"""
import logging
import time

import pytest
from PySide6.QtCore import QThread

from webcache.__main__ import install_shutdown_handler
from webcache.shell import consent


class _CooperativeWorker(QThread):
    """Blocks until asked to stop, then stops -- the well-behaved case."""

    def run(self):
        while not self.isInterruptionRequested():
            QThread.msleep(20)


class _StubbornWorker(QThread):
    """Ignores requestInterruption() entirely -- the worst case: a read
    against a device that will not hand back control on request. Only
    the test's own `release` flag, never interruption, stops it."""

    def __init__(self):
        super().__init__()
        self.release = False

    def run(self):
        while not self.release:
            QThread.msleep(20)


def test_shutdown_stops_a_blocked_but_cooperative_worker_promptly(qtbot):
    worker = _CooperativeWorker()
    consent._RUNNING_WORKERS.add(worker)
    worker.finished.connect(lambda: consent._RUNNING_WORKERS.discard(worker))
    worker.start()
    qtbot.waitUntil(worker.isRunning, timeout=2_000)

    start = time.monotonic()
    stuck = consent.shutdown_workers(timeout_ms=3_000)
    elapsed = time.monotonic() - start

    assert stuck == []
    assert elapsed < 2.0, "a cooperative worker should stop well inside the bound"
    assert worker.isFinished()


def test_shutdown_does_not_hang_on_a_worker_that_refuses_to_stop(qtbot, caplog):
    """The whole point of the shutdown handler: it must return in bounded
    time and report the worker rather than block application exit forever
    on a device that never releases control.

    Also checks the report actually reaches somewhere durable. The first
    cut of shutdown_workers used a bare print(), which goes nowhere an
    examiner running a windowed build would ever see -- this asserts the
    warning is emitted through logging instead, which is at minimum
    capturable and testable, and is a candidate for a future handler tied
    to the Integrity view's parse log (see the TODO in consent.py).
    """
    worker = _StubbornWorker()
    consent._RUNNING_WORKERS.add(worker)
    worker.finished.connect(lambda: consent._RUNNING_WORKERS.discard(worker))
    worker.start()
    qtbot.waitUntil(worker.isRunning, timeout=2_000)

    start = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="webcache.shell.consent"):
        stuck = consent.shutdown_workers(timeout_ms=300)
    elapsed = time.monotonic() - start

    assert worker in stuck
    # Bounded near the requested timeout -- not zero (it really waited)
    # and not indefinite (it really returned).
    assert 0.25 <= elapsed < 2.0, "shutdown_workers must return near its timeout, not hang"
    assert any("did not stop" in r.message for r in caplog.records), (
        "a stuck worker at shutdown must be logged somewhere durable, "
        "not only returned"
    )

    # Clean up: let the worker actually finish so it cannot leak into a
    # later test.
    worker.release = True
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=2_000)


def test_shutdown_bounds_total_time_across_multiple_stubborn_workers(qtbot):
    """Reproduces the Fix-round-1 finding directly: the first cut of
    shutdown_workers interleaved "request interruption, then wait" per
    worker, one at a time. A later worker was not even TOLD to stop until
    an earlier one had already burned its own full timeout -- so two
    stubborn workers cost roughly two timeouts, not one shared across
    both.

    Two stubborn workers, both started before shutdown_workers is called
    (so both are already blocked and ignoring interruption by the time it
    runs), prove the fix: total elapsed must stay near ONE timeout_ms, not
    stretch toward two. This is the test that would have caught the
    original interleaved version -- see the fix-round report for the
    actual before/after numbers.
    """
    workers = [_StubbornWorker(), _StubbornWorker()]
    for w in workers:
        consent._RUNNING_WORKERS.add(w)
        w.finished.connect(lambda w=w: consent._RUNNING_WORKERS.discard(w))
        w.start()
    for w in workers:
        qtbot.waitUntil(w.isRunning, timeout=2_000)

    timeout_ms = 300
    start = time.monotonic()
    stuck = consent.shutdown_workers(timeout_ms=timeout_ms)
    elapsed = time.monotonic() - start

    assert set(stuck) == set(workers)
    # A shared budget bounds this near one timeout (0.3s); an interleaved
    # per-worker timeout would have taken near two (0.6s). The midpoint,
    # 0.45s, cleanly separates the two implementations without being tight
    # enough to flake on normal scheduling jitter.
    assert elapsed < (timeout_ms / 1000.0) * 1.5, (
        "total shutdown time scaled with worker count instead of being "
        "bounded by a single shared timeout: took %.3fs for timeout_ms=%d"
        % (elapsed, timeout_ms))

    for w in workers:
        w.release = True
    for w in workers:
        qtbot.waitUntil(lambda w=w: not w.isRunning(), timeout=2_000)


def test_the_app_wires_about_to_quit_to_the_worker_shutdown(qapp):
    """install_shutdown_handler is what webcache.__main__.main() calls;
    exercised here directly (rather than by running main(), which would
    start a real event loop) by connecting it to the shared test-session
    QApplication and firing aboutToQuit by hand.

    Uses a cooperative worker so this test itself finishes quickly; the
    "does it actually bound a stuck worker" claim is proved separately
    above -- this one only proves aboutToQuit is really wired to
    shutdown_workers, not reimplement that proof.

    The connection is undone in a finally block: qapp is the
    session-scoped QApplication pytest-qt shares across every test in
    this session, so leaving this connected would fire
    consent.shutdown_workers() a second time -- accessing
    _RUNNING_WORKERS and printing/logging based on whatever unrelated
    workers happen to be running -- on every later test's own use of
    qapp, and again for real when the session's QApplication actually
    quits.
    """
    worker = _CooperativeWorker()
    consent._RUNNING_WORKERS.add(worker)
    worker.finished.connect(lambda: consent._RUNNING_WORKERS.discard(worker))
    worker.start()

    install_shutdown_handler(qapp)
    try:
        start = time.monotonic()
        qapp.aboutToQuit.emit()
        elapsed = time.monotonic() - start

        assert elapsed < 3.0
        assert worker.wait(2_000), "aboutToQuit did not reach the worker at all"
    finally:
        qapp.aboutToQuit.disconnect(consent.shutdown_workers)
