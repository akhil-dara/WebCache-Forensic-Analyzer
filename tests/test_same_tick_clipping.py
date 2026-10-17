"""Nothing is clipped in the same tick a scan lands.

On-screen verification at 1488x768 showed "Export view (N)" and the
sidebar's 4-digit "Deleted Records" badge clipped. The cause: text changed inside _on_recovery_loaded while the
enclosing layouts only re-measure on the NEXT posted LayoutRequest, and
NavRow._repaint_count's setMinimumWidth resized the badge IN PLACE,
anchored at its old x (the narrow dash), so it grew right past the nav
viewport. Any grab() or expose in that window showed clipped text.

The probe below is connected to the loader's `loaded` signal AFTER
MainWindow's own slot, so it runs in the same emit, right after
_on_recovery_loaded returns -- before any event-loop turn could run the
deferred layout pass and hide the defect.
"""
import pytest

from webcache.shell.main_window import MainWindow

from tests.fixtures import make_rows
from tests.test_recovery_wiring import (
    _DeferredFakeRecoveryLoader, _FakeEngine, _FakeParser, _open_exhibit,
    _history_carved_record)


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1488, 768)
    w.show()
    qtbot.waitExposed(w)
    return w


def _settle(qtbot, win):
    """Bring the window to the steady state an examiner would be looking
    at before the scan lands. doItemsLayout: under the offscreen platform
    a second MainWindow in one process keeps its nav rows at the list's
    pre-resize width (628 px, observed before any change here) until the
    list lays its items out again -- an artifact of the test process, not
    of the app, which only ever builds one window."""
    for _ in range(3):
        qtbot.wait(20)
        win.sidebar.nav.doItemsLayout()
        win.layout().activate()


def _probe_after_scan(win, qtbot, monkeypatch, tmp_path, total=2_742):
    """Open, view Deleted Records, scan, and measure in the same emit."""
    from webcache.shell import main_window as mw
    monkeypatch.setattr(mw, "RecoveryLoader", _DeferredFakeRecoveryLoader)
    path = str(tmp_path / "exhibit.dat")
    _open_exhibit(win, monkeypatch, path, rows=make_rows(5),
                  parser=_FakeParser("exhibit"))
    view = win._ensure_view_built("recovery")
    win.go_to("recovery")
    _settle(qtbot, win)
    win.recover_action.trigger()
    loader = _DeferredFakeRecoveryLoader.instances[-1]
    view.layout().activate()
    _settle(qtbot, win)

    seen = {}

    def probe(_engine):
        viewport = win.sidebar.nav.viewport()
        edges = {}
        for key, row in win.sidebar._rows.items():
            label = row.count_label
            if not label.isVisible():
                continue
            right = label.mapTo(viewport, label.rect().topRight()).x()
            edges[key] = (right, label.text())
        seen["viewport_width"] = viewport.width()
        seen["edges"] = edges
        seen["export"] = (view.export_button.width(),
                          view.export_button.sizeHint().width(),
                          view.export_button.text())

    loader.loaded.connect(probe)
    loader.finish_now(_FakeEngine(structured_records=[
        _history_carved_record("https://example.test/%d" % i)
        for i in range(total)]))
    return view, seen


def test_every_badge_stays_inside_the_nav_viewport_the_instant_a_scan_lands(
        win, qtbot, monkeypatch, tmp_path):
    _view, seen = _probe_after_scan(win, qtbot, monkeypatch, tmp_path)
    assert seen["edges"]["recovery"][1] == "2,742"
    over = {k: v for k, v in seen["edges"].items()
            if v[0] > seen["viewport_width"]}
    assert not over, (
        "badge right edge past the %dpx nav viewport: %r"
        % (seen["viewport_width"], over))


def test_export_view_button_is_whole_the_instant_a_scan_lands(
        win, qtbot, monkeypatch, tmp_path):
    _view, seen = _probe_after_scan(win, qtbot, monkeypatch, tmp_path)
    width, hint, text = seen["export"]
    assert text == "Export view (2,742)"
    assert width >= hint, "%r painted %dpx wide, needs %dpx" % (
        text, width, hint)


def test_recover_button_floor_covers_both_of_its_texts(win):
    """A floor measured with horizontalAdvance on the unpolished font,
    before the accent QSS's font-weight 600, and left out the icon: 214
    against a real need of 242."""
    view = win._ensure_view_built("recovery")
    b = view.recover_button
    original = b.text()
    try:
        for scanning in (False, True):
            view.set_scanning(scanning)
            b.ensurePolished()
            assert b.minimumWidth() >= b.sizeHint().width(), (
                "%r: floor %d < size hint %d"
                % (b.text(), b.minimumWidth(), b.sizeHint().width()))
    finally:
        view.set_scanning(False)
    assert b.text() == original
