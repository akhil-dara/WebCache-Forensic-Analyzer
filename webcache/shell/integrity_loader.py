"""Rows for the Integrity view.

WebCacheParser.get_database_info() supplies the facts: source hashes,
database state, parse statistics, the decision log and the derived time
zone. This module adds each hashed file's role (the database, the current
or a rolled transaction log, the checkpoint, reserved log space), decided
by ESE filename convention, as evidence_scope() decides what is hashed.

The read-only guarantee row states what WebCacheParser.open() does (mode
"rb", no ESE soft recovery), and its tooltip is evidence_model's "Source
handling" scope statement, the same sentence every export carries.
"""
import os

from ..engine.ese_parser import header_time_rows
from ..engine.evidence_model import SCOPE_STATEMENTS

#: The read-only guarantee: mode 'rb', and no ESE soft recovery.
READ_ONLY_GUARANTEE = (
    "Opened 'rb' (read-only); no ESE soft recovery (esentutl /r) was performed.")

#: The statement every export carries, used as the tooltip.
_SOURCE_HANDLING_TEXT = next(
    text for heading, text in SCOPE_STATEMENTS if heading == "Source handling")

#: decision_log lines that are flagged: skipped tables, tables registered
#: in Containers but absent, and records that failed to parse.
_FLAG_PHRASES = ("SKIPPED", "failed to parse", "table absent")
#: Recovery decisions that narrow what the recovered set can hold: logs a
#: collection did not include, and files left out at open.
_RECOVERY_FLAG_PHRASES = ("No V01*.log", "Not chosen at open")
#: How a recovery decision is told apart from a parsing one, in one list.
RECOVERY_PREFIX = "Recovery: "


def _role_for(filename, db_basename):
    """One file's role in the evidence scope, matched by name.
    `db_basename` is the database file's basename."""
    if filename == db_basename:
        return "Database file — the exhibit itself"
    fl = filename.lower()
    if fl.endswith(".log"):
        if fl == "v01.log":
            return "Transaction log (current) — read by the recovery carve"
        return "Transaction log (rolled) — read by the recovery carve"
    if fl.endswith(".chk"):
        return "Checkpoint file — read by the recovery carve to bound replay"
    if fl.endswith(".jrs"):
        return ("Reserved log file — hashed for completeness; not parsed "
                "by the recovery carve")
    if fl.endswith(".jfm"):
        return ("Flush-map file — hashed for completeness; not parsed by "
                "the recovery carve")
    return "Sibling file read alongside the database"


def hash_rows(info):
    """One row per file hashed on open, with its role and SHA-256.

    `info` is WebCacheParser.get_database_info(). The database file comes
    first, then the others alphabetically.
    """
    db_basename = os.path.basename(info.get("path") or "")
    rows = [
        {"File": filename, "Role": _role_for(filename, db_basename),
         "SHA256": sha256}
        for filename, sha256 in info.get("source_hashes", {}).items()
    ]
    rows.sort(key=lambda r: (r["File"] != db_basename, r["File"].lower()))
    return rows


def source_integrity_rows(info):
    """The Source Integrity card's fields, in a fixed order, each a
    dict with "label", "value" and "tooltip" ("" except on the read-only
    guarantee row).
    """
    stats = info.get("parse_stats") or {}
    tz = info.get("derived_tz") or (
        "Could not be derived (fewer than 5 SPS/ModifiedTime pairs)")
    fields = [
        ("Database state", info.get("db_state_text") or "Unknown", ""),
        ("Read-only guarantee", READ_ONLY_GUARANTEE, _SOURCE_HANDLING_TEXT),
        ("Derived machine TZ", tz, ""),
        ("Records (URL-cache entries)",
         format(info.get("total_entries", 0), ","),
         "Live records by the definition every count in this application "
         "uses: one URL-cache entry read from a container table."),
        ("Rows parsed, all tables", format(stats.get("parsed", 0), ","),
         "Records plus cookies, HSTS pins, certificates, leak and AppCache "
         "rows — every row the parser read."),
        ("Tables skipped", format(stats.get("skipped", 0), ","), ""),
        ("Record errors", format(stats.get("errors", 0), ","), ""),
    ]
    fields[1:1] = header_time_rows(info.get("header_times"))
    return [{"label": label, "value": value, "tooltip": tooltip}
            for label, value, tooltip in fields]


def clock_rows(info):
    """The Clock card: every UTC offset the SPS local/UTC pairs show, with
    records and dates, whether it is adopted, and the time display format
    in force. Each a dict with "label", "value" and "tooltip"."""
    from ..widgets import time_format
    rows = []
    periods = info.get("clock_offsets") or []
    if not periods:
        rows.append({"label": "Offsets observed",
                     "value": "No record pairs an SPS local time with its "
                              "UTC write time, so no offset was observed.",
                     "tooltip": ""})
    for p in periods:
        span = (p["first"] if p["first"] == p["last"]
                else "%s to %s" % (p["first"], p["last"]))
        rows.append({
            "label": p["offset"],
            "value": "%s %s, %s, %s records%s" % (
                format(p["records"], ","),
                "record" if p["records"] == 1 else "records", span,
                p.get("source", "live"),
                "" if p["adopted"] else " (not adopted: seen too rarely to "
                                        "be a clock the machine kept)"),
            "tooltip": "From History records whose SPS property 24 (local "
                       "time) and ModifiedTime (UTC) were written together."})
    rows.append({"label": "Times shown as",
                 "value": time_format.pattern(),
                 "tooltip": "View > Time display format. Exports always "
                            "write ISO 8601."})
    return rows


def decision_log_rows(info):
    """WebCacheParser.decision_log, one row per line in the engine's
    order, each flagged when it names a skipped table, a table registered
    but absent, or records that failed to parse.
    """
    rows = [{"text": text,
             "flagged": any(phrase in text for phrase in _FLAG_PHRASES)}
            for text in info.get("decision_log", [])]
    # The recovery scan's own decisions, once one has run.
    rows += [{"text": RECOVERY_PREFIX + text,
              "flagged": any(phrase in text for phrase in
                             _FLAG_PHRASES + _RECOVERY_FLAG_PHRASES)}
             for text in info.get("recovery_log", [])]
    return rows


def report_text(info, generated_utc):
    """The Integrity screen as one plain-text report: every card, every
    value in full, the decision log line by line with flagged lines
    marked "!". `generated_utc` is when the report was made."""
    from .. import provenance

    def rows_block(rows):
        width = max((len(r["label"]) for r in rows), default=0)
        return ["  %s : %s" % (r["label"].ljust(width), r["value"])
                for r in rows]

    lines = ["WebCache Forensic Analyzer %s — integrity report"
             % provenance.TOOL_VERSION,
             "Generated (UTC): %s" % generated_utc,
             "Evidence: %s" % (info.get("path") or ""),
             "",
             "SOURCE INTEGRITY"]
    lines += rows_block(source_integrity_rows(info))
    lines += ["", "CLOCK"]
    lines += rows_block(clock_rows(info))
    lines += ["", "SHA-256 SOURCE HASHES"]
    hashes = hash_rows(info)
    if not hashes:
        lines.append("  No source files were hashed for this exhibit.")
    for row in hashes:
        lines.append("  %s  %s  (%s)" % (row["SHA256"], row["File"],
                                         row["Role"]))
    lines += ["", "PARSING DECISION LOG",
              "  Lines marked ! name a skipped table, an absent table or "
              "records that failed to parse."]
    log = decision_log_rows(info)
    if not log:
        lines.append("  No decision-log entries for this exhibit.")
    for row in log:
        lines.append(("! " if row["flagged"] else "  ") + row["text"])
    return "\n".join(lines) + "\n"
