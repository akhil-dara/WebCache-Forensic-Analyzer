"""
Forensic Analysis Engine
Provides search, filtering, statistics, timeline grouping,
domain extraction, and export capabilities.
"""

import contextlib
import csv
import functools
import hashlib
import json
import math
import os
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

# One implementation of account-prefix stripping, shared with the carver, so a
# live record and a carved reading of the same URL normalise identically.
# recovery_engine has no local imports, so this direction cannot cycle.
from .recovery_engine import strip_account_prefix
import importlib.util
from urllib.parse import urlparse

# Availability without import: openpyxl (which pulls in numpy) and reportlab
# take seconds to import, so importing them at module load would delay every
# launch. find_spec checks that each is installed without importing it; the
# writers import what they need when called (see _xlsx() and _reportlab()
# below).
_HAS = importlib.util.find_spec

HAS_OPENPYXL = _HAS("openpyxl") is not None
HAS_REPORTLAB = _HAS("reportlab") is not None


#: The tool's one sentence about an EntryId gap. Every row carries it; the
#: Findings grid states it once, in a header tooltip.
ENTRYID_GAP_INTERPRETATION = (
    "IDs absent from the sequence. Consistent with deletion, with "
    "automatic cache scavenging, or with IDs consumed by uncommitted "
    "transactions; this analysis does not distinguish between them.")


def _xlsx():
    """openpyxl's names, imported on first use. Raises the same message as
    when the package is missing at load, so callers see the usual error."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import (Alignment, Border, Font, PatternFill,
                                     Side)
    except ImportError:
        raise RuntimeError("openpyxl not installed. Run: pip install openpyxl")
    return Workbook, Font, PatternFill, Alignment, Border, Side


def _reportlab():
    """reportlab's names, imported on first use."""
    try:
        from reportlab.lib import colors as rl_colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                        Spacer, Table, TableStyle)
    except ImportError:
        raise RuntimeError("reportlab not installed. Run: pip install reportlab")
    return (rl_colors, A4, getSampleStyleSheet, ParagraphStyle, mm,
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak)

from .ese_parser import filetime_to_dt, filetime_to_rfc3339
from . import evidence_model as em
from . import ese_records
from . import local_clock
# case_db defines what identifies a record. It is a stdlib-only leaf module,
# so importing it here cannot cycle, and every export keys tags and comments
# the way the case file does, carved artifacts included.
from .case_db import CaseDb
from .. import provenance

TOOL_NAME = "WebCache Forensic Analyzer"
TOOL_VERSION = "5.0"


def _report_canvas(footer_left):
    """A reportlab canvasmaker for the signed report.

    Every page carries "Page N of M" and a footer naming the case and the
    exhibit's SHA-256, so a single printed page can be tied to its report.
    M is known only after layout, so pages are held until save()
    (reportlab's two-pass pattern).

    The document dates are stamped in UTC, like every time the report
    states. reportlab's local stamp computes the offset's minutes from
    seconds (`gmtoff % 3600 % 60`), so a +05:30 machine would be written
    +05'00'.
    """
    import time as _time
    from reportlab.pdfgen import canvas as _canvas

    class ReportCanvas(_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            stamp = self._doc._timeStamp
            stamp.lt = _time.gmtime(stamp.t)
            stamp.YMDhms = tuple(stamp.lt)[:6]
            stamp.dhh = stamp.dmm = 0
            stamp.tzname = "UTC"
            self._held = []

        def showPage(self):
            self._held.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._held)
            for number, state in enumerate(self._held, 1):
                self.__dict__.update(state)
                width = self._pagesize[0]
                self.saveState()
                self.setFont("Helvetica", 6.5)
                self.setFillGray(0.35)
                self.drawString(42, 22, footer_left)
                self.drawRightString(width - 42, 22,
                                     "Page %d of %d" % (number, total))
                self.restoreState()
                super().showPage()
            super().save()

    return ReportCanvas


# Suspicious TLDs / schemes for the built-in watchlist
# Registries that independent abuse reporting has repeatedly ranked among the
# highest for spam, phishing and malware hosting — largely because
# registration is free or near-free. A domain under one of these is a reason
# to look at it, and nothing more: they are ordinary public gTLDs with
# entirely legitimate registrants (abc.xyz is Alphabet Inc.). Matching one is
# never by itself a finding about the person who visited it.
#
# onion is handled by its own rule rather than this one: a Tor hidden service
# is a specific, meaningful observation, not a registry statistic.
ELEVATED_ABUSE_TLDS = {".top", ".xyz", ".click", ".gq", ".tk", ".ml",
                       ".cf", ".zip", ".mov", ".country", ".stream"}

# Kept under the previous name: saved watchlists and any caller that imported
# it still resolve. .onion stays in this view of the set for compatibility.
SUSPICIOUS_TLDS = ELEVATED_ABUSE_TLDS | {".onion"}

# Why each rule fires, in words a report can quote.
IOC_RULE_BASIS = {
    "tld-elevated-abuse": (
        "The domain is registered under a top-level domain that abuse "
        "reporting consistently ranks among the highest for spam, phishing "
        "and malware hosting. These are ordinary public registries with "
        "legitimate registrants; this is a prompt to examine the domain, not "
        "a finding about it or about the person who visited it."),
    "tor-onion": (
        "The host is a .onion address, which resolves only through the Tor "
        "network. Reaching it requires Tor-capable software. This records "
        "that such an address appears in the cache; it does not establish "
        "who requested it or why."),
    "watchlist": (
        "The URL contains a term supplied by the examiner in the watchlist "
        "for this case. The significance of the term is the examiner's to "
        "state."),
}


# ══════════════════════════════════════════════════════════════════════
# CANONICAL EXPORT SCHEMA
# Every field the parser produces, plus derived analysis fields. Exports
# render from this single list so no format can silently drop a column.
# (key, column header, group)
# ══════════════════════════════════════════════════════════════════════

ENTRY_FIELDS = [
    # -- record identity ------------------------------------------------
    ("EntryId",                "EntryId",                 "Identity"),
    ("ContainerId",            "ContainerId",             "Identity"),
    ("ContainerName",          "ContainerName",           "Identity"),
    ("ContainerType",          "ContainerType",           "Identity"),
    ("TableName",              "SourceTable",             "Identity"),
    ("CacheId",                "CacheId",                 "Identity"),
    ("UrlHash",                "UrlHash",                 "Identity"),
    ("SecureDirectory",        "SecureDirectory",         "Identity"),
    # -- URL forensics ---------------------------------------------------
    ("Url",                    "Url (raw)",               "URL"),
    ("CleanUrl",               "Url (clean)",             "URL"),
    ("Domain",                 "Domain",                  "URL"),
    ("Scheme",                 "Scheme",                  "URL"),
    ("UrlCategory",            "UrlCategory",             "URL"),
    ("UrlUsername",            "UrlUsername",             "URL"),
    ("SearchTerms",            "SearchTerms",             "URL"),
    ("RedirectUrl",            "RedirectUrl",             "URL"),
    ("MSHistFrom",             "MSHistRangeFrom",         "URL"),
    ("MSHistTo",               "MSHistRangeTo",           "URL"),
    ("IsLocalFile",            "IsLocalFile",             "URL"),
    ("IsLeak",                 "IsLeakRecord",            "URL"),
    # -- visit counts ----------------------------------------------------
    ("AccessCount",            "AccessCount (column)",    "Visits"),
    ("SPS_VisitCount",         "VisitCount (SPS id6)",    "Visits"),
    ("VisitCountBest",         "VisitCount (best available)", "Visits"),
    ("VisitCountBestSource",   "VisitCount source",       "Visits"),
    ("SyncCount",              "SyncCount",               "Visits"),
    # -- timestamps: display (UTC unless labeled) ------------------------
    ("KeyTimestampUTC",        "KeyTimestamp (RFC3339 UTC)", "Timestamps"),
    ("KeyTimestampDesc",       "KeyTimestamp meaning",    "Timestamps"),
    ("CreationTime",           "CreationTime (UTC)",      "Timestamps"),
    ("ModifiedTime",           "ModifiedTime (UTC)",      "Timestamps"),
    ("AccessedTime",           "AccessedTime (UTC)",      "Timestamps"),
    ("ExpiryTime",             "ExpiryTime (UTC)",        "Timestamps"),
    ("SyncTime",               "SyncTime (UTC)",          "Timestamps"),
    ("PostCheckTime",          "PostCheckTime (UTC)",     "Timestamps"),
    ("SPS_LastVisitLocal",     "LastVisit (SPS id24, LOCAL)", "Timestamps"),
    # An MSHist record's ModifiedTime as stored: the machine's LOCAL wall
    # clock. "ModifiedTime (UTC)" carries the UTC derived from the recovered
    # zone (engine/local_clock.py). A column of its own keeps the LOCAL
    # label, so the stored value is never read as UTC in a spreadsheet.
    ("ModifiedTimeLocal",      "ModifiedTime (LOCAL, as stored by MSHist)", "Timestamps"),
    # -- timestamps: raw FILETIME + RFC 3339 ------------------------------
    ("CreationTime_rfc",       "CreationTime (RFC3339)",  "Timestamps"),
    ("ModifiedTime_rfc",       "ModifiedTime (RFC3339)",  "Timestamps"),
    ("AccessedTime_rfc",       "AccessedTime (RFC3339)",  "Timestamps"),
    ("ExpiryTime_rfc",         "ExpiryTime (RFC3339)",    "Timestamps"),
    ("SyncTime_rfc",           "SyncTime (RFC3339)",      "Timestamps"),
    ("CreationTime_raw",       "CreationTime (FILETIME)", "Raw"),
    ("ModifiedTime_raw",       "ModifiedTime (FILETIME)", "Raw"),
    ("AccessedTime_raw",       "AccessedTime (FILETIME)", "Raw"),
    ("ExpiryTime_raw",         "ExpiryTime (FILETIME)",   "Raw"),
    ("SyncTime_raw",           "SyncTime (FILETIME)",     "Raw"),
    ("PostCheckTime_raw",      "PostCheckTime (FILETIME)", "Raw"),
    ("SPS_LastVisitLocal_raw", "LastVisitLocal (FILETIME)", "Raw"),
    # -- flags / privacy --------------------------------------------------
    ("Flags",                  "Flags (int)",             "Flags"),
    ("FlagsDecoded",           "Flags (decoded)",         "Flags"),
    ("IsInPrivate",            "IsInPrivate",             "Flags"),
    ("Type",                   "Type",                    "Flags"),
    ("ExemptionDelta",         "ExemptionDelta",          "Flags"),
    # -- cached file -------------------------------------------------------
    ("Filename",               "CachedFilename",          "File"),
    ("FileExtension",          "FileExtension",           "File"),
    ("FileSize",               "FileSize",                "File"),
    ("CacheFolder",            "CacheFolder",             "File"),
    ("SecureDirectoryName",    "SecureDirectoryName",     "File"),
    ("CachedFilePath",         "CachedFilePath",          "File"),
    # -- downloads ---------------------------------------------------------
    ("DownloadPath",           "DownloadSavedTo",         "Download"),
    ("DownloadSourceUrl",      "DownloadSourceUrl",       "Download"),
    ("DownloadSize",           "DownloadSize",            "Download"),
    ("DownloadTime",           "DownloadTime (UTC)",      "Download"),
    # -- blobs / headers ----------------------------------------------------
    ("BlobClass",              "ResponseBlobClass",       "Blobs"),
    ("SPS_PageTitle",          "PageTitle (SPS)",         "Blobs"),
    ("SPS_PropertiesText",     "SPS properties (all)",    "Blobs"),
    ("HttpStatus",             "HTTP status",             "Blobs"),
    ("ContentType",            "Content-Type",            "Blobs"),
    ("Server",                 "Server header",           "Blobs"),
    ("ResponseHeadersText",    "ResponseHeaders (decoded)", "Blobs"),
    ("RequestHeadersText",     "RequestHeaders (decoded)", "Blobs"),
    ("ResponseHeadersSize",    "ResponseHeaders bytes",   "Blobs"),
    ("RequestHeadersSize",     "RequestHeaders bytes",    "Blobs"),
    # -- case management ----------------------------------------------------
    ("Tags",                   "Tags",                    "Case"),
    ("Comments",               "Analyst comments",        "Case"),
    # Carve provenance. The carver records Source, Offset, Page, Method and
    # Confidence, and the schema carries every one, so an exported recovered
    # record states that it was carved, from which file, at what byte offset
    # and with what confidence.
    ("Origin",                 "Origin",                  "Provenance"),
    ("Source",                 "Carved from file",        "Provenance"),
    ("Offset",                 "Carved at offset",         "Provenance"),
    ("Page",                   "Carved from page",         "Provenance"),
    ("Method",                 "Carve method",             "Provenance"),
    ("Confidence",             "Carve confidence",         "Provenance"),
]

ENTRY_FIELD_KEYS = [k for k, _, _ in ENTRY_FIELDS]
ENTRY_FIELD_HEADERS = [h for _, h, _ in ENTRY_FIELDS]

# A value becomes a date because its column says so, never because it parses
# as one, so a page title or search term that resembles a timestamp is not
# rewritten. The schema's "Timestamps" group covers most of the All Records /
# History / Downloads sheets, but some sheets and columns carry timestamps
# under keys outside ENTRY_FIELDS (or under another group, as DownloadTime is
# under "Download"); each key here was checked against the code that fills
# it. Module-level so export_csv uses the same set as export_xlsx.
TIMESTAMP_EXPORT_KEYS = frozenset(
    k for k, _h, g in ENTRY_FIELDS
    # RFC 3339 columns are written verbatim, keeping the "T", the zone and
    # the offset that make them RFC 3339.
    if g == "Timestamps" and not k.endswith("_rfc") and k != "KeyTimestampUTC"
) | {
    "DownloadTime",              # ENTRY_FIELDS group is "Download", not "Timestamps"
    "Expires", "LastModified",   # Cookies
    "LastTimeUsed",              # HSTS (Expires above covers HSTS's own Expires too)
    "LastAccessTime", "LastScavengeTime",  # Containers / Partitions
    "first_seen", "last_seen",   # Domains
    "FirstSeen", "LastSeen",     # Beaconing
    # Recovered. NearbyFiletimeRfc is NOT here: its heading says RFC3339,
    # so it is written verbatim with its Z like every other RFC3339 column.
    "LogCreateTime",
}

RECOVERED_FIELDS = [
    ("Url", "Url"), ("RecoverySource", "RecoverySource"),
    ("Confidence", "Confidence"), ("Source", "SourceFile"),
    ("Region", "Region"), ("Page", "Page"), ("Offset", "ByteOffset"),
    ("Encoding", "StringEncoding"), ("NearbyFiletimeRfc", "NearbyTime (RFC3339)"),
    ("Domain", "Domain"), ("LogGeneration", "LogGeneration"),
    ("LogCreateTime", "LogCreateTime"), ("InLiveDb", "PresentInLiveDb"),
]

COOKIE_FIELDS = [
    ("Domain", "Domain"), ("RDomain", "ReversedDomain"), ("Name", "CookieName"),
    ("Value", "CookieValue"), ("Path", "Path"), ("Expires", "Expires (UTC)"),
    ("LastModified", "LastModified (UTC)"), ("Flags", "Flags"),
    ("IsSecure", "IsSecure"), ("EntryId", "EntryId"), ("Table", "SourceTable"),
    ("PartitionId", "PartitionId"), ("AppDirectory", "AppDirectory"),
    ("Expires_raw", "Expires (FILETIME)"),
    ("LastModified_raw", "LastModified (FILETIME)"),
]

HSTS_FIELDS = [
    ("Domain", "Domain"), ("IncludeSubdomains", "IncludeSubdomains"),
    ("Expires", "Expires"), ("LastTimeUsed", "LastTimeUsed (UTC)"),
    ("EntryId", "EntryId"), ("Table", "SourceTable"), ("PartitionId", "PartitionId"),
]

CERT_FIELDS = [
    ("HostPort", "Host:Port"), ("IsCertificate", "IsCertificate"),
    ("Thumbprint", "SHA1Thumbprint"), ("ModifiedTime", "ModifiedTime (UTC)"),
    ("BlobSize", "BlobSize"), ("Type", "Type"), ("EntryId", "EntryId"),
    ("Table", "SourceTable"), ("PartitionId", "PartitionId"),
]

LEAK_FIELDS = [("LeakId", "LeakId"), ("Filename", "Filename"),
               ("CreationTime", "CreationTime (UTC)"),
               ("CreationTime_raw", "CreationTime (FILETIME)")]

CONTAINER_FIELDS = [
    ("ContainerId", "ContainerId"), ("Name", "Name"), ("TableName", "TableName"),
    ("RecordCount", "RecordCount"), ("Directory", "Directory"),
    # The subdirectory names, so the exported container list can rebuild a
    # cached file's path.
    ("SecureDirectoryNames", "SecureDirectories"),
    ("PartitionId", "PartitionId"), ("Flags", "Flags"), ("Size", "Size"),
    ("Limit", "Limit"), ("EntryMaxAge", "EntryMaxAge"),
    ("LastAccessTime", "LastAccessTime (UTC)"),
    ("LastScavengeTime", "LastScavengeTime (UTC)"), ("HasTable", "HasTable"),
]

PARTITION_FIELDS = [
    ("TableId", "TableId"), ("PartitionType", "PartitionType"),
    ("PartitionTypeName", "PartitionTypeName"), ("SetId", "SetId"),
    ("PartitionId", "PartitionId"), ("Directory", "Directory"),
    ("LastScavengeTime", "LastScavengeTime (UTC)"),
]


def _flatten_headers(headers) -> str:
    """Render a decoded header dict as a single readable cell value."""
    if not isinstance(headers, dict) or not headers:
        return ""
    parts = []
    status = headers.get("_status_line")
    if status:
        parts.append(status)
    for k, v in headers.items():
        if k == "_status_line":
            continue
        parts.append(f"{k}: {v}")
    return " | ".join(parts)


# The order that decides when a record happened. ModifiedTime is the visit
# being written; AccessedTime is a cache touch; CreationTime is when the entry
# was first made. SyncTime is not used: it is the last server revalidation,
# cache maintenance rather than user activity, and the analysis must date
# records as the timeline does.
KEY_TIMESTAMP_ORDER = (
    ("ModifiedTime_raw", "ModifiedTime (visit written)"),
    ("AccessedTime_raw", "AccessedTime (cache touch)"),
    ("CreationTime_raw", "CreationTime"),
)


def key_timestamp(entry):
    """The record's canonical instant AS UTC, and which column it came from.

    Used by the exports, the timeline and every analysis, so that all three
    agree about when a record happened. An MSHist record's ModifiedTime is
    local wall-clock (engine/local_clock.py): its UTC is derived from the
    recovered zone, or 0 when there is none -- never the local digits
    labelled UTC, and never a silent fall-through to a different column.
    """
    for field, description in KEY_TIMESTAMP_ORDER:
        raw = entry.get(field)
        if not raw:
            continue
        if local_clock.is_local_clock(entry, field):
            return (local_clock.utc_raw(entry, field),
                    "%s — %s" % (description, local_clock.clock_note(entry)))
        return raw, description
    return 0, ""


#: What SPS id 6 is: the count the property store keeps of the user's own
#: visits. Named as a constant so a caller states the source by reference
#: rather than re-typing the sentence -- two spellings of this claim would
#: be two claims.
VISIT_SOURCE_SPS = "SPS id6 (property store: user visits)"

#: What the AccessCount column is: how often the cache entry was touched,
#: which is not the same claim as a user visit.
VISIT_SOURCE_ACCESS_COUNT = (
    "AccessCount column (cache touches, not user visits)")


def visit_count_best(entry):
    """(value, source): the record's best visit count, and which counter it
    came from.

    One function used by the export rows (VisitCountBestSource) and by the
    row builders in webcache/shell/, so the screen and the exports agree.

    `is not None`, never truthiness: 0 is a recorded count, and `or` would
    fall through to AccessCount and mislabel the counter. Returns
    (None, "") when the record has no counter.
    """
    value = entry.get("SPS_VisitCount")
    if value is not None:
        return value, VISIT_SOURCE_SPS
    value = entry.get("AccessCount")
    return value, (VISIT_SOURCE_ACCESS_COUNT if value is not None else "")


def key_timestamp_display(entry):
    """The same instant as key_timestamp(), formatted for a person.

    key_timestamp() returns the stored FILETIME, which sorting and
    arithmetic need. This walks the same order and returns the decoded
    sibling column, so a time on screen is the instant the timeline and the
    exports used.

    Returns (text, which column it came from); ("", "") when the record
    carries no timestamp.
    """
    for field, description in KEY_TIMESTAMP_ORDER:
        if not entry.get(field):
            continue
        if local_clock.is_local_clock(entry, field):
            raw = local_clock.utc_raw(entry, field)
            dt = filetime_to_dt(raw) if raw else None
            shown = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""
            return shown, "%s — %s" % (description,
                                            local_clock.clock_note(entry))
        shown = entry.get(field[:-4])          # drop the "_raw" suffix
        if shown:
            return str(shown).replace(" UTC", ""), description
    return "", ""


def build_entry_row(entry: dict, tags_map: Optional[dict] = None,
                    comments_map: Optional[dict] = None) -> dict:
    """Expand a parsed entry into the full canonical export row, computing
    every derived field. This is the single source of truth for exports."""
    url = entry.get("Url", "") or ""
    resp = entry.get("ResponseHeaders", {})
    req = entry.get("RequestHeaders", {})

    key_raw, key_desc = key_timestamp(entry)

    # Name the counter this number came from. SPS id 6 counts the user's
    # visits; AccessCount counts cache touches, a different claim. The
    # fallback is visit_count_best() above, shared with the screen.
    visit_best, visit_source = visit_count_best(entry)

    status = content_type = server = ""
    if isinstance(resp, dict) and resp:
        line = resp.get("_status_line", "")
        if line:
            bits = line.split(" ", 2)
            status = bits[1] if len(bits) >= 2 else ""
        for k, v in resp.items():
            kl = k.lower()
            if kl == "content-type" and not content_type:
                content_type = str(v)
            elif kl == "server" and not server:
                server = str(v)

    sps_props = entry.get("SPS_Properties", {}) or {}
    sps_text = "; ".join(f"id{pid}={val}" for pid, val in sorted(sps_props.items())
                         if not isinstance(val, (bytes, bytearray)))

    # A live or structured-carve record's table name is derived from its
    # ContainerId ("Container_<id>"). A deleted-record stub has no
    # ContainerId (it resolves only to a b-tree key) but supplies its own
    # table name ("Container_11", "BlobEntry_13", "LeakFiles"). A structured
    # carve that resolved no container carries the key with the value None.
    # So "Container_<id>" is derived only from a real id (an int, or a
    # string of digits); otherwise a supplied TableName is kept, or "" is
    # used, as for every other unresolved identity field here (Domain,
    # ContentType and Server also default to "").
    cid = entry.get("ContainerId")
    has_real_container_id = (
        (isinstance(cid, int) and not isinstance(cid, bool))
        or (isinstance(cid, str) and cid.strip().isdigit()))
    if has_real_container_id:
        table_name = f"Container_{cid}"
    else:
        table_name = entry.get("TableName") or ""

    row = dict(entry)
    # Origin is filled for live rows too ("Live record"), as on screen. The
    # rule is detail_fields.row_for_record's: an explicit Origin wins;
    # otherwise RecoverySource (which every carved artifact and stub
    # carries, and no live parser record does) decides.
    if not row.get("Origin"):
        row["Origin"] = (provenance.CARVED_ORIGIN
                         if entry.get("RecoverySource")
                         else provenance.LIVE_ORIGIN)
    row.update({
        "TableName": table_name,
        "Domain": extract_domain(url),
        "Scheme": extract_scheme(entry.get("CleanUrl") or url),
        "UrlCategory": classify_url(url),
        "VisitCountBest": visit_best,
        "VisitCountBestSource": visit_source,
        "KeyTimestampUTC": filetime_to_rfc3339(key_raw),
        "KeyTimestampDesc": key_desc,
        "CreationTime_rfc": filetime_to_rfc3339(entry.get("CreationTime_raw")),
        "ModifiedTime_rfc": filetime_to_rfc3339(
            local_clock.utc_raw(entry, "ModifiedTime_raw")),
        "AccessedTime_rfc": filetime_to_rfc3339(entry.get("AccessedTime_raw")),
        "ExpiryTime_rfc": filetime_to_rfc3339(entry.get("ExpiryTime_raw")),
        "SyncTime_rfc": filetime_to_rfc3339(entry.get("SyncTime_raw")),
        "HttpStatus": status,
        "ContentType": content_type,
        "Server": server,
        "ResponseHeadersText": _flatten_headers(resp),
        "RequestHeadersText": _flatten_headers(req),
        "ResponseHeadersSize": len(entry["ResponseHeaders_raw"])
        if isinstance(entry.get("ResponseHeaders_raw"), bytes) else 0,
        "RequestHeadersSize": len(entry["RequestHeaders_raw"])
        if isinstance(entry.get("RequestHeaders_raw"), bytes) else 0,
        "SPS_PropertiesText": sps_text,
    })

    if tags_map is not None or comments_map is not None:
        # The record's key comes from the case file's own definition, so a
        # tag or comment on a carved artifact appears in every export as it
        # does on screen.
        #
        # Both key forms are looked up, so a case file written by an earlier
        # build still has its notes exported.
        keys = CaseDb.record_keys(entry)
        tags, comments = [], []
        for rk in keys:
            for tag in (tags_map or {}).get(rk, []):
                if tag not in tags:
                    tags.append(tag)
            comments.extend((comments_map or {}).get(rk, []))
        row["Tags"] = ", ".join(tags)
        row["Comments"] = " || ".join(
            c.get("comment", "") if isinstance(c, dict) else str(c) for c in comments)
    else:
        row.setdefault("Tags", "")
        row.setdefault("Comments", "")

    return row


def carved_inprivate(record):
    """True/False when a carved record's own Flags answer the InPrivate
    question, else None ("not determinable", never a guessed False).

    The live rule (ese_parser): bit 0x08, and only on a History record (on
    Content the same bit is EDITED_CACHE_ENTRY). A record whose Flags were
    not recovered (no key, None, or not an integer) makes no InPrivate
    claim, so the grid, the dialog, the value picker and every export state
    the same absence. Every carved-row builder calls this."""
    if (record.get("ContainerType") or "") != "History":
        return None
    flags = record.get("Flags")
    if flags is None or flags == "" or isinstance(flags, bool):
        return None
    try:
        return bool(int(flags) & 0x08)
    except (TypeError, ValueError):
        return None


def build_recovered_row(artifact: dict, tags_map: Optional[dict] = None,
                        comments_map: Optional[dict] = None) -> dict:
    """The canonical export row for one carved artifact or deleted-record
    stub, labelled the same way in every writer that emits carved rows
    (export_csv, export_sqlite).

    Built with build_entry_row(), the canonical builder, then the
    provenance columns build_entry_row leaves blank for a carved dict are
    filled: the artifact has RecoverySource rather than "Origin" or
    "Method" keys, so they are set here as recovery_loader.py labels a
    carved row for the screen. A stub (Url="", no *_raw timestamps) gives a
    row with an empty URL and timestamps; nothing is invented for it.
    """
    row = build_entry_row(artifact, tags_map, comments_map)
    nft = artifact.get("NearbyFiletime")
    if not row.get("KeyTimestampUTC") and nft:
        row["KeyTimestampUTC"] = nft
        row["KeyTimestampDesc"] = "Carved — nearby FILETIME context"
    row.setdefault("ContainerType", "Recovered")
    row.setdefault("Origin", provenance.CARVED_ORIGIN)
    # the same InPrivate answer the carved row shows on screen
    # (recovery_loader), from carved_inprivate -- a History record's Flags
    # bit, or the app's one absence wording where the Flags cannot answer.
    # Never blank beside the view's value, never a "No" the evidence does
    # not make.
    if row.get("IsInPrivate") is None:
        known = carved_inprivate(artifact)
        row["IsInPrivate"] = (provenance.ABSENCE_NOT_DETERMINABLE
                              if known is None else known)
    if not row.get("Method"):
        row["Method"] = artifact.get("RecoverySource") or ""
    return row


def canonical_record_row(record, carved=None, tags_map=None,
                         comments_map=None):
    """The canonical ENTRY_FIELDS row for one record, live or carved:
    what every view export and every location export appends after its
    own columns, so a record reads the same in all of them. `carved` None
    decides from the record itself (RecoverySource, which every carved
    artifact and stub carries, or a Carved Origin). `tags_map` and
    `comments_map` are the case file's, as every engine export receives
    them, so Tags and Analyst comments are filled."""
    record = record if isinstance(record, dict) else {}
    if carved is None:
        carved = (bool(record.get("RecoverySource"))
                  or str(record.get("Origin") or "").startswith("Carved"))
    if carved:
        return build_recovered_row(record, tags_map, comments_map)
    return build_entry_row(record, tags_map, comments_map)


def _as_int(value, default=0):
    """Best-effort integer. Damaged and carved records put strings, floats and
    nonsense in numeric columns; totals must survive that rather than raise."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# Control characters that are illegal in XLSX cells and that corrupt CSV and
# JSON output. Tab, newline and carriage return are deliberately kept.
_ILLEGAL_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
#: The two noncharacters XML (and so openpyxl) refuses outright. Written as
#: the same visible escape as a lone surrogate.
_NONCHARACTER = re.compile("[￾￿]")


#: Timestamps as this tool renders them for people: "2026-02-17T16:50:09Z",
#: "2026-07-06 23:59:59 UTC", "2026-02-14 05:47:51". Excel reads the first two
#: as TEXT -- a "T" separator, a trailing "Z", or a " UTC" suffix each stop it
#: recognising a date - so a column an analyst wants to sort or filter by time
#: arrives as strings, ordered alphabetically.
#:
#: Asked for directly: "if you export in excel, pls ensure excel date time
#: proper parseable thing".
#: Widest a spreadsheet column may be set. Wide enough for an ordinary URL
#: to be read without touching anything, narrow enough that one blob cannot
#: fill the screen. Only the VIEW is bounded -- no value is ever truncated
#: to fit it.
XLSX_MAX_COL_WIDTH = 80

_EXCEL_DT = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})"
    r"(\.\d+)?\s*(?:Z|UTC|LOCAL)?$")


def excel_datetime(value):
    """Normalise one cell to a shape a spreadsheet parses as a date-time.

    Only the shape changes: nothing is converted between zones or rounded.
    The clock is stated in every timestamp column's heading ("Last visit
    (UTC)", "Time (LOCAL)") and again in the provenance sidecar. Anything
    that is not a timestamp is returned unchanged, so a URL carrying digits
    is never altered.
    """
    text = str(value or "").strip()
    m = _EXCEL_DT.match(text)
    if not m:
        return value
    # Milliseconds are kept: a spreadsheet parses "2024-06-15 09:30:00.123"
    # as a date-time, and two records a few milliseconds apart are a
    # sequence that rounding to the second would make a tie.
    return "%s %s%s" % (m.group(1), m.group(2), m.group(3) or "")


#: The shape excel_datetime() leaves behind, re-read so a spreadsheet
#: writer can turn it into an actual date CELL. See excel_datetime_value.
_EXCEL_DT_CELL = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?$")

#: Two formats, because a value with milliseconds and one without are two
#: different precisions and the cell should say which it is.
EXCEL_DATE_FORMAT = "yyyy-mm-dd hh:mm:ss"
EXCEL_DATE_FORMAT_MS = "yyyy-mm-dd hh:mm:ss.000"


def excel_datetime_value(value):
    """(datetime, number_format) for a timestamp-shaped cell, else
    (None, "").

    The companion of excel_datetime(). openpyxl writes a Python str as a
    string cell, which a spreadsheet does not re-parse on open, so a
    normalised string would still sort alphabetically and offer no date
    filter. A writer puts this real datetime in the cell, with its format.

    Nothing is converted between zones or rounded: the same instant the
    string carried, as a date-time. Milliseconds are kept.

    Returns (None, "") for anything that is not a timestamp, so a URL
    carrying digits is never altered.
    """
    if isinstance(value, datetime):
        # Excel has no concept of a timezone-aware datetime and openpyxl
        # refuses one outright. The zone is stated in the column heading
        # and in the provenance sidecar, never in the cell.
        naked = value.replace(tzinfo=None)
        return naked, (EXCEL_DATE_FORMAT_MS if naked.microsecond
                       else EXCEL_DATE_FORMAT)
    if not isinstance(value, str):
        return None, ""
    m = _EXCEL_DT_CELL.match(value.strip())
    if not m:
        return None, ""
    year, month, day, hour, minute, second, fraction = m.groups()
    micro = int((fraction or "").ljust(6, "0") or 0) if fraction else 0
    try:
        parsed = datetime(int(year), int(month), int(day), int(hour),
                          int(minute), int(second), micro)
    except ValueError:
        # A damaged carve can produce a well-shaped impossible date
        # (month 13, day 32). Leaving it as the text it already is states
        # what the evidence holds; inventing a nearby valid date would not.
        return None, ""
    return parsed, (EXCEL_DATE_FORMAT_MS if fraction else EXCEL_DATE_FORMAT)


def _safe_text(value):
    """Make a string safe to write to any export format.

    Bytes carved from unallocated space regularly decode to lone surrogates or
    control characters. Both are legal Python strings, and both make UTF-8
    encoding (and openpyxl) raise. A report that cannot be written at all is
    worse than one that is marginally lossy, so substitute and carry on.
    """
    if not isinstance(value, str):
        return value
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        # Lone surrogates: written out as a visible, reversible \uD800.
        value = _LONE_SURROGATE.sub(
            lambda m: "\\u%04X" % ord(m.group()), value)
    value = _NONCHARACTER.sub(lambda m: "\\u%04X" % ord(m.group()), value)
    return _ILLEGAL_TEXT.sub(lambda m: "\\x%02X" % ord(m.group()), value)


def _safe_json(value):
    """_safe_text applied to every string inside a JSON-bound value --
    keys, values, nested lists and dicts -- so a lone surrogate carved out
    of a record cannot make json.dump raise and leave no file at all.
    Anything that is not a str, list, tuple or dict is returned as is."""
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, dict):
        return {_safe_json(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(v) for v in value]
    return value


@contextlib.contextmanager
def atomic_write(filepath, newline="", encoding="utf-8"):
    """Open a text file for writing that appears only once it is complete.

    Written beside the target and renamed on success, so an export that
    fails partway leaves no truncated file that could be mistaken for a
    complete one.
    """
    tmp = filepath + ".partial"
    try:
        with open(tmp, "w", newline=newline, encoding=encoding) as handle:
            yield handle
        os.replace(tmp, filepath)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


@contextlib.contextmanager
def atomic_path(filepath):
    """Same guarantee for writers that insist on opening the path themselves
    (openpyxl, reportlab). Yields the path to write to."""
    tmp = filepath + ".partial"
    try:
        yield tmp
        os.replace(tmp, filepath)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# Excel refuses a workbook with more than 255 sheets. The per-container split
# is a convenience view; the All Records sheet always holds everything.
CONTAINER_SHEET_LIMIT = 200


# FILETIME ticks per second (100-nanosecond units).
HUNDREDS_OF_NANOSECONDS = 10_000_000


def _pdf_visit_cell(entry):
    """Visit figure for the report, marked when it is only a cache touch.

    The property store counts user visits; the AccessCount column counts cache
    touches. A bare number in a court report would not distinguish them, so a
    fallback value is marked and the marker explained in the methodology.
    """
    value = entry.get("SPS_VisitCount")
    if value is not None:
        return str(value)
    value = entry.get("AccessCount")
    return "" if value is None else f"{value}*"


def local_filetime_to_utc_rfc3339(raw, offset_seconds):
    """Convert a FILETIME captured on the machine's local clock to UTC.

    Returns (text, converted). With no known offset the value is returned
    unconverted and flagged, so the caller labels it rather than marking a
    time that is not UTC with "Z".
    """
    if not raw:
        return "", False
    if not offset_seconds:
        return filetime_to_rfc3339(raw), False
    shifted = int(raw) - int(offset_seconds) * HUNDREDS_OF_NANOSECONDS
    if shifted <= 0:
        return filetime_to_rfc3339(raw), False
    return filetime_to_rfc3339(shifted), True


def collect_artifacts(parser) -> dict:
    """Gather every auxiliary artifact collection from a WebCacheParser, so
    exports cover the whole database rather than just container records."""
    return {
        "cookies": list(getattr(parser, "cookie_entries", []) or []),
        "hsts": list(getattr(parser, "hsts_entries", []) or []),
        "certs": list(getattr(parser, "cert_entries", []) or []),
        "leaks": list(getattr(parser, "leak_files", []) or []),
        "appcache": list(getattr(parser, "appcache_entries", []) or []),
        "containers": list(getattr(parser, "containers_meta", []) or []),
        "partitions": list(getattr(parser, "partitions", []) or []),
    }


def _cell(value):
    """Normalize any value into something every export backend accepts."""
    if value is None:
        return ""
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, bool):
        # "No", not blank: a blank IsInPrivate beside a view's own
        # InPrivate "No" read as "not recorded" for a value that is known.
        return "Yes" if value else "No"
    if isinstance(value, (bytes, bytearray)):
        # Full hex, never a prefix. Formats with a hard cell limit (XLSX)
        # handle it when writing, and say so.
        return value.hex().upper()
    if isinstance(value, (set, frozenset)):
        return ", ".join(str(v) for v in sorted(value))
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return _flatten_headers(value) or str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)  # "nan"/"inf"/"-inf": a text token, never a float cell
    if isinstance(value, datetime):
        # "Z" only on a true UTC instant. An aware value
        # is converted first; a naive one states no zone at all, since
        # nothing says it is UTC. Microseconds are kept.
        aware = value.tzinfo is not None and value.utcoffset() is not None
        if aware:
            value = value.astimezone(timezone.utc)
        text = value.strftime("%Y-%m-%dT%H:%M:%S")
        if value.microsecond:
            text += ".%06d" % value.microsecond
        return text + ("Z" if aware else "")
    return _safe_text(value) if isinstance(value, str) else value


def xlsx_cell_parts(raw, timestamp):
    """(value, number_format, force_text, text_len) for one xlsx cell,
    with every guard a workbook applies; used by both the in-memory writer
    (write_xlsx_cell) and the streamed view writer (write_simple_xlsx):
      * a value becomes a date only when its column is a timestamp column
        (`timestamp`), never because of its shape; a datetime keeps its
        microseconds (it goes to excel_datetime_value directly);
      * an int above 2**53 is written as text, since openpyxl writes ints
        as floats and above 2**53 that changes the value (UrlHash, raw
        FILETIMEs);
      * a string led by = + - @ is forced to a text cell: the cell type
        changes, never the stored value;
      * a string over the spreadsheet cell limit says how much is missing
        and where the whole value is.
    `number_format` is "" when the cell keeps the default format.
    """
    if timestamp and isinstance(raw, datetime):
        stamp, stamp_format = excel_datetime_value(raw)
        return stamp, stamp_format, False, len(stamp_format)
    val = _cell(excel_datetime(raw) if timestamp else raw)
    if isinstance(val, int) and not isinstance(val, bool) and abs(val) > 2 ** 53:
        val = str(val)
    text_len = len(val) if isinstance(val, str) else 0
    # A normalised string is still a string cell, which is not re-parsed on
    # open, so a real datetime is written. Gated like excel_datetime() above:
    # excel_datetime_value matches on shape alone.
    stamp, stamp_format = (excel_datetime_value(val)
                           if timestamp else (None, ""))
    if stamp is not None:
        return stamp, stamp_format, False, text_len
    if isinstance(val, str) and len(val) > 32000:
        # The spreadsheet cell limit is 32,767 characters, so the cell says
        # how much is missing and where the whole value is.
        val = (val[:32000] + f"…[TRUNCATED BY EXCEL: {len(val):,} "
               f"characters total, {len(val) - 32000:,} not shown. "
               "The complete value is in the CSV and JSON "
               "exports and in the app's blob viewer.]")
    # openpyxl only auto-infers "=" as a formula, but Excel/Sheets also
    # execute a cell opened with +, - or @, so all four leads are
    # neutralised the same way.
    force_text = isinstance(val, str) and val[:1] in ("=", "+", "-", "@")
    return val, "", force_text, text_len


def write_xlsx_cell(ws, r, c, raw, timestamp):
    """Write ONE value into an in-memory worksheet through
    xlsx_cell_parts' guards, and return (cell, length of its text for
    column sizing). Used by export_xlsx's write_table and Case Info sheet."""
    value, number_format, force_text, text_len = xlsx_cell_parts(raw, timestamp)
    cell = ws.cell(row=r, column=c, value=value)
    if force_text:
        cell.data_type = "s"
    if number_format:
        cell.number_format = number_format
    return cell, text_len


_XLSX_SHEET_FORBIDDEN = re.compile(r"[\[\]:*?/\\]")

#: How many leading rows size the columns of a streamed sheet. A
#: write-only sheet must declare its widths before its first row, so the
#: widths come from the headers and this bounded sample, never from a
#: second pass over every row.
XLSX_WIDTH_SAMPLE_ROWS = 200


_NEWLINE_TRANSLATED = []


def _writer_translates_newlines():
    """Whether openpyxl's standard-library writer turns a value's \\n into
    \\r\\n in the XML it writes (it does on Windows: a text-mode stream).
    Found by writing one tiny workbook, once, rather than assumed from the
    platform."""
    if not _NEWLINE_TRANSLATED:
        import io
        import zipfile
        from openpyxl import Workbook
        wb = Workbook(write_only=True)
        wb.create_sheet("S").append(["a\nb"])
        buf = io.BytesIO()
        wb.save(buf)
        with zipfile.ZipFile(buf) as z:
            sheet = next(n for n in z.namelist() if n.startswith("xl/worksheets/"))
            _NEWLINE_TRANSLATED.append(b"a\r\nb" in z.read(sheet))
    return _NEWLINE_TRANSLATED[0]


def _restore_carriage_returns(data, translated):
    """XML bytes with every carriage return that came from a value written
    as &#13;. Where the writer translated \\n to \\r\\n, that pair is its own
    and goes back to \\n first (a reader would fold it to \\n anyway)."""
    if translated:
        data = data.replace(b"\r\n", b"\n")
    return data.replace(b"\r", b"&#13;")


def keep_carriage_returns(path):
    """Make a carriage return in a saved workbook read back as written.

    openpyxl writes a value's \\r as the character reference &#13; only
    when lxml is installed, and the packaged build excludes lxml
    (packaging/webcache.spec). A raw \\r in XML is read back as \\n, so
    "line one\\r\\nline two\\r" would return as "line one\\n\\nline
    two\\n". Every raw \\r that is not the writer's own newline is
    restored as &#13;, member by member, streamed into a sibling file that
    replaces the original."""
    import shutil
    import zipfile
    from openpyxl.xml import LXML
    if LXML:
        return
    translated = _writer_translates_newlines()
    chunk_size = 1 << 20

    def holds_value_cr(src, info):
        with src.open(info) as fin:
            carry = b""
            for chunk in iter(lambda: fin.read(chunk_size), b""):
                data = carry + chunk
                carry = data[-1:] if data.endswith(b"\r") else b""
                body = data[:-1] if carry else data
                if b"\r" in (body.replace(b"\r\n", b"") if translated else body):
                    return True
            return bool(carry)

    with zipfile.ZipFile(path) as src:
        xml = [i for i in src.infolist() if i.filename.endswith(".xml")]
        if not any(holds_value_cr(src, info) for info in xml):
            return
        tmp = path + ".cr"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                with src.open(info) as fin, dst.open(info, "w") as fout:
                    if not info.filename.endswith(".xml"):
                        shutil.copyfileobj(fin, fout)
                        continue
                    carry = b""
                    for chunk in iter(lambda: fin.read(chunk_size), b""):
                        data = carry + chunk
                        # A \r ending this chunk may pair with a \n
                        # starting the next: hold it back one read.
                        carry = data[-1:] if data.endswith(b"\r") else b""
                        if carry:
                            data = data[:-1]
                        fout.write(_restore_carriage_returns(data, translated))
                    fout.write(_restore_carriage_returns(carry, translated))
    os.replace(tmp, path)


def write_simple_xlsx(filepath, sheet_title, headers, rows,
                      timestamp_columns=()):
    """One sheet: a bold header row, then `rows` (an iterable of cell
    lists), every cell through xlsx_cell_parts, with the same guards as the
    full workbook (dates only where the column says so, big ints as text,
    formula leads forced to text, the cell limit stated). Returns the
    number of data rows written.

    Streamed (openpyxl write_only): a normal workbook holds every cell
    until save, about 27 MB per 1,000 rows at 85 columns, so rows are
    written as they arrive and memory stays flat."""
    import itertools
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.utils import get_column_letter
    (Workbook, Font, _Fill, _Align, _Border, _Side) = _xlsx()
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(
        title=(_XLSX_SHEET_FORBIDDEN.sub(" ", str(sheet_title or "Sheet"))[:31]
               or "Sheet"))
    stamps = set(timestamp_columns)
    headers = list(headers)
    rows = iter(rows)
    sample = [[xlsx_cell_parts(raw, (ci in stamps)) for ci, raw in enumerate(cells)]
              for cells in itertools.islice(rows, XLSX_WIDTH_SAMPLE_ROWS)]
    longest = [len(str(h)) for h in headers]
    for parts in sample:
        for ci, part in enumerate(parts):
            if ci < len(longest):
                longest[ci] = max(longest[ci], part[3])
    for ci, width in enumerate(longest, 1):
        ws.column_dimensions[get_column_letter(ci)].width = \
            min(max(12, width + 2), XLSX_MAX_COL_WIDTH)
    ws.freeze_panes = "A2"
    bold = Font(bold=True)
    header_cells = []
    for header in headers:
        cell = WriteOnlyCell(ws, value=_cell(header))
        cell.font = bold
        header_cells.append(cell)
    ws.append(header_cells)

    def emit(parts):
        out = []
        for value, number_format, force_text, _len in parts:
            if not force_text and not number_format:
                # A plain cell needs no cell object, and a blank one is
                # not written at all (None) -- an empty string would be a
                # real, empty text cell costing the same as a full one.
                out.append(None if value == "" else value)
                continue
            cell = WriteOnlyCell(ws, value=value)
            if force_text:
                cell.data_type = "s"
            if number_format:
                cell.number_format = number_format
            out.append(cell)
        ws.append(out)

    written = 0
    for parts in sample:
        emit(parts)
        written += 1
    for cells in rows:
        emit([xlsx_cell_parts(raw, (ci in stamps))
              for ci, raw in enumerate(cells)])
        written += 1
    if written and headers:
        ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(headers)),
                                          written + 1)
    with atomic_path(filepath) as tmp:
        wb.save(tmp)
        keep_carriage_returns(tmp)
    return written




def _memo_url(fn):
    """Memoise a pure str -> str URL helper: the offline report's write
    would otherwise parse each record's URL three times over. An argument
    that cannot be hashed falls through to the plain function, unchanged."""
    cached = functools.lru_cache(maxsize=65536)(fn)

    @functools.wraps(fn)
    def wrapper(url):
        try:
            return cached(url)
        except TypeError:
            return fn(url)
    wrapper.cache_clear = cached.cache_clear
    wrapper.cache_info = cached.cache_info
    return wrapper


@_memo_url
def clean_url(url: str) -> str:
    """Strip the Windows history prefix from a stored URL.

    History URLs are stored as 'Visited: <user>@<url>' or
    ':<from><to>: <user>@<url>'. Only that leading account prefix is removed:
    an '@' inside the URL itself (userinfo, as in https://user:pw@host/path)
    must survive, or the scheme is destroyed and the record stops looking like
    a URL at all.
    """
    if not url:
        return ""
    cleaned = url.strip()

    # Leading MSHist date-range prefix, e.g. ':2026020920260216: '
    match = re.match(r"^:\d{8,}:\s*", cleaned)
    if match:
        cleaned = cleaned[match.end():]

    # 'Visited: ' prefix
    if cleaned.lower().startswith("visited:"):
        cleaned = cleaned[len("visited:"):].strip()

    # Account prefix: removed by the routine the carver uses, so a live
    # record and a carved reading of the same URL normalise alike. It
    # anchors on where the URL's scheme begins rather than on the account
    # name, since Windows account names can contain spaces, Unicode and
    # (for Microsoft accounts) an @.
    return strip_account_prefix(cleaned).strip()


# Schemes that genuinely address a remote host, so a hostname is meaningful.
_NETWORK_SCHEMES = ("http", "https", "ftp", "ftps", "ws", "wss")


@_memo_url
def extract_domain(url: str) -> str:
    """Hostname for a network URL, or a bracketed category for everything
    else.

    A URL with no host has no domain, so non-web records are labelled by
    what they are ([Local File], [App: ms-gamingoverlay], [Not a URL]),
    never by a hostname made from the path.
    """
    if not url:
        return ""
    try:
        cleaned = clean_url(url)
        if not cleaned:
            return ""

        scheme = ""
        if ":" in cleaned:
            head = cleaned.split(":", 1)[0].strip().lower()
            # A scheme is a bare token; anything else (e.g. ":Host: This PC")
            # is not a URL at all.
            if head and all(c.isalnum() or c in "+-." for c in head):
                scheme = head

        if scheme in _NETWORK_SCHEMES:
            host = urlparse(cleaned).netloc
            if host:
                # Strip any userinfo; keep the port, it can matter.
                if "@" in host:
                    host = host.rsplit("@", 1)[1]
                return host.lower()
            return "[Malformed URL]"

        if scheme == "file":
            return "[Local File]"
        if scheme == "res":
            return "[Resource]"
        if scheme == "about":
            return "[Browser Internal]"
        if scheme:
            # ms-appx, ms-gamingoverlay, ms-screenclip, x-…: a Windows app
            # protocol. Naming the scheme is informative; naming a fake host
            # is not.
            return f"[App: {scheme}]"
        return "[Not a URL]"
    except Exception:
        return "[Unparsable]"


def is_web_domain(domain: str) -> bool:
    """True when the value is a real hostname rather than a category label."""
    return bool(domain) and not domain.startswith("[")


@_memo_url
def extract_scheme(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return parsed.scheme or ""
    except Exception:
        return ""


@_memo_url
def classify_url(url: str) -> str:
    if not url:
        return "Empty"
    cleaned = clean_url(url)
    if not cleaned:
        return "Empty"
    if cleaned.startswith("file:///"):
        return "Local File Access"
    if cleaned.startswith("res://"):
        return "Resource Protocol"
    if cleaned.startswith("ms-appx"):
        return "Windows App"
    if cleaned.startswith("about:"):
        return "Browser Internal"
    scheme = extract_scheme(cleaned)
    if scheme in ("http", "https"):
        return "Web"
    if scheme == "ftp":
        return "FTP"
    return "Other"


class ForensicEngine:
    def __init__(self):
        self.entries = []

    def load_entries(self, entries: list):
        self.entries = entries

    # --- SEARCH & FILTER ---

    def search(
        self,
        keyword: str = "",
        container_type: str = "",
        url_category: str = "",
        domain_filter: str = "",
        date_from: str = "",
        date_to: str = "",
        inprivate_only: bool = False,
        min_access_count: int = 0,
        has_redirect: bool = False,
        regex_mode: bool = False,
    ) -> list:
        results = self.entries

        if keyword:
            if regex_mode:
                try:
                    pattern = re.compile(keyword, re.IGNORECASE)
                    results = [
                        e
                        for e in results
                        if pattern.search(e.get("Url", "") or "")
                        or pattern.search(e.get("Filename", "") or "")
                        or pattern.search(e.get("RedirectUrl", "") or "")
                        or pattern.search(e.get("ContainerName", "") or "")
                        or pattern.search(e.get("CachedFilePath", "") or "")
                    ]
                except re.error:
                    results = []
            else:
                kw = keyword.lower()
                results = [
                    e
                    for e in results
                    if kw in (e.get("Url", "") or "").lower()
                    or kw in (e.get("Filename", "") or "").lower()
                    or kw in (e.get("RedirectUrl", "") or "").lower()
                    or kw in (e.get("ContainerName", "") or "").lower()
                    # The resolved file path, so a secure subdirectory name
                    # can be searched for.
                    #
                    # CachedFilePath only, not CacheFolder: every record
                    # carries its container's folder, which contains the
                    # account name, so a search for that name would match
                    # every record.
                    or kw in (e.get("CachedFilePath", "") or "").lower()
                ]

        if container_type and container_type != "All":
            results = [e for e in results if e.get("ContainerType") == container_type]

        if url_category and url_category != "All":
            results = [e for e in results if classify_url(e.get("Url", "")) == url_category]

        if domain_filter:
            df = domain_filter.lower()
            results = [e for e in results if df in extract_domain(e.get("Url", "")).lower()]

        if date_from:
            try:
                dt_from = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                results = [
                    e
                    for e in results
                    if self._entry_date(e) and self._entry_date(e) >= dt_from
                ]
            except ValueError:
                pass

        if date_to:
            try:
                dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
                results = [
                    e
                    for e in results
                    if self._entry_date(e) and self._entry_date(e) <= dt_to
                ]
            except ValueError:
                pass

        if inprivate_only:
            results = [e for e in results if e.get("IsInPrivate")]

        if min_access_count > 0:
            results = [e for e in results if (e.get("AccessCount") or 0) >= min_access_count]

        if has_redirect:
            results = [e for e in results if e.get("RedirectUrl")]

        return results

    # Container metadata, when the caller has supplied it. Gap analysis uses
    # it to report each container's own scavenge time alongside its holes.
    _containers_meta = ()

    def set_containers_meta(self, containers_meta):
        """Give the engine the container table so findings can cite it."""
        self._containers_meta = list(containers_meta or ())

    def _entry_date(self, entry: dict) -> Optional[datetime]:
        """When this record happened, on the same basis as everything else:
        key_timestamp(), shared with the exports and the timeline, so a gap
        the analysis reports is a gap the timeline shows.
        """
        raw, _desc = key_timestamp(entry)
        return filetime_to_dt(raw) if raw else None

    # --- STATISTICS ---

    def get_statistics(self) -> dict:
        stats = {
            "total_entries": len(self.entries),
            "container_types": Counter(),
            "url_categories": Counter(),
            "top_domains": Counter(),
            "inprivate_count": 0,
            "entries_with_redirect": 0,
            "total_file_size": 0,
            "avg_access_count": 0,
            "entries_by_hour": Counter(),
            "entries_by_date": Counter(),
            "file_extensions": Counter(),
            "http_status_codes": Counter(),
            "schemes": Counter(),
        }

        access_counts = []

        for e in self.entries:
            # Container types
            stats["container_types"][e.get("ContainerType", "Unknown")] += 1

            # URL categories
            url = e.get("Url", "") or ""
            stats["url_categories"][classify_url(url)] += 1

            # Domains
            domain = extract_domain(url)
            if domain:
                stats["top_domains"][domain] += 1

            # InPrivate
            if e.get("IsInPrivate"):
                stats["inprivate_count"] += 1

            # Redirects
            if e.get("RedirectUrl"):
                stats["entries_with_redirect"] += 1

            # File size
            stats["total_file_size"] += _as_int(e.get("FileSize"))

            # Access count
            access_counts.append(_as_int(e.get("AccessCount")))

            # Hourly distribution
            dt = self._entry_date(e)
            if dt:
                stats["entries_by_hour"][dt.hour] += 1
                stats["entries_by_date"][dt.strftime("%Y-%m-%d")] += 1

            # File extensions
            ext = e.get("FileExtension", "") or ""
            if ext:
                stats["file_extensions"][ext.lower()] += 1

            # HTTP status codes from response headers
            resp = e.get("ResponseHeaders", {})
            if isinstance(resp, dict):
                status_line = resp.get("_status_line", "")
                if status_line:
                    parts = status_line.split(" ", 2)
                    if len(parts) >= 2:
                        stats["http_status_codes"][parts[1]] += 1

            # Schemes
            scheme = extract_scheme(url)
            if scheme:
                stats["schemes"][scheme] += 1

        if access_counts:
            stats["avg_access_count"] = round(sum(access_counts) / len(access_counts), 2)

        return stats

    # --- TIMELINE ---

    def get_timeline(self, group_by: str = "hour", records=None,
                     offset_seconds: int = 0, offset_for=None) -> list:
        """Activity grouped into periods.

        `records` lets a caller time-line something other than the live table
        -- specifically live PLUS carved. A deleted record that still carries
        a timestamp is evidence of something happening at that moment, and
        leaving it out understates the activity it is there to show.

        `offset_seconds` groups on the machine's LOCAL clock (UTC + that
        zone) instead of UTC; `offset_for(entry)` -> seconds | None lets a
        caller give each record ITS OWN offset (a zone that observes
        daylight saving has two), falling back to `offset_seconds`. Every
        record's instant is the same either way.
        """
        timeline = defaultdict(list)
        default_shift = timedelta(seconds=offset_seconds or 0)

        for e in (self.entries if records is None else records):
            dt = self._entry_date(e)
            if not dt:
                continue
            own = offset_for(e) if offset_for is not None else None
            dt = dt + (default_shift if own is None
                       else timedelta(seconds=own))

            if group_by == "minute":
                key = dt.strftime("%Y-%m-%d %H:%M")
            elif group_by == "hour":
                key = dt.strftime("%Y-%m-%d %H:00")
            elif group_by == "day":
                key = dt.strftime("%Y-%m-%d")
            elif group_by == "month":
                key = dt.strftime("%Y-%m")
            else:
                key = dt.strftime("%Y-%m-%d %H:00")

            timeline[key].append(e)

        result = []
        for key in sorted(timeline.keys()):
            result.append({"period": key, "count": len(timeline[key]), "entries": timeline[key]})

        return result

    # --- DOMAIN ANALYSIS ---

    def get_domain_analysis(self, records=None) -> list:
        """Per-domain profile.

        `records` lets a caller profile something other than the live table,
        such as live plus carved records: a domain that appears only in
        deleted records is still a domain the machine contacted.
        """
        domain_data = defaultdict(lambda: {
            "count": 0,
            "total_size": 0,
            "first_seen": None,
            "last_seen": None,
            "container_types": set(),
            "access_counts": [],
            "has_inprivate": False,
        })

        for e in (self.entries if records is None else records):
            url = e.get("Url", "") or ""
            domain = extract_domain(url)
            if not domain:
                continue

            d = domain_data[domain]
            d["count"] += 1
            d["total_size"] += _as_int(e.get("FileSize"))
            # A carved record often has no container type (the catalogue
            # entry that named it was destroyed), so it is stated rather
            # than recorded as an empty string.
            d["container_types"].add(
                e.get("ContainerType") or "Carved (type unknown)")
            d["access_counts"].append(_as_int(e.get("AccessCount")))
            if e.get("IsInPrivate"):
                d["has_inprivate"] = True

            dt = self._entry_date(e)
            if dt:
                if d["first_seen"] is None or dt < d["first_seen"]:
                    d["first_seen"] = dt
                if d["last_seen"] is None or dt > d["last_seen"]:
                    d["last_seen"] = dt

        result = []
        for domain, d in domain_data.items():
            result.append({
                "domain": domain,
                "count": d["count"],
                "total_size": d["total_size"],
                "first_seen": d["first_seen"].strftime("%Y-%m-%d %H:%M:%S") if d["first_seen"] else "",
                "last_seen": d["last_seen"].strftime("%Y-%m-%d %H:%M:%S") if d["last_seen"] else "",
                "container_types": ", ".join(sorted(d["container_types"])),
                "avg_access": round(sum(d["access_counts"]) / len(d["access_counts"]), 1) if d["access_counts"] else 0,
                "has_inprivate": d["has_inprivate"],
            })

        result.sort(key=lambda x: x["count"], reverse=True)
        return result

    # --- EXPORT ---

    def export_csv(self, entries: list, filepath: str, tags_map=None,
                   comments_map=None, recovered=None):
        """Flat CSV of every canonical field (see ENTRY_FIELDS), live and
        carved rows alike. Carved rows, deleted-record stubs included, are
        labelled by the Origin/Source/Offset/Page/Method/Confidence columns
        through build_recovered_row(), as in export_sqlite, never mixed
        unlabelled into the live set. Timestamp columns are gated on
        TIMESTAMP_EXPORT_KEYS (shared with export_xlsx), so a cell reads
        "2024-06-15 09:30:00" rather than "2024-06-15 09:30:00 UTC", a shape
        a spreadsheet parses as a date-time."""
        with atomic_write(filepath, encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(ENTRY_FIELD_HEADERS)
            for e in entries:
                row = build_entry_row(e, tags_map, comments_map)
                writer.writerow([_cell(excel_datetime(row.get(k))
                                       if k in TIMESTAMP_EXPORT_KEYS else row.get(k))
                                 for k in ENTRY_FIELD_KEYS])
            for a in (recovered or ()):
                row = build_recovered_row(a, tags_map, comments_map)
                writer.writerow([_cell(excel_datetime(row.get(k))
                                       if k in TIMESTAMP_EXPORT_KEYS else row.get(k))
                                 for k in ENTRY_FIELD_KEYS])

    def export_json(self, entries: list, filepath: str, case_meta=None,
                    db_info=None, artifacts=None, recovered=None,
                    tags_map=None, comments_map=None):
        """Complete structured export: provenance header, every entry field,
        every auxiliary artifact collection, recovered records, and analytics.

        `artifacts` is the dict returned by collect_artifacts()."""
        artifacts = artifacts or {}

        def _jsonable(value):
            if isinstance(value, str):
                return _safe_text(value)
            if isinstance(value, (bytes, bytearray)):
                return value.hex()
            if isinstance(value, (set, frozenset)):
                return sorted(str(v) for v in value)
            if isinstance(value, datetime):
                return value.strftime("%Y-%m-%dT%H:%M:%SZ")
            return value

        def _clean_list(rows, drop_raw_blobs=True):
            out = []
            for r in rows or []:
                item = {}
                for k, v in r.items():
                    if drop_raw_blobs and k in ("Blob_raw", "RequestHeaders_raw",
                                                "ResponseHeaders_raw"):
                        item[k + "_size"] = len(v) if isinstance(v, bytes) else 0
                        continue
                    item[k] = _jsonable(v)
                out.append(item)
            return out

        void_report = {}
        payload = {
            "report": self.build_report_header(case_meta or {}, db_info or {}),
            "schema": {
                "entry_fields": [
                    {"key": k, "header": h, "group": g,
                     "basis": em.basis_of(k),
                     "meaning": (em.get(k) or {}).get("meaning", ""),
                     "caveat": (em.get(k) or {}).get("caveat", ""),
                     "attribution": (em.get(k) or {}).get("citation", "")}
                    for k, h, g in ENTRY_FIELDS],
                "timestamp_policy": ("All timestamps UTC unless the field name "
                                     "says LOCAL. SPS id24 is machine-local."),
            },
            "counts": {
                "entries": len(entries),
                "recovered": len(recovered or []),
                **{k: len(v or []) for k, v in artifacts.items()
                   if isinstance(v, list)},
            },
            "entries": _clean_list(
                [build_entry_row(e, tags_map, comments_map) for e in entries]),
            "cookies": _clean_list(artifacts.get("cookies")),
            "hsts": _clean_list(artifacts.get("hsts")),
            "certificates": _clean_list(artifacts.get("certs")),
            "leak_files": _clean_list(artifacts.get("leaks")),
            "appcache": _clean_list(artifacts.get("appcache")),
            "containers": _clean_list(artifacts.get("containers")),
            "partitions": _clean_list(artifacts.get("partitions")),
            "recovered_artifacts": _clean_list(recovered),
            "analytics": {
                "entryid_gaps": self.analyze_entryid_gaps(
                    (artifacts or {}).get("containers")),
                "time_voids": self.analyze_time_voids(report=void_report),
                # Silences withheld because an MSHist visit with no
                # recovered zone may fall inside them (see
                # analyze_time_voids); stated, not dropped.
                "time_voids_withheld": void_report,
                "beaconing": self.detect_beaconing(),
                "domains": self.get_domain_analysis(),
            },
        }
        with atomic_write(filepath) as f:
            json.dump(payload, f, indent=2, default=str, ensure_ascii=False)

    def export_xlsx(self, entries: list, filepath: str, container_wise: bool = True,
                    case_meta=None, db_info=None, artifacts=None, recovered=None,
                    tags_map=None, comments_map=None, stats=None):
        """Full forensic workbook.

        Sheets: Case Info · Summary · All Records (every canonical field) ·
        History · Downloads & File Access · Cookies · HSTS · Certificates ·
        Leak Files · Containers · Partitions · Recovered · EntryId Gaps ·
        Domains · per-container record sheets.
        """
        if not HAS_OPENPYXL:
            raise RuntimeError("openpyxl not installed. Run: pip install openpyxl")
        # Imported here, not at module scope: see _xlsx's own note on what
        # that cost every launch.
        (Workbook, Font, PatternFill, Alignment, Border, Side) = _xlsx()

        artifacts = artifacts or {}
        wb = Workbook()
        header_font = Font(bold=True, color="FFFFFF", size=10)
        header_fill = PatternFill(start_color="0B5345", end_color="0B5345",
                                  fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center",
                                 wrap_text=True)
        title_font = Font(bold=True, size=12, color="0B5345")
        thin = Side(style="thin", color="BBBBBB")
        thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
        priv_fill = PatternFill(start_color="FFE0E0", end_color="FFE0E0",
                                fill_type="solid")

        used_names = set()

        def sheet(title, index=None):
            safe = re.sub(r"[\\/*?\[\]:]", "_", title)[:31] or "Sheet"
            base, n = safe, 2
            while safe in used_names:
                suffix = f"_{n}"
                safe = base[:31 - len(suffix)] + suffix
                n += 1
            used_names.add(safe)
            if index is not None:
                return wb.create_sheet(title=safe, index=index)
            return wb.create_sheet(title=safe)

        # Which columns get date-converted: the module-level
        # TIMESTAMP_EXPORT_KEYS (also used by export_csv), not a local copy --
        # a value becomes a date because its COLUMN says so, never because it
        # happens to parse as one.
        _TIMESTAMP_KEYS = TIMESTAMP_EXPORT_KEYS

        _write_cell = write_xlsx_cell

        def write_table(ws, columns, rows, highlight_key=None, freeze=True,
                        timestamps=()):
            """columns: list of (key, header). rows: list of dicts.
            `timestamps` names keys that are dates in THIS table only: the
            same KeyTimestampUTC is RFC3339 text under an "(RFC3339 UTC)"
            heading in All Records and a date under "Visit (UTC)" here."""
            stamp_keys = _TIMESTAMP_KEYS | frozenset(timestamps)
            for ci, (_, header) in enumerate(columns, 1):
                c = ws.cell(row=1, column=ci, value=header)
                c.font = header_font
                c.fill = header_fill
                c.alignment = header_align
                c.border = thin_border
            # Longest value seen per column, so the width can be set from the
            # CONTENT rather than from the heading alone. Sampled while the
            # rows are being written, which costs one len() per cell instead
            # of a second pass over the sheet.
            longest = [0] * len(columns)
            for ri, row in enumerate(rows, 2):
                flagged = bool(highlight_key and row.get(highlight_key))
                for ci, (key, _) in enumerate(columns, 1):
                    # A spreadsheet parses "2024-06-15 09:30:00.123" but not
                    # "... UTC": the zone label makes the cell text, so the
                    # column would sort alphabetically and offer no date
                    # filter. The clock is stated in each heading ("Last
                    # visit (UTC)") and in the provenance sidecar.
                    # Milliseconds are kept. A value is a timestamp because
                    # its column says so, as export_formats._clean() applies
                    # to the CSV.
                    c, text_len = _write_cell(ws, ri, ci, row.get(key),
                                              key in stamp_keys)
                    longest[ci - 1] = max(longest[ci - 1], text_len)
                    c.border = thin_border
                    if flagged:
                        c.fill = priv_fill
            if rows:
                ws.auto_filter.ref = ws.dimensions
            if freeze:
                ws.freeze_panes = "A2"
            # Width from the content as well as the heading, so a short
            # heading over long values gives a readable column.
            #
            # Capped at XLSX_MAX_COL_WIDTH, which shows a whole URL in the
            # ordinary case; a very long value (a ResponseHeaders blob) wraps
            # instead. The value is never truncated, only its display.
            for ci, (_, header) in enumerate(columns, 1):
                width = min(max(12, len(str(header)) + 4, longest[ci - 1] + 2),
                            XLSX_MAX_COL_WIDTH)
                ws.column_dimensions[ws.cell(row=1, column=ci).column_letter].width = width
            return ws

        # ---------- 1. Case Info ----------
        header = self.build_report_header(case_meta or {}, db_info or {})
        ws = wb.active
        ws.title = "Case Info"
        used_names.add("Case Info")
        ws.cell(row=1, column=1, value="WebCache Forensic Analyzer — Case Report").font = title_font
        info_rows = [
            ("Examiner", header["examiner"]), ("Case number", header["case_number"]),
            ("Evidence ID", header["evidence_id"]), ("Notes", header["notes"]),
            ("", ""),
            ("Evidence source", header["evidence_source"]),
            ("Evidence SHA-256", header["evidence_sha256"]),
            ("Database state", header["database_state"]),
            ("Derived machine timezone", header["derived_machine_timezone"]),
            ("", ""),
            ("Tool", header["tool"]), ("Parser backend", header["parser_backend"]),
            ("Generated (UTC)", header["generated_utc"]),
            ("Timezone policy", header["timezone_policy"]),
            ("", ""),
            ("Records exported", len(entries)),
            ("Recovered artifacts", len(recovered or [])),
        ]
        ps = header.get("parsing_statistics") or {}
        for k, v in ps.items():
            info_rows.append((f"Parsing: {k}", v))
        info_rows.append(("", ""))
        for fn, hx in sorted((header.get("related_file_hashes") or {}).items()):
            info_rows.append((f"SHA-256 {fn}", hx))
        for ri, (k, v) in enumerate(info_rows, 3):
            kc = ws.cell(row=ri, column=1, value=k)
            kc.font = Font(bold=True, size=9)
            # Case Info is written key by key rather than through
            # write_table, so it uses the same _write_cell guards. Only
            # "Generated (UTC)" is a timestamp; the free-text Examiner, Case
            # number and Notes fields are never converted to dates or written
            # as formulas.
            _write_cell(ws, ri, 2, v, k == "Generated (UTC)")
        # Wide enough for the sheet's title in A1, which is longer than any
        # key beneath it.
        ws.column_dimensions["A"].width = max(
            32, len(str(ws.cell(row=1, column=1).value or "")) + 2)
        ws.column_dimensions["B"].width = 100

        # ---------- 2. Summary ----------
        stats = stats or self.get_statistics()
        ws = sheet("Summary", index=1)
        summary_rows = [{"Metric": "Total records", "Value": len(entries)}]
        for name, counter in (("Container type", stats.get("container_types")),
                              ("URL category", stats.get("url_categories")),
                              ("Scheme", stats.get("schemes"))):
            for k, v in (counter or Counter()).most_common():
                summary_rows.append({"Metric": f"{name}: {k}", "Value": v})
        summary_rows += [
            {"Metric": "InPrivate records", "Value": stats.get("inprivate_count", 0)},
            {"Metric": "Records with redirect", "Value": stats.get("entries_with_redirect", 0)},
            {"Metric": "Local file (file:///) records",
             "Value": sum(1 for e in entries if e.get("IsLocalFile"))},
            {"Metric": "Records with search terms",
             "Value": sum(1 for e in entries if e.get("SearchTerms"))},
            {"Metric": "Total cached size (bytes)", "Value": stats.get("total_file_size", 0)},
            {"Metric": "Cookies", "Value": len(artifacts.get("cookies") or [])},
            {"Metric": "HSTS pins", "Value": len(artifacts.get("hsts") or [])},
            {"Metric": "TLS certificates", "Value": len(artifacts.get("certs") or [])},
            {"Metric": "Leak files", "Value": len(artifacts.get("leaks") or [])},
            {"Metric": "Recovered artifacts", "Value": len(recovered or [])},
        ]
        write_table(ws, [("Metric", "Metric"), ("Value", "Value")], summary_rows)
        ws.column_dimensions["A"].width = 44

        # ---------- 3. All Records (every field) ----------
        full_rows = [build_entry_row(e, tags_map, comments_map) for e in entries]
        write_table(sheet("All Records"), list(zip(ENTRY_FIELD_KEYS, ENTRY_FIELD_HEADERS)),
                    full_rows, highlight_key="IsInPrivate")

        # ---------- 4. Focused views ----------
        hist = [r for r in full_rows if r.get("ContainerType") == "History"]
        if hist:
            hist_cols = [("KeyTimestampUTC", "Visit (UTC)"),
                         ("SPS_LastVisitLocal", "Last visit (LOCAL)"),
                         ("VisitCountBest", "Visits"), ("CleanUrl", "URL"),
                         ("SearchTerms", "Search terms"), ("SPS_PageTitle", "Page title"),
                         ("IsInPrivate", "InPrivate"), ("IsLocalFile", "Local file"),
                         ("Domain", "Domain"), ("UrlUsername", "User"),
                         ("Tags", "Tags"), ("Comments", "Comments")]
            # Ordered by the UTC instant, never the stored FILETIME: an
            # MSHist record's ModifiedTime is local wall-clock
            # (engine/local_clock.py) and would sort hours off its twin.
            write_table(sheet("History"), hist_cols,
                        sorted(hist, key=lambda r: local_clock.utc_raw(
                            r, "ModifiedTime_raw"), reverse=True),
                        highlight_key="IsInPrivate",
                        timestamps=("KeyTimestampUTC",))

        dl = [r for r in full_rows if r.get("DownloadPath") or r.get("IsLocalFile")]
        if dl:
            write_table(sheet("Downloads & Files"), [
                ("DownloadPath", "Saved to"), ("CleanUrl", "URL / file path"),
                ("DownloadSourceUrl", "Source URL"), ("DownloadSize", "Download size"),
                ("DownloadTime", "Download time (UTC)"), ("FileSize", "Cached size"),
                ("Filename", "Cached filename"),
                ("KeyTimestampUTC", "Last activity (UTC)"),
                ("VisitCountBest", "Opens")], dl,
                timestamps=("KeyTimestampUTC",))

        # ---------- 5. Auxiliary artifact tables ----------
        for title, cols, rows in (
                ("Cookies", COOKIE_FIELDS, artifacts.get("cookies")),
                ("HSTS", HSTS_FIELDS, artifacts.get("hsts")),
                ("Certificates", CERT_FIELDS, artifacts.get("certs")),
                ("Leak Files", LEAK_FIELDS, artifacts.get("leaks")),
                ("Containers", CONTAINER_FIELDS, artifacts.get("containers")),
                ("Partitions", PARTITION_FIELDS, artifacts.get("partitions"))):
            if rows:
                write_table(sheet(title), cols, rows)

        # ---------- 6. Recovered ----------
        if recovered:
            rec_rows = []
            for a in recovered:
                r = dict(a)
                nft = a.get("NearbyFiletime")
                r["NearbyFiletimeRfc"] = (nft.strftime("%Y-%m-%dT%H:%M:%SZ")
                                          if nft else "")
                r["Domain"] = extract_domain(a.get("Url", "") or "")
                rec_rows.append(r)
            write_table(sheet("Recovered"), RECOVERED_FIELDS, rec_rows)

        # ---------- 7. Analytics ----------
        gaps = self.analyze_entryid_gaps(self._containers_meta)
        if gaps:
            write_table(sheet("EntryId Gaps"), [
                ("ContainerId", "ContainerId"), ("ContainerName", "Container"),
                ("ContainerType", "Type"), ("FirstEntryId", "First EntryId"),
                ("LastEntryId", "Last EntryId"), ("LiveRecords", "Live records"),
                ("MissingRecords", "Missing (deleted)"), ("GapRuns", "Gap runs")], gaps)

        domains = self.get_domain_analysis()
        if domains:
            write_table(sheet("Domains"), [
                ("domain", "Domain"), ("count", "Records"),
                ("total_size", "Total size"), ("first_seen", "First seen"),
                ("last_seen", "Last seen"), ("container_types", "Container types"),
                ("avg_access", "Avg visits"), ("has_inprivate", "Has InPrivate")],
                domains)

        beacons = self.detect_beaconing()
        if beacons:
            write_table(sheet("Beaconing"), [
                ("Domain", "Domain"), ("Events", "Events"),
                ("MeanIntervalSec", "Mean interval (s)"), ("IntervalCV", "Jitter (CV)"),
                ("FirstSeen", "First seen"), ("LastSeen", "Last seen")], beacons)

        # ---------- 8. Per-container sheets ----------
        if container_wise:
            by_container = defaultdict(list)
            for r in full_rows:
                by_container[f"{r.get('ContainerId')}_{r.get('ContainerName', '')}"].append(r)
            ordered = sorted(by_container.items(), key=lambda kv: -len(kv[1]))
            # Excel tops out at 255 sheets, so a per-container breakdown of a
            # large database cannot be unbounded. Every record is still on the
            # full sheet with all 69 fields; what is bounded here is only the
            # convenience split — and if any of it is left out, the workbook
            # says so rather than looking complete.
            shown = ordered[:CONTAINER_SHEET_LIMIT]
            for name, rows in shown:
                write_table(sheet(f"C{name}"),
                            list(zip(ENTRY_FIELD_KEYS, ENTRY_FIELD_HEADERS)),
                            rows, highlight_key="IsInPrivate")
            if len(ordered) > len(shown):
                omitted = ordered[len(shown):]
                write_table(
                    sheet("Sheets not split out"),
                    [("Container", "Container"), ("Records", "Records"),
                     ("Where", "Where to find these records")],
                    [{"Container": name, "Records": len(rows),
                      "Where": "All Records sheet (complete, all fields)"}
                     for name, rows in omitted])

        with atomic_path(filepath) as tmp:
            wb.save(tmp)
            keep_carriage_returns(tmp)

    # --- FORENSIC ANALYTICS ---

    def analyze_entryid_gaps(self, containers_meta=None,
                             extra_entries=None) -> list:
        """EntryIds absent from each container's sequence.

        ESE assigns EntryIds sequentially, so a hole means an ID was issued
        and the record that held it is not in the live table. It does not
        establish why. At least three things produce the same hole:

          * the record was deleted, by the user or by an application;
          * the container was scavenged: routine automatic cache turnover,
            which is how these containers normally shed old entries;
          * an ID was consumed by a transaction that never committed.

        This returns the observation with the container's scavenge and
        access times, so a reader can weigh those explanations; it does not
        pick one. A container with a few live records and thousands of
        missing IDs usually shows cache turnover, not thousands of
        deletions.
        """
        # How many of the absent IDs the carve recovered, per container, so
        # the finding states which part of the hole this tool holds and can
        # show.
        #
        # EntryId is unique only within a container, so this is indexed by
        # container.
        recovered_by_container = defaultdict(set)
        for art in (extra_entries or []):
            cid, eid = art.get("ContainerId"), art.get("EntryId")
            if cid in (None, "") or eid in (None, ""):
                continue
            try:
                recovered_by_container[cid].add(int(eid))
            except (TypeError, ValueError):
                continue

        meta_by_id = {m.get("ContainerId"): m for m in (containers_meta or [])}
        by_container = defaultdict(list)
        for e in self.entries:
            eid = e.get("EntryId")
            if eid:
                by_container[(e.get("ContainerId"), e.get("ContainerName", ""),
                              e.get("ContainerType", ""))].append(int(eid))
        results = []
        for (cid, cname, ctype), eids in by_container.items():
            eids = sorted(set(eids))
            if len(eids) < 2:
                continue
            missing = (eids[-1] - eids[0] + 1) - len(eids)
            runs = []
            for a, b in zip(eids, eids[1:]):
                if b - a > 1:
                    runs.append((a + 1, b - 1))
            if missing > 0:
                meta = meta_by_id.get(cid, {})
                live_ids = set(eids)
                got_back = sorted(
                    i for i in recovered_by_container.get(cid, ())
                    if eids[0] <= i <= eids[-1] and i not in live_ids)
                results.append({
                    "ContainerId": cid, "ContainerName": cname, "ContainerType": ctype,
                    "FirstEntryId": eids[0], "LastEntryId": eids[-1],
                    "LiveRecords": len(eids), "MissingEntryIds": missing,
                    # Of the missing IDs, how many the carve recovered.
                    "RecoveredEntryIds": len(got_back),
                    # Also kept under the previous key, which exports and
                    # case files written by earlier builds read.
                    "MissingRecords": missing,
                    "GapRuns": len(runs),
                    "LargestGaps": sorted(runs, key=lambda r: r[1] - r[0],
                                          reverse=True)[:5],
                    # Context a reader needs before calling a hole a deletion.
                    "LastScavengeTime": meta.get("LastScavengeTime", ""),
                    "LastAccessTime": meta.get("LastAccessTime", ""),
                    "ContainerRecordCount": meta.get("RecordCount", ""),
                    "Interpretation": ENTRYID_GAP_INTERPRETATION,
                })
        results.sort(key=lambda r: r["MissingRecords"], reverse=True)
        return results

    def analyze_time_voids(self, min_gap_hours: float = 24.0,
                           extra_entries=None, report=None) -> list:
        """Periods with no recorded activity inside an otherwise active span.

        A silence is an observation about the records, not about the person.
        The machine may have been off, the account not in use, another
        browser used, or the records for that period removed. This reports
        where the silences are and how long they ran; it does not choose
        between those, and a gap is not by itself evidence of history
        clearing.

        `extra_entries` is every other record that carries a time, in
        practice the carved ones. The engine is loaded once, at open, with
        the live entries, and the recovery scan runs later; without the
        carved records a silence could be reported across a window from
        which this tool recovered activity.

        The same applies to an MSHist visit stored in LOCAL time with no
        recovered zone (engine/local_clock.py): its true instant lies within
        [local - 14 h, local + 12 h] (every offset a zone has used), so a
        silence overlapping that window may hold it and is withheld.
        `report`, when given, is filled with how many such records there
        were and how many silences they withheld, so the exclusion is stated
        wherever the silences are.
        """
        records = list(self.entries) + list(extra_entries or [])
        dts = sorted(d for d in (self._entry_date(e) for e in records) if d)
        windows = []
        for e in records:
            if local_clock.is_unplaced(e):
                local = local_clock.local_naive(e).replace(tzinfo=timezone.utc)
                windows.append((local - timedelta(hours=14),
                                local + timedelta(hours=12)))
        withheld = 0
        if report is not None:
            report.clear()
            report.update(unplaced_records=len(windows), withheld_voids=0)
        if len(dts) < 10:
            return []
        voids = []
        for a, b in zip(dts, dts[1:]):
            gap_h = (b - a).total_seconds() / 3600.0
            if gap_h >= min_gap_hours:
                if any(lo < b and hi > a for lo, hi in windows):
                    withheld += 1
                    continue
                voids.append({
                    "From": a.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "To": b.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "GapHours": round(gap_h, 1),
                })
        voids.sort(key=lambda v: v["GapHours"], reverse=True)
        if report is not None:
            report["withheld_voids"] = withheld
        return voids

    def detect_beaconing(self, min_events: int = 6, max_cv: float = 0.35) -> list:
        """Beaconing/C2 heuristic: domains contacted at low-jitter regular
        intervals. CV = stddev/mean of inter-request intervals."""
        by_domain = defaultdict(list)
        for e in self.entries:
            dt = self._entry_date(e)
            if not dt:
                continue
            dom = extract_domain(e.get("Url", "") or "")
            if dom and not dom.startswith("["):
                by_domain[dom].append(dt)
        results = []
        for dom, times in by_domain.items():
            times = sorted(set(times))
            if len(times) < min_events:
                continue
            intervals = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
            intervals = [i for i in intervals if i > 1]
            if len(intervals) < min_events - 1:
                continue
            mean = statistics.mean(intervals)
            if not (5 <= mean <= 86400):
                continue
            cv = statistics.pstdev(intervals) / mean if mean else 99
            if cv <= max_cv:
                results.append({
                    "Domain": dom, "Events": len(times),
                    "MeanIntervalSec": round(mean, 1),
                    "IntervalCV": round(cv, 3),
                    "FirstSeen": times[0].strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "LastSeen": times[-1].strftime("%Y-%m-%d %H:%M:%S UTC"),
                })
        results.sort(key=lambda r: r["IntervalCV"])
        return results

    def match_iocs(self, watchlist: Optional[list] = None,
                   extra_entries: Optional[list] = None) -> list:
        """Entries matching the examiner's watchlist or a built-in rule.

        Two built-in rules fire without a watchlist: a domain registered
        under a registry with elevated abuse rates, and a .onion address.
        Neither is a finding on its own (the first matches ordinary
        legitimate sites), so every hit carries the basis on which its rule
        fired, for a report to quote.

        watchlist: iterable of domains/keywords (case-insensitive
            substrings).
        extra_entries: carved records, which this engine does not otherwise
            see (it is loaded once, at open, from the live tables). A deleted
            URL matters as much as a surviving one in a search. Each hit
            reports which set it came from.
        """
        terms = []
        for raw in (watchlist or []):
            if raw is None:
                continue
            term = str(raw).strip().lower()
            if term and not term.startswith("#"):
                terms.append(term)
        hits = []
        pool = [(e, False) for e in self.entries]
        pool += [(e, True) for e in (extra_entries or [])]
        for e, is_carved in pool:
            url = (e.get("CleanUrl") or e.get("Url") or "").lower()
            if not url:
                continue
            dom = extract_domain(e.get("Url", "") or "").lower()
            reasons = []
            for t in terms:
                if t in url:
                    reasons.append(f"watchlist:{t}")
            # onion is reported by its own rule below, so the registry
            # rule does not also claim it.
            for tld in ELEVATED_ABUSE_TLDS:
                if dom.endswith(tld):
                    reasons.append(f"tld-elevated-abuse:{tld}")
            if dom.endswith(".onion"):
                reasons.append("tor-onion")
            if reasons:
                reasons = sorted(set(reasons))
                hits.append({
                    "entry": e,
                    "carved": is_carved,
                    "reasons": reasons,
                    # Why each rule fired, so a report can quote a basis
                    # instead of a label.
                    "basis": [IOC_RULE_BASIS[r.split(":", 1)[0]]
                              for r in reasons
                              if r.split(":", 1)[0] in IOC_RULE_BASIS],
                })
        return hits

    # --- COURT-READY EXPORTS ---

    @staticmethod
    def build_report_header(case_meta: dict, db_info: dict) -> dict:
        """Court-ready provenance block stamped into every export."""
        now = datetime.now(timezone.utc)
        return {
            "tool": f"{TOOL_NAME} v{TOOL_VERSION}",
            "parser_backend": "dissect.esedb (dirty-state direct read, source opened read-only)",
            "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "examiner": case_meta.get("examiner", ""),
            "case_number": case_meta.get("case_number", ""),
            "evidence_id": case_meta.get("evidence_id", ""),
            "notes": case_meta.get("notes", ""),
            "evidence_source": db_info.get("path", ""),
            "evidence_sha256": db_info.get("sha256", ""),
            "related_file_hashes": db_info.get("source_hashes", {}),
            "database_state": db_info.get("db_state_text", ""),
            "derived_machine_timezone": db_info.get("derived_tz", ""),
            "timezone_policy": ("All timestamps UTC (RFC 3339) unless explicitly "
                                "labeled LOCAL (SPS property 24 is machine-local)."),
            "parsing_statistics": db_info.get("parse_stats", {}),
            "records_total": db_info.get("total_entries", 0),
            # Scope honesty travels with every export, not just the PDF.
            "scope_statements": [{"heading": h, "statement": t}
                                 for h, t in em.SCOPE_STATEMENTS],
            "evidentiary_basis_legend": {b: em.BASIS_DEFINITION[b]
                                         for b in em.BASIS_ORDER},
            "inferred_attributions": em.inferred_citations(),
        }

    def _write_metadata_sidecar(self, filepath: str, case_meta: dict,
                                db_info: dict, rows_written: int,
                                extra: Optional[dict] = None):
        header = self.build_report_header(case_meta or {}, db_info or {})
        header["export_file"] = os.path.basename(filepath)
        header["rows_written"] = rows_written
        header.update(extra or {})
        sidecar = filepath + ".metadata.json"
        # atomic_write, like every other writer in this module, so an
        # interrupted write never leaves a truncated sidecar beside a
        # complete export.
        with atomic_write(sidecar, encoding="utf-8") as f:
            json.dump(header, f, indent=2, default=str)

    def export_pdf_report(self, entries: list, stats: dict, filepath: str,
                          case_meta: dict, db_info: dict,
                          recovery_summary: Optional[dict] = None,
                          recovered: Optional[list] = None):
        """Signed-report-grade PDF: provenance header, hashes, methodology,
        statistics, EntryId gaps, recovered artifacts, top records."""
        if not HAS_REPORTLAB:
            raise RuntimeError("reportlab not installed. Run: pip install reportlab")
        (rl_colors, A4, getSampleStyleSheet, ParagraphStyle, mm,
         SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
         PageBreak) = _reportlab()

        header = self.build_report_header(case_meta or {}, db_info or {})
        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("H1x", parent=styles["Heading1"], fontSize=16,
                            spaceAfter=6, textColor=rl_colors.HexColor("#00695C"))
        h2 = ParagraphStyle("H2x", parent=styles["Heading2"], fontSize=12,
                            spaceBefore=10, spaceAfter=4,
                            textColor=rl_colors.HexColor("#00796B"))
        body = ParagraphStyle("Bodyx", parent=styles["BodyText"], fontSize=8.5,
                              leading=11)
        mono = ParagraphStyle("Monox", parent=styles["BodyText"], fontSize=7,
                              fontName="Courier", leading=9)

        def esc(s):
            return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;"))

        pdf_target = filepath + ".partial"
        doc = SimpleDocTemplate(pdf_target, pagesize=A4,
                                leftMargin=15 * mm, rightMargin=15 * mm,
                                topMargin=15 * mm, bottomMargin=15 * mm,
                                title="WebCache Forensic Analysis Report")
        story = [Paragraph("WebCache Forensic Analysis Report", h1)]

        # 1. Case / provenance
        # Sections are numbered as they are emitted, so skipping an optional
        # section leaves no gap in the numbering.
        section_no = [0]

        def section(title):
            section_no[0] += 1
            return Paragraph(f"{section_no[0]}. {title}", h2)

        story.append(section("Case &amp; Evidence Provenance"))
        prov_rows = [
            ["Examiner", header["examiner"] or "—"],
            ["Case number", header["case_number"] or "—"],
            ["Evidence ID", header["evidence_id"] or "—"],
            ["Evidence source", header["evidence_source"]],
            ["Evidence SHA-256", header["evidence_sha256"]],
            ["Database state", header["database_state"]],
            ["Machine timezone (derived)", header["derived_machine_timezone"] or "n/a"],
            ["Tool", header["tool"]],
            ["Generated (UTC)", header["generated_utc"]],
            ["Timezone policy", header["timezone_policy"]],
        ]
        t = Table([[Paragraph(esc(a), body), Paragraph(esc(b), mono)]
                   for a, b in prov_rows], colWidths=[42 * mm, 138 * mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.HexColor("#B0BEC5")),
            ("BACKGROUND", (0, 0), (0, -1), rl_colors.HexColor("#ECEFF1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)

        # 2. File hashes
        story.append(section("Source File Hashes (SHA-256, computed on load)"))
        hash_rows = [["File", "SHA-256"]] + [
            [fn, hx] for fn, hx in sorted(header["related_file_hashes"].items())]
        t = Table([[Paragraph(esc(a), body), Paragraph(esc(b), mono)]
                   for a, b in hash_rows], colWidths=[45 * mm, 135 * mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.HexColor("#B0BEC5")),
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#CFD8DC")),
        ]))
        story.append(t)

        # 3. Methodology
        story.append(section("Methodology and Scope"))
        story.append(Paragraph(
            "This section states plainly what this tool did, what it did not do, "
            "and where the limits of the method lie. Each finding elsewhere in "
            "this report should be read against it.", body))
        for heading, text in em.SCOPE_STATEMENTS:
            story.append(Paragraph(f"<b>{esc(heading)}.</b> {esc(text)}", body))

        # 3b. How to read the evidentiary basis labels
        story.append(Paragraph("3.1 Evidentiary basis of reported values", h2))
        story.append(Paragraph(
            "Every field in this report carries one of four bases. They are not "
            "equally strong and must not be treated as such.", body))
        basis_rows = [["Basis", "Meaning", "Fields"]]
        counts = em.counts_by_basis()
        for basis in em.BASIS_ORDER:
            basis_rows.append([basis, em.BASIS_DEFINITION[basis],
                               str(counts.get(basis, 0))])
        t = Table([[Paragraph(f"<b>{esc(a)}</b>", body), Paragraph(esc(b), body), c]
                   for a, b, c in basis_rows],
                  colWidths=[26 * mm, 130 * mm, 18 * mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.HexColor("#B0BEC5")),
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#CFD8DC")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)

        # 3c. Attributions for every inferred semantic used
        cites = em.inferred_citations()
        if cites:
            story.append(Paragraph("3.2 Attribution for inferred semantics", h2))
            story.append(Paragraph(
                "Values labelled INFERRED rest on the following published research "
                "rather than on Microsoft documentation. The underlying raw values "
                "are included in this report so each attribution can be checked "
                "independently.", body))
            for cite in cites:
                story.append(Paragraph("• " + esc(cite), body))

        # 4. Parsing statistics
        story.append(section("Parsing Statistics"))
        ps = header["parsing_statistics"]
        stat_rows = [
            ["Records parsed", str(ps.get("parsed", 0))],
            ["Tables skipped", str(ps.get("skipped", 0))],
            ["Record errors", str(ps.get("errors", 0))],
            ["Entries in report scope", str(len(entries))],
            ["InPrivate entries", str(stats.get("inprivate_count", 0))],
            ["Local-file (file:///) accesses",
             str(sum(1 for e in entries if e.get("IsLocalFile")))],
        ]
        if recovery_summary:
            stat_rows += [
                ["Recovered from transaction logs", str(recovery_summary.get("log_recovered", 0))],
                ["Recovered from DB unallocated space", str(recovery_summary.get("page_recovered", 0))],
            ]
        t = Table(stat_rows, colWidths=[70 * mm, 40 * mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.HexColor("#B0BEC5")),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ]))
        story.append(t)

        # Missing EntryIds — an observation, not a conclusion.
        gaps = self.analyze_entryid_gaps(self._containers_meta)
        if gaps:
            story.append(section(
                "Missing EntryIds (records absent from the live table)"))
            story.append(Paragraph(
                "ESE issues EntryIds in sequence, so a hole means an ID was "
                "issued and the record that held it is not in the live table. "
                "This does not by itself establish that anything was deleted: "
                "the same hole is produced by automatic cache scavenging, "
                "which is how these containers routinely shed old entries, and "
                "by IDs consumed by transactions that never committed. The "
                "container's own last-scavenge and last-access times are given "
                "so the alternatives can be weighed. Deleted records that were "
                "actually recovered are listed in the Recovered Artifacts "
                "section; those are evidence, this is a count.", body))
            gap_rows = [["Container", "Type", "Live", "Missing IDs",
                         "Gap runs", "Last scavenge"]]
            for g in gaps:
                gap_rows.append([f"{g['ContainerId']} {g['ContainerName']}",
                                 g["ContainerType"], str(g["LiveRecords"]),
                                 str(g["MissingEntryIds"]), str(g["GapRuns"]),
                                 (g.get("LastScavengeTime") or "not recorded")])
            t = Table(gap_rows, colWidths=[46 * mm, 22 * mm, 15 * mm, 20 * mm,
                                           15 * mm, 34 * mm])
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.HexColor("#B0BEC5")),
                ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#CFD8DC")),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]))
            story.append(t)

        # 6. Top domains
        story.append(section("Top Domains"))
        dom_rows = [["Domain", "Records"]] + [
            [d, str(c)] for d, c in stats["top_domains"].most_common(15)]
        t = Table([[Paragraph(esc(a), body), b] for a, b in dom_rows],
                  colWidths=[120 * mm, 25 * mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, rl_colors.HexColor("#B0BEC5")),
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#CFD8DC")),
        ]))
        story.append(t)

        # Recovered artifacts. Always present, so the report states whether
        # recovery found nothing or was not run.
        story.append(PageBreak())
        if not recovered:
            story.append(section("Recovered Artifacts"))
            story.append(Paragraph(
                "No deleted or unflushed records are included in this report. "
                "Either the recovery scan was not run for this case, or it "
                "recovered nothing. This is not evidence that the database "
                "contains no deleted records \u2014 run the recovery scan to "
                "establish that.", body))
        else:
            story.append(section(
                f"Recovered Artifacts ({len(recovered)}) \u2014 "
                "deleted/unflushed records absent from the live database"))
            rec_rows = [["Time (context)", "Source", "Conf.", "URL"]]
            for a in recovered:
                ft = (a["NearbyFiletime"].strftime("%Y-%m-%d %H:%M")
                      if a.get("NearbyFiletime") else "—")
                rec_rows.append([ft, a.get("RecoverySource", "")[:14],
                                 a.get("Confidence", ""),
                                 Paragraph(esc(a.get("Url", "")), mono)])
            t = Table(rec_rows, colWidths=[27 * mm, 26 * mm, 13 * mm, 114 * mm])
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.3, rl_colors.HexColor("#B0BEC5")),
                ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#CFD8DC")),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(t)

        # Every History record, not a sample of them. This is the section a
        # reader is most likely to rely on, so a cap here is the least
        # defensible place to have one.
        hist = [e for e in entries if e.get("ContainerType") == "History"]
        story.append(PageBreak())
        story.append(section(f"History Records (all {len(hist):,})"))
        story.append(Paragraph(
            "Visits marked with an asterisk come from the AccessCount column, "
            "which counts cache touches rather than user visits; unmarked "
            "figures come from the property store and do count user visits. "
            "URLs are printed in full.", body))
        hrows = [["Visit (UTC)", "Visits", "URL"]]
        # UTC order: see engine/local_clock.py for why not the raw column.
        hist_sorted = sorted(
            hist, key=lambda e: local_clock.utc_raw(e, "ModifiedTime_raw"),
            reverse=True)
        for e in hist_sorted:
            hrows.append([
                (e.get("ModifiedTime", "") or "").replace(" UTC", ""),
                _pdf_visit_cell(e),
                Paragraph(esc(e.get("CleanUrl") or e.get("Url", "")), mono),
            ])
        t = Table(hrows, colWidths=[30 * mm, 13 * mm, 137 * mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.3, rl_colors.HexColor("#B0BEC5")),
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#CFD8DC")),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)

        try:
            case_no = (case_meta or {}).get("case_number") or "not stated"
            sha = (db_info or {}).get("sha256") or "not computed"
            # On the template, not the canvas: the template writes its
            # own (default "(anonymous)") over a canvas's at build time.
            doc.author = (case_meta or {}).get("examiner") or "not stated"
            doc.creator = "%s %s" % (TOOL_NAME, TOOL_VERSION)
            doc.subject = "Case %s, evidence SHA-256 %s" % (case_no, sha)
            doc.build(story, canvasmaker=_report_canvas(
                "%s  |  Case %s  |  Evidence SHA-256 %s"
                % (TOOL_NAME, case_no, sha)))
            os.replace(pdf_target, filepath)
        except BaseException:
            try:
                os.remove(pdf_target)
            except OSError:
                pass
            raise

    # --- FULL BUNDLE ---------------------------------------------------

    #: Bumped when the table or column layout changes, so a script written
    #: against an older export can tell rather than guess. Recorded in
    #: export_info.
    SQLITE_SCHEMA_VERSION = 1

    #: Every field a position fix carries, with its heading. One list, as
    #: ENTRY_FIELDS, so every location format carries the same columns.
    LOCATION_FIELDS = [
        ("FixTimestamp", "Fix time — device said (UTC)"),
        ("RecordTimeUTC", "Cache wrote (UTC)"),
        # Why "Cache wrote (UTC)" is blank when it is: an MSHist visit on
        # the LOCAL clock with no recovered zone (engine/local_clock.py).
        ("RecordTimeNote", "Cache wrote — clock note"),
        ("LatitudeRaw", "Latitude (as stored)"),
        ("LongitudeRaw", "Longitude (as stored)"),
        ("AccuracyMetres", "Accuracy (m)"),
        ("Provider", "Reported source"),
        ("Assessment", "What this fix is worth"),
        ("Parameter", "From URL parameter"),
        ("Origin", "Source record"),
        ("EntryId", "EntryId"),
        ("ContainerId", "Container ID"),
        ("ContainerType", "Container type"),
        ("MapsUrl", "Google Maps"),
        ("OsmUrl", "OpenStreetMap"),
        ("Url", "Request URL"),
    ]

    #: The LOCATION_FIELDS that hold a time, for the workbook's date cells.
    LOCATION_TIME_KEYS = frozenset(("FixTimestamp", "RecordTimeUTC"))

    @staticmethod
    def _loc_value(fix, key):
        """One field of a fix, with Origin read off the record behind it."""
        if key == "Origin":
            entry = fix.get("_entry") or {}
            return entry.get("Origin") or provenance.LIVE_ORIGIN
        if key in ("LatitudeRaw", "LongitudeRaw") and not fix.get(key):
            # An older fix may carry only the float.
            number = fix.get(key[:-3])
            return "" if number is None else repr(number)
        value = fix.get(key)
        return "" if value is None else value

    #: Prefix on every source-record column of a position export, so
    #: "Origin" of the fix and "Source record: Origin" cannot be confused.
    LOCATION_RECORD_PREFIX = "Source record: "

    def _loc_canonical(self, fix):
        """The canonical ENTRY_FIELDS row of the record a fix was read out
        of -- canonical_record_row, the same path every view export takes."""
        record = fix.get("_record")
        if not isinstance(record, dict):
            record = fix.get("_entry") or {}
        carved = "carved" in str(self._loc_value(fix, "Origin")).lower()
        return canonical_record_row(record, carved=True if carved else None)

    def _loc_headers(self):
        return ([h for _k, h in self.LOCATION_FIELDS]
                + [self.LOCATION_RECORD_PREFIX + h
                   for _k, h, _g in ENTRY_FIELDS])

    def _loc_cells(self, fix):
        """The fix's derived columns, then its source record's canonical
        fields. Coordinates are written as the fix carries them."""
        canon = self._loc_canonical(fix)
        return ([self._loc_value(fix, k) for k, _h in self.LOCATION_FIELDS]
                + [canon.get(k) for k in ENTRY_FIELD_KEYS])

    def export_location_csv(self, fixes, filepath, case_meta=None,
                            db_info=None, places=None):
        """Every position fix, every field, one row each.

        The grid's export writes the columns on screen; this writes
        LOCATION_FIELDS in full, including the assessment, the parameter
        the coordinates came from, and the record each fix belongs to.

        Each fix's derived columns are followed by its source record's
        canonical fields, each headed LOCATION_RECORD_PREFIX + its
        ENTRY_FIELDS heading.
        """
        with atomic_write(filepath, encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(self._loc_headers())
            for fix in fixes or []:
                w.writerow([_cell(v) for v in self._loc_cells(fix)])
        self._write_metadata_sidecar(filepath, case_meta, db_info,
                                     rows_written=len(fixes or []))

    def export_location_json(self, fixes, filepath, case_meta=None):
        """Every fix as {"fix": LOCATION_FIELDS, "source_record":
        ENTRY_FIELDS}. Returns the number of fixes written."""
        def plain(value):
            if isinstance(value, (bytes, bytearray)):
                return value.hex()
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, (set, frozenset)):
                return sorted(_safe_text(str(v)) for v in value)
            return _safe_json(value)

        out = {
            "generated_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "case": dict(case_meta or {}),
            "caveat": ("A fix shows what the device reported to a server, "
                       "not that a particular person was present."),
            "fixes": [],
        }
        for fix in fixes or []:
            canon = self._loc_canonical(fix)
            out["fixes"].append({
                "fix": {k: plain(self._loc_value(fix, k))
                        for k, _h in self.LOCATION_FIELDS},
                "source_record": {k: plain(canon.get(k))
                                  for k in ENTRY_FIELD_KEYS},
            })
        with atomic_write(filepath, encoding="utf-8") as f:
            json.dump(out, f, indent=2, default=str, ensure_ascii=False)
        return len(out["fixes"])

    def export_location_xlsx(self, fixes, filepath):
        """The CSV's layout as a workbook: each fix, then its source
        record's canonical fields, through write_simple_xlsx's guards."""
        n_fix = len(self.LOCATION_FIELDS)
        # The fix's own two clocks first, then the source record's. A fix
        # time sent in a shape that is not a date stays as sent
        # (excel_datetime_value).
        stamps = [i for i, (k, _h) in enumerate(self.LOCATION_FIELDS)
                  if k in self.LOCATION_TIME_KEYS]
        stamps += [n_fix + i for i, k in enumerate(ENTRY_FIELD_KEYS)
                   if k in TIMESTAMP_EXPORT_KEYS]
        return write_simple_xlsx(
            filepath, "Position fixes", self._loc_headers(),
            (self._loc_cells(fix) for fix in fixes or []),
            timestamp_columns=stamps)

    def export_location_kml(self, fixes, filepath, case_meta=None):
        """Position fixes as KML, for Google Earth or any GIS.

        * Live and carved fixes are separate folders with separate pins: a
          recovered position carries different weight from one still in the
          live database, and they can be toggled independently.
        * Accuracy travels with the point: a WiFi fix good to +-100 m
          locates a building, not a room.

        Timestamps go in <TimeStamp>, so a time slider works on them.
        """
        def esc(value):
            return (str("" if value is None else value)
                    .replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))

        live, carved = [], []
        for fix in fixes or []:
            (carved if "carved" in str(self._loc_value(fix, "Origin")).lower()
             else live).append(fix)

        meta = case_meta or {}
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<kml xmlns="http://www.opengis.net/kml/2.2">', '<Document>',
               "<name>%s</name>" % esc(
                   "WebCache position fixes — case %s"
                   % (meta.get("case_number") or "unnumbered")),
               "<description>%s</description>" % esc(
                   "Positions the device reported to servers, recovered from "
                   "request URLs. Examiner: %s. Evidence: %s. Generated %s. "
                   "A fix shows what the device claimed, not that a "
                   "particular person was present."
                   % (meta.get("examiner") or "unstated",
                      meta.get("evidence_id") or "unstated",
                      datetime.now(timezone.utc).strftime(
                          "%Y-%m-%dT%H:%M:%SZ"))),
               '<Style id="live"><IconStyle><color>ff00a5ff</color>'
               '<scale>1.0</scale></IconStyle></Style>',
               '<Style id="carved"><IconStyle><color>ff0000ff</color>'
               '<scale>1.0</scale></IconStyle></Style>']

        for label, group, style in (("Live records", live, "live"),
                                    ("Recovered from deleted or unflushed "
                                     "data (carved)", carved, "carved")):
            if not group:
                continue
            out.append("<Folder><name>%s (%d)</name>" % (esc(label),
                                                         len(group)))
            for fix in group:
                lat = self._loc_value(fix, "LatitudeRaw")
                lon = self._loc_value(fix, "LongitudeRaw")
                if not lat or not lon:
                    continue
                when = str(fix.get("FixTimestamp")
                           or fix.get("RecordTimeUTC") or "")
                acc = fix.get("AccuracyMetres")
                desc = "\n".join(
                    "%s: %s" % (h, self._loc_value(fix, k))
                    for k, h in self.LOCATION_FIELDS
                    if str(self._loc_value(fix, k)) != "")
                out.append("<Placemark>")
                out.append("<name>%s</name>" % esc(
                    "%s%s" % (when or "undated",
                              "  ±%g m" % acc if acc else "")))
                out.append("<styleUrl>#%s</styleUrl>" % style)
                if when:
                    stamp = when.replace(" ", "T")
                    if not stamp.endswith("Z"):
                        stamp += "Z"
                    out.append("<TimeStamp><when>%s</when></TimeStamp>"
                               % esc(stamp))
                out.append("<description><![CDATA[%s]]></description>"
                           % desc.replace("]]>", "]]&gt;"))
                out.append("<Point><coordinates>%s,%s,0</coordinates></Point>"
                           % (lon, lat))
                out.append("</Placemark>")
            out.append("</Folder>")
        out.append("</Document></kml>")
        with atomic_write(filepath) as f:
            f.write("\n".join(out))

    def export_sqlite_raw(self, parser, filepath, case_meta=None,
                          recovered=None):
        """The ESE database converted to SQLite as it is stored.

        Not the curated export beside it: every ESE table becomes a SQLite
        table of the same name, with the same columns in the same order,
        holding the same values. No renaming, derived columns, filtering or
        interpretation: a table `Container_11` with a column `AccessedTime`
        is the same in this file, holding the number ESE stored.

        Every other export is this application's reading of the evidence;
        this one is the evidence in a format anyone can query without this
        application, which makes an independent check possible.

        Values keep their stored type: bytes as BLOB, integers as INTEGER,
        strings as TEXT. FILETIME columns stay raw 64-bit integers; the
        decoded times are in the other exports.

        Two tables are added, underscore-prefixed so they cannot collide
        with an ESE table name:
          _export_info    provenance: source path, SHA-256, when, row counts
          _carved_records records recovered from logs and unallocated pages,
                          which are not in any live ESE table
        """
        def _ident(name):
            return '"%s"' % str(name).replace('"', '""')

        def _val(v):
            if v is None or isinstance(v, (int, float, bytes, bytearray)):
                return v
            if isinstance(v, str):
                return _safe_text(v)
            if isinstance(v, datetime):
                return v.strftime("%Y-%m-%dT%H:%M:%SZ")
            if isinstance(v, (list, tuple, set, frozenset)):
                return ", ".join(str(x) for x in v)
            return str(v)

        tmp = filepath + ".partial"
        for stale in (tmp, filepath):
            if os.path.exists(stale):
                try:
                    os.remove(stale)
                except OSError:
                    pass

        con = sqlite3.connect(tmp)
        counts = {}
        problems = []
        skipped_stubs = 0
        try:
            cur = con.cursor()
            cur.execute("PRAGMA journal_mode=OFF")
            cur.execute("PRAGMA synchronous=OFF")

            for tname in list(getattr(parser, "table_names", []) or []):
                try:
                    table = parser.db.table(tname)
                    cols = [c.name for c in table.columns]
                    # live_records() skips leaf nodes too short to be a
                    # record (deleted-record stubs), so they are counted and
                    # reported, and a row count compared with the source .dat
                    # can be explained.
                    skipped_stubs += sum(1 for _ in ese_records.tombstones([table]))
                except Exception as exc:
                    problems.append("%s: could not open: %s" % (tname, exc))
                    continue
                if not cols:
                    problems.append("%s: no columns reported" % tname)
                    continue
                # ESE allows names SQLite would reject, and duplicates are
                # possible; every name is quoted and disambiguated rather than
                # a table skipped.
                seen, safe = {}, []
                for c in cols:
                    n = c if c not in seen else "%s_%d" % (c, seen[c])
                    seen[c] = seen.get(c, 0) + 1
                    safe.append(n)
                try:
                    cur.execute("CREATE TABLE %s (%s)"
                                % (_ident(tname),
                                   ", ".join(_ident(c) for c in safe)))
                except Exception as exc:
                    problems.append("%s: could not create: %s" % (tname, exc))
                    continue
                ins = ("INSERT INTO %s VALUES (%s)"
                       % (_ident(tname), ", ".join("?" * len(safe))))
                n = 0
                try:
                    for rec in ese_records.live_records(table):
                        cur.execute(ins, [_val(rec.get(c)) for c in cols])
                        n += 1
                except Exception as exc:
                    # A table that stops part way is still worth the rows it
                    # gave, but the shortfall must be recorded rather than
                    # left to look like the whole table.
                    problems.append("%s: stopped after %d rows: %s"
                                    % (tname, n, exc))
                counts[tname] = n

            cur.execute("CREATE TABLE _carved_records "
                        "(Url TEXT, Source TEXT, RecoverySource TEXT, "
                        "Confidence TEXT, NearbyFiletime TEXT, Offset INTEGER)")
            cur.executemany(
                "INSERT INTO _carved_records VALUES (?,?,?,?,?,?)",
                [(_val(a.get("Url")), _val(a.get("Source")),
                  _val(a.get("RecoverySource")), _val(a.get("Confidence")),
                  _val(a.get("NearbyFiletime")), a.get("Offset"))
                 for a in (recovered or [])])

            cur.execute("CREATE TABLE _export_info (key TEXT, value TEXT)")
            info = [
                ("conversion", "ESE -> SQLite, tables and values as stored"),
                ("source_database", str(getattr(parser, "db_path", "") or "")),
                ("generated_utc",
                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                ("ese_tables_converted", str(len(counts))),
                ("total_rows", str(sum(counts.values()))),
                ("carved_records", str(len(recovered or []))),
                ("skipped_deleted_stubs", str(skipped_stubs)),
                ("timestamp_note",
                 "FILETIME columns are the raw 64-bit integers ESE stored; "
                 "they are NOT converted. Decoded times are in the other "
                 "export formats."),
                ("blob_note",
                 "Binary columns are stored as SQLite BLOBs, byte for byte."),
            ]
            for fn, hx in sorted(
                    (getattr(parser, "source_hashes", None) or {}).items()):
                info.append(("sha256:" + str(fn), str(hx)))
            for tname, n in sorted(counts.items()):
                info.append(("rows:" + tname, str(n)))
            for p in problems:
                info.append(("problem", p))
            if case_meta:
                for k, v in dict(case_meta).items():
                    info.append(("case:" + str(k), _val(v)))
            cur.executemany("INSERT INTO _export_info VALUES (?,?)", info)
            con.commit()
        finally:
            con.close()
        os.replace(tmp, filepath)
        return counts

    def export_sqlite(self, entries: list, filepath: str, case_meta=None,
                      db_info=None, artifacts=None, recovered=None,
                      tags_map=None, comments_map=None):
        """The application's READING of the evidence, in SQLite.

        Kept alongside export_sqlite_raw, which is the faithful ESE->SQLite
        conversion. The two answer different questions and neither replaces
        the other: this one carries decoded timestamps, carved records
        labelled by source, and a field catalog; the raw one carries the
        database as stored, checkable without trusting this tool.
        """
        artifacts = artifacts or {}

        def _val(v):
            """A value SQLite will accept, without losing what it was."""
            if v is None or isinstance(v, (int, float, bytes, bytearray)):
                return v
            if isinstance(v, str):
                return _safe_text(v)
            if isinstance(v, datetime):
                # Fixed width, milliseconds included, as filetime_to_rfc3339
                # writes it, so a column holds one string width and sorts
                # correctly.
                return (v.strftime("%Y-%m-%dT%H:%M:%S.")
                       + "%03dZ" % (v.microsecond // 1000))
            if isinstance(v, (set, frozenset)):
                return ", ".join(sorted(str(x) for x in v))
            if isinstance(v, (list, tuple, dict)):
                return _safe_text(json.dumps(v, default=str,
                                             ensure_ascii=False))
            return str(v)

        def _ident(name):
            """A safe SQL identifier. Column names come from ENTRY_FIELDS,
            not from evidence, but quoting them is what keeps that true."""
            return '"%s"' % str(name).replace('"', '""')

        # Written to a temporary file and moved into place, so an
        # interrupted export never leaves a half-written database, as
        # atomic_write() guarantees for the text formats (sqlite3 needs a
        # path rather than a file object).
        tmp = filepath + ".partial"
        for stale in (tmp, filepath):
            if os.path.exists(stale):
                try:
                    os.remove(stale)
                except OSError:
                    pass
        con = sqlite3.connect(tmp)
        try:
            cur = con.cursor()
            cur.execute("PRAGMA journal_mode=OFF")
            cur.execute("PRAGMA synchronous=OFF")

            # -- records: live and carved, one table, always labelled ----
            cols = ["RecordSource"] + list(ENTRY_FIELD_KEYS)
            # No declared type: a TEXT affinity would store every integer as
            # text, breaking numeric ORDER BY and joins to containers.
            cur.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, %s)"
                        % ", ".join(_ident(c) for c in cols))
            ins = ("INSERT INTO records (%s) VALUES (%s)"
                   % (", ".join(_ident(c) for c in cols), ", ".join("?" * len(cols))))

            blob_rows = []
            BLOB_FIELDS = ("Blob_raw", "RequestHeaders_raw",
                           "ResponseHeaders_raw")
            rowid = 0
            for e in entries:
                row = build_entry_row(e, tags_map, comments_map)
                row["RecordSource"] = "Live database"
                cur.execute(ins, [_val(row.get(c)) for c in cols])
                rowid += 1
                for bf in BLOB_FIELDS:
                    raw = e.get(bf)
                    if isinstance(raw, (bytes, bytearray)) and raw:
                        blob_rows.append((rowid, bf, len(raw), bytes(raw)))

            for a in (recovered or []):
                # build_recovered_row() is the canonical row builder for a
                # carved artifact, shared with export_csv so a carved row in
                # the CSV and the same carved row here carry the same
                # provenance values (Origin, Method, KeyTimestampUTC/Desc,
                # ContainerType) -- not two hand-derived copies of the same
                # fill-in logic.
                row = build_recovered_row(a, tags_map, comments_map)
                row["RecordSource"] = ("RECOVERED — %s (%s confidence)"
                                       % (a.get("RecoverySource", ""),
                                          a.get("Confidence", "")))
                cur.execute(ins, [_val(row.get(c)) for c in cols])
                rowid += 1

            cur.execute("CREATE TABLE blobs (record_rowid INTEGER, "
                        "field TEXT, size INTEGER, data BLOB)")
            cur.executemany("INSERT INTO blobs VALUES (?,?,?,?)", blob_rows)
            cur.execute("CREATE INDEX idx_blobs_record ON blobs (record_rowid)")

            # -- artifacts, each collection its own table ----------------
            for table, key in (("cookies", "cookies"), ("hsts", "hsts"),
                               ("certificates", "certs"),
                               ("leak_files", "leaks"),
                               ("appcache", "appcache"),
                               ("containers", "containers"),
                               ("partitions", "partitions")):
                rows = artifacts.get(key) or []
                # A collection with no rows still gets its table: an absent
                # table would read as "not examined"; an empty one says
                # "examined, nothing found".
                keys = []
                for r in rows:
                    for k in r.keys():
                        if k not in keys:
                            keys.append(k)
                if not keys:
                    keys = ["note"]
                cur.execute("CREATE TABLE %s (%s)"
                            % (_ident(table),
                               ", ".join(_ident(k) for k in keys)))
                if rows:
                    cur.executemany(
                        "INSERT INTO %s VALUES (%s)"
                        % (_ident(table), ", ".join("?" * len(keys))),
                        [[_val(r.get(k)) for k in keys] for r in rows])

            # -- the file explains its own columns ----------------------
            cur.execute("CREATE TABLE field_catalog (key TEXT, header TEXT, "
                        "\"group\" TEXT, basis TEXT, meaning TEXT, "
                        "caveat TEXT, attribution TEXT)")
            cur.executemany(
                "INSERT INTO field_catalog VALUES (?,?,?,?,?,?,?)",
                [(k, h, g, _val(em.basis_of(k)),
                  _val((em.get(k) or {}).get("meaning", "")),
                  _val((em.get(k) or {}).get("caveat", "")),
                  _val((em.get(k) or {}).get("citation", "")))
                 for k, h, g in ENTRY_FIELDS])

            # -- case header, flattened to key/value --------------------
            cur.execute("CREATE TABLE case_info (key TEXT, value TEXT)")
            header = self.build_report_header(case_meta or {}, db_info or {})

            def _flatten(prefix, obj, out):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        _flatten("%s.%s" % (prefix, k) if prefix else str(k),
                                 v, out)
                elif isinstance(obj, (list, tuple)):
                    out.append((prefix, _val(list(obj))))
                else:
                    out.append((prefix, _val(obj)))

            flat = []
            _flatten("", header, flat)
            cur.executemany("INSERT INTO case_info VALUES (?,?)", flat)

            cur.execute("CREATE TABLE export_info (key TEXT, value TEXT)")
            cur.executemany("INSERT INTO export_info VALUES (?,?)", [
                ("schema_version", str(self.SQLITE_SCHEMA_VERSION)),
                ("generated_utc",
                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                ("live_records", str(len(entries))),
                ("recovered_records", str(len(recovered or []))),
                ("total_records", str(rowid)),
                ("blobs_stored", str(len(blob_rows))),
                ("timestamp_policy",
                 "All timestamps UTC unless the column name says LOCAL. "
                 "SPS id24 is machine-local."),
                ("record_source_note",
                 "records.RecordSource is 'Live database' for rows read from "
                 "the live tables and begins 'RECOVERED' for rows carved "
                 "from transaction logs or unallocated pages. The two carry "
                 "different evidentiary weight and are never merged."),
            ])

            # -- make it usable without knowing the schema --------------
            for idx, table, col in (
                    ("idx_records_time", "records", "KeyTimestampUTC"),
                    ("idx_records_domain", "records", "Domain"),
                    ("idx_records_source", "records", "RecordSource"),
                    ("idx_records_container", "records", "ContainerName"),
                    ("idx_records_entry", "records", "EntryId"),
                    ("idx_records_containerid", "records", "ContainerId")):
                if col in cols:
                    cur.execute("CREATE INDEX %s ON %s (%s)"
                                % (_ident(idx), _ident(table), _ident(col)))
            cur.execute(
                "CREATE VIEW v_timeline AS SELECT "
                '"KeyTimestampUTC", "RecordSource", "Domain", "CleanUrl", '
                '"KeyTimestampDesc", "ContainerName" FROM records '
                'WHERE "KeyTimestampUTC" <> \'\' '
                'ORDER BY "KeyTimestampUTC"')
            con.commit()
        finally:
            con.close()
        os.replace(tmp, filepath)

    def export_full_bundle(self, entries: list, out_dir: str, case_meta: dict,
                           db_info: dict, artifacts=None, recovered=None,
                           recovery_summary=None, tags_map=None,
                           comments_map=None, stats=None, parser=None) -> list:
        """Write every export format into one directory, plus a manifest with
        SHA-256 of each produced file. This is the 'hand the whole case over'
        deliverable.

        Returns the list of files written.
        """
        os.makedirs(out_dir, exist_ok=True)
        artifacts = artifacts or {}
        stats = stats or self.get_statistics()
        written = []

        def _try(label, filename, fn):
            path = os.path.join(out_dir, filename)
            try:
                fn(path)
                written.append(path)
            except Exception as e:
                # Never let one failing format abort the bundle; record it.
                err = os.path.join(out_dir, filename + ".ERROR.txt")
                with open(err, "w", encoding="utf-8") as f:
                    f.write(f"{label} export failed: {type(e).__name__}: {e}\n")
                written.append(err)

        _try("Full CSV", "01_all_records_full.csv",
             lambda p: self.export_csv(entries, p, tags_map, comments_map,
                                       recovered))
        _try("Excel workbook", "02_forensic_workbook.xlsx",
             lambda p: self.export_xlsx(entries, p, True, case_meta, db_info,
                                        artifacts, recovered, tags_map,
                                        comments_map, stats))
        _try("JSON", "03_complete_data.json",
             lambda p: self.export_json(entries, p, case_meta, db_info,
                                        artifacts, recovered, tags_map,
                                        comments_map))
        if HAS_REPORTLAB:
            _try("PDF report", "05_forensic_report.pdf",
                 lambda p: self.export_pdf_report(
                     entries, stats, p, case_meta, db_info, recovery_summary,
                     recovered))
        if recovered:
            _try("Recovered CSV", "06_recovered_artifacts.csv",
                 lambda p: self._write_recovered_csv(recovered, p))
        _try("SQLite database", "07_case.sqlite",
             lambda p: self.export_sqlite(entries, p, case_meta, db_info,
                                          artifacts, recovered, tags_map,
                                          comments_map))
        # The raw conversion needs the open ESE database, so it is written
        # only when the caller passes the parser; no empty "raw" file is
        # written otherwise.
        if parser is not None:
            _try("Raw ESE->SQLite", "08_raw_ese.sqlite",
                 lambda p: self.export_sqlite_raw(parser, p, case_meta,
                                                  recovered))

        # Manifest: hash every file in the bundle so it is self-verifying.
        #
        # Enumerated from the directory, not from the paths this method
        # assigned: some formats write a companion of their own (a
        # .metadata.json sidecar), and every file in the bundle must be in
        # the manifest.
        mpath = os.path.join(out_dir, "00_MANIFEST.json")
        manifest = {
            "report": self.build_report_header(case_meta or {}, db_info or {}),
            "manifest_scope": ("Every file in this directory except the "
                               "manifest itself, enumerated from disk after "
                               "all exports completed."),
            "files": [],
        }
        try:
            on_disk = sorted(
                os.path.join(out_dir, n) for n in os.listdir(out_dir)
                if os.path.isfile(os.path.join(out_dir, n)))
        except OSError:
            on_disk = list(written)
        for path in on_disk:
            if os.path.abspath(path) == os.path.abspath(mpath):
                continue
            try:
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                manifest["files"].append({
                    "name": os.path.basename(path),
                    "size_bytes": os.path.getsize(path),
                    "sha256": h.hexdigest(),
                })
            except OSError:
                continue
        with atomic_write(mpath, encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, default=str)
        # Return everything the bundle contains, not only what was requested,
        # so the caller's count matches the directory.
        written = [mpath] + [p for p in on_disk
                             if os.path.abspath(p) != os.path.abspath(mpath)]
        return written

    @staticmethod
    def _write_recovered_csv(recovered: list, filepath: str):
        with atomic_write(filepath, encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([h for _, h in RECOVERED_FIELDS])
            for a in recovered:
                nft = a.get("NearbyFiletime")
                row = dict(a)
                row["NearbyFiletimeRfc"] = (nft.strftime("%Y-%m-%dT%H:%M:%SZ")
                                            if nft else "")
                row["Domain"] = extract_domain(a.get("Url", "") or "")
                w.writerow([_cell(row.get(k)) for k, _ in RECOVERED_FIELDS])

    @staticmethod
    def _format_size(size) -> str:
        size = _as_int(size)
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def _html_escape(text) -> str:
        text = _safe_text(str(text))
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )
