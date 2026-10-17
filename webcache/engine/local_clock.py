"""MSHist containers' local clock, and how their UTC is derived.

An MSHist history container stores ModifiedTime on the machine's LOCAL
wall clock. Measured on five exhibits: of the MSHist History records that
have a History-container twin for the same URL, 20/21, 415/457, 151/169,
83/105 and 73/83 carry the twin's SPS id-24 LOCAL value in ModifiedTime,
and 0 carry the twin's UTC ModifiedTime. AccessedTime, ExpiryTime and
SyncTime of the same records match the twin's UTC columns and are not
local; CreationTime was 0 on every one. So exactly one column is on the
local clock, and only on MSHist records, recognised by the
':YYYYMMDDYYYYMMDD:' URL prefix split_history_url() parses into
MSHistFrom, which live and carved records both carry.

UTC is DERIVED per record, never from one offset applied to every date: a
zone that observes daylight saving shows two offsets an hour apart, and a
median of those is an hour wrong for the minority season, or on an even
split an offset no clock had (-04:30 between -05:00 and -04:00).
stamp_local_clock() takes, in order:

  1. the offset of the History twin that recorded the same visit (its
     SPS id-24 LOCAL value equals this record's stored ModifiedTime): an
     exact observation of the offset at that moment;
  2. when the exhibit shows more than one offset, the offset observed
     nearest in time to this record, named as such (INF);
  3. otherwise the single recovered zone.

An offset is only one observed on at least two History records (a mode of
the SPS id-24 deltas, rounded to 15 minutes); a lone outlier delta is
never adopted, and two offsets are never averaged. With no recovered zone
there is no UTC: utc_raw() returns 0 and clock_note() says why.

Engine-only: ese_parser imports this module and forensic_engine imports
ese_parser, so this imports neither.
"""
import bisect
import datetime
import re
from collections import Counter, defaultdict, namedtuple

from .sps_decoder import filetime_to_dt_naive

#: The columns an MSHist record stores on the LOCAL clock. See the module
#: docstring for the measurement; a column is added here only with one.
MSHIST_LOCAL_COLUMNS = frozenset({"ModifiedTime_raw"})
#: The offset, in seconds, stamped onto an MSHist record: the one its UTC
#: is derived with. Present-and-None means no zone was recovered.
TZ_OFFSET_KEY = "TzOffsetSeconds"
#: Where that offset came from, in words ("the recovered zone", ...).
TZ_SOURCE_KEY = "TzOffsetSource"
TICKS_PER_SECOND = 10_000_000
#: Offsets are real-world zone offsets: whole quarter hours.
OFFSET_STEP_SECONDS = 900
#: A twin's LOCAL value "equals" a stored ModifiedTime within this.
PAIR_TOLERANCE_TICKS = 2 * TICKS_PER_SECOND
#: An offset is a mode -- a clock the machine actually kept -- only when
#: at least this many History records show it, and at least this share.
MODE_MIN_COUNT = 2
MODE_MIN_SHARE = 0.10
#: Fewer SPS id-24 pairs than this and no zone is recovered at all.
MIN_ZONE_OBSERVATIONS = 5

SOURCE_ZONE = "the recovered zone"
SOURCE_TWIN = "the offset the History record of the same visit shows"
SOURCE_NEAREST = ("the offset observed nearest in time (a History record "
                  "%s away); this exhibit shows %d offsets (DST or a zone "
                  "change)")

LOCAL_DERIVED_NOTE = ("stored as LOCAL wall-clock by an MSHist container; "
                      "UTC derived with %s, %s (INF)")
LOCAL_NO_ZONE_NOTE = ("stored as LOCAL wall-clock by an MSHist container; "
                      "no time zone was recovered, so no UTC is stated")

#: One History record's observation of the machine offset: its SPS id-24
#: LOCAL FILETIME, its UTC ModifiedTime, the delta rounded to a quarter
#: hour, and its clean URL (for twin matching).
Observation = namedtuple("Observation", "local utc offset url")


def _int(value):
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _valid(raw):
    """A FILETIME that decodes to a date, else 0."""
    return raw if raw > 0 and filetime_to_dt_naive(raw) is not None else 0


def is_mshist_record(entry):
    return bool((entry or {}).get("MSHistFrom"))


def is_local_clock(entry, field):
    return field in MSHIST_LOCAL_COLUMNS and is_mshist_record(entry)


def zone_label(offset_seconds):
    if offset_seconds is None:
        return ""
    sign = "+" if offset_seconds >= 0 else "-"
    hours, rest = divmod(abs(int(offset_seconds)), 3600)
    return "UTC%s%02d:%02d" % (sign, hours, rest // 60)


# --- what the exhibit shows about its own clock ---------------------------

def zone_observations(entries):
    """Every History (non-MSHist) record's observation of the offset, in
    LOCAL-time order: SPS id 24 is local, ModifiedTime is UTC, and the
    difference is the machine offset at that visit."""
    out = []
    for e in entries or ():
        if not isinstance(e, dict) or is_mshist_record(e):
            continue
        local = _valid(_int(e.get("SPS_LastVisitLocal_raw")))
        utc = _valid(_int(e.get("ModifiedTime_raw")))
        if not local or not utc:
            continue
        delta = (local - utc) / TICKS_PER_SECOND
        offset = int(round(delta / OFFSET_STEP_SECONDS)) * OFFSET_STEP_SECONDS
        out.append(Observation(local, utc, offset, e.get("CleanUrl") or ""))
    out.sort(key=lambda o: o.local)
    return out


def offset_modes(observations):
    """The offsets the machine actually kept, commonest first: each seen on
    at least MODE_MIN_COUNT records and MODE_MIN_SHARE of them. A lone
    outlier delta is not a clock."""
    counts = Counter(o.offset for o in observations or ())
    floor = max(MODE_MIN_COUNT, MODE_MIN_SHARE * sum(counts.values()))
    return [(off, n) for off, n in counts.most_common() if n >= floor]


def offset_periods(observations, source="live"):
    """Every offset the observations show, commonest first: how many
    records show it, the first and last UTC date it was seen (YYYY-MM-DD),
    and whether it is adopted (offset_modes). A lone reading is listed but
    not adopted, so a short period in another zone is still visible."""
    adopted = {off for off, _n in offset_modes(observations)}
    seen = defaultdict(list)
    for o in observations or ():
        seen[o.offset].append(o.utc)
    epoch = datetime.datetime(1601, 1, 1)
    out = []
    for off, stamps in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        days = sorted((epoch + datetime.timedelta(microseconds=t // 10))
                      .strftime("%Y-%m-%d") for t in stamps)
        out.append({"offset": zone_label(off), "records": len(stamps),
                    "first": days[0], "last": days[-1],
                    "adopted": off in adopted, "source": source})
    return out


def recover_zone(observations):
    """The exhibit's principal offset, or None.

    The MODAL offset, never a median or mean: with two offsets an hour
    apart a median can sit between them, at an offset no clock kept. A
    tie between modes goes to the one observed most recently -- the
    machine's clock when the database was last written."""
    observations = list(observations or ())
    if len(observations) < MIN_ZONE_OBSERVATIONS:
        return None
    modes = offset_modes(observations)
    if not modes:
        return None
    top = modes[0][1]
    tied = {off for off, n in modes if n == top}
    if len(tied) == 1:
        return modes[0][0]
    latest = max((o for o in observations if o.offset in tied),
                 key=lambda o: o.utc)
    return latest.offset


# --- one record ------------------------------------------------------------

def clock_note(entry):
    """The stated reason for an MSHist record's derived (or absent) UTC;
    "" for any other record."""
    if not is_mshist_record(entry):
        return ""
    offset = (entry or {}).get(TZ_OFFSET_KEY)
    if offset is None:
        return LOCAL_NO_ZONE_NOTE
    return LOCAL_DERIVED_NOTE % (zone_label(offset),
                                 entry.get(TZ_SOURCE_KEY) or SOURCE_ZONE)


_NOTE_HEAD = "stored as LOCAL wall-clock by an MSHist container; "


def short_basis(text):
    """A time-basis sentence carrying clock_note()'s statement, cut to its
    gist for a grid cell: "LOCAL clock, UTC derived (INF)" or "LOCAL
    clock, no UTC stated". Anything else is returned unchanged. The whole
    statement stays on the record, in the tooltip and in every export."""
    text = str(text or "")
    at = text.find(_NOTE_HEAD)
    if at < 0:
        return text
    gist = ("LOCAL clock, no UTC stated" if LOCAL_NO_ZONE_NOTE in text
            else "LOCAL clock, UTC derived (INF)")
    return text[:at] + gist


def utc_raw(entry, field):
    """The column as a UTC FILETIME. A UTC column is returned as stored; a
    local-clock column is shifted by the offset stamped on the record, or 0
    when there is none or the stored value is not a decodable time -- 0 is
    every caller's existing "no usable time"."""
    raw = _int((entry or {}).get(field))
    if not raw or not is_local_clock(entry, field):
        return raw
    offset = entry.get(TZ_OFFSET_KEY)
    if offset is None or not _valid(raw):
        return 0
    return _valid(raw - int(offset) * TICKS_PER_SECOND)


def is_unplaced(entry):
    """An MSHist record holding a real LOCAL time that cannot be put on
    the UTC axis because no zone was recovered for it. Not undated: it
    has a time, on a clock this tool cannot convert."""
    if not is_mshist_record(entry):
        return False
    raw = _valid(_int((entry or {}).get("ModifiedTime_raw")))
    return bool(raw) and not utc_raw(entry, "ModifiedTime_raw")


def local_naive(entry):
    """The record's local wall-clock visit time as a naive datetime: SPS
    id 24 when the record has one, else an MSHist record's stored
    ModifiedTime, else None."""
    entry = entry or {}
    sps = _int(entry.get("SPS_LastVisitLocal_raw"))
    if sps:
        return filetime_to_dt_naive(sps)
    if is_mshist_record(entry):
        stored = _int(entry.get("ModifiedTime_raw"))
        if stored:
            return filetime_to_dt_naive(stored)
    return None


def derivation_text(entry):
    """How an MSHist record's UTC ModifiedTime was reached from the raw
    FILETIME, for the one place the raw number is printed beside it."""
    raw = _int((entry or {}).get("ModifiedTime_raw"))
    if not raw:
        return ""
    offset = (entry or {}).get(TZ_OFFSET_KEY)
    if offset is None or not utc_raw(entry, "ModifiedTime_raw"):
        return ("[no UTC: raw FILETIME %d is LOCAL wall-clock and no time "
                "zone was recovered]" % raw)
    op = "−" if offset >= 0 else "+"
    return ("[derived: LOCAL raw FILETIME %d %s %s s (%s, %s)]"
            % (raw, op, "{:,}".format(abs(int(offset))), zone_label(offset),
               entry.get(TZ_SOURCE_KEY) or SOURCE_ZONE))


def _display(raw, suffix):
    """The parser's own display shape (ese_parser.stamp_str), rebuilt here
    because this module may not import ese_parser."""
    dt = filetime_to_dt_naive(raw) if raw else None
    if dt is None:
        return ""
    text = dt.strftime("%Y-%m-%d %H:%M:%S")
    if dt.microsecond:
        text += ".%03d" % (dt.microsecond // 1000)
    return "%s %s" % (text, suffix)


#: The one sentence every surface prints for an MSHist stored
#: ModifiedTime: Search, the Table
#: Browser, carved hits. The local digits are never labelled UTC.
DESCRIBE_LOCAL = "local: %s"
DESCRIBE_DERIVED = "%s; UTC (derived, %s): %s%s"
DESCRIBE_NO_ZONE = "%s; no UTC: no time zone was recovered"
#: Added when no parsed record was found for a stored value, so the
#: principal zone stood in for the record's own offset.
FALLBACK_MARK = " (recovered zone)"


def describe_local_filetime(raw, offset, fallback=False):
    """"local: <digits>; UTC (derived, UTC+hh:mm): <utc>" for a stored
    LOCAL FILETIME, derived with `offset`; "...; no UTC: ..." when there
    is none. `fallback` says the offset is the recovered zone standing in
    for a record that could not be found. "" when `raw` is no time."""
    raw = _valid(_int(raw))
    if not raw:
        return ""
    text = DESCRIBE_LOCAL % _display(raw, "").strip()
    if offset is None:
        return DESCRIBE_NO_ZONE % text
    utc = _valid(raw - int(offset) * TICKS_PER_SECOND)
    if not utc:
        return DESCRIBE_NO_ZONE % text
    return DESCRIBE_DERIVED % (text, zone_label(offset),
                               _display(utc, "").strip(),
                               FALLBACK_MARK if fallback else "")


def mshist_entry_index(entries):
    """{(ContainerId, EntryId): entry} over the MSHist records in
    `entries`: how a raw table row finds the parsed record, and with it
    the offset that record was stamped with."""
    index = {}
    for entry in entries or ():
        if isinstance(entry, dict) and is_mshist_record(entry):
            index[(entry.get("ContainerId"), entry.get("EntryId"))] = entry
    return index


def clock_snapshot(entries, zone):
    """(zone, {(ContainerId, EntryId): offset}) for every stamped MSHist
    record: what a parser that opens the exhibit WITHOUT parsing its
    entries (the Search worker's) needs to read an MSHist ModifiedTime on
    the same clock as History. Small: one int per MSHist
    record."""
    offsets = {}
    for entry in entries or ():
        if (isinstance(entry, dict) and is_mshist_record(entry)
                and TZ_OFFSET_KEY in entry):
            offsets[(entry.get("ContainerId"), entry.get("EntryId"))] = \
                entry.get(TZ_OFFSET_KEY)
    return zone, offsets


def describe_stored_cell(entry, raw, zone):
    """The describe_local_filetime sentence for one stored MSHist
    ModifiedTime: with the offset stamped on its parsed `entry` when there
    is one, else the principal `zone`, marked as such."""
    if entry is not None and TZ_OFFSET_KEY in entry:
        return describe_local_filetime(raw, entry.get(TZ_OFFSET_KEY))
    return describe_local_filetime(raw, zone, fallback=zone is not None)


def _distance(ticks):
    hours = abs(ticks) / (3600 * TICKS_PER_SECOND)
    if hours < 48:
        return "%.1f h" % hours
    return "%.0f days" % (hours / 24)


def _choose_offset(raw, url, zone, modes, by_url, usable, locals_):
    """(offset, source) for one stored LOCAL value -- see the module
    docstring for the order. Only an observed mode is ever returned."""
    if zone is None:
        return None, None
    mode_set = {off for off, _n in modes}
    for obs in by_url.get(url, ()):
        if abs(obs.local - raw) <= PAIR_TOLERANCE_TICKS:
            return obs.offset, SOURCE_TWIN
    if len(mode_set) > 1 and raw and usable:
        i = bisect.bisect_left(locals_, raw)
        near = [usable[j] for j in (i - 1, i) if 0 <= j < len(usable)]
        best = min(near, key=lambda o: abs(o.local - raw))
        return best.offset, SOURCE_NEAREST % (_distance(best.local - raw),
                                              len(mode_set))
    return zone, SOURCE_ZONE


def observed_offset(entry, modes):
    """The machine offset THIS History record's own SPS id-24 pair shows
    (SPS local minus UTC ModifiedTime, to the quarter hour), when it is
    one of `modes` -- a clock the exhibit actually kept; else None. A lone
    outlier delta is never adopted. The Timeline cuts local days with it
    and the case summary prints each end with it."""
    if not isinstance(entry, dict) or is_mshist_record(entry):
        return None
    local = _valid(_int(entry.get("SPS_LastVisitLocal_raw")))
    utc = _valid(_int(entry.get("ModifiedTime_raw")))
    if not local or not utc:
        return None
    step = OFFSET_STEP_SECONDS
    offset = int(round(((local - utc) / TICKS_PER_SECOND) / step)) * step
    return offset if offset in modes else None


def record_offset(entry, zone, modes):
    """The offset that puts THIS record's UTC instant on its own local
    clock: an MSHist record's stamped offset, else its own observed
    offset, else the recovered `zone`."""
    if is_mshist_record(entry):
        own = (entry or {}).get(TZ_OFFSET_KEY)
        if own is not None:
            return own
        return zone
    observed = observed_offset(entry, modes)
    return observed if observed is not None else zone


# --- one visit, two containers --------------------

#: On an MSHist record: [(ContainerName, EntryId)] of the History record
#: of the same visit (at most one). On a History record: every MSHist
#: record of that visit. Absent when there is no pair.
TWIN_KEY = "VisitTwin"
#: A twin recovered by carving, whose container was not recorded.
RECOVERED_TWIN = "a recovered MSHist copy (container not recorded)"

_MSHIST_RANGE = re.compile(r"^MSHist\d{2}(\d{8})(\d{8})", re.I)


def mshist_span_word(container_name):
    """"daily" or "weekly" from an MSHist container's own date range, ""
    when the name says neither."""
    match = _MSHIST_RANGE.match(str(container_name or ""))
    if not match:
        return ""
    try:
        start, end = (datetime.datetime.strptime(g, "%Y%m%d")
                      for g in match.groups())
    except ValueError:
        return ""
    return {1: "daily", 7: "weekly"}.get((end - start).days, "")


def pair_visit_twins(entries):
    """Link each MSHist record to the History-container record of the SAME
    visit: the same CleanUrl, and the History record's SPS id-24 LOCAL
    equal to the MSHist stored ModifiedTime within PAIR_TOLERANCE_TICKS.
    Two records of one visit in two containers -- both evidence, neither
    a copy, so they are linked and never merged or hidden. Needs no zone:
    both values are on the local clock. Returns the number of pairs."""
    entries = [e for e in entries or () if isinstance(e, dict)]
    history = defaultdict(list)
    for entry in entries:
        entry.pop(TWIN_KEY, None)
        if is_mshist_record(entry) or entry.get("ContainerType") != "History":
            continue
        local = _valid(_int(entry.get("SPS_LastVisitLocal_raw")))
        if local:
            history[entry.get("CleanUrl") or ""].append((local, entry))
    pairs = 0
    for entry in entries:
        if not is_mshist_record(entry):
            continue
        raw = _valid(_int(entry.get("ModifiedTime_raw")))
        if not raw:
            continue
        near = [(abs(local - raw), twin)
                for local, twin in history.get(entry.get("CleanUrl") or "", ())
                if abs(local - raw) <= PAIR_TOLERANCE_TICKS]
        if not near:
            continue
        _gap, twin = min(near, key=lambda pair: pair[0])
        entry[TWIN_KEY] = [(twin.get("ContainerName") or "",
                            twin.get("EntryId"))]
        twin.setdefault(TWIN_KEY, []).append(
            (entry.get("ContainerName") or "", entry.get("EntryId")))
        pairs += 1
    return pairs


def same_visit_text(entry):
    """What the other record of this visit is, in words; "" unpaired."""
    twins = (entry or {}).get(TWIN_KEY) or ()
    if not twins:
        return ""
    if is_mshist_record(entry):
        name, entry_id = twins[0]
        span = mshist_span_word(entry.get("ContainerName"))
        copy = "this is its MSHist %scopy" % ((span + " ") if span else "")
        if not name or entry_id is None:
            return "a recovered History record (%s)" % copy
        return "History record %s #%s (%s)" % (name, entry_id, copy)
    names = []
    for name, _entry_id in twins:
        # A carved twin: string carving cannot say which container held it.
        name = mshist_copy_label(name) if name else RECOVERED_TWIN
        if name not in names:
            names.append(name)
    return "also in %s" % ", ".join(names)


def mshist_copy_label(container_name):
    """An MSHist container said in words, its own name kept beside it:
    "its MSHist daily copy for 2024-06-30 (MSHist012024063020240701)". The
    bare name left the examiner to decode the dates; a name that is not an
    MSHist range is returned as it is."""
    name = str(container_name or "")
    match = _MSHIST_RANGE.match(name)
    span = mshist_span_word(name)
    if not match or not span:
        return name
    start, end = (datetime.datetime.strptime(g, "%Y%m%d").date()
                  for g in match.groups())
    when = (start.isoformat() if span == "daily"
            else "%s to %s" % (start.isoformat(), end.isoformat()))
    return "its MSHist %s copy for %s (%s)" % (span, when, name)


def stamp_local_clock(entries, offset_seconds, observations=None):
    """Stamp every MSHist record in `entries` with the offset its UTC is
    derived with (and where that offset came from), and set its display
    strings: the column labelled UTC ("ModifiedTime") gets the derived UTC,
    or "" when there is no zone, and the stored local value gets its own
    key ("ModifiedTimeLocal", labelled LOCAL). Returns how many records
    were stamped. The raw FILETIME, as the database stored it, is never
    modified.

    `observations` is zone_observations() over the exhibit's live records;
    without them every record takes `offset_seconds`."""
    # One visit held in two containers is linked whether or not a zone
    # was recovered.
    pair_visit_twins(entries)
    observations = list(observations or ())
    modes = offset_modes(observations)
    # Only an observation at a real mode is evidence of a clock; a lone
    # outlier delta (a twin whose SPS and ModifiedTime are different
    # visits) is never adopted, not even for its own twin.
    mode_set = {off for off, _n in modes}
    usable = [o for o in observations if o.offset in mode_set]
    locals_ = [o.local for o in usable]
    by_url = defaultdict(list)
    for o in usable:
        by_url[o.url].append(o)
    stamped = 0
    for entry in entries or ():
        if not isinstance(entry, dict) or not is_mshist_record(entry):
            continue
        raw = _valid(_int(entry.get("ModifiedTime_raw")))
        offset, source = _choose_offset(
            raw, entry.get("CleanUrl") or "", offset_seconds, modes,
            by_url, usable, locals_)
        entry[TZ_OFFSET_KEY] = offset
        entry[TZ_SOURCE_KEY] = source
        for field in MSHIST_LOCAL_COLUMNS:
            stored = _int(entry.get(field))
            if stored:
                entry[field[:-4]] = _display(utc_raw(entry, field), "UTC")
                entry[field[:-4] + "Local"] = _display(_valid(stored), "LOCAL")
        stamped += 1
    return stamped
