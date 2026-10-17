"""Rows for the Indicators view: one per distinct (kind, value) found in
URLs and paths.

engine/url_intel.py makes every finding and states its reason; this
module only reshapes the result. A recovered entry is scanned whenever it
has a Url, including file:// URLs and bare paths, which often name an
account or a volume.
"""
from ..engine import url_intel
from .record_kinds import K_INDICATOR

#: Confidence labels. An unexpected value reads "Not determinable" rather
#: than being mapped to one of the three.
_CONF_LABELS = {url_intel.HIGH: "High", url_intel.MEDIUM: "Medium",
                url_intel.LOW: "Low"}


def _confidence_label(raw):
    return _CONF_LABELS.get(raw, "Not determinable")


def indicator_rows(live_entries, carved_entries=()):
    """One row per distinct (kind, value) indicator.

    `live_entries` is parser.all_entries; `carved_entries` is the recovered
    records and artifacts (empty before a recovery scan).

    Each row is an aggregate, not a record: `_kind` is K_INDICATOR,
    `_record` is None, and `_records` references every record that carried
    the value. Rows hold ten keys, the most that fit the smaller dict size.
    """
    records = list(live_entries)
    records.extend(e for e in carved_entries if e.get("Url"))

    findings = url_intel.scan_records(records)
    tally = url_intel.summarise(findings)

    rows = []
    for kind, values in tally.items():
        for value, info in values.items():
            rows.append({
                "Kind": kind,
                "Value": value,
                "Decoded": info["decoded"],
                "Conf": _confidence_label(info["confidence"]),
                "Records": info["count"],
                "Why": info["reason"],
                "_kind": K_INDICATOR,
                "_record": None,
                "_records": info["records"],
                # The fields the value was read from, sorted.
                "Fields": ", ".join(sorted(info["fields"])),
            })
    rows.sort(key=lambda r: (r["Kind"], -r["Records"]))
    return rows
