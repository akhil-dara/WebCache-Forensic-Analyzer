"""check_build.py's own behaviour, exercised directly against synthetic
trees -- fast, no PyInstaller needed. This is the regression test for
the one thing it must get right: failing
when Qt6WebEngineCore.dll is present, and passing when it isn't.
"""
import importlib.util
import pathlib

CHECK_BUILD_PATH = (pathlib.Path(__file__).resolve().parent.parent
                     / "packaging" / "check_build.py")


def _load_check_build():
    spec = importlib.util.spec_from_file_location("check_build", CHECK_BUILD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_tree(root, with_webengine):
    nested = root / "_internal" / "PySide6"
    nested.mkdir(parents=True)
    (nested / "Qt6Core.dll").write_bytes(b"not really a dll, just bytes")
    (nested / "Qt6Widgets.dll").write_bytes(b"also just bytes")
    if with_webengine:
        (nested / "Qt6WebEngineCore.dll").write_bytes(b"the one that must never ship")


def test_check_build_fails_when_webengine_is_present(tmp_path):
    root = tmp_path / "dist" / "WebCacheAnalyzer"
    _make_tree(root, with_webengine=True)
    check_build = _load_check_build()
    assert check_build.main(["check_build.py", str(root)]) == 1


def test_check_build_passes_on_a_clean_tree(tmp_path):
    root = tmp_path / "dist" / "WebCacheAnalyzer"
    _make_tree(root, with_webengine=False)
    check_build = _load_check_build()
    assert check_build.main(["check_build.py", str(root)]) == 0


def test_check_build_reports_no_build_as_exit_2(tmp_path):
    missing = tmp_path / "dist" / "DoesNotExist"
    check_build = _load_check_build()
    assert check_build.main(["check_build.py", str(missing)]) == 2
