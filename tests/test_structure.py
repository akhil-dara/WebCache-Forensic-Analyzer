"""The two structural rules, so the layout cannot rot into a tangle."""
import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent / "webcache"


#: Modules under webcache/views/ that are SHARED INFRASTRUCTURE rather than
#: a view: a record-set view subclasses RecordsView, so importing it is the
#: intended dependency, not the peer coupling this file forbids.
#:
#: This exists because the alternative actually happened. When File Access
#: became the second record-set view, both it and History imported the base
#: as `from webcache.views.records_view import ...` -- absolute, against this
#: package's relative style -- for the sole reason that the check below
#: matched `from .records_view` and `import records_view` but not the
#: dotted-absolute spelling of the same import. The rule was satisfied in
#: letter and evaded in substance, and every future view would have copied
#: the workaround until the check protected nothing. The fix is to name which
#: import is legitimate rather than to let views phrase an illegal one in a
#: way the regex misses -- so the base is named here, and _imports_view below
#: now catches the absolute form too.
#: record_chips holds the chips two record-set views share (Copies,
#: SameVisit) -- infrastructure in the same sense, so sharing them never
#: means one view importing another.
_BASE_MODULES = {"records_view", "record_chips"}


def _imports_view(text, other):
    """True when `text` imports view module `other`, however it is spelled.

    Covers the relative form (`from .other import`), the bare form
    (`import other`) AND the dotted-absolute form
    (`from webcache.views.other import`) -- the last of which is the one
    that slipped through and made this check decorative for two views.
    """
    return bool(re.search(
        r"\bfrom \.%s\b|\bimport %s\b|\bfrom webcache\.views\.%s\b"
        % (other, other, other), text))


def _too_few_to_check(modules):
    """True when there are not enough real view modules for the
    cross-import check below to compare anything against.

    Split out from the test itself so the THRESHOLD is independently
    testable (see test_the_vacuous_guard_fires_for_exactly_one_module
    below) rather than only provable by physically adding a second file
    under webcache/views/.

    The bar is TWO, not one. The original guard only fired on
    `not modules` -- zero view modules. The moment History landed
    as the first real view, `modules` held exactly one entry: `not
    modules` was False, so the guard no longer fired, and the test fell
    through into the loop below. But `others` -- every OTHER module's
    stem -- was still empty for that one module, so the inner assertion
    loop ran zero iterations: a silent PASS that checked nothing, reading
    exactly like a protected invariant.
    One real view module is exactly as unable to exercise a CROSS-import
    check as zero are.
    """
    return len(modules) < 2


def test_no_view_imports_another_view():
    """Real view modules communicate through the shell, never directly
    with each other.

    Guarded so it cannot stay silently vacuous. See _too_few_to_check's
    docstring for why the guard fires below TWO real view modules, not
    just zero: with a single view module this reports XFAIL with a reason
    naming the condition, rather than a silent pass. With two or more,
    the xfail branch is skipped and this is a live, exercised assertion.
    """
    modules = [p for p in (ROOT / "views").glob("*.py") if p.stem != "__init__"]
    if _too_few_to_check([p for p in modules if p.stem not in _BASE_MODULES]):
        pytest.xfail(
            "only %d real view module(s) exist -- the cross-import check "
            "below needs at least two to compare, so it has nothing to "
            "check yet; see _too_few_to_check's docstring" % len(modules))
    peers = [p for p in modules if p.stem not in _BASE_MODULES]
    for p in peers:
        text = p.read_text(encoding="utf-8")
        others = [q.stem for q in peers if q.stem != p.stem]
        for other in others:
            assert not _imports_view(text, other), (
                "%s imports view %s; views communicate through the shell"
                % (p.name, other))


def test_the_check_catches_a_dotted_absolute_import_not_just_a_relative_one():
    r"""The teeth. Pins the exact evasion that made this file decorative.

    Both record-set views once imported the shared base as
    `from webcache.views.records_view import ...` purely because the old
    regex -- `\bfrom \.other\b|\bimport other\b` -- did not match that
    spelling. A rule a view can satisfy by rephrasing the same import is
    not a rule, so all three spellings must be caught. `records_view`
    itself is exempt by name (_BASE_MODULES), not by spelling.
    """
    for text in ("from .history import HistoryView",
                 "import history",
                 "from webcache.views.history import HistoryView"):
        assert _imports_view(text, "history"), text
    assert not _imports_view("from ..widgets.column_spec import Column", "history")


def test_the_shared_base_is_not_a_backdoor_between_views():
    """_BASE_MODULES exempts the base from the peer check, so the base is
    the one module that could reintroduce view-to-view coupling without
    tripping anything. It must therefore import no view itself."""
    base = ROOT / "views" / "records_view.py"
    if not base.exists():
        pytest.skip("no shared base module in this tree")
    text = base.read_text(encoding="utf-8")
    views = [p.stem for p in (ROOT / "views").glob("*.py")
             if p.stem != "__init__" and p.stem not in _BASE_MODULES]
    assert views, "no real view modules to check the base against"
    for other in views:
        assert not _imports_view(text, other), (
            "records_view.py imports view %s; the shared base must not "
            "couple views to each other" % other)


def test_every_view_reaches_the_base_the_same_relative_way():
    """Style, but load-bearing style: the absolute spelling existed ONLY to
    dodge the old check. Now that the base is exempt by name, no view has a
    reason to phrase it differently, and a reappearing absolute import is
    the signal that someone is working around this file again."""
    views = [p for p in (ROOT / "views").glob("*.py")
             if p.stem != "__init__" and p.stem not in _BASE_MODULES]
    assert views, "no real view modules"
    for p in views:
        text = p.read_text(encoding="utf-8")
        for base in _BASE_MODULES:
            assert not re.search(r"\bfrom webcache\.views\.%s\b" % base, text), (
                "%s imports the shared base absolutely; use `from .%s import "
                "...` -- the base is exempt by name, so the workaround the "
                "absolute form was invented for no longer applies"
                % (p.name, base))


def test_the_vacuous_guard_fires_for_exactly_one_module_not_just_zero():
    """Pins the actual regression this fix closes.

    A guard of `if not modules` only fires at
    zero. Reverting to that logic reintroduces the exact bug this test
    would have caught the whole time: History landing as the
    lone view module made `not modules` False while `others` stayed
    empty, so the real assertion loop silently ran zero iterations. This
    checks the threshold directly, independent of pytest's own xfail
    machinery and without needing a second on-disk view module to exist
    for the check to mean something.
    """
    zero = []
    one = [pathlib.Path("history.py")]
    two = [pathlib.Path("history.py"), pathlib.Path("search.py")]
    assert _too_few_to_check(zero) is True
    assert _too_few_to_check(one) is True, (
        "one view module cannot exercise a CROSS-import check any more "
        "than zero can -- this is the exact case that passed silently "
        "before this fix")
    assert _too_few_to_check(two) is False


def test_no_widget_imports_the_engine():
    """Widgets receive data already shaped by their caller; reaching into
    the engine directly would let a widget skip that boundary.

    Checked by parsing each file's AST and looking only at real import
    statements, not by searching the raw text for the substring "engine".
    A raw substring search also matches the word inside a comment or
    docstring that merely talks about the engine -- exactly the false
    positive test_no_proxy.py's own docstring warns about for
    QSortFilterProxyModel -- and webcache/widgets/filter_popup.py already
    has one such comment ("...eliminating from the engine...", about Task
    5's work, not an import) that would otherwise fail this test forever
    regardless of whether any widget actually imports the engine.

    ast.ImportFrom is checked on BOTH `node.module` and `node.names`.
    `node.module` alone catches `from ..engine import parse` (module ==
    "engine") but misses `from .. import engine` -- there `module` is
    None (nothing follows the dots) and "engine" is the imported *name*
    itself, in `node.names`. That second shape is exactly how a widget
    would pull in the engine package and then use it as a namespace
    (`engine.parse(...)`), so checking only `node.module` would have
    traded the original substring false-positive for a false negative on
    the single most natural way to write the banned import.
    """
    for p in (ROOT / "widgets").glob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "engine" not in alias.name.split("."), (
                        "%s imports the engine; views pass data in" % p.name)
            elif isinstance(node, ast.ImportFrom):
                module_parts = (node.module or "").split(".")
                assert "engine" not in module_parts, (
                    "%s imports the engine; views pass data in" % p.name)
                for alias in node.names:
                    assert "engine" not in alias.name.split("."), (
                        "%s imports the engine; views pass data in" % p.name)
