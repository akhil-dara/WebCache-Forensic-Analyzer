"""HSTS "Other records?" and "Subdomains" are
flags, one display form -- Yes / No, never NO beside yes -- and their
funnels offer Is Yes / Is No. The engine's own strings (and the exports
built from them) are unchanged."""
from PySide6.QtCore import Qt

from webcache.engine.analysis_extra import hsts_visit_evidence
from webcache.shell.evidence_loader import hsts_rows_from_parser
from webcache.views.cookies import CookiesView
from tests.test_evidence_loader_cookies import _StubHstsParser, _hsts_entry


def _rows():
    stub = _StubHstsParser(
        [_hsts_entry(Domain="example.com"),
         _hsts_entry(Domain="nowhere.example")],
        all_entries=[{"CleanUrl": "https://example.com/a"}])
    return hsts_rows_from_parser(stub), stub


def test_other_records_and_subdomains_are_booleans_on_the_row():
    rows, _ = _rows()
    assert sorted(r["Corroborated"] for r in rows) == [False, True]
    assert all(isinstance(r["IncludeSubdomains"], bool) for r in rows)


def test_the_grid_reads_yes_and_no_in_one_form(qtbot):
    rows, _ = _rows()
    view = CookiesView()
    qtbot.addWidget(view)
    view.set_records_for("hsts", rows)
    view._switch_segment("hsts")
    model = view.table.model()
    col = [c.key for c in model.columns].index("Corroborated")
    shown = {model.data(model.index(i, col), Qt.DisplayRole)
             for i in range(model.rowCount())}
    assert shown == {"Yes", "No"}


def test_the_engine_strings_are_unchanged():
    _, stub = _rows()
    engine = hsts_visit_evidence(stub.hsts_entries, stub.all_entries)
    assert sorted(r["Corroborated"] for r in engine) == ["NO", "yes"]
