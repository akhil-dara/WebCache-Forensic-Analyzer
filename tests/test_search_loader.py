"""Shaping and wording for the Search view -- no Qt, no widgets, the
timeline_loader half of the timeline_loader/timeline_builder pair.

WHICH SEARCH THIS IS. Every function here shapes the output of
WebCacheParser.search_all_tables, which reads the DATABASE -- every table
dissect enumerates and every column of every row, plus the hex/ASCII/
UTF-16 readings of any binary value that did not decode to text.
ForensicEngine.search, which reads the parsed record set, is deliberately
not wired to this screen: one view that quietly switched between the two
would make "no hits" mean two different things, and the second is a far
weaker claim.

THE TWO ABSENCES IN THE URL COLUMN. A hit in a table that has no Url
column at all, and a hit in a table that has one holding nothing, are two
different facts. The absence vocabulary already spells both, and a blank
cell spells neither.
"""
import sys

import pytest

from webcache import provenance
from webcache.shell import record_kinds, search_loader


def _hit(table="Container_1", row=None, matched=("Url",), blob=False,
         row_index=7, **overrides):
    row = {"Url": "https://example.test/a", "EntryId": "11"} if row is None else row
    result = {
        "table": table,
        "table_type": "History",
        "container_name": "History",
        "column": matched[0],
        "matched_columns": list(matched),
        "match_value": "https://example.test/a",
        "match_in_blob": blob,
        "match_raw": "https://example.test/a",
        "match_raw_type": "text",
        "url": row.get("Url", ""),
        "row_index": row_index,
        "row": row,
    }
    result.update(overrides)
    return result


class _StubParser:
    """Only what hit_field_rows and scope_options actually read."""

    def __init__(self, columns=(), rows=(), table_names=()):
        self._columns = list(columns)
        self._rows = [list(r) for r in rows]
        self.table_names = list(table_names)

    def get_table_rows_raw(self, name, limit=500, offset=0):
        return list(self._columns), [list(r) for r in
                                     self._rows[offset:offset + limit]]

    def get_table_display_name(self, name):
        return "%s (display)" % name

    @staticmethod
    def raw_type_name(value):
        return "binary" if isinstance(value, bytes) else "text"

    @staticmethod
    def raw_rendering(value):
        return value.hex(" ").upper() if isinstance(value, bytes) else str(value)


class _FailingParser(_StubParser):
    """The engine's own can't-distinguish-failure-from-empty return."""

    def get_table_rows_raw(self, name, limit=500, offset=0):
        return [], []


# --- the result rows ------------------------------------------------------

def test_a_hit_row_carries_exactly_the_declared_keys():
    row = search_loader.search_rows([_hit()])[0]
    assert set(row) == {
        "Table", "Container", "TableType", "Row", "MatchedColumns",
        "FoundIn", "Context", "BlobOffset", "BlobEncoding", "MatchedValue",
        "RawType", "RawValue", "Url", "_kind", "_result"}


def test_a_hit_row_stays_inside_its_size_bucket():
    """Twelve keys sits in the 11-21 -> 464 B bucket; the ceiling before
    the next step is 21."""
    row = search_loader.search_rows([_hit()])[0]
    ceiling = 21
    assert len(row) <= ceiling
    baseline = {("k%03d" % i): i for i in range(ceiling)}
    assert sys.getsizeof(row) == sys.getsizeof(baseline)


def test_a_hit_row_names_its_kind_with_an_interned_constant():
    row = search_loader.search_rows([_hit()])[0]
    assert row["_kind"] is record_kinds.K_TABLE_ROW


def test_a_hit_row_points_at_the_engine_result_by_reference():
    """The pane's source. `is`, not `==` -- a copy would double every
    hit's cost and let the row and the result drift apart."""
    result = _hit()
    row = search_loader.search_rows([result])[0]
    assert row["_result"] is result


def test_every_matched_column_is_listed_never_the_first_one_only():
    """"Matched columns" is an open set and the whole point is that an
    examiner can see all of it -- never "four of nine"."""
    row = search_loader.search_rows(
        [_hit(matched=("Url", "Filename", "ResponseHeaders"))])[0]
    assert row["MatchedColumns"] == "Url, Filename, ResponseHeaders"


def test_found_in_is_a_closed_two_value_set():
    plain = search_loader.search_rows([_hit(blob=False)])[0]
    deep = search_loader.search_rows([_hit(blob=True)])[0]
    assert plain["FoundIn"] == "value"
    assert deep["FoundIn"] == "inside blob"


def test_the_row_ordinal_is_carried_through_as_a_number():
    row = search_loader.search_rows([_hit(row_index=413)])[0]
    assert row["Row"] == 413


# --- the two different Url absences --------------------------------------

def test_a_table_with_no_url_column_says_not_applicable():
    row = search_loader.search_rows(
        [_hit(row={"Name": "MSysObjects", "Id": "3"}, matched=("Name",))])[0]
    assert row["Url"] == provenance.ABSENCE_NOT_APPLICABLE


def test_a_url_column_that_held_nothing_says_empty():
    row = search_loader.search_rows(
        [_hit(row={"Url": "", "EntryId": "11"}, matched=("EntryId",))])[0]
    assert row["Url"] == provenance.ABSENCE_EMPTY


def test_the_two_url_absences_are_different_strings():
    """They are two different facts and the vocabulary already spells
    both; one blank cell spells neither."""
    assert provenance.ABSENCE_NOT_APPLICABLE != provenance.ABSENCE_EMPTY


# --- the detail pane's rows ----------------------------------------------

def test_hit_field_rows_pairs_every_decoded_value_with_its_stored_one():
    parser = _StubParser(columns=["Url", "Blob"],
                         rows=[["https://example.test/a", b"\x01\x02"]])
    result = _hit(row={"Url": "https://example.test/a", "Blob": "[BLOB 2B]"},
                  matched=("Url",), row_index=1)
    rows = search_loader.hit_field_rows(parser, result)

    assert [r["Column"] for r in rows] == ["Url", "Blob"]
    assert rows[0]["Decoded"] == "https://example.test/a"
    assert rows[1]["Decoded"] == "[BLOB 2B]"
    assert rows[1]["Stored"] == "01 02", (
        "every column shows both readings, not only the matched one")


def test_hit_field_rows_marks_matched_columns_yes_or_no_never_blank():
    parser = _StubParser(columns=["Url", "Blob"],
                         rows=[["https://example.test/a", b"\x01"]])
    result = _hit(row={"Url": "https://example.test/a", "Blob": "[BLOB 1B]"},
                  matched=("Blob",), row_index=1)
    rows = search_loader.hit_field_rows(parser, result)
    assert {r["Column"]: r["Matched"] for r in rows} == {"Url": "no",
                                                         "Blob": "yes"}


def test_hit_field_rows_re_reads_exactly_one_row_at_the_hits_own_offset():
    """row_index is 1-based within the table; the re-read is offset by
    one row and limited to one, the identical bounded call the Table
    Browser already pays on every page click."""
    seen = {}

    class _Recording(_StubParser):
        def get_table_rows_raw(self, name, limit=500, offset=0):
            seen.update(name=name, limit=limit, offset=offset)
            return _StubParser.get_table_rows_raw(self, name, limit, offset)

    parser = _Recording(columns=["Url"], rows=[["a"], ["b"], ["c"]])
    search_loader.hit_field_rows(
        parser, _hit(table="T", row={"Url": "c"}, row_index=3))
    assert seen == {"name": "T", "limit": 1, "offset": 2}


def test_a_failed_re_read_says_so_in_every_stored_cell_and_never_blank():
    """The engine returns ([], []) for a table it could not read AND for
    an empty one, so this cannot tell them apart. What it must never do
    is paint a blank, which reads as "the database stored nothing"."""
    result = _hit(row={"Url": "https://example.test/a", "EntryId": "11"})
    rows = search_loader.hit_field_rows(_FailingParser(), result)
    assert rows
    assert all(r["Stored"] == search_loader.RAW_REREAD_FAILED for r in rows)
    assert search_loader.RAW_REREAD_FAILED != ""


def test_the_re_read_failure_token_is_deliberately_not_an_absence_token():
    """None of the five is true here: the bytes exist, nothing was
    carved, the column applies. Borrowing one would put a wrong sentence
    behind the tooltip."""
    assert search_loader.RAW_REREAD_FAILED not in provenance.ABSENCE_TOKENS


def test_hit_field_rows_survives_a_parser_that_raises():
    class _Exploding(_StubParser):
        def get_table_rows_raw(self, name, limit=500, offset=0):
            raise OSError("page checksum")

    rows = search_loader.hit_field_rows(_Exploding(), _hit())
    assert all(r["Stored"] == search_loader.RAW_REREAD_FAILED for r in rows)


def test_a_pane_row_names_its_kind_too():
    """F1 on a pane cell reaches origin_line exactly as it does on the
    grid above it, and must get the same honest answer."""
    parser = _StubParser(columns=["Url"], rows=[["a"]])
    rows = search_loader.hit_field_rows(parser, _hit(row={"Url": "a"},
                                                     row_index=1))
    assert rows[0]["_kind"] is record_kinds.K_TABLE_ROW


# --- scope ----------------------------------------------------------------

def test_scope_options_lead_with_all_tables_then_every_table_sorted():
    parser = _StubParser(table_names=["Zeta", "Alpha", "Mid"])
    options = search_loader.scope_options(parser)
    assert options[0] == (search_loader.ALL_TABLES,
                          "All tables and recovered records")
    # one group heading (this parser names no table type), then the
    # tables sorted and indented under it.
    assert [key for key, _label in options[1:]] == [
        search_loader.GROUP_PREFIX + "Tables", "Alpha", "Mid", "Zeta"]
    assert options[2][1] == "    Alpha (display)"


def test_the_all_tables_sentinel_maps_to_the_engines_own_every_table():
    assert search_loader.table_filter_for(search_loader.ALL_TABLES) == ""
    assert search_loader.table_filter_for("Container_5") == "Container_5"
    assert search_loader.table_filter_for(None) == ""


def test_a_query_is_captured_whole():
    q = search_loader.SearchQuery("kw", table_filter="T", scope_label="T",
                                  db_path="C:/case/x.dat",
                                  known_hashes={"C:/case/x.dat": "a" * 64})
    assert (q.keyword, q.table_filter, q.scope_label) == ("kw", "T", "T")
    assert q.db_path == "C:/case/x.dat"
    assert q.known_hashes == {"C:/case/x.dat": "a" * 64}
    with pytest.raises(AttributeError):
        q.something_else = 1


# --- the wording ----------------------------------------------------------

def test_the_result_note_states_the_scope_and_the_work_done():
    q = search_loader.SearchQuery("needle")
    note = search_loader.result_note(
        q, {"tables": 83, "rows_scanned": 4506, "skipped": []})
    assert "'needle'" in note
    assert "83 table(s)" in note
    assert "4,506 row(s) scanned" in note


def test_no_skipped_tables_means_no_sentence_at_all():
    assert search_loader.skipped_sentence("") == ""
    assert search_loader.skipped_sentence([]) == ""
    assert search_loader.skipped_sentence(None) == ""


def test_a_skipped_table_is_named_and_what_it_means_is_stated():
    sentence = search_loader.skipped_sentence(
        [("MSysObjects", "page checksum"), ("LeakFiles", "bad page")])
    assert "2 table(s)" in sentence
    assert "MSysObjects" in sentence and "LeakFiles" in sentence
    assert "may still be present in them" in sentence


def test_the_result_note_carries_the_skipped_sentence_when_there_is_one():
    q = search_loader.SearchQuery("needle")
    note = search_loader.result_note(
        q, {"tables": 82, "rows_scanned": 10,
            "skipped": [("MSysObjects", "page checksum")]})
    assert "NOT searched" in note


def test_the_four_state_texts_all_exist_and_say_different_things():
    texts = [search_loader.IDLE_TEXT, search_loader.SEARCHING_TEXT,
             search_loader.CANCELLED_TEXT, search_loader.no_hits_text("kw")]
    assert len(set(texts)) == 4
    assert all(t.strip() for t in texts)


def test_the_cancelled_text_refuses_to_be_read_as_a_result():
    text = search_loader.CANCELLED_TEXT
    assert "No results are shown for an incomplete search" in text
    assert "incomplete search" in text


def test_the_no_hits_text_is_about_the_database_not_about_the_person():
    text = search_loader.no_hits_text("needle")
    assert "'needle'" in text
    assert "not what was typed or visited" in text


def test_the_scope_note_warns_that_a_blob_hit_is_invisible_in_the_browser():
    note = search_loader.SCOPE_NOTE
    assert "inside blob" in note
    assert "Table Browser" in note


# --- what the export sidecar needs ---------------------------------------

def test_export_scope_names_the_keyword_the_scope_and_the_work_done():
    q = search_loader.SearchQuery("needle", scope_label="All tables")
    scope = search_loader.export_scope(
        (q, {"tables": 83, "rows_scanned": 4506,
             "skipped": [("MSysObjects", "page checksum")]}))
    assert scope["search_keyword"] == "needle"
    assert scope["search_scope_label"] == "All tables"
    assert scope["tables_searched"] == 83
    assert scope["rows_scanned"] == 4506
    assert scope["tables_skipped"] == ["MSysObjects"]


def test_export_scope_of_nothing_adds_nothing():
    assert search_loader.export_scope(None) == {}
