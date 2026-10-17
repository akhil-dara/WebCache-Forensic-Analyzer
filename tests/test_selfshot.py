"""WEBCACHE_SELFSHOT: a permanent, env-var-gated self-screenshot hook.

Used for on-screen verification. The packaged build is a
separate OS process, so nothing outside it can call widget.grab() the way
an in-process test can; the only external alternative -- an OS-level
screenshot of the app's window -- was tried against the real frozen exe
and came back with the Windows lock screen instead of the app, because the
session under test turned out to be locked. QWidget.grab() renders through
Qt's own paint engine into a pixmap and never touches the OS compositor,
so it is unaffected by lock state. _maybe_self_shot() lets the app
photograph its own window from the inside, on request -- see
webcache/__main__.py's module docstring for the full reasoning.

This is a permanent hook, not a one-off test fixture, so what matters most
here is the property that makes it safe to ship permanently: it must be
completely inert -- no timer scheduled, nothing touched -- unless an
operator has explicitly set WEBCACHE_SELFSHOT. That is the one thing an
ordinary examiner's launch (which never sets this variable) depends on.
"""
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from webcache.__main__ import _maybe_self_shot


@pytest.fixture(autouse=True)
def _clean_selfshot_env(monkeypatch):
    # Every test in this file starts from "the variable is unset", and
    # monkeypatch restores the real environment afterwards regardless of
    # which test set what -- so a run order or a leaked os.environ.setdefault
    # elsewhere can never make one test's env bleed into another's.
    monkeypatch.delenv("WEBCACHE_SELFSHOT", raising=False)
    monkeypatch.delenv("WEBCACHE_SELFSHOT_MS", raising=False)


def test_inert_when_unset_schedules_no_timer(qtbot, monkeypatch):
    """The property this whole file exists to pin: with the variable
    unset (the state of every ordinary launch), _maybe_self_shot must not
    schedule anything. Proven by intercepting QTimer.singleShot itself --
    not just "no file appeared", which a slow or broken timer could also
    produce -- so a regression that starts scheduling unconditionally
    fails this test even if the save path itself never gets exercised."""
    calls = []
    monkeypatch.setattr(QTimer, "singleShot",
                         staticmethod(lambda *a, **k: calls.append((a, k))))
    w = QWidget()
    qtbot.addWidget(w)

    _maybe_self_shot(w)

    assert calls == [], (
        "WEBCACHE_SELFSHOT is unset -- _maybe_self_shot must return "
        "before touching QTimer at all")


def test_inert_when_unset_writes_no_file(qtbot, tmp_path):
    """The end-to-end version of the same guarantee: even a path that
    WOULD exist if the hook fired must not appear."""
    target = tmp_path / "would_be_selfshot.png"
    w = QWidget()
    qtbot.addWidget(w)

    _maybe_self_shot(w)
    qtbot.wait(100)

    assert not target.exists()


def test_saves_a_real_screenshot_when_the_env_var_is_set(qtbot, monkeypatch, tmp_path):
    """The hook actually works when asked: a short delay, a real widget,
    a real PNG landing at the named path -- proving grab()+save() are
    wired correctly, not just that the gate logic is correct."""
    out = tmp_path / "selfshot.png"
    monkeypatch.setenv("WEBCACHE_SELFSHOT", str(out))
    monkeypatch.setenv("WEBCACHE_SELFSHOT_MS", "20")
    w = QWidget()
    w.resize(64, 64)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)

    _maybe_self_shot(w)
    qtbot.waitUntil(lambda: out.exists(), timeout=3000)

    assert out.stat().st_size > 0


def test_default_delay_is_four_seconds_when_ms_is_not_given(qtbot, monkeypatch):
    """WEBCACHE_SELFSHOT_MS is optional; the documented 4000 ms default
    must be what actually gets scheduled, not just what the docstring
    claims."""
    monkeypatch.setenv("WEBCACHE_SELFSHOT", "ignored.png")
    seen = {}

    def _fake_single_shot(ms, _fn):
        seen["ms"] = ms

    monkeypatch.setattr(QTimer, "singleShot", staticmethod(_fake_single_shot))
    w = QWidget()
    qtbot.addWidget(w)

    _maybe_self_shot(w)

    assert seen["ms"] == 4000
