"""A search hit lands on its row, and a FILETIME reads decoded beside
the stored integer in Table Browser."""
import datetime
import types

import pytest

from webcache.shell import row_locator, table_browser_loader
from webcache.shell.record_kinds import K_TABLE_ROW
from webcache.shell.table_row_detail import fields_for_row

UTC = datetime.timezone.utc
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=UTC)
FT = int((datetime.datetime(2024, 3, 1, 10, 0, tzinfo=UTC) - _EPOCH)
         .total_seconds()) * 10_000_000

HIT = {"Table": "Container_2", "Row": 3, "Container": "Content",
       "TableType": "Content", "MatchedColumns": "Url", "FoundIn": "value",
       "_kind": K_TABLE_ROW, "_result": {"table": "Container_2", "row_index": 3}}


def test_a_hit_is_a_reference_to_its_exact_row():
    ref = row_locator.source_row(HIT)
    assert ref is not None
    assert ref.kind == row_locator.ORDINAL
    assert ref.table == "Container_2" and ref.key == {"Row #": 3}
    assert row_locator.action_label(ref) == "Show in database table"


def test_the_grid_menu_names_what_open_does_on_a_hit(qtbot):
    from webcache.views.search import SearchView
    view = SearchView()
    qtbot.addWidget(view)
    view.set_records([dict(HIT, Context="x", BlobOffset=None, MatchedValue="x",
                           RawType="text", RawValue="x", Url="(empty)")])
    menu = view.table._build_context_menu(view.table.model().index(0, 0))
    labels = [a.text() for a in menu.actions()]
    assert labels[0].startswith("Open this row in Table Browser")
    assert not any(t.startswith("Open this record") for t in labels)


class _Parser:
    derived_tz_offset_seconds = 19800
    container_map = {1: "History", 2: "MSHist012024030120240302"}

    def raw_rendering(self, value):
        return str(value)

    def raw_type_name(self, value):
        return "integer"


def test_a_filetime_cell_carries_its_decoded_reading():
    cell = table_browser_loader._cell(_Parser(), FT, column="ModifiedTime",
                                      table="Container_1")
    assert cell["text"] == str(FT)
    assert cell["decoded"] == "2024-03-01 10:00:00 UTC"


def test_a_non_time_integer_is_not_decoded():
    cell = table_browser_loader._cell(_Parser(), FT, column="UrlHash",
                                      table="Container_1")
    assert cell["decoded"] == ""


def test_the_row_dialog_shows_the_decoded_reading_beside_the_stored_one():
    cells = [{"type": "integer", "text": str(FT), "raw": None,
              "decoded": "2024-03-01 10:00:00 UTC"}]
    field = fields_for_row(["ModifiedTime"], cells)[0]
    assert field.shown == str(FT)
    assert field.decoded == "2024-03-01 10:00:00 UTC"


# --- land by the row's KEY, and say LOCAL for MSHist ---------------

KEYED_HIT = dict(HIT, _result={"table": "Container_2", "row_index": 3,
                               "row_key": {"EntryId": 4401}})


def test_a_hit_that_carries_its_key_is_located_by_key():
    ref = row_locator.source_row(KEYED_HIT)
    assert ref.kind == row_locator.LIVE
    assert ref.table == "Container_2" and ref.key == {"EntryId": 4401}


def _search_parser(rows):
    from tests.test_ese_parser_search import _Table, _parser
    return _parser({"Container_2": _Table(["EntryId", "Url"], rows)})


def test_the_search_pass_hands_each_hit_its_primary_key():
    parser = _search_parser([[10, "https://a.example.test/"],
                             [11, "https://needle.example.test/"]])
    hit = parser.search_all_tables("needle")[0]
    assert hit["row_key"] == {"EntryId": 11}


def test_a_table_without_a_known_key_hands_none_not_a_guess():
    from tests.test_ese_parser_search import _Table, _parser
    parser = _parser({"Odd": _Table(["Url"], [["https://needle.test/"]])})
    assert parser.search_all_tables("needle")[0].get("row_key") is None


def test_an_mshist_companion_says_local_then_derived_utc():
    local = FT + 19800 * 10_000_000
    cell = table_browser_loader._cell(_Parser(), local, column="ModifiedTime",
                                      table="Container_2")
    assert cell["decoded"].startswith("local: 2024-03-01 15:30:00")
    assert "UTC (derived, UTC+05:30): 2024-03-01 10:00:00" in cell["decoded"]


def test_an_mshist_companion_without_a_zone_gives_no_utc():
    class NoZone(_Parser):
        derived_tz_offset_seconds = None
    cell = table_browser_loader._cell(NoZone(), FT, column="ModifiedTime",
                                      table="Container_2")
    assert cell["decoded"].startswith("local: 2024-03-01 10:00:00")
    assert "UTC (derived" not in cell["decoded"]
    assert "no time zone" in cell["decoded"]


def test_a_synthetic_mshist_table_page_reads_local_in_its_cells():
    class TableParser(_Parser):
        containers_meta = []

        def get_table_rows_raw(self, table, limit=1, offset=0):
            return ["EntryId", "ModifiedTime", "AccessedTime"], [
                [1, FT + 19800 * 10_000_000, FT]]

        def get_table_display_name(self, t):
            return t

        def get_table_type(self, t):
            return "Content"

        def get_table_row_count(self, t):
            return 1

    page = table_browser_loader.table_page(TableParser(), "Container_2")
    modified, accessed = page["rows"][0][1], page["rows"][0][2]
    assert modified["decoded"].startswith("local: ")
    assert accessed["decoded"] == "2024-03-01 10:00:00 UTC"
