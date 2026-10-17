"""Shared fixtures.

Qt tests run offscreen so they need no display and never steal focus. This is
set before any PySide6 import, which is why it lives here rather than in a
test module.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# openpyxl's standard-library XML path, the one the packaged build takes
# (it excludes lxml). With lxml installed, openpyxl wrote a carriage
# return the safe way here and the raw, lossy way in the shipped program;
# the suite passed on this machine and failed on the release runner.
# openpyxl reads this switch once, at import, so it is set before any.
os.environ["OPENPYXL_LXML"] = "False"

from webcache import paths  # noqa: E402

from tests.fixtures import FIXTURE_COLUMNS, make_rows  # noqa: E402

_MISSING = object()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "launch_default: run with the application's real window_maximized "
        "default instead of the harness's un-maximised one")


@pytest.fixture(autouse=True)
def _windows_open_unmaximised_unless_asked(request):
    """The application opens maximised by default. The offscreen
    platform maximises to its 800x800 screen, and ~200 window tests size
    the window themselves and assert against that size -- so the harness
    opens windows un-maximised unless a test is marked launch_default,
    which is how the real default is tested."""
    from webcache.shell import settings
    if request.node.get_closest_marker("launch_default"):
        yield
        return
    original = settings.DEFAULTS.get("window_maximized", _MISSING)
    settings.DEFAULTS["window_maximized"] = False
    try:
        yield
    finally:
        if original is _MISSING:
            settings.DEFAULTS.pop("window_maximized", None)
        else:
            settings.DEFAULTS["window_maximized"] = original


#: The modules that must see the REAL paths.cases_dir -- they test it
#: (that it is created, where it sits for a portable, an installed and a
#: chosen location). Excluded by name deliberately: neither writes into
#: the checkout -- test_case_folder points the program at tmp_path first
#: -- which is the only thing the redirect below exists to prevent.
_PATHS_MODULES = {"test_paths", "test_case_folder"}


@pytest.fixture(autouse=True)
def _case_files_go_somewhere_disposable(request, tmp_path_factory):
    """Every case file a test opens lands in a temp directory.

    paths.cases_dir() is app-local by design -- keyed by the evidence
    SHA-256, never beside the exhibit -- and in a development checkout
    "app-local" IS the repository. Nothing in this application opened a
    CaseDb until the Export unit landed; now every MainWindow test that
    loads evidence opens one, so without this the suite would leave a
    .case.sqlite per fake exhibit in the source tree, permanently.

    autouse rather than a fixture each test file has to remember: a test
    that forgot it would silently write into the checkout, which is
    exactly the "works because everyone remembered" shape this project
    replaces with a mechanism. mkdir(parents=True, exist_ok=True) is kept
    so the replacement behaves like the real function it stands in for.
    """
    if request.module.__name__.rsplit(".", 1)[-1] in _PATHS_MODULES:
        yield None
        return
    directory = tmp_path_factory.mktemp("cases")
    original = paths.cases_dir

    def _cases_dir():
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    # settings.json gets the same treatment, and for a sharper reason
    # than tidiness. MainWindow.closeEvent calls settings.save()
    # unconditionally, the suite runs under QT_QPA_PLATFORM=offscreen, and
    # QWidget.saveGeometry() stamps the width of the screen it was saved
    # on -- 800 for the offscreen platform. Qt then REFUSES that blob on a
    # real display, so every suite run destroyed the developer's saved
    # window position and the application opened at its default instead.
    # It was reported as "maximizer window not opening always".
    settings_file = directory / "settings.json"
    original_settings = paths.settings_path
    paths.settings_path = lambda: settings_file

    paths.cases_dir = _cases_dir
    try:
        yield directory
    finally:
        paths.cases_dir = original
        paths.settings_path = original_settings


@pytest.fixture(autouse=True)
def _flush_deferred_deletes():
    """Drain Qt's DeferredDelete queue after every test.

    qtbot.addWidget() tears a widget down with close() + deleteLater();
    the actual C++ destructor only runs once the event loop processes
    that DeferredDelete event, which Qt schedules for "later" rather
    than now. Nothing forces "later" to arrive before the NEXT test
    starts, so a run of MainWindow-heavy tests (each building a full
    shell: sidebar, toolbar, every eagerly-built view) can leave a
    backlog of undestroyed widget trees sitting in the queue.

    That backlog is not free: found by profiling
    test_no_elision.py::test_a_long_value_list_lays_out_without_stalling,
    which measured runs of ~200-300ms of REAL CPU time (time.process_time()
    tracked time.perf_counter() almost exactly, ruling out an external
    process stealing the CPU) landing inside its own StallDetector window
    whenever it ran straight after test_main_window_integrity_browser.py
    and test_main_window_records_views.py -- the backlog's destructors
    fired mid-measurement and were attributed to the widget under test.
    A bare QLabel probe dropped into the same slot stalled by the same
    amount with no FilterPopup involved at all, which is what pins this
    on teardown debt rather than on the popup.

    Flushing here, once per test, keeps that debt from ever crossing a
    test boundary -- the next test's own StallDetector (if it has one)
    measures its own work, not a bill left by whichever heavy test ran
    before it.
    """
    yield
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


@pytest.fixture(autouse=True)
def _dialogs_see_a_real_sized_screen(request, monkeypatch):
    """The offscreen platform reports an 800x800 screen. The record
    dialog's room tests measure the examiner's real 1279x724 dialog, and
    clamping it to 800x800 would measure a window nobody uses. Tests of
    the clamp itself (tests/test_record_detail_fits.py) set their own
    room."""
    try:
        from PySide6.QtCore import QRect
        from webcache.shell import record_detail
    except ImportError:
        yield
        return
    if hasattr(record_detail, "screen_room"):
        monkeypatch.setattr(record_detail, "screen_room",
                            lambda _w: QRect(24, 24, 2512, 1392))
    yield


@pytest.fixture(scope="session")
def columns():
    return list(FIXTURE_COLUMNS)


@pytest.fixture(scope="session")
def rows_2k():
    return make_rows(2_000)


@pytest.fixture(scope="session")
def rows_20k():
    return make_rows(20_000)


@pytest.fixture(scope="session")
def rows_100k():
    return make_rows(100_000)


@pytest.fixture(autouse=True)
def _notes_start_folded():
    """NoteLine remembers an opened note per view for the session; a test
    that opens one must not leave the next test's view open."""
    from webcache.widgets import note_line
    note_line._STATE.clear()
    yield
    note_line._STATE.clear()


@pytest.fixture(scope="session")
def browser():
    """One headless Chrome/Edge for the whole session, over the DevTools
    protocol (tests/_browser.py). It skips, saying why, only where no
    browser exists. On the examiner's machine it always runs (offline HTML
    package plan, Global Constraints)."""
    from tests import _browser
    executable = _browser.find_browser()
    if executable is None:
        pytest.skip("no Chrome or Edge found (set WEBCACHE_BROWSER to one)")
    try:
        import websocket  # noqa: F401
    except ImportError:
        pytest.skip("websocket-client is not installed (pip install -e .[dev])")
    driver = _browser.Browser(executable)
    try:
        yield driver
    finally:
        driver.close()
