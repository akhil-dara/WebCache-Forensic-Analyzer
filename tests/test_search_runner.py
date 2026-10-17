"""SearchRunner: a cross-table search off the GUI thread, on its OWN
file handle.

TWO HANDLES, TWO SEEK POSITIONS. Every other worker in this application
either owns its parser outright or shares the GUI's; the recovery worker
MUST share it, because carving needs that db object. A search must not.
A search is the one background operation whose whole duration invites the
examiner to keep using the Table Browser and the blob viewer -- and both
of those read the GUI parser's single file handle. So this worker opens
its own WebCacheParser on the same path, with the consent gate's already
computed hashes passed through so a multi-gigabyte exhibit is not
re-hashed (measured: 1.06 s of open against a 6.5-7.8 s search).

A CANCELLED SEARCH REPORTS NOTHING. The codebase's one idiom for an
interrupted worker -- recovery_loader.py's CANCEL-DISCARD RULE. A partial
hit list standing in for a complete one is the failure this closes: an
examiner reading "3 hits" cannot tell a finished search from a scan that
stopped a fifth of the way through.

Mirrors test_timeline_builder.py's shutdown-discipline tests exactly:
unparented worker, tracked in consent._RUNNING_WORKERS, self-cleaning via
finished -> deleteLater.
"""
import pytest

from webcache.engine import ese_parser
from webcache.shell import consent, search_loader, search_runner
from webcache.shell.search_runner import SearchRunner, SearchWorker


def _query(keyword="needle", table_filter=""):
    return search_loader.SearchQuery(
        keyword, table_filter=table_filter, scope_label="All tables",
        db_path="C:/case/WebCacheV01.dat",
        known_hashes={"C:/case/WebCacheV01.dat": "a" * 64})


def _engine_result(row_index=1):
    return {
        "table": "Container_1", "table_type": "History",
        "container_name": "History", "column": "Url",
        "matched_columns": ["Url"], "match_value": "https://example.test/a",
        "match_in_blob": False, "match_raw": "https://example.test/a",
        "match_raw_type": "text", "url": "https://example.test/a",
        "row_index": row_index, "row": {"Url": "https://example.test/a"},
    }


class _FakeParser:
    """WebCacheParser's surface, as far as the worker touches it."""

    opened = []
    closed = []
    open_raises = None

    def __init__(self):
        self.table_names = ["T1", "T2", "T3"]
        self.search_skipped_tables = []
        self.calls = []

    def open(self, path, known_hashes=None):
        if _FakeParser.open_raises is not None:
            raise _FakeParser.open_raises
        _FakeParser.opened.append((path, known_hashes))
        return True

    def search_all_tables(self, keyword, table_filter="", max_results=0,
                          progress_callback=None):
        self.calls.append((keyword, table_filter, max_results))
        for i in (1, 2, 3):
            if progress_callback is not None:
                progress_callback(i * 200, i, 3, "T%d" % i)
        self.search_skipped_tables = [("MSysObjects", "page checksum")]
        return [_engine_result(1), _engine_result(2)]

    def close(self):
        _FakeParser.closed.append(self)


@pytest.fixture(autouse=True)
def _fake_engine(monkeypatch):
    _FakeParser.opened = []
    _FakeParser.closed = []
    _FakeParser.open_raises = None
    monkeypatch.setattr(search_runner.ese_parser, "WebCacheParser",
                        _FakeParser)
    yield


def _run_worker(qtbot, worker, signal, timeout=10_000):
    with qtbot.waitSignal(signal, timeout=timeout) as blocker:
        worker.start()
    worker.wait(timeout)
    return blocker


# --- its own parser, its own handle ---------------------------------------

def test_the_worker_opens_its_own_parser_on_the_querys_path(qtbot):
    worker = SearchWorker(_query())
    _run_worker(qtbot, worker, worker.found)
    assert [path for path, _h in _FakeParser.opened] == [
        "C:/case/WebCacheV01.dat"]


def test_the_known_hashes_travel_so_the_exhibit_is_not_re_hashed(qtbot):
    worker = SearchWorker(_query())
    _run_worker(qtbot, worker, worker.found)
    assert _FakeParser.opened[0][1] == {"C:/case/WebCacheV01.dat": "a" * 64}


def test_the_parser_is_closed_when_the_search_finishes(qtbot):
    worker = SearchWorker(_query())
    _run_worker(qtbot, worker, worker.found)
    assert len(_FakeParser.closed) == 1


def test_the_parser_is_closed_even_when_the_search_fails(qtbot):
    class _Exploding(_FakeParser):
        def search_all_tables(self, *a, **k):
            raise OSError("page checksum")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(search_runner.ese_parser, "WebCacheParser", _Exploding)
        worker = SearchWorker(_query())
        _run_worker(qtbot, worker, worker.failed)
    assert len(_FakeParser.closed) == 1


# --- what lands on the GUI thread ----------------------------------------

def test_a_finished_search_emits_rows_already_shaped_by_the_loader(qtbot):
    """Row shaping is pure and Qt-free, so it runs on the WORKER -- the
    GUI thread receives finished rows, never a list of engine results to
    walk."""
    worker = SearchWorker(_query())
    blocker = _run_worker(qtbot, worker, worker.found)
    query, payload = blocker.args
    assert query is worker._query
    assert [r["Table"] for r in payload["rows"]] == ["Container_1",
                                                     "Container_1"]
    assert payload["rows"][0]["_kind"] is not None


def test_the_payload_states_what_was_skipped_scanned_and_searched(qtbot):
    worker = SearchWorker(_query())
    blocker = _run_worker(qtbot, worker, worker.found)
    _query_out, payload = blocker.args
    assert payload["skipped"] == [("MSysObjects", "page checksum")]
    assert payload["rows_scanned"] == 600
    assert payload["tables"] == 3


def test_max_results_is_always_zero_because_a_search_must_not_stop_early(
        qtbot):
    seen = {}

    class _Recording(_FakeParser):
        def search_all_tables(self, keyword, table_filter="", max_results=0,
                              progress_callback=None):
            seen.update(keyword=keyword, table_filter=table_filter,
                        max_results=max_results)
            return _FakeParser.search_all_tables(
                self, keyword, table_filter, max_results, progress_callback)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(search_runner.ese_parser, "WebCacheParser", _Recording)
        worker = SearchWorker(_query(table_filter="T2"))
        _run_worker(qtbot, worker, worker.found)
    assert seen == {"keyword": "needle", "table_filter": "T2",
                    "max_results": 0}


# --- progress -------------------------------------------------------------

def test_progress_states_real_counts_and_never_a_percentage(qtbot):
    seen = []
    worker = SearchWorker(_query())
    worker.progress.connect(seen.append)
    _run_worker(qtbot, worker, worker.found)
    assert seen, "a multi-second scan reported nothing at all"
    assert "table 3 of 3" in seen[-1]
    assert "600 row(s) scanned" in seen[-1]
    assert not any("%" in message for message in seen), (
        "three tables hold 73% of the sample exhibit's rows, so a "
        "percentage over table count would be fabricated")


# --- cancellation ---------------------------------------------------------

def test_a_cancelled_worker_emits_nothing_at_all(qtbot):
    """CANCEL-DISCARD. Not an empty result, not a partial one -- nothing,
    so the shell's own cancelled wording is what the examiner reads."""
    worker = SearchWorker(_query())
    found, failed = [], []
    worker.found.connect(lambda *a: found.append(a))
    worker.failed.connect(failed.append)
    worker.requestInterruption()
    worker.start()
    worker.wait(10_000)
    assert found == [] and failed == []


def test_the_cancellation_exception_is_a_subclass_of_the_engines_own(qtbot):
    """It has to be, or search_all_tables' per-table catch-all would
    swallow it and the scan would run to completion."""
    assert issubclass(search_runner._SearchCancelled,
                      ese_parser.SearchCancelled)


def test_a_cancelled_worker_still_closes_its_parser(qtbot):
    worker = SearchWorker(_query())
    worker.requestInterruption()
    worker.start()
    worker.wait(10_000)
    assert len(_FakeParser.closed) == 1


# --- failure --------------------------------------------------------------

def test_a_parser_that_cannot_be_opened_reports_failed(qtbot):
    _FakeParser.open_raises = RuntimeError("Failed to open database: nope")
    worker = SearchWorker(_query())
    blocker = _run_worker(qtbot, worker, worker.failed)
    assert "nope" in blocker.args[0]


def test_a_failed_search_emits_nothing_on_found(qtbot):
    _FakeParser.open_raises = RuntimeError("nope")
    worker = SearchWorker(_query())
    found = []
    worker.found.connect(lambda *a: found.append(a))
    _run_worker(qtbot, worker, worker.failed)
    assert found == []


# --- shutdown discipline --------------------------------------------------

def test_worker_is_never_parented(qtbot):
    assert SearchWorker(_query()).parent() is None


def test_start_registers_the_worker_in_the_shared_shutdown_set_and_self_cleans(
        qtbot):
    runner = SearchRunner()
    with qtbot.waitSignal(runner.found, timeout=10_000):
        runner.start(_query())
        qtbot.waitUntil(lambda: runner._worker is not None, timeout=2_000)
        assert runner._worker in consent._RUNNING_WORKERS
    worker = runner._worker
    qtbot.waitUntil(lambda: worker not in consent._RUNNING_WORKERS,
                    timeout=5_000)


def test_cancel_requests_interruption_on_the_worker(qtbot):
    calls = []

    class _Spy:
        def requestInterruption(self):
            calls.append(1)

    runner = SearchRunner()
    runner._worker = _Spy()
    runner.cancel()
    assert calls == [1]


def test_cancel_before_any_search_does_not_raise(qtbot):
    SearchRunner().cancel()


def test_the_table_number_and_the_table_name_describe_the_same_table(qtbot):
    """The engine reports tables COMPLETED, which is one behind while a
    table is still being read -- printed beside the name of the table
    currently being read, that is "table 1 of 3 (T2)"."""
    seen = []
    worker = SearchWorker(_query())
    worker.progress.connect(seen.append)
    _run_worker(qtbot, worker, worker.found)
    for i, name in ((1, "T1"), (2, "T2"), (3, "T3")):
        assert any("table %d of 3 (%s)" % (i, name) in m for m in seen), (
            "no message paired %d with %s: %r" % (i, name, seen))
