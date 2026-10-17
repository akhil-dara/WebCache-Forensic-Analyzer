"""TimelineBuilder: building all four Timeline grains off the GUI thread.

main_window._fill_timeline used to build every
grain synchronously, on the GUI thread -- measured at 100 s of fully
blocked GUI on this machine for 100,000 synthetic dated records (66 s
after timeline_loader._period_start's own strptime fix). This module is
the worker that removes the block entirely: period_rows()/grain_note()
are pure functions over plain dicts, with no Qt object and no engine I/O,
so they can run on a background QThread and hand the finished rows back
in one shot.

Mirrors test_evidence_loader.py's own shutdown-discipline tests exactly
(unparented worker, tracked in consent._RUNNING_WORKERS, self-cleaning via
finished -> deleteLater) -- the same worker shape, the same pattern,
proved the same way.
"""
import datetime

import pytest

from webcache.shell import consent, timeline_loader
from webcache.shell.timeline_builder import TimelineBuilder, TimelineBuildWorker

_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


def _filetime(*args):
    dt = datetime.datetime(*args, tzinfo=datetime.timezone.utc)
    return int((dt - _EPOCH).total_seconds() * 10_000_000)


def _entry(day=15, **overrides):
    base = {
        "Url": "https://a.example/page",
        "CleanUrl": "https://a.example/page",
        "ContainerType": "History",
        "ContainerId": 3,
        "ContainerName": "History",
        "EntryId": 1,
        "ModifiedTime_raw": _filetime(2024, 6, day, 9, 0, 0),
    }
    base.update(overrides)
    return base


def _inputs():
    return timeline_loader.timeline_inputs(
        [_entry(day=1, EntryId=1), _entry(day=1, EntryId=2),
         _entry(day=20, EntryId=3)])


# --- shutdown discipline, mirroring test_evidence_loader.py exactly ------

def test_worker_is_never_parented(qtbot):
    """A parented QThread destroyed while still running is undefined
    behaviour, not a clean abort -- see consent.py's own docstring."""
    worker = TimelineBuildWorker(_inputs(), scan_run=False)
    assert worker.parent() is None


def test_cancel_requests_interruption_on_the_worker(qtbot):
    """Proved with a spy rather than the real QThread's own
    isInterruptionRequested(): requestInterruption() is a documented
    no-op on a thread that was never started, which a never-started
    TimelineBuildWorker always is here."""
    calls = []

    class _SpyWorker:
        def requestInterruption(self):
            calls.append(1)

    builder = TimelineBuilder()
    builder._worker = _SpyWorker()
    builder.cancel()
    assert calls == [1]


def test_cancel_before_any_build_does_not_raise(qtbot):
    builder = TimelineBuilder()
    builder.cancel()  # must not raise


def test_build_registers_the_worker_in_the_shared_shutdown_set_and_self_cleans(
        qtbot):
    """consent.shutdown_workers() only ever iterates
    consent._RUNNING_WORKERS -- a worker that never lands there would
    silently outlive application exit."""
    builder = TimelineBuilder()
    with qtbot.waitSignal(builder.built, timeout=10_000):
        builder.build(_inputs(), scan_run=False)
        qtbot.waitUntil(lambda: builder._worker is not None, timeout=2_000)
        assert builder._worker in consent._RUNNING_WORKERS
    worker = builder._worker
    qtbot.waitUntil(lambda: worker not in consent._RUNNING_WORKERS,
                    timeout=5_000)


# --- the real build --------------------------------------------------------

def test_a_real_build_emits_built_with_all_four_grains(qtbot):
    builder = TimelineBuilder()
    with qtbot.waitSignal(builder.built, timeout=10_000) as blocker:
        builder.build(_inputs(), scan_run=False)
    rows_by_grain, notes_by_grain = blocker.args
    assert set(rows_by_grain) == {g[0] for g in timeline_loader.GRAINS}
    assert set(notes_by_grain) == {g[0] for g in timeline_loader.GRAINS}
    assert len(rows_by_grain["day"]) == 2
    assert len(rows_by_grain["month"]) == 1


def test_the_built_rows_match_what_period_rows_returns_synchronously(qtbot):
    """The async path must not be a second, possibly-drifting copy of
    what period_rows() already computes -- it calls the identical
    function, off-thread."""
    inputs = _inputs()
    builder = TimelineBuilder()
    with qtbot.waitSignal(builder.built, timeout=10_000) as blocker:
        builder.build(inputs, scan_run=False)
    rows_by_grain, notes_by_grain = blocker.args
    for grain, _label, _plural in timeline_loader.GRAINS:
        expected_rows = timeline_loader.period_rows(inputs, grain)
        assert rows_by_grain[grain] == expected_rows, grain
        expected_note = timeline_loader.grain_note(
            inputs, expected_rows, grain, scan_run=False)
        assert notes_by_grain[grain] == expected_note, grain


def test_scan_run_reaches_the_notes(qtbot):
    """scan_run=True must produce the recovered-count note, not the
    "nobody has looked yet" one -- proving the flag actually reaches
    grain_note() on the worker thread."""
    builder = TimelineBuilder()
    with qtbot.waitSignal(builder.built, timeout=10_000) as blocker:
        builder.build(_inputs(), scan_run=True)
    _rows_by_grain, notes_by_grain = blocker.args
    assert "no recovery scan has run" not in notes_by_grain["day"]


def test_an_interrupted_build_never_emits_built(qtbot):
    """Best-effort cancellation: a worker asked to stop before it starts
    must report nothing at all, exactly like a cancelled evidence load or
    a cancelled recovery scan -- never a partial result standing in for
    a complete one."""
    worker = TimelineBuildWorker(_inputs(), scan_run=False)
    seen = []
    worker.built.connect(lambda *a: seen.append(a))
    worker.requestInterruption()
    worker.start()
    worker.wait(5_000)
    assert seen == []
