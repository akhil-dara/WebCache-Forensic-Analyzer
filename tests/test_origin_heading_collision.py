"""The grid's vertical header always paints ORIGIN_HEADING
("Origin", record_model.py) in its own corner/section -- see
records_table.py's _OriginHeaderView. A view whose own COLUMNS declares a
DATA column headed the same word puts "Origin" on screen twice, with no
way for an examiner to tell the vertical header's Live/Carved marker from
the data column's own "Live record"/"Carved (deleted/unflushed)" text.

Source-level (AST), not instantiated views: several views need real
fixtures/engine state to construct, and the defect (and its fix) is a
literal string in a Column(...) call, not anything about run-time
behaviour."""
import ast
import pathlib

import pytest

from webcache.widgets.record_model import ORIGIN_HEADING

VIEWS_DIR = pathlib.Path(__file__).resolve().parent.parent / "webcache" / "views"


def _column_labels(path):
    """[(label, lineno), ...] for every Column(...) call in `path` that
    gives its label as a literal string -- positionally (every call site
    today) or via label=."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Column"):
            continue
        label = None
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            label = node.args[1].value
        for kw in node.keywords:
            if kw.arg == "label" and isinstance(kw.value, ast.Constant):
                label = kw.value.value
        if isinstance(label, str):
            found.append((label, node.lineno))
    return found


@pytest.mark.parametrize("path", sorted(VIEWS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_no_column_heading_duplicates_the_vertical_headers_heading(path):
    for label, lineno in _column_labels(path):
        assert label != ORIGIN_HEADING, (
            "%s:%d declares a column headed %r, which duplicates the "
            "grid's own vertical-header heading -- an examiner cannot "
            "tell the two \"Origin\" headings apart. Give the DATA "
            "column its own wording (e.g. \"Origin detail\"); the "
            "vertical header's heading is fixed and must stay \"%s\"."
            % (path.name, lineno, label, ORIGIN_HEADING))


# --- resolved headings, not only literal ones ---
#
# A label built from a variable -- Location's Raw records columns take
# theirs from ENTRY_FIELDS -- never reaches the AST check above. These
# views are instantiated and every heading they actually resolve to is
# checked, on every record set.

def _views():
    from webcache.views.containers import ContainersView
    from webcache.views.cookies import CookiesView
    from webcache.views.domains import DomainsView
    from webcache.views.file_access import FileAccessView
    from webcache.views.headers import HeadersView
    from webcache.views.history import HistoryView
    from webcache.views.indicators import IndicatorsView
    from webcache.views.iocs import FindingsView
    from webcache.views.location import LocationView
    from webcache.views.recovery import RecoveryView
    from webcache.views.search import SearchView
    from webcache.views.timeline import TimelineView
    return [ContainersView, CookiesView, DomainsView, FileAccessView,
            HeadersView, HistoryView, IndicatorsView, FindingsView,
            LocationView, RecoveryView, SearchView, TimelineView]


@pytest.mark.parametrize("cls", _views(), ids=lambda c: c.__name__)
def test_no_resolved_heading_duplicates_the_vertical_headers_heading(cls, qtbot):
    view = cls()
    qtbot.addWidget(view)
    sets = getattr(view, "_record_sets", None)
    columns = ([(rs.key, c) for rs in sets for c in rs.columns] if sets
               else [(None, c) for c in view.COLUMNS])
    for key, col in columns:
        assert col.label != ORIGIN_HEADING, (
            "%s/%s column %r is headed %r, the vertical header's own "
            "heading" % (cls.__name__, key, col.key, col.label))
