import pathlib
import sys

from webcache import paths


def test_unfrozen_app_dir_is_the_package_parent():
    assert paths.app_dir() == pathlib.Path(paths.__file__).resolve().parent.parent


def test_frozen_app_dir_follows_the_executable_not_the_temp_dir(monkeypatch, tmp_path):
    """--onefile unpacks into a temp dir that is deleted on exit.

    Resolving app-local storage there loses the examiner's case file every
    time they close the app, with no error shown.
    """
    exe = tmp_path / "portable" / "WebCacheAnalyzer.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI12345"), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))

    assert paths.app_dir() == exe.parent
    assert "_MEI" not in str(paths.cases_dir())


def test_cases_dir_is_created_and_sits_under_app_dir():
    d = paths.cases_dir()
    assert d.is_dir()
    assert d.parent == paths.app_dir()
