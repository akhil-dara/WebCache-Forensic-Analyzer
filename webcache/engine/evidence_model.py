"""
Evidence provenance model.

A forensic tool must be able to answer, for every number it puts on screen or
in a report: *where did this come from, and how certain is it?* This module is
the single source of truth for that answer.

Every field is classified into exactly one evidentiary basis:

    OBSERVED  Read directly out of an ESE column. No interpretation applied.
              The strongest class — if the database says it, we report it.

    DERIVED   Computed by this tool from observed values using arithmetic that
              is fully documented and reproducible (FILETIME -> UTC, hostname
              extracted from a URL, timezone from the modal delta). Deterministic:
              the same input always yields the same output.

    INFERRED  The *semantics* are community-reverse-engineered, NOT documented
              by Microsoft. The bytes are real; the meaning attributed to them
              rests on published research. Always shown with its attribution.

    CARVED    Recovered heuristically from unallocated space or transaction
              logs. Probabilistic by nature and graded by confidence. Never
              presented as equivalent to a live record.

The UI renders these as badges, tooltips explain the meaning and the trap
cases, and every export plus the court PDF carries the same wording. Nothing
is presented as more certain than it is.
"""

OBSERVED = "OBSERVED"
DERIVED = "DERIVED"
INFERRED = "INFERRED"
CARVED = "CARVED"

BASIS_ORDER = (OBSERVED, DERIVED, INFERRED, CARVED)

BASIS_DEFINITION = {
    OBSERVED: "Read directly from an ESE database column; no interpretation applied.",
    DERIVED: "Computed by this tool from observed values using documented, "
             "reproducible arithmetic.",
    INFERRED: "Byte values are real, but their meaning is community-reverse-"
              "engineered and not documented by Microsoft. Attribution shown.",
    CARVED: "Recovered heuristically from unallocated space or transaction logs. "
            "Probabilistic; carries a confidence grade and byte-offset provenance.",
}

# Short label used on compact UI badges.
BASIS_SHORT = {OBSERVED: "OBS", DERIVED: "DER", INFERRED: "INF", CARVED: "CARV"}

# Citations for the inferred semantics, shown verbatim wherever an inferred
# value appears so a reader can go and check the source themselves.
CITE_SPS = ("Serialized Property Storage semantics from published practitioner "
            "research, correlated with Microsoft propkey.h. The property store "
            "format itself is documented ([MS-PROPSTORE]); the meaning of these "
            "specific property IDs is NOT. Published research describes visit "
            "count as thought to be stored in, or closely allied to, ID 6, and "
            "ID 24 as believed to be the actual last-visit date.")
CITE_IEDOWNLOAD = ("iedownload record layout (GUID + FILETIME + size header, then "
                   "string region) inferred from published documentation of the "
                   "legacy index.dat iedownload record and Kim/Jang/Lee (2016). "
                   "No Microsoft specification exists; the "
                   "in-blob string encoding is not authoritatively documented, so the "
                   "parser auto-detects ASCII vs UTF-16LE.")
CITE_FLAGS = ("WinINet cache-entry flag bit meanings from published practitioner "
              "research (Muir 2015 and subsequent Windows forensics literature). "
              "Bit 0x08 marks InPrivate on History records only; on Content "
              "(cache) records the same bit is EDITED_CACHE_ENTRY, so it is not "
              "read as InPrivate there. For a record recovered from deleted "
              "space, published research has not established a marker that "
              "separates an InPrivate session from ordinary browsing: the bit "
              "is read the same way, and is an indication to corroborate.")
CITE_CARVE = ("Deleted ESE records persist because the engine only flags their space "
              "as reusable; the bytes survive until the page is reorganised (Chivers "
              "& Hargreaves; Malmstrom & Teveldal). Recovery here is signature and "
              "structure carving, NOT ESE engine recovery or transaction-log replay.")
CITE_TZ = ("Machine UTC offset derived by this tool from the difference between "
           "the SPS ID-24 value (local clock) and the ModifiedTime column (UTC) "
           "of each History record, rounded to the nearest 15 minutes. The most "
           "frequently observed offset is adopted (never a median or mean, which "
           "across daylight saving can fall between two real offsets), and an "
           "offset seen on fewer than two records is never used. Inherits the "
           "INFERRED status of SPS ID 24.")


def _f(basis, meaning, caveat="", citation=""):
    return {"basis": basis, "meaning": meaning, "caveat": caveat, "citation": citation}


# ── Field catalog ────────────────────────────────────────────────────
# Keyed by the field name used in ENTRY_FIELDS / artifact field lists.

FIELD_PROVENANCE = {
    # -- record identity -----------------------------------------------
    "EntryId": _f(OBSERVED, "Sequential record identifier assigned by ESE within "
                            "its container table.",
                  "Gaps in the sequence indicate deleted records, but the numbering "
                  "is per-container and is not a global identifier."),
    "ContainerId": _f(OBSERVED, "Identifier joining this record to its row in the "
                                "Containers table."),
    "ContainerName": _f(OBSERVED, "Container name from the Containers table "
                                  "(History, Content, Cookies, MSHist01…)."),
    "ContainerType": _f(DERIVED, "Category this tool assigns by matching the "
                                 "container name (History / Content / Cookies / "
                                 "DOMStore / BackgroundTransfer).",
                        "A convenience grouping created by this tool, not a field "
                        "stored in the database."),
    "DomainVisits": _f(DERIVED, "Visits to this domain by the browser's own "
                                "count: the sum of each address's visit "
                                "count (SPS id 6), each address once -- its "
                                "live record's count where there is one, else "
                                "the highest a recovered copy holds. An "
                                "address with no stored count adds nothing; "
                                "cache requests are never counted as visits."),
    "ContainerFrom": _f(INFERRED, "How a recovered record's container was "
                                  "identified when the Containers table no "
                                  "longer lists it or the carve did not keep "
                                  "it: from the record's own dated-history "
                                  "prefix, or from the owner of the database "
                                  "page it was carved from."),
    "TableName": _f(DERIVED, "The ESE table holding this record, as Container_<id>.",
                    "Container numbering is machine-specific and must never be "
                    "hard-coded across systems."),
    "CacheId": _f(OBSERVED, "Cache identifier stored with the record."),
    "UrlHash": _f(OBSERVED, "Hash of the URL computed by Windows and stored in the "
                            "record.",
                  "This is Windows' own hash, not a hash this tool computed; it is "
                  "not a cryptographic integrity value."),
    "SecureDirectory": _f(OBSERVED, "Index of the cache subdirectory holding the "
                                    "cached file, where applicable."),
    "CacheFolder": _f(OBSERVED, "The folder this record's container manages on the "
                                "examined machine, from the Containers table.",
                      "A folder, not a file: it says where the container kept its "
                      "content, not that any particular file is in it."),
    "SecureDirectoryName": _f(DERIVED, "The cache subdirectory this record's index "
                                       "selects, resolved against the list its "
                                       "container declares.",
                              "The stored value is an index; the name is looked up "
                              "from the container's SecureDirectories column."),
    "CachedFilePath": _f(DERIVED, "Where the cached file was recorded on the examined "
                                  "machine: the container's folder, the secure "
                                  "subdirectory its index selects, and the filename.",
                         "Assembled by this tool from three stored values; the "
                         "database never holds this path as one string. It records "
                         "where the file was written, not that it is still there — "
                         "scavenging deletes cached files and leaves the record. "
                         "The path describes the examined machine, so it must be "
                         "mapped onto the mounted image rather than opened locally."),

    # -- URL forensics --------------------------------------------------
    "Url": _f(OBSERVED, "The URL exactly as stored, including any 'Visited:' or "
                        "MSHist date-range prefix.",
              "This is the raw stored value — reproduce it verbatim in findings."),
    "CleanUrl": _f(DERIVED, "The URL with the Windows history prefix and user "
                            "portion removed, for readability and matching.",
                   "A presentation convenience; the raw Url field remains the "
                   "authoritative value."),
    "LocalPath": _f(DERIVED, "A file: URL decoded to the Windows path it names "
                             "(percent-escapes resolved, backslashes).",
                    "Derived by this tool from the stored value beside it; "
                    "the stored value is the authoritative one."),
    "Drive": _f(DERIVED, "The volume the decoded local path is on: a drive "
                         "letter, or the server and share of a network path.",
                "Read off the path as stored; it names the drive letter at the "
                "time of the visit, which removable media can change."),
    "FileType": _f(DERIVED, "The extension of the decoded local path's last "
                            "segment.",
                   "An extension is a name, not a verified file format; a "
                   "path without one is usually a folder."),
    "Domain": _f(DERIVED, "Hostname parsed out of the URL.",
                 "Local file paths and app-internal schemes have no real hostname "
                 "and are bracketed, e.g. [Local File]."),
    "Scheme": _f(DERIVED, "URL scheme (https, http, file, ms-appx…)."),
    "UrlCategory": _f(DERIVED, "Classification this tool assigns: Web, Local File "
                               "Access, Windows App, Browser Internal, Other."),
    "UrlUsername": _f(OBSERVED, "The Windows account name embedded in the history "
                                "URL prefix by the operating system.",
                      "Attributes the record to a Windows profile, not to a person; "
                      "shared or automated use of an account is always possible."),
    "SearchTerms": _f(DERIVED, "Search phrase decoded from the query string of a "
                               "recognised search-engine URL.",
                      "Evidence that the query string was requested. It does not by "
                      "itself prove the user typed it — links, redirects and "
                      "suggestions produce identical URLs."),
    "RedirectUrl": _f(OBSERVED, "Redirect target recorded with this cache entry."),
    "MSHistFrom": _f(DERIVED, "Start of the date range encoded in an MSHist "
                              "container's URL prefix."),
    "MSHistTo": _f(DERIVED, "End of the date range encoded in an MSHist container's "
                            "URL prefix.",
                   "The range is the history bucket the record was filed in — a "
                   "weekly/daily grouping, not the precise visit time."),
    "IsLocalFile": _f(DERIVED, "True when the URL is a file:/// reference.",
                      "Records that a local file was opened through a WinINet-aware "
                      "application. Absence does not prove a file was never opened."),
    "IsLeak": _f(OBSERVED, "Record is a LEAK entry — a cache entry Windows could not "
                           "delete because the file was still locked.",
                 "Forensically valuable precisely because LEAK records survive "
                 "ordinary cache clearing."),

    # -- visit counts ---------------------------------------------------
    "AccessCount": _f(OBSERVED, "The AccessCount column as stored by Windows."),
    "SPS_VisitCount": _f(INFERRED, "Visit count decoded from property ID 6 of the "
                                   "Serialized Property Storage blob in "
                                   "ResponseHeaders.",
                         "Where this disagrees with AccessCount, report both and do "
                         "not silently prefer one. In the validation sample the two "
                         "agreed on 434 of 465 History records.",
                         CITE_SPS),
    "VisitCountBestSource": _f(DERIVED,
                              "Names which counter VisitCountBest was taken "
                              "from on this record: the SPS property store "
                              "(user visits) or the AccessCount column (cache "
                              "touches).",
                              "Read this before quoting VisitCountBest: the two "
                              "counters answer different questions, and on the "
                              "sample database 53% of records have no SPS value "
                              "and fall back to cache touches."),
    "VisitCountBest": _f(DERIVED, "Convenience field: the SPS value when present, "
                                  "otherwise the AccessCount column.",
                         "A display shortcut. Cite AccessCount or SPS-6 explicitly "
                         "in findings rather than this merged value.", CITE_SPS),
    "SyncCount": _f(OBSERVED, "Sync counter stored with the record."),

    # -- timestamps -----------------------------------------------------
    "KeyTimestampUTC": _f(DERIVED, "The single most meaningful timestamp for this "
                                   "record, chosen for sorting and timelining.",
                          "Which column was chosen is stated in the adjacent "
                          "'KeyTimestamp meaning' field — always read them together."),
    "KeyTimestampDesc": _f(DERIVED, "Names which column supplied the key timestamp."),
    "CreationTime": _f(OBSERVED, "CreationTime column, converted to UTC.",
                       "When the record was created, which can be later than the "
                       "first visit it represents."),
    "ModifiedTime": _f(OBSERVED, "ModifiedTime column, converted to UTC.",
                       "For History records this tracks the visit; it is the column "
                       "the SPS local-time value corresponds to. EXCEPTION: an "
                       "MSHist container stores this column on the LOCAL clock "
                       "(measured on five exhibits); there it is shown as LOCAL "
                       "and its UTC is derived from the recovered zone, or left "
                       "blank when no zone was recovered. In a Content (cache) "
                       "container it is the server's last-modified date of "
                       "what was cached, which can fall years before the "
                       "cache entry was written; it is not activity on this "
                       "machine, and such a record is placed in time by "
                       "AccessedTime, else CreationTime."),
    "ModifiedTimeLocal": _f(OBSERVED, "An MSHist container's ModifiedTime "
                                      "exactly as stored: the machine's "
                                      "LOCAL wall clock.",
                            "Its UTC is the ModifiedTime field, derived "
                            "from the recovered zone."),
    "AccessedTime": _f(OBSERVED, "AccessedTime column, converted to UTC.",
                       "The record was last ACCESSED — a cache touch. This is not "
                       "necessarily a user visit, and is the single most commonly "
                       "misread field in this artifact."),
    "ExpiryTime": _f(OBSERVED, "ExpiryTime column, converted to UTC.",
                     "Server-driven cache expiry. It reflects HTTP caching policy, "
                     "not user activity, and may lie far in the future."),
    "SyncTime": _f(OBSERVED, "SyncTime column, converted to UTC."),
    "PostCheckTime": _f(OBSERVED, "PostCheckTime column, converted to UTC."),
    "SPS_LastVisitLocal": _f(INFERRED, "True last-visit time from property ID 24 of "
                                       "the SPS blob — recorded on the machine's "
                                       "LOCAL clock, not UTC.",
                             "Never compare this directly against the UTC columns. "
                             "In the validation sample it equalled ModifiedTime plus "
                             "exactly the machine's UTC offset (+05:30).", CITE_SPS),

    # -- raw / RFC 3339 forms -------------------------------------------
    "CreationTime_rfc": _f(DERIVED, "CreationTime as an RFC 3339 UTC string."),
    "ModifiedTime_rfc": _f(DERIVED, "ModifiedTime as an RFC 3339 UTC string."),
    "AccessedTime_rfc": _f(DERIVED, "AccessedTime as an RFC 3339 UTC string."),
    "ExpiryTime_rfc": _f(DERIVED, "ExpiryTime as an RFC 3339 UTC string."),
    "SyncTime_rfc": _f(DERIVED, "SyncTime as an RFC 3339 UTC string."),
    "CreationTime_raw": _f(OBSERVED, "Unconverted 64-bit FILETIME as stored.",
                           "Included so any conversion this tool performs can be "
                           "independently recomputed and checked."),
    "ModifiedTime_raw": _f(OBSERVED, "Unconverted 64-bit FILETIME as stored."),
    "AccessedTime_raw": _f(OBSERVED, "Unconverted 64-bit FILETIME as stored."),
    "ExpiryTime_raw": _f(OBSERVED, "Unconverted 64-bit FILETIME as stored."),
    "SyncTime_raw": _f(OBSERVED, "Unconverted 64-bit FILETIME as stored."),
    "PostCheckTime_raw": _f(OBSERVED, "Unconverted 64-bit FILETIME as stored."),
    "SPS_LastVisitLocal_raw": _f(INFERRED, "Unconverted FILETIME from SPS property 24.",
                                 "Local clock. Millisecond-truncated in every sample "
                                 "record observed.", CITE_SPS),

    # -- flags ----------------------------------------------------------
    "Flags": _f(OBSERVED, "Raw Flags bitfield as stored."),
    "FlagsDecoded": _f(INFERRED, "Human-readable decode of the Flags bitfield.",
                       "Bit meanings come from practitioner research, not Microsoft "
                       "documentation. Unrecognised bits are shown as hex rather "
                       "than dropped.", CITE_FLAGS),
    "IsInPrivate": _f(INFERRED, "Record was created during InPrivate/private "
                                "browsing (Flags bit 0x08 on a History record).",
                      "Scoped to History records only. The same bit on a Content "
                      "record means EDITED_CACHE_ENTRY and is NOT private browsing — "
                      "treating it as such is a common false-positive.", CITE_FLAGS),
    "Type": _f(OBSERVED, "Record type value as stored."),
    "ExemptionDelta": _f(OBSERVED, "Cache exemption delta as stored."),

    # -- cached file ----------------------------------------------------
    "Filename": _f(OBSERVED, "Name of the cached file on disk, where one exists.",
                   "The cache file itself lives outside this database; this is only "
                   "the pointer to it."),
    "FileExtension": _f(OBSERVED, "File extension recorded with the entry."),
    "FileSize": _f(OBSERVED, "Size of the cached content in bytes, as recorded."),

    # -- downloads ------------------------------------------------------
    "DownloadPath": _f(INFERRED, "Local save path extracted from the iedownload "
                                 "record.",
                       "Records where the download was written according to the "
                       "database. It does not prove the file is still there.",
                       CITE_IEDOWNLOAD),
    "DownloadSourceUrl": _f(INFERRED, "Source URL the download came from.",
                            "", CITE_IEDOWNLOAD),
    "DownloadSize": _f(INFERRED, "Download size from the iedownload record header.",
                       "", CITE_IEDOWNLOAD),
    "DownloadTime": _f(INFERRED, "Download timestamp from the iedownload record "
                                 "(UTC).", "", CITE_IEDOWNLOAD),

    # -- blobs / headers -------------------------------------------------
    "BlobClass": _f(DERIVED, "What the ResponseHeaders blob was detected to be: an "
                             "SPS property store, raw HTTP headers, or unknown.",
                    "Detected from the blob's own signature bytes, not assumed from "
                    "the container type."),
    "SPS_PageTitle": _f(INFERRED, "Page title string found in the SPS blob.",
                        "", CITE_SPS),
    "SPS_PropertiesText": _f(INFERRED, "Every property ID and value decoded from the "
                                       "SPS blob, so the raw structure can be checked.",
                             "Exposed deliberately: the inferred fields above are "
                             "drawn from these, and an examiner should be able to "
                             "verify them independently.", CITE_SPS),
    "HttpStatus": _f(OBSERVED, "HTTP status code from the stored response headers."),
    "ContentType": _f(OBSERVED, "Content-Type from the stored response headers."),
    "Server": _f(OBSERVED, "Server header from the stored response headers."),
    "ResponseHeadersText": _f(OBSERVED, "Decoded response headers as stored."),
    "RequestHeadersText": _f(OBSERVED, "Decoded request headers as stored."),
    "ResponseHeadersSize": _f(DERIVED, "Byte length of the raw ResponseHeaders blob."),
    "RequestHeadersSize": _f(DERIVED, "Byte length of the raw RequestHeaders blob."),

    # -- case management --------------------------------------------------
    "Tags": _f(DERIVED, "Tags applied by the examiner in this case file.",
               "Analyst annotation — not evidence recovered from the database."),
    "Comments": _f(DERIVED, "Comments written by the examiner in this case file.",
                   "Analyst annotation — not evidence recovered from the database."),

    # -- auxiliary artifact tables -----------------------------------------
    "RDomain": _f(OBSERVED, "Domain as stored by Windows in reversed form "
                            "('com.microsoft')."),
    "CookieName": _f(OBSERVED, "Cookie name as stored."),
    "CookieValue": _f(OBSERVED, "Cookie value as stored."),
    "CookieValueDecoded": _f(DERIVED, "Cookie value with its percent-escapes "
                                      "decoded; the stored value is Cookie "
                                      "value."),
    "Expires": _f(OBSERVED, "Expiry timestamp as stored (UTC)."),
    "LastModified": _f(OBSERVED, "Last-modified timestamp as stored (UTC)."),
    "IncludeSubdomains": _f(OBSERVED, "HSTS pin also covers subdomains."),
    "LastTimeUsed": _f(OBSERVED, "When the HSTS pin was last used (UTC)."),
    "Thumbprint": _f(OBSERVED, "SHA-1 thumbprint of the stored certificate."),
    "HostPort": _f(OBSERVED, "Host and port the certificate entry belongs to."),

    # -- recovery ----------------------------------------------------------
    "RecoverySource": _f(CARVED, "Which source the artifact was carved from: a "
                                 "transaction log or database unallocated space.",
                         "", CITE_CARVE),
    "Confidence": _f(CARVED, "Confidence grade for a carved artifact, based on how "
                             "much supporting structure was found alongside it.",
                     "Low confidence means a string was recovered without "
                     "corroborating structure — treat as a lead, not a finding.",
                     CITE_CARVE),
    "Offset": _f(CARVED, "Byte offset the artifact was recovered from, so the "
                         "finding can be independently verified in a hex editor.",
                 "", CITE_CARVE),
    # Origin, Source, Page and Method describe the same recovery act as
    # Confidence and Offset above, and carry the same CARVED grade.
    "Origin": _f(CARVED, "Whether this row is a live database record or was "
                         "carved from deleted/unallocated data.",
                 "", CITE_CARVE),
    "Source": _f(CARVED, "Which file this record was carved from -- a transaction "
                         "log or the database itself -- so the finding can be "
                         "traced back to its source file.",
                 "", CITE_CARVE),
    "Page": _f(CARVED, "ESE page number the record was carved from, alongside the "
                       "byte offset, so the finding can be independently verified "
                       "in a hex editor.",
               "", CITE_CARVE),
    "Method": _f(CARVED, "Which carving technique recovered this record -- e.g. "
                         "page-scan structure carving or transaction-log replay.",
                 "", CITE_CARVE),
    "NearbyFiletime": _f(CARVED, "A plausible FILETIME found adjacent to the carved "
                                 "string, offered as temporal context.",
                         "Proximity in bytes is not proof of association. This is a "
                         "contextual hint, never a established timestamp for the "
                         "artifact.", CITE_CARVE),
}


# ── Scope-honesty statements for reports ─────────────────────────────
# These go verbatim into the court PDF and the export metadata. Candour about
# method limits strengthens admissibility rather than weakening it.

SCOPE_STATEMENTS = [
    ("Source handling",
     "The database was opened strictly read-only and parsed directly in its "
     "dirty-shutdown state. No ESE soft recovery (esentutl /r) was performed. "
     "That step is commonly recommended, but it writes to the database file: "
     "it replays the transaction logs into it and rewrites its header."),
    ("Recovered records",
     "Deleted-record recovery is heuristic signature and structure carving of "
     "unallocated pages and transaction logs. It is NOT ESE engine recovery and "
     "NOT transaction-log replay — the ESE log record format is not publicly "
     "documented and no open implementation of replay exists. Recovered items are "
     "reported with a confidence grade and the byte offset they came from, and "
     "must not be treated as equivalent to live records."),
    ("Inferred semantics",
     "Visit count (SPS property 6) and true last-visit time (SPS property 24) are "
     "decoded from a documented container format, but the meaning attributed to "
     "those specific property IDs is community-reverse-engineered and is not "
     "documented by Microsoft. The same applies to the iedownload record layout "
     "and to WinINet flag-bit meanings. Every such value is labelled INFERRED and "
     "its raw form is exposed for independent verification."),
    ("Clock basis",
     "All timestamps are reported in UTC unless explicitly labelled LOCAL. The "
     "SPS property-24 value, and the ModifiedTime of MSHist history records, are "
     "stored on the machine's local clock. The machine's UTC offset was derived "
     "from the most frequently observed difference between SPS property 24 and "
     "the ModifiedTime column of History records; an MSHist record's UTC is "
     "derived with the offset observed for the same visit where there is one."),
    ("Interpretation limits",
     "AccessedTime records when a cache record was last touched and is not by "
     "itself proof of a user visit. ExpiryTime is server-driven caching policy, "
     "not user activity. A Windows account name in a record attributes it to a "
     "profile, not to a specific person."),
    ("Artifact scope",
     "WebCacheV01.dat is written by WinINet/WinHTTP consumers across Windows — "
     "Windows Update, Office, the Store, IE-mode in Edge and embedded WebViews — "
     "as well as by browsing. Records here are evidence of a request being made by "
     "some component, which is not always deliberate user browsing. Chromium-based "
     "Edge (v79+) does not use this database."),
]


# ── Accessors ─────────────────────────────────────────────────────────

def get(field_name):
    """Provenance record for a field, or None when the field is uncatalogued."""
    return FIELD_PROVENANCE.get(field_name)


def basis_of(field_name, default=DERIVED):
    entry = FIELD_PROVENANCE.get(field_name)
    return entry["basis"] if entry else default


def describe(field_name):
    """Full tooltip text: meaning, caveat, and attribution when inferred."""
    entry = FIELD_PROVENANCE.get(field_name)
    if not entry:
        return ""
    parts = [entry["meaning"]]
    if entry.get("caveat"):
        parts.append("Caution: " + entry["caveat"])
    if entry.get("citation"):
        parts.append("Basis: " + entry["citation"])
    return "\n\n".join(parts)


def fields_by_basis(basis):
    return sorted(k for k, v in FIELD_PROVENANCE.items() if v["basis"] == basis)


def counts_by_basis():
    out = {b: 0 for b in BASIS_ORDER}
    for v in FIELD_PROVENANCE.values():
        out[v["basis"]] = out.get(v["basis"], 0) + 1
    return out


def inferred_citations():
    """Unique attributions in use, for the report's methodology section."""
    seen = []
    for v in FIELD_PROVENANCE.values():
        cite = v.get("citation")
        if cite and cite not in seen:
            seen.append(cite)
    return seen
