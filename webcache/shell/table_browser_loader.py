"""Shaping for the Table Browser view: raw ESE tables, as WebCacheParser
exposes them, reshaped for a paginated master/detail view, so the view
never calls the engine directly.

grouped_tables() is the left panel's data: parser.get_tables_grouped()
classifies every table (ese_parser.get_table_type), and this function
imposes a stable sort order so the list is the same on every open.

table_page() is the right panel's data, one page at a time, requested on
every table selection and every Prev/Next click; a whole table is never
loaded for display. Cells come from get_table_rows_raw(): the raw Python
values, not get_table_rows()' display strings, which reformat
FILETIME-shaped integers. Each value goes through raw_type_name() and
raw_rendering(), so a cell states the type the database stored and the
value as stored: hex for binary, escaped for text.

Row counts come from the cache count_all_tables() fills at the end of
parse_all_entries(), so get_table_row_count() never scans a table.

A cache directory is looked up by table name: a Container_<id> table is
matched on its containers_meta entry's "TableName". A table that is no
container's storage (a modern *Ex table, MSysObjects, PartitionsEx)
reports None.
"""

from ..engine import local_clock
from ..engine.ese_parser import (FILETIME_COLUMNS, filetime_to_dt,
                                 filetime_to_str)

#: Column names whose integer IS a FILETIME -- the parser's own set plus
#: the modern tables' time columns (cookies, HSTS pins).
FILETIME_CELL_COLUMNS = frozenset(FILETIME_COLUMNS) | {
    "Expires", "LastModified", "LastTimeUsed"}


def _mshist_container_id(parser, table):
    if not str(table).startswith("Container_"):
        return None
    try:
        cid = int(str(table).split("_", 1)[1])
    except ValueError:
        return None
    name = str((getattr(parser, "container_map", None) or {}).get(cid, ""))
    return cid if name.lower().startswith("mshist") else None


def _parsed_mshist_entry(parser, cid, entry_id):
    """The parsed record behind one raw MSHist row, or None."""
    finder = getattr(parser, "mshist_entry", None)
    if finder is not None:
        return finder(cid, entry_id)
    for entry in getattr(parser, "all_entries", None) or ():
        if (isinstance(entry, dict) and entry.get("ContainerId") == cid
                and entry.get("EntryId") == entry_id
                and local_clock.is_mshist_record(entry)):
            return entry
    return None


def decode_filetime_cell(parser, table, column, value, entry_id=None):
    """The decoded reading of one FILETIME cell, "" for anything else.
    Named columns only: an integer is a time because its column says so,
    never because it falls in a plausible range, and a named column whose
    value is no usable time stays raw.

    An MSHist ModifiedTime is LOCAL; its UTC is derived with the offset
    on the parsed record at (ContainerId, `entry_id`), the one History and
    the exports use. When no record is found the recovered zone is used,
    and the sentence says so (worded as in local_clock)."""
    if (column not in FILETIME_CELL_COLUMNS or isinstance(value, bool)
            or not isinstance(value, int) or value <= 0
            or filetime_to_dt(value) is None):
        return ""
    cid = _mshist_container_id(parser, table)
    if column == "ModifiedTime" and cid is not None:
        return local_clock.describe_stored_cell(
            _parsed_mshist_entry(parser, cid, entry_id), value,
            getattr(parser, "derived_tz_offset_seconds", None))
    return filetime_to_str(value)


#: Rows per page, unless a caller overrides it. get_table_rows_raw bounds
#: the read; this bounds how much of it is on screen at once.
DEFAULT_PAGE_SIZE = 200

#: How many bytes of a binary cell the grid renders as hex: one line at
#: the column width, so a row beside a blob stays about one line tall.
#: The cell ends in GRID_BYTES_MARKER, and the bytes stay in the cell
#: ("raw") for the viewer, the row view and Copy.
GRID_HEX_BYTES = 24
GRID_BYTES_MARKER = "  \u25be +%s more bytes \u2014 View these bytes (right-click)"


def grid_hex(data):
    """A binary cell as the grid shows it: the first GRID_HEX_BYTES as
    hex, then a marker saying how many bytes follow and where they are."""
    data = bytes(data)
    text = " ".join("%02X" % b for b in data[:GRID_HEX_BYTES])
    if len(data) > GRID_HEX_BYTES:
        text += GRID_BYTES_MARKER % format(len(data) - GRID_HEX_BYTES, ",")
    return text


def grouped_tables(parser):
    """[(group_name, [table_info, ...]), ...], sorted by group name, each
    group's own tables sorted by name."""
    groups = parser.get_tables_grouped()
    return [(group, sorted(tables, key=lambda t: t["name"]))
            for group, tables in sorted(groups.items())]


def _directory_for_table(parser, table_name):
    """The cache directory of a Container_<id> table, or None: for any
    other table, and for a container whose Containers row is missing or
    has no directory. Never another container's path, never ""."""
    if not table_name.startswith("Container_"):
        return None
    for meta in parser.containers_meta:
        if meta.get("TableName") == table_name:
            return meta.get("Directory") or None
    return None


def _cell(parser, value, column="", table="", entry_id=None):
    """One cell: what the database stored, and how it renders.

    "raw" is the cell's bytes, held by reference and only for a binary
    value, so every binary column (including those no decoder reads) can
    reach the hex viewer (blob_source.blobs_for_cells), the row view and
    Copy. It is bounded by DEFAULT_PAGE_SIZE rows and released with the
    page.

    "text" is the whole value as stored for everything but binary; the
    grid and the row view read the same string, and the row cap decides
    how much a cell paints. Binary renders only what the grid can paint
    (grid_hex), ending in a marker that names the bytes not shown.
    """
    if isinstance(value, memoryview):
        value = value.tobytes()
    binary = isinstance(value, (bytes, bytearray))
    text = grid_hex(value) if binary else parser.raw_rendering(value)
    # "decoded" is the FILETIME reading of a named time column, ""
    # for every other cell; "text" stays the stored value.
    return {"type": parser.raw_type_name(value), "text": text,
            "raw": value if binary else None,
            "decoded": ("" if binary else
                        decode_filetime_cell(parser, table, column, value,
                                             entry_id))}


def table_page(parser, table_name, offset=0, limit=DEFAULT_PAGE_SIZE):
    """One page of `table_name`: its column names, that page's raw rows
    (each cell a {"type", "text"} dict; see _cell), the table's cached
    row count, its classified type and display name, and its cache
    directory when it has one. `offset`/`limit` are passed unchanged to
    get_table_rows_raw(), which bounds how much is read at once.
    """
    columns, raw_rows = parser.get_table_rows_raw(
        table_name, limit=limit, offset=offset)
    rendered_rows = [render_row(parser, table_name, columns, row)
                     for row in raw_rows]
    return {
        "table": table_name,
        "display_name": parser.get_table_display_name(table_name),
        "type": parser.get_table_type(table_name),
        "columns": columns,
        "rows": rendered_rows,
        "row_count": parser.get_table_row_count(table_name),
        "offset": offset,
        "limit": limit,
        "directory": _directory_for_table(parser, table_name),
    }


# --- the whole table, for the row filter and sort --------------------------

def render_row(parser, table_name, columns, row):
    """One raw row as the grid's cells (see _cell)."""
    key_at = columns.index("EntryId") if "EntryId" in columns else None
    entry_id = (row[key_at] if key_at is not None and key_at < len(row)
                else None)
    return [_cell(parser, v, columns[i] if i < len(columns) else "",
                  table_name, entry_id)
            for i, v in enumerate(row)]


def all_rows(parser, table_name):
    """(columns, every raw row) of one table, as the engine stores them.
    Raw values only: cells are rendered a page at a time (page_of_rows),
    so holding a whole table costs its values, not a dict and a hex
    string per cell."""
    count = parser.get_table_row_count(table_name)
    return parser.get_table_rows_raw(table_name, limit=max(count, 1),
                                     offset=0)


def row_texts(parser, table_name, columns, row):
    """What the row filter matches in each cell of one raw row: the cell
    as the grid shows it, and the decoded FILETIME reading its tooltip
    states, so a date finds the rows of that date. Lower-cased."""
    return ["%s%s" % (cell["text"], cell["decoded"] or "")
            if cell["decoded"] else cell["text"]
            for cell in render_row(parser, table_name, columns, row)]


def sort_key(value):
    """A raw value's place in a heading sort: numbers as numbers, text
    case-insensitively, bytes by their bytes, and an empty cell last in
    either direction (the caller keeps blanks last)."""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bool):
        return (0, int(value), b"")
    if isinstance(value, (int, float)):
        return (0, value, b"")
    if isinstance(value, (bytes, bytearray)):
        return (2, 0, bytes(value))
    return (1, 0, str(value).lower().encode("utf-8", "surrogatepass"))


def page_of_rows(parser, table_name, columns, raw_rows, ordinals, offset,
                 limit):
    """table_page's dict for one page of a filtered or sorted table:
    `ordinals` are the matching rows' positions in the TABLE, so every row
    keeps its own table row number."""
    picked = ordinals[offset:offset + limit]
    return {
        "table": table_name,
        "display_name": parser.get_table_display_name(table_name),
        "type": parser.get_table_type(table_name),
        "columns": columns,
        "rows": [render_row(parser, table_name, columns, raw_rows[i])
                 for i in picked],
        "ordinals": list(picked),
        "matches": len(ordinals),
        "row_count": len(raw_rows),
        "offset": offset,
        "limit": limit,
        "directory": _directory_for_table(parser, table_name),
    }
