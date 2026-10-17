"""
Serialized Property Storage (SPS) decoder for WebCacheV01.dat ResponseHeaders blobs.

History-container ResponseHeaders values are Windows Property Stores per
[MS-PROPSTORE]. Structure:

    outer:  [4-byte total size] repeated property-set blocks
    set:    [4-byte size] ['1SPS' 0x31 0x53 0x50 0x53] [16-byte FMTID GUID]
            [property records ...] [4-byte 0x00000000 terminator]
    record: [4-byte size] [4-byte property id] [1 reserved byte 0x00]
            [TypedPropertyValue = 2-byte VT type + 2-byte pad + value]

Property meanings below are DERIVED, not Microsoft-documented:
  - Property ID 6  = visit count (cross-check against the AccessCount
    column).
  - Property ID 24 = last-visit date, VT_FILETIME stored in LOCAL time.
    Every other ESE timestamp column in WebCache is UTC; never mix them.
"""

import struct
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

SPS_SIGNATURE = b"1SPS"

# Variant types we decode ([MS-OLEPS] TypedPropertyValue)
VT_EMPTY = 0x0000
VT_NULL = 0x0001
VT_I2 = 0x0002
VT_I4 = 0x0003
VT_R4 = 0x0004
VT_R8 = 0x0005
VT_DATE = 0x0007
VT_BSTR = 0x0008
VT_BOOL = 0x000B
VT_I1 = 0x0010
VT_UI1 = 0x0011
VT_UI2 = 0x0012
VT_UI4 = 0x0013
VT_I8 = 0x0014
VT_UI8 = 0x0015
VT_LPSTR = 0x001E
VT_LPWSTR = 0x001F
VT_FILETIME = 0x0040
VT_BLOB = 0x0041
VT_STREAM = 0x0042
VT_CLSID = 0x0048

VT_NAMES = {
    VT_EMPTY: "VT_EMPTY", VT_NULL: "VT_NULL", VT_I2: "VT_I2", VT_I4: "VT_I4",
    VT_R4: "VT_R4", VT_R8: "VT_R8", VT_DATE: "VT_DATE", VT_BSTR: "VT_BSTR",
    VT_BOOL: "VT_BOOL", VT_I1: "VT_I1", VT_UI1: "VT_UI1", VT_UI2: "VT_UI2",
    VT_UI4: "VT_UI4", VT_I8: "VT_I8", VT_UI8: "VT_UI8", VT_LPSTR: "VT_LPSTR",
    VT_LPWSTR: "VT_LPWSTR", VT_FILETIME: "VT_FILETIME", VT_BLOB: "VT_BLOB",
    VT_STREAM: "VT_STREAM", VT_CLSID: "VT_CLSID",
}

# IE/Edge (EdgeHTML) history property IDs. "derived" means not
# Microsoft-documented: the meaning was established by correlation with
# propkey.h and validation against sample databases.
KNOWN_HISTORY_PROPS = {
    6: ("VisitCount", "Visit count (derived: published research)"),
    24: ("LastVisitTimeLocal", "True last-visit time — FILETIME in LOCAL time (derived)"),
}

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def filetime_to_dt_utc(ft: int) -> Optional[datetime]:
    """Convert a FILETIME integer to a UTC datetime. Returns None if implausible."""
    if not ft or ft <= 0 or ft > 2650467743990000000:
        return None
    try:
        return FILETIME_EPOCH + timedelta(microseconds=ft // 10)
    except (OverflowError, ValueError):
        return None


def filetime_to_dt_naive(ft: int) -> Optional[datetime]:
    """Convert a FILETIME integer to a NAIVE datetime (no tz) — for values
    known to be stored in local time (SPS property 24)."""
    dt = filetime_to_dt_utc(ft)
    return dt.replace(tzinfo=None) if dt else None


def _decode_typed_value(vt: int, data: bytes) -> tuple:
    """Decode a TypedPropertyValue payload. Returns (value, ok)."""
    try:
        if vt == VT_EMPTY or vt == VT_NULL:
            return None, True
        if vt == VT_I2:
            return struct.unpack_from("<h", data)[0], True
        if vt == VT_UI2:
            return struct.unpack_from("<H", data)[0], True
        if vt == VT_I4:
            return struct.unpack_from("<i", data)[0], True
        if vt == VT_UI4:
            return struct.unpack_from("<I", data)[0], True
        if vt == VT_I8:
            return struct.unpack_from("<q", data)[0], True
        if vt in (VT_UI8, VT_FILETIME):
            return struct.unpack_from("<Q", data)[0], True
        if vt == VT_R4:
            return struct.unpack_from("<f", data)[0], True
        if vt in (VT_R8, VT_DATE):
            return struct.unpack_from("<d", data)[0], True
        if vt == VT_BOOL:
            return struct.unpack_from("<h", data)[0] != 0, True
        if vt in (VT_I1,):
            return struct.unpack_from("<b", data)[0], True
        if vt in (VT_UI1,):
            return struct.unpack_from("<B", data)[0], True
        if vt in (VT_LPWSTR, VT_BSTR):
            # [4-byte char/byte count][UTF-16LE chars][NUL]
            n = struct.unpack_from("<I", data)[0]
            raw = data[4:4 + n * 2] if vt == VT_LPWSTR else data[4:4 + n]
            return raw.decode("utf-16-le", errors="replace").rstrip("\x00"), True
        if vt == VT_LPSTR:
            n = struct.unpack_from("<I", data)[0]
            return data[4:4 + n].decode("ascii", errors="replace").rstrip("\x00"), True
        if vt == VT_CLSID:
            return str(uuid.UUID(bytes_le=bytes(data[:16]))), True
        if vt in (VT_BLOB, VT_STREAM):
            n = struct.unpack_from("<I", data)[0]
            return bytes(data[4:4 + n]), True
    except (struct.error, ValueError, IndexError):
        return None, False
    return bytes(data), False  # unknown VT: keep raw for the hex view


def parse_property_store(blob: Optional[bytes]) -> list:
    """Parse a serialized property store. Returns a list of property sets:
    [{"fmtid": str, "offset": int, "properties": {id: prop_dict}}]
    Each prop_dict: {"id", "vt", "vt_name", "value", "raw", "name", "meaning"}.
    Tolerant: scans for '1SPS' so leading garbage or concatenated stores parse.
    """
    if not blob or len(blob) < 28:
        return []

    sets = []
    pos = 0
    n = len(blob)

    while pos < n - 28:
        sig_at = blob.find(SPS_SIGNATURE, pos)
        if sig_at < 4:
            if sig_at == -1:
                break
            pos = sig_at + 4
            continue

        set_start = sig_at - 4
        try:
            set_size = struct.unpack_from("<I", blob, set_start)[0]
        except struct.error:
            break
        if set_size < 28 or set_start + set_size > n + 4:
            pos = sig_at + 4
            continue

        fmtid_raw = blob[sig_at + 4: sig_at + 20]
        try:
            fmtid = str(uuid.UUID(bytes_le=fmtid_raw))
        except ValueError:
            fmtid = fmtid_raw.hex()

        props = {}
        rec_pos = sig_at + 20
        set_end = min(set_start + set_size, n)

        while rec_pos + 4 <= set_end:
            rec_size = struct.unpack_from("<I", blob, rec_pos)[0]
            if rec_size == 0:
                break  # terminator
            if rec_size < 13 or rec_pos + rec_size > set_end:
                break  # corrupt record — stop this set, keep what we have
            prop_id = struct.unpack_from("<I", blob, rec_pos + 4)[0]
            # rec_pos+8 is the 1 reserved byte, value starts at +9
            vt = struct.unpack_from("<H", blob, rec_pos + 9)[0]
            payload = blob[rec_pos + 13: rec_pos + rec_size]
            value, ok = _decode_typed_value(vt, payload)

            name, meaning = KNOWN_HISTORY_PROPS.get(prop_id, ("", ""))
            props[prop_id] = {
                "id": prop_id,
                "vt": vt,
                "vt_name": VT_NAMES.get(vt, f"VT_0x{vt:04X}"),
                "value": value,
                "decoded_ok": ok,
                "raw": bytes(blob[rec_pos + 9: rec_pos + rec_size]),
                "name": name,
                "meaning": meaning,
            }
            rec_pos += rec_size

        sets.append({"fmtid": fmtid, "offset": set_start, "properties": props})
        pos = max(rec_pos, sig_at + 4)

    return sets


def classify_response_headers(blob: Optional[bytes]) -> str:
    """Classify a ResponseHeaders blob into its forensic content class:
    'sps' (property store), 'http' (raw HTTP response headers),
    'download' (iedownload record), 'empty', or 'unknown'."""
    if not blob:
        return "empty"
    if SPS_SIGNATURE in blob[:256]:
        return "sps"
    head = blob[:16]
    if head.startswith(b"HTTP/"):
        return "http"
    try:
        if blob[:5].decode("ascii", errors="ignore").startswith("HTTP/"):
            return "http"
    except Exception:
        pass
    # UTF-16LE "HTTP/"
    if blob[:10] == "HTTP/".encode("utf-16-le"):
        return "http"
    return "unknown"


def extract_history_forensics(blob: Optional[bytes]) -> dict:
    """High-level extraction for a History-record ResponseHeaders blob.

    Returns {
        "visit_count":            int | None   (SPS id 6 — derived),
        "last_visit_local":       naive datetime | None (SPS id 24 — LOCAL time),
        "last_visit_local_raw":   int | None   (raw FILETIME),
        "page_title":             str | None   (any LPWSTR string property),
        "property_sets":          full parse result,
        "all_properties":         flat {id: prop} merged across sets,
    }"""
    out = {
        "visit_count": None,
        "last_visit_local": None,
        "last_visit_local_raw": None,
        "page_title": None,
        "property_sets": [],
        "all_properties": {},
    }
    sets = parse_property_store(blob)
    if not sets:
        return out
    out["property_sets"] = sets

    for pset in sets:
        for pid, prop in pset["properties"].items():
            out["all_properties"][pid] = prop
            if pid == 6 and isinstance(prop["value"], int):
                out["visit_count"] = prop["value"]
            elif pid == 24 and prop["vt"] == VT_FILETIME and isinstance(prop["value"], int):
                out["last_visit_local_raw"] = prop["value"]
                out["last_visit_local"] = filetime_to_dt_naive(prop["value"])
            elif prop["vt"] == VT_LPWSTR and isinstance(prop["value"], str):
                if out["page_title"] is None and len(prop["value"]) > 1:
                    out["page_title"] = prop["value"]

    return out
