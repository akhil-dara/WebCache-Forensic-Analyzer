# -*- mode: python ; coding: utf-8 -*-
"""One spec, two artefacts: a onedir portable folder and a onefile exe.

Onedir is the recommended one. Onefile unpacks to %TEMP% on every launch,
which is slower and writes to an examination machine's disk.

Size is secondary to startup reliability and launch speed: only what the
application never loads is excluded.
"""
import pathlib
import sys

# SPECPATH is set by PyInstaller to the directory containing this .spec, the
# base every relative path below resolves against, so the generated .ico is
# written to "packaging/" wherever PyInstaller is run from.
sys.path.insert(0, SPECPATH)
from build_icon import build_ico

# Regenerated on every build and never committed (see build_icon.py and
# .gitignore), so the shipped icon always matches the drawn mark.
ICON_PATH = str(build_ico(pathlib.Path(SPECPATH) / "webcache.ico"))

# The version resource (product, description, version, copyright) both
# executables carry, generated from the application's own version.
import re
import version_info
_VERSION = re.search(
    r'TOOL_VERSION = "([^"]+)"',
    (pathlib.Path(SPECPATH).parent / "webcache" / "provenance.py")
    .read_text(encoding="utf-8")).group(1)
pathlib.Path(workpath).mkdir(parents=True, exist_ok=True)
VERSION_FILE = str(version_info.write(
    pathlib.Path(workpath) / "version_info.txt", _VERSION))

block_cipher = None

EXCLUDES = [
    # Qt modules a widgets application never loads. Also a second line of
    # defence: the project depends on PySide6-Essentials, so Addons should
    # not be present at all -- but a transitive dependency could drag it in,
    # and a 195 MB browser engine inside a forensic tool is an attack
    # surface that buys the examiner nothing.
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtCharts",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    # stdlib the application does not use.
    "tkinter", "unittest", "pydoc", "doctest", "test",
    # numpy and lxml: neither is a direct dependency of this application
    # (grep webcache/ for "numpy" or "DataFrame" and it comes back empty).
    # Both are reachable only because PyInstaller's static analysis walks
    # into openpyxl's own optional backends: openpyxl/compat/numbers.py
    # does `try: import numpy` purely to recognise numpy scalar types as
    # valid cell values, and openpyxl/xml/__init__.py does the same for
    # lxml as a faster XML backend, falling back to stdlib
    # xml.etree.ElementTree (via the already-required et_xmlfile) when
    # either is missing. Confirmed by reading both call sites, and by
    # running export_xlsx() end-to-end with both modules blocked at
    # import time. Excluding them here removes ~35-45 MB of code this
    # application never executes.
    "numpy", "lxml",
]

a = Analysis(
    ["../webcache/__main__.py"],
    pathex=[".."],
    binaries=[],
    # The offline HTML report reads its template, stylesheet and scripts
    # from disk at export time (webcache/shell/html_package.py).
    datas=[("../webcache/shell/html_package_assets",
            "webcache/shell/html_package_assets")],
    hiddenimports=["dissect.esedb"],
    excludes=EXCLUDES,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_onedir = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="WebCacheAnalyzer",
    console=False,
    icon=ICON_PATH,
    version=VERSION_FILE,
    # UPX is off deliberately. It would save perhaps 15 MB and costs a
    # decompression stall on every launch plus a standing antivirus
    # heuristic.
    upx=False,
)
coll = COLLECT(
    exe_onedir, a.binaries, a.datas,
    strip=False, upx=False,
    name="WebCacheAnalyzer",
)

exe_onefile = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="WebCacheAnalyzer-portable",
    console=False,
    icon=ICON_PATH,
    version=VERSION_FILE,
    upx=False,
    onefile=True,
)
