"""Count notes count what they describe.

Domains and Indicators said "N recovered" with N = every Deleted Records
row -- deleted-record stubs included -- although only the carved entries
are scanned; stubs carry no URL to scan. The Deleted Records note put
stubs under "did not (a different container, or none a string carve can
supply)", a reason that does not apply to them.
"""
import types

from tests.test_domains_wiring import (_FakeParser, _carved_entry, _entry,
                                       _fake_evidence_set, win)  # noqa: F401

_STUBS = [{"Table": "Container_4", "KeyColumns": ("EntryId",),
           "KeyValues": (i,), "Source": "WebCacheV01.dat"} for i in (7, 8)]


def _scan(win):
    parser = _FakeParser([_entry(Url="https://a.example/1")])
    win._on_evidence_loaded({"rows": [], "parser": parser},
                            _fake_evidence_set())
    engine = types.SimpleNamespace(
        structured_records=[_carved_entry(Url="https://gone.example/1")],
        all_artifacts=lambda: [], tombstones=list(_STUBS))
    win._on_recovery_loaded(engine)


def test_domains_counts_only_the_carved_entries_it_profiled(win):  # noqa: F811
    view = win._ensure_view_built("domains")
    _scan(win)
    text = view.line_text()
    assert "1 live, 1 recovered" in text, text


def test_indicators_counts_only_the_carved_entries_it_scanned(win):  # noqa: F811
    view = win._ensure_view_built("indicators")
    _scan(win)
    text = view.line_text()
    assert "1 recovered record(s) scanned" in text, text


def test_deleted_records_note_names_the_stubs_separately(win):  # noqa: F811
    view = win._ensure_view_built("recovery")
    _scan(win)
    text = view.count_label.text()
    assert "1 merged into History; 0 did not" in text, text
    assert "2 deleted-record stubs (key only)" in text, text
