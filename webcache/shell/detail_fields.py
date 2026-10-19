"""Which fields a record shows, in what order, and what a missing one says.

Qt-free, and separate from record_detail.py, which paints exactly what
fields_for() returns. Which values appear, in what order, with what
wording, and what is said where there is no value, is decided here so it
can be tested without a QApplication.

It lives in shell/ because it needs the engine (evidence_model for the
provenance catalogue, sps_decoder to name a property id, ese_parser to
classify a blob), which widgets/ may not import (tests/test_structure.py),
and a module in views/ could not be imported by the record views.

THREE GUARANTEES

1. NOTHING RECOVERED IS HIDDEN. After the named groups, the sweep
   (_sweep) emits every remaining key under "Other recovered values", so
   a field added to the engine appears here with no UI change.

2. A BLANK IS NEVER A VALUE. Every DetailField.display_value is a
   non-empty string. Where there is no value it is one of the absence
   sentences (provenance.ABSENCE_TOKENS): "the database stored nothing
   here", "this cannot be known from the evidence", "the carve did not
   reach this column" and "this field does not exist for this kind of
   record" are different facts.

3. NO BADGE IS GUESSED. DetailField.field is an explicit key into
   evidence_model.FIELD_PROVENANCE, or None. evidence_model.basis_of()
   defaults to DERIVED, so a key is never derived from the label; None
   paints no badge. Fields such as UrlHealth, Region, RecordEndMode,
   InLiveDb, Encoding, AlsoSeenIn, SecureDirectoryNames, Limit,
   EntryMaxAge and the Fragment* fields are uncatalogued and show none.

COPY, NEVER OPEN. Every value naming a location on the examined machine is
grouped under G_MACHINE and rendered kind="path", and a path field never
has a click target (tests/test_no_open_paths.py).
"""
import datetime

from ..widgets import time_format
import hashlib

from ..engine import ese_parser, evidence_model, local_clock, sps_decoder
from .. import provenance
from . import blob_source, record_kinds
from .headers_loader import (CLIENT_IP_NOTE, HEADER_INTEREST,
                             STATUS_LINE_LABEL, duplicates_note, header_pairs)
from .record_kinds import (AGGREGATES, K_CARVED_STRING, K_CARVED_STRUCT,
                           K_CERT, K_CONTAINER, K_COOKIE, K_DOMAIN,
                           K_DOWNLOAD, K_FILE_ACCESS, K_HISTORY, K_HSTS,
                           K_INDICATOR, K_PERIOD, K_PLACE, K_TABLE_ROW,
                           K_TOMBSTONE)

# --- groups -------------------------------------------------------------
#
# ONE canonical order for EVERY record kind, so an examiner learns it once
# and it holds whether they are reading a cookie, a certificate or a string
# pulled out of page slack. A kind that has nothing for a group simply
# omits it; no kind ever reorders them.

#: Only when the carve is not intact, and always first, so a mis-bounded
#: string is not read as a recorded URL.
G_QUALITY = "Carve quality"
#: Only for an AGGREGATE kind. States, before any number, that the row
#: is a summary over N records and not a thing that happened once.
G_AGGREGATE = "This is an aggregate"
G_WHAT = "What this record is"
G_SAYS = "What it says happened"
G_WHEN = "When"
G_FLAGS = "Flags and state"
G_WHERE_DB = "Where it lives in the database"
#: Everything naming a location on the examined machine. kind="path"
#: throughout; never a link. See the module docstring on copy-never-open.
G_MACHINE = "On the examined machine"
G_HOW = "How it was recovered"
#: One row per blob: label, size, detected type and this tool's own hash.
#: Never the bytes.
G_BINARY = "Binary"
#: The members of an aggregate, each openable in its own dialog.
G_RECORDS = "Records"
#: The sweep. ALWAYS LAST, ALWAYS PRESENT.
G_OTHER = "Other recovered values"

GROUPS = (G_QUALITY, G_AGGREGATE, G_WHAT, G_SAYS, G_WHEN, G_FLAGS,
          G_WHERE_DB, G_MACHINE, G_HOW, G_BINARY, G_RECORDS, G_OTHER)

#: The four keys the carve-quality banner claims when it fires. They live
#: under G_HOW the rest of the time -- an intact carve still states its
#: health, it just does not need a banner about it.
_QUALITY_KEYS = ("UrlHealth", "UrlHealthNote", "UrlSalvaged", "UrlSalvageNote")


class _NotEmitted:
    """Sentinel: this field does not apply to this record and no row is
    produced for it.

    A distinct object, because None from _absence_for means "a real value;
    no absence applies".
    """

    __slots__ = ()

    def __repr__(self):
        return "NOT_EMITTED"


NOT_EMITTED = _NotEmitted()


class DetailField:
    """One row of the detail dialog.

    label          what the examiner reads in the field column
    key            the source key, for the sweep's bookkeeping and for tests
    value          the raw value, untouched -- what a byte-exact copy emits
    display_value  what is painted. ALWAYS a non-empty string.
    field          explicit evidence_model key, or None for "uncatalogued"
    kind           "text" | "url" | "path" | "time" | "num" | "flag"
    note           the sub-line under the value; "" when there is none
    absence        one of provenance.ABSENCE_TOKENS, or None for a real value
    raw_value      the paired raw FILETIME, when this field has one
    target         a row dict this field opens (aggregate members only)
    blob_key       the _record key holding this field's bytes (G_BINARY only)
    """

    __slots__ = ("label", "key", "value", "display_value", "field", "kind",
                 "note", "absence", "raw_value", "target", "blob_key")

    def __init__(self, label, key, value, display_value, field=None,
                 kind="text", note="", absence=None, raw_value=None,
                 target=None, blob_key=None):
        self.label = label
        self.key = key
        self.value = value
        self.display_value = display_value
        self.field = field
        self.kind = kind
        self.note = note or ""
        self.absence = absence
        self.raw_value = raw_value
        self.target = target
        self.blob_key = blob_key

    def __repr__(self):
        return "DetailField(%r, %r)" % (self.label, self.display_value)


class FieldGroup:
    __slots__ = ("name", "fields")

    def __init__(self, name, fields):
        self.name = name
        self.fields = list(fields)

    def __repr__(self):
        return "FieldGroup(%r, %d fields)" % (self.name, len(self.fields))


# --- the field table ----------------------------------------------------
#
# (key, group, label, provenance-field, kind). Declaration order is the
# order inside a group. A key not named here is emitted by the sweep under
# G_OTHER with its own key as the label.
#
# Every provenance-field is an explicit key into evidence_model.
# FIELD_PROVENANCE or None; tests/test_detail_fields.py fails on a key the
# catalogue does not have.

#: the engine's own tokens, in words. Shown as "words (token)" so the
#: stored token stays beside what this tool says it means.
TOKEN_WORDS = {
    "RecordEndMode": {
        "sps-212": "ended after its 212-byte property store",
        "http-crlf": "ended at the blank line closing its HTTP headers",
        "http-nul": "ended at a NUL after its HTTP headers",
        "utf16-nul": "ended at a UTF-16 NUL terminator",
        "null-field": "ended at an empty (null) field",
        "long-value-key": "ended at a long-value reference",
        "next-marker": "ended where the next record begins",
        "clean": "ended cleanly",
    },
    "Region": {
        "deleted-record": "a deleted record's space in the database",
        "page-slack": "unused space inside a database page",
        "empty-page": "an empty (freed) database page",
        "transaction-log": "a transaction log file",
    },
}


def token_display(key, value):
    words = TOKEN_WORDS.get(key, {}).get(str(value)) if value else None
    return "%s (%s)" % (words, value) if words else None


_COMMON = (
    # -- what this record is ------------------------------------------
    ("CleanUrl", G_WHAT, "Clean URL", "CleanUrl", "url"),
    ("Url", G_WHAT, "Raw URL (as stored)", "Url", "text"),
    ("Title", G_WHAT, "Page title", "SPS_PageTitle", "text"),
    ("SPS_PageTitle", G_WHAT, "Page title (property store)", "SPS_PageTitle", "text"),
    ("Domain", G_WHAT, "Domain", "Domain", "text"),
    ("RDomain", G_WHAT, "Domain (reversed, as stored)", "RDomain", "text"),
    ("Scheme", G_WHAT, "Scheme", "Scheme", "text"),
    ("UrlCategory", G_WHAT, "URL category", "UrlCategory", "text"),
    ("UrlUsername", G_WHAT, "User name inside the URL", "UrlUsername", "text"),
    ("RedirectUrl", G_WHAT, "Redirect target", "RedirectUrl", "url"),
    ("MSHistFrom", G_WHAT, "MSHist range from", "MSHistFrom", "text"),
    ("MSHistTo", G_WHAT, "MSHist range to", "MSHistTo", "text"),

    # -- what it says happened ----------------------------------------
    ("VisitCount", G_SAYS, "Visits (property store)", "SPS_VisitCount", "num"),
    ("CacheTouches", G_SAYS, "Cache touches (AccessCount)", "AccessCount",
     "num"),
    ("SPS_VisitCount", G_SAYS, "Visit count (SPS id 6)", "SPS_VisitCount", "num"),
    ("AccessCount", G_SAYS, "Cache touches (AccessCount)", "AccessCount", "num"),
    ("SyncCount", G_SAYS, "Sync count", "SyncCount", "num"),
    ("SearchTerms", G_SAYS, "Search terms", "SearchTerms", "text"),
    ("DownloadSourceUrl", G_SAYS, "Downloaded from", "DownloadSourceUrl", "url"),
    ("DownloadSize", G_SAYS, "Download size", "DownloadSize", "size"),
    ("DownloadConfidence", G_SAYS, "Download decode confidence", None, "text"),
    ("DownloadGuid", G_SAYS, "Download GUID", None, "text"),
    ("FileSize", G_SAYS, "File size", "FileSize", "size"),
    ("HttpStatus", G_SAYS, "HTTP status", "HttpStatus", "text"),
    ("ContentType", G_SAYS, "Content type", "ContentType", "text"),
    ("Server", G_SAYS, "Server", "Server", "text"),

    # -- when ---------------------------------------------------------
    ("AccessedUtc", G_WHEN, "Last visit (UTC)", "KeyTimestampUTC", "time"),
    ("AccessedLocal", G_WHEN, "Last visit (LOCAL)", "SPS_LastVisitLocal", "time"),
    ("Timestamp", G_WHEN, "Timestamp (UTC)", "KeyTimestampUTC", "time"),
    ("ModifiedTime", G_WHEN, "Modified (UTC)", "ModifiedTime", "time"),
    ("ModifiedTimeLocal", G_WHEN, "Modified (LOCAL, as stored)",
     "ModifiedTimeLocal", "time"),
    ("AccessedTime", G_WHEN, "Accessed (UTC)", "AccessedTime", "time"),
    ("CreationTime", G_WHEN, "Created (UTC)", "CreationTime", "time"),
    ("ExpiryTime", G_WHEN, "Expires (UTC)", "ExpiryTime", "time"),
    ("SyncTime", G_WHEN, "Synced (UTC)", "SyncTime", "time"),
    ("PostCheckTime", G_WHEN, "Post-check (UTC)", "PostCheckTime", "time"),
    ("SPS_LastVisitLocal", G_WHEN, "Last visit, property store (LOCAL)",
     "SPS_LastVisitLocal", "time"),
    ("DownloadTime", G_WHEN, "Downloaded (UTC)", "DownloadTime", "time"),
    ("ModifiedTimeBasis", G_WHEN, "Canonical instant taken from",
     "KeyTimestampDesc", "text"),
    ("NearbyFiletime", G_WHEN, "Nearby FILETIME", "NearbyFiletime", "time"),

    # -- flags and state ----------------------------------------------
    ("Flags", G_FLAGS, "Flags", "Flags", "num"),
    ("FlagsDecoded", G_FLAGS, "Flags decoded", "FlagsDecoded", "text"),
    ("IsInPrivate", G_FLAGS, "InPrivate", "IsInPrivate", "flag"),
    ("Type", G_FLAGS, "Entry type", "Type", "num"),
    ("IsLeak", G_FLAGS, "Leak record", "IsLeak", "flag"),
    ("IsLocalFile", G_FLAGS, "Local file", "IsLocalFile", "flag"),
    ("ExemptionDelta", G_FLAGS, "Exemption delta", "ExemptionDelta", "num"),

    # -- where it lives in the database -------------------------------
    ("EntryId", G_WHERE_DB, "Entry id", "EntryId", "num"),
    ("ContainerId", G_WHERE_DB, "Container id", "ContainerId", "num"),
    ("ContainerName", G_WHERE_DB, "Container name", "ContainerName", "text"),
    ("ContainerType", G_WHERE_DB, "Container type", "ContainerType", "text"),
    ("ContainerFrom", G_WHERE_DB, "How the container was found",
     "ContainerFrom", "text"),
    ("TableName", G_WHERE_DB, "ESE table", "TableName", "text"),
    ("Table", G_WHERE_DB, "ESE table", None, "text"),
    ("PartitionId", G_WHERE_DB, "Partition", None, "text"),
    ("CacheId", G_WHERE_DB, "Cache id", "CacheId", "num"),
    ("UrlHash", G_WHERE_DB, "URL hash (Windows')", "UrlHash", "num"),
    ("BlobClass", G_WHERE_DB, "Blob class", "BlobClass", "text"),
    ("InLiveDb", G_WHERE_DB, "Also present in the live database", None, "flag"),

    # -- on the examined machine ---------------
    ("CachedFilePath", G_MACHINE, "Cached file path", "CachedFilePath", "path"),
    ("CacheFolder", G_MACHINE, "Cache folder", "CacheFolder", "path"),
    ("SecureDirectory", G_MACHINE, "Cache subdirectory index",
     "SecureDirectory", "path"),
    ("SecureDirectoryName", G_MACHINE, "Cache subdirectory name",
     "SecureDirectoryName", "path"),
    ("Filename", G_MACHINE, "Cached file name", "Filename", "path"),
    ("FileExtension", G_MACHINE, "Cached file extension", "FileExtension", "path"),
    ("DownloadPath", G_MACHINE, "Saved to", "DownloadPath", "path"),
    ("AppDirectory", G_MACHINE, "Application directory", None, "path"),

    # -- how it was recovered -----------------------------------------
    ("Origin", G_HOW, "Origin", "Origin", "text"),
    ("Source", G_HOW, "Source file", "Source", "text"),
    ("Offset", G_HOW, "Byte offset", "Offset", "offset"),
    ("Page", G_HOW, "Page", "Page", "num"),
    ("Method", G_HOW, "Recovery method", "Method", "text"),
    ("RecoverySource", G_HOW, "Recovery method (engine)", "RecoverySource", "text"),
    ("Confidence", G_HOW, "Confidence", "Confidence", "text"),
    ("Region", G_HOW, "Region of the file", None, "text"),
    ("RecordEndMode", G_HOW, "How the record ended", None, "text"),
    ("Encoding", G_HOW, "Encoding", None, "text"),
    ("AlsoSeenIn", G_HOW, "Also seen in", None, "text"),
    ("UrlHealth", G_HOW, "URL health", None, "text"),
    ("UrlHealthNote", G_HOW, "URL health note", None, "text"),
    ("UrlSalvaged", G_HOW, "URL was repaired", None, "flag"),
    ("UrlSalvageNote", G_HOW, "How the URL was repaired", None, "text"),
    ("CarvedFieldsDerived", G_HOW, "Fields re-derived after carving", None, "flag"),
    ("FragmentCount", G_HOW, "Number of fragments recovered", None, "num"),
)

#: Overrides for keys whose meaning depends on the record kind. "Name" is
#: a cookie's name on a cookie and a container's name on a container; one
#: table entry cannot be both, and guessing from context is how a cookie
#: value ends up labelled as a container.
_BY_KIND = {
    K_TABLE_ROW: (
        ("Table", G_WHERE_DB, "ESE table", None, "text"),
        ("Container", G_WHERE_DB, "Container", None, "text"),
        ("TableType", G_WHERE_DB, "Table type", None, "text"),
        ("Row", G_WHERE_DB, "Row # in its table", None, "num"),
        ("MatchedColumns", G_SAYS, "Matched columns", None, "text"),
        ("FoundIn", G_SAYS, "Found in", None, "text"),
        ("Context", G_SAYS, "Keyword in context", None, "text"),
        ("BlobOffset", G_SAYS, "Offset in the value", None, "offset"),
        ("MatchedValue", G_SAYS, "Matched value (decoded)", None, "text"),
        ("RawType", G_SAYS, "Stored as", None, "text"),
        ("RawValue", G_SAYS, "Matched value (as stored)", None, "text"),
    ),
    K_COOKIE: (
        ("Name", G_WHAT, "Cookie name", "CookieName", "text"),
        ("Value", G_SAYS, "Cookie value", "CookieValue", "text"),
        ("ValueDecoded", G_SAYS, "Cookie value (percent-decoded)",
         "CookieValueDecoded", "text"),
        ("Path", G_WHAT, "Path", None, "text"),
        ("IsSecure", G_FLAGS, "Secure (HTTPS only)", None, "flag"),
        ("Expires", G_WHEN, "Expires (UTC)", "Expires", "time"),
        ("LastModified", G_WHEN, "Last modified (UTC)", "LastModified", "time"),
    ),
    K_HSTS: (
        ("Significance", G_SAYS, "What the pin shows", None, "text"),
        ("Corroborated", G_SAYS, "Corroborated by", None, "text"),
        ("HostAttribution", G_SAYS, "Host attribution", None, "text"),
        ("IncludeSubdomains", G_FLAGS, "Includes subdomains",
         "IncludeSubdomains", "flag"),
        ("Expires", G_WHEN, "Pin expires (UTC)", "Expires", "time"),
        ("LastTimeUsed", G_WHEN, "Last used (UTC)", "LastTimeUsed", "time"),
    ),
    K_CERT: (
        ("HostPort", G_WHAT, "Host and port", "HostPort", "text"),
        ("IsCertificate", G_FLAGS, "Is a certificate", None, "flag"),
        ("Thumbprint", G_SAYS, "Thumbprint (as stored)", "Thumbprint", "text"),
        ("BlobSize", G_SAYS, "Blob size recorded by the database", None, "size"),
        ("BlobBytes", G_SAYS, "Blob size this tool measured", None, "size"),
    ),
    K_CONTAINER: (
        ("Id", G_WHERE_DB, "Container id", "ContainerId", "num"),
        ("Name", G_WHAT, "Container name", "ContainerName", "text"),
        ("Type", G_WHAT, "Container type", "ContainerType", "text"),
        ("Records", G_SAYS, "Records", None, "num"),
        ("RecordCount", G_SAYS, "Records counted in the table", None, "num"),
        ("HasTable", G_FLAGS, "Its table is present", None, "flag"),
        ("Size", G_SAYS, "Size", None, "size"),
        ("Limit", G_SAYS, "Container limit", None, "num"),
        ("EntryMaxAge", G_SAYS, "Entry maximum age", None, "num"),
        ("Partition", G_WHERE_DB, "Partition", None, "text"),
        ("Directory", G_MACHINE, "Directory", "CacheFolder", "path"),
        ("LastAccess", G_WHEN, "Last access (UTC)", None, "time"),
        ("LastScavenge", G_WHEN, "Last scavenge (UTC)", None, "time"),
    ),
    K_DOMAIN: (
        ("Domain", G_WHAT, "Domain", "Domain", "text"),
        ("Records", G_SAYS, "Records in this aggregate", None, "num"),
        ("Visits", G_SAYS, "Visits (property store)", "DomainVisits", "num"),
        ("VisitsAddresses", G_SAYS, "Addresses with a visit count", None,
         "num"),
        ("Carved", G_SAYS, "Of those, carved", None, "num"),
        ("OnlyCarved", G_SAYS, "Seen only in carved records", None, "flag"),
        ("FileSize", G_SAYS, "Total cached size", "FileSize", "size"),
        ("AccessCount", G_SAYS, "Mean cache touches", "AccessCount", "text"),
        ("ContainerType", G_WHERE_DB, "Container types seen",
         "ContainerType", "text"),
        ("IsInPrivate", G_FLAGS, "Any record InPrivate", "IsInPrivate", "flag"),
        ("FirstSeen", G_WHEN, "First seen (UTC)", None, "time"),
        ("LastSeen", G_WHEN, "Last seen (UTC)", None, "time"),
    ),
    #: A Timeline period. Every value on it is computed across the records
    #: that fell in one bucket -- Records is a count, Types and Domains are
    #: tallies, and GapBefore is a property of the SILENCE before it, not
    #: of anything that happened. PeriodStart is declared rather than left
    #: to the sweep group, because "Period start (UTC)" is what it is and
    #: "PeriodStart" is what the sweep would call it.
    K_PERIOD: (
        ("Period", G_WHAT, "Period", None, "text"),
        ("PeriodStart", G_WHEN, "Period start (UTC)", None, "time"),
        ("Records", G_SAYS, "Records in this period", None, "num"),
        ("Carved", G_SAYS, "Of those, recovered from deleted data", None,
         "num"),
        ("GapBefore", G_WHEN, "Empty periods before this one", None, "text"),
        # G_SAYS, not G_WHERE_DB: a tally of what KINDS of record fell in
        # this bucket is a statement about what the period holds. Where it
        # lives in the database is a container id, and a period has none.
        ("Types", G_SAYS, "Record types", None, "text"),
        ("Domains", G_SAYS, "Domains (busiest first)", None, "text"),
    ),
    #: A Location place. Every value is computed across the fixes grouped
    #: at the examiner's chosen scale: Fixes is a count, Accuracy a range
    #: (never a mean), Providers the set of sources reported. The headings
    #: use the view's wording: "claimed" and "reported".
    K_PLACE: (
        ("Coords", G_WHAT, "Latitude, Longitude (as grouped)", None, "text"),
        ("Grouping", G_WHAT, "Grouped by", None, "text"),
        ("Fixes", G_SAYS, "Position fixes at this place", None, "num"),
        ("Carved", G_SAYS, "Of those, recovered from deleted data", None,
         "num"),
        ("Accuracy", G_SAYS, "Accuracy claimed across these fixes", None,
         "text"),
        ("Providers", G_SAYS, "Reported source", None, "text"),
        ("FirstSeen", G_WHEN, "First reported (UTC)", None, "time"),
        ("LastSeen", G_WHEN, "Last reported (UTC)", None, "time"),
        # Text, and never a link. These are copied, never opened -- opening
        # one would send this position to that provider, which is a network
        # request this application does not make (tests/test_no_open_paths).
        ("MapsUrl", G_SAYS, "Google Maps link (copy, never opened)", None,
         "text"),
        ("OsmUrl", G_SAYS, "OpenStreetMap link (copy, never opened)", None,
         "text"),
    ),
    K_INDICATOR: (
        ("Kind", G_WHAT, "Indicator kind", None, "text"),
        ("Value", G_WHAT, "Value", None, "text"),
        ("Decoded", G_SAYS, "Decoded", None, "text"),
        ("Conf", G_SAYS, "Confidence", None, "text"),
        ("Why", G_SAYS, "Why this was flagged", None, "text"),
        ("Records", G_SAYS, "Records carrying it", None, "num"),
        ("Fields", G_WHERE_DB, "Found in", None, "text"),
    ),
}

#: A position fix's own fields (see location_loader._shape). Not keyed
#: into _BY_KIND: a fix's `_kind` is the kind of the record it came from
#: (K_HISTORY, K_FILE_ACCESS, K_DOWNLOAD, K_CARVED_STRUCT or
#: K_CARVED_STRING), and a fix adds these facts about the position its URL
#: reported. A fix is recognised on the row (fields_for's `is_fix`:
#: FixTimeFormat is set by _shape for every fix and by nothing else) and
#: these specs are layered on top of the kind's own (_specs_for). Labels
#: match LocationView's fix grid (views/location.py, _fix_columns).
#: Origin, ContainerType and the URL columns come from _COMMON.
_FIX_FIELDS = (
    ("FixTimeUtc", G_WHEN, "Fix time — device said (UTC)", None, "time"),
    ("FixTimeFormat", G_WHEN, "Fix time read as", None, "text"),
    ("FixTimeRaw", G_WHEN, "Fix time — device said (as sent)", None, "text"),
    ("RecordTimeUtc", G_WHEN, "Cache wrote (UTC)", "ModifiedTime", "time"),
    ("Disagreement", G_WHEN, "Times differ by", None, "text"),
    ("Coords", G_WHAT, "Latitude, Longitude (as stored)", None, "text"),
    ("Place", G_WHAT, "Place (as grouped)", None, "text"),
    ("Parameter", G_WHAT, "From URL parameter", None, "text"),
    ("Accuracy", G_SAYS, "Accuracy claimed (m)", None, "text"),
    ("Provider", G_SAYS, "Reported source", None, "text"),
    ("Assessment", G_SAYS, "What this fix is worth", None, "text"),
    # Text, and never a link -- same reason K_PLACE's own MapsUrl/OsmUrl
    # entries above are: opening one would send this position to that
    # provider, a network request this application does not make
    # (tests/test_no_open_paths).
    ("MapsUrl", G_SAYS, "Google Maps link (copy, never opened)", None,
     "text"),
    ("OsmUrl", G_SAYS, "OpenStreetMap link (copy, never opened)", None,
     "text"),
)

#: Keys shown as the sub-line under the value they explain rather than as
#: rows of their own: "the visit was written" and "the cache entry was
#: touched" describe the timestamp above them.
#: {source key: (host key, prefix)}
_NOTES = {
    "AccessedUtcBasis": ("AccessedUtc", "from %s"),
}
#: The same note key hosted by a different field on a different kind.
_NOTES_BY_KIND = {
    K_CARVED_STRUCT: {"AccessedUtcBasis": ("AccessedUtc", "from %s")},
}

#: (kind, key) pairs where an empty value means "this does not exist for
#: this kind of record", not "the carve missed it". A structured carve
#: reconstructs real columns and has no character encoding to state --
#: only a raw string carve does.
_NOT_APPLICABLE = {(K_CARVED_STRUCT, "Encoding")}

#: The columns struct_carver's reconstruction is SUPPOSED to reach. A
#: carved structured record missing one of these did not merely fail to
#: have a value: the carve did not get there, and that is worth saying
#: even though the key is absent from the dict entirely.
_CARVE_EXPECTED = frozenset((
    "EntryId", "ContainerId", "CacheId", "UrlHash", "SecureDirectory",
    "Type", "Flags", "AccessCount", "SyncCount", "ExemptionDelta",
    "FileSize", "Url", "Filename", "CreationTime_raw", "ModifiedTime_raw",
    "AccessedTime_raw", "ExpiryTime_raw", "SyncTime_raw",
    "PostCheckTime_raw"))

#: The blobs a record can carry, and their labels. The bytes stay on the
#: engine record; only their size, detected type and hash reach a field
#: row, and the viewer renders hex on demand.
#:
#: Imported from blob_source, which turns each entry into a BlobSource, so
#: Enter on a Binary field row opens the viewer tab of the same label.
#: tests/test_blob_source.py checks it is the same object.
BLOB_FIELDS = blob_source.BLOB_FIELDS
_BLOBS = BLOB_FIELDS


# --- absence ------------------------------------------------------------

def _carve_expected(kind, key, source):
    """Should a missing key still get a "(not recovered)" row?

    Only for a carved structured record, and only for the columns
    struct_carver's reconstruction targets. "(not recovered)" says this
    carve did not reach this column; a string carve reconstructs no
    columns (it recovers text and where it was found), so for it the
    statement would be false. Without this, a string artifact would also
    show dozens of identical rows.

    A decoded field whose paired _raw is present is always emitted, so a
    carve that recovered a FILETIME without a formatted form shows the
    number.
    """
    if key + "_raw" in source:
        return True
    return kind == K_CARVED_STRUCT and key in _CARVE_EXPECTED


def _absence_for(carved, key, present, value):
    """Which absence state applies.

    Returns an absence token, None for a real value, or NOT_EMITTED when no
    row should be produced.

    0, False and "" are real values: Offset 0 is the first byte of a file,
    Page 0 a real page, AccessCount 0 a real count. This matches
    provenance.describe_origin (`if offset is not None`), so the two never
    disagree about a record.
    """
    if provenance.is_absence(value):
        # Already carries a stated absence -- a carved string artifact's
        # IsInPrivate, a container's not-determinable record count. Never
        # re-decide it: the loader knew something this function does not.
        return value
    if not present:
        if carved:
            return provenance.ABSENCE_NOT_RECOVERED
        return NOT_EMITTED
    if value is None:
        return (provenance.ABSENCE_NOT_RECOVERED if carved
                else provenance.ABSENCE_EMPTY)
    # len()-empty, checked by TYPE rather than by truthiness: `not value`
    # is True for 0, 0.0 and False, all of which are real values.
    if isinstance(value, (str, bytes, bytearray, list, tuple, dict)) and not len(value):
        return (provenance.ABSENCE_NOT_RECOVERED if carved
                else provenance.ABSENCE_EMPTY)
    return None


# --- rendering ----------------------------------------------------------

def _render(value, kind):
    """The displayed form of a real value. Never "" -- callers only reach
    this for values _absence_for has already declared real."""
    if isinstance(value, bool):
        # Checked before int (bool is an int in Python), so a flag never
        # reads as a count of 1 or 0.
        return "Yes" if value else "No"
    if isinstance(value, datetime.datetime):
        return time_format.format_dt(value)
    if isinstance(value, datetime.date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, int):
        if kind == "offset":
            return "%d (0x%08X)" % (value, value)
        if kind == "size":
            return "{:,} bytes".format(value)
        return "{:,}".format(value)
    if isinstance(value, float):
        return "%g" % value
    # A non-empty string is shown as itself, whitespace included: it was
    # already classified as a real value by _absence_for. A time the engine
    # wrote as text is re-spelled with the examiner's chosen pattern.
    return time_format.respell(str(value))


def _blob_summary(label, data):
    """Size, content-derived type, and this tool's hash. Never the bytes.

    detect_blob_type reads the magic bytes, not the column name, so a
    column expected to hold headers that holds a PNG is reported as PNG.
    """
    digest = hashlib.sha256(bytes(data)).hexdigest()
    # All 64 digits, as the hex viewer shows them: a digest is only
    # checkable whole.
    return "%s bytes · %s · SHA-256 %s" % (
        "{:,}".format(len(data)), ese_parser.detect_blob_type(bytes(data)),
        digest)


# --- identity -----------------------------------------------------------

def _record_identity(entry):
    for key in ("CleanUrl", "Url", "SPS_PageTitle", "HostPort", "Domain",
                "Name", "Value"):
        value = (entry or {}).get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


#: what a deleted-row stub is called -- it is not a carved record (no
#: bytes of the row survive), it is the key entry the deletion left behind.
STUB_TITLE = "DELETED-RECORD STUB"


def identity_of(row):
    """The one line naming this record, for the dialog's header.

    Never invents one: a record with nothing nameable says so rather than
    getting a fabricated title or an empty header bar.
    """
    row = row or {}
    kind = row.get("_kind")
    record = row.get("_record") or {}
    if kind == K_TOMBSTONE:
        return "Deleted row — key %s in %s" % (
            row.get("Key") or "not decoded",
            record.get("Table") or "an unknown table")
    if kind == K_COOKIE:
        name = row.get("Name") or record.get("Name") or ""
        domain = row.get("Domain") or record.get("Domain") or ""
        if name or domain:
            return " — ".join(p for p in (name, domain) if p)
    if kind == K_INDICATOR:
        parts = [p for p in (row.get("Kind"), row.get("Value")) if p]
        if parts:
            return " — ".join(str(p) for p in parts)
    if kind == K_CONTAINER:
        name = row.get("Name") or record.get("Name") or ""
        if name:
            return str(name)
    if kind == K_PLACE:
        # Nothing on a place row is a URL, a title or a name either, and
        # its identity is the one thing it unambiguously has: where it is.
        # Declared BEFORE the generic walk below because that walk would
        # otherwise find nothing at all here.
        coords = row.get("Coords")
        if isinstance(coords, str) and coords.strip():
            return coords
    if kind == K_PERIOD:
        # Nothing on a period row is a URL, a domain or a name, so the
        # generic walk below finds nothing and the dialog would open with
        # "(this record carries no value that names it)" over a row whose
        # whole identity is its period label.
        period = row.get("Period")
        if isinstance(period, str) and period.strip():
            return period
    for key in ("CleanUrl", "Url", "HostPort", "Domain", "Title", "Value",
                "Name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    identity = _record_identity(record)
    if identity:
        return identity
    # A per-container summary (an EntryId gap row) is named by the
    # container it summarises.
    cid, cname = row.get("ContainerId"), row.get("ContainerName")
    if cid not in (None, "") or cname:
        return " · ".join(
            p for p in (("Container %s" % cid) if cid not in (None, "") else "",
                        str(cname or "")) if p)
    return "(this record carries no value that names it)"


def twin_line(row):
    """"Same visit as: ..." for a record with a twin in another container, "" otherwise. Plain text: it names the other record,
    it never opens it."""
    row = row or {}
    text = (local_clock.same_visit_text(row.get("_record") or {})
            or row.get("SameVisit") or "")
    return "Same visit as: %s" % text if text else ""


def origin_line(row):
    """The line under the identity, saying what this row is.

    For a record, provenance.describe_origin() verbatim: the sentence
    Explain and every export use.

    For an aggregate, the population it summarises: an aggregate has no
    origin of its own, and describe_origin would read its ContainerType as
    if it were one record.
    """
    row = row or {}
    # First, before the aggregate branch: a kind with a declared sentence
    # is neither a record nor a population (a raw table row matched by a
    # search is one row). See record_kinds.ORIGIN_SENTENCE.
    sentence = record_kinds.ORIGIN_SENTENCE.get(row.get("_kind"))
    if sentence:
        return sentence
    if row.get("_kind") == K_TOMBSTONE:
        # Nothing of the record was carved: its key survived, in a live
        # b-tree node.
        return STUB_ORIGIN_LINE
    if row.get("_kind") in AGGREGATES:
        members = row.get("_members")
        if members is None:
            members = row.get("_records")
        total = row.get("Records")
        count = total if isinstance(total, int) else len(members or ())
        return ("Summary of %s records, not a single record."
                % "{:,}".format(count))
    return provenance.describe_origin(row)


def row_for_record(entry):
    """A minimal row wrapping an engine record, so an aggregate member can
    be opened in its own dialog.

    Every key is read from the record; nothing is invented. The provenance
    keys are copied because provenance.describe_origin reads them by name.

    `entry` may be a raw engine dict (an aggregate member from
    domain_loader's or indicator_loader's carved_entries union), and the
    engine never writes Origin, so a missing Origin does not mean live.
    RecoverySource, which every carved record carries and no live record
    does, decides carved-ness when Origin is absent.
    """
    entry = entry or {}
    origin = entry.get("Origin")
    if origin:
        carved = str(origin).startswith("Carved")
    else:
        carved = bool(entry.get("RecoverySource"))
    row = {"_record": entry,
           "_kind": K_CARVED_STRUCT if carved else _kind_for_entry(entry)}
    for key in ("Origin", "Source", "Offset", "Page", "Method", "Confidence",
                "ContainerType", "ContainerName"):
        if key in entry:
            row[key] = entry[key]
    if not origin:
        row["Origin"] = (provenance.CARVED_ORIGIN if carved
                         else provenance.LIVE_ORIGIN)
    return row


#: Aliases for the rule now defined in record_kinds.py, which
#: shell/headers_loader.py also uses; kept so existing callers keep
#: working.
kind_for_entry = record_kinds.kind_for_entry
_kind_for_entry = record_kinds.kind_for_entry


# --- the builder --------------------------------------------------------

def _specs_for(kind, extra=()):
    """Common table first, then the kind's own overrides, then `extra`
    (a position fix's fields, applied whatever the kind; see _FIX_FIELDS).
    A later spec replaces an earlier one for the same key."""
    by_key = {}
    order = []
    for spec in _COMMON + tuple(_BY_KIND.get(kind, ())) + tuple(extra):
        if spec[0] not in by_key:
            order.append(spec[0])
        by_key[spec[0]] = spec
    return [by_key[key] for key in order]


def provenance_field_for(key, kind=None):
    """The catalogue field a row key's value is described by (the fourth
    element of its spec), or None -- what F1 names for a column whose grid
    declaration cites no field (History's Title is SPS_PageTitle)."""
    for spec_key, _group, _label, field, _kind in _specs_for(kind):
        if spec_key == key:
            return field
    return None


def _merged_source(row):
    """One namespace over the engine record and the shell row.

    The row wins on a collision: it holds the shell's decision (a datetime
    where the engine kept a formatted string, "Not determinable" where the
    engine left ""), so the dialog agrees with the grid it was opened from.
    """
    source = {}
    record = row.get("_record")
    if isinstance(record, dict):
        source.update(record)
    for key, value in row.items():
        if not str(key).startswith("_"):
            source[key] = value
    return source


def fields_for(row, all_members=False):
    """Every value this row carries, grouped and worded for an examiner.

    `all_members` builds every member row of an aggregate; otherwise the
    first _MAX_MEMBER_ROWS are built and a last row offers the rest.

    Total, never raising: carved data is damaged data, a hand-built row is
    a real caller, and a dialog that dies on a malformed record tells the
    examiner nothing at all. A row with no _record, no _kind, or nothing
    but junk still comes back with the sweep group.
    """
    row = row if isinstance(row, dict) else {}
    kind = row.get("_kind")
    carved = (str(row.get("Origin") or "").startswith("Carved")
              or kind in (K_CARVED_STRUCT, K_CARVED_STRING, K_TOMBSTONE))
    source = _merged_source(row)
    # Each counter once, under its own name: a row's copy of a record
    # field replaces the record's.
    for row_key, record_key in _ECHOES:
        if (row_key in source and record_key in source
                and source[record_key] == source[row_key]):
            del source[record_key]
    consumed = set()
    buckets = {name: [] for name in GROUPS}

    # A fix's `_kind` is the kind of the record it came from (see
    # _FIX_FIELDS), so a fix is recognised by FixTimeFormat, which
    # location_loader._shape sets on every fix (ABSENCE_NOT_SUPPLIED when
    # the URL carried no timestamp) and nothing else sets.
    fix_fields = _FIX_FIELDS if "FixTimeFormat" in source else ()

    notes = dict(_NOTES)
    notes.update(_NOTES_BY_KIND.get(kind, {}))
    note_for = {}
    for note_key, (host, template) in notes.items():
        value = source.get(note_key)
        if host in source and isinstance(value, str) and value.strip():
            note_for[host] = template % value
            consumed.add(note_key)

    if kind in AGGREGATES:
        buckets[G_AGGREGATE].append(_aggregate_statement(row))

    # -- the declared fields, in the declared order --------------------
    for key, group, label, field, field_kind in _specs_for(kind, fix_fields):
        present = key in source
        if not present and not _carve_expected(kind, key, source):
            # "(not recovered)" describes what a carve tried to
            # reconstruct; a string carve reconstructs no columns, so it
            # does not apply (see _carve_expected).
            continue
        value = source.get(key)
        if (key == "RecoverySource" and value
                and str(value) == str(source.get("Method") or "")):
            # the same value under two labels read as two facts.
            consumed.add(key)
            continue
        absence = _absence_for(carved, key, present, value)
        if absence is NOT_EMITTED:
            continue
        if (kind, key) in _NOT_APPLICABLE and absence is not None:
            absence = provenance.ABSENCE_NOT_APPLICABLE
        consumed.add(key)
        buckets[group].append(_make_field(
            source, consumed, key, label, value, field, field_kind,
            absence, note_for.get(key, "")))

    # -- flattenings: stated, never joined into one opaque string ------
    _flatten_sps(source, consumed, buckets)
    _flatten_list(source, consumed, buckets, "SecureDirectoryNames",
                  G_MACHINE, "Cache subdirectory %d of %d", "path")
    _flatten_fragments(source, consumed, buckets)
    _flatten_headers(source, consumed, buckets)

    # -- blobs: size, type and hash. Never the bytes -------------------
    for blob_key, blob_label in _BLOBS:
        data = source.get(blob_key)
        consumed.add(blob_key)
        if not isinstance(data, (bytes, bytearray)) or not len(data):
            continue
        buckets[G_BINARY].append(DetailField(
            blob_label, blob_key, None, _blob_summary(blob_label, data),
            field=None, kind="text", blob_key=blob_key,
            note="SHA-256 computed by this tool over the bytes as "
                 "extracted, not a value the database stores."))

    if kind in AGGREGATES:
        _members(row, buckets, all_members)

    _sweep(source, consumed, carved, buckets)

    groups = [FieldGroup(name, buckets[name]) for name in GROUPS
              if buckets[name] or name == G_OTHER]
    if carved:
        # Where a recovered record came from is the first question about
        # it, not the eleventh. Straight after carve quality, if present.
        how = [g for g in groups if g.name == G_HOW]
        rest = [g for g in groups if g.name != G_HOW]
        lead = [g for g in rest if g.name == G_QUALITY]
        groups = lead + how + [g for g in rest if g.name != G_QUALITY]
    return _promote_carve_quality(row, groups)


#: (row key, strip label) for the labelled provenance strip under the
#: identity line -- the same facts the grid shows first, worded
#: for a sentence rather than a column heading.
_PROVENANCE_FACTS = (("Source", "Carved from"), ("Offset", "Offset"),
                     ("Page", "Page"), ("Method", "Method"),
                     ("Confidence", "Confidence"), ("Key", "Key"))


#: What a deleted-record stub's dialog says it is.
STUB_ORIGIN_LINE = ("Deleted-record stub: the b-tree key survived; no "
                    "record bytes were carved")


def provenance_facts(row):
    """(label, value) pairs saying where a recovered row came from; [] for
    a live record. The offset is hex, matching record_model's "0x%08X"
    for the same byte position.

    A deleted-record stub (K_TOMBSTONE) carries the Page and Offset of its
    b-tree node when the node's tag gave them; otherwise they are None and
    skipped. Its Confidence names the key it matched ("exact key: UrlHash
    111, EntryId 7"), shown as given.

    One strip for every carved kind; a fact not copied onto the row is
    read from its record.
    """
    row = row or {}
    if not str(row.get("Origin") or "").startswith("Carved"):
        return []
    record = row.get("_record") if isinstance(row.get("_record"), dict) else {}
    fallback = {"Source": "Source", "Offset": "Offset", "Page": "Page",
                "Method": "RecoverySource", "Confidence": "Confidence",
                "Key": "Key"}
    out = []
    for key, label in _PROVENANCE_FACTS:
        v = row.get(key)
        if v in (None, ""):
            v = record.get(fallback[key])
        if v in (None, ""):
            continue
        if key == "Offset" and isinstance(v, int):
            v = "0x%08X" % v
        if key == "Source" and row.get("_kind") == K_TOMBSTONE:
            # A stub's key was FOUND in this file; nothing was carved.
            label = "Found in"
        out.append((label, str(v)))
    return out


def _make_field(source, consumed, key, label, value, field, field_kind,
                absence, note):
    """One row, with its paired raw FILETIME folded into the same row.

    The pretty form and the number an examiner types into another tool
    must never be separated by a scroll, and they must never become two
    rows either -- a record would grow a second, duplicate time section
    made of bare integers.
    """
    raw_key = key + "_raw"
    derivation = ""
    if (local_clock.is_local_clock(source, "ModifiedTime_raw")
            and source.get("ModifiedTime_raw")):
        # An MSHist record's stored ModifiedTime is LOCAL wall-clock
        # (engine/local_clock.py). The raw number decodes to the LOCAL
        # row, so it is printed THERE; printed beside the derived UTC it
        # would be 5 h 30 m (or whatever the zone is) off the value on
        # its own line. The UTC row states its derivation instead.
        if key == "ModifiedTimeLocal":
            raw_key = "ModifiedTime_raw"
        elif key == "ModifiedTime":
            # The offset and its source are stated in the derivation, so
            # they are not swept into "Other" as bare, uncatalogued keys.
            consumed.update((raw_key, local_clock.TZ_OFFSET_KEY,
                             local_clock.TZ_SOURCE_KEY))
            derivation = local_clock.derivation_text(source)
            raw_key = None
    raw_value = source.get(raw_key) if raw_key else None
    if raw_key and raw_key in source:
        consumed.add(raw_key)
    if absence is not None:
        display = absence
        if isinstance(raw_value, int) and raw_value:
            # A decoded value that came out empty while the raw is
            # non-zero is a DECODE failure, and hiding the number would
            # hide the only evidence of it.
            display = "%s  [raw FILETIME: %d]" % (absence, raw_value)
    else:
        display = _render(value, field_kind)
        worded = token_display(key, value)
        if worded:
            display = worded
        if isinstance(raw_value, int) and raw_value:
            display = "%s  [raw FILETIME: %d]" % (display, raw_value)
    if derivation:
        display = "%s  %s" % (display, derivation)
    return DetailField(label, key, value, display, field=field,
                       kind=field_kind, note=note, absence=absence,
                       raw_value=raw_value if isinstance(raw_value, int) else None)


#: What one member of an aggregate is, per kind: "records" for a
#: Domains, Indicators or Timeline row; position fixes for a place, since
#: one URL can report more than one fix and a place of two fixes may
#: summarise a single record. Read by the app's dialog and the offline
#: report.
AGGREGATE_NOUN = {K_PLACE: ("position fix", "position fixes")}


def _aggregate_statement(row):
    """First and plainly: this is not a record.

    An aggregate's numbers are sums, counts and extrema across N members.
    Shown without this sentence they read as one thing that happened, and
    a summary that reads as a record is a summary an examiner will cite.
    """
    total = row.get("Records")
    if not isinstance(total, int):
        total = row.get("Fixes")
    count = total if isinstance(total, int) else len(
        row.get("_members") or row.get("_records") or ())
    singular, plural = AGGREGATE_NOUN.get(row.get("_kind"),
                                           ("record", "records"))
    noun = singular if count == 1 else plural
    text = ("This row summarises %s %s. It is not itself a record; "
            "every value below is computed across those %s."
            % ("{:,}".format(count), noun, "{:,}".format(count)))
    return DetailField("What this row is", "aggregate:summary", None, text,
                       field=None, kind="text")


#: The most member rows this dialog builds as openable rows. Domains and
#: Indicators aggregates have no bound the exhibit imposes, and a
#: QTableWidget's rows are not virtualised, so only a bound on how many
#: are built keeps the dialog fast. The real total is always stated
#: (G_AGGREGATE's statement and the truncation row); only the openable
#: rows past this number are not built.
_MAX_MEMBER_ROWS = 500


def _members(row, buckets, all_members=False):
    members = row.get("_members")
    if members is None:
        members = row.get("_records")
    members = list(members or ())
    total = len(members)
    built = members if all_members else members[:_MAX_MEMBER_ROWS]
    for index, entry in enumerate(built, 1):
        if not isinstance(entry, dict):
            continue
        identity = _record_identity(entry) or "(record with no naming value)"
        # An already-shaped row opens as itself. A Location place's
        # members are fix rows, each with its own _kind and its engine
        # record as _record; wrapping one again would lose that record, so
        # a fix reached through a place renders as it does from the grid.
        # Domains, Indicators and Timeline members are raw engine dicts
        # with neither key.
        shaped = "_kind" in entry and "_record" in entry
        buckets[G_RECORDS].append(DetailField(
            "Record %d of %d" % (index, total), "aggregate:member", entry,
            identity, field=None, kind="text",
            target=entry if shaped else row_for_record(entry),
            note="Opens in its own dialog."))
    if len(built) < total:
        buckets[G_RECORDS].append(DetailField(
            "More records", "aggregate:member_overflow", None,
            "Show all %s records — %s are listed above; press Enter or "
            "double-click to list the other %s here."
            % ("{:,}".format(total), "{:,}".format(len(built)),
               "{:,}".format(total - len(built))),
            field=None, kind="text",
            note="Listing thousands of records takes a few seconds."))


def _flatten_sps(source, consumed, buckets):
    """One row per property id, never with a guessed name.

    sps_decoder.KNOWN_HISTORY_PROPS names two ids (6 and 24); exhibits
    also carry others (9, 13, 23, 28, 32, 33). An undocumented id is shown
    with its number and a note saying its meaning is not documented.
    """
    props = source.get("SPS_Properties")
    consumed.add("SPS_Properties")
    if not isinstance(props, dict) or not props:
        return
    # The VT tag comes from re-parsing the blob, which is the only place
    # it survives -- ese_parser keeps {id: value} on the entry and drops
    # the type. Absent or unparseable, the row simply carries no VT tag
    # rather than a guessed one.
    vt_names = {}
    blob = source.get("ResponseHeaders_raw")
    if isinstance(blob, (bytes, bytearray)):
        try:
            for prop_set in sps_decoder.parse_property_store(bytes(blob)):
                for pid, prop in (prop_set.get("properties") or {}).items():
                    if prop.get("vt_name"):
                        vt_names[pid] = prop["vt_name"]
        except Exception:
            vt_names = {}
    for pid in sorted(props, key=lambda p: (str(type(p)), p)):
        known = sps_decoder.KNOWN_HISTORY_PROPS.get(pid)
        label = "SPS property %s" % pid
        note = ""
        if known:
            label += " (%s)" % known[0]
            note = known[1]
        else:
            note = ("meaning not documented — this tool does not name it")
        if pid in vt_names:
            label += " [%s]" % vt_names[pid]
        value = props[pid]
        if isinstance(value, (bytes, bytearray)):
            display = _blob_summary(label, value)
            value = None
        else:
            absence = _absence_for(False, str(pid), True, value)
            display = absence if absence else _render(value, "text")
        buckets[G_SAYS].append(DetailField(
            label, "SPS_Properties[%s]" % pid, value, display,
            field=None, kind="text", note=note))


def _flatten_list(source, consumed, buckets, key, group, template, kind):
    values = source.get(key)
    consumed.add(key)
    if not isinstance(values, (list, tuple)) or not values:
        return
    for index, value in enumerate(values, 1):
        absence = _absence_for(False, key, True, value)
        buckets[group].append(DetailField(
            template % (index, len(values)), key, value,
            absence if absence else _render(value, kind),
            field=None, kind=kind, absence=absence))


def _flatten_fragments(source, consumed, buckets):
    """Every discarded partial reading, kept by the carver so every
    decision can be verified."""
    offsets = source.get("FragmentOffsets")
    texts = source.get("FragmentTexts")
    consumed.update(("FragmentOffsets", "FragmentTexts"))
    if not isinstance(texts, (list, tuple)) or not texts:
        return
    offsets = list(offsets or ())
    for index, text in enumerate(texts, 1):
        label = "Fragment %d of %d" % (index, len(texts))
        if index - 1 < len(offsets):
            try:
                label += " @ 0x%08X" % int(offsets[index - 1])
            except (TypeError, ValueError):
                label += " @ offset %s (unparsed)" % offsets[index - 1]
        absence = _absence_for(True, "FragmentTexts", True, text)
        buckets[G_HOW].append(DetailField(
            label, "FragmentTexts", text,
            absence if absence else _render(text, "text"),
            field=None, kind="text", absence=absence))


def _flatten_headers(source, consumed, buckets):
    """One row per header, in wire order, with the status line named.

    Order: decode_content_headers builds a dict whose insertion order is
    wire order, and it is kept; header order can itself be evidence.

    The status line is emitted first, under its own label, not as the
    internal `_status_line` key, and is skipped by the pair loop.

    Repeated names: the dict keeps only the last occurrence of a name
    (Set-Cookie, most often). The overwritten count comes from
    re-splitting the raw blob with headers_loader.header_pairs(), as the
    pane and the pair export do, so it is stated wherever the record is
    opened.

    A client-IP header carries HEADER_INTEREST's sentence as its note, so
    the fact is written down as well as coloured.
    """
    dropped = 0
    for key, prefix, field, side in (
            ("ResponseHeaders", "Response header", "ResponseHeadersText",
             "response"),
            ("RequestHeaders", "Request header", "RequestHeadersText",
             "request")):
        headers = source.get(key)
        consumed.add(key)
        if not isinstance(headers, dict) or not headers:
            continue
        # Wire order from the raw blob when there is one; the decoded
        # dict's own insertion order when there is not. Either way the
        # keys rendered are the DICT's, so this cannot show a header the
        # record's own decoded field set does not have.
        pairs = header_pairs(source, side)
        ordered = [name for _o, name, _v, _r in pairs
                   if name == STATUS_LINE_LABEL or name in headers]
        seen = set()
        names = []
        for name in ordered:
            if name not in seen:
                seen.add(name)
                names.append(name)
        for name in headers:
            if name != "_status_line" and name not in seen:
                names.append(name)
        # The lines the dict overwrote: every non-status pair beyond the
        # first of each name. The same arithmetic, on the same pair list,
        # as headers_loader's DuplicateCount.
        lines = [name for _o, name, _v, _r in pairs
                 if name != STATUS_LINE_LABEL]
        dropped += len(lines) - len(set(lines))
        for name in names:
            if name == STATUS_LINE_LABEL:
                value = headers.get("_status_line")
                label = "Status line"
            else:
                value = headers[name]
                label = "%s: %s" % (prefix, name)
            absence = _absence_for(False, key, True, value)
            buckets[G_SAYS].append(DetailField(
                label, key, value,
                absence if absence else _render(value, "text"),
                field=field, kind="text", absence=absence,
                note=(CLIENT_IP_NOTE if name.lower() in HEADER_INTEREST
                      else "")))
    consumed.add("DuplicateCount")
    if dropped:
        buckets[G_SAYS].append(DetailField(
            "Repeated header names", "DuplicateCount", dropped,
            duplicates_note(dropped), field=None, kind="text"))


def _sweep(source, consumed, carved, buckets):
    """Every remaining key, under "Other recovered values".

    A field added to the engine, or anything unusual a carve recovered,
    appears here with no UI change.

    Skips three things: keys the groups already emitted, `_`-prefixed
    internal keys, and raw bytes (summarised under Binary).
    """
    for key in sorted(source):
        if key in consumed or str(key).startswith("_"):
            continue
        value = source[key]
        if isinstance(value, (bytes, bytearray)):
            continue
        label = str(key) or "(unnamed column)"
        if key.endswith("_raw"):
            # Its decoded partner was not emitted, so this is the only form
            # of the value; it is labelled rather than shown as a bare
            # integer.
            label = "%s (raw)" % key[:-4]
        absence = _absence_for(carved, key, True, value)
        if absence is NOT_EMITTED:
            continue
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value, 1):
                item_absence = _absence_for(carved, key, True, item)
                buckets[G_OTHER].append(DetailField(
                    "%s %d of %d" % (label, index, len(value)), key, item,
                    item_absence if item_absence else _render(item, "text"),
                    field=None, kind="text", absence=item_absence))
            continue
        if isinstance(value, dict):
            for name in sorted(value, key=str):
                item = value[name]
                if isinstance(item, (bytes, bytearray)):
                    continue
                item_absence = _absence_for(carved, key, True, item)
                buckets[G_OTHER].append(DetailField(
                    "%s: %s" % (label, name), key, item,
                    item_absence if item_absence else _render(item, "text"),
                    field=None, kind="text", absence=item_absence))
            continue
        buckets[G_OTHER].append(DetailField(
            label, key, value,
            absence if absence else _render(value, "text"),
            field=None, kind="text", absence=absence))


def _promote_carve_quality(row, groups):
    """A damaged carve says so first, at position 0.

    normalise_record computes UrlHealth for every carved record so that
    damaged bytes are not read as a recorded URL, and the warning comes
    before the value it qualifies.

    An intact carve gets no banner; the health verdict is stated under
    "How it was recovered" either way.
    """
    health = row.get("UrlHealth") or (row.get("_record") or {}).get("UrlHealth")
    if not isinstance(health, str) or not health or health == "intact":
        return groups
    quality, rest = [], []
    for group in groups:
        if group.name != G_HOW:
            rest.append(group)
            continue
        keep = []
        for field in group.fields:
            (quality if field.key in _QUALITY_KEYS else keep).append(field)
        if keep:
            rest.append(FieldGroup(G_HOW, keep))
    if not quality:
        return groups
    return [FieldGroup(G_QUALITY, quality)] + rest


# --- helpers for the dialog --------------------------------------------

def flatten(groups):
    """Every field, in group order. What "Copy all fields" walks."""
    return [field for group in groups for field in group.fields]


def counts(groups):
    """(total, absent). The dialog's count line states both: "78 fields —
    every value this record carries, nothing truncated. 6 of them state
    why they have no value." The second number is what stops an examiner
    reading six absence sentences as six values."""
    fields = flatten(groups)
    return len(fields), len([f for f in fields if f.absence])


#: A live record's Origin. The catalogue grades the key "Origin" CARVED,
#: which is right for a carved row (its Origin is the recovery act) but
#: not for a live one, which was read from a live table.
_LIVE_ORIGIN_TOOLTIP = (
    "OBS (Observed) — This record was read from a live table of the open "
    "database, not recovered by carving.")


#: Fields whose value is a UTC instant DERIVED from a local-clock column on
#: an MSHist record (engine/local_clock.py).
_LOCAL_CLOCK_FIELDS = frozenset({"KeyTimestampUTC", "ModifiedTime",
                                 "ModifiedTime_rfc"})


#: (row key, record key) pairs holding the same value under two names.
_ECHOES = (("VisitCount", "SPS_VisitCount"), ("CacheTouches", "AccessCount"))

#: Fields that name a record's container.
_CONTAINER_FIELDS = frozenset(("ContainerId", "ContainerName", "ContainerType"))


def basis_badge(field_key, carved=None, record=None):
    """(short, tooltip) for a catalogued field, or (None, "") for an
    uncatalogued one.

    `carved` is whether the record is carved, when the caller knows it:
    Origin on a live record is observed, not carved (_LIVE_ORIGIN_TOOLTIP).
    `record` is the engine record, when the caller has it: on an MSHist
    record a UTC derived from its local-clock ModifiedTime is INFERRED,
    and the tooltip says why; its LOCAL visit time is the stored
    ModifiedTime, not SPS id 24, so it is badged as ModifiedTimeLocal.

    An uncatalogued field gets no chip; basis_of()'s DERIVED default is
    never used.
    """
    if not field_key or field_key not in evidence_model.FIELD_PROVENANCE:
        return None, ""
    if field_key == "Origin" and carved is False:
        return evidence_model.BASIS_SHORT[evidence_model.OBSERVED],             _LIVE_ORIGIN_TOOLTIP
    if field_key in _CONTAINER_FIELDS and isinstance(record, dict):
        # A container the record did not store, identified another way:
        # inferred, with how it was found.
        inner = record.get("_record")
        how = record.get("ContainerFrom") or (
            inner.get("ContainerFrom") if isinstance(inner, dict) else None)
        if how:
            short = evidence_model.BASIS_SHORT[evidence_model.INFERRED]
            return short, "%s (Inferred) — %s" % (short, how)
    if isinstance(record, dict) and local_clock.is_mshist_record(record):
        if field_key in _LOCAL_CLOCK_FIELDS and record.get("ModifiedTime_raw"):
            short = evidence_model.BASIS_SHORT[evidence_model.INFERRED]
            return short, "%s (Inferred) — %s" % (
                short, local_clock.clock_note(record))
        if (field_key == "SPS_LastVisitLocal"
                and not record.get("SPS_LastVisitLocal_raw")):
            field_key = "ModifiedTimeLocal"
    basis = evidence_model.basis_of(field_key)
    short = evidence_model.BASIS_SHORT[basis]
    tooltip = "%s (%s) — %s" % (short, basis.capitalize(),
                                evidence_model.BASIS_DEFINITION[basis])
    described = evidence_model.describe(field_key)
    if described:
        tooltip = "%s\n\n%s" % (tooltip, described)
    return short, tooltip
