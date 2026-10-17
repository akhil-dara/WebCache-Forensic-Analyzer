"""A theme switch restyles only what is on screen.

Qt re-polishes every widget inside the window when the application
stylesheet changes, and the hidden views cost most of that. Built views
that are not on screen are parked outside the window during the switch
and brought back, refreshed for the new theme, when they are next shown.
Every lookup still reaches a parked view."""
from webcache.shell import theme
from webcache.shell.main_window import MainWindow


def _win(qtbot, tmp_path, monkeypatch):
    import webcache.paths as paths
    monkeypatch.setattr(paths, "settings_path", lambda: tmp_path / "s.json")
    win = MainWindow()
    qtbot.addWidget(win)
    for key in ("history", "domains", "recovery"):
        win._ensure_view_built(key)
    win.go_to("history")
    return win


def test_hidden_views_leave_the_window_during_a_switch(qtbot, tmp_path,
                                                        monkeypatch):
    win = _win(qtbot, tmp_path, monkeypatch)
    domains = win._built_widget("domains")
    win._toggle_theme()
    assert not win.isAncestorOf(domains)
    assert win._built_widget("domains") is domains
    assert win.isAncestorOf(win._built_widget("history"))


def test_a_parked_view_returns_restyled_when_shown(qtbot, tmp_path,
                                                    monkeypatch):
    win = _win(qtbot, tmp_path, monkeypatch)
    domains = win._built_widget("domains")
    calls = []
    monkeypatch.setattr(domains, "refresh_theme",
                        lambda: calls.append(theme.current_name()))
    win._toggle_theme()
    assert calls == []                          # deferred while hidden
    win.go_to("domains")
    assert win.isAncestorOf(domains)
    assert win.stack.currentWidget() is domains
    assert calls == [theme.current_name()]


def test_settings_still_reach_parked_views(qtbot, tmp_path, monkeypatch):
    win = _win(qtbot, tmp_path, monkeypatch)
    win._toggle_theme()
    win.set_grid_wrap(False)
    assert win._built_widget("domains").table._wrap is False
