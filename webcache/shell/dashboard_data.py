"""The numbers the Dashboard shows, computed from the evidence.

views/dashboard.py never imports the engine; this module stands between
it and forensic_engine.ForensicEngine / parser.get_database_info().

compute_dashboard_stats() reads only parser.all_entries, the live
database, so every number it returns at open is a live-only figure.

merge_recovered_into_stats() is called when a recovery scan completes
(main_window._on_recovery_loaded). It folds the full recovered set
(recovery_loader.deleted_records_rows, the list Deleted Records shows)
into Total Records, Container Types and Top Domains, so those figures and
the Container Types percentages stay consistent after a scan.

InPrivate and Cache Size are not extended by the merge: recovered rows
carry no FileSize or InPrivate flag (a string carve never had either),
and neither is estimated. Table and container counts describe the schema
and do not change with a carve.

A deleted-record stub is counted in Container Types (its ContainerType is
the catalogue's answer for its table, or
provenance.CONTAINER_NOT_DETERMINABLE), but has no URL: its CleanUrl is
provenance.ABSENCE_NOT_RECOVERED, so it is not passed to extract_domain()
and never counted in Top Domains (checked on `_kind == K_TOMBSTONE`).
"""
import datetime
import os
from collections import Counter

from ..engine import forensic_engine, local_clock
from ..engine.ese_parser import filetime_to_dt
from ..provenance import CONTAINER_NOT_DETERMINABLE
from . import domain_loader
from .record_kinds import K_TOMBSTONE


def compute_dashboard_stats(parser):
    """None when `parser` cannot support this -- no exhibit open yet, a
    failed load, or (in tests) a stand-in parser without a real ESE
    surface -- mirroring the hasattr guards main_window.py already
    applies for File Access/Cookies/Containers rather than raising.
    """
    if (parser is None or not hasattr(parser, "all_entries")
            or not hasattr(parser, "get_database_info")):
        return None
    engine = forensic_engine.ForensicEngine()
    engine.load_entries(list(parser.all_entries))
    engine.set_containers_meta(list(getattr(parser, "containers_meta", ()) or ()))
    stats = engine.get_statistics()
    db_info = parser.get_database_info()
    return {
        "total_records": stats["total_entries"],
        "table_count": db_info.get("table_count", 0),
        "container_count": db_info.get("container_count", 0),
        "inprivate_count": stats["inprivate_count"],
        "total_file_size": stats["total_file_size"],
        "container_types": Counter(stats["container_types"]),
        "top_domains": Counter(stats["top_domains"]),
        "db_path": db_info.get("path") or "",
        "db_file_size": db_info.get("file_size", 0),
        # 0 until a recovery scan runs (see merge_recovered_into_stats);
        # always present, so callers need no guard.
        "recovered_count": 0,
        # 0 recovered because none were found is not 0 because no scan
        # ran; the headline says which.
        "recovery_run": False,
    }


def merge_recovered_into_stats(stats, recovered_rows):
    """Returns a new dict and never modifies `stats`. The caller
    (main_window._on_recovery_loaded) always merges into the original
    live stats built at open, never a previously merged result.
    """
    if stats is None:
        return None
    merged = dict(stats)
    merged["total_records"] = stats["total_records"] + len(recovered_rows)
    merged["recovered_count"] = len(recovered_rows)
    merged["recovery_run"] = True
    container_types = Counter(stats["container_types"])
    top_domains = Counter(stats["top_domains"])
    # the recovered share of each domain, so the card can
    # say Live / Mixed / Recovered only as the Domains view does.
    recovered_domains = Counter()
    for row in recovered_rows:
        container_types[row.get("ContainerType") or CONTAINER_NOT_DETERMINABLE] += 1
        # A stub's ContainerType is counted (its table is where the
        # deleted row lived), but its CleanUrl is an absence token, not a
        # URL, so it is not passed to extract_domain. Checked on `_kind`,
        # never on the token's wording.
        if row.get("_kind") == K_TOMBSTONE:
            continue
        # The Domains view's rule, so one label never carries two
        # numbers: a carved fragment ("bhttp://...") is not counted.
        record = row.get("_record")
        source = record if isinstance(record, dict) else row
        if not domain_loader.counts_as_a_url(source):
            continue
        # The stored URL, as the Domains view reads it: the cleaned form
        # of a launcher address unwraps to its target, which would name a
        # host the Domains view has no row for.
        domain = forensic_engine.extract_domain(
            source.get("Url") or row.get("CleanUrl") or "")
        if domain:
            top_domains[domain] += 1
            recovered_domains[domain] += 1
    merged["container_types"] = container_types
    merged["top_domains"] = top_domains
    merged["top_domains_recovered"] = recovered_domains
    return merged


def _stamp(dt):
    from ..widgets.time_format import format_dt
    return format_dt(dt)


def _record_offset(entry, zone_offset, modes=()):
    """The offset that turns this record's UTC instant back into its local
    wall clock, the one the Timeline cuts its day with: an MSHist record's
    stamped offset, a History record's observed SPS id-24 offset when it
    is a clock the exhibit kept, else the recovered zone
    (local_clock.record_offset)."""
    return local_clock.record_offset(entry, zone_offset, modes)


def _extremes(records):
    """(earliest, latest) as (utc datetime, entry), or (None, None)."""
    earliest = latest = None
    for entry in records:
        raw, _basis = forensic_engine.key_timestamp(entry)
        dt = filetime_to_dt(raw) if raw else None
        if dt is None:
            continue
        if earliest is None or dt < earliest[0]:
            earliest = (dt, entry)
        if latest is None or dt > latest[0]:
            latest = (dt, entry)
    return earliest, latest


def _utc_text(earliest, latest):
    return "%s – %s" % (_stamp(earliest[0]), _stamp(latest[0]))


def case_summary(parser, recovery_rows=None, recovery_state=None):
    """(label, value) rows for the Dashboard's Case summary card:
    what an examiner wants first. The activity range runs over every dated
    record, live AND recovered once a scan has run (the "Activity covers"
    row says which), on the same key timestamp the Timeline and the exports
    use. When recovery widens the range the live-only range is shown too.
    Each end of the local range is shifted by the offset that record's own
    UTC was derived with, and names it; a single label is used only when
    both ends share one. `recovery_rows` is None until a scan has run;
    `recovery_state` "running" says a scan is in flight,
    so the card never says "Not run" while one runs."""
    info = (parser.get_database_info()
            if hasattr(parser, "get_database_info") else {}) or {}
    live_records = list(getattr(parser, "all_entries", None) or ())
    recovered = [r.get("_record") or {} for r in (recovery_rows or ())]
    offset = getattr(parser, "derived_tz_offset_seconds", None)
    modes = {off for off, _n in local_clock.offset_modes(
        local_clock.zone_observations(live_records))}
    earliest, latest = _extremes(live_records + recovered)
    live_only = None
    if earliest is not None:
        utc_range = _utc_text(earliest, latest)
        ends = [(dt, _record_offset(entry, offset, modes)) for dt, entry in
                (earliest, latest)]
        if all(o is None for _d, o in ends):
            local_label, local_range = ("Activity (local)",
                                        "No time zone was recovered")
        elif ends[0][1] == ends[1][1]:
            local_label = "Activity (local, %s)" % local_clock.zone_label(
                ends[0][1])
            local_range = " – ".join(
                _stamp(dt + datetime.timedelta(seconds=o)) for dt, o in ends)
        else:
            local_label = "Activity (local)"
            local_range = " – ".join(
                "%s (%s)" % (_stamp(dt + datetime.timedelta(seconds=o)),
                             local_clock.zone_label(o))
                if o is not None else "no time zone" for dt, o in ends)
        if recovery_rows is not None:
            e2, l2 = _extremes(live_records)
            if e2 is not None and _utc_text(e2, l2) != utc_range:
                live_only = _utc_text(e2, l2)
    else:
        utc_range = "No record carries a usable timestamp"
        local_label, local_range = "Activity (local)", utc_range
    if recovery_rows is None and recovery_state == "running":
        recovery = "Running — recovered records are added when it finishes"
        covers = "Live records only (recovery running)"
    elif recovery_rows is None:
        recovery = "Not run"
        covers = "Live records only (recovery not run)"
    else:
        n = len(recovery_rows)
        recovery = "Ran — %s recovered record%s" % (
            format(n, ","), "" if n == 1 else "s")
        covers = "Live and recovered records"
    rows = [
        ("File", os.path.basename(info.get("path") or "")),
        ("Size", info.get("file_size", 0)),
        ("Activity (UTC)", utc_range),
        (local_label, local_range),
        ("Activity covers", covers),
    ]
    if live_only is not None:
        rows.append(("Activity (live only, UTC)", live_only))
    return rows + [
        ("Recovered time zone", info.get("derived_tz")
         or "Could not be derived (fewer than 5 SPS/ModifiedTime pairs)"),
        ("Database state", info.get("db_state_text") or "Unknown"),
        ("SHA-256", info.get("sha256") or "(not computed)"),
        ("Recovery", recovery),
    ]


def database_info_rows(stats):
    """(label, value) pairs for the Database Info card -- File/Size/
    Tables/Containers. Values are left as raw
    ints/strings; formatting (Size -> "12.3 MB", thousands separators) is
    views/dashboard.py's job, the same split every other view keeps
    between shaping (shell) and presentation (view)."""
    if stats is None:
        return []
    return [
        ("File", os.path.basename(stats["db_path"])),
        ("Size", stats["db_file_size"]),
        ("Tables", stats["table_count"]),
        ("Containers", stats["container_count"]),
    ]


def apportioned_percentages(counts):
    """Integer percentages for `counts`, in the order given, that sum to
    exactly 100 whenever the counts sum to more than zero (the
    largest-remainder method).

    Rounding each share independently can total 101 or 99 (546/46/10/8 of
    610 rounds to 90/8/2/1). Instead every share gets its floor, and the
    leftover points go one each to the largest fractional remainders.
    Ties keep the input order, because sorted() is stable.
    """
    total = sum(counts)
    if total <= 0:
        return [0] * len(counts)
    shares = [c * 100.0 / total for c in counts]
    floors = [int(s) for s in shares]
    remainder = 100 - sum(floors)
    order = sorted(range(len(counts)), key=lambda i: shares[i] - floors[i],
                   reverse=True)
    result = list(floors)
    for i in order[:remainder]:
        result[i] += 1
    return result


def format_size(num_bytes):
    """B / KB / MB / GB, the formula forensic_engine's reports use
    (ForensicEngine._format_size), so the Dashboard and an exported report
    show the same figure for the same bytes."""
    try:
        size = int(num_bytes or 0)
    except (TypeError, ValueError):
        size = 0
    if size < 1024:
        return "%d B" % size
    if size < 1024 * 1024:
        return "%.1f KB" % (size / 1024)
    if size < 1024 * 1024 * 1024:
        return "%.1f MB" % (size / (1024 * 1024))
    return "%.2f GB" % (size / (1024 * 1024 * 1024))
