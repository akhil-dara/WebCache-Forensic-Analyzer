"""What the build must and must not contain.

These run without building -- they read the spec file. The build itself is
verified by check_build.py in CI, because building takes minutes and this
suite runs on every commit.
"""
import ast
import importlib.util
import pathlib
import re

SPEC = pathlib.Path(__file__).resolve().parent.parent / "packaging" / "webcache.spec"
MAIN = pathlib.Path(__file__).resolve().parent.parent / "webcache" / "__main__.py"
BUILD_ICON = pathlib.Path(__file__).resolve().parent.parent / "packaging" / "build_icon.py"


def _load_build_icon():
    """Loaded by path, the same way test_check_build.py loads
    check_build.py -- packaging/ is not a package on sys.path, and this
    avoids polluting it for every other test in the session."""
    spec = importlib.util.spec_from_file_location("build_icon", BUILD_ICON)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_spec_exists():
    assert SPEC.is_file()


def test_main_entry_point_uses_no_relative_imports():
    """A relative import in `webcache/__main__.py` (for example
    `from .shell.consent import shutdown_workers`) resolves fine under `python -m webcache` and under pytest,
    because both set __package__ correctly through Python's normal
    package machinery. It does NOT resolve under PyInstaller:
    `Analysis(["../webcache/__main__.py"])` runs this file as an
    unpackaged top-level script, __package__ is never set, and the very
    first relative import raises `ImportError: attempted relative import
    with no known parent package` before a single window opens.

    529 tests were green, `PyInstaller` exited 0, `check_build.py`
    reported a plausible size, and the built exe still crashed on launch
    -- nothing above the actual binary could see it. This is the same
    AST-walking idiom test_structure.py already uses to ban an import
    shape without building anything, aimed at the one file where
    PyInstaller changes what "correct" means.
    """
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    relative = [node.lineno for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.level > 0]
    assert not relative, (
        "webcache/__main__.py has a relative import at line(s) %s -- "
        "PyInstaller runs this file as an unpackaged top-level script "
        "with no parent package, so this raises ImportError the instant "
        "the frozen exe launches even though `python -m webcache` and "
        "pytest both hide it completely; use an absolute "
        "'from webcache.x import y' instead" % relative)


def test_webengine_and_qml_are_excluded():
    text = SPEC.read_text(encoding="utf-8")
    for mod in ("QtWebEngine", "QtQml", "QtQuick", "Qt3D", "QtMultimedia",
                "QtPdf", "QtCharts"):
        assert mod in text, "%s must be excluded" % mod


def test_upx_is_disabled():
    """Not a size decision. UPX costs a decompression stall on every launch
    and is a standing antivirus heuristic -- an examiner whose AV quarantines
    the tool mid-examination has had a far worse day than one who downloaded
    a bigger file.

    There are three upx= sites in the spec (exe_onedir, COLLECT,
    exe_onefile). A single re.search only ever inspects the first match,
    so flipping either of the other two to True would pass unnoticed --
    every site is checked here instead."""
    text = SPEC.read_text(encoding="utf-8")
    values = re.findall(r"upx\s*=\s*(True|False)", text)
    assert len(values) >= 3, (
        "expected at least 3 upx= sites (exe_onedir, COLLECT, "
        "exe_onefile), found %d: %r" % (len(values), values))
    assert all(v == "False" for v in values), (
        "UPX must be off at every site; found %r" % values)


def test_the_software_gl_fallback_is_not_excluded():
    """opengl32sw.dll ships. Examiners work in VMs and over RDP, which is
    exactly where the software fallback is what starts the app at all."""
    code = "\n".join(line.split("#")[0] for line
                     in SPEC.read_text(encoding="utf-8").splitlines())
    assert "opengl32sw" not in code, (
        "opengl32sw.dll must not be excluded: it is the software GL "
        "fallback that starts the app on a machine with no usable driver")


def test_stdlib_bulk_is_excluded():
    text = SPEC.read_text(encoding="utf-8")
    for mod in ("tkinter", "unittest", "pydoc"):
        assert mod in text


# --- the icon: no setWindowIcon and no spec icon= existed before this ------

def test_the_exe_sets_an_icon_at_both_build_sites():
    """A missing icon is the single most visible framework tell there is --
    the taskbar and Alt-Tab show it before an examiner sees a pixel of the
    UI, and the release ships an unsigned exe that already triggers a
    SmartScreen warning, which a generic icon right next to makes worse,
    not neutral. Both EXE() sites must carry icon=, not just the onedir
    build: test_upx_is_disabled above uses the same "count every site"
    discipline for exactly the reason a single re.search would miss a
    second site left unset.
    """
    text = SPEC.read_text(encoding="utf-8")
    values = re.findall(r"icon\s*=\s*(\S+)", text)
    assert len(values) >= 2, (
        "expected an icon= at both EXE() sites (exe_onedir, exe_onefile), "
        "found %d: %r" % (len(values), values))


def test_build_icon_produces_a_multi_size_ico(tmp_path):
    """packaging/webcache.spec calls build_ico() at build time so the
    downloaded exe itself has an identity in Explorer, generated fresh
    rather than a binary asset that could go stale or missing (see
    build_icon.py's own docstring and .gitignore)."""
    build_icon = _load_build_icon()
    dest = build_icon.build_ico(tmp_path / "webcache.ico")
    assert dest.is_file()

    from PIL import Image
    img = Image.open(dest)
    assert img.format == "ICO"
    sizes = {w for w, h in img.info.get("sizes", set())}
    assert sizes == set(build_icon.SIZES)


def test_build_icon_actually_paints_the_mark_not_a_blank_square(tmp_path):
    """isNull()/format checks alone would still pass for a background-only
    render with the ellipse and line never drawn -- exactly the silent
    failure webcache/shell/icon.py's own QPainter implementation hit until
    its pen-carrying-the-previous-shape's-NoPen-style bug was found and
    fixed (see that module's _paint_one docstring). This is the independent
    Pillow implementation of the same mark, and nothing proves it does not
    have its own version of that bug just because it uses a different
    drawing API.
    """
    build_icon = _load_build_icon()
    img = build_icon._render(128).convert("RGB")
    pixels = img.load()
    colors = {pixels[x, y] for x in range(img.width) for y in range(img.height)}
    assert build_icon._MARK[:3] in colors, "the emerald mark must actually be painted"
    assert build_icon._BG[:3] in colors, "the near-black background must actually be painted"


def test_the_offline_report_assets_ship_with_the_build():
    """The page's template, stylesheet and scripts are read from disk at
    export time; a frozen build without them cannot write the report."""
    assert "html_package_assets" in SPEC.read_text(encoding="utf-8")
    pyproject = (SPEC.parent.parent / "pyproject.toml").read_text(
        encoding="utf-8")
    assert "html_package_assets/*" in pyproject
    assert "websocket-client" in pyproject


def test_the_asset_loader_reads_the_frozen_bundle_when_frozen(
        tmp_path, monkeypatch):
    """From source the assets sit beside html_package.py; in a frozen
    build they are wherever the spec's `datas` put them under
    sys._MEIPASS (webcache/shell/html_package_assets). The loader must
    read THAT copy when frozen, and the source copy otherwise."""
    import shutil
    import sys

    from webcache.shell import html_package

    source = pathlib.Path(html_package.__file__).resolve().parent \
        / "html_package_assets"
    assert "frozen-marker" not in html_package.page_style()
    bundled = tmp_path / "webcache" / "shell" / "html_package_assets"
    shutil.copytree(source, bundled)
    css = bundled / "page.css"
    css.write_text(css.read_text(encoding="utf-8") + "\n/* frozen-marker */\n",
                   encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert "frozen-marker" in html_package.page_style()
    assert html_package.page_script()      # every script found there too


VERSION_INFO = (pathlib.Path(__file__).resolve().parent.parent
                / "packaging" / "version_info.py")


def test_both_executables_carry_a_version_resource():
    """An executable with no product name, description or version reads
    to a scanner as anonymous; both artefacts declare who made them."""
    source = SPEC.read_text(encoding="utf-8")
    exes = re.findall(r"EXE\((.*?)\n\)", source, re.S)
    assert len(exes) == 2
    for body in exes:
        assert "version=VERSION_FILE" in body


def test_the_version_resource_states_the_application_version():
    from webcache import provenance
    spec = importlib.util.spec_from_file_location("version_info",
                                                  VERSION_INFO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = module.version_text(provenance.TOOL_VERSION)
    assert "filevers=(5, 0, 0, 0)" in text
    for field in ("CompanyName", "FileDescription", "ProductName",
                  "LegalCopyright", "OriginalFilename", "ProductVersion"):
        assert "StringStruct('%s'" % field in text
    assert "StringStruct('ProductVersion', '%s')" % provenance.TOOL_VERSION \
        in text
