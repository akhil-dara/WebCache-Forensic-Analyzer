"""QSortFilterProxyModel is banned.

It was measured at 680x slower than sorting the list (20,624 ms against
30.3 ms at 100k rows). It is not a style preference.

The ban is enforced by parsing each file with `ast` and checking for the
banned name as a real import or identifier (Import, ImportFrom, Name,
Attribute) rather than by grepping raw file text. A raw substring search
over the whole file also flags the name inside comments, docstrings, and
string literals -- and this module's own docstring, and record_filter.py's,
both name QSortFilterProxyModel to explain *why* it is banned. Prose that
explains a ban is not a use of the thing it bans, and a check that cannot
tell the difference forces every explanation of the ban to be deleted along
with any real offender, which is backwards.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "webcache"


def _app_sources():
    """Every module outside the analysis engine, which has no GUI code."""
    return [p for p in ROOT.rglob("*.py") if "engine" not in p.parts]


def _uses_name_in_source(source, name):
    """True if `name` appears as a real Python identifier -- imported,
    referenced bare, or accessed as an attribute -- anywhere in `source`.

    Comments, docstrings, and other string literals are never seen: by the
    time `ast.parse` hands back a tree, that text has already been thrown
    away. Only four node kinds can possibly spell the name: importing it
    (Import/ImportFrom), naming it bare (Name), or reaching it off an
    attribute chain such as QtCore.QSortFilterProxyModel (Attribute).
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == name or alias.name.endswith("." + name)
                   for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == name for alias in node.names):
                return True
        elif isinstance(node, ast.Name):
            if node.id == name:
                return True
        elif isinstance(node, ast.Attribute):
            if node.attr == name:
                return True
    return False


def _uses_name(path, name):
    return _uses_name_in_source(path.read_text(encoding="utf-8"), name)


def test_qsortfilterproxymodel_is_never_imported():
    offenders = [str(p.relative_to(ROOT)) for p in _app_sources()
                 if _uses_name(p, "QSortFilterProxyModel")]
    assert offenders == [], (
        "QSortFilterProxyModel is banned: measured 680x slower than "
        "rows.sort() at 100k rows. Found in: %s" % offenders)


def test_qsortfilterproxymodel_ban_has_teeth():
    """Proof the AST check actually catches a real use and does not just
    happen to find nothing. A ban that has been loosened until it stops
    firing looks identical, from the outside, to a ban that was never
    enforced -- this is the test that would have caught that.

    All parsed from string literals with ast.parse; nothing is written to
    the tree.
    """
    real_import = "from PySide6.QtCore import QSortFilterProxyModel\n"
    real_usage = "model = QSortFilterProxyModel()\n"
    qualified_usage = "x = QtCore.QSortFilterProxyModel()\n"
    only_mentioned = (
        '"""The obvious idiom -- QSortFilterProxyModel -- was measured '
        'and rejected."""\n'
        "# QSortFilterProxyModel is banned; see the module docstring.\n"
        "s = 'QSortFilterProxyModel'\n"
    )

    assert _uses_name_in_source(real_import, "QSortFilterProxyModel") is True
    assert _uses_name_in_source(real_usage, "QSortFilterProxyModel") is True
    assert _uses_name_in_source(qualified_usage, "QSortFilterProxyModel") is True
    assert _uses_name_in_source(only_mentioned, "QSortFilterProxyModel") is False
