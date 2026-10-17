"""The dialog states a carved record's provenance as labelled facts, first.

Provenance must not sit in two places an examiner has to find on their
own: one grey run-on sentence under the identity line
(origin_label), and the labelled fields buried inside "How it was
recovered" -- a group near the end of ~69. Neither says "here is where
this came from" at a glance. This file pins the strip that now sits under
the identity line, and the group reorder that brings G_HOW forward for a
recovered row.
"""
import types

from PySide6.QtWidgets import QWidget

from webcache.provenance import CARVED_ORIGIN
from webcache.shell import detail_fields
from webcache.shell.record_detail import RecordDetailDialog
from webcache.shell.record_kinds import K_CARVED_STRUCT, K_TOMBSTONE
from webcache.shell.recovery_loader import deleted_records_rows

_CARVED = {"CleanUrl": "https://example.invalid/a", "Origin": CARVED_ORIGIN,
           "Source": "WebCacheV01.dat", "Offset": 0x3B0523, "Page": 117,
           "Method": "Structured record reconstruction", "Confidence": "medium",
           "_kind": K_CARVED_STRUCT, "_record": {}}

#: A deleted-record stub, built through the real loader rather than a
#: hand-built dict -- test_tombstone_rows.py's own `_engine`/`_STUB` shape,
#: so this file exercises the actual row deleted_records_rows() produces
#: (a stub whose node gave no position: Offset/Page None; the evidence file
#: as Source; Confidence naming the b-tree key) rather than an
#: approximation of it.
_STUB = {"Table": "Container_4", "KeyColumns": ("UrlHash", "EntryId"),
         "KeyValues": (111, 7), "Source": "WebCacheV01.dat"}


def _stub_row():
    engine = types.SimpleNamespace(structured_records=[],
                                   all_artifacts=lambda: [],
                                   tombstones=[_STUB])
    rows = deleted_records_rows(engine)
    assert len(rows) == 1
    assert rows[0]["_kind"] == K_TOMBSTONE
    return rows[0]


def test_provenance_facts_are_labelled():
    assert detail_fields.provenance_facts(_CARVED) == [
        ("Carved from", "WebCacheV01.dat"), ("Offset", "0x003B0523"),
        ("Page", "117"), ("Method", "Structured record reconstruction"),
        ("Confidence", "medium")]


def test_a_live_record_has_no_provenance_facts():
    assert detail_fields.provenance_facts({"Origin": "Live record"}) == []


def test_the_dialog_shows_them_as_a_strip(qtbot):
    # Built by hand, exactly as test_record_detail_room.py's own `build`
    # fixture does: RecordDetailDialog sets WA_DeleteOnClose, so
    # qtbot.addWidget's teardown would call close() on an already-deleted
    # C++ object. A real QWidget parent, closed by hand afterwards.
    parent = QWidget()
    d = RecordDetailDialog(dict(_CARVED), parent)
    try:
        assert d.provenance_strip is not None
        text = " ".join(l.text() for l in
                        d.provenance_strip.findChildren(type(d.origin_label)))
        for label, value in detail_fields.provenance_facts(_CARVED):
            assert label in text and value in text
    finally:
        d.close()
        parent.close()


def test_how_it_was_recovered_comes_before_what_the_record_says():
    names = [g.name for g in detail_fields.fields_for(_CARVED)]
    assert detail_fields.G_HOW in names
    ahead = names[:names.index(detail_fields.G_HOW)]
    assert set(ahead) <= {detail_fields.G_QUALITY}


# --- a deleted-record stub (K_TOMBSTONE), real row shape ----------------

def test_a_stub_states_source_and_method_and_confidence_with_no_offset_or_page():
    """Offset and Page are None on a stub -- not carved, only a b-tree key
    survived -- and a None fact must be skipped, never printed as the word
    "None". Confidence is free text naming the exact key, not a level."""
    row = _stub_row()
    assert row["Offset"] is None and row["Page"] is None

    facts = detail_fields.provenance_facts(row)
    labelled = dict(facts)
    assert "Offset" not in labelled
    assert "Page" not in labelled
    assert "None" not in [v for _, v in facts]
    assert labelled["Found in"] == "WebCacheV01.dat", (
        "the evidence file, never a table name under a file heading")
    assert labelled["Method"] == row["Method"]
    assert labelled["Method"] == "Deleted-record stub (b-tree key only)"
    assert labelled["Confidence"] == row["Confidence"]
    # the key is its own fact now, and Confidence is the one word.
    assert labelled["Confidence"] == "exact"
    assert labelled["Key"] == "UrlHash 111, EntryId 7"


def test_the_dialog_shows_the_stub_strip_too():
    row = _stub_row()
    parent = QWidget()
    d = RecordDetailDialog(dict(row), parent)
    try:
        assert d.provenance_strip is not None
        text = " ".join(l.text() for l in
                        d.provenance_strip.findChildren(type(d.origin_label)))
        for label, value in detail_fields.provenance_facts(row):
            assert label in text and value in text
        assert "Offset" not in text
        assert "Page" not in text
    finally:
        d.close()
        parent.close()


def test_a_placed_stub_states_its_offset_and_page():
    """The node's tag gives a stub's page and offset
    exactly; once known they are provenance like any carved record's."""
    placed = dict(_STUB, Page=5, Offset=0x3B0523)
    engine = types.SimpleNamespace(structured_records=[],
                                   all_artifacts=lambda: [],
                                   tombstones=[placed])
    row = deleted_records_rows(engine)[0]
    labelled = dict(detail_fields.provenance_facts(row))
    assert labelled["Offset"] == "0x003B0523"
    assert labelled["Page"] == "5"


def test_a_none_confidence_is_skipped_not_printed():
    row = dict(_CARVED, Confidence=None)
    facts = detail_fields.provenance_facts(row)
    assert "Confidence" not in dict(facts)
    assert "None" not in [v for _, v in facts]


def test_a_short_strip_value_does_not_fold_onto_three_lines(qtbot):
    """"Method  Structured record reconstruction" wrapped to three lines
    with the strip's right half empty (seen on a real machine): a wrapping
    label asks for far less width than its text, and a trailing stretch
    took the rest. In a wide dialog every cell is one line."""
    parent = QWidget()
    d = RecordDetailDialog(dict(_CARVED), parent)
    try:
        d.resize(1500, 700)
        d.show()
        qtbot.waitExposed(d)
        cells = d.provenance_strip.findChildren(type(d.origin_label))
        # Wrapped at its real width vs. one line at unlimited width.
        tall = [c.text() for c in cells
                if c.heightForWidth(c.width()) > c.heightForWidth(100000)]
        assert not tall, tall
    finally:
        parent.close()


def test_the_origin_sentence_separates_its_confidence():
    from webcache import provenance
    text = provenance.describe_origin(dict(_CARVED))
    assert "reconstruction, confidence medium" in text, text
