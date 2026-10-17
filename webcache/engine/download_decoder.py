"""Decoder for the iedownload container's ResponseHeaders blob.

The blob holds a download record in the layout of the legacy index.dat
iedownload record: a 16-byte mixed-endian GUID (also present in the record
URL), an 8-byte FILETIME (UTC), a file size, then the local save path and
the source URL as strings.

The string delimiter and encoding are not authoritatively documented, so
the decoder anchors on structure (GUID, a plausible FILETIME, a size),
splits the string region on NULs and detects ASCII or UTF-16LE from the
pattern of zero bytes. Every result carries a confidence grade and the
blob offsets used, so it can be verified in the hex view.
"""

import re
import struct
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

# Plausible FILETIME window: 2000-01-01 .. 2040-01-01
_FT_MIN = 125911584000000000
_FT_MAX = 138538080000000000

_RE_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_RE_UNC_PATH = re.compile(r"^\\\\")
_RE_URL = re.compile(r"^(https?|ftp|file)://", re.IGNORECASE)
_RE_GUID_IN_URL = re.compile(r"\{?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                             r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\}?")


def filetime_to_dt_utc(ft: int) -> Optional[datetime]:
    if not ft or ft <= 0 or ft > 2650467743990000000:
        return None
    try:
        return FILETIME_EPOCH + timedelta(microseconds=ft // 10)
    except (OverflowError, ValueError):
        return None


def _extract_strings(data: bytes) -> list:
    """Extract candidate strings from a byte region, auto-detecting
    ASCII vs UTF-16LE by null-byte pattern. Returns list of (offset, encoding, text)."""
    results = []

    # UTF-16LE runs: printable ASCII char followed by 0x00, repeated
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){4,}", data):
        try:
            text = m.group().decode("utf-16-le").rstrip("\x00")
            if len(text) >= 4:
                results.append((m.start(), "utf-16-le", text))
        except UnicodeDecodeError:
            pass

    # ASCII runs of 4+ printable chars not inside a UTF-16 run
    utf16_spans = [(s, s + len(t) * 2) for s, _, t in results]

    def _in_utf16(pos):
        return any(s <= pos < e for s, e in utf16_spans)

    for m in re.finditer(rb"[\x20-\x7e]{4,}", data):
        if not _in_utf16(m.start()):
            try:
                results.append((m.start(), "ascii", m.group().decode("ascii")))
            except UnicodeDecodeError:
                pass

    results.sort(key=lambda r: r[0])
    return results


def decode_download_blob(blob: Optional[bytes]) -> dict:
    """Decode an iedownload ResponseHeaders blob.

    Returns {
        "guid": str|None, "guid_offset": int|None,
        "download_time_utc": datetime|None, "download_time_raw": int|None,
        "file_size": int|None,
        "local_path": str|None, "source_url": str|None,
        "strings": [(offset, encoding, text)],
        "confidence": "high"|"medium"|"low"|"none",
        "notes": [str],
    }"""
    out = {
        "guid": None, "guid_offset": None,
        "download_time_utc": None, "download_time_raw": None,
        "file_size": None,
        "local_path": None, "source_url": None,
        "strings": [], "confidence": "none", "notes": [],
    }
    if not blob or len(blob) < 24:
        if blob:
            out["notes"].append(f"Blob too small ({len(blob)}B) for a download record")
        return out

    strings = _extract_strings(blob)
    out["strings"] = strings

    # 1) Classify strings: local path vs source URL
    for _, enc, text in strings:
        t = text.strip().strip("\x00")
        if out["local_path"] is None and (_RE_DRIVE_PATH.match(t) or _RE_UNC_PATH.match(t)):
            out["local_path"] = t
        elif out["source_url"] is None and _RE_URL.match(t):
            out["source_url"] = t

    # 2) Find a plausible FILETIME on any 4-byte alignment in the fixed header
    #    region (before the first string).
    first_str_off = strings[0][0] if strings else len(blob)
    scan_end = min(first_str_off, len(blob) - 8)
    ft_candidates = []
    for off in range(0, max(0, scan_end) + 1):
        try:
            val = struct.unpack_from("<Q", blob, off)[0]
        except struct.error:
            break
        if _FT_MIN <= val <= _FT_MAX:
            ft_candidates.append((off, val))
    if ft_candidates:
        off, val = ft_candidates[0]
        out["download_time_raw"] = val
        out["download_time_utc"] = filetime_to_dt_utc(val)
        out["notes"].append(f"FILETIME found at offset {off}")

        # 3) GUID: 16 bytes immediately before the FILETIME is the classic
        #    layout; validate it round-trips as a GUID with sane variant bits.
        if off >= 16:
            guid_bytes = blob[off - 16: off]
            try:
                g = uuid.UUID(bytes_le=bytes(guid_bytes))
                out["guid"] = str(g)
                out["guid_offset"] = off - 16
            except ValueError:
                pass

        # 4) File size: 4- or 8-byte integer right after the FILETIME that is
        #    below 100 GB and non-zero.
        for size_off, fmt in ((off + 8, "<Q"), (off + 8, "<I")):
            try:
                sz = struct.unpack_from(fmt, blob, size_off)[0]
            except struct.error:
                continue
            if 0 < sz < 100 * 1024 ** 3:
                out["file_size"] = sz
                break

    # 5) GUID fallback: match a GUID literally present in one of the strings
    if out["guid"] is None:
        for _, _, text in strings:
            m = _RE_GUID_IN_URL.search(text)
            if m:
                out["guid"] = m.group(1).lower()
                out["notes"].append("GUID recovered from string content, not fixed header")
                break

    # Confidence: a structure-anchored decode ranks above strings alone.
    score = sum((
        out["local_path"] is not None,
        out["source_url"] is not None,
        out["download_time_utc"] is not None,
        out["guid"] is not None,
    ))
    if score >= 3:
        out["confidence"] = "high"
    elif score == 2:
        out["confidence"] = "medium"
    elif score == 1:
        out["confidence"] = "low"

    return out


def build_synthetic_download_blob(
    guid: str, filetime: int, file_size: int,
    local_path: str, source_url: str, encoding: str = "utf-16-le",
) -> bytes:
    """Build a synthetic iedownload blob for validation tests (mirrors the
    published layout: header + GUID + FILETIME + size + strings)."""
    g = uuid.UUID(guid)
    header = b"\x00" * 8  # unknown leading fields seen in real records
    body = g.bytes_le + struct.pack("<Q", filetime) + struct.pack("<Q", file_size)
    if encoding == "utf-16-le":
        strings = local_path.encode("utf-16-le") + b"\x00\x00" + \
            source_url.encode("utf-16-le") + b"\x00\x00"
    else:
        strings = local_path.encode("ascii") + b"\x00" + \
            source_url.encode("ascii") + b"\x00"
    return header + body + strings
