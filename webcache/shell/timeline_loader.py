"""What happened when: TimelineView's one row per period, and the records
inside one of them.

Qt-free. This layer calls the engine and reshapes the result;
forensic_engine.get_timeline() does the bucketing.

ONE ADMISSION RULE. Whether a record goes on the timeline is decided by
one predicate, _is_dated, which is forensic_engine.key_timestamp(): the
same stamp the bucketer uses. The loader, the nav badge and the
excluded-count line all read it, so their numbers agree.

CARVED-NESS IS AN IDENTITY SET. `carved_ids` holds id() of the admitted
carved entries; no Origin key is written onto an engine dict. Those dicts
are shared with Domains, Indicators, the Dashboard, the Recovery grid and
every export.

WHAT IS NOT ON THE TIMELINE IS COUNTED. undated_live and undated_carved
are stated in the count line: a record with no usable timestamp is a fact
about the exhibit, and leaving it out unstated would make the timeline
read as all of the activity.

SILENCES ARE MEASURED. get_timeline emits only periods that received a
record, and no zero-count rows are added. Each silence is measured and
shown on the row that follows it (GapBefore), in buckets at the current
grain, so "Empty days before: 22" is what the rows on screen show and it
rescales with the grain. (analyze_time_voids measures record-to-record
hours for Findings.)
"""
import datetime
from collections import Counter

from ..engine import forensic_engine, local_clock
from ..engine.ese_parser import filetime_to_dt
from .. import provenance
from ..provenance import ABSENCE_NOT_APPLICABLE, CARVED_ORIGIN
from . import record_counts, record_kinds
from .record_kinds import K_PERIOD

#: (grain key, switcher label, plural noun). Declared FINE TO COARSE --
#: the order an examiner scans them in -- while the view opens on
#: DEFAULT_GRAIN, which RecordsView's own `initial_key` exists for.
GRAINS = (("minute", "By minute", "minutes"),
          ("hour", "By hour", "hours"),
          ("day", "By day", "days"),
          ("month", "By month", "months"))

#: The grain that is legible on a first look. Minute grain on a real
#: exhibit is tens of thousands of rows and month grain is a dozen;
#: neither answers "what did this machine do" at a glance.
DEFAULT_GRAIN = "day"


#: The words domain_loader.py uses for a carved record whose container the
#: carve could not resolve.
CARVED_TYPE_UNKNOWN = "Carved (type unknown)"

#: Shown when no recovery scan has run, so a zero in the Carved column is
#: not read as "nothing was deleted". main_window.py uses this constant.
CARVED_NOT_SCANNED_NOTE = (
    "“From deleted” is not yet meaningful — no recovery scan has run for "
    "this exhibit; run Evidence ▸ Recover deleted records to populate it")

#: Shown with the silence count: a gap in a cache is a gap in what was
#: cached.
SILENCE_CAVEAT = ("An empty period means no cached activity, not "
                  "necessarily no activity. Timeline places each record "
                  "once, by its key time; Findings ▸ Silences measures gaps "
                  "in every time this machine wrote to a record instead, so "
                  "the two counts differ.")

#: strftime format per grain: the keys get_timeline emits. Documents the
#: label shape; _period_start reads the same fixed-width shape by slicing.
_PERIOD_FORMAT = {"minute": "%Y-%m-%d %H:%M", "hour": "%Y-%m-%d %H:00",
                  "day": "%Y-%m-%d", "month": "%Y-%m"}


class TimelineInput:
    """Everything four calls to period_rows() need, computed once.

    __slots__ rather than a dict: one instance per exhibit, but it holds
    the admitted record list and the carved identity set, and a plain
    object states the shape the four grains all read.
    """
    __slots__ = ("records", "carved_ids", "live_total", "carved_total",
                 "undated_live", "undated_carved", "unplaced_live",
                 "unplaced_carved", "stubs", "offsets")

    def __init__(self, records, carved_ids, live_total, carved_total,
                 undated_live, undated_carved, unplaced_live=0,
                 unplaced_carved=0, stubs=0, offsets=None):
        # id(entry) -> the offset THAT record was observed at (only
        # records that show one; the rest take the recovered zone).
        self.offsets = offsets or {}
        # deleted-record stubs are recovered records with no URL and
        # no time; they are never on a timeline, and the note names them.
        self.stubs = stubs
        self.records = records
        self.carved_ids = carved_ids
        self.live_total = live_total
        self.carved_total = carved_total
        self.undated_live = undated_live
        self.undated_carved = undated_carved
        # NOT undated: an MSHist visit holding a real LOCAL time that no
        # recovered zone can place in UTC (engine/local_clock.py). Off the
        # timeline like an undated record, but counted -- and worded --
        # apart from one, because "carries no timestamp" would be false.
        self.unplaced_live = unplaced_live
        self.unplaced_carved = unplaced_carved


def _is_dated(entry):
    """The single admission predicate. Never modifies the entry.

    Decodes rather than testing for a non-zero raw value, because the
    bucketer decodes: filetime_to_dt returns None for anything outside the
    representable range. A stamp that cannot be decoded is not a usable
    timestamp, and its record is counted as undated.
    """
    raw, _basis = forensic_engine.key_timestamp(entry)
    if not raw:
        return False
    return filetime_to_dt(raw) is not None


def timeline_inputs(live_entries, carved_entries=(), stubs=0):
    """Admit every record that carries a usable timestamp, count the rest.

    `live_entries` is parser.all_entries, unmodified. `carved_entries` is
    the union domain_loader/indicator_loader take (engine.
    structured_records + engine.all_artifacts()); an empty sequence before
    a recovery scan has run, so every Carved cell is zero.

    Carved entries are de-duplicated by identity: the union can contain
    the same dict twice (a structured record also reachable as an
    artifact), and the sum of every row's Carved must equal carved_total.
    """
    live_total = 0
    records = []
    undated_live = unplaced_live = 0
    for entry in live_entries:
        live_total += 1
        if _is_dated(entry):
            records.append(entry)
        elif local_clock.is_unplaced(entry):
            unplaced_live += 1
        else:
            undated_live += 1

    carved_ids = set()
    undated_carved = unplaced_carved = 0
    # Identity first, then the dated check, so a duplicate is never counted
    # twice in the undated note. `seen_carved` is separate from `carved_ids`,
    # which holds only admitted carved records.
    seen_carved = set()
    for entry in carved_entries:
        if id(entry) in seen_carved:
            continue
        seen_carved.add(id(entry))
        if not _is_dated(entry):
            if local_clock.is_unplaced(entry):
                unplaced_carved += 1
            else:
                undated_carved += 1
            continue
        carved_ids.add(id(entry))
        records.append(entry)

    return TimelineInput(records, carved_ids, live_total, len(carved_ids),
                         undated_live, undated_carved, unplaced_live,
                         unplaced_carved, stubs,
                         _observed_offsets(live_entries))


def _observed_offsets(live_entries):
    """id(entry) -> the machine offset that record's own SPS id-24 pair
    shows, for a History record whose offset is one the exhibit kept (a
    mode; a lone outlier delta is never adopted). Local days are cut with
    this record by record: a zone with daylight saving has two offsets,
    and one global offset would file the minority season's late evenings
    on the wrong day."""
    observations = local_clock.zone_observations(live_entries)
    modes = {off for off, _n in local_clock.offset_modes(observations)}
    if len(modes) < 2:
        return {}
    out = {}
    for e in live_entries:
        offset = local_clock.observed_offset(e, modes)
        if offset is not None:
            out[id(e)] = offset
    return out


def dated_record_count(inputs):
    """What the nav badge counts.

    RECORDS, not table rows: the row count changes with the grain, and a
    badge that changes when you press a button is a badge that means
    nothing. Same predicate as the buckets, so badge and view cannot
    drift.
    """
    return len(inputs.records)


def period_rows(inputs, grain, offset_seconds=0, local=None):
    """One row per period that received a record.

    Calls get_timeline(grain, records) with an explicit record list; that
    path does not read self.entries and _entry_date is stateless, so no
    load_entries() call is needed.

    At most ten keys: the dict size steps at the eleventh, and the minute
    grain on a large exhibit produces tens of thousands of rows. `_record`
    is absent rather than None for that reason
    (detail_fields._merged_source reads it with .get()).
    """
    # LOCAL days are cut on UTC + each record's OWN offset (an MSHist
    # record's stamped one, a History record's observed one), falling back
    # to the recovered zone. `local` is explicit so a zone of UTC+00:00
    # (which still observes daylight saving) is not mistaken for UTC.
    if local is None:
        local = bool(offset_seconds)
    tz = (datetime.timezone(datetime.timedelta(seconds=offset_seconds or 0))
          if local else datetime.timezone.utc)
    offset_for = None
    if local:
        observed = inputs.offsets

        def offset_for(entry):
            stamped = entry.get(local_clock.TZ_OFFSET_KEY)
            if stamped is not None:
                return stamped
            return observed.get(id(entry))
    engine = forensic_engine.ForensicEngine()
    buckets = engine.get_timeline(grain, inputs.records,
                                  offset_seconds=offset_seconds or 0,
                                  offset_for=offset_for)
    peak = max((b["count"] for b in buckets), default=0) or 1

    rows = []
    previous = None
    for bucket in buckets:
        period = bucket["period"]
        entries = bucket["entries"]
        rows.append({
            "Period": period,
            "PeriodStart": _period_start(grain, period, tz),
            "Records": bucket["count"],
            "Share": round(bucket["count"] / peak, 4),
            "Carved": sum(1 for e in entries if id(e) in inputs.carved_ids),
            # ABSENCE_NOT_APPLICABLE on the first row, never 0 and never
            # blank: there is no previous period, so there is no silence
            # to measure, and a 0 would assert adjacency to nothing. The
            # mixed int/string in a kind="num" column is already handled
            # by record_filter._sort_key, with a precedent in
            # ContainersView's own Records column.
            "GapBefore": (ABSENCE_NOT_APPLICABLE if previous is None
                          else empty_buckets_between(grain, previous, period)),
            "Types": _types_cell(entries),
            "Domains": _domains_cell(entries),
            "_kind": K_PERIOD,
            # By reference. The total across every period is one pointer
            # per record, not a second copy of the set.
            "_members": entries,
        })
        previous = period
    return rows


def _types_cell(entries):
    """"History:12, Content:3" -- uncapped, commonest first.

    Uncapped on purpose: the number of distinct container types in one
    period is bounded by the database's own container catalogue, not by
    the record count, so there is nothing here to run away.
    """
    counter = Counter(e.get("ContainerType") or CARVED_TYPE_UNKNOWN
                      for e in entries)
    return ", ".join("%s:%d" % (name, count) for name, count
                     in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def _domains_cell(entries):
    """Every host in this period with its record count, busiest first
    (ties alphabetical)."""
    counter = Counter()
    for entry in entries:
        domain = forensic_engine.extract_domain(entry.get("Url") or "")
        if domain:
            counter[domain] += 1
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join("%s (%d)" % (host, count) for host, count in ranked)


def _period_start(grain, period, tz=datetime.timezone.utc):
    """The bucket's first instant, as an aware datetime.

    A separate column from Period, which is a string: a month bucket is
    "2024-06", which record_filter._parse_dt cannot read, so time
    operators work on this column instead.

    Parsed by slicing rather than datetime.strptime, which re-resolves the
    locale and recompiles its regex on every call and dominated the cost
    of building the grains for large exhibits. get_timeline builds
    `period` with the fixed-width, zero-padded formats in _PERIOD_FORMAT,
    so slicing is exact.
    """
    year = int(period[0:4])
    month = int(period[5:7])
    day = int(period[8:10]) if grain != "month" else 1
    hour = int(period[11:13]) if grain in ("hour", "minute") else 0
    minute = int(period[14:16]) if grain == "minute" else 0
    return datetime.datetime(year, month, day, hour, minute,
                             tzinfo=tz)


def empty_buckets_between(grain, previous_period, period):
    """How many buckets at `grain` hold nothing between these two.

    Exact integer arithmetic on the period labels themselves, so the
    number is in the same unit as the rows around it. The month branch is
    computed in absolute months ((y*12+m) difference) rather than by
    subtracting month numbers, which goes NEGATIVE across a year boundary
    and would read as a silence running backwards.
    """
    a = _period_start(grain, previous_period)
    b = _period_start(grain, period)
    if grain == "minute":
        return int((b - a).total_seconds()) // 60 - 1
    if grain == "hour":
        return int((b - a).total_seconds()) // 3600 - 1
    if grain == "month":
        return (b.year * 12 + b.month) - (a.year * 12 + a.month) - 1
    return (b - a).days - 1


def member_record_rows(entries, carved_ids=None):
    """One row per record in `entries`, shaped like History's rows so the
    same dialog, badges and carved styling apply. Carved-ness comes from
    `carved_ids` (identity) when the caller has it, else from the record
    itself (provenance.is_carved_entry)."""
    rows = []
    for entry in entries or ():
        raw_ts, basis = forensic_engine.key_timestamp(entry)
        carved = (id(entry) in carved_ids if carved_ids is not None
                  else provenance.is_carved_entry(entry))
        rows.append({
            "CleanUrl": entry.get("CleanUrl") or entry.get("Url") or "",
            "KeyTimeUtc": filetime_to_dt(raw_ts) if raw_ts else None,
            # WHICH COLUMN THE TIME CAME FROM: different claims about what
            # happened, which one UTC column would collapse.
            "KeyTimeBasis": basis,
            # SPS id 24, or an MSHist record's stored (LOCAL) ModifiedTime
            # -- engine/local_clock.py.
            "LocalTime": local_clock.local_naive(entry),
            "ContainerType": entry.get("ContainerType") or "",
            "ContainerId": entry.get("ContainerId"),
            "ContainerName": entry.get("ContainerName") or "",
            # Each counter under its own name, never merged.
            "VisitCount": entry.get("SPS_VisitCount"),
            "CacheTouches": entry.get("AccessCount"),
            "SearchTerms": entry.get("SearchTerms") or "",
            "IsInPrivate": bool(entry.get("IsInPrivate")),
            "Origin": CARVED_ORIGIN if carved else "Live record",
            "_kind": _kind_for(entry, carved),
            "_record": entry,
        })
    return rows


def record_rows(period_row, inputs):
    """One row per record inside one period, for TimelineView's pane."""
    return member_record_rows((period_row or {}).get("_members") or (),
                              inputs.carved_ids)


def _kind_for(entry, carved):
    """The kind of a carved record: K_CARVED_STRUCT when the carve
    reconstructed real columns, K_CARVED_STRING when only URL-shaped text
    survived; the two answer different questions (see record_kinds.py).
    Decided by record_kinds, so location_loader and this module give the
    same answer for the same artifact.
    """
    if not carved:
        return record_kinds.kind_for_entry(entry)
    return record_kinds.kind_for_carved(entry)


def grain_note(inputs, rows, grain, scan_run, clock_label="UTC"):
    """The count line MainWindow passes to set_records_for.

    Three obligations, in this order: what is on the timeline and what is
    not; the silences; and the caveat, restated AT the number rather than
    only in the nav rail. A caveat an examiner reads once on the way past
    is a caveat; a caveat beside the figure it qualifies is a reading.
    """
    dated = dated_record_count(inputs)
    unplaced = inputs.unplaced_live + inputs.unplaced_carved
    total = (inputs.live_total + inputs.carved_total + inputs.undated_carved
             + inputs.unplaced_carved)
    excluded = inputs.undated_live + inputs.undated_carved
    plural = _plural_for(grain)

    recovered = inputs.carved_total + inputs.undated_carved         + inputs.unplaced_carved
    split = ("%s live + %s recovered" % (_n(inputs.live_total),
                                         _n(recovered))
             if scan_run else "%s live" % _n(inputs.live_total))
    stub_text = record_counts.stub_clause(inputs.stubs) if scan_run else ""
    if stub_text:
        split += "; " + stub_text
    head = ("%s of %s records (%s) carry a usable timestamp"
            % (_n(dated), _n(total), split))
    if excluded or not unplaced:
        head += ("; %s carr%s none and %s not on this timeline"
                 % (_n(excluded), "ies" if excluded == 1 else "y",
                    "is" if excluded == 1 else "are"))
    if unplaced:
        # engine/local_clock.py: a time on a clock this tool cannot
        # convert is not "no timestamp", and saying so would be false.
        head += ("; %s carr%s a LOCAL time (MSHist) that cannot be placed "
                 "in UTC because no time zone was recovered, and %s not on "
                 "this timeline"
                 % (_n(unplaced), "ies" if unplaced == 1 else "y",
                    "is" if unplaced == 1 else "are"))
    parts = ["Periods are %s %s. %s" % (clock_label, plural, head)]

    if scan_run:
        parts[0] += " (of those on it, %s recovered)" % _n(inputs.carved_total)
    else:
        parts[0] += " — " + CARVED_NOT_SCANNED_NOTE

    gaps = [r["GapBefore"] for r in rows
            if isinstance(r["GapBefore"], int) and r["GapBefore"] > 0]
    if rows:
        parts.append(
            "%s %s hold records, with %s silence%s between them%s"
            % (_n(len(rows)), plural if len(rows) != 1 else plural[:-1],
               _n(len(gaps)), "" if len(gaps) == 1 else "s",
               ("; the longest is %s empty %s" % (_n(max(gaps)), plural))
               if gaps else ""))
    parts.append(SILENCE_CAVEAT)
    return ". ".join(parts)


def _plural_for(grain):
    for key, _label, plural in GRAINS:
        if key == grain:
            return plural
    return "periods"


def _n(value):
    return format(value, ",")
