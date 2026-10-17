"""Copy, never Open -- as a rule, not as a convention.

Every path this application displays belongs to the EXAMINED machine, not
to the examiner's. Opening one launches a program on the analysis
workstation against a location that either does not exist there or, worse,
does and is a different file entirely -- and in the case it does exist, the
open writes an access time onto the analyst's own system while looking to
the examiner exactly like it read the evidence.

The rule has been stated in three docstrings (records_table.py's context
menu, column_spec.KINDS on why "path" is not "url", detail_fields.py's
machine group) and enforced by nothing. A single QDesktopServices.openUrl
in a future view would satisfy every existing test.

This is deliberately a WHOLE-TREE AST check rather than a check on the
detail dialog alone: the rule is not about one surface, and a rule scoped
to the surface that happens to exist today is a rule that stops applying
the moment someone adds a surface.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent / "webcache"

#: Modules whose whole job is launching something. The point of naming the
#: set is that adding one has to be a deliberate, reviewed edit to this
#: file rather than a quiet import somewhere.
#:
#: export_folder opens the examiner's OWN export folder after a write,
#: refuses any evidence directory, and never opens a file. It is the only
#: module allowed to.
_ALLOWED = frozenset({"export_folder"})

#: Every mechanism that hands a path to the operating system to act on.
#: QDesktopServices.openUrl is Qt's; os.startfile is Windows'; webbrowser
#: and subprocess are Python's two general ones.
_BANNED_IMPORTS = {"webbrowser", "subprocess"}
_BANNED_NAMES = {"QDesktopServices", "startfile"}


def _modules():
    return sorted(p for p in ROOT.rglob("*.py")
                  if "__pycache__" not in p.parts and p.stem not in _ALLOWED)


def test_every_allowed_module_exists_and_is_the_only_one():
    """A stale name in _ALLOWED would silently exempt whatever file next
    takes that name; the exemption is exactly one real module."""
    found = [p for p in ROOT.rglob("*.py")
             if "__pycache__" not in p.parts and p.stem in _ALLOWED]
    assert sorted(p.stem for p in found) == sorted(_ALLOWED)
    assert len(found) == 1


def test_there_are_modules_to_check():
    """An empty walk would make every assertion below vacuously true --
    the exact silent-pass failure test_structure.py's own guard exists
    for."""
    assert len(_modules()) > 20


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_module_imports_a_way_to_open_a_path(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in _BANNED_IMPORTS, (
                    "%s imports %s; this application copies paths, it never "
                    "opens them" % (path.name, alias.name))
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in _BANNED_IMPORTS, (
                "%s imports from %s; copy, never open" % (path.name, node.module))
            for alias in node.names:
                assert alias.name not in _BANNED_NAMES, (
                    "%s imports %s; copy, never open" % (path.name, alias.name))


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_module_calls_a_way_to_open_a_path(path):
    """Checked on the AST, not by searching the text: a docstring that
    talks ABOUT QDesktopServices (this file's own reasoning, quoted in
    detail_fields.py) is not a call to it, and a substring check that
    cannot tell those apart is a check nobody can keep green honestly.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name in ("openUrl", "startfile", "Popen", "run", "system"):
            owner = getattr(getattr(func, "value", None), "id", "")
            assert owner not in ("QDesktopServices", "os", "subprocess"), (
                "%s calls %s.%s; copy, never open" % (path.name, owner, name))


def test_the_check_would_actually_catch_the_banned_call():
    """The teeth. A guard nobody has ever seen fail is a guard nobody
    knows works -- test_structure.py learned this the hard way when its
    own cross-import check ran zero iterations for a whole phase."""
    tree = ast.parse("import os\nos.startfile(row['CachedFilePath'])\n")
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            owner = getattr(getattr(func, "value", None), "id", "")
            if name == "startfile" and owner == "os":
                hits.append(name)
    assert hits == ["startfile"]
