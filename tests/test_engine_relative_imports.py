"""Every engine module must reach its siblings by a package-relative import.

The engine was copied in from a flat directory where `import struct_carver`
resolved because every module sat on sys.path together. Under a package it
does not, and the rewrite that fixed that used a regex anchored at column
zero -- so it corrected the imports at module level and silently skipped the
four sitting INSIDE function bodies.

That is why this is an AST walk and not a grep for `^import`. A bare import
nested in a function does not fail at import time; it fails only when that
function is finally called, which here meant the entire structured carve
crashed and every carved record came back with ContainerType None, so nothing
ever merged into the History view. The module imported cleanly the whole time.

`ast.walk` reaches every node at every depth, so a future import added inside
a method, a `try:` block or a conditional is caught the same as one at the
top of the file.
"""
import ast
import pathlib

ENGINE = pathlib.Path(__file__).resolve().parent.parent / "webcache" / "engine"

#: The sibling modules. A bare import of any of these resolves only if the
#: engine directory itself is on sys.path, which it is not when the package
#: is installed or frozen.
SIBLINGS = {p.stem for p in ENGINE.glob("*.py") if p.stem != "__init__"}


def _bare_sibling_imports(path):
    """(lineno, statement) for every non-relative import of a sibling."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # level > 0 is already relative -- `from .ese_parser import x`.
            if node.level == 0 and node.module:
                if node.module.split(".")[0] in SIBLINGS:
                    out.append((node.lineno, "from %s import ..." % node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in SIBLINGS:
                    out.append((node.lineno, "import %s" % alias.name))
    return out


def test_the_sibling_set_is_not_empty():
    """A typo in the glob would make every other test here vacuous."""
    assert len(SIBLINGS) >= 10, SIBLINGS
    assert "ese_parser" in SIBLINGS
    assert "struct_carver" in SIBLINGS


def test_no_engine_module_imports_a_sibling_by_bare_name():
    offenders = []
    for path in sorted(ENGINE.glob("*.py")):
        for lineno, stmt in _bare_sibling_imports(path):
            offenders.append("%s:%d  %s" % (path.name, lineno, stmt))
    assert offenders == [], (
        "these resolve only if webcache/engine/ is itself on sys.path, which "
        "it is not once installed or frozen:\n  " + "\n  ".join(offenders))


def test_the_check_reaches_imports_nested_inside_functions():
    """The teeth. The real defect was four imports inside function bodies.

    A column-anchored grep saw none of them, so this asserts the walk finds
    an import at depth rather than trusting that it would.
    """
    sibling = sorted(SIBLINGS)[0]
    nested = ast.parse(
        "def outer():\n"
        "    def inner():\n"
        "        try:\n"
        "            import %s\n"
        "        except ImportError:\n"
        "            pass\n" % sibling
    )
    found = [
        alias.name
        for node in ast.walk(nested)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert found == [sibling], found
