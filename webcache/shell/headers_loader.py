"""HTTP header records to rows, and the raw blob back into ordered pairs.

`parser` needs only an `all_entries` attribute and `engine` only
`structured_records`, so both builders are testable against a stub. Qt-free.

WHAT THIS VIEW DOES NOT LIST. ese_parser decodes a response-headers blob
by its detected class, not by its container (ese_parser._parse_record): a
blob that classifies "sps" is an [MS-PROPSTORE] property store and yields
SPS_* fields and no header dict. Most History records are of that kind,
so on a History-heavy exhibit this view lists far fewer records than the
status bar counts. That is neither a decode failure nor a filter, so
views/headers.py states it in the subtitle and the empty state, and
test_headers_loader.py tests the predicate.

WIRE ORDER AND REPEATED NAMES. ese_parser.decode_content_headers returns a
dict, so:

  * a repeated name (Set-Cookie, most often) keeps only its last value;
  * header order survives only as insertion order. Header order can
    itself be evidence.

header_pairs() re-splits the raw blob with the same line rule, so both
survive. This is an additional reading of bytes the record already
carries; ResponseHeadersText and the engine's consumers are unchanged.

ROW SIZE: 21 KEYS AT MOST. 19 data keys plus `_record`/`_kind`, within the
dict-size bucket tests/test_row_is_a_record.py measures (11-21 keys ->
464 B, 22 -> 832 B). Anything further belongs on `_record`.

So `_pairs` is not a row key: pair_export_rows() builds the pairs at
export time, for the visible rows only. PairCount is a row key, because
"Export header pairs (N)" is recounted on every filter change; it is
computed by the same header_pairs() the export uses, so the label and the
file agree (test_headers_loader.py checks this).

StatusText is not a row key: the pane and the detail dialog read the
record's pairs, whose first entry is the status line.
"""
from ..engine import forensic_engine
from ..engine.ese_parser import filetime_to_dt
from ..provenance import ABSENCE_EMPTY, CARVED_ORIGIN
from .record_kinds import K_CARVED_STRUCT, kind_for_entry

#: The header names that state a client IP address as the server saw it.
#: Lower-cased because HTTP header names are compared case-insensitively
#: on the wire; the DISPLAYED name keeps whatever case the record stored.
#:
#: Colour alone is not a finding: these drive a
#: real ClientIpHeaders column, a quick-filter chip, and a note in the
#: detail dialog that states the limit of what they show.
HEADER_INTEREST = ("x-forwarded-for", "x-real-ip", "cf-connecting-ip",
                   "x-client-ip", "true-client-ip")

#: What the synthetic `_status_line` key is called anywhere an examiner
#: reads it. The underscore name is this tool's own plumbing, and a report
#: carrying it is the tool showing its wiring.
STATUS_LINE_LABEL = "(status line)"

#: The sub-line under a client-IP header wherever one is rendered. One
#: literal, so the caveat cannot be worded two ways on two surfaces.
CLIENT_IP_NOTE = ("names a client IP address as the server saw it; "
                  "presence is not attribution")

#: side -> (raw blob key, decoded dict key).
_SIDES = {"response": ("ResponseHeaders_raw", "ResponseHeaders"),
          "request": ("RequestHeaders_raw", "RequestHeaders")}

#: The two sides, in the order every surface renders them.
DIRECTIONS = ("response", "request")


def duplicates_note(count):
    """The sentence shown wherever DuplicateCount is non-zero, defined
    once for the pane, the detail dialog and the export sidecar.

    It counts the lines that were overwritten, not the lines that share a
    name: a name that appears four times has three overwritten lines, and
    DuplicateCount is three, because three is what the decoded field list
    no longer holds.
    """
    return ("%d header line%s overwritten by a later line with the same "
            "name. The decoded field list keeps only the last of each; the "
            "pair export carries all of them."
            % (count, " was" if count == 1 else "s were"))


def carries_headers(entry):
    """Does this record carry HTTP headers at all?

    True when ResponseHeaders or RequestHeaders is a non-empty dict. An
    empty dict is a decode that produced nothing, and is not counted.

    A record whose response blob classified "sps" has neither key (see the
    module docstring).
    """
    entry = entry or {}
    for _side, (_raw_key, dict_key) in _SIDES.items():
        value = entry.get(dict_key)
        if isinstance(value, dict) and value:
            return True
    return False


def _split_blob(blob):
    """The raw blob as (name, value) pairs, in wire order.

    The line rule is decode_content_headers' own: utf-8 with a latin-1
    fallback, CRLF split, strip, skip blanks; a line with a colon that does
    not start with "HTTP/" is a header, and one that does is the status
    line. It matches the engine's rule exactly, so the two never count a
    different number of headers.
    """
    try:
        text = bytes(blob).decode("utf-8")
    except UnicodeDecodeError:
        text = bytes(blob).decode("latin-1")
    pairs = []
    for line in text.split("\r\n"):
        line = line.strip()
        if not line:
            continue
        if ":" in line and not line.startswith("HTTP/"):
            name, value = line.split(":", 1)
            pairs.append((name.strip(), value.strip()))
        elif line.startswith("HTTP/"):
            pairs.append((STATUS_LINE_LABEL, line))
    return pairs


def _from_decoded(decoded):
    """The fallback when a record has a decoded dict and no raw blob.

    Insertion order IS wire order for a dict decode_content_headers built,
    so this preserves as much as the dict can carry. What it cannot carry
    is the collapsed duplicates -- there is no way to recover a value the
    dict already overwrote -- so every pair here reads as unrepeated,
    which is the truth about this dict rather than a claim about the wire.
    """
    return [(STATUS_LINE_LABEL if name == "_status_line" else name, value)
            for name, value in decoded.items()]


def header_pairs(record, side):
    """(ordinal, name, value, repeats_name) for one side, in wire order.

    `side` is "response" or "request"; anything else raises.

    `repeats_name` is True when this exact, stripped name appears more
    than once on this side, the key the decoded dict uses, so it marks
    exactly the lines the dict collapsed. A case-insensitive match would
    also flag pairs the dict kept.
    """
    raw_key, dict_key = _SIDES[side]
    record = record or {}
    blob = record.get(raw_key)
    if isinstance(blob, (bytes, bytearray)) and len(blob):
        pairs = _split_blob(blob)
    else:
        decoded = record.get(dict_key)
        pairs = _from_decoded(decoded) if isinstance(decoded, dict) else []
    counts = {}
    for name, _value in pairs:
        counts[name] = counts.get(name, 0) + 1
    return [(ordinal, name, value, counts[name] > 1)
            for ordinal, (name, value) in enumerate(pairs, 1)]


def pairs_for(row):
    """Every pair on a row's record, response side first, each labelled
    with the side it came from.

    The direction is carried explicitly because the distinction exists
    ONLY in which key the dict came out of -- a file that drops it cannot
    tell a request header from a response one.
    """
    record = (row or {}).get("_record") or {}
    out = []
    for direction in DIRECTIONS:
        for ordinal, name, value, repeats in header_pairs(record, direction):
            out.append((direction, ordinal, name, value, repeats))
    return out


def total_pairs(rows):
    """The number "Export header pairs (N)" shows, over whatever rows are
    on screen. Arithmetic on a key each row already carries, so it costs
    nothing on a filter change."""
    return sum(int(row.get("PairCount") or 0) for row in rows)


def pair_export_rows(rows):
    """The transient shape export_formats.write_header_pairs_csv reads.

    Built at export time, on the GUI thread, for the visible rows only --
    never stored on a view row, per this module's own budget note. Eight
    keys: the six the pair writer reads off the record, `_kind` (which
    export_formats.origin_cell needs to tell an aggregate from a record),
    and `_pairs` itself.
    """
    out = []
    for row in rows:
        out.append({
            "CleanUrl": row.get("CleanUrl"),
            "ContainerId": row.get("ContainerId"),
            "EntryId": row.get("EntryId"),
            "ModifiedTime": row.get("ModifiedTime"),
            "Origin": row.get("Origin"),
            "Source": row.get("Source"),
            "_kind": row.get("_kind"),
            "_pairs": pairs_for(row),
        })
    return out


def _header_value(pairs, wanted):
    """The value of one header by case-insensitive name, last occurrence
    winning, as in the decoded dict, so a column here agrees with the
    detail dialog's field."""
    found = ""
    for _ordinal, name, value, _repeats in pairs:
        if name.lower() == wanted:
            found = value
    return found


def _client_ip_headers(pairs):
    """The notable header names this record carried, in wire order, each
    named once.

    Blank when there are none, not an absence token: the quick-filter chip
    is Condition("is not blank"), and a token would match every row.
    """
    seen = []
    for _ordinal, name, _value, _repeats in pairs:
        if name.lower() in HEADER_INTEREST and name not in seen:
            seen.append(name)
    return ", ".join(seen)


def _status_of(pairs):
    """(status code, class) from the status line, or the absence token.

    ABSENCE_EMPTY, never a dash: this codebase already has a vocabulary
    for absence (see provenance.ABSENCE_TOKENS and
    tests/test_absence_vocabulary.py) and a second spelling of the same
    fact is a second thing every consumer has to learn.

    StatusClass stays a plain "" when there is no code to classify. It is
    a FILTER KEY, not a displayed value -- the 4xx/5xx chip reads it and
    no column shows it -- and an absence token there would become a
    filterable value that reads like a status class of its own.
    """
    line = ""
    for _ordinal, name, value, _repeats in pairs:
        if name == STATUS_LINE_LABEL:
            line = value
            break
    tokens = line.split()
    if len(tokens) < 2:
        return ABSENCE_EMPTY, ""
    code = tokens[1]
    if len(code) == 3 and code.isdigit():
        return code, code[0] + "xx"
    return code, ""


def _blob_bytes(record, key):
    blob = record.get(key)
    return len(blob) if isinstance(blob, (bytes, bytearray)) else 0


def _header_row(entry, origin, source, kind):
    """One row. See this module's docstring for the 21-key budget."""
    resp = header_pairs(entry, "response")
    req = header_pairs(entry, "request")

    resp_names = {name for _o, name, _v, _r in resp
                  if name != STATUS_LINE_LABEL}
    req_names = {name for _o, name, _v, _r in req
                 if name != STATUS_LINE_LABEL}
    resp_lines = sum(1 for _o, name, _v, _r in resp
                     if name != STATUS_LINE_LABEL)
    req_lines = sum(1 for _o, name, _v, _r in req
                    if name != STATUS_LINE_LABEL)

    status, status_class = _status_of(resp)
    raw_ts, basis = forensic_engine.key_timestamp(entry)

    return {
        "CleanUrl": entry.get("CleanUrl") or entry.get("Url") or "",
        "Status": status,
        "StatusClass": status_class,
        # Distinct names, not lines, excluding the status line: what the
        # decoded field list holds.
        "RespCount": len(resp_names),
        "ReqCount": len(req_names),
        # The lines the dict dropped, both sides. A sortable column, so an
        # examiner can find these records rather than stumble on one.
        "DuplicateCount": ((resp_lines - len(resp_names))
                           + (req_lines - len(req_names))),
        # Every pair the export writes, status line included. Computed by
        # the SAME header_pairs() that writes them, so the button's number
        # and the file's row count are the same arithmetic.
        "PairCount": len(resp) + len(req),
        "ContentType": _header_value(resp, "content-type"),
        "Server": _header_value(resp, "server"),
        "ClientIpHeaders": _client_ip_headers(resp + req),
        "ContainerId": entry.get("ContainerId"),
        "ContainerName": entry.get("ContainerName") or "",
        "EntryId": entry.get("EntryId"),
        "ModifiedTime": filetime_to_dt(raw_ts) if raw_ts else None,
        # WHICH COLUMN THE RECORD'S CANONICAL INSTANT CAME FROM, in
        # key_timestamp()'s own words -- the same pair evidence_loader.
        # file_access_rows_from_parser already carries.
        "ModifiedTimeBasis": basis,
        "RespBytes": _blob_bytes(entry, "ResponseHeaders_raw"),
        "ReqBytes": _blob_bytes(entry, "RequestHeaders_raw"),
        "Origin": origin,
        "Source": source,
        "_record": entry,
        "_kind": kind,
    }


def header_rows_from_parser(parser):
    """The HTTP Headers row set, live records only.

    Every row has Origin="Live record" and Source="", as in every other
    loader, so carved_header_rows() concatenates onto this list directly.

    `_kind` is the record's own kind (kind_for_entry()), so the same record
    opened from here and from a Domains drill-down renders the same, and
    blob_source._KIND_BLOBS offers the raw ResponseHeaders_raw and
    RequestHeaders_raw tabs.
    """
    return [_header_row(entry, "Live record", "", kind_for_entry(entry))
            for entry in parser.all_entries if carries_headers(entry)]


def carved_header_rows(engine):
    """Carved records that carry HTTP headers, with the same keys as the
    live rows, so MainWindow concatenates the two into one row set.

    Only engine.structured_records are candidates: a URL-string carve has
    no blob. recovery_engine passes every structured record through
    ese_parser.normalise_record(), as for a live entry, which decodes a
    carved blob of class "http" into a ResponseHeaders dict, so
    carries_headers() applies unchanged.

    Origin is shown: these are RecordsView rows, so the Origin column, the
    carved row styling and markers, and the detail dialog's carved chip
    all apply.
    """
    return [_header_row(entry, CARVED_ORIGIN, entry.get("Source") or "",
                        K_CARVED_STRUCT)
            for entry in engine.structured_records if carries_headers(entry)]
