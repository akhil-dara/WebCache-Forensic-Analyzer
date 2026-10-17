import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from webcache.provenance import EvidenceSet
from webcache.shell import main_window, settings
from webcache.shell.main_window import ExplainDialog, MainWindow
from tests.fixtures import make_rows
from tests.test_literal_tooltips import shown

EXPECTED = ["dashboard", "history", "downloads", "search", "timeline",
            "domains", "location", "indicators", "iocs", "cookies",
            "headers", "containers", "recovery", "browser", "tagged",
            "integrity", "export"]


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def test_all_sixteen_views_are_present_and_in_order(win):
    """The app has 16 nav destinations. An earlier design draft planned for
    14 and dropped Integrity and Export & Report while 'keep every feature'
    was a stated decision."""
    assert win.nav_keys == EXPECTED


def test_the_downloads_view_is_labelled_file_access(win):
    """The key is 'downloads'; the name the examiner sees is not."""
    assert win.label_for("downloads") == "File Access"


def test_every_view_is_reachable_and_switching_is_a_stack_change(win):
    for key in win.nav_keys:
        win.go_to(key)
        assert win.current_key == key


def _click_nav_row(win, qtbot, key):
    """A REAL mouse click on the nav list at the given row's own position
    -- win.go_to(key) alone (as the test above uses) only proves the
    stack can switch; it says nothing about what happens when an
    examiner's mouse actually lands on a dormant row, which is the whole
    point of the tests below. NavRow.setEnabled(False) (see sidebar.py's
    set_dormant) dims a row's own painted contents, but does not stop
    QListWidget's own item hit-testing/selection -- verified directly,
    a real click at a dormant row's rect still changes nav.currentRow()
    -- so the item widget being visually disabled is not by itself a
    guarantee the click is refused."""
    for i in range(win.nav.count()):
        item = win.nav.item(i)
        if item.data(Qt.UserRole) == key:
            rect = win.nav.visualItemRect(item)
            QTest.mouseClick(win.nav.viewport(), Qt.LeftButton, pos=rect.center())
            return
    raise AssertionError("no nav row for %r" % key)


# --- a nav click before any evidence is open must not be a dead click ------
# The earlier version said "Load a database first" for exactly this
# situation. Before this fix, a click on a dormant row still fired
# QListWidget's currentItemChanged -> _nav_changed -> go_to(key): self.
# _current and the status bar's caveat silently changed to the clicked
# view's OWN wording, while content_stack stayed on FirstRunView -- so
# nothing an examiner could actually see ever changed, and the one thing
# that DID change (the status bar) said something misleading rather than
# useful.

def test_clicking_a_nav_row_before_evidence_is_loaded_says_so(win, qtbot):
    _click_nav_row(win, qtbot, "history")
    assert "load a database" in win.status_message().lower()


def test_clicking_a_nav_row_before_evidence_is_loaded_leaves_the_current_view_alone(win, qtbot):
    assert win.current_key == "dashboard"
    _click_nav_row(win, qtbot, "history")
    assert win.current_key == "dashboard"
    assert win.content_stack.currentIndex() == 0  # still FirstRunView, not the real stack


def test_clicking_a_nav_row_before_evidence_is_loaded_does_not_move_the_nav_highlight(win, qtbot):
    _click_nav_row(win, qtbot, "history")
    current_item = win.nav.item(win.nav.currentRow())
    assert current_item.data(Qt.UserRole) == "dashboard"


def test_a_nav_click_before_evidence_is_loaded_is_reachable_after_it_loads(win, qtbot):
    """The revert above must not leave the nav list permanently stuck --
    once evidence actually loads, the identical row must work exactly as
    test_every_view_is_reachable_and_switching_is_a_stack_change already
    proves it does when driven through go_to() directly."""
    win._on_evidence_loaded({"rows": make_rows(5), "parser": None},
                            _fake_evidence_set())
    _click_nav_row(win, qtbot, "history")
    assert win.current_key == "history"
    assert win.content_stack.currentIndex() == 1


# --- [7] the Export menu bypasses the identical not-yet-loaded guard -------
# "Export & Report..." (Ctrl+Shift+E) was wired straight to
# `lambda: self.go_to("export")` -- enabled from construction, unlike
# export_this_view_action, which go_to() itself already gates on whether
# the CURRENT view has a table. On a fresh window this moves self.stack's
# current index and the nav list's own selection while content_stack (see
# __init__ and _on_evidence_loaded) stays on FirstRunView, since nothing
# but _ever_loaded gates that swap -- a nav row that highlights over a
# screen that never moved, exactly the defect _nav_changed's own guard
# already exists to prevent for a genuine click on the nav list.

def test_the_export_menu_action_before_evidence_is_loaded_says_so(win):
    win.export_report_action.trigger()
    assert "load a database" in win.status_message().lower()


def test_the_export_menu_action_before_evidence_is_loaded_leaves_the_current_view_alone(win):
    assert win.current_key == "dashboard"
    win.export_report_action.trigger()
    assert win.current_key == "dashboard"
    assert win.content_stack.currentIndex() == 0, (
        "still FirstRunView, not the real stack")


def test_the_export_menu_action_before_evidence_is_loaded_does_not_move_the_nav_highlight(win):
    win.export_report_action.trigger()
    current_item = win.nav.item(win.nav.currentRow())
    assert current_item.data(Qt.UserRole) == "dashboard"


def test_the_export_menu_action_is_reachable_once_evidence_loads(win):
    win._on_evidence_loaded({"rows": make_rows(5), "parser": None},
                            _fake_evidence_set())
    win.export_report_action.trigger()
    assert win.current_key == "export"
    assert win.content_stack.currentIndex() == 1


def test_every_view_carries_a_forensic_caveat(win):
    """What each view does NOT prove. This is what makes the tool
    testifiable, and it belongs on the view, not in a Help menu."""
    for key in win.nav_keys:
        assert win.caveat_for(key), "%s has no caveat" % key


def test_the_deleted_records_caveat_explains_why_container_can_be_undeterminable(win):
    """An examiner reading a "Not determinable" Container cell has to be
    able to find out why without leaving the view -- the caveat line is
    where every other "what this does NOT prove" fact already lives.
    Plainly states the fact (no container record for a string carve) and
    that it is a property of carving, not the tool failing to read a
    field."""
    text = win.caveat_for("recovery").lower()
    assert "container" in text
    assert "not determinable" in text
    assert "did not preserve which container" in text


# --- provenance mode: removed rather than shipped half-built ---------------
# A full provenance mode is a large feature (dynamic provenance columns appearing on every one of the 16 views, every
# DERIVED cell showing its basis badge rather than just the few that
# carry OBS/DER today, a record dialog gaining the full chain including
# the source file's hash and raw bytes, the parse log and evidence set
# becoming directly reachable) -- none of it was ever built. Ctrl+Shift+P
# toggled a flag nothing else in the application read and printed a
# status line claiming the mode was "on". This project's own Explain-
# dialog docstring already named this exact class of defect ("a control
# that looks alive and is not... worse than not shipping it at all") and
# chose not to ship a hollow version of a bigger feature; removing this
# toggle is the identical choice, not a new one.

def test_no_provenance_mode_action_survives_in_the_view_menu(win):
    menu = win.menu_for_views()
    labels = [a.text() for a in menu.actions()]
    assert not any("provenance" in label.lower() for label in labels)


def test_ctrl_shift_p_is_no_longer_bound_to_anything(win):
    before = win.status_message()
    QTest.keyClick(win, Qt.Key_P, Qt.ControlModifier | Qt.ShiftModifier)
    assert win.status_message() == before


def test_provenance_mode_api_is_gone_not_just_unwired(win):
    """The point is not merely "nothing calls it" -- the API itself
    (property, setter, and the marker-visibility helper that existed only
    to be tested against the toggle) must not still be sitting there,
    reachable and claiming a mode that no longer means anything."""
    assert not hasattr(win, "provenance_mode")
    assert not hasattr(win, "set_provenance_mode")
    assert not hasattr(win, "origin_marker_visible")


# --- status bar: the trailing DB-summary segment --------------------------


class _FakeDbInfoParser:
    """Just enough of WebCacheParser's surface for the status bar's
    right-hand summary -- get_database_info()'s own return shape, not a
    real ESE database (none exists on this machine -- see the module
    docstring pattern every other *_loader test file already follows)."""

    def __init__(self, table_count, container_count, total_entries, db_state):
        self._info = {
            "table_count": table_count,
            "container_count": container_count,
            "total_entries": total_entries,
            "db_state": db_state,
            "db_state_text": {1: "Clean shutdown", 2: "Dirty shutdown",
                              3: "Being converted"}.get(db_state, str(db_state)),
        }
        # the status bar counts RECORDS (len(all_entries)), the parser's
        # own live list, not get_database_info()'s total_entries.
        self.all_entries = [{}] * total_entries

    def get_database_info(self):
        return self._info


def test_db_summary_is_empty_before_any_evidence_is_open(win):
    """Before evidence is open, show only what is true -- a zero here would
    read as a measurement of an exhibit that was never parsed."""
    assert win._db_summary_label.text() == ""


def test_db_summary_states_records_tables_containers_and_state(win):
    parser = _FakeDbInfoParser(table_count=83, container_count=34,
                               total_entries=993, db_state=2)
    win._on_evidence_loaded(
        {"rows": make_rows(5), "parser": parser}, _fake_evidence_set())
    text = win._db_summary_label.text()
    assert "993 live records (recovery not run)" in text
    assert "83" in text and "tables" in text
    assert "34" in text and "containers" in text
    assert "Dirty shutdown" in text


def test_db_summary_total_is_every_table_not_just_history(win):
    """total_entries is WebCacheParser.get_database_info()'s own count --
    every table (History, Cookies, HSTS, the certificate store...), a
    DIFFERENT number from the History-only live row count this same load
    also reports (in the status bar's other, left-hand message)."""
    parser = _FakeDbInfoParser(table_count=1, container_count=1,
                               total_entries=993, db_state=1)
    win._on_evidence_loaded(
        {"rows": make_rows(5), "parser": parser}, _fake_evidence_set())
    assert "993 live records" in win._db_summary_label.text()
    assert "5 live records" not in win._db_summary_label.text()


def test_dirty_shutdown_is_amber_but_never_colour_only(win):
    parser = _FakeDbInfoParser(table_count=1, container_count=1,
                               total_entries=1, db_state=2)
    win._on_evidence_loaded(
        {"rows": [], "parser": parser}, _fake_evidence_set())
    text = win._db_summary_label.text()
    assert "Dirty shutdown" in text, "the word itself must be there too"
    assert "color:" in text, "and reinforced with the amber colour"


def test_clean_shutdown_carries_no_amber_span(win):
    parser = _FakeDbInfoParser(table_count=1, container_count=1,
                               total_entries=1, db_state=1)
    win._on_evidence_loaded(
        {"rows": [], "parser": parser}, _fake_evidence_set())
    text = win._db_summary_label.text()
    assert "Clean shutdown" in text
    assert "<span" not in text


def test_db_summary_survives_a_parser_without_get_database_info(win):
    """Several tests below hand _on_evidence_loaded a minimal stand-in
    parser (identity only, no real ESE surface) -- this must never crash,
    and the honest answer is an empty summary, the same as before any
    evidence was opened."""
    win._on_evidence_loaded(
        {"rows": make_rows(5), "parser": object()}, _fake_evidence_set())
    assert win._db_summary_label.text() == ""


# --- status bar: the left-hand message must never collide with the
# --- permanent counters on the right ----------------------------------

def test_a_long_status_message_never_overlaps_the_permanent_counters(win, qtbot):
    """Observed verbatim on a real launch: "...run Evidence" (the tail of
    a per-view caveat) ran straight into "610 records" with no separation
    at all -- QStatusBar.showMessage() draws its text with no eliding and
    no guaranteed clearance from whatever is added via addPermanentWidget.
    A view's caveat wording is deliberate (this is NOT fixed by shortening
    it); the fix owns eliding on the DISPLAY side while the full sentence
    stays reachable.

    Reproduced with the real caveat text (dashboard's, genuinely long) and
    the real DB-summary segment (_on_evidence_loaded, with the exact
    counts from the observed collision: 610 records, 74 tables, 22
    containers, dirty shutdown) at a width narrow enough that the two
    cannot both fit -- the scenario the native, un-elided showMessage()
    could not handle.
    """
    parser = _FakeDbInfoParser(table_count=74, container_count=22,
                               total_entries=610, db_state=2)
    win._on_evidence_loaded(
        {"rows": make_rows(5), "parser": parser}, _fake_evidence_set())
    win.resize(1100, 700)  # the split status text is wider than "610 records", so 900 left no room at all
    qtbot.wait(10)
    win.go_to("dashboard")
    # Navigation no longer restates the caveat in the status bar; the
    # dashboard's caveat is still the long, real sentence to elide.
    win._set_status_message(win._caveats["dashboard"])
    qtbot.wait(10)

    full_text = win._caveats["dashboard"]
    assert len(full_text) > 40, "test needs a genuinely long caveat to prove anything"

    message = win._status_message
    counters = win._db_summary_label
    assert message.geometry().right() < counters.geometry().left(), (
        "the status message must never overlap or push the permanent counters")

    displayed = message.text()
    fm = message.fontMetrics()
    assert fm.horizontalAdvance(displayed) <= message.width(), (
        "the displayed text must actually fit -- elided, not clipped mid-pixel")
    assert displayed != full_text, "at this width the message must be elided"
    assert "…" in displayed or displayed.endswith("..."), (
        "an elided message must look elided, not just truncated silently")

    # The full sentence -- caveat wording is deliberate and must stay
    # reachable even though the screen only has room for part of it.
    assert win.status_message() == full_text
    assert shown(message.toolTip()) == full_text


def test_a_short_status_message_is_shown_in_full_with_no_ellipsis(win, qtbot):
    """The fix must not turn eliding into a blanket truncation -- a
    message that already fits is shown exactly as before."""
    win.resize(1600, 900)
    qtbot.wait(10)
    win.go_to("dashboard")
    # Navigation no longer restates the caveat in the status bar; the
    # dashboard's caveat is still the long, real sentence to elide.
    win._set_status_message(win._caveats["dashboard"])
    qtbot.wait(10)
    full_text = win._caveats["dashboard"]
    message = win._status_message
    assert message.text() == full_text
    assert "…" not in message.text()


def test_keyboard_shortcuts_reach_the_first_nine_views(win):
    for i, key in enumerate(win.nav_keys[:9], start=1):
        QTest.keyClick(win, getattr(Qt, "Key_%d" % i), Qt.ControlModifier)
        assert win.current_key == key


def test_views_beyond_nine_are_reachable_without_a_number_key(win):
    """Ctrl+1..9 cannot address 16 views. The rest must still be reachable
    by keyboard alone, through the View menu.

    Calling win.go_to("export") directly would only prove the stack can
    switch -- already covered by
    test_every_view_is_reachable_and_switching_is_a_stack_change -- and say
    nothing about whether a keyboard-only examiner can actually reach it.
    So this finds the real QAction the View menu exposes for "export" and
    fires it with .trigger(), which is the same call Qt itself makes when
    a menu item is chosen by keyboard (Alt to open the menu bar, arrow keys
    to the item, Enter) rather than by a mouse click.
    """
    menu = win.menu_for_views()
    assert menu is not None
    export_label = win.label_for("export")
    export_action = next(
        (a for a in menu.actions() if a.text() == export_label), None)
    assert export_action is not None, "no View-menu action for 'export'"
    assert export_action.isEnabled()
    export_action.trigger()
    assert win.current_key == "export"


def _default_here():
    """The size a fresh launch opens at ON THIS SCREEN.

    Not the literal _DEFAULT_SIZE: that is 1600x900 and the offscreen
    test screen is 800x800, exactly the situation default_size() exists
    to handle. Asserting the constant would pass only while the fallback
    ignored the screen it was opening on -- which was the bug."""
    from PySide6.QtGui import QGuiApplication
    return main_window.default_size(
        QGuiApplication.primaryScreen().availableGeometry().size())


def test_window_geometry_is_remembered(win, qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    win.resize(1234, 777)
    win.close()
    assert settings.get("window_geometry")


def test_close_event_survives_an_unwritable_settings_path(win, tmp_path, monkeypatch):
    """closeEvent calls settings.save() unconditionally -- this proves the
    whole close path survives an unwritable settings destination end to
    end, through the real closeEvent, not just settings.save() in
    isolation (see test_save_does_not_raise_when_the_destination_is_
    unwritable in test_theme_settings.py for that half)."""
    monkeypatch.setattr(
        "webcache.paths.settings_path",
        lambda: tmp_path / "no-such-directory" / "settings.json")
    win.close()  # must not raise


# --- restoring window geometry: the other half of remembering it -----------
# --- (test_window_geometry_is_remembered above only proves it is WRITTEN) --

def test_window_geometry_round_trips_through_settings(qtbot, tmp_path, monkeypatch):
    """test_window_geometry_is_remembered above only proves closeEvent
    WRITES a value; nothing before this fix ever read it back --
    restoreGeometry() was called nowhere in the application. This proves a
    second, later MainWindow actually restores the size an earlier one
    saved, through settings.py itself, the way a real re-launch would.

    700x600, not something closer to the 1600x900 default: tests run under
    QT_QPA_PLATFORM=offscreen (see conftest.py), whose virtual screen is
    only 800x800 -- Qt's own QWidget.restoreGeometry() clamps a restored
    size down to fit the CURRENT screen when it doesn't, which is entirely
    correct behaviour but would make a size near the real default
    indistinguishable from that clamping rather than from an actual
    restore. It also clears MIN_USABLE_SIZE, so this stays a test about
    round-tripping rather than one that happens to trip the floor below.
    """
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.show()
    qtbot.waitExposed(w1)
    w1.resize(700, 600)
    w1.close()

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.size().width() == 700
    assert w2.size().height() == 600


def test_a_corrupt_saved_geometry_falls_back_to_the_default_size(
        qtbot, tmp_path, monkeypatch):
    """Mirrors the discipline settings.load() already applies to a corrupt
    settings.json (test_corrupt_settings_file_does_not_stop_the_app in
    test_theme_settings.py): a hand-edited or truncated window_geometry
    hex string must not raise the moment a new MainWindow is constructed,
    and must not leave the window at some undefined size -- it falls back
    to the same default __main__.py used to set directly."""
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    settings.save(window_geometry="not-actually-hex-zz")

    w = MainWindow()  # must not raise
    qtbot.addWidget(w)
    assert (w.size().width(), w.size().height()) == _default_here()


def test_a_geometry_restored_off_every_current_screen_falls_back_to_the_default_size(
        qtbot, tmp_path, monkeypatch):
    """An examiner's saved position from a monitor that is no longer
    attached -- routine when moving between a docked workstation and a
    laptop -- must not strand the window off every screen that is
    actually there.

    QGuiApplication.screens() is monkeypatched to report a screen far from
    anywhere this window could plausibly land, rather than moving the
    window off-screen and saving THAT: verified directly that
    QWidget.restoreGeometry() itself repositions a rect that was saved
    entirely off the virtual desktop back onto it before this application's
    own _on_a_current_screen() check ever runs -- at least on this Qt
    version/platform, which is exactly why a real multi-monitor examiner
    still needs this application's own belt-and-braces check rather than
    trusting that Qt-internal behaviour on every platform. Monkeypatching
    screens() tests _on_a_current_screen's own fallback branch directly,
    independent of whether restoreGeometry() happens to pre-empt it.
    """
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.resize(600, 500)
    w1.close()

    class _FarAwayScreen:
        def geometry(self):
            return QRect(200_000, 200_000, 100, 100)

    monkeypatch.setattr(
        "webcache.shell.main_window.QGuiApplication.screens",
        staticmethod(lambda: [_FarAwayScreen()]))

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert (w2.size().width(), w2.size().height()) == _default_here()


# --- column widths: the machinery existed, nothing called it ---------------

_EVIDENCE_PATH = r"C:\case\WebCacheV01.dat"


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                        {_EVIDENCE_PATH: "a" * 64})


def test_column_widths_persist_through_settings_keyed_by_view_name(
        qtbot, tmp_path, monkeypatch):
    """RecordsTable.save_column_state()/restore_column_state() already
    round-trip in isolation
    (test_column_widths_round_trip_through_settings in
    test_records_table.py) -- that test passed even when nothing in the
    application called either method. This proves the actual wiring: a
    width an examiner sets survives through settings.py itself, under the
    "history" key (not a single shared blob -- see settings.py's own
    column_state comment on why that would corrupt as soon as a second
    view exists), across a real closeEvent and a fresh MainWindow opening
    the same view, driven through the real _on_evidence_loaded rather than
    calling HistoryView.set_records directly.
    """
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    evidence_set = _fake_evidence_set()

    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1._on_evidence_loaded({"rows": make_rows(20), "parser": None}, evidence_set)
    history1 = w1._ensure_view_built("history")
    address = [c.key for c in history1.table.model().columns].index("CleanUrl")
    history1.table.horizontalHeader().resizeSection(address, 521)
    w1.close()

    assert settings.get("column_state", {}).get("history"), (
        "column_state must be saved keyed by the view's own name")

    w2 = MainWindow()
    qtbot.addWidget(w2)
    w2._on_evidence_loaded({"rows": make_rows(20), "parser": None}, evidence_set)
    history2 = w2._ensure_view_built("history")
    assert history2.table.horizontalHeader().sectionSize(address) == 521


def test_column_state_is_restored_only_on_the_first_records_set(
        qtbot, tmp_path, monkeypatch):
    """_restore_column_state is a one-shot gate per view
    (self._column_state_restored): applied on the first records-set for a
    view and never again, so a SECOND Open Evidence in the same session
    does not silently re-read settings.json and snap columns back to
    whatever an EARLIER LAUNCH had saved.

    RecordsTable.set_records() always resets every column to its own
    declared default width first (_fit_columns(), keyed off Column.width)
    on every call regardless of this fix -- that part is pre-existing and
    not what this test is about. What this fix controls is only whether
    the ON-DISK state gets reapplied on top of that reset. Proved by
    saving a column-0 width that is neither the column's own default NOR
    whatever a naive "always restore" would coincidentally produce: if the
    one-shot gate were missing, the second Open Evidence below would read
    settings.json again and land back on that saved width instead of the
    column's own default.
    """
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    evidence_set = _fake_evidence_set()

    w = MainWindow()
    qtbot.addWidget(w)
    w._on_evidence_loaded({"rows": make_rows(20), "parser": None}, evidence_set)
    history = w._ensure_view_built("history")
    default_width = history.table.horizontalHeader().sectionSize(0)

    # A column-0 width from an EARLIER launch, captured as a real header
    # state blob (not a fabricated one) and deliberately different from
    # the column's own declared default.
    history.table.horizontalHeader().resizeSection(0, default_width + 200)
    earlier_launch_state = history.table.save_column_state().hex()
    settings.save(column_state={"history": earlier_launch_state})

    # A second Open Evidence in the same session: set_records() resets
    # column 0 back to its own default first: this must be the last word,
    # not the on-disk state from above landing on top of it a second time.
    w._on_evidence_loaded({"rows": make_rows(30), "parser": None}, evidence_set)
    assert history.table.horizontalHeader().sectionSize(0) == default_width


#: Every view _collect_column_state (main_window.py, ~line 1510) actually
#: saves -- the seven keys settings.json's own column_state carries. Kept
#: as a literal list, not read off MainWindow itself, so this test cannot
#: be satisfied by silently shrinking the set of views collected.
_COLUMN_STATE_VIEWS = ["history", "downloads", "domains", "indicators",
                       "cookies", "containers", "recovery"]


@pytest.mark.parametrize("key", _COLUMN_STATE_VIEWS)
def test_column_widths_persist_for_every_record_view_not_just_history(
        qtbot, tmp_path, monkeypatch, key):
    """_collect_column_state already saves all seven of these views' column
    state at close (test_column_widths_persist_through_settings_keyed_by_
    view_name above proves it for History alone) -- but restoring it back
    was only ever wired for "history" (_restore_column_state was called
    exactly once in _on_evidence_loaded). The other six views' saved
    widths were being collected and then never read back: an examiner who
    widened a column in, say, Containers or Recovery had it silently
    reset to the default on every relaunch. Mirrors the History-only test
    above, parametrized across every view that actually has column state
    to restore.

    Resized to 900, not 321: 321 sat below "downloads"'s
    own column 0 ("Downloaded (UTC)", a basis-badge column) once
    RecordsTable._enforce_heading_floor's badge-centring bug was fixed
    (records_table.py -- see that method's own docstring) to actually
    guarantee the margin it always claimed to, which raised that
    column's floor past 321. This test is about restore WIRING, not
    about any one column's own minimum width, so it now resizes past
    every one of these seven views' column-0 floors (verified directly)
    rather than a value that happened to clear the old, undersized one.
    """
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    evidence_set = _fake_evidence_set()

    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1._on_evidence_loaded({"rows": make_rows(20), "parser": None}, evidence_set)
    view1 = w1._ensure_view_built(key)
    view1.table.horizontalHeader().resizeSection(0, 900)
    w1.close()

    assert settings.get("column_state", {}).get(key), (
        "column_state must be saved for %r" % key)

    w2 = MainWindow()
    qtbot.addWidget(w2)
    w2._on_evidence_loaded({"rows": make_rows(20), "parser": None}, evidence_set)
    view2 = w2._ensure_view_built(key)
    assert view2.table.horizontalHeader().sectionSize(0) == 900


# --- Explain dialog: a Copy button, so the text goes into a report -------

_EXPLAIN_TEXT = ("Column: AccessedUtc\nValue: 2026-02-17 22:24:33\n\n"
                  "Live record in Container_6")


def test_explain_dialog_copy_button_puts_the_full_text_on_the_clipboard(
        win, qtbot):
    """The Explain output needs a Copy button "so it goes into a
    report". A button that exists but is not really wired
    proves nothing -- this clicks the real Copy button through Qt's own
    button-click machinery and reads back what actually landed on the
    system clipboard, the same discipline test_consent.py's
    test_copy_path_action_actually_copies_to_clipboard already uses for
    "Copy path". The clipboard content must be the exact text on screen --
    column, value, and provenance.describe_origin()'s line -- so what
    lands in a report matches what the examiner read, not a paraphrase of
    it.
    """
    dlg = ExplainDialog(win, _EXPLAIN_TEXT)
    qtbot.addWidget(dlg)
    qtbot.mouseClick(dlg.copy_button, Qt.LeftButton)
    assert QGuiApplication.clipboard().text() == _EXPLAIN_TEXT


def test_explain_dialog_copy_does_not_close_the_dialog(win, qtbot):
    """A QMessageBox closes on ANY button click, regardless of role --
    verified directly against a real QMessageBox before this fix was
    written. That would make "Copy" also dismiss the explanation before an
    examiner has necessarily finished reading it, so ExplainDialog is a
    purpose-built QDialog instead (see its own docstring). Proves the
    payoff of that choice: the dialog is still on screen, and still
    showing the same text, after Copy is clicked -- an examiner can copy,
    keep reading, and copy again without a round trip back through F1.
    """
    dlg = ExplainDialog(win, _EXPLAIN_TEXT)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    qtbot.mouseClick(dlg.copy_button, Qt.LeftButton)
    assert dlg.isVisible()
    assert dlg.result() != ExplainDialog.Accepted


# --- a saved size too small to work in -------------------------------------
#
# _on_a_current_screen() above asks only whether the restored rectangle
# OVERLAPS an attached screen. A window can overlap a screen perfectly
# and still be unusable: 820x360 was restored on this machine and the
# application was reported as "not launching", because at that height
# the content area is chrome with a sliver of table under it and at that
# width the sidebar takes a quarter of the window.
#
# The floor is deliberately low. Rejecting a size an examiner chose on
# purpose would be a worse bug than the one being fixed, so it sits at
# 640x480 -- the smallest full-screen mode Windows has ever offered, and
# below the smallest size anyone would drag a window to on purpose.


def test_a_saved_size_too_small_to_work_in_falls_back_to_the_default(
        qtbot, tmp_path, monkeypatch):
    """The reported defect, exactly: 820x360 was in settings.json and the
    window came back at 820x360 every launch."""
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.show()
    qtbot.waitExposed(w1)
    w1.resize(820, 360)
    w1.close()
    assert settings.get("window_geometry")

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert (w2.size().width(), w2.size().height()) == _default_here()


def test_the_floor_never_asks_for_more_than_the_screen_offers(qtbot):
    """A guard that demanded 640x480 on a 500x400 screen would reject
    every geometry there is and fight Qt's own clamping forever. Tested
    as the pure function rather than by faking a screen, because
    QGuiApplication.screens() cannot be replaced convincingly enough for
    the answer to mean anything."""
    from PySide6.QtCore import QSize
    assert main_window.geometry_floor(QSize(1920, 1080)) == \
        main_window.MIN_USABLE_SIZE
    assert main_window.geometry_floor(QSize(500, 400)) == (500, 400)
    assert main_window.geometry_floor(QSize(700, 300)) == (640, 300)


def test_a_size_at_the_floor_is_still_restored(qtbot, tmp_path, monkeypatch):
    """The fix must not become "ignore saved geometry". A size exactly on
    the floor is a size an examiner may have chosen, and is kept."""
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    floor_w, floor_h = main_window.MIN_USABLE_SIZE
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.show()
    qtbot.waitExposed(w1)
    w1.resize(floor_w, floor_h)
    w1.close()

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert (w2.size().width(), w2.size().height()) == (floor_w, floor_h)


# --- and a default bigger than the screen ----------------------------------
#
# The other half of the "not launching" report, and the one that produced
# "app launching in full expanded window on launch": _DEFAULT_SIZE is
# 1600x900 and this machine's desktop is 1536x816 of usable space. A
# fresh launch asked for a window larger than the screen in BOTH axes, so
# it filled the display and spilled off it, looking maximised without
# being maximised. Measured on the real machine, not inferred.


def test_a_fresh_launch_fits_on_the_screen_it_opens_on(
        qtbot, tmp_path, monkeypatch):
    from PySide6.QtGui import QGuiApplication
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    available = QGuiApplication.primaryScreen().availableGeometry()
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.size().width() <= available.width()
    assert w.size().height() <= available.height()


def test_the_default_is_untouched_on_a_screen_with_room_for_it(qtbot):
    from PySide6.QtCore import QSize
    assert main_window.default_size(QSize(2560, 1440)) == \
        main_window._DEFAULT_SIZE
    # 1920x1080, not 1600x900: a screen exactly the size of the
    # default has no room for _DEFAULT_MARGIN, and correctly gives
    # back slightly less. "Room for it" means room for the margin.
    assert (main_window.default_size(QSize(1920, 1080))
            == main_window._DEFAULT_SIZE)


def test_the_default_shrinks_to_fit_a_smaller_screen(qtbot):
    from PySide6.QtCore import QSize
    w, h = main_window.default_size(QSize(1536, 816))
    assert w <= 1536 and h <= 816
    # Not shrunk into uselessness either: still a working window.
    assert (w, h) >= main_window.MIN_USABLE_SIZE


# --- a maximized window must come back maximized ---------------------------
#
# Reported: "maximizer window not opening always". Root-caused rather than
# guessed at. Qt's QWidget.restoreGeometry() stores the width of the screen
# the geometry was saved on, and REFUSES the whole blob when that width
# differs from the current screen -- isolated by patching that one field in
# a real saved blob, which flipped the call from False to True and changed
# nothing else.
#
# That refusal is reasonable for a POSITION. Applying it to the maximized
# STATE is not: an examiner who docks a laptop, or moves between a 4K panel
# and a projector, changes the screen width every time, and loses "I work
# maximized" on every one of those launches. The flag is therefore saved
# and restored independently of Qt's blob.


def _blob_saved_on_another_screen(win):
    """This window's own geometry, restamped as if it were saved on a
    screen of a DIFFERENT width from the one running the test.

    The width is derived from the current screen rather than hardcoded.
    A first draft stamped 800 -- the width of the real settings.json this
    bug was traced from -- which is also exactly the width Qt reports
    under QT_QPA_PLATFORM=offscreen, so under pytest it removed the
    mismatch instead of creating one and the test passed while proving
    nothing.
    """
    import struct
    from PySide6.QtGui import QGuiApplication
    here = QGuiApplication.primaryScreen().geometry().width()
    blob = bytearray(bytes(win.saveGeometry()))
    struct.pack_into(">i", blob, 46, here + 736)   # screenWidth field
    return bytes(blob)


def test_qt_refuses_a_geometry_saved_on_a_different_width_screen(qtbot):
    """Pins the Qt behaviour the fix is built around. If a future Qt stops
    refusing these, this test fails and the workaround can be reconsidered
    rather than left in place forever as cargo."""
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(900, 600)
    assert w.restoreGeometry(_blob_saved_on_another_screen(w)) is False


def test_a_window_closed_maximized_reopens_maximized(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.show()
    qtbot.waitExposed(w1)
    w1.showMaximized()
    qtbot.wait(50)
    assert w1.isMaximized()
    w1.close()

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.isMaximized()


def test_the_maximized_state_survives_a_screen_the_geometry_cannot(
        qtbot, tmp_path, monkeypatch):
    """The actual reported bug. Qt throws the geometry away; the maximized
    state must not go with it."""
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.show()
    qtbot.waitExposed(w1)
    w1.showMaximized()
    qtbot.wait(50)
    w1.close()
    # Restamp the saved blob as if it came from a narrower screen, which is
    # what a harness under the offscreen platform actually wrote into a real
    # settings.json.
    settings.save(window_geometry=_blob_saved_on_another_screen(w1).hex())

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.isMaximized(), (
        "Qt refused the geometry and the maximized state was discarded "
        "with it")


def test_a_window_closed_not_maximized_does_not_come_back_maximized(
        qtbot, tmp_path, monkeypatch):
    """The fix must not become 'always maximize'."""
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    w1 = MainWindow()
    qtbot.addWidget(w1)
    w1.show()
    qtbot.waitExposed(w1)
    w1.resize(900, 620)
    w1.close()

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert not w2.isMaximized()


# --- maximised unless the examiner un-maximised ------------------------

@pytest.mark.launch_default
def test_a_first_launch_opens_maximised(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.windowState() & Qt.WindowMaximized


@pytest.mark.launch_default
def test_a_saved_state_without_the_flag_still_opens_maximised(
        qtbot, tmp_path, monkeypatch):
    """A settings file written before the flag existed carries a geometry
    and no window_maximized key. That is 'no saved state' for this
    question."""
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text('{"theme": "dark"}',
                                            encoding="utf-8")
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.windowState() & Qt.WindowMaximized


@pytest.mark.launch_default
def test_a_saved_false_restores_the_saved_geometry(qtbot, tmp_path,
                                                    monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    settings.save(window_maximized=False)
    w = MainWindow()
    qtbot.addWidget(w)
    assert not (w.windowState() & Qt.WindowMaximized)


def test_the_explain_popup_is_wide_enough_to_read(qtbot):
    """It opened 270 px wide: a two-sentence provenance answer wrapped
    into a tall, narrow block of eight lines."""
    dlg = ExplainDialog(None, "Column: Last visit (UTC)\nValue: 2025-06-23 "
                        "02:04:45\n\nCarved (deleted/unflushed) in History "
                        "from WebCacheV01.dat @ 0x005E022A (page 187) by "
                        "Structured record reconstruction, confidence high")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    assert dlg.width() >= 460, dlg.width()
