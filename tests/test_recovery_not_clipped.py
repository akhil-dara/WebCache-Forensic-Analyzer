"""Nothing in the recovery surface is clipped.

A real screenshot of the running app, taken immediately after a recovery
scan, showed the "Recover deleted records..." button's text clipped at
both ends ("ecover deleted rec") and the Deleted Records sidebar badge
showing "8" for 418 records.

Both symptoms trace to the SAME root cause, and it is not "the harness
grabbed a frame too early": QWidget.grab() renders through Qt's own paint
engine directly into a pixmap (see webcache/__main__.py's module docstring
on _maybe_self_shot, which relies on exactly that property for its own
packaged-build screenshot) -- it does not touch the OS compositor, so
whatever grab() renders is what a real repaint would show if one landed at
that instant. Reproducing with an instrumented harness proved the widget
tree really does sit in a too-narrow
state for one full event-loop turn:

- `count_label`/`recover_button` get their new TEXT set synchronously
  (QLabel.setText / QPushButton.setText), but their WIDTH is owned by the
  enclosing layout, which only re-measures sizeHint() on the NEXT
  QEvent::LayoutRequest -- a separate, deferred event, not delivered
  within the same call. Between those two moments the widget holds new
  text at old width.
- _on_recovery_loaded (main_window.py) sets the sidebar's "recovery" count
  and flips the button's text back from "Recovering..." synchronously, in
  one handler, with no processEvents() in between and no wait after it
  returns -- so if the very next thing Qt does is repaint (an expose
  event, a window restore, anything that forces a frame), it paints the
  stale width.

So these tests check the width in that exact window: immediately after
the state change, with NO qtbot.wait()/processEvents() afterward to let
the deferred layout catch up -- a test that waits 50ms after each change
cannot see the race. Once
recover_button/count_label carry an explicit setMinimumWidth() sized to
their own text, QWidget.setMinimumSize's own synchronous resize() (see
Qt's source: a widget already smaller than a newly-set minimum is resized
on the spot, not on the next layout pass) closes the window the deferred
layout otherwise leaves open.

A badge test (`test_a_nav_badge_shows_its_whole_number` below) that never
calls `sidebar.set_loaded(True)` -- a bare
`MainWindow()` starts every nav row DORMANT (see NavRow.set_dormant),
and `_repaint_count` paints a permanent dash for a dormant row regardless
of what `set_count` was just told. Without it, `count_label` shows "-"
the whole time and the assertion fails because the wrong text is on
screen, not because of any width defect -- a red for the wrong reason.
`set_loaded(True)` is added here so the
label is actually showing "1,028" when the width is checked.

Two more things:

1. The button fix (recover_button.setMinimumWidth in views/recovery.py)
   had no committed test that failed without it -- every test above that
   touches the button used a bare RecoveryView, and a bare QPushButton's
   own sizeHint-driven width already happens to resolve synchronously
   enough in that narrow scaffold to pass either way.
   `test_the_recover_button_survives_a_real_scan_round_trip_unclipped`
   below drives the REAL path instead: a real MainWindow, RecoveryLoader
   monkeypatched to test_recovery_wiring.py's own synchronous stand-in
   (`_DeferredFakeRecoveryLoader`, whose `finish_now` calls the real
   `_on_recovery_loaded` directly -- same thread, no event-loop queueing
   at all), and checks the button's width the instant `finish_now()`
   returns, no wait -- the exact production sequence.

2. Sidebar.SIDEBAR_WIDTH is a fixed 208px, and a count badge sized for
   its own full text can claim enough of that width that
   the destination's NAME -- "Deleted Records", "Table Browser" -- gets
   squeezed by the row's internal layout, and a plain QLabel does not
   elide on its own; it just clips mid-glyph. `test_a_nav_badge_and_the_
   destination_name_both_survive_a_huge_count` below drives
   `sidebar.set_count("recovery", ...)` with 100,000 and then 1,234,567
   on a real MainWindow sidebar and checks BOTH, in priority order: the
   count is always shown whole, and the name keeps at least its first 6
   characters visible, elided with "…" rather than cut. See
   NavRow._reflow_name and NavRow._repaint_count's own docstrings in
   shell/sidebar.py for the fix: honest elision computed from the TRUE
   remaining width (never inflated to pretend there is more room than
   there is), plus a smaller badge font once a count reaches 5+ digits,
   so the name has room to keep those 6 characters in the first place.
"""
import pytest

from webcache.shell.main_window import MainWindow
from webcache.views.recovery import RecoveryView

from tests.fixtures import make_rows
from tests.test_recovery_wiring import (
    _DeferredFakeRecoveryLoader, _FakeEngine, _FakeParser, _open_exhibit,
    _start_scan, _history_carved_record)


def _start_scan_while_viewing_recovery(win, monkeypatch, tmp_path,
                                       name="exhibit.dat"):
    """Exactly test_recovery_wiring.py's own _start_scan, except the
    Deleted Records page is made the CURRENT one (win.go_to("recovery"))
    before the scan starts -- the given shot.py harness's own sequence
    (win.go_to("recovery"); ...; win._start_recovery()). A page that is
    never the QStackedWidget's CURRENT widget never gets a real layout
    pass at all (verified directly), so without this the button's width
    is some leftover default and the assertion cannot fail for the right
    reason either way."""
    from webcache.shell import main_window as mw
    monkeypatch.setattr(mw, "RecoveryLoader", _DeferredFakeRecoveryLoader)
    path = str(tmp_path / name)
    parser = _FakeParser(name)
    _open_exhibit(win, monkeypatch, path, rows=make_rows(5), parser=parser)
    win.go_to("recovery")
    win.recover_action.trigger()
    return _DeferredFakeRecoveryLoader.instances[-1]


def test_the_recover_button_is_wide_enough_for_its_label(qtbot):
    v = RecoveryView()
    qtbot.addWidget(v)
    v.resize(1228, 700)
    v.show()
    qtbot.waitExposed(v)
    b = v.recover_button
    assert b.width() >= b.fontMetrics().horizontalAdvance(b.text()) + 24


def test_the_recover_button_survives_a_scanning_round_trip_unclipped(qtbot):
    """The exact sequence _on_recovery_loaded/_start_recovery drive: the
    button's text goes "Recover deleted records..." -> "Recovering..." ->
    "Recover deleted records..." again, synchronously, with no wait after
    the final flip -- the moment the real screenshot was taken in. Kept
    as a guard even though a bare RecoveryView alone cannot fail this
    assertion either way (see test_the_recover_button_survives_a_real_
    scan_round_trip_unclipped below for the version that can)."""
    v = RecoveryView()
    qtbot.addWidget(v)
    v.resize(1228, 700)
    v.show()
    qtbot.waitExposed(v)
    b = v.recover_button
    v.set_scanning(True)
    v.set_scanning(False)
    # No qtbot.wait()/processEvents() here on purpose -- see module
    # docstring: that is exactly the window the original defect lived in.
    assert b.width() >= b.fontMetrics().horizontalAdvance(b.text()) + 24


def test_a_nav_badge_shows_its_whole_number(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    # set_loaded(True): see module docstring -- without it every row is
    # dormant and set_count never reaches the screen at all.
    w.sidebar.set_loaded(True)
    w.sidebar.set_count("recovery", 0)
    qtbot.wait(50)
    w.sidebar.set_count("recovery", 1028)
    qtbot.wait(50)
    label = w.sidebar._rows["recovery"].count_label
    assert label.width() >= label.fontMetrics().horizontalAdvance("1,028")


def test_a_nav_badge_shows_its_whole_number_right_after_the_count_changes(qtbot):
    """Same assertion as above, but WITHOUT the settling waits -- the
    sidebar's own set_count("recovery", ...) calls inside
    _on_recovery_loaded run back to back with nothing in between, and the
    real screenshot was taken without ever giving Qt a spare event-loop
    turn to re-measure the label first."""
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.sidebar.set_loaded(True)
    label = w.sidebar._rows["recovery"].count_label
    w.sidebar.set_count("recovery", 0)
    w.sidebar.set_count("recovery", 1028)
    # No qtbot.wait()/processEvents() here on purpose -- see module
    # docstring.
    assert label.width() >= label.fontMetrics().horizontalAdvance("1,028")


# --- (code review): real-path tests -----------------------------

@pytest.fixture
def win(qtbot):
    """Identical to test_recovery_wiring.py's own `win` fixture -- a real,
    reasonably-sized MainWindow (1600x900, same as that module), not a
    cramped default: the sidebar's nav-list scrollbar only activates when
    the window is too short for all 16 destinations, and an active
    scrollbar's own reserve eats another 12px this file's big-count
    arithmetic already accounts for at this size."""
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    return w


def test_the_recover_button_survives_a_real_scan_round_trip_unclipped(
        win, monkeypatch, tmp_path):
    """The REAL path: a real MainWindow, a real _start_recovery/_on_
    recovery_loaded, RecoveryLoader monkeypatched to test_recovery_
    wiring.py's own synchronous stand-in. loader.finish_now(engine) calls
    self.loaded.emit(engine), which invokes the real _on_recovery_loaded
    DIRECTLY (same thread, no event-loop queueing) -- so checking the
    button's width the instant finish_now() returns, with no wait, is the
    exact production sequence: _push_recovery_state (inside _on_recovery_
    loaded) calls recovery_view.set_scanning(False), flipping the
    button's text back from "Recovering..." to "Recover deleted
    records...", and nothing runs a layout pass before this assertion
    does.

    win.go_to("recovery") matters here, not just cosmetically -- see
    _start_scan_while_viewing_recovery's own docstring.

    recovery_view.layout().activate() (right after the scan starts, NOT
    after it finishes) matters too, and deserves its own explanation: on
    a real, on-screen window this button's width settles down to fit
    "Recovering…" on its own, through Qt's ordinary deferred-layout +
    repaint cycle -- proved directly against a real (non-offscreen)
    window while debugging this task. Under this suite's QT_QPA_PLATFORM=offscreen, that same
    deferred layout pass does NOT run on its own even after real
    QTest.qWait()/processEvents() time (verified directly: with only
    those, the button sat at its widest-ever size throughout and this
    test could not fail even with the fix reverted -- a red for the
    wrong reason). layout().activate() forces that ONE settle
    synchronously, standing in for the natural repaint a real display
    would already have done by this point. It is called ONLY here, once,
    to reach the state a real user would already be looking at DURING the
    scan -- never after finish_now(), because forcing a second settle
    there would erase the exact race being tested: production code itself
    never calls activate() (or processEvents(), or anything else) between
    _push_recovery_state's set_scanning(False) and this method returning."""
    recovery_view = win._ensure_view_built("recovery")
    b = recovery_view.recover_button
    loader = _start_scan_while_viewing_recovery(win, monkeypatch, tmp_path)
    recovery_view.layout().activate()
    loader.finish_now(_FakeEngine(
        structured_records=[_history_carved_record()]))
    # No qtbot.wait()/processEvents()/activate() here on purpose -- see
    # docstring above.
    assert b.width() >= b.fontMetrics().horizontalAdvance(b.text()) + 24


def test_a_nav_badge_and_the_destination_name_both_survive_a_huge_count(
        win, monkeypatch, tmp_path):
    """A real MainWindow sidebar (per the review finding), driven with
    set_count("recovery", ...) at 100,000 and then 1,234,567. Required
    outcome, in priority order:

    1. The count is ALWAYS shown whole -- a clipped number is a false
       number, and this can never be sacrificed.
    2. The destination's own name ("Deleted Records") stays identifiable
       -- at least its first 6 characters visible, elided with "…" rather
       than cut, if the badge's own width leaves no room for the rest.
    """
    win.sidebar.set_loaded(True)
    row = win.sidebar._rows["recovery"]
    label = row.count_label
    name = row.text_label
    full_name = row._full_label

    for total in (100_000, 1_234_567):
        expected = format(total, ",")
        win.sidebar.set_count("recovery", total)

        # 1. the count is shown whole.
        assert label.text() == expected
        assert label.width() >= label.fontMetrics().horizontalAdvance(expected)

        # 2. the name keeps at least 6 characters, honestly elided.
        shown = name.text()
        if shown != full_name:
            assert shown.endswith("…"), (
                "name was cut without an ellipsis: %r" % shown)
            visible = shown[:-1]
        else:
            visible = shown
        assert len(visible) >= 6, (
            "only %r of %r stayed visible for count %s"
            % (shown, full_name, expected))
        # And never wider than the room the row's own layout actually
        # granted it, or "elided" is a fiction the width fix has no way
        # to prove.
        assert name.width() >= name.fontMetrics().horizontalAdvance(shown)


def test_a_real_scan_can_also_drive_the_badge_to_a_huge_count(
        win, monkeypatch, tmp_path):
    """The same requirement as the test above, but reached through the
    real recovery path (RecoveryLoader -> _on_recovery_loaded ->
    sidebar.set_count("recovery", len(recovery_rows))) rather than calling
    Sidebar.set_count directly -- proves main_window.py really does hand
    the sidebar a number this large when a scan's carved yield is large,
    not just that the sidebar can display one if asked. Capped at a few
    thousand structured records (not 1,234,567 -- building that many
    fixture dicts would make the test itself the slow thing), which is
    already five digits and already exercises the same font-shrink path
    the huge-count test above pins exactly."""
    row = win.sidebar._rows["recovery"]
    label = row.count_label
    name = row.text_label
    total = 12_345
    loader = _start_scan(win, monkeypatch, tmp_path)
    loader.finish_now(_FakeEngine(structured_records=[
        _history_carved_record("https://example.com/%d" % i)
        for i in range(total)]))

    expected = format(total, ",")
    assert label.text() == expected
    assert label.width() >= label.fontMetrics().horizontalAdvance(expected)
    shown = name.text()
    visible = shown[:-1] if shown.endswith("…") else shown
    assert len(visible) >= 6


# --- a big count stays legible ---------------------------

def _badge_font_px(label):
    import re
    m = re.search(r"font-size:\s*(\d+)px", label.styleSheet())
    return int(m.group(1)) if m else None


def test_a_five_digit_badge_is_painted_at_a_legible_size(win):
    """6 px is not a number an examiner can check at a glance;
    counts of 10,000+ are realistic for Dashboard, History and Timeline.
    Large counts now use 9 px, named, not an inline literal."""
    from webcache.shell import sidebar
    assert getattr(sidebar, "_BADGE_FONT_PX", None) == 11
    assert getattr(sidebar, "_BADGE_FONT_PX_LARGE", None) == 9
    assert getattr(sidebar, "_BADGE_LARGE_DIGITS", None) == 5
    win.sidebar.set_loaded(True)
    label = win.sidebar._rows["recovery"].count_label
    win.sidebar.set_count("recovery", 1_234)
    assert _badge_font_px(label) == 11
    win.sidebar.set_count("recovery", 12_345)
    assert _badge_font_px(label) == 9
