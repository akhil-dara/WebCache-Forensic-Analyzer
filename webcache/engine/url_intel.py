"""Indicators inside URLs and file paths.

A URL often carries information no column holds: a cache-busting
parameter that is the client's clock at the moment of the request, a GUID
that encodes the generating machine's MAC address and the time it was
created, an account name in a profile path, a drive letter that places a
file on removable media.

Each extractor is calibrated against real evidence, because the naive
version of each is wrong:

  * A six-group hyphenated hex run is not necessarily a MAC address: a
    screenshot filename such as "Screenshot_YYYY-MM-DD-hh-mm-ss-cc"
    contains the same shape, and is a date and time.
  * A nine-to-thirteen digit run is not necessarily an epoch: unfiltered,
    such runs decode to dates years outside the records' own span.

So each finding carries a confidence and the reason it was reached, stated
as a fact about the input. A value that cannot be justified is labelled
low confidence or not reported.
"""

import base64
import binascii
import re
from urllib.parse import unquote
from datetime import datetime, timedelta, timezone

from .ese_parser import filetime_to_dt

# ── shapes ────────────────────────────────────────────────────────────

#: Six hex groups. Necessary for a MAC, not sufficient (see
#: _mac_findings).
_MAC_SHAPE = re.compile(
    r"(?<![0-9A-Za-z])((?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2})"
    r"(?![0-9A-Za-z])")
#: Twelve bare hex characters, only ever accepted with a naming context.
_MAC_BARE = re.compile(r"(?<![0-9A-Za-z])([0-9A-Fa-f]{12})(?![0-9A-Za-z])")
_GUID = re.compile(
    r"(?<![0-9A-Za-z])([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}"
    r"-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})(?![0-9A-Za-z])")
_IPV4 = re.compile(
    r"(?<![\d.])((?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d))(?![\d.])")
_EMAIL = re.compile(r"(?<![\w.+-])([\w.+-]{1,64}@[\w-]{2,}(?:\.[\w-]{2,})+)")
#: Extensions that end an address used as a FILE NAME ("<user>@host.tld.pdf"):
#: trimmed, with the reason saying so -- some (.zip, .mov) are also real
#: top-level domains, so the decision is shown, never silent.
_FILE_EXTENSIONS = frozenset((
    "pdf", "zip", "rar", "7z", "gz", "tar", "exe", "msi", "dll", "lnk",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "rtf", "odt",
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "tif", "tiff",
    "mp3", "mp4", "wav", "avi", "mkv", "mov", "html", "htm", "xml", "json",
    "eml", "msg", "ics", "vcf", "iso", "img"))
_SID = re.compile(r"(?<![\w-])(S-1-\d+(?:-\d+){1,14})(?![\w-])")
_DIGITS = re.compile(r"(?<![\d.])(\d{9,19})(?![\d.])")
#: Windows history containers are named for the period they cover, as
#: ":YYYYMMDDYYYYMMDD:". Sixteen digits, so the epoch reader claimed them as
#: microsecond timestamps and dated them to 2034. They are two dates, and
#: saying so is more useful than suppressing them.
_MSHIST_RANGE = re.compile(r"(?<!\d)((?:19|20)\d{6})((?:19|20)\d{6})(?!\d)")
#: C:\Users\<name>\ and /Users/<name>/ -- the account the file belonged to.
_USERDIR = re.compile(r"[/\\]Users[/\\]([^/\\?&#]{1,64})[/\\]",
                      re.IGNORECASE)
#: The "Visited: <user>@" prefix Windows puts on history URLs.
_VISITED = re.compile(r"^Visited:\s*([^@]{1,64})@", re.IGNORECASE)
#: A UNC path or a file:// URL naming a host other than this machine.
_UNC = re.compile(r"(?:^|[^\w])\\\\([A-Za-z0-9][\w.-]{1,62})\\")
_FILE_HOST = re.compile(r"file://(?://)?/?/([A-Za-z0-9][\w.-]{1,62})/",
                        re.IGNORECASE)
#: A drive letter at the head of a local path.
_DRIVE = re.compile(r"(?:^|[/\\:])([A-Za-z]):[/\\]")
_COORDS = re.compile(
    r"(?<![\w.-])(-?(?:[0-8]?\d(?:\.\d{3,})|90(?:\.0+)?))"
    r"\s*[,;|]\s*(-?(?:1[0-7]\d|[0-9]?\d)(?:\.\d{3,})|180(?:\.0+)?)"
    r"(?![\w.-])")

#: Query keys whose value is meant to be a time. Presence of one of these
#: turns a digit run from "might be an epoch" into "is labelled an epoch".
_TIME_KEYS = ("t", "ts", "time", "timestamp", "date", "epoch", "unixtime",
              "_", "cb", "rnd", "v", "ver", "mtime", "expires", "exp",
              "issued", "iat", "nbf", "created", "modified", "lastmod")
#: Query keys that name a hardware address.
_MAC_KEYS = ("mac", "macaddr", "macaddress", "bssid", "ap", "apmac", "eth",
             "wifi", "hwaddr", "deviceid", "devicemac", "clientmac")

#: Anything outside this is not a timestamp in a browser cache. Broad;
#: narrow it per case with `span` rather than here.
_FLOOR = datetime(2005, 1, 1, tzinfo=timezone.utc)
_CEIL = datetime(2035, 1, 1, tzinfo=timezone.utc)
#: 1601-01-01, the FILETIME and UUIDv1 epoch.
_1601 = datetime(1601, 1, 1, tzinfo=timezone.utc)
#: 0001-01-01, the .NET DateTime.Ticks epoch.
_0001_OFFSET = 62135596800


HIGH, MEDIUM, LOW = "high", "medium", "low"


class Finding(object):
    """One indicator found inside a URL or path."""

    __slots__ = ("kind", "value", "decoded", "confidence", "reason",
                 "field", "source", "record")

    def __init__(self, kind, value, decoded, confidence, reason,
                 field="", source="", record=None):
        self.kind = kind
        self.value = value
        #: What the value means once decoded, in words.
        self.decoded = decoded
        self.confidence = confidence
        #: Why this was reported, as a fact about the input, so the
        #: reasoning can be checked and disputed.
        self.reason = reason
        self.field = field
        self.source = source
        self.record = record

    def as_row(self):
        return {
            "Kind": self.kind,
            "Value": self.value,
            "Decoded": self.decoded,
            "Confidence": self.confidence,
            "Why": self.reason,
            "Field": self.field,
            "Source": self.source,
        }


# ── helpers ───────────────────────────────────────────────────────────

def _query_key_before(text, start):
    """The query-string key whose value contains offset `start`, if any.

    Context is what separates a timestamp from a coincidence. "t=1770468857"
    is a timestamp; the same digits inside an opaque asset id are not.
    """
    head = text[:start]
    cut = max(head.rfind("?"), head.rfind("&"), head.rfind(";"),
              head.rfind("#"))
    if cut < 0:
        return ""
    key = head[cut + 1:]
    if key.endswith("="):
        key = key[:-1]
    return key.strip().lower() if 0 < len(key) <= 24 else ""


def _looks_like_a_date_run(groups):
    """True when six hyphenated groups are a date and time.

    A filename such as "Screenshot_YYYY-MM-DD-hh-mm-ss-cc.png" contains
    "MM-DD-hh-mm-ss-cc", which has the shape of a MAC address and is a
    month, day, hour, minute, second and centisecond.
    """
    if any(not g.isdigit() for g in groups):
        return False            # a real MAC almost always carries a-f
    numbers = [int(g) for g in groups]
    return (numbers[0] <= 12 and numbers[1] <= 31
            and numbers[2] <= 23 and numbers[3] <= 59 and numbers[4] <= 59)


def _mac_detail(raw):
    """Vendor-independent facts a MAC's own bits state."""
    octets = [int(x, 16) for x in re.split(r"[:-]", raw)] if \
        re.search(r"[:-]", raw) else [int(raw[i:i + 2], 16)
                                      for i in range(0, 12, 2)]
    first = octets[0]
    bits = []
    bits.append("locally administered" if first & 0x02
                else "globally unique (has an OUI)")
    if first & 0x01:
        bits.append("multicast/group address")
    return "%s — %s" % (":".join("%02X" % o for o in octets), ", ".join(bits))


def _decode_epoch(digits):
    """(datetime, unit) for a digit run that plausibly encodes a time."""
    n = int(digits)
    width = len(digits)
    tries = []
    if width == 10:
        tries.append(("seconds since 1970", datetime.fromtimestamp, n))
    elif width == 13:
        tries.append(("milliseconds since 1970", datetime.fromtimestamp,
                      n / 1000.0))
    elif width == 16:
        tries.append(("microseconds since 1970", datetime.fromtimestamp,
                      n / 1000000.0))
    elif width in (17, 18):
        # FILETIME: 100 ns since 1601. Also .NET ticks: 100 ns since 0001.
        tries.append(("100-nanosecond intervals since 1601 (FILETIME)",
                      None, n))
        tries.append(("100-nanosecond intervals since 0001 (.NET ticks)",
                      None, n))
    for unit, fn, value in tries:
        try:
            if fn is not None:
                when = fn(value, timezone.utc)
            elif "1601" in unit:
                when = _1601 + timedelta(microseconds=value / 10)
            else:
                when = datetime.fromtimestamp(value / 10000000.0
                                              - _0001_OFFSET, timezone.utc)
        except (OverflowError, OSError, ValueError):
            continue
        if _FLOOR <= when <= _CEIL:
            return when, unit
    return None, ""


def _guid_detail(raw):
    """What a GUID's layout says about how it was made.

    A version-1 UUID carries the 60-bit time it was generated and, in its
    last six bytes, the MAC address of the machine that generated it: a
    hardware identifier and a clock reading inside a URL.
    """
    hexed = raw.replace("-", "")
    version = hexed[12]
    variant = int(hexed[16], 16)
    rfc = 0x8 <= variant <= 0xB
    if not rfc:
        return ("not an RFC-4122 UUID (variant nibble %s) — an opaque "
                "identifier, not a decodable one" % hexed[16]), None, None
    if version != "1":
        return ("RFC-4122 version %s — %s" % (
            version, {"3": "MD5 name-based", "4": "random",
                      "5": "SHA-1 name-based"}.get(version, "unspecified")),
            None, None)
    ticks = int(hexed[13:16] + hexed[8:12] + hexed[0:8], 16)
    try:
        when = _1601 + timedelta(microseconds=ticks / 10)
    except (OverflowError, ValueError):
        when = None
    node = hexed[20:32]
    mac = ":".join(node[i:i + 2].upper() for i in range(0, 12, 2))
    detail = "RFC-4122 version 1 — generated %s by the machine with MAC %s" \
        % (when.strftime("%Y-%m-%d %H:%M:%S UTC") if when else "at an "
           "undecodable time", mac)
    return detail, when, mac


def _b64_text(chunk):
    """A base64 run decoded, when it decodes to something readable."""
    if len(chunk) < 12 or len(chunk) % 4:
        return ""
    try:
        raw = base64.b64decode(chunk, validate=True)
    except (binascii.Error, ValueError):
        return ""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    printable = sum(1 for c in text if c.isprintable())
    if not text.strip() or printable < len(text) * 0.9 or len(text) < 6:
        return ""
    return text


# ── extractors ────────────────────────────────────────────────────────

def _mac_findings(text):
    for match in _MAC_SHAPE.finditer(text):
        raw = match.group(1)
        groups = re.split(r"[:-]", raw)
        key = _query_key_before(text, match.start())
        named = key in _MAC_KEYS
        if _looks_like_a_date_run(groups) and not named:
            # The sixteen false positives. Say nothing rather than say this.
            continue
        has_hex_letter = any(c in "abcdefABCDEF" for c in raw)
        if named:
            confidence, why = HIGH, "the parameter is named %r" % key
        elif ":" in raw and has_hex_letter:
            confidence, why = HIGH, ("colon-separated and contains hex "
                                     "letters, which a date cannot")
        elif has_hex_letter:
            confidence, why = MEDIUM, ("contains hex letters, so it is not a "
                                       "date, but nothing names it a MAC")
        else:
            confidence, why = LOW, ("six hex pairs, but all decimal and "
                                    "nothing names it -- could be anything")
        yield Finding("MAC address", raw, _mac_detail(raw), confidence, why)
    for match in _MAC_BARE.finditer(text):
        key = _query_key_before(text, match.start())
        if key in _MAC_KEYS:
            raw = match.group(1)
            yield Finding("MAC address", raw, _mac_detail(raw), HIGH,
                          "twelve hex characters in a parameter named %r"
                          % key)


def _ymd(eight):
    """A YYYYMMDD run as a date, or None if it is not one."""
    try:
        return datetime(int(eight[:4]), int(eight[4:6]), int(eight[6:8]),
                        tzinfo=timezone.utc)
    except ValueError:
        return None


def _mshist_findings(text):
    """The date range a Windows history container is named for."""
    for match in _MSHIST_RANGE.finditer(text):
        start, end = _ymd(match.group(1)), _ymd(match.group(2))
        if start is None or end is None or not start <= end:
            continue
        yield Finding(
            "History period", match.group(0),
            "container covers %s to %s"
            % (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
            HIGH,
            "two consecutive YYYYMMDD dates, which is how Windows names a "
            "history container for the week it covers")


def _mshist_spans(text):
    """Offsets covered by a container date range, so epochs skip them."""
    spans = []
    for match in _MSHIST_RANGE.finditer(text):
        if _ymd(match.group(1)) and _ymd(match.group(2)):
            spans.append((match.start(), match.end()))
    return spans


def _epoch_findings(text, record_time=None):
    skip = _mshist_spans(text)
    for match in _DIGITS.finditer(text):
        digits = match.group(1)
        # A container's date range is two dates, not a microsecond clock.
        # Read as an epoch it put these records in 2034.
        if any(s <= match.start() and match.end() <= e for s, e in skip):
            continue
        when, unit = _decode_epoch(digits)
        if when is None:
            continue
        key = _query_key_before(text, match.start())
        named = key in _TIME_KEYS
        stamp = when.strftime("%Y-%m-%d %H:%M:%S UTC")
        detail = "%s (%s)" % (stamp, unit)
        if named:
            confidence = HIGH
            why = "the parameter is named %r, which names a time" % key
        elif record_time is not None and abs(
                (when - record_time).total_seconds()) <= 86400:
            confidence = HIGH
            why = ("within a day of this record's own timestamp, so the two "
                   "corroborate each other")
        elif len(digits) == 13:
            confidence = MEDIUM
            why = ("thirteen digits decoding to a plausible date -- the "
                   "usual shape of a JavaScript millisecond clock")
        else:
            confidence = LOW
            why = ("a digit run that happens to decode to a plausible date; "
                   "nothing names it a time")
        # An embedded time that disagrees with the record's own time is
        # worth an analyst's attention rather than being averaged away.
        if record_time is not None:
            drift = (when - record_time).total_seconds()
            if abs(drift) > 86400:
                detail += "  |  %+.1f days from this record's timestamp" % (
                    drift / 86400.0)
        yield Finding("Epoch timestamp", digits, detail, confidence, why)


def _guid_findings(text):
    for match in _GUID.finditer(text):
        raw = match.group(1)
        detail, when, mac = _guid_detail(raw)
        confidence = HIGH if mac else MEDIUM
        why = ("its version and variant nibbles decode, so this is a real "
               "UUID and its layout is readable"
               if mac else "matches the UUID shape exactly")
        yield Finding("GUID / UUID", raw, detail, confidence, why)
        if mac:
            yield Finding(
                "MAC address", mac, _mac_detail(mac.replace(":", "")), HIGH,
                "carried in the node field of version-1 UUID %s" % raw)
        if when:
            yield Finding(
                "Epoch timestamp", raw,
                when.strftime("%Y-%m-%d %H:%M:%S UTC")
                + " (60-bit UUID version-1 clock)", HIGH,
                "the time field of version-1 UUID %s" % raw)


def _simple_findings(text):
    for match in _IPV4.finditer(text):
        raw = match.group(1)
        first, second = (int(p) for p in raw.split(".")[:2])
        if first == 10 or (first == 172 and 16 <= second <= 31) \
                or (first == 192 and second == 168):
            note = "private address (RFC 1918) - an address on a local network"
        elif first == 127:
            note = "loopback - this machine"
        elif first == 169 and second == 254:
            note = "link-local - assigned when no DHCP server answered"
        else:
            note = "routable address"
        yield Finding("IPv4 address", raw, note, MEDIUM,
                      "four dotted octets, each in range")
    for match in _EMAIL.finditer(text):
        address = match.group(1)
        reason = "local part, @ and a dotted domain"
        local, domain = address.rsplit("@", 1)
        stem, _dot, last = domain.rpartition(".")
        if last.lower() in _FILE_EXTENSIONS and "." in stem:
            address = "%s@%s" % (local, stem)
            reason += ("; the trailing .%s is a file extension (the address "
                       "is part of a file name)" % last)
        yield Finding("Email address", address,
                      "domain %s" % address.rsplit("@", 1)[-1],
                      MEDIUM, reason)
    for match in _SID.finditer(text):
        raw = match.group(1)
        rid = raw.rsplit("-", 1)[-1]
        well_known = {"500": "the built-in Administrator",
                      "501": "the built-in Guest",
                      "512": "Domain Admins", "513": "Domain Users"}
        note = well_known.get(rid, "relative identifier %s" % rid)
        yield Finding("Windows SID", raw, note, HIGH,
                      "the S-1-<authority>-<sub> form is unambiguous")
    for match in _COORDS.finditer(text):
        yield Finding("Coordinates", "%s, %s" % match.groups(),
                      "latitude %s, longitude %s" % match.groups(), MEDIUM,
                      "a latitude/longitude pair with enough decimal places "
                      "to be a real fix rather than a version number")


def _machine_findings(text):
    """Account, host and volume -- the "whose machine" indicators."""
    seen_users = set()
    for pattern, why in ((_VISITED,
                          "the Windows history prefix names the account "
                          "that visited it"),
                         (_USERDIR,
                          "the path runs through that account's profile "
                          "directory")):
        for match in pattern.finditer(text):
            name = match.group(1)
            if name.lower() in seen_users or not name.strip():
                continue
            seen_users.add(name.lower())
            yield Finding("User account", name, "Windows account name",
                          HIGH, why)
    for match in _UNC.finditer(text):
        yield Finding("Remote host", match.group(1),
                      "a UNC path - the file was on another machine or share",
                      HIGH, "a UNC host/share path names the host directly")
    for match in _FILE_HOST.finditer(text):
        host = match.group(1)
        if len(host) == 1 or host.lower() in ("localhost", "127.0.0.1"):
            continue
        yield Finding("Remote host", host,
                      "named in a file:// URL, so not this machine's disk",
                      MEDIUM, "a file:// URL with a host component")
    letters = {}
    for match in _DRIVE.finditer(text):
        letters.setdefault(match.group(1).upper(), match.start())
    for letter in letters:
        note = ("the system volume" if letter == "C"
                else "a volume other than C: - removable or mapped media, "
                     "which may no longer be attached")
        yield Finding("Volume", "%s:" % letter, note,
                      HIGH if letter != "C" else LOW,
                      "a drive letter at the head of a local path")


def _b64_findings(text):
    for chunk in re.findall(r"(?<![A-Za-z0-9+/=])"
                            r"([A-Za-z0-9+/]{16,}={0,2})"
                            r"(?![A-Za-z0-9+/=])", text):
        decoded = _b64_text(chunk)
        if decoded:
            yield Finding("Base64 payload", chunk,
                          "decodes to: " + decoded, MEDIUM,
                          "valid base64 that decodes to printable text, "
                          "which random identifiers do not")


#: Every extractor, in the order their findings should be read.
_EXTRACTORS = (_machine_findings, _mac_findings, _guid_findings,
               _simple_findings, _b64_findings, _mshist_findings)

#: The fields worth scanning on a record, and what to call them on screen.
SCANNED_FIELDS = (("Url", "URL"), ("CleanUrl", "URL (decoded)"),
                  ("RedirectUrl", "Redirect target"),
                  ("Filename", "File name"), ("SearchTerms", "Search terms"))


def scan_text(text, record_time=None):
    """Every indicator inside one string."""
    if not text:
        return []
    found = []
    for extractor in _EXTRACTORS:
        found.extend(extractor(text))
    found.extend(_epoch_findings(text, record_time))
    return found


def _record_time(record, time_key):
    """The instant to anchor this record's findings to, or None.

    The raw column first: ese_parser stores a live entry's AccessedTime as
    a display string and keeps the int64 in AccessedTime_raw, so the raw
    value is what anchors a live record. The anchor lets _epoch_findings
    grade a value "within a day of this record's own timestamp" as HIGH
    and state the drift otherwise.

    A datetime is used next: a carved record's NearbyFiletime, or any
    caller that passes one.
    """
    raw = record.get(time_key + "_raw")
    if raw is not None and not isinstance(raw, bool):
        when = filetime_to_dt(raw)
        if when is not None:
            return when
    when = record.get(time_key)
    if not isinstance(when, datetime):
        return None
    return when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when


def scan_records(records, time_key="AccessedTime"):
    """Every indicator across a set of records, de-duplicated per record.

    Identical (kind, value) pairs within one record collapse, so the
    caller gets one row per distinct indicator per record.
    """
    out = []
    for record in records:
        when = _record_time(record, time_key)
        seen = set()
        for key, label in SCANNED_FIELDS:
            text = record.get(key)
            if not isinstance(text, str) or not text:
                continue
            for finding in scan_text(text, when):
                token = (finding.kind, finding.value)
                if token in seen:
                    continue
                seen.add(token)
                finding.field = label
                finding.source = text
                finding.record = record
                out.append(finding)
    return out


def summarise(findings):
    """Distinct values per kind, most frequent first.

    `fields` and `records` are kept alongside the tally, not derived from
    it afterwards, because scan_records is the only place that knows them
    and Finding already carries both.

    WHY fields. SCANNED_FIELDS covers five places an indicator can be
    read from, and collapsing them loses the difference between a MAC
    address that appears in a URL and one that appears in a cached
    filename -- two different claims about the same string. A set, so a
    value seen in the same field on nine hundred records names that field
    once.

    WHY records, and why by reference. "Records: N" is a dead number
    without a way to reach the N. These are the SAME record dicts the
    caller passed in -- already resident for the life of the session --
    so this is one pointer per finding, never a copy.
    """
    tally = {}
    for finding in findings:
        bucket = tally.setdefault(finding.kind, {})
        entry = bucket.setdefault(finding.value, {
            "count": 0, "decoded": finding.decoded,
            "confidence": finding.confidence, "reason": finding.reason,
            "fields": set(), "records": []})
        entry["count"] += 1
        if finding.field:
            entry["fields"].add(finding.field)
        if finding.record is not None:
            entry["records"].append(finding.record)
        # Keep the strongest justification seen for this value.
        order = {LOW: 0, MEDIUM: 1, HIGH: 2}
        if order[finding.confidence] > order[entry["confidence"]]:
            entry.update(confidence=finding.confidence,
                         reason=finding.reason, decoded=finding.decoded)
    return tally


_FILE_TYPE = re.compile(r"^[A-Za-z0-9]{1,8}$")


def path_volume(path):
    """The volume a decoded Windows path is on: "E:" for a drive letter
    (upper-cased), "\\\\server\\share" for a UNC path, "" when the path
    names neither. Derived from the path beside it."""
    text = str(path or "")
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        return text[0].upper() + ":"
    if text.startswith("\\\\"):
        parts = text[2:].split("\\")
        if len(parts) >= 2 and parts[0] and parts[1]:
            return "\\\\%s\\%s" % (parts[0], parts[1])
    return ""


def path_file_type(path):
    """The extension of the path's LAST segment, lower-cased and without
    the dot -- "" when that segment has none (a folder, usually). A dot in
    a folder name further up is not the file's type, and anything longer
    than eight characters, not alphanumeric, or a bare version number
    ("3.12") is not read as one."""
    last = str(path or "").replace("/", "\\").rsplit("\\", 1)[-1]
    if "." not in last:
        return ""
    ext = last.rsplit(".", 1)[1]
    if not _FILE_TYPE.match(ext):
        return ""
    # Digits alone are a version ("Python 3.12") far more often than a
    # type, except in the split-archive shape: image.001, image.002.
    if ext.isdigit() and len(ext) != 3:
        return ""
    return ext.lower()


def windows_path_from_file_url(url):
    """A file: URL as the Windows path it names -- percent-decoded,
    backslashes, a UNC path for a host. "" for anything that is not a
    file: URL. Derived: the stored URL stays beside it on every surface."""
    text = str(url or "")
    if not text.lower().startswith("file:"):
        return ""
    rest = text[5:]
    if rest.startswith("////"):
        # file:////server/share and file://///server/share: a UNC path
        # written after an empty host.
        return "\\\\" + unquote(rest.lstrip("/")).replace("/", "\\")
    if rest.startswith("///"):
        return unquote(rest[3:]).replace("/", "\\")
    if rest.startswith("//"):
        host, _sep, path = rest[2:].partition("/")
        if host.lower() == "localhost":
            # file://localhost/C:/... names this machine's own drive.
            return unquote(path).replace("/", "\\")
        return "\\\\" + unquote(rest[2:]).replace("/", "\\")
    return unquote(rest.lstrip("/")).replace("/", "\\")
