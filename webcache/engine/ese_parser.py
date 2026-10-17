"""
ESE Database Parser Engine for WebCacheV01.dat
Uses dissect.esedb which handles dirty shutdown databases correctly.
"""

import hashlib
import os
import re
import struct
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from urllib.parse import urlparse, parse_qs, unquote_plus

from dissect.esedb import EseDB

from . import sps_decoder
from . import download_decoder
from . import ese_records
from . import local_clock
from ..spellings import other_spellings

EPOCH_AS_FILETIME = 116444736000000000
HUNDREDS_OF_NANOSECONDS = 10_000_000

# ── Timestamp integrity layer ─────────────────────────────────────────
# Every timestamp column is labeled with its semantic meaning and clock
# basis. ESE record columns are FILETIME in UTC; the SPS property-24 value
# is the single LOCAL-time exception (labeled at extraction site).
TIMESTAMP_SEMANTICS = {
    "SyncTime":         ("Last server sync check", "UTC"),
    "CreationTime":     ("Record created (often later than first visit)", "UTC"),
    "ExpiryTime":       ("Cache/content expiry (server-driven, not user activity)", "UTC"),
    "ModifiedTime":     ("Content modified / last visit written", "UTC"),
    "AccessedTime":     ("Record last ACCESSED (cache touch, not necessarily a visit)", "UTC"),
    "PostCheckTime":    ("Post-check revalidation time", "UTC"),
    "LastScavengeTime": ("Container last scavenged", "UTC"),
    "LastAccessTime":   ("Container last accessed", "UTC"),
    "SPS_LastVisitLocal": ("True last visit (SPS id 24) — stored in LOCAL machine time", "LOCAL"),
}

# wininet cache-entry flag bits (Content containers). NOTE: bit 0x8 here is
# EDITED_CACHE_ENTRY — it is only the InPrivate marker on History records.
WININET_FLAG_BITS = {
    0x00000001: "NORMAL",
    0x00000004: "STICKY",
    0x00000008: "EDITED/InPrivate(history)",
    0x00000010: "TRACK_OFFLINE",
    0x00000020: "TRACK_ONLINE",
    0x00000040: "REDIRECT",
    0x00010000: "SPARSE",
    0x00100000: "COOKIE",
    0x00200000: "URLHISTORY",
}

# Search engines, as (registrable-domain labels, required path prefix or
# None, query parameter). Matching is on host labels, not substrings, so
# 'google.' does not match mail.google.com and a mailbox search is not
# reported as a web search.
#
# The path is required where the engine uses one, so an arbitrary page on a
# search engine's domain that happens to carry ?q= is not read as a search.
SEARCH_ENGINES = (
    ("google",        "/search",  "q"),
    ("bing",          "/search",  "q"),
    ("duckduckgo",    None,       "q"),
    ("ecosia",        "/search",  "q"),
    ("qwant",         None,       "q"),
    ("startpage",     None,       "q"),
    ("baidu",         "/s",       "wd"),
    ("brave",         "/search",  "q"),
    ("yahoo",         "/search",  "p"),
    ("yandex",        "/search",  "text"),
    ("yandex",        "/search",  "q"),
    ("youtube",       "/results", "search_query"),
    ("mojeek",        "/search",  "q"),
)

# Subdomains of multi-service providers that are not web search. A search
# parameter here belongs to a mailbox, a drive or a document — someone's
# private content, not their browsing.
NON_SEARCH_SUBDOMAINS = frozenset({
    "mail", "drive", "docs", "calendar", "photos", "meet", "chat", "groups",
    "keep", "translate", "maps", "news", "scholar", "books", "play", "store",
    "accounts", "myaccount", "admin", "console", "cloud", "analytics",
})

# Kept for anything that imported the previous mapping.
SEARCH_PARAMS = {
    "q": tuple(f"{host}." for host, _p, param in SEARCH_ENGINES if param == "q"),
    "p": ("search.yahoo",),
    "search_query": ("youtube.",),
    "text": ("yandex.",),
}

# BLOB magic signatures for forensic identification
BLOB_SIGS = [
    (b"\xff\xd8\xff", "JPEG Image"),
    (b"\x89PNG\r\n\x1a\n", "PNG Image"),
    (b"GIF87a", "GIF Image"), (b"GIF89a", "GIF Image"),
    (b"RIFF", "RIFF/WEBP"),
    (b"bplist", "Apple Binary Plist"),
    (b"<?xml", "XML/Plist"),
    (b"%PDF", "PDF Document"),
    (b"PK\x03\x04", "ZIP/Office Archive"),
    (b"\x1f\x8b", "GZIP Compressed"),
    (b"II\x2a\x00", "TIFF Image (LE)"), (b"MM\x00\x2a", "TIFF Image (BE)"),
    (b"OggS", "OGG Audio"),
    (b"ID3", "MP3 Audio"),
    (b"\xff\xfb", "MP3 Audio"),
    (b"\x1a\x45\xdf\xa3", "MKV/WEBM Video"),
]

#: Length of one entry in the Containers table's SecureDirectories column.
#: The column holds several directory names run together with no separator,
#: so the only thing that divides them is this fixed width.
SECURE_DIR_NAME_LEN = 8


_LOG_FAMILY = re.compile(r"^webcache(v\d{2})\.dat$", re.IGNORECASE)


def log_prefix(db_path: str) -> str:
    """The name prefix of this database's own transaction logs: V01 for
    WebCacheV01.dat, V24 for WebCacheV24.dat (early Windows 8 builds).
    A renamed copy falls back to V01, the current family."""
    m = _LOG_FAMILY.match(os.path.basename(str(db_path)))
    return m.group(1).upper() if m else "V01"


def evidence_scope(db_path: str) -> list:
    """Every file opening this database will read, without reading any.

    The Open dialog and the hasher both call this, so the files listed are
    exactly the files read.

    Selection is by name, not content, so the scope is known before
    anything is opened.
    """
    directory = os.path.dirname(os.path.abspath(db_path))
    targets = [db_path]
    prefix = log_prefix(db_path).lower()
    try:
        for fn in sorted(os.listdir(directory)):
            fl = fn.lower()
            if fl.startswith(prefix) and fl.endswith((".log", ".chk", ".jrs",
                                                      ".jfm")):
                targets.append(os.path.join(directory, fn))
    except OSError:
        pass
    return targets


def resolve_cache_location(record, meta):
    """Where a record's cached file was recorded on the examined machine.

    Returns (folder, file_path, subdirectory). `folder` is the container's
    own directory and is known for any record with a container. `file_path`
    is that folder plus the secure subdirectory plus the filename, and
    `subdirectory` is that middle part on its own -- the name the record's
    index selects, which turns a bare "4" in the interface into RHQ60E6S.

    The last two are only returned when the record names a file AND its
    index falls inside the list the container declares. An index that does
    not, or a container that declares none, yields nothing rather than a
    plausible-looking wrong path.

    No value asserts the file is still on disk. Scavenging removes cached
    files and leaves their records behind, so this is where WinINET recorded
    the file, not a claim about the current contents of the volume.
    """
    if not meta:
        return "", "", ""
    folder = (meta.get("Directory") or "").strip()
    filename = (record.get("Filename") or "").strip()
    if not folder or not filename:
        return folder, "", ""
    names = meta.get("SecureDirectoryNames") or []
    try:
        index = int(record.get("SecureDirectory") or 0)
    except (TypeError, ValueError):
        return folder, "", ""
    # The index is 1-based: every container in the sample that stores files
    # declares four directories and uses indices 1 through 4.
    if index < 1 or index > len(names):
        return folder, "", ""
    base = folder if folder.endswith("\\") else folder + "\\"
    subdir = names[index - 1]
    return folder, base + subdir + "\\" + filename, subdir


# Known text columns across ALL ESE table types
TEXT_COLUMNS = {
    "Url", "Filename", "FileExtension", "RedirectUrl",
    "Name", "Directory", "PartitionId", "SecureDirectoryName",
    "AppId", "SubKey", "CookieName", "CookieValue",
    "ManifestUrl", "MasterUrl", "FallbackUrl", "NamespaceUrl",
    "OnlineWhitelistUrl", "Group", "GroupName",
    "RuleData", "Data",
}

# Known FILETIME columns across ALL ESE table types
FILETIME_COLUMNS = {
    "SyncTime", "CreationTime", "ExpiryTime", "ModifiedTime",
    "AccessedTime", "PostCheckTime", "LastScavengeTime",
    "LastAccessTime", "LastModifiedTime", "LastCheckedTime",
    "TokenExpiry", "ManifestLastAccessTime", "ManifestExpiryTime",
}


def detect_blob_type(data: Optional[bytes]) -> str:
    """Detect binary BLOB type from magic bytes."""
    if not data or len(data) < 4:
        return f"Binary ({len(data)}B)" if data else "Empty"
    for sig, label in BLOB_SIGS:
        if data[:len(sig)] == sig:
            if sig == b"RIFF" and len(data) > 11 and data[8:12] == b"WEBP":
                return "WEBP Image"
            return label
    if len(data) > 8 and data[4:8] == b"ftyp":
        return "MP4/MOV Video"
    if data[0] == 0x0a or data[0] == 0x08:
        return "Protobuf/Serialized"
    return f"Binary ({len(data)}B)"


def filetime_to_dt(ft) -> Optional[datetime]:
    """FILETIME -> UTC datetime, or None if the value is not a usable time.

    Accepts anything: carved records and damaged databases yield strings,
    floats and other values where an integer belongs, and the result is
    then "no time" rather than an exception.
    """
    if ft is None or isinstance(ft, bool):
        return None
    if not isinstance(ft, int):
        try:
            ft = int(ft)
        except (TypeError, ValueError):
            return None
    if ft <= 0 or ft > 2650467743990000000:
        return None
    try:
        return datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(
            microseconds=ft // 10
        )
    except (OverflowError, OSError, ValueError):
        return None


def stamp_str(dt, suffix: str) -> str:
    """Format one decoded timestamp, keeping the precision it has.

    A FILETIME counts 100-nanosecond ticks, and many stored times have a
    non-zero sub-second part, so two records shown as the same second can
    be most of a second apart. Milliseconds are shown where there are any,
    so whole-second values do not gain a misleading ".000".
    """
    if dt is None:
        return ""
    base = dt.strftime("%Y-%m-%d %H:%M:%S")
    if dt.microsecond:
        base += ".%03d" % (dt.microsecond // 1000)
    return "%s %s" % (base, suffix) if suffix else base


def filetime_to_str(ft: Optional[int]) -> str:
    return stamp_str(filetime_to_dt(ft), "UTC")


def format_cell(val, col_name: str = "") -> str:
    """Convert a raw ESE value to its display string: the one rendering the
    cross-table search matches against (WebCacheParser._format_raw_value
    delegates here), so a recovered record's integer and FILETIME columns
    are searched as a live cell of the same column is. Boolean-like values
    and edge cases are handled explicitly."""
    if val is None:
        return ""

    # Handle bytes
    if isinstance(val, bytes):
        if len(val) == 0:
            return ""
        # Try decode as text for known text fields
        if col_name in TEXT_COLUMNS:
            try:
                decoded = val.decode("utf-8", errors="replace").rstrip("\x00")
                if decoded:
                    return decoded
                return ""
            except Exception:
                pass
        # Try to detect if the bytes are actually a readable text string
        # (for columns not in TEXT_COLUMNS but containing text anyway)
        try:
            decoded = val.decode("utf-8")
            decoded = decoded.rstrip("\x00")
            # Check if mostly printable
            if decoded and all(c.isprintable() or c in ('\r', '\n', '\t') for c in decoded):
                return decoded
        except (UnicodeDecodeError, AttributeError):
            pass
        # For binary blobs, show BLOB type + hex summary
        blob_type = detect_blob_type(val)
        if len(val) > 64:
            hex_preview = " ".join(f"{b:02X}" for b in val[:32])
            return f"[{blob_type} {len(val)}B] {hex_preview}..."
        elif len(val) > 0:
            hex_preview = " ".join(f"{b:02X}" for b in val)
            return f"[{blob_type} {len(val)}B] {hex_preview}"
        return ""

    # Handle bool (before int, since bool is subclass of int)
    if isinstance(val, bool):
        return "True" if val else "False"

    # Handle int
    if isinstance(val, int):
        # Auto-detect FILETIME columns
        if col_name in FILETIME_COLUMNS:
            dt_str = filetime_to_str(val)
            if dt_str:
                return dt_str
        # Large values that look like FILETIME even if column not recognized
        # (heuristic: FILETIME values are typically > 100000000000000)
        if val > 100000000000000 and col_name not in {"UrlHash", "ExemptionDelta"}:
            dt_str = filetime_to_str(val)
            if dt_str:
                return f"{dt_str} ({val})"
        return str(val)

    # Handle float
    if isinstance(val, float):
        return f"{val:.6g}"

    return str(val)


def filetime_to_rfc3339(ft: Optional[int]) -> str:
    """RFC 3339 UTC string (for the *_rfc export columns)."""
    dt = filetime_to_dt(ft)
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# Prefix shapes: 'Visited: user@url' and ':YYYYMMDDYYYYMMDD: user@url'
_RE_MSHIST_PREFIX = re.compile(r"^:(\d{8})(\d{8}):\s*")
_RE_VISITED_PREFIX = re.compile(r"^Visited:\s*", re.I)


def split_history_url(url: str) -> dict:
    """Split a History/MSHist URL into its forensic parts.

    Returns {clean_url, username, mshist_from, mshist_to, prefix_type}."""
    out = {"clean_url": url or "", "username": "", "mshist_from": "",
           "mshist_to": "", "prefix_type": ""}
    if not url:
        return out
    rest = url
    m = _RE_MSHIST_PREFIX.match(rest)
    if m:
        out["prefix_type"] = "MSHist"
        d1, d2 = m.group(1), m.group(2)
        out["mshist_from"] = f"{d1[:4]}-{d1[4:6]}-{d1[6:]}"
        out["mshist_to"] = f"{d2[:4]}-{d2[4:6]}-{d2[6:]}"
        rest = rest[m.end():]
    else:
        m2 = _RE_VISITED_PREFIX.match(rest)
        if m2:
            out["prefix_type"] = "Visited"
            rest = rest[m2.end():]
    if "@" in rest:
        cand_user, cand_rest = rest.split("@", 1)
        # only treat as user prefix when it looks like a bare username
        if cand_user and "/" not in cand_user and ":" not in cand_user:
            out["username"] = cand_user
            rest = cand_rest
    out["clean_url"] = rest.strip()
    return out


def extract_search_terms(url: str) -> str:
    """The terms searched for, when this URL is a search-engine query.

    Returns "" for anything else. A site's own filter, an API parameter or a
    mailbox search are not web searches, and putting them in a column headed
    "Search terms" would attribute to a person something they did not do.
    """
    if not url or "?" not in url:
        return ""
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower().split(":")[0]
        if not host:
            return ""
        labels = host.split(".")
        # A mailbox or drive search is not a web search.
        if labels and labels[0] in NON_SEARCH_SUBDOMAINS:
            return ""
        path = (parsed.path or "/").lower()
        qs = parse_qs(parsed.query)
        for engine, needs_path, param in SEARCH_ENGINES:
            # Match a whole host label, not a substring anywhere in the name.
            if engine not in labels:
                continue
            if needs_path and not path.startswith(needs_path):
                continue
            values = qs.get(param)
            if not values:
                continue
            value = values[0].strip()
            if value:
                return unquote_plus(value)
    except (ValueError, UnicodeDecodeError):
        pass
    return ""


def decode_flags(flags: int, container_type: str) -> str:
    """Human-readable wininet flag decode; InPrivate only applies to History."""
    if not flags:
        return ""
    bits = []
    for bit, name in WININET_FLAG_BITS.items():
        if flags & bit:
            if bit == 0x08:
                name = "InPrivate" if container_type == "History" else "EDITED"
            bits.append(name)
    unknown = flags & ~sum(WININET_FLAG_BITS)
    if unknown:
        bits.append(f"0x{unknown:X}")
    return "|".join(bits)


def decode_content_headers(blob: Optional[bytes]) -> dict:
    if not blob:
        return {}
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        text = blob.decode("latin-1")

    headers = {}
    for line in text.split("\r\n"):
        line = line.strip()
        if not line:
            continue
        if ":" in line and not line.startswith("HTTP/"):
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
        elif line.startswith("HTTP/"):
            headers["_status_line"] = line
    return headers


def decode_sps_blob(blob: Optional[bytes]) -> dict:
    """Typed SPS parse (delegates to sps_decoder). Returns {id: value}."""
    fx = sps_decoder.extract_history_forensics(blob)
    return {pid: p["value"] for pid, p in fx["all_properties"].items()}


# ── One schema for every record, live or carved ──────────────────────
#
# A live record carries fields derived from its raw columns: the URL with
# its "Visited: user@" prefix stripped, the account name, whether it is a
# local file, the container's type and name, the flags in words. Every
# view reads those derived fields, so a carved record gets them too, from
# the same functions; otherwise recovered local-file accesses would be
# missing from File Access and carved URLs would keep their prefix.
#
# Deriving is not inventing: every field below is computed from bytes
# already recovered. What carving cannot know stays empty, and
# CarvedFieldsDerived records that derivation took place.

# Shapes that mean the carve boundary was wrong rather than that the URL was
# odd. "mhttp://" is an 'm' glued to the front of a real URL by a mis-set
# start offset; '"url":"https://' is a fragment of surrounding JSON.
_MALFORMED_URL = re.compile(
    r'^(?:[a-z0-9_%"\']{1,3}(?=https?://)|["\'{\[,]|.*?"url"\s*:\s*")',
    re.IGNORECASE)


def carved_url_health(url: str) -> tuple:
    """Is this carved URL intact, and if not, what is wrong with it?

    Returns (health, note). health is "intact", "repairable" or "damaged".
    A carve that begins mid-token is still evidence, but is not presented
    as a clean URL.
    """
    text = str(url or "")
    if not text:
        return "damaged", "no URL was recovered"
    body = strip_account_prefix_local(text)
    for scheme in ("https://", "http://"):
        at = body.lower().find(scheme)
        if at > 0 and at <= 3:
            return ("repairable",
                    f"{at} stray byte(s) before the scheme — the carve began "
                    f"mid-token; the URL from {scheme!r} onwards is intact")
        if at > 3:
            return ("repairable",
                    "the URL is embedded in surrounding data (JSON or a "
                    "longer field); the scheme onwards is intact")
    if "://" not in body and not body.startswith(("file:", ":")):
        return "damaged", "no scheme was recovered, so this may be a fragment"
    return "intact", ""


def strip_account_prefix_local(url: str) -> str:
    """The URL without any 'Visited: user@' or ':range:' prefix."""
    return split_history_url(url or "").get("clean_url", url or "")


def normalise_record(record: dict, containers_meta=None,
                     container_types=None) -> dict:
    """Give a carved record the same fields a live one has.

    `containers_meta` is the parser's container table and
    `container_types` its ContainerId -> type map, used to name and
    classify the container a carved record belongs to. Without them the
    container fields stay empty.

    The record is updated in place and returned.
    """
    if not isinstance(record, dict):
        return record

    url = str(record.get("Url") or "")
    parts = split_history_url(url)
    clean = parts["clean_url"]

    record.setdefault("CleanUrl", "")
    if not record.get("CleanUrl"):
        record["CleanUrl"] = clean
    record.setdefault("UrlUsername", parts["username"])
    record.setdefault("MSHistFrom", parts["mshist_from"])
    record.setdefault("MSHistTo", parts["mshist_to"])
    record.setdefault("SearchTerms", extract_search_terms(clean))

    # A carve that began mid-prefix still holds the URL.
    #
    # In "YYMMDD: user@file:///C:/Users/..." the leading
    # ":YYYYMMDDYYYYMMDD:" was cut in half, so the prefix pattern does not
    # match. The file path after "file:///" is intact; it is salvaged, and
    # the salvage is stated. The raw value stays in Url so the reading can
    # be checked against the bytes.
    if "://" not in clean.split("?", 1)[0][:12]:
        for scheme in ("file:///", "file://", "https://", "http://"):
            at = clean.lower().find(scheme)
            if at > 0:
                record["CleanUrl"] = clean = clean[at:]
                record["UrlSalvaged"] = True
                record.setdefault(
                    "UrlSalvageNote",
                    f"The carve began mid-prefix; {at} damaged byte(s) before "
                    f"{scheme!r} were discarded. Everything from the scheme "
                    f"onwards is as stored.")
                break

    record["IsLocalFile"] = clean.lower().startswith("file:")
    record.setdefault("IsLeak", url.upper().startswith("LEAK"))

    # A local file's name and extension, for the File Access view.
    if record["IsLocalFile"]:
        path = clean[5:].lstrip("/")
        name = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        record.setdefault("Filename", name)
        record.setdefault("FileExtension",
                          ("." + name.rsplit(".", 1)[-1].lower())
                          if "." in name else "")
    else:
        record.setdefault("Filename", "")
        record.setdefault("FileExtension", "")

    # Container identity, when the container table survived.
    ctype = record.get("ContainerType") or ""
    cname = record.get("ContainerName") or ""
    cid = record.get("ContainerId")
    own_meta = None
    if not ctype and container_types:
        ctype = container_types.get(cid) or ""
    if containers_meta:
        for meta in containers_meta:
            if meta.get("ContainerId") == cid:
                own_meta = meta
                if not cname:
                    cname = (meta.get("Name")
                             or meta.get("ContainerName") or "")
                    # The container's own Name is also its category when the
                    # type map is unavailable — "Content", "History",
                    # "Cookies".
                    ctype = ctype or cname
                break
    record["ContainerType"] = ctype
    record["ContainerName"] = cname

    # Where this record's file was recorded on the examined machine, joined
    # from the Containers table's folder for the record's container.
    folder, file_path, subdir = resolve_cache_location(record, own_meta)
    record["CacheFolder"] = folder
    record["CachedFilePath"] = file_path
    record["SecureDirectoryName"] = subdir

    # Flags in words, decoded against the container type just resolved.
    if not record.get("FlagsDecoded"):
        try:
            record["FlagsDecoded"] = decode_flags(
                int(record.get("Flags") or 0), ctype)
        except (TypeError, ValueError):
            record["FlagsDecoded"] = ""

    # Whatever the response-header blob holds: HTTP headers, or a property
    # store carrying the visit count and page title.
    blob = record.get("ResponseHeaders_raw")
    record.setdefault("BlobClass", "")
    if isinstance(blob, (bytes, bytearray)) and blob:
        try:
            blob = bytes(blob)
            klass = sps_decoder.classify_response_headers(blob)
            record["BlobClass"] = klass
            if klass == "http":
                record.setdefault("ResponseHeaders",
                                  decode_content_headers(blob))
            elif klass == "sps":
                fx = sps_decoder.extract_history_forensics(blob)
                record.setdefault("SPS_Properties", {
                    pid: p["value"] for pid, p in fx["all_properties"].items()})
                if fx.get("visit_count") is not None:
                    record.setdefault("SPS_VisitCount", fx["visit_count"])
                if fx.get("last_visit_local"):
                    record.setdefault(
                        "SPS_LastVisitLocal",
                        stamp_str(fx["last_visit_local"], "LOCAL"))
                    record.setdefault("SPS_LastVisitLocal_raw",
                                      fx.get("last_visit_local_raw"))
                if fx.get("page_title"):
                    record.setdefault("SPS_PageTitle", fx["page_title"])
        except Exception:
            pass

    # Say plainly that a carve was mis-bounded rather than showing the
    # damage as though it were the recorded URL.
    health, note = carved_url_health(url)
    record["UrlHealth"] = health
    record["UrlHealthNote"] = note
    record["CarvedFieldsDerived"] = True
    return record


class SearchCancelled(Exception):
    """Raised by a search's progress_callback to stop a scan.

    Declared in the engine because search_all_tables' per-table
    `except Exception: continue` would otherwise swallow a cancellation
    and continue to the next table. search_all_tables re-raises this
    exception ahead of that clause; the shell subclasses it.
    """


#: Rows between progress_callback calls, mirroring parse_all_entries' own
#: every-200-records cadence rather than inventing a second one.
_SEARCH_PROGRESS_ROWS = 200


class WebCacheParser:
    def __init__(self):
        self.db = None
        self.db_file = None
        self.db_path = None
        self.containers_meta = []
        self.container_map = {}  # cid -> name
        self.container_type_map = {}  # cid -> type
        self.all_entries = []
        self.table_names = []
        self.table_row_counts = {}  # table_name -> count (cached)
        self._tombstones = None  # deleted-record stubs (cached); see tombstones()

        # Forensic integrity / provenance
        self.source_hashes = {}      # filename -> sha256 hex
        self.db_state = None         # 1=clean, 2=dirty shutdown
        self.parse_stats = {"parsed": 0, "skipped": 0, "errors": 0}
        self.decision_log = []       # transparent per-table processing notes
        #: [(table_name, reason), ...] for the LAST search_all_tables call
        #: -- the same instance-attribute-as-out-param idiom parse_stats
        #: and decision_log above already use. Reset at the top of every
        #: search, so it can never describe an earlier one.
        self.search_skipped_tables = []

        # Modern Win11 table families (no free GUI decodes these)
        self.partitions = []         # PartitionsEx rows (TableId join key)
        self.cookie_entries = []     # CookieEntryEx_* decoded cookies
        self.hsts_entries = []       # HstsEntryEx_* decoded HSTS pins
        self.cert_entries = []       # BlobEntry_* TLS certificate store
        self.leak_files = []         # LeakFiles rows (survive deletion)
        self.appcache_entries = []   # AppCacheEntryEx_* rows

        # Timezone recovery: the modal (SPS id24 - ModifiedTime) offset
        # across History records -- see engine/local_clock.py.
        self.derived_tz_offset_seconds = None
        self.derived_tz_label = ""
        #: Every History record's observation of the offset
        #: (local_clock.zone_observations), kept so a later recovery scan
        #: stamps carved MSHist records as the live ones were.
        self.zone_observations = []

    def open(self, db_path: str, known_hashes: dict = None) -> bool:
        try:
            self.db_file = open(db_path, "rb")
            self.db = EseDB(self.db_file)
            self.db_path = db_path
            try:
                self.db_state = int(self.db.header.dbstate)
            except (AttributeError, TypeError, ValueError):
                self.db_state = None
            if known_hashes is not None:
                # The Open dialog has already hashed every file in scope
                # (EvidenceSet.hashes, keyed by full path), so the files
                # are not read a second time.
                self.source_hashes = {os.path.basename(p): h
                                       for p, h in known_hashes.items()}
            else:
                self._hash_sources(db_path)
            self._load_tables()
            self._load_containers()
            self._load_partitions()
            state_txt = {1: "clean shutdown", 2: "DIRTY shutdown", 3: "being converted"}.get(
                self.db_state, f"state {self.db_state}")
            self.decision_log.append(
                f"Opened read-only: {os.path.basename(db_path)} ({state_txt}); "
                f"SHA-256 {self.source_hashes.get(os.path.basename(db_path), '')}")
            if self.db_state == 2:
                self.decision_log.append(
                    "Dirty state read directly (no esentutl recovery run) — "
                    "preserves records a soft recovery could destroy.")
            return True
        except Exception as e:
            self.db = None
            if self.db_file:
                self.db_file.close()
                self.db_file = None
            # Some failures arrive with no message at all -- a zero-byte
            # file raises an exception whose str() is empty -- and
            # "Failed to open database:" with nothing after the colon
            # tells an examiner only that it failed, on the one screen
            # whose whole job is to say why. Fall back to what can be
            # established from the file itself.
            reason = str(e).strip()
            if not reason:
                try:
                    size = os.path.getsize(db_path)
                except OSError:
                    size = None
                if size == 0:
                    reason = ("the file is empty (0 bytes) -- an ESE "
                              "database is never zero-length")
                elif size is not None:
                    reason = ("%s gave no reason; the file is %d byte(s)"
                              % (type(e).__name__, size))
                else:
                    reason = "%s gave no reason" % type(e).__name__
            raise RuntimeError(f"Failed to open database: {reason}")

    def _hash_sources(self, db_path: str):
        """SHA-256 the database and its transaction-log siblings (read-only)."""
        self.source_hashes = {}
        for path in evidence_scope(db_path):
            try:
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                self.source_hashes[os.path.basename(path)] = h.hexdigest()
            except OSError:
                continue

    def _load_partitions(self):
        """PartitionsEx: TableId is the join key for *Ex table suffixes;
        PartitionType 4=Content/BlobEntry 3=Cookies 2=HSTS 1=Dependency 0=AppCache;
        PartitionId is 'M' (medium integrity), 'L' (low) or an AppContainer SID."""
        self.partitions = []
        if not self.db or "PartitionsEx" not in self.table_names:
            return
        ptype_names = {0: "AppCache", 1: "Dependency", 2: "HSTS", 3: "Cookies",
                       4: "Content"}
        try:
            pt = self.db.table("PartitionsEx")
            for rec in ese_records.live_records(pt):
                self.partitions.append({
                    "TableId": self._safe_int(rec.get("TableId")),
                    "PartitionType": self._safe_int(rec.get("PartitionType")),
                    "PartitionTypeName": ptype_names.get(
                        self._safe_int(rec.get("PartitionType")), "Unknown"),
                    "SetId": self._safe_int(rec.get("SetId")),
                    "PartitionId": self._safe_str(rec.get("PartitionId")),
                    "Directory": self._safe_str(rec.get("Directory")),
                    "LastScavengeTime": filetime_to_str(rec.get("LastScavengeTime")),
                })
        except Exception as e:
            self.decision_log.append(f"PartitionsEx: SKIPPED — {e}")

    def partition_for_suffix(self, suffix: int) -> dict:
        for p in self.partitions:
            if p["TableId"] == suffix:
                return p
        return {}

    def _load_tables(self):
        self.table_names = []
        if not self.db:
            return
        for t in self.db.tables():
            self.table_names.append(t.name)

    def _load_containers(self):
        self.containers_meta = []
        self.container_map = {}
        self.container_type_map = {}
        if not self.db:
            return

        try:
            ct = self.db.table("Containers")
        except Exception:
            return

        if not ct:
            return

        for rec in ese_records.live_records(ct):
            try:
                cid = rec.get("ContainerId") or 0
                name = rec.get("Name") or ""
                directory = rec.get("Directory") or ""
                partition_id = rec.get("PartitionId") or ""
                flags = rec.get("Flags")
                size = rec.get("Size")
                limit = rec.get("Limit")
                last_scavenge = rec.get("LastScavengeTime")
                entry_max_age = rec.get("EntryMaxAge")
                last_access = rec.get("LastAccessTime")

                # Handle bytes for text fields
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace").rstrip("\x00")
                if isinstance(directory, bytes):
                    directory = directory.decode("utf-8", errors="replace").rstrip("\x00")
                if isinstance(partition_id, bytes):
                    partition_id = partition_id.decode("utf-8", errors="replace").rstrip("\x00")

                # WinINET spreads a container's cached files across a few
                # randomly named subdirectories and stores their names
                # concatenated, eight characters each, in one column. Each
                # record carries an index into this list, so it is split
                # here to place a filename on disk.
                secure_raw = rec.get("SecureDirectories")
                if isinstance(secure_raw, bytes):
                    secure_raw = secure_raw.decode("utf-8", errors="replace")
                secure_raw = (secure_raw or "").rstrip("\x00").strip()
                # dissect renders an absent column as the string "None".
                if secure_raw in ("None", ""):
                    secure_names = []
                else:
                    secure_names = [secure_raw[i:i + SECURE_DIR_NAME_LEN]
                                    for i in range(0, len(secure_raw),
                                                   SECURE_DIR_NAME_LEN)]
                    # A trailing fragment is not a directory name. Keep only
                    # whole ones rather than emit a truncated path.
                    secure_names = [s for s in secure_names
                                    if len(s) == SECURE_DIR_NAME_LEN]

                meta = {
                    "ContainerId": cid,
                    "Name": name,
                    "Directory": directory,
                    "SecureDirectoryNames": secure_names,
                    "PartitionId": partition_id,
                    "Flags": flags,
                    "Size": size,
                    "Limit": limit,
                    "LastScavengeTime": filetime_to_str(last_scavenge),
                    "LastAccessTime": filetime_to_str(last_access),
                    # The raw FILETIMEs alongside the formatted strings,
                    # for the same reason the HSTS pin keeps Expires_raw:
                    # views/containers.py declares both of these columns
                    # kind="time", and a pre-formatted string in a time
                    # column cannot be compared by record_filter's
                    # before/after/between/on/last-N-days operators, nor
                    # ordered by anything but its own characters. Kept as
                    # ints (0 for a container never scavenged, which is
                    # what the table itself stores) rather than as
                    # datetimes, so this module keeps deciding nothing
                    # about presentation.
                    "LastScavengeTime_raw": self._safe_int(last_scavenge),
                    "LastAccessTime_raw": self._safe_int(last_access),
                    "EntryMaxAge": entry_max_age,
                    "TableName": f"Container_{cid}",
                    "RecordCount": 0,
                }

                # Mark table existence; actual count is set after parsing
                tbl_name = f"Container_{cid}"
                meta["HasTable"] = tbl_name in self.table_names

                self.containers_meta.append(meta)
                self.container_map[cid] = name
                self.container_type_map[cid] = self.get_container_type(cid)
            except Exception:
                continue

    def get_table_type(self, table_name: str) -> str:
        """Classify any table name into a category."""
        tl = table_name.lower()
        if tl.startswith("container_"):
            try:
                cid = int(table_name.split("_", 1)[1])
                return self.container_type_map.get(cid, "Container")
            except (ValueError, IndexError):
                return "Container"
        if tl == "containers":
            return "Containers (Registry)"
        if tl.startswith("msysobjects"):
            return "System Catalog"
        if "blobentry" in tl:
            return "BLOB Entries"
        if "cookieentry" in tl:
            return "Cookie Entries"
        if "hstsentryex" in tl or "hstsentry" in tl:
            return "HSTS Entries"
        if "dependencyentry" in tl:
            return "Dependency Entries"
        if "appcache" in tl and "entry" in tl:
            return "AppCache Entries"
        if "appcache" in tl:
            return "AppCache"
        if "leakfiles" in tl:
            return "Leak Files"
        if tl == "partitionsex":
            return "Partitions"
        return "System"

    def get_table_display_name(self, table_name: str) -> str:
        """Get a human-readable display name for a table."""
        # For Container_N tables, include container name and type
        if table_name.startswith("Container_"):
            try:
                cid = int(table_name.split("_", 1)[1])
                cname = self.container_map.get(cid, "")
                ctype = self.container_type_map.get(cid, "")
                if cname:
                    return f"{table_name} [{ctype}] {cname}"
                return f"{table_name} [{ctype}]"
            except (ValueError, IndexError):
                pass
        return table_name

    def get_container_name_for_table(self, table_name: str) -> str:
        """Return the container name if this is a Container_N table, else ''."""
        if table_name.startswith("Container_"):
            try:
                cid = int(table_name.split("_", 1)[1])
                return self.container_map.get(cid, "")
            except (ValueError, IndexError):
                pass
        return ""

    def get_container_type(self, cid: int) -> str:
        name = self.container_map.get(cid, "")
        if not name:
            return "Unknown"
        name_lower = name.lower()
        if "history" in name_lower or name_lower.startswith("mshist"):
            return "History"
        if "content" in name_lower:
            return "Content"
        if "cookie" in name_lower:
            return "Cookies"
        if "iedownload" in name_lower:
            return "Downloads"
        if "domstore" in name_lower:
            return "DOMStore"
        if "iecompat" in name_lower:
            return "Compatibility"
        if "backgroundtransfer" in name_lower:
            return "BackgroundTransfer"
        return name

    def parse_all_entries(self, progress_callback=None) -> list:
        self.all_entries = []
        if not self.db:
            return self.all_entries

        self.parse_stats = {"parsed": 0, "skipped": 0, "errors": 0}
        parsed = 0
        container_counts = {}

        for meta in self.containers_meta:
            cid = meta["ContainerId"]
            tbl_name = meta["TableName"]
            container_name = meta["Name"] or "Unknown"
            container_type = self.get_container_type(cid)

            if not meta.get("HasTable", False):
                self.decision_log.append(
                    f"{tbl_name} ({container_name}): registered in Containers but table absent")
                continue

            try:
                table = self.db.table(tbl_name)
            except Exception as e:
                self.decision_log.append(f"{tbl_name}: SKIPPED — {e}")
                self.parse_stats["skipped"] += 1
                continue

            count = 0
            errors = 0
            for rec in ese_records.live_records(table):
                try:
                    entry = self._parse_record(rec, cid, container_name, container_type)
                    if entry:
                        # Where this record's file was recorded on disk.
                        # Done here for live records; normalise_record does
                        # the same for carved ones.
                        folder, path, subdir = resolve_cache_location(
                            entry, meta)
                        entry["CacheFolder"] = folder
                        entry["CachedFilePath"] = path
                        entry["SecureDirectoryName"] = subdir
                        self.all_entries.append(entry)
                        self.parse_stats["parsed"] += 1
                    else:
                        errors += 1
                except Exception:
                    errors += 1

                count += 1
                parsed += 1
                if progress_callback and parsed % 200 == 0:
                    progress_callback(parsed, 0)

            container_counts[cid] = count
            if errors:
                self.parse_stats["errors"] += errors
                self.decision_log.append(
                    f"{tbl_name} ({container_name}): {errors}/{count} records failed to parse")

        # Update container meta with actual record counts
        for meta in self.containers_meta:
            cid = meta["ContainerId"]
            if cid in container_counts:
                meta["RecordCount"] = container_counts[cid]

        # Modern Win11 auxiliary tables (cookies, HSTS, cert store, leaks, appcache)
        self._parse_modern_tables(progress_callback)

        # Row counts for EVERY table, so the browser sidebar can state how many
        # records each holds instead of leaving most of them blank. Cheap: the
        # whole catalogue counts in well under a second.
        self.count_all_tables()

        # Time zone recovery: SPS id 24 is local time and tracks
        # ModifiedTime, so each History record's delta observes the
        # machine's UTC offset. The modal offset is adopted, never a median:
        # across DST the two offsets are an hour apart and a median can fall
        # between them (engine/local_clock.py). MSHist records are excluded:
        # their ModifiedTime is itself local.
        observations = local_clock.zone_observations(self.all_entries)
        self.zone_observations = observations
        offset = local_clock.recover_zone(observations)
        if offset is not None:
            modes = local_clock.offset_modes(observations)
            self.derived_tz_offset_seconds = offset
            self.derived_tz_label = local_clock.zone_label(offset)
            self.decision_log.append(
                f"Machine timezone recovered from SPS id-24 deltas: "
                f"{self.derived_tz_label} (modal offset, "
                f"{dict(modes)[offset]} of n={len(observations)})")
            if len(modes) > 1:
                self.decision_log.append(
                    "The exhibit shows %d UTC offsets (DST or a zone "
                    "change): %s. Each MSHist record takes the offset of "
                    "its History twin, else the one observed nearest in "
                    "time; no offset is averaged."
                    % (len(modes), ", ".join(
                        "%s on %d record(s)" % (local_clock.zone_label(o), n)
                        for o, n in modes)))

        # MSHist containers store ModifiedTime on the LOCAL clock
        # (engine/local_clock.py): stamp each one's offset so every
        # consumer can derive UTC -- or say that it cannot.
        stamped = local_clock.stamp_local_clock(
            self.all_entries, self.derived_tz_offset_seconds, observations)
        if stamped:
            self.decision_log.append(
                "%d MSHist record(s): ModifiedTime read as LOCAL wall-clock; "
                "UTC %s" % (stamped,
                            ("derived with %s" % local_clock.zone_label(
                                self.derived_tz_offset_seconds))
                            if self.derived_tz_offset_seconds is not None
                            else "not stated (no zone recovered)"))

        if progress_callback:
            progress_callback(parsed, parsed)

        return self.all_entries

    # ── Modern Win11 auxiliary tables ────────────────────────────────

    def _parse_modern_tables(self, progress_callback=None):
        self.cookie_entries = []
        self.hsts_entries = []
        self.cert_entries = []
        self.leak_files = []
        self.appcache_entries = []

        for tname in self.table_names:
            try:
                if tname.startswith("CookieEntryEx_"):
                    self._parse_cookie_table(tname)
                elif tname.startswith("HstsEntryEx_"):
                    self._parse_hsts_table(tname)
                elif tname.startswith("BlobEntry_"):
                    self._parse_blob_table(tname)
                elif tname.startswith("AppCacheEntryEx_"):
                    self._parse_appcache_table(tname)
                elif tname == "LeakFiles":
                    self._parse_leakfiles()
            except Exception as e:
                self.decision_log.append(f"{tname}: SKIPPED — {e}")
                self.parse_stats["skipped"] += 1

    @staticmethod
    def _unreverse_domain(rdomain: str) -> str:
        """'com.microsoft.login' -> 'login.microsoft.com'."""
        if not rdomain or rdomain.startswith(":"):
            return rdomain or ""
        return ".".join(reversed(rdomain.split(".")))

    def _table_partition_context(self, tname: str) -> tuple:
        try:
            suffix = int(tname.rsplit("_", 1)[1])
        except (ValueError, IndexError):
            return "", {}
        p = self.partition_for_suffix(suffix)
        return p.get("PartitionId", ""), p

    def _parse_cookie_table(self, tname: str):
        table = self.db.table(tname)
        part_id, part = self._table_partition_context(tname)
        for rec in ese_records.live_records(table):
            name = rec.get("Name")
            value = rec.get("Value")
            rdomain = self._safe_str(rec.get("RDomain"))
            flags = self._safe_int(rec.get("Flags"))
            self.cookie_entries.append({
                "Table": tname,
                "PartitionId": part_id,
                "AppDirectory": part.get("Directory", ""),
                "EntryId": self._safe_int(rec.get("EntryId")),
                "Domain": self._unreverse_domain(rdomain),
                "RDomain": rdomain,
                "Path": self._safe_str(rec.get("Path")),
                "Name": self._safe_str(name),
                "Value": self._safe_str(value),
                "Flags": flags,
                "IsSecure": bool(flags & 0x1),       # observed bit patterns; derived
                "Expires": filetime_to_str(rec.get("Expires")),
                "Expires_raw": self._safe_int(rec.get("Expires")),
                "LastModified": filetime_to_str(rec.get("LastModified")),
                "LastModified_raw": self._safe_int(rec.get("LastModified")),
            })
            self.parse_stats["parsed"] += 1

    def _parse_hsts_table(self, tname: str):
        table = self.db.table(tname)
        part_id, part = self._table_partition_context(tname)
        NEVER = 0x7FFFFFFFFFFFFFFF
        for rec in ese_records.live_records(table):
            rdomain = self._safe_str(rec.get("RDomain"))
            if rdomain == ":version":
                continue  # schema marker row, not evidence
            exp_raw = self._safe_int(rec.get("Expires"))
            used_raw = self._safe_int(rec.get("LastTimeUsed"))
            self.hsts_entries.append({
                "Table": tname,
                "PartitionId": part_id,
                "EntryId": self._safe_int(rec.get("EntryId")),
                "Domain": self._unreverse_domain(rdomain),
                "IncludeSubdomains": bool(self._safe_int(rec.get("IncludeSubdomains")) & 1),
                "Expires": "never" if exp_raw == NEVER else filetime_to_str(exp_raw),
                # The int as stored, sentinel included. LastTimeUsed_raw
                # above normalises NEVER to 0, since an unused pin has no
                # last-use instant; for Expires, NEVER is a recorded fact
                # ("does not expire"), so it is kept, and the shell can show
                # a sortable datetime or "never".
                "Expires_raw": exp_raw,
                "LastTimeUsed": "" if used_raw == NEVER else filetime_to_str(used_raw),
                "LastTimeUsed_raw": 0 if used_raw == NEVER else used_raw,
            })
            self.parse_stats["parsed"] += 1

    def _parse_blob_table(self, tname: str):
        """BlobEntry_* — TLS certificate store: host:port + cert + SHA-1 print."""
        table = self.db.table(tname)
        part_id, part = self._table_partition_context(tname)
        for rec in ese_records.live_records(table):
            url = self._safe_str(rec.get("Url"))
            if not url:
                continue
            data = rec.get("Data")
            data2 = rec.get("Data2")
            is_cert = isinstance(data, bytes) and len(data) > 8 and data[4:8] == b"CERT"
            self.cert_entries.append({
                "Table": tname,
                "PartitionId": part_id,
                "EntryId": self._safe_int(rec.get("EntryId")),
                "HostPort": url,
                "Type": self._safe_int(rec.get("Type")),
                "IsCertificate": is_cert,
                "ModifiedTime": filetime_to_str(rec.get("ModifiedTime")),
                "ModifiedTime_raw": self._safe_int(rec.get("ModifiedTime")),
                "Thumbprint": data2.hex() if isinstance(data2, bytes) else "",
                "BlobSize": len(data) if isinstance(data, bytes) else 0,
                "Blob_raw": data if isinstance(data, bytes) else None,
            })
            self.parse_stats["parsed"] += 1

    def _parse_appcache_table(self, tname: str):
        table = self.db.table(tname)
        for rec in ese_records.live_records(table):
            url = self._safe_str(rec.get("Url"))
            if not url:
                continue
            self.appcache_entries.append({
                "Table": tname,
                "EntryId": self._safe_int(rec.get("EntryId")),
                "Url": url,
                "Type": self._safe_int(rec.get("Type")),
                "FileSize": self._safe_int(rec.get("FileSize")),
                "ModifiedTime": filetime_to_str(rec.get("ModifiedTime")),
                "Filename": self._safe_str(rec.get("Filename")),
            })
            self.parse_stats["parsed"] += 1

    def _parse_leakfiles(self):
        """LEAK records: cache files that could not be deleted — they survive
        normal deletion and are forensic gold."""
        table = self.db.table("LeakFiles")
        for rec in ese_records.live_records(table):
            self.leak_files.append({
                "LeakId": self._safe_int(rec.get("LeakId")),
                "Filename": self._safe_str(rec.get("Filename")),
                "CreationTime": filetime_to_str(rec.get("CreationTime")),
                "CreationTime_raw": self._safe_int(rec.get("CreationTime")),
            })
            self.parse_stats["parsed"] += 1

    def _safe_str(self, val) -> str:
        if val is None:
            return ""
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="replace").rstrip("\x00")
        return str(val)

    def _safe_int(self, val) -> int:
        if val is None:
            return 0
        if isinstance(val, int):
            return val
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    def _parse_record(self, rec, cid, container_name, container_type) -> Optional[dict]:
        try:
            url = self._safe_str(rec.get("Url"))
            flags_val = self._safe_int(rec.get("Flags"))
            # InPrivate bit 0x08 is only meaningful on History-type records;
            # on Content records the same bit is wininet EDITED_CACHE_ENTRY.
            is_inprivate = bool(flags_val & 0x08) and container_type == "History"

            sync_time_raw = self._safe_int(rec.get("SyncTime"))
            creation_time_raw = self._safe_int(rec.get("CreationTime"))
            expiry_time_raw = self._safe_int(rec.get("ExpiryTime"))
            modified_time_raw = self._safe_int(rec.get("ModifiedTime"))
            accessed_time_raw = self._safe_int(rec.get("AccessedTime"))
            post_check_time_raw = self._safe_int(rec.get("PostCheckTime"))

            entry = {
                "EntryId": self._safe_int(rec.get("EntryId")),
                "ContainerId": cid,
                "ContainerName": container_name,
                "ContainerType": container_type,
                "CacheId": self._safe_int(rec.get("CacheId")),
                "UrlHash": self._safe_int(rec.get("UrlHash")),
                "SecureDirectory": self._safe_int(rec.get("SecureDirectory")),
                "FileSize": self._safe_int(rec.get("FileSize")),
                "Type": self._safe_int(rec.get("Type")),
                "Flags": flags_val,
                "IsInPrivate": is_inprivate,
                "AccessCount": self._safe_int(rec.get("AccessCount")),
                "SyncTime": filetime_to_str(sync_time_raw),
                "CreationTime": filetime_to_str(creation_time_raw),
                "ExpiryTime": filetime_to_str(expiry_time_raw),
                "ModifiedTime": filetime_to_str(modified_time_raw),
                "AccessedTime": filetime_to_str(accessed_time_raw),
                "PostCheckTime": filetime_to_str(post_check_time_raw),
                "SyncTime_raw": sync_time_raw,
                "CreationTime_raw": creation_time_raw,
                "ExpiryTime_raw": expiry_time_raw,
                "ModifiedTime_raw": modified_time_raw,
                "AccessedTime_raw": accessed_time_raw,
                "PostCheckTime_raw": post_check_time_raw,
                "SyncCount": self._safe_int(rec.get("SyncCount")),
                "ExemptionDelta": self._safe_int(rec.get("ExemptionDelta")),
                "Url": url,
                "Filename": self._safe_str(rec.get("Filename")),
                "FileExtension": self._safe_str(rec.get("FileExtension")),
                "RedirectUrl": self._safe_str(rec.get("RedirectUrl")),
                "RequestHeaders": {},
                "ResponseHeaders": {},
                "RequestHeaders_raw": None,
                "ResponseHeaders_raw": None,
                "SPS_Properties": {},
                # SPS-derived history forensics (empty unless History w/ SPS blob)
                "SPS_VisitCount": None,
                "SPS_LastVisitLocal": "",
                "SPS_LastVisitLocal_raw": None,
                "SPS_PageTitle": "",
                # iedownload-derived download forensics
                "DownloadPath": "",
                "DownloadSourceUrl": "",
                "DownloadSize": None,
                "DownloadTime": "",
                # URL forensics
                "CleanUrl": "",
                "UrlUsername": "",
                "MSHistFrom": "",
                "MSHistTo": "",
                "SearchTerms": "",
                "IsLocalFile": False,
                "IsLeak": url.upper().startswith("LEAK"),
                "FlagsDecoded": decode_flags(flags_val, container_type),
                "BlobClass": "",
            }

            # URL structure: strip Visited:/MSHist prefixes, extract username
            parts = split_history_url(url)
            entry["CleanUrl"] = parts["clean_url"]
            entry["UrlUsername"] = parts["username"]
            entry["MSHistFrom"] = parts["mshist_from"]
            entry["MSHistTo"] = parts["mshist_to"]
            entry["IsLocalFile"] = parts["clean_url"].lower().startswith("file:")
            entry["SearchTerms"] = extract_search_terms(parts["clean_url"])

            # Decode header blobs by observed class, not just container type
            try:
                req_blob = rec.get("RequestHeaders")
                resp_blob = rec.get("ResponseHeaders")
                if isinstance(req_blob, bytes):
                    entry["RequestHeaders_raw"] = req_blob
                if isinstance(resp_blob, bytes):
                    entry["ResponseHeaders_raw"] = resp_blob

                blob = resp_blob if isinstance(resp_blob, bytes) else None
                blob_class = sps_decoder.classify_response_headers(blob)
                entry["BlobClass"] = blob_class

                if blob_class == "http":
                    entry["RequestHeaders"] = decode_content_headers(
                        req_blob if isinstance(req_blob, bytes) else None)
                    entry["ResponseHeaders"] = decode_content_headers(blob)
                elif blob_class == "sps":
                    fx = sps_decoder.extract_history_forensics(blob)
                    entry["SPS_Properties"] = {
                        pid: p["value"] for pid, p in fx["all_properties"].items()}
                    entry["SPS_VisitCount"] = fx["visit_count"]
                    if fx["last_visit_local"]:
                        entry["SPS_LastVisitLocal"] = stamp_str(
                            fx["last_visit_local"], "LOCAL")
                        entry["SPS_LastVisitLocal_raw"] = fx["last_visit_local_raw"]
                    if fx["page_title"]:
                        entry["SPS_PageTitle"] = fx["page_title"]

                if container_type == "Downloads" and blob:
                    dl = download_decoder.decode_download_blob(blob)
                    entry["DownloadPath"] = dl["local_path"] or ""
                    entry["DownloadSourceUrl"] = dl["source_url"] or ""
                    entry["DownloadSize"] = dl["file_size"]
                    if dl["download_time_utc"]:
                        entry["DownloadTime"] = stamp_str(
                            dl["download_time_utc"], "UTC")
            except Exception:
                pass

            return entry
        except Exception:
            return None

    def get_database_info(self) -> dict:
        file_size = 0
        if self.db_path and os.path.exists(self.db_path):
            file_size = os.path.getsize(self.db_path)
        state_txt = {1: "Clean shutdown", 2: "Dirty shutdown",
                     3: "Being converted"}.get(self.db_state, str(self.db_state))
        info = {
            "path": self.db_path or "",
            "file_size": file_size,
            "tables": self.table_names,
            "table_count": len(self.table_names),
            "container_count": len(self.containers_meta),
            "total_entries": len(self.all_entries),
            "db_state": self.db_state,
            "db_state_text": state_txt,
            "sha256": self.source_hashes.get(
                os.path.basename(self.db_path or ""), ""),
            "source_hashes": dict(self.source_hashes),
            "parse_stats": dict(self.parse_stats),
            "decision_log": list(self.decision_log),
            "derived_tz": self.derived_tz_label,
            "derived_tz_offset_seconds": self.derived_tz_offset_seconds,
            "clock_offsets": local_clock.offset_periods(
                self.zone_observations),
            "cookie_count": len(self.cookie_entries),
            "hsts_count": len(self.hsts_entries),
            "cert_count": len(self.cert_entries),
            "leak_count": len(self.leak_files),
        }
        return info

    def get_table_columns(self, table_name: str) -> list:
        """Get column names for a raw ESE table."""
        if not self.db or table_name not in self.table_names:
            return []
        try:
            table = self.db.table(table_name)
            cols = []
            for col in table.columns:
                cols.append(col.name)
            return cols
        except Exception:
            return []

    def get_table_column_info(self, table_name: str) -> list:
        """Get column names and types for a raw ESE table."""
        if not self.db or table_name not in self.table_names:
            return []
        try:
            table = self.db.table(table_name)
            cols = []
            for col in table.columns:
                col_type = str(getattr(col, 'type', 'unknown'))
                cols.append({"name": col.name, "type": col_type})
            return cols
        except Exception:
            return []

    def get_table_rows(self, table_name: str, limit: int = 500, offset: int = 0) -> tuple:
        """Browse raw ESE table. Returns (column_names, rows_as_lists).
        Values are converted to display-friendly strings."""
        if not self.db or table_name not in self.table_names:
            return [], []
        try:
            table = self.db.table(table_name)
            col_names = [col.name for col in table.columns]
            rows = []
            count = 0
            total = 0
            for rec in ese_records.live_records(table):
                total += 1
                if count < offset:
                    count += 1
                    continue
                if count >= offset + limit:
                    # Still count remaining rows for total
                    continue
                row = []
                for cname in col_names:
                    val = rec.get(cname)
                    row.append(self._format_raw_value(val, cname))
                rows.append(row)
                count += 1
            # Cache the total
            self.table_row_counts[table_name] = total
            return col_names, rows
        except Exception:
            return [], []

    def count_all_tables(self, progress_callback=None) -> dict:
        """Count rows in every table once and cache it."""
        for i, tname in enumerate(self.table_names):
            if tname not in self.table_row_counts:
                self.get_table_row_count(tname)
            if progress_callback and i % 10 == 0:
                progress_callback(i, len(self.table_names))
        return dict(self.table_row_counts)

    def get_table_row_count(self, table_name: str) -> int:
        """Count rows in a raw ESE table (uses cache if available)."""
        if table_name in self.table_row_counts:
            return self.table_row_counts[table_name]
        if not self.db or table_name not in self.table_names:
            return 0
        try:
            table = self.db.table(table_name)
            count = 0
            for _ in ese_records.live_records(table):
                count += 1
            self.table_row_counts[table_name] = count
            return count
        except Exception:
            return 0

    # Context shown either side of a match found inside a blob.
    _MATCH_CONTEXT = 60

    def _searchable_text(self, val, display: str) -> str:
        """Everything in a value that a search should be able to match.

        `display` is a summary: for a binary blob, a hex preview of the
        first 32 bytes. The strings deeper inside a property store or a
        UTF-16 blob are matched too.
        """
        if not isinstance(val, (bytes, bytearray)):
            return display
        # A value that already decoded to readable text is fully searchable.
        if not display.startswith("["):
            return display
        raw = bytes(val)
        parts = [display, raw.hex(" ")]
        for encoding in ("ascii", "utf-16-le"):
            try:
                parts.append(raw.decode(encoding, "replace"))
            except Exception:
                continue
        return "\n".join(parts)

    def _match_context(self, haystack: str, keyword: str) -> str:
        """A window around the first hit, so the reported value shows it."""
        at = haystack.lower().find(keyword)
        if at == -1:
            return ""
        start = max(0, at - self._MATCH_CONTEXT)
        end = min(len(haystack), at + len(keyword) + self._MATCH_CONTEXT)
        lead = "\u2026" if start > 0 else ""
        tail = "\u2026" if end < len(haystack) else ""
        return (lead + haystack[start:end] + tail).replace("\n", " ")

    def _format_raw_value(self, val, col_name: str = "") -> str:
        """See format_cell -- kept as a method for its existing callers."""
        return format_cell(val, col_name)

    def mshist_entry(self, container_id, entry_id):
        """The parsed MSHist record stored at (ContainerId, EntryId), or
        None. Indexed once per parse: all_entries is replaced, never
        appended to after parse_all_entries, so the identity of the list
        is what the cached index is keyed on."""
        entries = getattr(self, "all_entries", None)
        if entries is None:
            entries = self.all_entries = []
        cached = getattr(self, "_mshist_index", None)
        if cached is None or cached[0] is not entries:
            cached = (entries, local_clock.mshist_entry_index(entries))
            self._mshist_index = cached
        return cached[1].get((container_id, entry_id))

    def adopt_clock(self, snapshot):
        """Take the zone and each MSHist record's offset from a parse done
        elsewhere (local_clock.clock_snapshot) -- for a parser opened only
        to search, which never parses entries and so has neither. Nothing
        is written to the evidence."""
        if not snapshot:
            return
        zone, offsets = snapshot
        self.derived_tz_offset_seconds = zone
        if getattr(self, "all_entries", None) is None:
            self.all_entries = []
        self._mshist_index = (self.all_entries, {
            key: {"MSHistFrom": True, local_clock.TZ_OFFSET_KEY: offset}
            for key, offset in (offsets or {}).items()})

    def stored_local_cell(self, table_name, column, value, entry_id):
        """The local-clock reading of one stored cell, or "" when the cell
        is not on the local clock. Only an MSHist container's ModifiedTime
        is (engine/local_clock.py); format_cell stays clock-blind."""
        if (column != "ModifiedTime" or isinstance(value, bool)
                or not isinstance(value, int)
                or not self.get_container_name_for_table(
                    table_name).lower().startswith("mshist")):
            return ""
        try:
            cid = int(table_name.split("_", 1)[1])
        except (ValueError, IndexError):
            return ""
        return local_clock.describe_stored_cell(
            self.mshist_entry(cid, entry_id), value,
            self.derived_tz_offset_seconds)

    def _format_value_for_detail(self, val, col_name: str = "") -> tuple:
        """Format value with rich type info for detail view.
        Returns (display_string, type_label, is_binary)."""
        if val is None:
            return ("", "NULL", False)

        if isinstance(val, bytes):
            if len(val) == 0:
                return ("", "BINARY (0B)", True)
            if col_name in TEXT_COLUMNS:
                try:
                    decoded = val.decode("utf-8", errors="replace").rstrip("\x00")
                    if decoded:
                        return (decoded, f"TEXT ({len(val)}B)", False)
                except Exception:
                    pass
            try:
                decoded = val.decode("utf-8")
                decoded = decoded.rstrip("\x00")
                if decoded and all(c.isprintable() or c in ('\r', '\n', '\t') for c in decoded):
                    return (decoded, f"TEXT ({len(val)}B)", False)
            except (UnicodeDecodeError, AttributeError):
                pass
            blob_type = detect_blob_type(val)
            # Full hex dump for detail
            hex_lines = []
            for i in range(0, min(len(val), 4096), 16):
                row = val[i:i+16]
                hex_part = " ".join(f"{b:02X}" for b in row)
                ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
                hex_lines.append(f"{i:04X}  {hex_part:<48s}  {ascii_part}")
            if len(val) > 512:
                hex_lines.append(f"... {len(val):,} bytes total — open Properties for the full blob")
            return ("\n".join(hex_lines), f"{blob_type} ({len(val)}B)", True)

        if isinstance(val, bool):
            return ("True" if val else "False", "BOOL", False)

        if isinstance(val, int):
            if col_name in FILETIME_COLUMNS:
                dt_str = filetime_to_str(val)
                if dt_str:
                    return (f"{dt_str}  (raw: {val})", "FILETIME", False)
            if val > 100000000000000 and col_name not in {"UrlHash", "ExemptionDelta"}:
                dt_str = filetime_to_str(val)
                if dt_str:
                    return (f"{dt_str}  (raw: {val})", "FILETIME", False)
            return (str(val), "INT", False)

        if isinstance(val, float):
            return (f"{val:.6g}", "REAL", False)

        return (str(val), "TEXT", False)

    def get_table_rows_raw(self, table_name: str, limit: int = 500, offset: int = 0) -> tuple:
        """Browse raw ESE table. Returns (column_names, rows_as_raw_values).
        Values are NOT converted — raw Python objects for detail view usage."""
        if not self.db or table_name not in self.table_names:
            return [], []
        try:
            table = self.db.table(table_name)
            col_names = [col.name for col in table.columns]
            rows = []
            count = 0
            for rec in ese_records.live_records(table):
                if count < offset:
                    count += 1
                    continue
                if count >= offset + limit:
                    break
                row = []
                for cname in col_names:
                    row.append(rec.get(cname))
                rows.append(row)
                count += 1
            return col_names, rows
        except Exception:
            return [], []

    def find_row_ordinal(self, table_name: str, key: dict):
        """0-based position of the row whose columns equal `key`, counted
        over live_records as get_table_rows_raw counts, so
        ordinal // page_size is the page that holds it. None when the table
        or the row is not there. Found by key, never by a remembered
        position, so pagination and deleted-record stubs cannot shift it.

        A linear walk (about 15 us a record); the shell runs it off the GUI
        thread for a large table (shell/row_locate_runner.py)."""
        if not self.db or table_name not in self.table_names or not key:
            return None
        try:
            wanted = [(col, int(value)) for col, value in key.items()]
            table = self.db.table(table_name)
            for ordinal, rec in enumerate(ese_records.live_records(table)):
                if all(self._key_cell_equals(rec.get(col), value)
                       for col, value in wanted):
                    return ordinal
        except Exception:
            return None
        return None

    @staticmethod
    def _key_cell_equals(cell, value):
        """A stored key cell equals `value` only when it is THERE: never
        _safe_int, which reads a missing/NULL cell as 0 and would take a
        row without the column for the row whose key is 0."""
        if cell is None or isinstance(cell, bool):
            return False
        try:
            return int(cell) == value
        except (TypeError, ValueError):
            return False

    @staticmethod
    def raw_type_name(value) -> str:
        """What the database stores in this cell."""
        if value is None:
            return "null"
        if isinstance(value, (bytes, bytearray, memoryview)):
            return "binary"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "text"
        return type(value).__name__

    @classmethod
    def raw_rendering(cls, value) -> str:
        """The stored value written out as stored, not as displayed.

        A displayed value has been decoded: a history URL loses its
        "Visited: user@" prefix, a property store becomes a visit count, a
        blob becomes a preview. This is what the decoding started from, so
        the two can be checked against each other in the same row.

        Binary is hex. Text is written with escapes, so a trailing NUL, a
        stray tab or a right-to-left override is visible, which for a domain
        name separates a homograph from an ordinary hostname.

        Always the whole value, every byte and every escaped character. How
        much a grid cell paints is decided by the row cap
        (records_table.ROW_LINE_CAP), not here.
        """
        if value is None:
            return ""
        if isinstance(value, memoryview):
            value = value.tobytes()
        if isinstance(value, (bytes, bytearray)):
            return " ".join("%02X" % b for b in bytes(value))
        if isinstance(value, str):
            # ascii() escapes control characters, bidi overrides and anything
            # non-ASCII, then the quotes it adds are stripped -- the point is
            # to expose the characters, not to quote them.
            return ascii(value)[1:-1]
        return str(value)

    def search_all_tables(self, keyword: str, table_filter: str = "",
                          max_results: int = 0, progress_callback=None) -> list:
        """Search across all tables, returning results with container
        context.

        max_results=0 means no limit: a search never stops early and hides
        matching evidence.

        progress_callback(rows_scanned, tables_done, tables_total,
        table_name) is called every _SEARCH_PROGRESS_ROWS rows and at every
        table boundary. All four are real counts: tables_total is
        len(tables), rows_scanned a running total of rows read. No
        percentage is computed, since a few tables hold most of the rows. A
        callback that raises SearchCancelled stops the scan.

        A table that cannot be read is recorded in
        self.search_skipped_tables as (name, reason), so the view can state
        which tables were not searched.
        """
        self.search_skipped_tables = []
        if not self.db or not keyword:
            return []
        kw = keyword.lower()
        results = []
        tables = [table_filter] if table_filter else self.table_names
        tables_total = len(tables)
        tables_done = 0
        rows_scanned = 0
        for tname in tables:
            if tname not in self.table_names:
                continue
            try:
                table = self.db.table(tname)
                col_names = [col.name for col in table.columns]
                # Get container context for this table
                container_name = self.get_container_name_for_table(tname)
                table_type = self.get_table_type(tname)
                row_idx = 0
                for rec in ese_records.live_records(table):
                    row_idx += 1
                    rows_scanned += 1
                    if (progress_callback is not None
                            and rows_scanned % _SEARCH_PROGRESS_ROWS == 0):
                        progress_callback(rows_scanned, tables_done,
                                          tables_total, tname)
                    # Decode each column once and reuse it for the context
                    # row; dissect's per-cell decode is most of a search's
                    # cost.
                    matched_cols = []
                    row_vals = {}
                    deep_hits = {}
                    # The value as the database holds it, kept for columns
                    # that matched: a decoded value (a URL without its
                    # "Visited: user@" prefix, a blob preview) and the stored
                    # bytes are different evidence, and both are shown. Rows
                    # that do not match cost nothing.
                    raw_by_col = {}
                    for cname in col_names:
                        raw_val = rec.get(cname)
                        # An MSHist ModifiedTime is LOCAL: it reads, and is
                        # matched, as local plus the derived UTC -- never
                        # as its local digits labelled UTC.
                        display = (self.stored_local_cell(
                            tname, cname, raw_val, rec.get("EntryId"))
                            if cname == "ModifiedTime" else "")
                        if not display:
                            display = self._format_raw_value(raw_val, cname)
                        row_vals[cname] = display
                        if display and kw in display.lower():
                            matched_cols.append(cname)
                            raw_by_col[cname] = raw_val
                            continue
                        # Not in the display — look inside the value itself.
                        searchable = self._searchable_text(raw_val, display)
                        if searchable is not display and kw in searchable.lower():
                            matched_cols.append(cname)
                            raw_by_col[cname] = raw_val
                            deep_hits[cname] = self._match_context(searchable, kw)
                            continue
                        # What an examiner types, against the stored
                        # spelling: "Tax%20docs", "how+to", "file:///C:/".
                        for alt in other_spellings(display):
                            if kw in alt.lower():
                                matched_cols.append(cname)
                                raw_by_col[cname] = raw_val
                                deep_hits[cname] = self._match_context(alt, kw)
                                break
                    if matched_cols:
                        # Get URL if available
                        url = row_vals.get("Url", "")
                        # The row's identity: the table's own key, read in
                        # this same pass, so a hit can be found again by
                        # key and never by a position that moves.
                        row_key = None
                        for key_col in ("EntryId", "LeakId"):
                            key_val = rec.get(key_col)
                            if (key_col in col_names
                                    and isinstance(key_val, int)
                                    and not isinstance(key_val, bool)):
                                row_key = {key_col: key_val}
                                break
                        results.append({
                            "row_key": row_key,
                            "table": tname,
                            "table_type": table_type,
                            "container_name": container_name,
                            "column": matched_cols[0],  # Primary match column
                            "matched_columns": matched_cols,
                            # A hit inside a blob shows the text around it,
                            # not the preview.
                            "match_value": deep_hits.get(
                                matched_cols[0], row_vals.get(matched_cols[0], "")),
                            "match_in_blob": bool(deep_hits.get(matched_cols[0])),
                            # The same cell as the database stores it, so the
                            # decoded hit can be checked against the bytes it
                            # was decoded from without leaving the results.
                            "match_raw": self.raw_rendering(
                                raw_by_col.get(matched_cols[0])),
                            "match_raw_type": self.raw_type_name(
                                raw_by_col.get(matched_cols[0])),
                            "url": url,
                            "row_index": row_idx,
                            "row": row_vals,
                        })
                    if max_results and len(results) >= max_results:
                        break
            # Before `except Exception`, so a cancellation is not caught
            # by the clause below (see SearchCancelled).
            except SearchCancelled:
                raise
            except Exception as exc:
                # Recorded, not silently skipped (see the docstring).
                self.search_skipped_tables.append((tname, str(exc)))
                continue
            tables_done += 1
            if progress_callback is not None:
                progress_callback(rows_scanned, tables_done, tables_total,
                                  tname)
            if max_results and len(results) >= max_results:
                break
        return results

    def get_tables_grouped(self) -> dict:
        """Group all tables by type for sidebar tree display."""
        groups = {}
        for tname in self.table_names:
            ttype = self.get_table_type(tname)
            if ttype not in groups:
                groups[ttype] = []
            count = self.table_row_counts.get(tname, -1)
            groups[ttype].append({
                "name": tname,
                "display_name": self.get_table_display_name(tname),
                "type": ttype,
                "count": count,
            })
        return groups

    def tombstones(self) -> list:
        """Deleted-record stubs in every table (see ese_records).

        Each stub names the evidence file it lies in (`Source`, the
        database's basename, as a carved record's Source does) and, for a
        Container_N table, its container (`ContainerId`, and
        `ContainerType` from container_type_map): a stub reconstructs no
        columns, but its container is known from the catalogue.

        A table that cannot be walked is recorded in decision_log rather
        than raised: this runs on the recovery worker over dirty evidence,
        and one unreadable page must not stop the scan.

        Computed once and cached."""
        if self._tombstones is not None:
            return self._tombstones
        if not self.db:
            self._tombstones = []
            return self._tombstones
        failures = []
        source = os.path.basename(self.db_path or "")
        stubs = []
        for stub in ese_records.tombstones(self.db.tables(), failures):
            stub["Source"] = source
            table = stub.get("Table") or ""
            cid = None
            if table.startswith("Container_"):
                suffix = table[len("Container_"):]
                if suffix.isdigit():
                    cid = int(suffix)
            stub["ContainerId"] = cid
            stub["ContainerType"] = (self.container_type_map.get(cid)
                                     if cid is not None else None)
            stubs.append(stub)
        for name, exc in failures:
            self.decision_log.append(
                f"{name}: deleted-record stub walk incomplete — {exc}")
        if failures:
            self.decision_log.append(
                f"Deleted-record stubs: {len(failures)} table(s) could not "
                f"be fully walked")
        self._tombstones = stubs
        return self._tombstones

    def close(self):
        self.db = None
        if self.db_file:
            try:
                self.db_file.close()
            except Exception:
                pass
            self.db_file = None
