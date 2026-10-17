"""What counts as a record in an ESE table.

dissect.esedb yields a Record for every b-tree leaf node, and parses the
record header (fidFixedLastInRec, fidVarLastInRec, ibEndOfFixedData) only
when the payload is long enough to hold it; a shorter node resolves every
column to None. Such a node is a deleted-record stub, not a record.

The test is the payload length alone. The Deleted tag flag is not a
reliable marker (leaf nodes carrying it can hold full records), and an
all-NULL record is still a record.

Imports nothing from this package, so any engine module can use it.
"""
from dissect.esedb.c_esedb import c_esedb

#: 4: fidFixedLastInRec (1) + fidVarLastInRec (1) + ibEndOfFixedData (2).
RECORD_HEADER_LEN = len(c_esedb.RECHDR)


def is_record_node(rec) -> bool:
    """True when the node's payload is long enough to hold a record."""
    return len(rec._node.data) >= RECORD_HEADER_LEN


def live_records(table):
    """table.records(), without the leaf nodes too short to be records."""
    for rec in table.records():
        if is_record_node(rec):
            yield rec


_SEGMENT = 9          # 0x7F marker + 8 bytes


def decode_node_key(key) -> tuple:
    """A node key of one or more normalised signed 64-bit segments, or ()
    when the key is not entirely in that form."""
    key = bytes(key or b"")
    values = []
    i = 0
    while i + _SEGMENT <= len(key) and key[i] == 0x7F:
        raw = int.from_bytes(key[i + 1:i + _SEGMENT], "big") ^ (1 << 63)
        values.append(raw - (1 << 64) if raw >= (1 << 63) else raw)
        i += _SEGMENT
    return tuple(values) if values and i == len(key) else ()


def _key_columns(table_name, count):
    """What the key segments name, per table shape, established against
    the stored columns of real records."""
    if count == 2:
        return ("UrlHash", "EntryId")
    if count == 1:
        return ("LeakId",) if table_name == "LeakFiles" else ("EntryId",)
    return ()


def _node_position(rec, page_size):
    """(page number, absolute file offset) of a leaf node's data, or
    (None, None) when the node carries no tag to derive them from.

    Computed as struct_carver computes a live record's offset, so a
    stub's Offset and a carved record's Offset are the same kind of
    number: the page's position ((N + 1) * page_size), past the page
    header (40 bytes on a small page, 80 above 8 KiB), to the tag, past
    the key prefix."""
    try:
        node = rec._node
        tag = node.tag
        page = tag.page
        num = page.num
    except Exception:                                  # noqa: BLE001
        return None, None
    if not page_size:
        return num, None
    header = 40 if getattr(page, "is_small_page", False) else 80
    try:
        offset = ((num + 1) * page_size + header + tag.offset
                  + (len(tag.data) - len(node.data)))
    except Exception:                                  # noqa: BLE001
        offset = None
    return num, offset


def tombstones(tables, failures=None):
    """Every leaf node too short to be a record, with its key, page and
    absolute file offset.

    A table that cannot be walked (an unreadable page) stops only that
    table. When `failures` is a list, each such table is appended to it
    as (name, error)."""
    for table in tables:
        name = getattr(table, "name", "?")
        try:
            page_size = getattr(getattr(table, "db", None), "page_size", None)
        except Exception:                              # noqa: BLE001
            page_size = None
        found = []
        try:
            for rec in table.records():
                if is_record_node(rec):
                    continue
                values = decode_node_key(rec._node.key)
                page, offset = _node_position(rec, page_size)
                found.append({"Table": name,
                              "KeyColumns": _key_columns(name, len(values)),
                              "KeyValues": values,
                              "Page": page,
                              "Offset": offset})
        except Exception as exc:                       # noqa: BLE001
            # Stubs found before the bad page are kept; the failure entry
            # records that the walk was incomplete.
            if failures is not None:
                failures.append((name, exc))
        yield from found
