"""No test may write the developer's real settings.json.

conftest.py already redirects paths.cases_dir for exactly this reason,
and its own docstring argues the case: autouse "rather than a fixture
each test file has to remember: a test that forgot it would silently
write into the checkout, which is exactly the 'works because everyone
remembered' shape this project replaces with a mechanism."

settings_path was left on the honour system anyway. Twelve test files
close a MainWindow; seven redirect. MainWindow.closeEvent calls
settings.save() unconditionally, so the other five wrote the checkout's
own settings.json -- and because the suite runs under
QT_QPA_PLATFORM=offscreen, what they wrote was a window geometry stamped
with the offscreen platform's 800px-wide virtual screen.

That is not a tidiness problem. Qt refuses a geometry blob whose stored
screen width differs from the real display, so the developer's saved
window state was destroyed by every suite run, and the application
opened at its default size instead of where they left it. It was
reported as "maximizer window not opening always" and traced back to
here.
"""
import pathlib

from webcache import paths

_REPO = pathlib.Path(__file__).resolve().parent.parent


def test_settings_path_is_redirected_away_from_the_checkout():
    where = pathlib.Path(paths.settings_path()).resolve()
    assert _REPO not in where.parents, (
        "settings_path() points inside the repository at %s -- a test that "
        "closes a window will overwrite the developer's own settings" % where)


def test_the_redirect_is_automatic_not_remembered():
    """It must come from the autouse fixture, not from this file asking
    for it: the whole point is that a test which forgets cannot do harm."""
    where = pathlib.Path(paths.settings_path()).resolve()
    assert where.name == "settings.json"
    assert where.parent.exists(), (
        "the redirect must point somewhere writable, or settings.save() "
        "will swallow the error and the test will pass for the wrong reason")


def test_writing_settings_in_a_test_cannot_touch_the_real_file():
    from webcache.shell import settings
    settings.save(window_geometry="deadbeef", window_maximized=True)
    assert settings.get("window_geometry") == "deadbeef"
    real = _REPO / "settings.json"
    if real.exists():
        import json
        assert json.loads(real.read_text(encoding="utf-8")).get(
            "window_geometry") != "deadbeef"
