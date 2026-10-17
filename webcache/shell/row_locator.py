"""Where a record's raw row lives.

Qt-free and engine-free: a grid row (or its `_record`) in, a table name and
a primary key out. The key is the table's own: EntryId for Container_<id>
tables and for every table whose records carry "Table" (cookies, HSTS,
certificates, AppCache); LeakId for LeakFiles. A key, not a position,
because positions shift with pagination and deleted-record stubs.
"""
import collections

from .record_kinds import K_TABLE_ROW, K_TOMBSTONE

LIVE = "live"
CARVED = "carved"
DELETED = "deleted"

#: A raw table row known by its position -- a search hit. Its table
#: and its 1-based "Row #" are what the search itself counted.
ORDINAL = "ordinal"
#: The pseudo-table recovered search hits name (search_loader.RECOVERED_TABLE),
#: spelled here so this Qt-free module need not import the loader.
_RECOVERED_TABLE = "Recovered records"

RowRef = collections.namedtuple("RowRef", "kind table key")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def source_row(row):
    """The RowRef for one grid row, or None for a row that is not one
    record (an aggregate, a period, a place)."""
    if not isinstance(row, dict):
        return None
    result = row.get("_result")
    hit_key = result.get("row_key") if isinstance(result, dict) else None
    if (row.get("_kind") == K_TABLE_ROW and row.get("Table")
            and row.get("Table") != _RECOVERED_TABLE
            and isinstance(hit_key, dict) and hit_key):
        # A hit that carries its key is located like any record: by key.
        return RowRef(LIVE, row["Table"], dict(hit_key))
    if (row.get("_kind") == K_TABLE_ROW and row.get("Table")
            and row.get("Table") != _RECOVERED_TABLE
            and _is_int(row.get("Row")) and row["Row"] >= 1):
        return RowRef(ORDINAL, row["Table"], {"Row #": row["Row"]})
    record = row.get("_record")
    record = record if isinstance(record, dict) else None
    if row.get("_kind") == K_TOMBSTONE:
        rec = record or {}
        columns = tuple(rec.get("KeyColumns") or ())
        values = tuple(rec.get("KeyValues") or ())
        return RowRef(DELETED, rec.get("Table") or rec.get("TableName") or "",
                      dict(zip(columns, values)))
    if (str(row.get("Origin") or "").startswith("Carved")
            or (record is not None and record.get("RecoverySource"))):
        return RowRef(CARVED, "", {})
    if record is None:
        return None
    entry_id = record.get("EntryId")
    table = record.get("Table")
    container_id = record.get("ContainerId")
    if not table and _is_int(container_id) and _is_int(entry_id):
        return RowRef(LIVE, "Container_%d" % container_id,
                      {"EntryId": entry_id})
    if table and _is_int(entry_id):
        return RowRef(LIVE, table, {"EntryId": entry_id})
    if _is_int(record.get("LeakId")):
        return RowRef(LIVE, "LeakFiles", {"LeakId": record["LeakId"]})
    return None


def describe_key(key):
    return ", ".join("%s %s" % (c, v) for c, v in key.items()) or "not decoded"


def action_label(ref):
    if ref.kind == CARVED:
        return "Show bytes at the carve offset"
    if ref.kind == DELETED:
        return "Show table %s (row deleted; key %s)" % (
            ref.table or "unknown", describe_key(ref.key))
    return "Show in database table"


def locate(parser, ref):
    """The row's 0-based ordinal in its table, or None."""
    finder = getattr(parser, "find_row_ordinal", None)
    if ref is None or ref.kind != LIVE or not callable(finder):
        return None
    return finder(ref.table, ref.key)


def locating_note(ref):
    return ("Locating the row with key %s in %s…"
            % (describe_key(ref.key), ref.table))


def landed_note(ref, ordinal):
    """Shown beside the grid when the row was found, naming the row."""
    if ref.kind == ORDINAL:
        return ("Row %s of this table is selected — the row the search "
                "hit was found in." % format(ordinal + 1, ","))
    return ("Row %s of this table (key %s) is selected."
            % (format(ordinal + 1, ","), describe_key(ref.key)))


def deleted_note(ref):
    return ("The row with key %s no longer exists in %s: it was deleted, "
            "and only its key survives in the table's b-tree. The table is "
            "shown as it stands now." % (describe_key(ref.key), ref.table))


def not_found_note(ref):
    return ("No row with key %s was found in %s. The record may come from "
            "a different copy of the database than the one open now."
            % (describe_key(ref.key), ref.table))
