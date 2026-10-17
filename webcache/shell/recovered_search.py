"""What a Search reads from a recovered record: the one declared list.

Qt-free, so the offline report searches recovered records by the same
list as the application's Search.
"""
from ..engine import local_clock
from ..engine.ese_parser import format_cell
from ..provenance import is_absence
from .record_kinds import K_CARVED_STRING, K_CARVED_STRUCT, K_TOMBSTONE


#: The fields a Search over recovered records reads, per kind. A hit
#: asserts that the term is in the evidence, so only values read from the
#: carved bytes qualify:
#:
#: - a structured record: the columns struct_carver read off the record
#:   (Url, Filename, SecureDirectory, the integer columns, the six
#:   FILETIMEs -- rendered exactly as the live search renders the same
#:   column, via ese_parser.format_cell), the ResponseHeaders bytes, and
#:   the page title decoded from those bytes. A Filename the parser
#:   derived from a file: URL is a substring of Url, so it can never add
#:   a hit Url does not already give.
#: - a string carve: the carved text (Url) and the other carved readings
#:   of the same string (FragmentTexts). NearbyFiletime is context found
#:   near the bytes, not part of them.
#: - a deleted-record stub: its key values, matched as WHOLE numbers.
#:
#: Everything else on a Deleted Records row is this tool's own vocabulary
#: or location metadata and is not searched: Origin,
#: Method/RecoverySource, Confidence, ContainerType/ContainerName (the
#: latter joined from the LIVE Containers table), UrlHealth, IsInPrivate,
#: Region, Encoding, Source, Offset, Page, RecordEndMode, Timestamp,
#: HasResponseHeaders, InLiveDb, and the re-derivations of Url (CleanUrl,
#: UrlNormalized, Domain), which would let a stripped prefix or a
#: normalisation produce a hit the bytes do not hold. An absence token is
#: never searched, whatever field it sits in.
SEARCHED_FIELDS = {
    K_CARVED_STRUCT: ("Url", "Filename", "SecureDirectory",
                      "ResponseHeaders_raw", "SPS_PageTitle",
                      "EntryId", "ContainerId", "CacheId", "UrlHash",
                      "Flags", "Type", "AccessCount", "FileSize",
                      "SyncCount", "ExemptionDelta",
                      "CreationTime", "ModifiedTime", "AccessedTime",
                      "ExpiryTime", "SyncTime", "PostCheckTime"),
    K_CARVED_STRING: ("Url", "FragmentTexts"),
    K_TOMBSTONE: ("KeyValues",),
}

#: The structured-record columns held as a FILETIME: the record keeps the
#: number read off the bytes in "<name>_raw" and a tool-formatted string
#: under the name itself; the search renders the number, as live does.
_FILETIME_FIELDS = ("CreationTime", "ModifiedTime", "AccessedTime",
                    "ExpiryTime", "SyncTime", "PostCheckTime")


def searched_values(row):
    """[(field, value, whole), ...]: what Search reads from one Deleted
    Records row (SEARCHED_FIELDS for its kind). `value` is
    text or bytes; `whole` is True when it must equal the keyword rather
    than contain it (a stub's key). Empty and absent values are left out:
    a 0 FILETIME is the carve's own "none", never a time."""
    record = row.get("_record") or {}
    kind = row.get("_kind")
    out = []
    for name in SEARCHED_FIELDS.get(kind, ()):
        if kind == K_TOMBSTONE:
            for value in record.get(name) or ():
                out.append((name, str(value), True))
            continue
        if name in _FILETIME_FIELDS:
            raw = record.get(name + "_raw")
            if isinstance(raw, int) and raw:
                # A carved MSHist ModifiedTime is LOCAL: the same sentence
                # live Search prints, with the offset this record was
                # stamped with.
                text = (local_clock.describe_local_filetime(
                    raw, record.get(local_clock.TZ_OFFSET_KEY))
                    if local_clock.is_local_clock(record, name + "_raw")
                    else "")
                out.append((name, text or format_cell(raw, name), False))
            continue
        value = record.get(name)
        values = value if isinstance(value, (list, tuple)) else (value,)
        for item in values:
            if item is None or item == "" or is_absence(item):
                continue
            if isinstance(item, (bytes, bytearray)):
                out.append((name, bytes(item), False))
            elif isinstance(item, int):
                out.append((name, format_cell(item, name), False))
            else:
                out.append((name, str(item), False))
    return out
