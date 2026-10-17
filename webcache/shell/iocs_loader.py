"""Rows for the Findings view (nav key "iocs"): six forensic_engine and
analysis_extra analyses, reshaped into the row sets the view switches
between. The engine makes every finding and states why; this module only
calls it and reshapes the result.

Six segments, six engine calls, never summed into one count (see
main_window._NO_COUNT_KEYS). Each function answers one question:

  ioc_hit_rows            forensic_engine.ForensicEngine.match_iocs: a
                          watchlist term or a built-in rule (an
                          elevated-abuse-registry TLD, a .onion address).
  entryid_gap_rows        .analyze_entryid_gaps: a hole in a container's
                          EntryId sequence.
  time_void_rows          .analyze_time_voids: a period with no recorded
                          activity.
  beaconing_rows          .detect_beaconing: a domain contacted at
                          low-jitter regular intervals.
  deceptive_hostname_rows analysis_extra.homograph_findings: a punycode,
                          non-ASCII or mixed-script hostname.
  redirect_hop_rows       analysis_extra.redirect_chains: a reconstructed
                          navigation/redirect chain, one row per hop
                          (count noun "hops").

CARVED RECORDS. Every function except beaconing_rows takes
`carved_entries` and passes it to the engine's `extra_entries`, because the
engine itself is loaded with live entries only. Before a recovery scan the
default `()` is the correct input, and the view's note states that no scan
has run.

beaconing_rows has no `carved_entries`: detect_beaconing() takes no extra
entries (see record_kinds.K_BEACON), and the view says so.

`_engine_for` builds a ForensicEngine per call; load_entries() stores the
list by reference, so this costs nothing.
"""
import re
from collections import defaultdict
from urllib.parse import urlparse

from .. import provenance
from ..engine import forensic_engine
from ..engine.analysis_extra import homograph_findings, redirect_chains
from ..engine.ese_parser import filetime_to_dt
from . import location_loader
from .record_kinds import (K_BEACON, K_DECEPTIVE_HOST, K_ENTRYID_GAP,
                           K_REDIRECT_HOP, K_TIME_VOID, kind_for_carved,
                           kind_for_entry)

#: How long a silence has to run before analyze_time_voids reports it.
_MIN_VOID_HOURS = 24.0


def _engine_for(live_entries):
    engine = forensic_engine.ForensicEngine()
    engine.load_entries(list(live_entries))
    return engine


def _host_of(entry):
    """The host of an entry's URL (CleanUrl or Url, netloc, lowercased),
    read the way analysis_extra.homograph_findings reads it, so entries are
    grouped by the same host the finding names. Never raises: a URL that
    does not parse contributes no host."""
    url = entry.get("CleanUrl") or entry.get("Url") or ""
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def split_watchlist(raw_text):
    """Free text (the Findings watchlist box, comma- or newline-
    separated) into a list of terms -- `re.split(r"[,\\n]", raw)`. Blank entries are dropped here; anything
    else (a leading "#" comment, case) is forensic_engine.match_iocs's
    own business, not this shell's."""
    return [t.strip() for t in re.split(r"[,\n]", raw_text or "") if t.strip()]


# --- ioc_hit_rows -----------------------------------------------------

def ioc_hit_rows(live_entries, carved_entries=(), terms=()):
    """One row per record match_iocs flagged: a watchlist term, or a
    built-in rule (elevated-abuse-registry TLD, .onion). Each row is the
    matching record itself: `_record` is the entry, by reference, and
    `_kind` comes from kind_for_entry/kind_for_carved, so opening it shows
    the record.
    """
    engine = _engine_for(live_entries)
    hits = engine.match_iocs(list(terms), extra_entries=list(carved_entries))
    rows = []
    for h in hits:
        entry = h["entry"]
        carved = bool(h["carved"])
        raw_ts, _basis = forensic_engine.key_timestamp(entry)
        rows.append({
            "Reasons": ", ".join(h["reasons"]),
            # The engine's sentence for why the rule fired (IOC_RULE_BASIS
            # covers every rule, the watchlist included); the engine's
            # reasons are the fallback for a rule without one.
            "Why": "; ".join(h.get("basis", [])) or ", ".join(h["reasons"]),
            "Source": "carved" if carved else "live",
            # Every row states its Origin. Without it origin_cell fell
            # through to "Live record" for a carved hit, and its export
            # said so beside the hit's own carve method.
            "Origin": provenance.CARVED_ORIGIN if carved
                      else provenance.LIVE_ORIGIN,
            "CleanUrl": entry.get("CleanUrl") or entry.get("Url") or "",
            "AccessedUtc": filetime_to_dt(raw_ts) if raw_ts else None,
            "_record": entry,
            "_kind": kind_for_carved(entry) if carved else kind_for_entry(entry),
        })
    return rows


# --- entryid_gap_rows ---------------------------------------------------

def entryid_gap_rows(live_entries, carved_entries=()):
    """One row per container analyze_entryid_gaps reports a hole for.
    Not a record (record_kinds.K_ENTRYID_GAP). `_records` references the
    live entries the exhibit holds for that container, the ones the "Live"
    column counts, so that count can be opened.
    """
    engine = _engine_for(live_entries)
    gaps = engine.analyze_entryid_gaps(extra_entries=list(carved_entries))
    by_container = defaultdict(list)
    for entry in live_entries:
        cid = entry.get("ContainerId")
        if cid is not None:
            by_container[cid].append(entry)
    rows = []
    for g in gaps:
        # The live records AND the recovered ones inside the hole, so the
        # row's origin derives from what it really holds.
        members = list(by_container.get(g["ContainerId"], []))
        first, last = g.get("FirstEntryId"), g.get("LastEntryId")
        live_ids = {e.get("EntryId") for e in members}
        for art in carved_entries:
            if art.get("ContainerId") != g["ContainerId"]:
                continue
            try:
                eid = int(art.get("EntryId"))
            except (TypeError, ValueError):
                continue
            if (first is not None and first <= eid <= last
                    and eid not in live_ids):
                members.append(art)
        rows.append({
            "ContainerId": g["ContainerId"],
            "ContainerName": g.get("ContainerName", ""),
            "Live": g["LiveRecords"],
            "Missing": g["MissingRecords"],
            "Recovered": g["RecoveredEntryIds"],
            "GapRuns": g["GapRuns"],
            # THE ENGINE'S OWN WORDS -- never re-phrased at this layer.
            "Interpretation": g["Interpretation"],
            "_record": None,
            "_kind": K_ENTRYID_GAP,
            "_records": members,
        })
    return rows


# --- time_void_rows -------------------------------------------------------

def time_void_rows(live_entries, carved_entries=()):
    """One row per silence analyze_time_voids reports. NEITHER A RECORD
    NOR AN AGGREGATE -- see record_kinds.K_TIME_VOID: there is no
    population of records to point at, only their absence."""
    return time_void_rows_and_note(live_entries, carved_entries)[0]


def time_void_rows_and_note(live_entries, carved_entries=()):
    """(rows, exclusion sentence). The sentence is "" unless some MSHist
    visit holds a LOCAL time with no recovered zone: such a visit cannot
    be placed in UTC, and analyze_time_voids withholds every silence it
    could fall inside. Withholding without saying so would be a silent
    change to a finding, so the count line states both numbers."""
    engine = _engine_for(live_entries)
    report = {}
    voids = engine.analyze_time_voids(_MIN_VOID_HOURS, list(carved_entries),
                                      report=report)
    rows = [{
        "From": v["From"],
        "To": v["To"],
        # The same span in days and hours: an exact figure of 19,271.3
        # hours made the examiner divide to see two years.
        "Length": location_loader.duration_text(
            int(round(float(v["GapHours"]) * 3600))),
        "GapHours": v["GapHours"],
        "_record": None,
        "_kind": K_TIME_VOID,
    } for v in voids]
    unplaced = report.get("unplaced_records", 0)
    note = ""
    if unplaced:
        withheld = report.get("withheld_voids", 0)
        note = ("%s MSHist visit%s hold%s a LOCAL time that cannot be placed "
                "in UTC because no time zone was recovered; %s silence%s that "
                "could contain %s %s withheld, not reported."
                % ("{:,}".format(unplaced), "" if unplaced == 1 else "s",
                   "s" if unplaced == 1 else "",
                   "{:,}".format(withheld), "" if withheld == 1 else "s",
                   "it" if unplaced == 1 else "them",
                   "is" if withheld == 1 else "are"))
    return rows, note


# --- beaconing_rows -------------------------------------------------------

def beaconing_rows(live_entries):
    """One row per domain detect_beaconing flags as low-jitter/periodic.
    Not a record (record_kinds.K_BEACON). No `carved_entries`: the engine
    call does not take them."""
    engine = _engine_for(live_entries)
    beacons = engine.detect_beaconing()
    by_domain = defaultdict(list)
    for entry in live_entries:
        dom = forensic_engine.extract_domain(entry.get("Url") or "")
        if dom:
            by_domain[dom].append(entry)
    rows = []
    for b in beacons:
        rows.append({
            "Domain": b["Domain"],
            "Events": b["Events"],
            "MeanIntervalSec": b["MeanIntervalSec"],
            "IntervalCV": b["IntervalCV"],
            "FirstSeen": b["FirstSeen"],
            "LastSeen": b["LastSeen"],
            "_record": None,
            "_kind": K_BEACON,
            "_records": by_domain.get(b["Domain"], []),
        })
    return rows


# --- deceptive_hostname_rows ----------------------------------------------

def deceptive_hostname_rows(live_entries, carved_entries=()):
    """One row per hostname analysis_extra.homograph_findings flags:
    punycode, non-ASCII or mixed-script. Not a record (record_kinds.
    K_DECEPTIVE_HOST). Carved candidates are scanned as in
    domain_loader.domain_rows: any candidate with a URL."""
    pool = list(live_entries) + [e for e in carved_entries if e.get("Url")]
    findings = homograph_findings(pool)
    by_host = defaultdict(list)
    for entry in pool:
        host = _host_of(entry)
        if host:
            by_host[host].append(entry)
    rows = []
    for f in findings:
        rows.append({
            "Host": f["host"],
            "Decoded": f["decoded"],
            "Skeleton": f["skeleton"],
            "Records": f["records"],
            # THE ENGINE'S OWN WORDS. analyze_hostname built one sentence
            # per indicator it found; joined, never re-phrased.
            "Why": "; ".join(f["findings"]),
            # The engine's assessment, phrased as a question to weigh
            # ("Compare against the domain it resembles before drawing any
            # conclusion"), never a verdict.
            "Assessment": f["assessment"],
            "_record": None,
            "_kind": K_DECEPTIVE_HOST,
            "_records": by_host.get(f["host"], []),
        })
    return rows


# --- redirect_hop_rows -----------------------------------------------------

def redirect_hop_rows(live_entries, carved_entries=()):
    """One row per hop of every redirect chain analysis_extra.
    redirect_chains reconstructs (count noun "hops"), so each hop keeps
    its own recorded source (a RedirectUrl column or an HTTP 3xx Location
    header). Not a record, even for a hop that matches a row of this
    exhibit (record_kinds.K_REDIRECT_HOP)."""
    pool = list(live_entries) + [
        e for e in carved_entries if e.get("Url") or e.get("CleanUrl")]
    chains = redirect_chains(pool)
    rows = []
    for chain_index, chain in enumerate(chains, 1):
        for step, hop in enumerate(chain["hops"], 1):
            rows.append({
                "Chain": chain_index,
                "Step": step,
                "Url": hop["url"],
                "Source": hop["source"],
                "InDb": "yes" if hop["in_db"] else "no",
                "_record": None,
                "_kind": K_REDIRECT_HOP,
            })
    return rows
