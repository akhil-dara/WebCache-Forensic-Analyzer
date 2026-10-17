"""A breadcrumb is in words -- never an internal
kind key -- and an on-screen position is named as on screen, never as the
table's own row. A search hit names its hit number and the table row it
landed on."""
from webcache.shell import search_loader
from tests.test_navigation_back import ROW, win  # noqa: F401  (fixture)


def test_a_history_crumb_names_the_record_and_its_on_screen_position(win):
    history = win._ensure_view_built("history")
    history.table.selectRow(7)
    win.show_in_database_table(ROW)
    crumb = win.nav_bar.crumb_label.text()
    assert crumb == ("from: History record 8 (on screen): "
                     + ROW["CleanUrl"])
    assert "history:" not in crumb


def test_a_search_hit_crumb_names_the_hit_and_the_table_row(win):
    result = {"table": "Container_5", "container_name": "History",
              "table_type": "History", "row_index": 2,
              "row_key": {"EntryId": 44}, "matched_columns": ["Url"],
              "match_in_blob": False, "match_value": "https://x.test/",
              "match_raw_type": "text", "match_raw": "x",
              "row": {"Url": "https://x.test/"}}
    rows = search_loader.search_rows([result], keyword="x.test")
    search = win._ensure_view_built("search")
    search.set_records(rows)
    win.go_to("search")
    win.show_in_database_table(search.table.model().row_at(0))
    crumb = win.nav_bar.crumb_label.text()
    assert crumb.startswith("from: Search hit 1 → Container_5 row 2")
    assert "table_row" not in crumb
