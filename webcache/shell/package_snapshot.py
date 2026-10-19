"""What the offline report carries, read off the application as it stands.

Runs on the GUI thread, once per export. It reads the BUILT views -- each
RecordSet's own columns and the rows the app is showing -- because that is
the only place the exact row set exists after loaders, recovery merges and
per-view shaping. Rows are handed on BY REFERENCE (the precedent
ExportJob(rows=...) already sets for a view export) and are only read.

Duck-typed and Qt-free: a plain stand-in with the same attributes is enough
to test it, and nothing here imports PySide6
(tests/test_package_snapshot.py).

Two parts are deferred to the export worker through a segment factory,
because neither needs the GUI thread: Timeline's period rows on each clock
(the same timeline_loader.period_rows calls the app's own UTC/LOCAL toggle
makes) and the raw ESE tables (read the way export_sqlite_raw already reads
them from the worker).
"""
from .. import provenance
from ..engine import evidence_model, forensic_engine, local_clock
from . import (dashboard_data, html_package, integrity_loader,
               table_browser_loader, timeline_loader)
from .html_package import (PackageColumn, PackageSegment, PackageSnapshot,
                           PackageView)
from .record_kinds import K_TABLE_ROW

#: The record views the page carries, in the app's nav order. Dashboard and
#: Integrity become the page's Case summary, Search its own search, Export
#: & Report its own export, and Table Browser its "Raw tables".
PACKAGE_VIEW_KEYS = ("history", "downloads", "timeline", "domains",
                     "location", "indicators", "iocs", "cookies", "headers",
                     "containers", "recovery")

SECTION_OF = {"history": "USER ACTIVITY", "downloads": "USER ACTIVITY",
              "timeline": "ANALYSIS", "domains": "ANALYSIS",
              "location": "ANALYSIS", "indicators": "ANALYSIS",
              "iocs": "ANALYSIS", "cookies": "ARTIFACTS",
              "headers": "ARTIFACTS", "containers": "ARTIFACTS",
              "recovery": "RECOVERY", "raw": "DATABASE"}

#: Why a post= chip (History's "One row per visit") is listed, not offered.
POST_CHIP_REASON = (
    "Not reproduced in the offline report: this chip decides by comparing "
    "each row with the other rows on screen, which only the app can do. "
    "Every row it would hide is in this report.")

RAW_VIEW_CAPTION = ("Raw ESE tables exactly as stored, with no "
                    "interpretation applied.")


def quick_spec(spec):
    """One QuickFilter as the page applies it: a value set (encoded the way
    the island stores cells) or a Condition (op, a, b) -- or, for a chip
    that needs the other rows on screen, the reason it is not offered."""
    post = getattr(spec, "post", None)
    if post is not None:
        from ..views.record_chips import hide_shown_twins
        if post is hide_shown_twins:
            # "One row per visit" compares each row's visit key with its
            # twin's; the report carries both (seg "tw") and applies the
            # same rule in the page.
            return {"label": spec.label, "twins": True,
                    "sentence": spec.sentence}
        return {"label": spec.label, "skipped": POST_CHIP_REASON}
    condition = spec.condition
    return {
        "label": spec.label, "key": spec.key,
        "values": (None if spec.values is None else
                   [html_package.encode_cell(v) for v in spec.values]),
        "cond": (None if condition is None else
                 [condition.op, condition.a, condition.b]),
        "sentence": spec.sentence,
        # Whether the chip names how many records it keeps, as the app's
        # does (QuickFilter.counted).
        "counted": bool(getattr(spec, "counted", False)),
        # What a zero on this chip does and does not cover.
        "none_note": getattr(spec, "none_note", None),
    }


def split_open_log(case):
    """(case without the open log, [[opened_utc, path, sha256, bytes], ...])
    -- the case file's evidence-opened log becomes its own table in the
    report instead of a JSON string in the Case table."""
    import json
    from .case_store import OPEN_LOG_META_KEY
    case = dict(case or {})
    raw = case.pop(OPEN_LOG_META_KEY, None)
    rows = []
    try:
        entries = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        entries = []
    for entry in entries if isinstance(entries, list) else []:
        for f in (entry or {}).get("files") or ():
            rows.append([entry.get("opened_utc", ""), f.get("path", ""),
                         f.get("sha256", ""), f.get("bytes", 0)])
    return case, rows


def page_summary(summary):
    """The Dashboard's case summary as the page shows it. "Size" reads as
    the app's own figure ("136.5 MB") with the exact byte count beside it; every other row is unchanged."""
    out = []
    for label, value in summary:
        if label == "Size" and isinstance(value, int):
            value = "%s (%s bytes)" % (dashboard_data.format_size(value),
                                       format(value, ","))
        out.append((label, value))
    return out


def _recovery_chips():
    """Deleted Records' own chips (views/recovery.py), as the page applies
    them: the three method buttons -- one exclusive group, "All methods"
    being none of them ticked -- and "High confidence only"."""
    from .record_kinds import K_CARVED_STRING, K_CARVED_STRUCT, K_TOMBSTONE

    def chip(label, key, value, sentence, group=None):
        return {"label": label, "key": key,
                "values": [html_package.encode_cell(value)], "cond": None,
                "sentence": sentence, "group": group}
    return [
        chip("Structured", "_kind", K_CARVED_STRUCT, "Method: Structured",
             "method"),
        chip("String carves", "_kind", K_CARVED_STRING,
             "Method: String carves", "method"),
        chip("Deleted-record stubs", "_kind", K_TOMBSTONE,
             "Method: Deleted-record stubs", "method"),
        chip("High confidence only", "Confidence", "high",
             "Confidence: high"),
    ]


def segments_of(view, caption=""):
    """Every RecordSet of a RecordsView, or RecoveryView's one table."""
    record_sets = getattr(view, "_record_sets", None)
    if record_sets:
        quick = [quick_spec(s)
                 for s in (getattr(view, "_quick_filters", None) or ())]
        view_caveat = getattr(view, "_view_caveat", None) or caption
        noun = getattr(view, "COUNT_NOUN", "records")
        notes = getattr(view, "_segment_notes", None) or {}
        table = getattr(view, "table", None)
        cap = (getattr(table.itemDelegate(), "line_cap", None)
               if table is not None else None)
        out = []
        for rs in record_sets:
            rows = list(view._segment_rows.get(rs.key) or ())
            out.append(PackageSegment(
                rs.key, rs.label,
                [PackageColumn.from_column(c) for c in rs.columns], rows,
                noun=rs.count_noun or noun, subtitle=rs.subtitle(len(rows)),
                caveat=rs.caveat or view_caveat,
                empty_text=(view.empty_text_for(rs)
                            if hasattr(view, "empty_text_for") else rs.empty_text),
                note=notes.get(rs.key) or "", default_sort=rs.default_sort,
                quick=quick, cap=cap))
        return out
    model = view.table.model()
    rows = list(model.filter.rows) if model is not None else []
    note = getattr(view, "_note", None) or ""
    return [PackageSegment(
        "records", "Recovered records",
        [PackageColumn.from_column(c)
         for c in (getattr(view, "COLUMNS", None) or ())], rows,
        subtitle=("%s recovered record%s. Every row states which file it "
                  "was carved from and how confident the engine is in it."
                  % (format(len(rows), ","), "" if len(rows) == 1 else "s")),
        noun="recovered records",
        quick=_recovery_chips(),
        caveat=caption, empty_text=note or "No recovered records.",
        note=note, default_sort=("Timestamp", True))]


def _period_factory(inputs, grain, offset, local, label, scan_run):
    def load():
        if inputs is None:
            return None, [], ""
        rows = timeline_loader.period_rows(inputs, grain,
                                           offset_seconds=offset, local=local)
        return None, rows, timeline_loader.grain_note(
            inputs, rows, grain, scan_run=scan_run, clock_label=label)
    return load


def badge_for(window, key):
    """(text, unit) for one view's badge in the report: the app sidebar's
    own, or None.

    Timeline's is counted from the SAME inputs timeline_segments builds the
    report's pages from: the sidebar's figure waits on a background
    rebuild after recovery, and an export taken in that window stamped
    the live-only count beside pages holding every dated record."""
    inputs = getattr(window, "_timeline_inputs", None)
    if key == "timeline" and inputs is not None:
        from . import record_counts
        return (format(timeline_loader.dated_record_count(inputs), ","),
                record_counts.BADGE_UNITS["timeline"])
    sidebar = getattr(window, "sidebar", None)
    if sidebar is None or not hasattr(sidebar, "count_of"):
        return None
    return sidebar.count_of(key)


def timeline_segments(window, view):
    """The four grains on UTC and, when a zone was recovered, the four on
    LOCAL -- each built by the call MainWindow._fill_timeline makes for
    that clock."""
    inputs = getattr(window, "_timeline_inputs", None)
    offset = window._timeline_zone_offset()
    scan_run = getattr(window, "_recovery_engine", None) is not None
    grains = {rs.key: rs for rs in getattr(view, "_record_sets", ())}
    view_caveat = getattr(view, "_view_caveat", "") or ""
    clocks = [("utc", 0, False, "UTC")]
    if offset is not None:
        clocks.append(("local", offset, True,
                       local_clock.zone_label(offset) or "local"))
    out = []
    for clock, off, local, label in clocks:
        for grain, grain_label, _plural in timeline_loader.GRAINS:
            rs = grains.get(grain)
            if rs is None:
                continue
            columns = [PackageColumn.from_column(c) for c in rs.columns]
            for col in columns:
                if col.key == "PeriodStart":
                    col.label = "Period start (%s)" % label
            out.append(PackageSegment(
                "%s_%s" % (grain, clock),
                "%s (%s)" % (grain_label, label), columns,
                noun=rs.count_noun or getattr(view, "COUNT_NOUN", "periods"),
                subtitle=rs.subtitle, caveat=rs.caveat or view_caveat,
                empty_text=rs.empty_text, clock=clock,
                default_sort=rs.default_sort,
                factory=_period_factory(inputs, grain, off, local, label,
                                        scan_run)))
    return out


def _raw_factory(parser, name):
    def load():
        count = parser.get_table_row_count(name)
        names, raw_rows = parser.get_table_rows_raw(
            name, limit=max(count, 1), offset=0)
        key_at = names.index("EntryId") if "EntryId" in names else None
        stored, decoded_any, rows = {}, set(), []
        for number, raw in enumerate(raw_rows, 1):
            row = {"_kind": K_TABLE_ROW, "_record": None, "_row": number}
            entry_id = (raw[key_at] if key_at is not None and key_at < len(raw)
                        else None)
            for i, column in enumerate(names):
                value = raw[i] if i < len(raw) else None
                if isinstance(value, memoryview):
                    value = value.tobytes()
                stored.setdefault(column, set()).add(
                    parser.raw_type_name(value))
                if isinstance(value, (bytes, bytearray)):
                    # Every byte, as hex: nothing is cut.
                    row["c:" + column] = bytes(value).hex().upper()
                    continue
                row["c:" + column] = parser.raw_rendering(value)
                decoded = table_browser_loader.decode_filetime_cell(
                    parser, name, column, value, entry_id)
                if decoded:
                    row["d:" + column] = decoded
                    decoded_any.add(column)
            rows.append(row)
        columns = [PackageColumn("_row", "Row #", kind="num", width=70)]
        for column in names:
            kinds = sorted(t for t in stored.get(column, ()) if t != "null")
            columns.append(PackageColumn(
                "c:" + column, column, kind="text", width=160,
                note=("Stored as %s. Shown exactly as stored: binary as hex, "
                      "nothing decoded." % (", ".join(kinds) or "null"))))
            if column in decoded_any:
                columns.append(PackageColumn(
                    "d:" + column, "%s (decoded)" % column, kind="text",
                    width=190,
                    note=("This tool's FILETIME reading of the column to its "
                          "left. The stored value is that column.")))
        # The count line already says "N rows".
        return columns, rows, ""
    return load


def raw_view(parser, caption=""):
    segments = []
    for group, tables in table_browser_loader.grouped_tables(parser):
        for info in tables:
            name = info["name"]
            segments.append(PackageSegment(
                "t:" + name, parser.get_table_display_name(name) or name, [],
                noun="rows", caveat=caption or RAW_VIEW_CAPTION,
                empty_text="This table holds no rows.", group=group,
                factory=_raw_factory(parser, name)))
    return PackageView("raw", "Raw tables", SECTION_OF["raw"],
                       caption or RAW_VIEW_CAPTION, segments, picker="list")


def integrity_section(info):
    """The Integrity screen's cards for the page: hashes, source
    integrity, the clock offsets observed and the decision log. The
    clock leaves out "Times shown as", the examiner's display setting."""
    return {
        "hashes": [[r["File"], r["Role"], r["SHA256"]]
                   for r in integrity_loader.hash_rows(info)],
        "source": [[r["label"], r["value"], r["tooltip"]]
                   for r in integrity_loader.source_integrity_rows(info)],
        "clock": [[r["label"], r["value"], r["tooltip"]]
                  for r in integrity_loader.clock_rows(info)
                  if r["label"] != "Times shown as"],
        "log": [[r["text"], r["flagged"]]
                for r in integrity_loader.decision_log_rows(info)],
    }


def snapshot_from_window(window, member_columns=()):
    parser = getattr(window, "_parser", None)
    labels = getattr(window, "_labels", None) or {}
    caveats = getattr(window, "_caveats", None) or {}
    views = []
    for key in PACKAGE_VIEW_KEYS:
        window._ensure_view_built(key)
        view = window.stack.widget(window._index[key])
        caption = caveats.get(key, "")
        if key == "timeline":
            segments, initial = timeline_segments(window, view), "day_utc"
        else:
            segments, initial = segments_of(view, caption), None
        views.append(PackageView(key, labels.get(key, key), SECTION_OF[key],
                                 caption, segments, initial=initial))
    if parser is not None and getattr(parser, "db", None) is not None:
        views.append(raw_view(parser, caveats.get("browser", "")))
    for view in views:
        found = badge_for(window, "browser" if view.key == "raw"
                          else view.key)
        if found and found[0]:
            view.badge, view.unit = found
    recovery_rows = None
    if getattr(window, "_recovery_engine", None) is not None:
        recovery = views[PACKAGE_VIEW_KEYS.index("recovery")]
        recovery_rows = list(recovery.segments[0].rows or ())
    info = dict(getattr(window, "_db_summary_info", None) or {})
    summary = page_summary(dashboard_data.case_summary(
        parser, recovery_rows,
        recovery_state=getattr(window, "_recovery_state", None))
               if parser is not None else [])
    evidence = window._evidence_or_empty()
    case_meta, opened = split_open_log(window._case_meta())
    offset = getattr(parser, "derived_tz_offset_seconds", None)
    meta = {
        "tool": forensic_engine.TOOL_NAME,
        "tool_version": provenance.TOOL_VERSION,
        "evidence": [{"path": path,
                      "sha256": (evidence.hashes or {}).get(path, ""),
                      "bytes": (evidence.sizes or {}).get(path, 0)}
                     for path in evidence.files],
        "case": case_meta,
        "opened": opened,
        "recovery_scan_run": (getattr(window, "_recovery_engine", None)
                              is not None),
        "zone": {"offset_seconds": offset,
                 "label": local_clock.zone_label(offset)},
    }
    integrity = integrity_section(info)
    return PackageSnapshot(
        views, meta, summary=summary, integrity=integrity,
        scope=list(evidence_model.SCOPE_STATEMENTS),
        basis=[(evidence_model.BASIS_SHORT[b], b,
                evidence_model.BASIS_DEFINITION[b])
               for b in evidence_model.BASIS_ORDER],
        member_columns=list(member_columns), tags_map=window._tags_map(),
        comments_map=window._comments_map())
