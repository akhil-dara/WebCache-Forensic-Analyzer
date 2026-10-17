"""What this tool can write, why a format is sometimes unavailable, and
the two writers that are not engine functions.

THE CATALOGUE IS DATA. views/export.py renders every entry this module
declares, including those that cannot run now: an unavailable format stays
on screen, greyed, with the sentence saying why. UNAVAILABLE_REASON is a
table of literals so the same unavailability is always explained the same
way.

The position formats read "not loaded" when no fixes have been read, as a
count line says "deleted records not yet recovered" rather than 0.

TWO WRITERS LIVE HERE. forensic_engine writes the canonical 80-field
schema, and each of its exports carries every field. The other unit of
export is the rows the examiner is looking at, in the columns and order
shown, after filters: write_view_csv writes those, and
write_view_provenance writes the sidecar that states which filters
produced them. A view's on-screen shape belongs to the shell, so these
writers are here rather than in the engine.

Qt-free. Imported by a view (views/export.py, for the catalogue) and by
the shell (main_window/export_runner, for the writers); nothing here
returns an engine object, only strings, booleans and files.
"""
import csv
import datetime
import hashlib
import json
import os

from .. import provenance
from ..engine import forensic_engine
from ..widgets.column_spec import blank_label, display_text
from . import record_kinds

#: Group headings, in the order views/export.py renders them.
G_COURT = "Court-ready / DFIR pipeline"
G_GENERAL = "General purpose"
G_POSITION = "Position fixes"
G_BUNDLE = "Complete case bundle"

#: The number of canonical fields every engine export carries, read from
#: the engine's schema rather than written as a number.
CANONICAL_FIELD_COUNT = len(forensic_engine.ENTRY_FIELDS)

#: token -> the sentence shown on a card the token disables. One literal
#: per token; never assembled at the call site, so the same unavailability
#: can never be explained two different ways.
UNAVAILABLE_REASON = {
    "reportlab": ("reportlab is not installed, so no PDF can be written. "
                  "Every other format carries the same fields."),
    "openpyxl": ("openpyxl is not installed, so no workbook can be written. "
                 "Flat CSV carries every field this workbook would."),
    "entries": "No evidence is open. Open a database first.",
    "stats": "Statistics could not be computed for this exhibit.",
    "parser": ("No evidence is open, so there is no database to copy table "
               "for table."),
    # A statement about the exhibit: the sentence names the scan that has
    # not run, so "nothing was found" is not confused with "not looked".
    "location_fixes": ("No position fixes were found in this exhibit — no "
                       "cached URL reported a position. Run Evidence ▸ "
                       "Recover deleted records: a position is routinely "
                       "found only in a deleted or unflushed URL, which the "
                       "live database no longer holds."),
}


class ExportFormat:
    """One row of the catalogue.

    requires  capability tokens (see UNAVAILABLE_REASON) that must all be
              true before this format can run.
    writes    "file" or "directory": which chooser the shell opens.
    sidecar   whether the runner writes <file>.metadata.json itself.
              False for formats whose engine writer already writes its
              own (loc_csv, through _write_metadata_sidecar), so there is
              one writer per sidecar.
    """
    __slots__ = ("key", "title", "icon", "group", "description", "extension",
                 "default_basename", "requires", "writes", "sidecar")

    def __init__(self, key, title, icon, group, description, extension,
                 default_basename, requires=(), writes="file", sidecar=True):
        self.key = key
        self.title = title
        self.icon = icon
        self.group = group
        self.description = description
        self.extension = extension
        self.default_basename = default_basename
        self.requires = tuple(requires)
        self.writes = writes
        self.sidecar = sidecar

    def __repr__(self):
        return "ExportFormat(%r)" % self.key


CATALOGUE = [
    ExportFormat(
        "pdf", "Signed-report PDF", "file", G_COURT,
        "Provenance header, hashes, methodology, statistics, EntryId "
        "gaps and the records themselves — the document that goes in "
        "the bundle handed to counsel.",
        ".pdf", "webcache_forensic_report",
        requires=("entries", "stats", "reportlab")),
    ExportFormat(
        "sqlite_raw", "Raw ESE → SQLite", "database", G_COURT,
        "Every ESE table copied table for table, with no interpretation "
        "applied — the second opinion another examiner can query without "
        "trusting this tool's decoding.",
        ".sqlite", "webcache_raw_ese",
        requires=("parser",)),

    ExportFormat(
        "xlsx", "Forensic workbook", "grid", G_GENERAL,
        "Case info, summary, all records, and a sheet per record kind plus "
        "per-container sheets. Timestamps are real date cells and every "
        "column is at least as wide as its own heading.",
        ".xlsx", "webcache_forensic_workbook",
        requires=("entries", "openpyxl")),
    ExportFormat(
        "csv", "Flat CSV (every field)", "file", G_GENERAL,
        "One row per record carrying all %d canonical fields. The format "
        "nothing can fail to read." % CANONICAL_FIELD_COUNT,
        ".csv", "webcache_all_records_full",
        requires=("entries",)),
    ExportFormat(
        "json", "Complete JSON", "file", G_GENERAL,
        "Provenance header, every entry field, every auxiliary artifact "
        "collection, recovered records and analytics, in one structured "
        "document.",
        ".json", "webcache_complete_data",
        requires=("entries",)),
    ExportFormat(
        "sqlite", "Case SQLite", "database", G_GENERAL,
        "The canonical schema as a queryable database, with the artifact "
        "collections and recovered records alongside it.",
        ".sqlite", "webcache_case",
        requires=("entries",)),
    ExportFormat(
        "html", "Offline HTML report", "globe", G_GENERAL,
        "One file that opens in any browser with nothing installed: every "
        "view's records, raw beside derived, with filter, sort, search and "
        "CSV/XLSX export inside the page.",
        ".html", "webcache_offline_report",
        requires=("entries",)),

    ExportFormat(
        "loc_csv", "Position fixes CSV", "pin", G_POSITION,
        "Every position the device reported, with accuracy and the place "
        "record it belongs to.",
        ".csv", "webcache_location_fixes",
        # sidecar=False: export_location_csv writes its own sidecar
        # (rows_written=len(fixes), through _write_metadata_sidecar).
        #
        # "entries" first, then "location_fixes": availability() stops at
        # the first failing token, and location_fixes is False both when an
        # open exhibit has no fixes and when nothing is open. Checking
        # "entries" first means "no evidence is open" is reported whenever
        # it is true, and the exhibit sentence ("No position fixes were
        # found in this exhibit...") only once evidence is open.
        requires=("entries", "location_fixes"), sidecar=False),
    ExportFormat(
        "loc_kml", "Position fixes KML", "pin", G_POSITION,
        "The same fixes as a map layer, with carved fixes kept in their own "
        "folder so a reconstructed position is never plotted as a recorded "
        "one.",
        ".kml", "webcache_location_fixes",
        requires=("entries", "location_fixes")),
    ExportFormat(
        "loc_json", "Position fixes JSON", "pin", G_POSITION,
        "Every fix with its derived fields and, beside each, every field of "
        "the record it was read out of.",
        ".json", "webcache_location_fixes",
        requires=("entries", "location_fixes")),
    ExportFormat(
        "loc_xlsx", "Position fixes workbook", "pin", G_POSITION,
        "The fixes CSV as a workbook: each fix, then its source record's "
        "fields, raw FILETIMEs and ids included.",
        ".xlsx", "webcache_location_fixes",
        requires=("entries", "location_fixes", "openpyxl")),

    ExportFormat(
        "bundle", "Complete case bundle", "download", G_BUNDLE,
        "Every format above written into one directory, plus a SHA-256 "
        "manifest of every file in it.",
        "", "webcache_case_bundle",
        requires=("entries",), writes="directory", sidecar=False),
]

BY_KEY = {fmt.key: fmt for fmt in CATALOGUE}

#: The bundle's members, in write order, with the filenames
#: ForensicEngine.export_full_bundle uses. Listed here so the runner can
#: show real progress ("4 of 10"), stop between members so a cancelled
#: bundle keeps whole files, and record a per-format status in the
#: manifest (a PDF absent because reportlab is missing appears with its
#: reason). tests/test_export_runner.py checks every filename here against
#: export_full_bundle's source.
BUNDLE_MEMBERS = [
    ("csv", "Full CSV", "01_all_records_full.csv"),
    ("xlsx", "Excel workbook", "02_forensic_workbook.xlsx"),
    ("json", "JSON", "03_complete_data.json"),
    ("html", "Offline HTML report", "04_offline_report.html"),
    ("pdf", "PDF report", "05_forensic_report.pdf"),
    ("recovered_csv", "Recovered CSV", "06_recovered_artifacts.csv"),
    ("sqlite", "SQLite database", "07_case.sqlite"),
    ("sqlite_raw", "Raw ESE->SQLite", "08_raw_ese.sqlite"),
]

#: The one manifest filename. Matches export_full_bundle's own.
MANIFEST_NAME = "00_MANIFEST.json"

#: Bundle-member keys whose file leaves recovered records out. Currently
#: empty: every member includes the carved records, merged into one table
#: (csv, sqlite), in a section of its own (xlsx, json, pdf), or as every
#: view's rows (the offline report). finalise_bundle_manifest consults it,
#: so a member that excludes them is recorded in one place.
BUNDLE_KEYS_WITHOUT_RECOVERED = frozenset()

#: Bundle members the SHELL writes and the engine cannot: the offline
#: report is built from the app's views (a PackageSnapshot), which
#: ForensicEngine.export_full_bundle never sees, so that engine-only
#: method has no HTML member. The test pinning BUNDLE_MEMBERS against its
#: source skips these keys.
SHELL_WRITTEN_BUNDLE_KEYS = frozenset({"html"})

#: filename -> key, built from BUNDLE_MEMBERS once rather than at every
#: manifest write. finalise_bundle_manifest receives (filename, label,
#: status, reason) tuples with no key of their own, so this is how it
#: recovers which writer produced each file.
_BUNDLE_FILENAME_TO_KEY = {filename: key for key, _label, filename
                          in BUNDLE_MEMBERS}


def formats_in(group):
    """Catalogue order, never re-sorted per call -- the page's reading
    order is part of the design, not an accident of dict iteration."""
    return [fmt for fmt in CATALOGUE if fmt.group == group]


def capabilities(parser, entries, stats, recovery_engine, location_fixes=()):
    """What is loaded now, as capability tokens.

    Called by MainWindow on every state change (evidence loaded, recovery
    finished) and passed to availability(). No format requires a recovery
    scan, but whether one has run is recorded in the bundle manifest, so
    it is answered here once.
    """
    return {
        "parser": parser is not None,
        "entries": bool(entries),
        "stats": bool(stats),
        "reportlab": bool(forensic_engine.HAS_REPORTLAB),
        "openpyxl": bool(forensic_engine.HAS_OPENPYXL),
        "location_fixes": bool(location_fixes),
        "recovery_scan_run": recovery_engine is not None,
    }


def availability(caps):
    """{key: (ok, reason)} for every catalogue key.

    Never a filtered list: the view renders every card, so every key has
    an answer. `reason` is "" exactly when ok is True.
    """
    caps = caps or {}
    out = {}
    for fmt in CATALOGUE:
        reason = ""
        for token in fmt.requires:
            if not caps.get(token):
                reason = UNAVAILABLE_REASON[token]
                break
        out[fmt.key] = (reason == "", reason)
    return out


# --- the view CSV, and the sidecar that states its scope ----------------

#: Appended to every view CSV after the view's own columns, except where
#: the view already declares them (appended_columns_for). Without them a
#: Cookies or Domains CSV could not tell a carved row from a live one.
APPENDED_COLUMNS = ("Origin", "RecordSource")


def appended_columns_for(columns):
    """Which of APPENDED_COLUMNS this view's CSV still needs appended.

    History, Recovery and Headers declare their own Origin column, holding
    the values origin_cell() derives (Origin="Live record"/CARVED_ORIGIN,
    set by evidence_loader.py and recovery_loader.py), so it is not
    appended twice.

    write_view_csv and scope_from_view both call this, so a file's header
    and its sidecar's "Columns in file" line always name the same columns.

    Decided by label and by key: History declares Origin under the label
    "Origin detail" and Source as "Carved from".
    """
    declared_labels = {col.label for col in columns}
    declared_keys = {col.key for col in columns}
    return [name for name, key in zip(APPENDED_COLUMNS, ("Origin", "Source"))
            if name not in declared_labels and key not in declared_keys]


def column_arithmetic(scope):
    """The sidecar line reconciling the file's column count with the
    view's and the schema's, so the footnote, the sidecar and the file
    state numbers that refer to each other."""
    total = len(scope.get("columns") or ())
    view = scope.get("view_column_count", 0)
    entry = scope.get("canonical_entry_count",
                      scope.get("canonical_column_count", 0))
    shown = scope.get("canonical_shown_count", 0)
    own = scope.get("canonical_own_count", 0)
    line = ("%s = %s view columns + %s canonical fields "
            "(of %d in the schema; %s already shown as view columns)"
            % (format(total, ","), format(view, ","), format(entry, ","),
               len(forensic_engine.ENTRY_FIELDS), format(shown, ",")))
    if own:
        line += " + %s record fields" % format(own, ",")
    return line


#: Record kinds that are NOT URL-cache entries. ENTRY_FIELDS describes a
#: cache entry (a URL, its container, its FILETIMEs); stamped on a cookie,
#: an HSTS pin, a certificate or a container it is ~76 blank columns and a
#: derived UrlCategory claim about a URL the record does not have. Each of
#: these instead gets its OWN record's complete field set -- every key its
#: source dict carries, its raw FILETIME integers included.
OWN_FIELD_KINDS = frozenset((record_kinds.K_COOKIE, record_kinds.K_HSTS,
                             record_kinds.K_CERT, record_kinds.K_CONTAINER))


def _record_of(row):
    """The one record behind a row, or None for a row that is not one
    record (an aggregate, a search table row, a place)."""
    if row.get("_kind") in record_kinds.AGGREGATES:
        return None
    record = row.get("_record")
    return record if isinstance(record, dict) else None


def _block_of(row):
    """"own" for a non-entry record kind, "entry" for every other record,
    None for a row with no single record. Decided from the row's KIND,
    never from which of its columns happen to be blank."""
    if _record_of(row) is None:
        return None
    return "own" if row.get("_kind") in OWN_FIELD_KINDS else "entry"


def canonical_columns_for(rows, columns):
    """[(key, header)] appended after a view's own columns.

    For URL-cache records (history, file access, downloads, carved rows,
    stubs, header and IOC rows): the full ENTRY_FIELDS set, in schema
    order, minus what the view already shows: the same fixed column set
    every engine export writes, so a field a record lacks is a blank cell,
    never a missing column.

    "Already shows" is decided by declaration, not by name: a view column
    stands in for a record field only when both its key and its declared
    `field` are that field. A key that merely shares the name means
    something else (the IOC view's Source is "carved"/"live"; the
    canonical Source is the file a record was carved from), so the
    canonical field is kept under its canonical label, or "<label>
    (record)" where that label is taken. The appended Origin and
    RecordSource are derived per row and stand in for nothing; the
    record's own Origin and Source are always written too.

    For the OWN_FIELD_KINDS (cookies, HSTS pins, certificates,
    containers): every key their source records carry, in first-seen
    order, keyed ("_record", key) so the writer reads the record itself.

    [] when no row is a record (an aggregate view: a Domains or
    Timeline-period row has no single record behind it)."""
    blocks = {_block_of(r) for r in rows}
    blocks.discard(None)
    if not blocks:
        return []
    declared_keys = {c.key for c in columns
                     if c.field is not None and c.field == c.key}
    used = {c.label for c in columns} | set(APPENDED_COLUMNS)
    out = []

    def add(key, header):
        if header in used:
            header = "%s (record)" % header
        used.add(header)
        out.append((key, header))

    if "entry" in blocks:
        for key, header, _group in forensic_engine.ENTRY_FIELDS:
            if key not in declared_keys:
                add(key, header)
    if "own" in blocks:
        seen = {}
        for row in rows:
            if _block_of(row) == "own":
                for key in _record_of(row):
                    seen.setdefault(key, None)
        for key in seen:
            if key not in declared_keys:
                add(("_record", key), str(key))
    return out


def view_layout(rows, columns):
    """(headers, timestamp flags, appended, canon) -- the one layout both
    view writers write, so the CSV and the xlsx can never differ."""
    appended = appended_columns_for(columns)
    canon = canonical_columns_for(rows, columns)
    headers = ([c.label for c in columns] + appended
               + [header for _key, header in canon])
    flags = ([c.kind in _TIMESTAMP_KINDS for c in columns]
             + [False] * len(appended)
             + [not isinstance(key, tuple)
                and key in forensic_engine.TIMESTAMP_EXPORT_KEYS
                for key, _h in canon])
    return headers, flags, appended, canon


def canonical_counts(rows, columns, canon):
    """The sidecar's facts about the appended block, from the layout
    itself: how many ENTRY_FIELDS columns, how many own-record columns,
    how many ENTRY_FIELDS the view already shows, and whether every row is
    an aggregate (the reason a view gets none)."""
    entry = sum(1 for key, _h in canon if not isinstance(key, tuple))
    return {
        "canonical_column_count": len(canon),
        "canonical_entry_count": entry,
        "canonical_own_count": len(canon) - entry,
        "canonical_shown_count": (len(forensic_engine.ENTRY_FIELDS) - entry
                                  if entry else 0),
        "rows_are_aggregates": all(
            r.get("_kind") in record_kinds.AGGREGATES for r in rows),
    }


def _record_layout_into(scope, columns, appended, canon, headers, rows=()):
    """Write the layout a writer used into the sidecar's scope, so
    "Columns in file" and both counts describe the file on disk, also for
    a caller (Timeline period, Search row) that built its own scope."""
    if isinstance(scope, dict):
        scope["columns"] = list(headers)
        scope["view_column_count"] = len(columns) + len(appended)
        scope.update(canonical_counts(rows, columns, canon))


def _view_cells(row, columns, appended, canon, tags_map=None,
                comments_map=None):
    # A bool in the view's own columns is written as the grid shows it,
    # "Yes"/"No", by both writers. The canonical block below is written as
    # the engine writes it.
    cells = [display_text(v, c) if isinstance(v, bool) else v
             for v, c in ((row.get(c.key), c) for c in columns)]
    if "Origin" in appended:
        cells.append(origin_cell(row))
    if "RecordSource" in appended:
        cells.append(row.get("Source"))
    if canon:
        block = _block_of(row)
        record = _record_of(row)
        full = None
        if block == "entry":
            carved = origin_cell(row) == provenance.CARVED_ORIGIN
            full = forensic_engine.canonical_record_row(
                record, carved=True if carved else None,
                tags_map=tags_map, comments_map=comments_map)
        for key, _h in canon:
            if isinstance(key, tuple):
                value = record.get(key[1]) if block == "own" else None
            else:
                value = full.get(key) if full is not None else None
            cells.append(forensic_engine._cell(value))
    return cells

#: The characters Excel treats as the start of a formula. Values that
#: begin with one are COUNTED and never altered -- changing a stored value
#: to make a spreadsheet behave is evidence tampering. Only text is
#: counted: a negative number legitimately begins with "-" and Excel reads
#: it as the number it is.
_FORMULA_LEAD = ("=", "+", "-", "@")

_AGGREGATE_CELL = "Aggregate (not a record)"
_LIVE_CELL = "Live record"


def origin_cell(row):
    """What the appended Origin column says for one row.

    Three answers. The aggregate test comes first: a Domains row is not a
    record, whatever Origin it carries, and is never described as one
    (see record_kinds.K_DOMAIN).
    """
    label = provenance.row_origin_label(row)
    if label == provenance.NOT_A_RECORD:
        return label
    if provenance.aggregate_members(row) is not None:
        return "%s — %s" % (_AGGREGATE_CELL, label)
    if row.get("_kind") in record_kinds.AGGREGATES:
        return _AGGREGATE_CELL
    if label == "Carved":
        return provenance.CARVED_ORIGIN
    return _LIVE_CELL


def _clean(value, is_timestamp=False):
    """One cell, made safe to write without changing what it says.

    `is_timestamp` must be passed explicitly for every column; it defaults
    to False and is never guessed from the value. A value is a timestamp
    because its column says so (Column.kind "time"/"time_local" in
    write_view_csv, ModifiedTime alone in write_header_pairs_csv), so a
    stored value that only resembles one (an HTTP Date header such as
    "2024-06-15T09:30:00Z") is written exactly as stored.

    A timestamp goes through the engine's excel_datetime, the function
    export_xlsx calls, so the two writers agree. Lone surrogates (common in
    carved text) are substituted through the engine's _safe_text; left in,
    they would raise mid-write.
    """
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        # Uppercase hex through the engine's own _cell, the one the XLSX
        # writer uses: never Python's b'...' repr, which csv.writer wrote.
        return forensic_engine._cell(value)
    if isinstance(value, datetime.datetime) and not is_timestamp:
        # The XLSX writer's own text for a datetime outside a timestamp
        # column (xlsx_cell_parts -> _cell). The CSV said str(value), a
        # different spelling of the same cell.
        return forensic_engine._cell(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        value = str(value)
    if isinstance(value, str):
        value = forensic_engine._safe_text(value)
        if is_timestamp:
            value = forensic_engine.excel_datetime(value)
        return value
    return value


#: Column kinds that hold a timestamp: the only kinds _clean() passes
#: through excel_datetime(). One definition for every writer.
_TIMESTAMP_KINDS = ("time", "time_local")


def _is_formula_text(value):
    return isinstance(value, str) and value[:1] in _FORMULA_LEAD


def write_view_csv(rows, columns, path, scope, tags_map=None,
                   comments_map=None):
    """The rows the examiner is looking at, in the columns and order
    shown. Returns the number of data rows written.

    UTF-8 with BOM through forensic_engine.atomic_write, so the file exists
    only if the export finished.

    Every declared column is written, including one the table hides
    because it holds a single value: that value is still a fact about the
    file, and scope["hidden_columns"] tells the sidecar which columns were
    off screen. Origin and RecordSource follow (APPENDED_COLUMNS), then the
    canonical fields the records carry (canonical_columns_for).

    scope is written once: scope["formula_values"] counts text cells that
    begin with =, +, - or @, counted in the same pass, so
    write_view_provenance can state it.
    """
    rows = list(rows)
    formula_count = 0
    written = 0
    # Only the appended columns the view has not declared (see
    # appended_columns_for). Timestamp flags come from each column's
    # declared kind (and, for a canonical field, TIMESTAMP_EXPORT_KEYS),
    # never from the value (see _clean).
    headers, flags, appended, canon = view_layout(rows, columns)
    with forensic_engine.atomic_write(path, encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for row in rows:
            cells = []
            for value, is_timestamp in zip(
                    _view_cells(row, columns, appended, canon,
                                tags_map, comments_map), flags):
                value = _clean(value, is_timestamp=is_timestamp)
                if _is_formula_text(value):
                    formula_count += 1
                cells.append(value)
            writer.writerow(cells)
            written += 1
    if isinstance(scope, dict):
        scope["formula_values"] = formula_count
    _record_layout_into(scope, columns, appended, canon, headers, rows)
    return written


def write_view_xlsx(rows, columns, path, scope, tags_map=None,
                    comments_map=None):
    """The same layout as write_view_csv, as a workbook: real date cells
    where the column is a timestamp, raw integers kept exact (every cell
    through forensic_engine.write_xlsx_cell, the full workbook's guards)."""
    rows = list(rows)
    headers, flags, appended, canon = view_layout(rows, columns)
    formula_count = [0]

    def cells():
        for row in rows:
            out = _view_cells(row, columns, appended, canon,
                              tags_map, comments_map)
            formula_count[0] += sum(1 for v in out if _is_formula_text(v))
            yield out

    title = scope.get("view_label") if isinstance(scope, dict) else None
    written = forensic_engine.write_simple_xlsx(
        path, title or "View", headers, cells(),
        timestamp_columns=[i for i, flag in enumerate(flags) if flag])
    if isinstance(scope, dict):
        scope["formula_values"] = formula_count[0]
    _record_layout_into(scope, columns, appended, canon, headers, rows)
    return written


#: The pair CSV's own columns. Direction is written explicitly because the
#: distinction exists only in which dict the pair came out of; Ordinal
#: preserves wire order in a file that will be sorted by whoever opens it.
HEADER_PAIR_COLUMNS = ("Url", "Container", "EntryId", "Direction", "Ordinal",
                       "Header", "Value", "RepeatsName", "Stored (UTC)")


def write_header_pairs_csv(rows, path, scope):
    """One row per header pair, not per record. Returns pairs written.

    Each row carries its record's `_pairs` list of
    (direction, ordinal, name, value, repeats_name) tuples, split from the
    raw blob in wire order by shell/headers_loader.py, so a repeated
    Set-Cookie the decoded dict collapsed is included. Origin/RecordSource
    are appended by the same rule as every other view CSV.
    """
    formula_count = 0
    written = 0
    with forensic_engine.atomic_write(path, encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(list(HEADER_PAIR_COLUMNS) + list(APPENDED_COLUMNS))
        for row in rows:
            origin = origin_cell(row)
            source = _clean(row.get("Source"))
            for direction, ordinal, name, value, repeats in row.get("_pairs", ()):
                name_cell, value_cell = _clean(name), _clean(value)
                for cell in (name_cell, value_cell):
                    if _is_formula_text(cell):
                        formula_count += 1
                writer.writerow([
                    _clean(row.get("CleanUrl")), _clean(row.get("ContainerId")),
                    _clean(row.get("EntryId")), direction, ordinal,
                    # name_cell/value_cell are the header's OWN content --
                    # never a timestamp column, however date-shaped a
                    # stored "Date"/"Expires" value looks.
                    name_cell, value_cell, "yes" if repeats else "no",
                    # ModifiedTime alone is "Stored (UTC)" -- a genuine
                    # timestamp, so it alone goes through excel_datetime.
                    _clean(row.get("ModifiedTime"), is_timestamp=True),
                    origin, source])
                written += 1
    if isinstance(scope, dict):
        scope["formula_values"] = formula_count
    return written


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_view_provenance(csv_path, stamp, scope, caution):
    """<name>.provenance.txt beside the file it describes.

    Returns the sidecar's path, or "" if it could not be written -- and a
    failure here NEVER loses the CSV. The caller says so on screen instead
    ("written without one"); refusing to keep a whole export because its
    companion note failed would be the tail wagging the dog.

    Everything in it is a fact one of the three inputs already carries.
    Nothing is derived here that is not arithmetic on those.
    """
    scope = scope or {}
    stamp = stamp or {}
    side = csv_path + ".provenance.txt"
    unit = scope.get("unit") or "rows"
    lines = []
    add = lines.append

    add("WebCache Forensic Analyzer %s — export provenance"
        % provenance.TOOL_VERSION)
    add("Written (UTC): %s" % stamp.get("exported_utc", ""))
    add("")
    add("FILE")
    add("  Name    : %s" % os.path.basename(csv_path))
    try:
        add("  SHA-256 : %s" % _sha256_of(csv_path))
        add("  Bytes   : %s" % format(os.path.getsize(csv_path), ","))
    except OSError as exc:
        add("  SHA-256 : not computed (%s)" % exc)
    add("")
    add("EVIDENCE")
    for path, digest in (stamp.get("evidence") or {}).items():
        add("  %s" % path)
        add("    SHA-256 %s" % digest)
    if not (stamp.get("evidence") or {}):
        add("  (no evidence set recorded for this export)")
    add("")
    add("VIEW")
    add("  Name             : %s" % scope.get("view_label", scope.get("view", "")))
    add("  Columns in file  : %s" % ", ".join(scope.get("columns") or []))
    if "view_column_count" in scope:
        add("  View columns     : %s" % format(scope["view_column_count"], ","))
        add("  Column total     : %s" % column_arithmetic(scope))
        entry = scope.get("canonical_entry_count",
                          scope.get("canonical_column_count", 0))
        own = scope.get("canonical_own_count", 0)
        if entry:
            add("  Canonical fields : %s (the full ENTRY_FIELDS export "
                "schema, in schema order, minus the %s fields this view "
                "already shows; the same fixed column set every engine "
                "export writes. A blank cell means that record does not "
                "carry the field. Raw FILETIMEs, ids and carve provenance "
                "included.)" % (format(entry, ","),
                                format(scope.get("canonical_shown_count", 0),
                                       ",")))
        if own:
            add("  Record fields    : %s (every field these records' own "
                "source rows carry, in first-seen order, minus any this "
                "view already shows as that same field. Cookies, HSTS "
                "pins, certificates and containers are not URL-cache "
                "entries, so the ENTRY_FIELDS schema does not apply to "
                "them. A blank cell means that record does not carry the "
                "field. Raw FILETIMEs and ids included.)"
                % format(own, ","))
        if not entry and not own:
            if scope.get("rows_are_aggregates", True):
                add("  Canonical fields : none (the rows in this view are "
                    "aggregates, not single records, so no per-record "
                    "fields apply)")
            else:
                add("  Canonical fields : none (the rows in this view are "
                    "not single parsed records, so no per-record fields "
                    "apply)")
    hidden = scope.get("hidden_columns") or []
    add("  Hidden on screen but PRESENT in this file: %s"
        % (", ".join(hidden) if hidden else "none"))
    add("  %s in file       : %s" % (unit.capitalize(),
                                     format(scope.get("rows_in_file", 0), ",")))
    add("  Rows in view     : %s" % format(scope.get("rows_in_view", 0), ","))
    add("  Rows in record set: %s"
        % format(scope.get("rows_in_record_set", 0), ","))
    if unit != "rows":
        add("  NOTE: the unit of this file is %s, not records. The two "
            "counts above are not the same number and must not be read as "
            "one." % unit)
    add("")
    add("SCOPE")
    if scope.get("is_subset"):
        add("  THIS IS A FILTERED SUBSET, NOT THE WHOLE VIEW.")
        if scope.get("text_filter"):
            add("  Search text      : %s" % scope["text_filter"])
        for key, described in (scope.get("conditions") or {}).items():
            add("  Column condition : %s %s" % (key, described))
        for key, values in (scope.get("values") or {}).items():
            # Every value: this line is how the subset is reproduced, and
            # a "+N more" tail cannot be.
            add("  Value filter     : %s = %s"
                % (key, ", ".join(str(v) for v in values)))
        if scope.get("text_filter") or scope.get("conditions"):
            # A condition's own words may not appear in the file: "tax
            # docs" matched an address stored as "Tax%20docs". Stated so
            # the subset can be reproduced from the file alone.
            add("  Text matching    : a value also matched by its decoded "
                "spelling -- percent-escapes decoded, a '+' in a query read "
                "as a space, a file: address read as its Windows path. This "
                "file holds the values as stored.")
        if scope.get("chip_text"):
            add("  As shown on screen: %s" % scope["chip_text"])
        excluded = max(0, scope.get("rows_in_record_set", 0)
                       - scope.get("rows_in_view", 0))
        add("  Rows excluded    : %s" % format(excluded, ","))
        add("  Re-run with filters cleared for the whole view.")
    else:
        add("  No filter was in force. This file is the whole view.")
    # Written only when present, so no other view's sidecar changes. A hit
    # list needs the keyword that produced it and the extent read, and
    # write_view_provenance writes a fixed key set.
    if scope.get("search_keyword"):
        add("")
        add("SEARCH")
        add("  Keyword          : %s" % scope["search_keyword"])
        add("  Scope            : %s" % scope.get("search_scope_label", ""))
        add("  Tables searched  : %s"
            % format(scope.get("tables_searched", 0), ","))
        add("  Rows scanned     : %s"
            % format(scope.get("rows_scanned", 0), ","))
        skipped = scope.get("tables_skipped") or []
        add("  Tables NOT read  : %s"
            % (", ".join(str(name) for name in skipped) if skipped else "none"))
        if scope.get("searched_row"):
            add("  Row in this file : %s" % scope["searched_row"])
        add("  This file lists hits in what the database stored. A "
            "keyword's absence here is not evidence the thing never "
            "happened.")
    add("")
    add("ORIGIN")
    add("  %s live, %s carved in this file."
        % (format(scope.get("live_rows", 0), ","),
           format(scope.get("carved_rows", 0), ",")))
    add("  Recovery scan run for this exhibit: %s"
        % ("yes" if scope.get("recovery_scan_run") else
           "NO — deleted records have not been carved, so nothing here can "
           "be read as covering them"))
    add("")
    add("TIMESTAMPS")
    add("  UTC timestamps are written as YYYY-MM-DD HH:MM:SS[.ffffff] (a date "
        "cell in XLSX); the RFC 3339 form of each is in its *_rfc column. "
        "Any column labelled LOCAL is the examined machine's own clock as "
        "the database stored it, not a conversion.")
    add("")
    add("TEXT ENCODING")
    add("  Binary values are written as uppercase hex. NUL, other control "
        "characters, lone surrogates and the noncharacters U+FFFE/U+FFFF "
        "cannot be stored in CSV or XLSX, so each is written as a visible "
        "escape (\\x00, \\x07, \\uD800, \\uFFFE) and "
        "nothing is dropped; a literal backslash in the evidence is not "
        "escaped. NaN and infinity are written as the text nan, inf and "
        "-inf.")
    if caution:
        add("")
        add("CAUTION")
        add("  %s value(s) in this file begin with =, +, - or @ and Excel "
            "will evaluate them as formulas. They were not altered: "
            "changing a stored value to make a spreadsheet behave would be "
            "evidence tampering." % format(caution, ","))
    try:
        # utf-8-sig, matching the CSV beside it: the sidecar contains
        # non-ASCII text (an em dash on its first line, and any URL or
        # value it quotes), and a BOM-less UTF-8 file can be misread by
        # programs that guess the encoding.
        with forensic_engine.atomic_write(side, newline="\n",
                                          encoding="utf-8-sig") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        return ""
    return side


# --- the bundle manifest ------------------------------------------------

#: Case fields the EXAMINER types. Never reinterpreted, even when the
#: text happens to look like JSON.
_CASE_FREE_TEXT = frozenset(("examiner", "case_number", "evidence_id",
                             "notes"))


def _case_for_manifest(case_meta):
    """The case record with every machine-kept field that the case file
    stores as JSON text (the evidence-opened log, among others) decoded
    to the structure it holds, so the manifest is read once, not twice."""
    case = {}
    for key, value in dict(case_meta or {}).items():
        if (key not in _CASE_FREE_TEXT and isinstance(value, str)
                and value.lstrip()[:1] in ("[", "{")):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        case[key] = value
    return case


def _csv_formula_values(path):
    """How many cells of a written CSV begin with a character Excel
    treats as the start of a formula. Read back from the file itself, so
    the count describes what is on disk. A cell that reads as a number
    ("-5") is not counted: Excel reads it as the number it is."""
    count = 0
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                for cell in row:
                    if cell[:1] in _FORMULA_LEAD and len(cell) > 1:
                        try:
                            float(cell)
                        except ValueError:
                            count += 1
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    return count


def finalise_bundle_manifest(out_dir, job, files, cancelled):
    """Rewrite 00_MANIFEST.json with what the engine's manifest does not
    carry. Returns the manifest's path.

    tool_version: provenance.TOOL_VERSION, the string the status bar shows.
    evidence: every file with its opening SHA-256 and size, plus
      EvidenceSet.verify() re-run at export time, so a bundle from an
      exhibit that changed says so.
    formats: one entry per member attempted, with status and reason (a PDF
      absent because reportlab is missing is listed with that reason).
    cancelled: true/false, with "not attempted (cancelled)" for every
      member that did not run, so an incomplete folder says so.
    """
    manifest_path = os.path.join(out_dir, MANIFEST_NAME)
    evidence_set = getattr(job, "evidence_set", None)
    evidence = []
    for path in list(getattr(evidence_set, "files", None) or []):
        evidence.append({
            "path": path,
            "sha256_at_open": (getattr(evidence_set, "hashes", {}) or {}).get(path, ""),
            "size_bytes": (getattr(evidence_set, "sizes", {}) or {}).get(path, 0),
        })
    changed = []
    if evidence_set is not None and hasattr(evidence_set, "verify"):
        try:
            changed = list(evidence_set.verify())
        except Exception as exc:            # pragma: no cover - defensive
            changed = ["verification could not run: %s" % exc]

    on_disk = {}
    try:
        for name in sorted(os.listdir(out_dir)):
            full = os.path.join(out_dir, name)
            if os.path.isfile(full) and name != MANIFEST_NAME:
                on_disk[name] = full
    except OSError:
        pass

    # Each member states its own scope, so a
    # reader comparing two files' row counts finds the reason here rather
    # than a silent disagreement. Every current member includes carved
    # records (BUNDLE_KEYS_WITHOUT_RECOVERED is empty).
    carved_total = len(getattr(job, "recovered", None) or [])
    formula_total = 0
    entries = []
    for name, label, status, reason in (files or []):
        item = {"name": label, "file": name, "status": status,
                "reason": reason}
        key = _BUNDLE_FILENAME_TO_KEY.get(name)
        if key is not None:
            includes = key not in BUNDLE_KEYS_WITHOUT_RECOVERED
            item["includes_recovered_records"] = includes
            if not includes and carved_total:
                item["carved_records_excluded"] = carved_total
        full = on_disk.get(name)
        if full is not None:
            try:
                item["bytes"] = os.path.getsize(full)
                item["sha256"] = _sha256_of(full)
            except OSError:
                pass
            if name.lower().endswith(".csv"):
                formulas = _csv_formula_values(full)
                if formulas is not None:
                    item["values_starting_with_formula_character"] = formulas
                    formula_total += formulas
        entries.append(item)

    listed = {item["file"] for item in entries}
    companions = []
    for name, full in on_disk.items():
        if name in listed:
            continue
        try:
            companions.append({"name": name, "bytes": os.path.getsize(full),
                               "sha256": _sha256_of(full)})
        except OSError:
            continue

    manifest = {
        "tool_version": provenance.TOOL_VERSION,
        "manifest_scope": ("Every file in this directory except the manifest "
                           "itself, enumerated from disk after all exports "
                           "finished or were cancelled."),
        "written_utc": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cancelled": bool(cancelled),
        "case": _case_for_manifest(getattr(job, "case_meta", None)),
        "evidence": evidence,
        "evidence_changed_since_opening": changed,
        "scope": {
            "live_entries": len(getattr(job, "entries", None) or []),
            "carved_records": len(getattr(job, "recovered", None) or []),
            "recovery_scan_run": bool(
                (getattr(job, "scope", None) or {}).get("recovery_scan_run")),
            "cookies": len((getattr(job, "artifacts", None) or {}).get("cookies", [])),
            "hsts": len((getattr(job, "artifacts", None) or {}).get("hsts", [])),
            "certs": len((getattr(job, "artifacts", None) or {}).get("certs", [])),
            "leaks": len((getattr(job, "artifacts", None) or {}).get("leaks", [])),
        },
        "formats": entries,
        "companion_files": companions,
    }
    if formula_total:
        # The same sentence the view CSV's provenance sidecar carries.
        manifest["caution"] = (
            "%s value(s) in this bundle's CSV files begin with =, +, - or @ "
            "and Excel will evaluate them as formulas. They were not "
            "altered: changing a stored value to make a spreadsheet behave "
            "would be evidence tampering. Each CSV's count is its "
            "values_starting_with_formula_character." % format(
                formula_total, ","))
    with forensic_engine.atomic_write(manifest_path, encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, default=str)
    return manifest_path


# --- what produced a screen ---------------------------------------------

def scope_from_view(view, key, label, model):
    """Everything the sidecar has to state about ONE screen.

    Reads a view duck-typed -- `.table`, and `.filter_box` when it has one
    -- so RecoveryView works without becoming a RecordsView, and so this
    module stays Qt-free and testable with plain stand-ins.

    provenance.view_state()/export_stamp() -- the two functions ten
    modules import and nothing has ever called -- build the OTHER half of
    the record (tool version, evidence hashes, exported time). This is the
    half they cannot: which columns, which filters, and how much of the
    record set is missing from the file.

    `is_subset` compares the visible count against the RECORD SET's total,
    not against the model's own row count, because those are the same
    number: what makes an export a subset is that rows the record set
    holds are not in it.
    """
    columns = list(getattr(model, "columns", []) or [])
    cols = {c.key: c for c in columns}
    rows = list(model.filter.visible())
    canon = canonical_columns_for(rows, columns)
    live = sum(1 for r in rows if origin_cell(r) == _LIVE_CELL)
    carved = sum(1 for r in rows
                 if origin_cell(r) == provenance.CARVED_ORIGIN)
    total = model.filter.total_count
    shown = model.rowCount()
    values = {}
    for value_key in list(getattr(model.filter, "_values", {}) or {}):
        allowed = model.filter.allowed_values(value_key) or set()
        # NOT sliced here: write_view_
        # provenance lists every value, and this full,
        # untruncated set is the only copy of the filter that exists
        # anywhere in this scope dict.
        column = cols.get(value_key)
        label = column.label if column is not None else model.filter.label_for(value_key)
        values[label] = sorted(display_text(v, column) or blank_label(column)
                               for v in allowed)
    conditions = {}
    for cond_key in list(getattr(model.filter, "_conditions", {}) or {}):
        condition = model.filter.condition_for(cond_key)
        if condition is not None:
            conditions[cols[cond_key].label if cond_key in cols else model.filter.label_for(cond_key)] = condition.describe(cols.get(cond_key))
    box = getattr(view, "filter_box", None)
    return {
        "view": key,
        "view_label": label,
        # Includes the appended columns write_view_csv writes, computed
        # with the same appended_columns_for(), so "Columns in file" names
        # every column the file has.
        "columns": ([col.label for col in columns]
                    + appended_columns_for(columns)
                    + [header for _key, header in canon]),
        "view_column_count": len(columns) + len(appended_columns_for(columns)),
        **canonical_counts(rows, columns, canon),
        "column_keys": [col.key for col in columns],
        "hidden_columns": [col.label for i, col in enumerate(columns)
                           if col.hidden or (getattr(view, "table", None)
                                             is not None and
                                             view.table.isColumnHidden(i))],
        "rows_in_file": shown,
        "rows_in_view": shown,
        "rows_in_record_set": total,
        "text_filter": box.text() if box is not None else "",
        "chip_text": model.chip_text(),
        "conditions": conditions,
        "values": values,
        "is_subset": shown != total,
        "live_rows": live,
        "carved_rows": carved,
        "unit": "rows",
    }
