"""Rows for the Domains view: one per host, from live records and, after
a recovery scan, recovered ones. A host can exist only in recovered data.

The aggregation is done here rather than with
forensic_engine.get_domain_analysis(), which returns first and last seen as
formatted strings; a time column needs datetimes for its filters.

Recovered candidates: every reconstructed record, and carved text only
where it begins with a clean scheme (http://, https://, file:///); see
counts_as_a_url.
"""
from ..engine import forensic_engine
from ..engine.ese_parser import filetime_to_dt
from ..engine.recovery_engine import STRUCTURED_METHOD
from .record_kinds import K_DOMAIN


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _inprivate(entry):
    """True, False, or None when it cannot be known.

    A live History record carries IsInPrivate (Flags bit 0x08). A carved
    structured record carries Flags but not IsInPrivate, so the bit is
    read here. A carved string has no Flags at all: None. The bit means
    InPrivate only on a History record, so it is read only there.
    """
    known = entry.get("IsInPrivate")
    if isinstance(known, bool):
        return known
    # A Flags key holding None is not an answer.
    return forensic_engine.carved_inprivate(entry)


def domain_rows(live_entries, carved_entries=()):
    """One row per domain.

    `live_entries` is parser.all_entries; `carved_entries` is the
    recovered records and artifacts (empty before a recovery scan).

    Each row is an aggregate: `_kind` is K_DOMAIN, `_record` is None, and
    `_members` references every entry counted, so "Records: N" can be
    opened. Rows hold thirteen keys; their number is bounded by the number
    of distinct hosts, not records.
    """
    domains = {}
    for entry in live_entries:
        _accumulate(domains, entry, carved=False)
    for entry in carved_entries:
        if not counts_as_a_url(entry):
            continue
        _accumulate(domains, entry, carved=True)

    rows = []
    for domain, d in domains.items():
        carved = d["carved"]
        # The count is the length of the member list, so the drill-down
        # pane always lists the same number of records.
        total = len(d["members"])
        rows.append({
            "Domain": domain,
            "Records": total,
            "Carved": carved,
            "OnlyCarved": bool(carved) and carved >= total,
            "FileSize": d["total_size"],
            "FirstSeen": d["first_seen"],
            "LastSeen": d["last_seen"],
            "ContainerType": ", ".join(sorted(d["container_types"])),
            "AccessCount": (round(sum(d["access_counts"]) / len(d["access_counts"]), 1)
                           if d["access_counts"] else 0),
            "IsInPrivate": d["has_inprivate"],
            "_kind": K_DOMAIN,
            "_record": None,
            "_members": d["members"],
        })
    rows.sort(key=lambda r: r["Records"], reverse=True)
    return rows


#: Carved text counts only where it is plainly a URL; a fragment with a
#: stray leading byte ("bhttp://...") does not.
_CLEAN_SCHEMES = ("http://", "https://", "file:///")


def counts_as_a_url(entry):
    """Whether a carved entry belongs in a Domains row.

    A reconstructed record always does; its stored URL, account prefix
    included, is read by extract_domain as a live one's is. Carved text
    needs a clean scheme (_CLEAN_SCHEMES) once the account prefix is
    removed."""
    if entry.get("RecoverySource") == STRUCTURED_METHOD:
        return True
    url = forensic_engine.clean_url(
        str(entry.get("Url") or entry.get("CleanUrl") or ""))
    return (url or "").lower().startswith(_CLEAN_SCHEMES)


def _accumulate(domains, entry, carved):
    url = entry.get("Url", "") or ""
    domain = forensic_engine.extract_domain(url)
    if not domain:
        return
    d = domains.setdefault(domain, {
        "carved": 0, "total_size": 0,
        "first_seen": None, "last_seen": None,
        "container_types": set(), "access_counts": [],
        "has_inprivate": False,
        # The entries counted into this domain, so its "Records: N" can
        # be opened.
        "members": [],
    })
    # domain_rows() adds live entries before carved ones, so the last
    # d["carved"] members are the carved ones; DomainsView relies on this.
    d["members"].append(entry)
    if carved:
        d["carved"] += 1
    d["total_size"] += _as_int(entry.get("FileSize"))
    # A carved record often has no container type; it is stated rather
    # than left blank.
    d["container_types"].add(entry.get("ContainerType") or "Carved (type unknown)")
    d["access_counts"].append(_as_int(entry.get("AccessCount")))
    # `is True`: None (unknown) must not count as an InPrivate visit.
    if _inprivate(entry) is True:
        d["has_inprivate"] = True

    raw_ts, _basis = forensic_engine.key_timestamp(entry)
    dt = filetime_to_dt(raw_ts) if raw_ts else None
    if dt:
        if d["first_seen"] is None or dt < d["first_seen"]:
            d["first_seen"] = dt
        if d["last_seen"] is None or dt > d["last_seen"]:
            d["last_seen"] = dt
