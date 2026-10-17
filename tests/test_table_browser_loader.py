"""table_browser_loader: shaping for the Table Browser view's master/
detail pair, tested against a stub parser -- the same discipline every
other *_loader module in this package already uses (see
test_evidence_loader_containers.py's own docstring).

The stub SUBCLASSES WebCacheParser without calling its __init__ (no real
ESE database exists on this machine for CI to open) purely so it inherits
raw_type_name()/raw_rendering() unchanged -- those two are the actual
"render as stored" contract this loader must not reimplement or
paraphrase; testing against the real methods rather than a hand-rolled
stand-in is the point.
"""
from webcache.engine.ese_parser import WebCacheParser
from webcache.shell.table_browser_loader import (DEFAULT_PAGE_SIZE, GRID_HEX_BYTES,
                                                  grouped_tables, table_page)


class _StubParser(WebCacheParser):
    """Deliberately skips WebCacheParser.__init__ -- see the module
    docstring. Only the attributes/methods table_browser_loader.py
    actually calls are set."""

    def __init__(self, grouped=None, tables=None, containers_meta=None,
                row_counts=None, display_names=None, table_types=None):
        self._grouped = grouped or {}
        # table_name -> list of raw-value rows (each row a list of cells)
        self._tables = tables or {}
        self.containers_meta = containers_meta or []
        self._row_counts = row_counts or {}
        self._display_names = display_names or {}
        self._table_types = table_types or {}

    def get_tables_grouped(self):
        return self._grouped

    def get_table_rows_raw(self, table_name, limit=500, offset=0):
        rows = self._tables.get(table_name, {}).get("rows", [])
        return self._tables.get(table_name, {}).get("columns", []), \
            rows[offset:offset + limit]

    def get_table_row_count(self, table_name):
        return self._row_counts.get(table_name, len(
            self._tables.get(table_name, {}).get("rows", [])))

    def get_table_display_name(self, table_name):
        return self._display_names.get(table_name, table_name)

    def get_table_type(self, table_name):
        return self._table_types.get(table_name, "System")


# --- grouped_tables: the left panel's data ------------------------------

def test_grouped_tables_sorts_groups_and_tables_within_each_group():
    parser = _StubParser(grouped={
        "History": [{"name": "Container_9", "display_name": "Container_9",
                    "type": "History", "count": 5},
                   {"name": "Container_2", "display_name": "Container_2",
                    "type": "History", "count": 3}],
        "Cookie Entries": [{"name": "CookieEntryEx_1",
                            "display_name": "CookieEntryEx_1",
                            "type": "Cookie Entries", "count": 1}],
    })
    result = grouped_tables(parser)
    assert [group for group, _tables in result] == \
        ["Cookie Entries", "History"]
    history_names = [t["name"] for t in
                     next(tables for g, tables in result if g == "History")]
    assert history_names == ["Container_2", "Container_9"]


def test_grouped_tables_on_an_empty_database_yields_no_groups():
    assert grouped_tables(_StubParser(grouped={})) == []


# --- table_page: the right panel's data, one page at a time --------------

def test_table_page_reports_columns_and_the_requested_slice():
    parser = _StubParser(tables={
        "Foo": {"columns": ["A", "B"],
               "rows": [[1, "x"], [2, "y"], [3, "z"]]},
    }, row_counts={"Foo": 3})
    page = table_page(parser, "Foo", offset=0, limit=2)
    assert page["columns"] == ["A", "B"]
    assert len(page["rows"]) == 2
    assert page["row_count"] == 3
    assert page["offset"] == 0
    assert page["limit"] == 2


def test_table_page_defaults_to_the_module_page_size():
    parser = _StubParser(tables={"Foo": {"columns": ["A"], "rows": [[1]]}})
    page = table_page(parser, "Foo")
    assert page["limit"] == DEFAULT_PAGE_SIZE


def test_table_page_never_asks_for_more_rows_than_the_engine_limit_allows():
    """The engine's own get_table_rows_raw(name, limit, offset) already
    bounds what gets read into memory -- this loader must pass limit/
    offset straight through, not silently request an unbounded read."""
    seen = {}

    class _Recording(_StubParser):
        def get_table_rows_raw(self, table_name, limit=500, offset=0):
            seen["limit"] = limit
            seen["offset"] = offset
            return ["A"], []

    table_page(_Recording(), "Foo", offset=400, limit=50)
    assert seen == {"limit": 50, "offset": 400}


# --- rendering: raw type + raw rendering, never the "prettified" form ----

def test_cells_carry_both_the_raw_type_name_and_the_raw_rendering():
    parser = _StubParser(tables={
        "Foo": {"columns": ["Blob", "Text", "Num"],
               "rows": [[b"\x00\x01", "hello", 42]]},
    })
    page = table_page(parser, "Foo", offset=0, limit=10)
    cells = page["rows"][0]
    assert cells[0]["type"] == "binary"
    assert cells[0]["text"] == "00 01"
    assert cells[1]["type"] == "text"
    assert cells[1]["text"] == "hello"
    assert cells[2]["type"] == "integer"
    assert cells[2]["text"] == "42"


def test_a_large_filetime_shaped_integer_is_rendered_as_the_plain_number_not_reinterpreted():
    """get_table_rows() (NOT used here) auto-detects large ints as
    probable FILETIME values and silently reformats them -- exactly the
    "prettified" interpretation this browser must NOT apply. raw_rendering() never does that; this pins it stays that
    way through this loader."""
    huge = 133535904000000000  # a real FILETIME-shaped value
    parser = _StubParser(tables={
        "Foo": {"columns": ["X"], "rows": [[huge]]}})
    page = table_page(parser, "Foo", offset=0, limit=10)
    assert page["rows"][0][0]["text"] == str(huge)
    assert page["rows"][0][0]["type"] == "integer"


# --- table/type/display-name/row-count passthrough -----------------------

def test_page_carries_the_tables_own_display_name_type_and_row_count():
    parser = _StubParser(
        tables={"Container_9": {"columns": ["X"], "rows": []}},
        row_counts={"Container_9": 0},
        display_names={"Container_9": "Container_9 [History] MSHist"},
        table_types={"Container_9": "History"})
    page = table_page(parser, "Container_9")
    assert page["table"] == "Container_9"
    assert page["display_name"] == "Container_9 [History] MSHist"
    assert page["type"] == "History"
    assert page["row_count"] == 0


# --- cache directory: looked up by table name, container tables only -----

def test_a_container_table_carries_its_own_cache_directory():
    parser = _StubParser(
        tables={"Container_3": {"columns": ["X"], "rows": []}},
        containers_meta=[{"ContainerId": 3, "TableName": "Container_3",
                          "Directory": r"C:\case\Content.IE5"}])
    page = table_page(parser, "Container_3")
    assert page["directory"] == r"C:\case\Content.IE5"


def test_a_non_container_table_carries_no_directory():
    parser = _StubParser(tables={"MSysObjects": {"columns": ["X"], "rows": []}})
    page = table_page(parser, "MSysObjects")
    assert page["directory"] is None


def test_a_container_table_with_no_matching_containers_meta_entry_carries_no_directory():
    """A Container_<id> table whose OWN Containers-table row is missing
    for some reason -- e.g. a stub/edge case -- must degrade to "unknown",
    not crash or attribute an unrelated container's directory to it."""
    parser = _StubParser(tables={"Container_99": {"columns": ["X"], "rows": []}},
                         containers_meta=[{"ContainerId": 3,
                                          "TableName": "Container_3",
                                          "Directory": r"C:\case\Other"}])
    page = table_page(parser, "Container_99")
    assert page["directory"] is None


def test_an_empty_directory_string_is_reported_as_none_not_a_blank_value():
    parser = _StubParser(
        tables={"Container_5": {"columns": ["X"], "rows": []}},
        containers_meta=[{"ContainerId": 5, "TableName": "Container_5",
                          "Directory": ""}])
    page = table_page(parser, "Container_5")
    assert page["directory"] is None


# --- the whole value, always ---------------------------------------------
#
# The grid, the row view, the search hits and the
# search export all read raw_rendering, and it used to give a PREVIEW (48
# bytes of hex, or 400 escaped characters). There is no preview any more:
# how much of a value a cell PAINTS is the row cap's job, never the data's.


def test_raw_rendering_is_always_the_whole_text():
    long_text = "z" * 900
    assert WebCacheParser.raw_rendering(long_text) == long_text


def test_the_whole_text_is_still_escaped_as_stored_not_prettified():
    """Not truncating is not the same as interpreting. A NUL and a
    right-to-left override stay visible in the whole rendering -- for a
    domain name that is the difference between a homograph and an
    ordinary host."""
    whole = WebCacheParser.raw_rendering("ab\x00c" + "d" * 500)
    assert whole.startswith(r"ab\x00c")
    assert "\x00" not in whole


def test_raw_rendering_gives_every_byte_of_a_binary_value():
    whole = WebCacheParser.raw_rendering(bytes(range(256)))
    assert whole.startswith("00 01 02")
    assert whole.endswith("FF")
    assert "bytes total" not in whole
    assert len(whole.split(" ")) == 256


def test_a_long_text_cell_is_the_whole_value():
    long_text = "z" * 900
    parser = _StubParser(tables={
        "Foo": {"columns": ["T"], "rows": [[long_text]]}})
    cell = table_page(parser, "Foo")["rows"][0][0]
    assert cell["text"] == long_text
    assert "full" not in cell


def test_a_binary_cell_carries_its_bytes_and_a_grid_rendering_that_says_so():
    """Full hex for every binary cell of a 200-row page is megabytes of
    text nobody asked for. The grid renders what it can paint and ends in
    a marker naming the bytes not shown; the bytes are kept ("raw") for
    the hex viewer, the row view and a Copy."""
    data = bytes(range(200))
    parser = _StubParser(tables={"Foo": {"columns": ["B"], "rows": [[data]]}})
    cell = table_page(parser, "Foo")["rows"][0][0]
    assert cell["raw"] == data
    assert cell["text"].startswith("00 01 02")
    assert "+%d more bytes" % (200 - GRID_HEX_BYTES) in cell["text"]
    assert "View these bytes" in cell["text"]
