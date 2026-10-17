"""
Structured reconstruction of deleted container records.

The string carver in recovery_engine finds URL text in unallocated space.
This module recovers the whole record: EntryId, ContainerId, every
timestamp, AccessCount, Flags, the URL, and the trailing ResponseHeaders
field, which for History records is the property store holding the visit
count and the local-clock last-visit time.

How it works
------------
Kim/Jang/Lee (Digital Investigation 18 (2016) S118–S124) describe a fixed
4-byte constant associated with container records. That constant is the
ESE record header (RECHDR) of every Container_N record, identical for all
of them because they share one schema:

    11        fidFixedLastInRec = 17   -> 17 fixed columns, EntryId..ExemptionDelta
    7f        fidVarLastInRec   = 127  -> zero variable-length columns
    77 00     ibEndOfFixedData  = 119  -> 4 header + 112 fixed + 3 null-bitmap

Because the schema is fixed, the tagged-field array always begins at
record offset 119, and column binding is arithmetic.

Confidence in the method
------------------------
`validate()` replays this pipeline over every live record and compares the
result with dissect's parse of the same record. On the reference sample:
982 of 993 live records detected (the 11 not detected are 1-byte stubs
whose only content is a null, checked by length), 982/982 fixed columns
byte-exact, and for History 465/465 exact on every field including the
212-byte property-store blob. Run it on a database before relying on
carved output.

Carved records remain CARVED evidence: graded, and reported with the byte
offset they came from, so any finding can be checked in a hex editor.
"""

from __future__ import annotations

import collections
import datetime
import struct

from . import ese_records

from dissect.esedb.esedb import EseDB
from dissect.esedb.record import RecordData
from dissect.esedb.c_esedb import PAGE_FLAG

# The shared RECHDR of every Container_N record. Only this byte order occurs;
# the reversed form appears nowhere in the reference sample.
RECORD_MARK = b"\x11\x7f\x77\x00"

TAGGED_DATA_START = 119     # == ibEndOfFixedData, since there are no var columns
PAGE_HEADER_LEN = 80        # PGHDR(40) + PGHDR2(40) on pages larger than 8 KiB
DEFAULT_PAGE_SIZE = 32768   # used when the header cannot be read

TAG_SEPARATED = 0x04        # value lives in the long-value tree, not in-record
TAG_NULL = 0x20

SPS_BLOB_LEN = 212          # History ResponseHeaders is always exactly this
SPS_HEADER_DWORDS = (121, 117)

# Plausible FILETIME window used only to grade confidence: 2000-01-01..2035-01-01
FT_MIN, FT_MAX = 125_911_584_000_000_000, 136_969_056_000_000_000

FIXED_COLUMNS = (
    "EntryId", "ContainerId", "CacheId", "UrlHash", "SecureDirectory",
    "FileSize", "Type", "Flags", "AccessCount", "SyncTime", "CreationTime",
    "ExpiryTime", "ModifiedTime", "AccessedTime", "PostCheckTime",
    "SyncCount", "ExemptionDelta",
)


# ── Minimal shim so dissect can parse bytes that are not on a live page ──

class _FakePage:
    # NewRecordFormat is required or RecordData refuses to parse tagged fields.
    flags = PAGE_FLAG.Leaf | PAGE_FLAG.NewRecordFormat


class _FakeTag:
    page = _FakePage()


class _FakeNode:
    __slots__ = ("data", "tag", "key")

    def __init__(self, buf):
        self.data = memoryview(buf)
        self.tag = _FakeTag()
        self.key = b""


# ── Structure parsing ────────────────────────────────────────────────

def parse_tag_fields(buf: bytes):
    """Read the tagged-field array of a candidate record.

    Returns [(column_id, data_offset), …] or None when the candidate fails
    the structural gate. The gate is strict: on the reference sample it
    rejected no genuine record and admitted no coincidental match.
    """
    if len(buf) < TAGGED_DATA_START + 4 or buf[:4] != RECORD_MARK:
        return None
    first = int.from_bytes(buf[TAGGED_DATA_START:TAGGED_DATA_START + 4], "little")
    if (first & 0xFFFF) != 256:          # first tagged column must be Url
        return None
    array_len = (first >> 16) & 0x7FFF   # first value's offset == array size
    if (array_len == 0 or array_len % 4 or array_len > 32
            or len(buf) < TAGGED_DATA_START + array_len):
        return None

    fields = []
    for i in range(array_len // 4):
        pos = TAGGED_DATA_START + 4 * i
        v = int.from_bytes(buf[pos:pos + 4], "little")
        fields.append((v & 0xFFFF, (v >> 16) & 0x7FFF))

    ids = [f[0] for f in fields]
    offsets = [f[1] for f in fields]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        return None
    if not all(256 <= i <= 263 for i in ids):
        return None
    if offsets != sorted(offsets):
        return None
    return fields


def find_record_end(raw: bytes, base: int, page_end: int, fields):
    """Locate the exact end of the record whose header sits at `base`.

    The last tagged field's own type says where it stops, which is what
    makes the trailing ResponseHeaders recoverable. Returns
    (end_offset, mode), where mode records how the end was determined.
    """
    last_id, last_offset = fields[-1]
    header_byte = base + TAGGED_DATA_START + last_offset
    if header_byte >= page_end:
        return None, "reject"

    flags = raw[header_byte]
    data_start = header_byte + 1

    if flags & TAG_NULL:
        return data_start, "null-field"
    if flags & TAG_SEPARATED:
        # Value is in the long-value tree; only its 8-byte key is in-record.
        return data_start + 8, "long-value-key"

    if last_id == 260:  # ResponseHeaders
        if (raw[data_start + 8:data_start + 12] == b"1SPS"
                and struct.unpack("<I", raw[data_start:data_start + 4])[0] == SPS_HEADER_DWORDS[0]
                and struct.unpack("<I", raw[data_start + 4:data_start + 8])[0] == SPS_HEADER_DWORDS[1]):
            return data_start + SPS_BLOB_LEN, "sps-212"
        # An HTTP header block is CRLF-separated ASCII ending in a blank
        # line and contains no NUL byte (true of every such blob in both
        # sample databases), so its end is the blank line, not a NUL.
        if raw[data_start:data_start + 5] == b"HTTP/":
            term = raw.find(b"\r\n\r\n", data_start, page_end)
            if term != -1:
                return term + 4, "http-crlf"
        nul = raw.find(b"\x00", data_start, page_end)
        if nul != -1:
            return nul + 1, "http-nul"
    elif last_id in (256, 257, 258, 261):  # UTF-16LE text field last
        i = data_start
        while i + 1 < page_end:
            if raw[i] == 0 and raw[i + 1] == 0:
                return i + 2, "utf16-nul"
            i += 2

    nxt = raw.find(RECORD_MARK, base + 4, page_end)
    return (nxt if nxt != -1 else page_end), "next-marker"


def _tagged_bytes(record_data: RecordData, column):
    """Read one tagged field's raw bytes.

    Used instead of RecordData's accessor, which can raise on carved data
    when a value points into a long-value tree that no longer exists.
    """
    idx = record_data._find_tag_field_idx(column.identifier)
    if idx is None:
        return None, 0
    tf = record_data._get_tag_field(idx)
    if tf.is_null:
        return None, int(tf.flags)
    if tf.flags & TAG_SEPARATED:
        return None, int(tf.flags)
    start = tf.offset + (1 if tf.has_extended_info else 0)
    end = (record_data._get_tag_field(idx + 1).offset
           if idx + 1 < record_data._tagged_data_count else len(record_data.data))
    base = record_data._tagged_data_start
    return bytes(record_data.data[base + start:base + end]), int(tf.flags)


def _utf16z(b):
    if not b:
        return None
    for i in range(0, len(b) - 1, 2):
        if b[i] == 0 and b[i + 1] == 0:
            b = b[:i]
            break
    return b.decode("utf-16-le", "replace") or None


def _plausible_filetime(v):
    return isinstance(v, int) and FT_MIN < v < FT_MAX


# Fixed-column layout of every Container_N record, relative to the end of
# the 4-byte record header, confirmed byte-for-byte against the reference
# sample. Records can be decoded with it even when the ESE catalogue is
# unreadable.
FIXED_LAYOUT = [
    ("EntryId", 0, "<q"), ("ContainerId", 8, "<q"), ("CacheId", 16, "<q"),
    ("UrlHash", 24, "<q"), ("SecureDirectory", 32, "<I"), ("FileSize", 36, "<q"),
    ("Type", 44, "<I"), ("Flags", 48, "<I"), ("AccessCount", 52, "<I"),
    ("SyncTime", 56, "<q"), ("CreationTime", 64, "<q"), ("ExpiryTime", 72, "<q"),
    ("ModifiedTime", 80, "<q"), ("AccessedTime", 88, "<q"),
    ("PostCheckTime", 96, "<q"), ("SyncCount", 104, "<I"),
    ("ExemptionDelta", 108, "<I"),
]

# Tagged column identifiers used by the Container_N schema.
TAG_URL = 256
TAG_FILENAME = 257
TAG_RESPONSE_HEADERS = 260


def decode_record_manually(buf: bytes, fields):
    """Decode a carved record straight from its bytes, without dissect.

    Used when the ESE catalogue cannot be read — a truncated image, a
    zeroed-out header page, or a database carved from free space. The record
    layout is fixed for every Container_N table, so the catalogue is a
    convenience rather than a requirement.
    """
    out = {}
    body = buf[4:]
    for name, offset, fmt in FIXED_LAYOUT:
        size = struct.calcsize(fmt)
        if offset + size > len(body):
            out[name] = None
            continue
        try:
            out[name] = struct.unpack_from(fmt, body, offset)[0]
        except struct.error:
            out[name] = None

    # Tagged fields: each value runs to the next field's offset.
    tagged = {}
    for i, (col_id, data_offset) in enumerate(fields):
        start = TAGGED_DATA_START + data_offset
        if start >= len(buf):
            continue
        flags = buf[start]
        value_start = start + 1
        if flags & TAG_NULL:
            continue
        if flags & TAG_SEPARATED:
            continue          # value lives in a long-value tree, not in-record
        end = (TAGGED_DATA_START + fields[i + 1][1]
               if i + 1 < len(fields) else len(buf))
        tagged[col_id] = bytes(buf[value_start:min(end, len(buf))])

    out["Url"] = _utf16z(tagged.get(TAG_URL))
    out["Filename"] = _utf16z(tagged.get(TAG_FILENAME))
    out["ResponseHeaders"] = tagged.get(TAG_RESPONSE_HEADERS)
    return out


def _live_record_offsets(db, page_size):
    """Absolute file offsets of every record that is still live, so carving
    never re-reports something the normal parse already found."""
    live = set()
    for table in db.tables():
        if not table.name.startswith("Container_"):
            continue
        try:
            for rec in ese_records.live_records(table):
                node = rec._node
                tag = node.tag
                page = tag.page
                live.add((page.num + 1) * page_size + PAGE_HEADER_LEN
                         + tag.offset + (len(tag.data) - len(node.data)))
        except Exception:
            continue
    return live


# ── Public API ───────────────────────────────────────────────────────

def carve_records(db_path, db=None, progress_callback=None):
    """Recover deleted container records from anywhere in the database file.

    Candidates are taken from the whole file, not only page slack: genuine
    deleted records also occur in inter-tag gaps and on orphaned pages no
    table B-tree reaches.

    Returns a list of dicts with the record's columns plus:
        _offset  byte offset the record was recovered from
        _page    page it lives on
        _mode    how the record's end was determined
        _grade   HIGH / MEDIUM / LOW confidence
        _sps     True when a full property-store blob was recovered
    """
    with open(db_path, "rb") as fh:
        raw = fh.read()

    # The catalogue is a convenience, not a requirement. If it cannot be read
    # — truncated image, zeroed header page, database carved from free space —
    # fall back to decoding records directly from their bytes.
    own_db = False
    if db is None:
        try:
            db = EseDB(open(db_path, "rb"))
            own_db = True
        except Exception:
            db = None

    page_size = DEFAULT_PAGE_SIZE
    template = None
    columns = {}
    live = set()

    if db is not None:
        try:
            page_size = db.page_size or DEFAULT_PAGE_SIZE
        except Exception:
            page_size = DEFAULT_PAGE_SIZE
        try:
            template = _container_template(db)
        except Exception:
            try:
                # Any Container_N table works — they all share the schema.
                template = next((t for t in db.tables()
                                 if t.name.startswith("Container_")), None)
            except Exception:
                template = None
        if template is not None:
            try:
                columns = {c.name: c for c in template.columns}
            except Exception:
                template, columns = None, {}
        try:
            live = _live_record_offsets(db, page_size)
        except Exception:
            live = set()

    out = []
    offset = raw.find(RECORD_MARK)
    scanned = 0
    while offset != -1:
        current, offset = offset, raw.find(RECORD_MARK, offset + 1)
        scanned += 1
        if progress_callback and scanned % 200 == 0:
            progress_callback(scanned, 0)
        if current in live:
            continue

        page_end = (current // page_size + 1) * page_size
        fields = parse_tag_fields(
            raw[current:min(current + TAGGED_DATA_START + 40, page_end)])
        if fields is None:
            continue
        end, mode = find_record_end(raw, current, page_end, fields)
        if end is None or end <= current + TAGGED_DATA_START:
            continue

        chunk = bytes(raw[current:end])
        rec = None
        rh_flags = 0
        decoded_by = "catalogue"
        if template is not None:
            try:
                rd = RecordData(template, _FakeNode(chunk))
                rec = {name: rd.get(columns[name]) for name in FIXED_COLUMNS}
                url_b, _ = _tagged_bytes(rd, columns["Url"])
                fn_b, _ = _tagged_bytes(rd, columns["Filename"])
                rh_b, rh_flags = _tagged_bytes(rd, columns["ResponseHeaders"])
                rec.update(Url=_utf16z(url_b), Filename=_utf16z(fn_b),
                           ResponseHeaders=rh_b)
            except Exception:
                rec = None
        if rec is None:
            # No usable catalogue (or dissect refused these bytes): decode
            # from the fixed layout instead.
            try:
                rec = decode_record_manually(chunk, fields)
                decoded_by = "fixed-layout"
            except Exception:
                continue
        rh_b = rec.get("ResponseHeaders")

        rec.update(
            _offset=current, _page=current // page_size - 1,
            _mode=mode, _rh_flags=rh_flags, _decoded_by=decoded_by,
            _sps=bool(rh_b) and len(rh_b) == SPS_BLOB_LEN and rh_b[8:12] == b"1SPS",
        )

        url, cid, eid = rec["Url"], rec["ContainerId"], rec["EntryId"]
        strong = (url and url.isprintable() and len(url) >= 4
                  and isinstance(cid, int) and 0 < cid < 100000
                  and isinstance(eid, int) and 0 <= eid < 10_000_000
                  and _plausible_filetime(rec["AccessedTime"])
                  and mode != "next-marker")
        rec["_grade"] = ("HIGH" if strong else
                         "MEDIUM" if (url and _plausible_filetime(rec["AccessedTime"]))
                         else "LOW")
        out.append(rec)

    if own_db:
        try:
            db.fh.close()
        except Exception:
            pass
    return out


def _container_template(db):
    """Any Container_N table, to read the column layout from.

    Container numbering is specific to the machine the cache came from, so
    no particular container is assumed. The layout is identical in every
    container table; one with rows is preferred.
    """
    best = None
    for table in db.tables():
        if not table.name.startswith("Container_"):
            continue
        if best is None:
            best = table
        try:
            if next(ese_records.live_records(table), None) is not None:
                return table
        except Exception:
            continue
    if best is None:
        raise KeyError("this database defines no Container_<n> table")
    return best


def validate(db_path):
    """Measure this method's accuracy against ground truth.

    Replays the blind carve pipeline at every live record's offset and
    compares the result with dissect's parse of the same record. Returns a
    Counter of outcomes: a measured error rate.
    """
    with open(db_path, "rb") as fh:
        raw = fh.read()
    db = EseDB(open(db_path, "rb"))
    page_size = db.page_size
    template = _container_template(db)
    columns = {c.name: c for c in template.columns}
    stats = collections.Counter()

    for table in db.tables():
        if not table.name.startswith("Container_"):
            continue
        for rec in ese_records.live_records(table):
            node = rec._node
            tag = node.tag
            page = tag.page
            off = ((page.num + 1) * page_size + PAGE_HEADER_LEN + tag.offset
                   + (len(tag.data) - len(node.data)))
            page_end = (page.num + 2) * page_size
            true_len = len(node.data)
            stats["live"] += 1

            fields = parse_tag_fields(
                raw[off:min(off + TAGGED_DATA_START + 40, page_end)])
            if fields is None:
                # Name which kind of non-detection this is. A record whose
                # data is a single null byte carries nothing to carve, and
                # returning nothing for it is correct (as for a URL held in
                # the long-value tree). A rejected record that does carry
                # data is a real miss and is counted separately.
                if true_len <= 1:
                    stats["empty stub (nothing to carve)"] += 1
                else:
                    stats["undetected WITH DATA"] += 1
                continue
            end, mode = find_record_end(raw, off, page_end, fields)
            stats["detected"] += 1
            stats["mode:" + mode] += 1
            stats["length exact" if end - off == true_len else "length differs"] += 1

            try:
                rd = RecordData(template, _FakeNode(bytes(raw[off:end])))
            except Exception:
                stats["reparse failed"] += 1
                continue
            stats["fixed columns exact"
                  if all(rd.get(columns[f]) == rec.get(f) for f in FIXED_COLUMNS)
                  else "fixed columns differ"] += 1
            ub, uflags = _tagged_bytes(rd, columns["Url"])
            if uflags & TAG_SEPARATED:
                # A URL too long for the record lives in the long-value tree;
                # only its 8-byte key is here. Returning nothing is the correct
                # answer, so counting it as a miss would misstate the method's
                # accuracy — it is a separate category, reported separately.
                stats["url in long-value tree"] += 1
            else:
                stats["url exact" if _utf16z(ub) == rec.get("Url")
                      else "url differs"] += 1
            rb, _ = _tagged_bytes(rd, columns["ResponseHeaders"])
            truth = rec.get("ResponseHeaders", raw=True)
            truth = bytes(truth) if truth is not None else None
            if rb == truth:
                stats["responseheaders exact"] += 1
            elif rb is None and truth:
                stats["responseheaders in long-value tree"] += 1
            else:
                stats["responseheaders differs"] += 1
    try:
        db.fh.close()
    except Exception:
        pass
    return stats
