"""The row sets derived from an open exhibit, computed once.

Several views, sidebar badges and the dashboard read the same derived sets
(the carved union, Deleted Records' rows, the merged Domains and Indicators
rows, the Findings segments). Each is computed once per exhibit, or per
recovery scan, and cached on the object it is derived from: live sets on
the parser, recovery sets on the recovery engine.

The worker threads that parse the exhibit and run the recovery scan fill
the cache before they report (precompute_live / precompute_recovery), so
the GUI thread only fills grids. A set not yet cached is computed when it
is first asked for, so every caller gets the same result either way.

A cache entry is valid only for the live entry list it was computed from
(identity and length), so a parser whose entries are replaced is
recomputed rather than read stale.
"""
import logging

_LOG = logging.getLogger(__name__)
_ATTR = "_wc_derived"


def _token(parser):
    entries = getattr(parser, "all_entries", None)
    return (id(entries), len(entries) if entries is not None else -1)


def _cache(owner, parser):
    """The cache dict on `owner`, emptied if `parser`'s entries changed."""
    token = _token(parser)
    cache = getattr(owner, _ATTR, None)
    if cache is None or cache.get("__token__") != token:
        cache = {"__token__": token}
        try:
            setattr(owner, _ATTR, cache)
        except (AttributeError, TypeError):
            # An owner that refuses attributes is simply not cached.
            pass
    return cache


def get(owner, parser, name, compute):
    """`compute()`'s result for `name`, cached on `owner`."""
    cache = _cache(owner, parser)
    if name not in cache:
        cache[name] = compute()
    return cache[name]


# --- the sets ---------------------------------------------------------------

def carved_entries(parser, engine):
    """engine.structured_records + engine.all_artifacts(): the carved set
    Domains, Indicators, Timeline, Location and Findings all read."""
    return get(engine, parser, "carved_entries",
               lambda: (list(engine.structured_records)
                        + list(engine.all_artifacts())))


def deleted_records(parser, engine):
    from .recovery_loader import deleted_records_rows
    return get(engine, parser, "deleted_records",
               lambda: deleted_records_rows(engine))


def carved_history(parser, engine):
    from .recovery_loader import carved_history_rows
    return get(engine, parser, "carved_history",
               lambda: carved_history_rows(engine))


def carved_file_access(parser, engine):
    from .recovery_loader import carved_file_access_rows
    return get(engine, parser, "carved_file_access",
               lambda: carved_file_access_rows(engine))


def carved_downloads(parser, engine):
    from .recovery_loader import carved_downloads_rows
    return get(engine, parser, "carved_downloads",
               lambda: carved_downloads_rows(engine))


def carved_headers(parser, engine):
    from .headers_loader import carved_header_rows
    return get(engine, parser, "carved_headers",
               lambda: carved_header_rows(engine))


def file_text_only(parser, engine):
    from .recovery_loader import file_text_only_count
    return get(engine, parser, "file_text_only",
               lambda: file_text_only_count(engine))


def domains(parser, engine=None):
    """Domains rows: live only before a scan, live and carved after."""
    from .domain_loader import domain_rows
    if engine is None:
        return get(parser, parser, "domains_live",
                   lambda: domain_rows(parser.all_entries))
    return get(engine, parser, "domains_merged",
               lambda: domain_rows(parser.all_entries,
                                   carved_entries(parser, engine)))


def indicators(parser, engine=None):
    """Indicators rows: live only before a scan, live and carved after."""
    from .indicator_loader import indicator_rows
    if engine is None:
        return get(parser, parser, "indicators_live",
                   lambda: indicator_rows(parser.all_entries))
    return get(engine, parser, "indicators_merged",
               lambda: indicator_rows(parser.all_entries,
                                      carved_entries(parser, engine)))


def finding(parser, engine, name, terms=()):
    """One Findings segment's rows (time_voids: (rows, note)). `terms`
    applies to ioc_hits only."""
    from . import iocs_loader as L
    live = parser.all_entries
    carved = carved_entries(parser, engine) if engine is not None else ()
    owner = engine if engine is not None else parser
    if name == "beaconing":
        return get(parser, parser, "f_beaconing",
                   lambda: L.beaconing_rows(live))
    compute = {
        "ioc_hits": lambda: L.ioc_hit_rows(live, carved, list(terms)),
        "entryid_gaps": lambda: L.entryid_gap_rows(live, carved),
        "time_voids": lambda: L.time_void_rows_and_note(live, carved),
        "deceptive_hostnames": lambda: L.deceptive_hostname_rows(live, carved),
        "redirect_chains": lambda: L.redirect_hop_rows(live, carved),
    }[name]
    key = "f_%s_%s" % (name, "|".join(terms)) if name == "ioc_hits" else "f_" + name
    return get(owner, parser, key, compute)


def timeline_inputs(parser, engine=None):
    """timeline_loader.timeline_inputs over the live entries, and the
    carved set and stub count once a scan has run."""
    from . import timeline_loader
    if engine is None:
        return get(parser, parser, "timeline_live",
                   lambda: timeline_loader.timeline_inputs(parser.all_entries))
    return get(engine, parser, "timeline_merged",
               lambda: timeline_loader.timeline_inputs(
                   parser.all_entries, carved_entries(parser, engine),
                   stubs=len(getattr(engine, "tombstones", None) or ())))


def location(parser, engine, grouping):
    """(position fixes, places) at `grouping`, live or merged."""
    from . import location_loader

    def compute():
        carved = carved_entries(parser, engine) if engine is not None else ()
        fixes = location_loader.position_fixes(
            parser.all_entries, carved, grouping=grouping)
        return fixes, location_loader.places(fixes, grouping=grouping)
    return get(engine if engine is not None else parser, parser,
               "location_" + grouping, compute)


def file_access_rows(parser):
    from .evidence_loader import file_access_rows_from_parser
    return get(parser, parser, "file_access_live",
               lambda: file_access_rows_from_parser(parser))


def download_rows(parser):
    from .evidence_loader import downloads_rows_from_parser
    return get(parser, parser, "downloads_live",
               lambda: downloads_rows_from_parser(parser))


def header_rows(parser):
    from .headers_loader import header_rows_from_parser
    return get(parser, parser, "headers_live",
               lambda: header_rows_from_parser(parser))


def dashboard_live(parser):
    from . import dashboard_data
    return get(parser, parser, "dashboard_live",
               lambda: dashboard_data.compute_dashboard_stats(parser))


def report_statistics(parser):
    """ForensicEngine.get_statistics() over the live entries, or None when
    the statistics pass fails on a damaged exhibit."""
    def compute():
        from ..engine import forensic_engine
        try:
            engine = forensic_engine.ForensicEngine()
            engine.load_entries(list(parser.all_entries))
            return engine.get_statistics()
        except Exception:                              # noqa: BLE001
            return None
    return get(parser, parser, "report_statistics", compute)


def dashboard_merged(parser, engine):
    """The dashboard's figures with the recovered set merged in."""
    from . import dashboard_data
    return get(engine, parser, "dashboard_merged",
               lambda: dashboard_data.merge_recovered_into_stats(
                   dashboard_live(parser), deleted_records(parser, engine)))


def case_summary(parser, engine, recovery_state):
    """The dashboard's Case summary rows (engine None before a scan)."""
    from . import dashboard_data
    rows = deleted_records(parser, engine) if engine is not None else None
    return get(engine if engine is not None else parser, parser,
               "case_summary_" + str(recovery_state),
               lambda: dashboard_data.case_summary(
                   parser, rows, recovery_state=recovery_state))


def clock_offsets(parser, engine):
    """offset_periods for the live records, then for the recovered ones."""
    from ..engine import local_clock

    def compute():
        live = local_clock.offset_periods(
            getattr(parser, "zone_observations", None) or [], "live")
        recovered = local_clock.offset_periods(
            local_clock.zone_observations(carved_entries(parser, engine)),
            "recovered")
        return live + recovered
    return get(engine, parser, "clock_offsets", compute)


def _default_grouping():
    from .location_loader import DEFAULT_GROUPING
    return DEFAULT_GROUPING


_FINDINGS = ("ioc_hits", "entryid_gaps", "time_voids", "beaconing",
             "deceptive_hostnames", "redirect_chains")


# --- pre-computation on a worker thread --------------------------------------

def _run(steps, stopping, progress=None):
    for label, step in steps:
        if stopping():
            return
        if progress is not None:
            progress(label)
        try:
            step()
        except Exception as exc:  # pragma: no cover - computed again on use
            _LOG.warning("Pre-computing a derived set failed: %s", exc)


def precompute_live(parser, stopping=lambda: False, progress=None):
    """Fill the live sets, on the parsing worker after a parse.
    `progress(label)` is called before each step."""
    if not hasattr(parser, "all_entries"):
        return
    _run([("File Access", lambda: file_access_rows(parser)),
          ("Downloads", lambda: download_rows(parser)),
          ("HTTP Headers", lambda: header_rows(parser)),
          ("Dashboard", lambda: dashboard_live(parser)),
          ("report statistics", lambda: report_statistics(parser)),
          ("Domains", lambda: domains(parser)),
          ("Indicators", lambda: indicators(parser)),
          ("Timeline", lambda: timeline_inputs(parser)),
          ("Location", lambda: location(parser, None, _default_grouping()))]
         + [("Findings", lambda n=n: finding(parser, None, n))
            for n in _FINDINGS],
         stopping, progress)


def precompute_recovery(parser, engine, stopping=lambda: False,
                        progress=None):
    """Fill the recovery sets, on the recovery worker after a scan.
    `progress(label)` is called before each step."""
    if parser is None or not hasattr(parser, "all_entries"):
        return
    _run([("recovered records", lambda: carved_entries(parser, engine)),
          ("Deleted Records", lambda: deleted_records(parser, engine)),
          ("History", lambda: carved_history(parser, engine)),
          ("File Access", lambda: carved_file_access(parser, engine)),
          ("Downloads", lambda: carved_downloads(parser, engine)),
          ("HTTP Headers", lambda: carved_headers(parser, engine)),
          ("File Access", lambda: file_text_only(parser, engine)),
          ("Domains", lambda: domains(parser, engine)),
          ("Indicators", lambda: indicators(parser, engine)),
          ("Timeline", lambda: timeline_inputs(parser, engine)),
          ("Location", lambda: location(parser, engine, _default_grouping())),
          ("Dashboard", lambda: dashboard_merged(parser, engine)),
          ("Dashboard", lambda: case_summary(parser, engine, "done")),
          ("Integrity", lambda: clock_offsets(parser, engine))]
         + [("Findings", lambda n=n: finding(parser, engine, n))
            for n in _FINDINGS],
         stopping, progress)
