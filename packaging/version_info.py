"""The Windows version resource both executables carry: product name,
description, version and copyright, shown under the file's Properties
and read by scanners that treat an executable with none as anonymous.

`write(path, version)` writes the file PyInstaller's `version=` takes.
"""
import pathlib

PRODUCT = "WebCache Forensic Analyzer"
AUTHOR = "Akhil Dara"
EXE_NAME = "WebCacheAnalyzer.exe"


def _numbers(version):
    """The four integers Windows' file version holds: the release number's
    numeric parts, so "5.1.0.dev0" gives (5, 1, 0, 0)."""
    parts = [int(p) for p in version.split(".") if p.isdigit()][:4]
    return tuple(parts + [0] * (4 - len(parts)))


def version_text(version):
    nums = _numbers(version)
    strings = [
        ("CompanyName", AUTHOR),
        ("FileDescription", PRODUCT),
        ("FileVersion", version),
        ("InternalName", "WebCacheAnalyzer"),
        ("LegalCopyright", "Copyright (c) 2026 %s. AGPL-3.0-only." % AUTHOR),
        ("OriginalFilename", EXE_NAME),
        ("ProductName", PRODUCT),
        ("ProductVersion", version),
    ]
    rows = ",\n            ".join(
        "StringStruct(%r, %r)" % pair for pair in strings)
    return """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=%(nums)r,
    prodvers=%(nums)r,
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
            %(rows)s
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""" % {"nums": nums, "rows": rows}


def write(path, version):
    path = pathlib.Path(path)
    path.write_text(version_text(version), encoding="utf-8")
    return path
