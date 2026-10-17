"""The offline HTML report: one self-contained file that a reviewer opens in
any browser with nothing installed.

Qt-free. Three layers, top to bottom of this file:
  1. the cell encoding -- ONE stored form per cell, exactly what
     export_formats.write_view_csv writes for it, plus three tags for the
     facts the CSV text alone would lose;
  2. the snapshot data classes and build_island();
  3. the page renderer and write_package().

WHY THE CSV FORM. The page shows, filters, sorts and exports every cell.
Stored as the CSV text, the page's CSV is the app's CSV by construction;
the grid's text, the search text, the sort key and the XLSX cell are each
derived from it in the page by a JavaScript copy of the Python function
that derives them in the app (column_spec.display_text / searchable_text,
record_filter._sort_key, forensic_engine.xlsx_cell_parts), and a parity
test holds each copy to its original.
"""
import base64
import collections
import copy
import datetime
import hashlib
import json
import os
import pathlib
import sys

from .. import provenance
from ..engine import forensic_engine
from . import (detail_fields, export_formats, record_kinds, recovered_search,
               timeline_loader)

#: The island's schema id. Changed only by a change a reader of an older
#: file would misread.
SCHEMA = "webcache-offline-report/1"

#: A cell that was a datetime OBJECT. The text after it is what the CSV
#: writes (str(value), e.g. "2026-02-17 16:50:09.123456+00:00"); the XLSX
#: writer makes a date cell of its wall-clock digits, as xlsx_cell_parts
#: does for a real datetime in a timestamp column.
TAG_DATETIME = "\x01"
#: An int beyond 2**53, which a JavaScript number cannot hold exactly.
#: xlsx_cell_parts writes it as text for the same reason.
TAG_BIGINT = "\x02"
#: A float, kept in Python's own spelling ("1.0", "1e-05") so the page's
#: CSV says what the app's does.
TAG_FLOAT = "\x03"
#: A bytes value: the text after it is uppercase hex, as every app writer
#: spells bytes.
TAG_BYTES = ""
TAGS = (TAG_DATETIME, TAG_BIGINT, TAG_FLOAT, TAG_BYTES)
MAX_SAFE_INT = 2 ** 53


def encode_cell(value, is_timestamp=False):
    """One cell as the island stores it. See the module docstring.

    Control characters cannot occur in a stored string: export_formats.
    _clean runs every string through forensic_engine._safe_text, which
    writes \\x00-\\x08 as a visible \\xNN escape -- so a leading tag cannot be
    confused with evidence text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return value if abs(value) <= MAX_SAFE_INT else TAG_BIGINT + str(value)
    if isinstance(value, float):
        # nan / inf / -inf are text tokens after the tag, as in every writer.
        return TAG_FLOAT + repr(value)
    if isinstance(value, (bytes, bytearray)):
        return TAG_BYTES + export_formats._clean(value)
    if isinstance(value, datetime.datetime) and is_timestamp:
        # A date cell only in a timestamp column -- xlsx_cell_parts' rule.
        return TAG_DATETIME + export_formats._clean(value, is_timestamp=True)
    cleaned = export_formats._clean(value, is_timestamp=is_timestamp)
    if cleaned is None or cleaned == "":
        return None
    return cleaned if isinstance(cleaned, str) else str(cleaned)


def view_cells(row, columns, appended, flags):
    """The view part of one row's export -- the view's own columns, then
    the appended Origin/RecordSource -- encoded. `flags` may be the whole
    layout's flag list; only its leading entries are read."""
    raw = export_formats._view_cells(row, columns, appended, [], None, None)
    out = []
    append = out.append
    safe = forensic_engine._safe_text
    shape = forensic_engine.excel_datetime
    # encode_cell's own result, by the short paths canonical_cells takes
    # (see there): None, a safe int, and a str -- printable, it is its
    # own _safe_text.
    for value, stamp in zip(raw, flags):
        kind = type(value)
        if value is None:
            append(None)
        elif kind is str:
            if not value:
                append(None)
                continue
            if not value.isprintable():
                value = safe(value)
            append(shape(value) if stamp else value)
        elif kind is int and -MAX_SAFE_INT <= value <= MAX_SAFE_INT:
            append(value)
        else:
            append(encode_cell(value, stamp))
    return out


def canonical_cells(record, carved, tags_map=None, comments_map=None):
    """All 80 ENTRY_FIELDS of one record, in schema order, exactly as
    _view_cells writes them: canonical_record_row, then _cell, then the
    timestamp-only date shape. `carved` is what _view_cells passes --
    origin_cell(row) == CARVED_ORIGIN -- so the same record reads the same
    in the page as in every app export.

    Three short paths give the identical result for the commonest values,
    because this runs 80 times per record: None is a blank cell; an int a
    JavaScript number holds exactly is itself (what _cell then
    encode_cell make of it); and a str is _safe_text(str) -- which is all
    _cell does to one, and running it a second time inside _clean changes
    nothing -- then the date shape if the column is a timestamp. A str
    that is all printable IS its own _safe_text: _safe_text rewrites only
    control characters and lone surrogates, and neither is printable."""
    full = forensic_engine.canonical_record_row(
        record, carved=True if carved else None, tags_map=tags_map,
        comments_map=comments_map)
    get = full.get
    safe = forensic_engine._safe_text
    shape = forensic_engine.excel_datetime
    cell = forensic_engine._cell
    out = []
    append = out.append
    for key, stamp in _CANONICAL_PLAN:
        raw = get(key)
        if raw is None:
            append(None)
            continue
        kind = type(raw)
        if kind is str:
            if not raw:
                append(None)
                continue
            value = raw if raw.isprintable() else safe(raw)
            append(shape(value) if stamp else value)
        elif kind is int and -MAX_SAFE_INT <= raw <= MAX_SAFE_INT:
            append(raw)
        else:
            append(encode_cell(cell(raw), stamp))
    return out


#: (canonical key, is a timestamp column), in schema order.
_CANONICAL_PLAN = tuple((key, key in forensic_engine.TIMESTAMP_EXPORT_KEYS)
                        for key in forensic_engine.ENTRY_FIELD_KEYS)


def own_cells(record):
    """Every key a cookie / HSTS pin / certificate / container record
    carries, in its own order -- export_formats.OWN_FIELD_KINDS' block."""
    return {str(key): encode_cell(forensic_engine._cell(value), False)
            for key, value in record.items()}

_CANONICAL_KEYS = frozenset(forensic_engine.ENTRY_FIELD_KEYS)


def absence_words(row):
    """{canonical key: absence token} for every field of `row` that the
    app's record dialog (detail_fields.fields_for) words as absent. Only
    canonical keys: the island stores words for canonical cells alone."""
    return {f.key: f.absence for group in detail_fields.fields_for(row)
            for f in group.fields if f.absence and f.key in _CANONICAL_KEYS}


def _absence_class(value):
    """Everything detail_fields reads of one value when it decides an
    absence word: a stated absence token as itself; otherwise the value's
    type, whether it is len()-empty, whether a string is blank once
    stripped (a note), its truthiness (ModifiedTime_raw, MSHistFrom), and
    the same facts for each item of a list or each entry of a dict (the
    sweep words each item). Never the text of a present value.

    The exact types str and int are answered first: they are nearly every
    value, and a subclass of either takes the general path below."""
    kind = type(value)
    if kind is str:
        if value in _ABSENCE_TOKENS:
            return ("T", value)
        if value.strip():
            return _TEXT
        return _BLANK if value else _EMPTY
    if kind is int:
        return _NONZERO if value else _ZERO
    if value is None:
        return 0
    if isinstance(value, str):
        if provenance.is_absence(value):
            return ("T", str(value))
        return ("S", len(value) > 0, bool(value.strip()))
    if isinstance(value, (bytes, bytearray)):
        return ("B", len(value) > 0)
    if isinstance(value, (list, tuple)):
        return ("L", tuple(_absence_class(item) for item in value))
    if isinstance(value, dict):
        return ("D", tuple((str(name), _absence_class(value[name]))
                           for name in sorted(value, key=str)))
    return (kind.__name__, bool(value))


_ABSENCE_TOKENS = frozenset(provenance.ABSENCE_TOKENS)
_TEXT = ("S", True, True)
_BLANK = ("S", True, False)
_EMPTY = ("S", False, False)
_NONZERO = ("int", True)
_ZERO = ("int", False)


def absence_signature(row):
    """A hashable key such that two rows with the same key get the same
    absence_words(), or None where that is not established (an aggregate,
    whose dialog lists its members; a key that is not a string).

    What detail_fields.fields_for reads to decide a canonical field's word
    (canonical keys are the only words the island keeps):
      - the row's kind, and whether its Origin says Carved;
      - which keys the merged record+row namespace holds (presence decides
        whether a field is emitted, its paired _raw whether a carve
        expected it, FixTimeFormat the fix fields);
      - each value's _absence_class (the token, None, len()-empty; the
        sweep's per-item words; the truthiness local_clock reads);
      - UrlHealth's own text (it reorders the dialog's groups).
    The words of declared fields come from _absence_for(carved, key,
    present, value); swept keys the same per value or item; flattened
    SPS, header, fragment and directory fields carry non-canonical keys.
    tests/test_html_package_island.py checks that memoised words equal
    absence_words() for every row of its corpus."""
    kind = row.get("_kind")
    if kind in record_kinds.AGGREGATES:
        return None
    source = detail_fields._merged_source(row)
    if not all(type(key) is str for key in source):
        return None
    items = tuple([(key, _absence_class(value))
                   for key, value in sorted(source.items())])
    health = source.get("UrlHealth")
    return (kind, str(row.get("Origin") or "").startswith("Carved"),
            health if isinstance(health, str) else None, items)


# --- the snapshot ------------------------------------------------------------

_NUMERIC_KINDS = ("num", "count", "size", "offset")
_TIME_KINDS = ("time", "time_local")


class PackageColumn:
    """A view column as the page needs it: no callbacks, no Qt. Duck-types
    widgets.column_spec.Column for every attribute export_formats reads
    (key, label, kind, numeric, field, hidden)."""
    __slots__ = ("key", "label", "kind", "numeric", "field", "badge",
                 "badge_tooltip", "note", "optional", "width", "sort_by",
                 "copies", "basis_key", "hidden", "multi", "multi_source",
                 "blank_text")

    def __init__(self, key, label=None, kind="text", field=None, badge=None,
                 badge_tooltip=None, note=None, optional=False, width=None,
                 sort_by=None, copies=False, basis_key=None, multi=False,
                 multi_source=None, blank_text=None):
        self.key = key
        self.label = key if label is None else label
        self.kind = kind
        self.numeric = kind in _NUMERIC_KINDS
        self.field = field
        self.badge = badge
        self.badge_tooltip = badge_tooltip
        self.note = note
        self.optional = bool(optional)
        self.width = width
        self.sort_by = sort_by
        self.copies = bool(copies)
        self.basis_key = basis_key
        self.hidden = self.optional
        #: column_spec.Column.multi / multi_source: the value picker offers
        #: each individual value of a joined cell (see record_filter).
        self.multi = bool(multi)
        self.multi_source = multi_source if self.multi else None
        #: column_spec.Column.blank_text: what an empty cell means here.
        self.blank_text = blank_text

    @classmethod
    def from_column(cls, col):
        return cls(col.key, col.label, col.kind, col.field,
                   getattr(col, "badge", None),
                   getattr(col, "badge_tooltip", None),
                   getattr(col, "note", None),
                   getattr(col, "optional", False),
                   getattr(col, "width", None),
                   getattr(col, "sort_by", None),
                   bool(getattr(col, "on_click", None) is not None
                        and getattr(col, "on_click_copies", False)),
                   getattr(col, "basis_key", None),
                   getattr(col, "multi", False),
                   getattr(col, "multi_source", None),
                   getattr(col, "blank_text", None))

    def to_json(self):
        return {"k": str(self.key), "l": str(self.label), "kind": self.kind,
                "num": self.numeric, "field": self.field, "badge": self.badge,
                "tip": self.badge_tooltip, "note": self.note,
                "opt": self.optional, "w": self.width, "copies": self.copies,
                "multi": self.multi, "blank": self.blank_text}


class PackageSegment:
    """One record set. `rows` are the app's own row dicts, by reference,
    read-only. `factory` (Timeline periods, raw tables) defers the rows to
    the export worker: factory() -> (columns or None, rows, note)."""
    __slots__ = ("key", "label", "columns", "rows", "noun", "subtitle",
                 "caveat", "empty_text", "note", "default_sort", "quick",
                 "clock", "group", "factory", "cap")

    def __init__(self, key, label, columns, rows=None, noun="records",
                 subtitle="", caveat="", empty_text="", note="",
                 default_sort=None, quick=(), clock="", group="",
                 factory=None, cap=None):
        self.key = key
        self.label = label
        self.columns = list(columns or ())
        self.rows = rows
        self.noun = noun
        self.subtitle = subtitle
        self.caveat = caveat
        self.empty_text = empty_text
        self.note = note
        self.default_sort = default_sort
        self.quick = list(quick or ())
        self.clock = clock
        self.group = group
        self.factory = factory
        #: Most lines a wrapped row shows (records_table.set_line_cap);
        #: None: the page's default, records_table.ROW_LINE_CAP.
        self.cap = cap

    def resolve(self):
        if self.factory is None:
            return self.columns, list(self.rows or ()), self.note
        columns, rows, note = self.factory()
        return (list(columns) if columns is not None else self.columns,
                list(rows or ()), note if note is not None else self.note)


class PackageView:
    __slots__ = ("key", "label", "section", "caption", "segments", "picker",
                 "initial", "badge", "unit")

    def __init__(self, key, label, section, caption, segments,
                 picker="buttons", initial=None, badge=None, unit=None):
        self.key = key
        self.label = label
        self.section = section
        self.caption = caption
        self.segments = list(segments)
        self.picker = picker
        self.initial = initial
        #: The app sidebar's own badge for this view (Sidebar.count_of).
        self.badge = badge
        self.unit = unit


class PackageSnapshot:
    __slots__ = ("views", "meta", "summary", "integrity", "scope", "basis",
                 "member_columns", "tags_map", "comments_map")

    def __init__(self, views, meta, summary=(), integrity=None, scope=(),
                 basis=(), member_columns=(), tags_map=None,
                 comments_map=None):
        self.views = list(views)
        self.meta = dict(meta or {})
        self.summary = list(summary or ())
        self.integrity = integrity or {"hashes": [], "source": [], "log": []}
        self.scope = list(scope or ())
        self.basis = list(basis or ())
        self.member_columns = list(member_columns or ())
        self.tags_map = tags_map
        self.comments_map = comments_map


# --- the island ----------------------------------------------------------------

def _summary_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return format(value, ",")
    return str(value)


class _IslandBuilder:
    """A record's canonical cells are stored once; what the dialog says
    for a row is stored on the row.

    Records are de-duplicated by (identity, block, carved): the block
    decides which field set a row exports (export_formats._block_of) and
    the carved flag is what _view_cells passes canonical_record_row, the
    only inputs the stored cells depend on.

    The header (identity, origin, twin and provenance strip: what the
    app's dialog says for the row clicked, _head) goes in the island's
    `heads` table, de-duplicated by value, and each row points at its own
    through the segment's `hd` list beside `rec`. Two rows over one record
    share its cells and keep their own words.

    Identity is id(record), so every record keyed is held in `_keep` for
    the builder's lifetime: a factory segment's rows are freed once the
    segment is built, and CPython could give the next segment's records
    the same ids."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.records = []
        self.heads = []
        self._index = {}
        self._keep = {}
        self._head_index = {}
        self._absence_memo = {}
        self.evidence = []
        self._evidence_index = {}

    def evidence_ref(self, row):
        """The index in `ev` of what Search reads from this row, or -1.

        A recovered record (a kind in recovered_search.SEARCHED_FIELDS) is
        searched in the fields read from its carved bytes and nothing
        else -- the app's own rule (search_loader.recovered_hits), so a
        label this tool wrote (Origin, Method, Confidence...) is never a
        hit. Every other row is searched as its grid shows it."""
        kind = row.get("_kind")
        if kind not in recovered_search.SEARCHED_FIELDS:
            return -1
        record = row.get("_record") or {}
        key = (id(record), kind)
        index = self._evidence_index.get(key)
        if index is None:
            self._keep[id(record)] = record
            index = self._evidence_index[key] = len(self.evidence)
            self.evidence.append(_evidence_fields(row))
        return index

    def ref(self, record, block, carved, member=False, row=None):
        key = (id(record), block, bool(carved))
        index = self._index.get(key)
        if index is None:
            self._keep[id(record)] = record
            index = self._index[key] = len(self.records)
            self.records.append(self._record_entry(record, block, carved,
                                                   row))
        entry = self.records[index]
        if member and "m" not in entry:
            entry["m"] = self._member_cells(record)
            # A member has no row: row_for_record is its row, as when the
            # app opens one.
            entry["mh"] = self.head(record, None)
        return index

    def head(self, record, row):
        """The index in `heads` of what the dialog says for this row."""
        identity, origin, twin, facts = self._head(record, row)
        kind = self._kind(record, row)
        key = (identity, origin, twin, facts, kind)
        index = self._head_index.get(key)
        if index is None:
            index = self._head_index[key] = len(self.heads)
            self.heads.append({"i": identity, "o": origin, "t": twin,
                               "p": [[label, value]
                                     for label, value in facts],
                               "k": kind})
        return index

    @staticmethod
    def _kind(record, row):
        """What the dialog's chip is decided from: "stub" (a deleted-record
        stub), "carved", "live", or "other" (a record that is not a
        URL-cache entry: cookie, HSTS pin, certificate, container...). Read
        from the row's kind and origin, as the app's own dialog reads them,
        never from the words of its title."""
        shown = row if row is not None else detail_fields.row_for_record(record)
        kind = shown.get("_kind")
        if kind == record_kinds.K_TOMBSTONE:
            return "stub"
        if (str(shown.get("Origin") or "").startswith("Carved")
                or kind in (record_kinds.K_CARVED_STRUCT,
                            record_kinds.K_CARVED_STRING)):
            return "carved"
        if export_formats._block_of(shown) != "entry":
            return "other"
        return "live"

    @staticmethod
    def _head(record, row):
        """The record dialog's header for this row: what the app's own
        dialog says for the row clicked. Kept per row, so two rows over
        one record each state their own words -- never the first row's
        words for the second row. row_for_record(record) alone would not
        do: it drops what a row builder states about its record (a stub's
        composed Key and Method, a cookie's kind, a table row's origin
        sentence). A member has no row, so row_for_record is its row, as
        when the app opens one."""
        shown = row if row is not None else detail_fields.row_for_record(record)
        return (detail_fields.identity_of(shown),
                detail_fields.origin_line(shown),
                detail_fields.twin_line(shown),
                tuple((str(label), str(value)) for label, value
                      in detail_fields.provenance_facts(shown)))

    def _record_entry(self, record, block, carved, row=None):
        if block == "own":
            return {"own": own_cells(record)}
        cells = canonical_cells(record, carved, self.snapshot.tags_map,
                                self.snapshot.comments_map)
        entry = {"c": cells}
        said = self._absence_said(record, row)
        blank = {str(i): said[key]
                 for i, key in enumerate(forensic_engine.ENTRY_FIELD_KEYS)
                 if cells[i] is None and key in said}
        if blank:
            entry["a"] = blank
        return entry

    def _absence_said(self, record, row):
        """{canonical key: absence token}: what the app's dialog says for
        each canonical field of this row that holds no value ("(empty)",
        "(not recovered)", "(not supplied)"...). A canonical field the
        dialog does not show at all is worded by the page as
        "(not applicable)" (island `na`).

        Computed once per distinct absence_signature: the words depend on
        the row's shape, never on the text of a present value, and building
        the whole dialog per row would dominate the cost."""
        shown = row if row is not None else detail_fields.row_for_record(record)
        signature = absence_signature(shown)
        if signature is None:
            return absence_words(shown)
        said = self._absence_memo.get(signature)
        if said is None:
            said = self._absence_memo[signature] = absence_words(shown)
        return said

    def _member_cells(self, record):
        rows = timeline_loader.member_record_rows([record])
        row = rows[0] if rows else {}
        return [encode_cell(row.get(c.key), c.kind in _TIME_KINDS)
                for c in self.snapshot.member_columns]

    @staticmethod
    def _member_record(member):
        """(record, block, carved) for one aggregate member. A Location
        place's members are position fixes, shaped rows with the engine
        record behind them as _record, and the member table shows that
        record. Raw engine dicts (Timeline, Domains) pass through
        unchanged."""
        record = member.get("_record")
        if "_kind" in member and isinstance(record, dict):
            member = record
        return member, "entry", provenance.is_carved_entry(member)

    def segment(self, seg):
        columns, rows, note = seg.resolve()
        headers, flags, appended, canon = export_formats.view_layout(
            rows, columns)
        counts = export_formats.canonical_counts(rows, columns, canon)
        view_width = len(columns) + len(appended)
        # origins[] is the export's Origin cell; ol[] beside it is the
        # word the app's leading origin column shows for that row (Live,
        # Carved, Mixed, Recovered only, or a dash). One export cell can
        # stand for two words (an aggregate kind without members), so the
        # pair is the key.
        origins, olabels, origin_at = [], [], {}
        out_rows, rec, hd, mem, org, ev = [], [], [], [], [], []
        any_members = False
        noun = None
        for row in rows:
            ev.append(self.evidence_ref(row))
            out_rows.append(view_cells(row, columns, appended,
                                       flags[:view_width]))
            origin = export_formats.origin_cell(row)
            pair = (origin, provenance.row_origin_label(row))
            if pair not in origin_at:
                origin_at[pair] = len(origins)
                origins.append(origin)
                olabels.append(pair[1])
            org.append(origin_at[pair])
            block = export_formats._block_of(row)
            if block is None:
                rec.append(-1)
                hd.append(-1)
            else:
                record = export_formats._record_of(row)
                rec.append(self.ref(record, block,
                                    origin == provenance.CARVED_ORIGIN,
                                    row=row))
                hd.append(self.head(record, row))
            members = provenance.aggregate_members(row)
            if members is None:
                mem.append(None)
            else:
                any_members = True
                mem.append([self.ref(*self._member_record(m), member=True)
                            for m in members if isinstance(m, dict)])
                noun = noun or detail_fields.AGGREGATE_NOUN.get(row.get("_kind"))
        # A chip may read a row field the grid does not show (History's
        # IsLocalFile, SearchTerms; HTTP Headers' StatusClass): its values
        # ride along, keyed by field, so every value/condition chip works.
        shown = {c.key for c in columns}
        qv = {}
        for q in seg.quick:
            key = q.get("key")
            if key and not q.get("skipped") and key not in shown                     and key not in qv:
                qv[key] = [encode_cell(r.get(key)) for r in rows]
        # A multi column whose joined text cannot be re-split safely
        # carries the loader's own pre-split list (Column.multi_source).
        mv = {}
        for i, col in enumerate(columns):
            source = getattr(col, "multi_source", None)
            if getattr(col, "multi", False) and source:
                mv[str(i)] = [None if r.get(source) is None else
                              [encode_cell(v) for v in r.get(source)]
                              for r in rows]
        # "One row per visit": each row's own visit key, and for an MSHist
        # record the key of its History twin -- views/record_chips.
        # hide_shown_twins' rule, applied in the page.
        tw = None
        if any(q.get("twins") for q in seg.quick):
            tw = [_visit_keys(r) for r in rows]
        sortv = {}
        for i, col in enumerate(columns):
            if col.sort_by:
                sortv[str(i)] = [encode_cell(r.get(col.sort_by)) for r in rows]
        sort = None
        if seg.default_sort:
            key, desc = seg.default_sort
            for i, col in enumerate(columns):
                if col.key == key:
                    sort = [i, bool(desc)]
                    break
        keys = forensic_engine.ENTRY_FIELD_KEYS
        subtitle = (seg.subtitle(len(rows)) if callable(seg.subtitle)
                    else seg.subtitle or "")
        return {
            "key": seg.key, "label": seg.label, "noun": seg.noun or "records",
            "subtitle": subtitle, "caveat": seg.caveat or "",
            "empty": seg.empty_text or "", "note": note or "",
            "clock": seg.clock or "", "group": seg.group or "", "sort": sort,
            "cap": seg.cap,
            "cols": [c.to_json() for c in columns], "n": len(columns),
            "rows": out_rows, "rec": rec, "hd": hd, "mem": mem if any_members else None,
            # What a member IS where it is not a record ("position fixes").
            "mn": list(noun) if noun else None,
            "org": org, "origins": origins, "ol": olabels, "sortv": sortv,
            "export": dict(
                headers=headers, ts=flags, appended=appended,
                canon=[[keys.index(k), None, h] if not isinstance(k, tuple)
                       else [None, str(k[1]), h] for k, h in canon],
                view_column_count=view_width, **counts),
            "quick": list(seg.quick), "qv": qv, "mv": mv, "tw": tw,
            "ev": ev if any(i >= 0 for i in ev) else None,
        }


def _visit_keys(row):
    """[own, twin] for "One row per visit": own is set on a non-MSHist
    record, twin on an MSHist record that has one -- as
    views/record_chips.hide_shown_twins reads them."""
    record = row.get("_record") or {}
    if not isinstance(record, dict):
        return [None, None]
    if not record.get("MSHistFrom"):
        return ["%s|%s" % (record.get("ContainerName"), record.get("EntryId")),
                None]
    twins = record.get("VisitTwin") or ()
    return [None, "%s|%s" % tuple(twins[0])[:2] if twins else None]


def _plain(text):
    """Control characters as a middle dot, as search_loader.blob_context
    shows an undecodable or control unit."""
    if text.isprintable():
        return text
    return "".join(c if c.isprintable() else "·" for c in text)


def _evidence_fields(row):
    """[[field, text, whole], ...]: recovered_search.searched_values for one
    recovered row, as text. A bytes value is kept in the two readings
    search_loader.blob_context searches -- UTF-8 and UTF-16LE -- never as
    Latin-1, so no mojibake is ever a hit."""
    out = []
    for name, value, whole in recovered_search.searched_values(row):
        if isinstance(value, (bytes, bytearray)):
            data = bytes(value)
            out.append([name, _plain(data.decode("utf-8", "replace")), 0])
            wide = _plain(data[:len(data) // 2 * 2].decode("utf-16-le",
                                                           "replace"))
            if wide:
                out.append([name, wide, 0])
        else:
            out.append([name, _plain(str(value)), 1 if whole else 0])
    return out


def build_island(snapshot, generated_utc):
    """Everything the page reads, as one JSON-ready dict."""
    builder = _IslandBuilder(snapshot)
    safe = forensic_engine._safe_json
    views = []
    for view in snapshot.views:
        views.append({"key": view.key, "label": safe(view.label),
                      "section": view.section,
                      "caption": safe(view.caption or ""),
                      "picker": view.picker, "initial": view.initial,
                      "badge": safe(view.badge), "unit": safe(view.unit),
                      "segments": [_safe_segment(builder.segment(s))
                                   for s in view.segments]})
    meta = dict(snapshot.meta)
    meta.setdefault("tool", forensic_engine.TOOL_NAME)
    meta["generated_utc"] = generated_utc
    stamps = forensic_engine.TIMESTAMP_EXPORT_KEYS
    # every string that is NOT a cell goes through
    # _safe_text, as every other writer's does -- json.dumps writes a
    # control character as a JSON escape, so island_json's own pass never
    # sees one. Cells (rows, records, qv, mv) keep their tags and already
    # passed _safe_text in encode_cell; ev keeps _plain's "·".
    return {
        "schema": SCHEMA,
        "meta": safe(meta),
        "summary": safe([[str(label), _summary_text(value)]
                         for label, value in snapshot.summary]),
        "integrity": safe(snapshot.integrity),
        "scope": safe([[heading, text] for heading, text in snapshot.scope]),
        "basis": safe([list(item) for item in snapshot.basis]),
        "na": provenance.ABSENCE_NOT_APPLICABLE,
        "fields": [[key, header, group, key in stamps]
                   for key, header, group in forensic_engine.ENTRY_FIELDS],
        "records": builder.records,
        "heads": safe(builder.heads),
        "ev": builder.evidence,
        "member_cols": safe([c.to_json() for c in snapshot.member_columns]),
        "views": views,
    }


#: A segment's strings that are never cells.
_SAFE_SEGMENT_KEYS = ("label", "noun", "subtitle", "caveat", "empty", "note",
                      "origins", "ol", "cols")


def _safe_segment(seg):
    safe = forensic_engine._safe_json
    for key in _SAFE_SEGMENT_KEYS:
        if key in seg:
            seg[key] = safe(seg[key])
    seg["export"]["headers"] = safe(seg["export"]["headers"])
    for q in seg.get("quick") or ():
        for key in ("label", "sentence", "skipped"):
            if isinstance(q.get(key), str):
                q[key] = forensic_engine._safe_text(q[key])
    return seg


# --- the stored form -----------------------------------------------------------
#
# The island is stored packed, and the page unpacks it before anything reads
# it (boot.js unpackIsland), so every reader (the grid, the dialog, both
# exporters) sees the dict build_island made. Lossless:
# unpack_island(pack_island(x)) == x here, and the browser's WC.data() equals
# build_island's dict (tests/test_html_package_boot.py). Four steps:
#   1. a string written more than once, where that is shorter, is written
#      once in the table `s` and referenced as "~" + its base-62 index;
#   2. a run of two or more nulls inside a list is "~-" + its base-62 length;
#   3. records' canonical cells and segments' rows are stored by column, so
#      a column no record fills is one run token, not one null per record;
#      a record's absence words and a head's provenance strip, repeated
#      verbatim across records, are stored once in `x` ("~*" + index) and
#      copied out for each reader;
#   4. a column's attributes equal to PackageColumn's defaults are left out
#      (its label too, when it equals its key).
# A string that itself starts with "~" is written with one more "~" in
# front. Packing keeps a large exhibit's report within its size budget.

PACK_VERSION = 1
_MARK = "~"
_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
#: PackageColumn.to_json's keys, in its order, and the defaults left out.
COLUMN_KEYS = ("k", "l", "kind", "num", "field", "badge", "tip", "note",
               "opt", "w", "copies", "multi", "blank")
COLUMN_DEFAULTS = {"kind": "text", "num": False, "field": None,
                   "badge": None, "tip": None, "note": None, "opt": False,
                   "w": None, "copies": False, "multi": False, "blank": None}


def _b62(number):
    digits = ""
    while True:
        number, rest = divmod(number, 62)
        digits = _B62[rest] + digits
        if not number:
            return digits


def _unb62(text):
    number = 0
    for ch in text:
        number = number * 62 + _B62.index(ch)
    return number


def _slim_column(col):
    if tuple(col) != COLUMN_KEYS:
        raise ValueError("a column without PackageColumn's keys: %r"
                         % (tuple(col),))
    out = {}
    for key, value in col.items():
        if key == "l":
            if type(value) is type(col["k"]) and value == col["k"]:
                continue
        elif key in COLUMN_DEFAULTS:
            default = COLUMN_DEFAULTS[key]
            if value is default or (type(value) is type(default)
                                    and value == default):
                continue
        out[key] = value
    return out


def _full_column(col):
    out = {}
    for key in COLUMN_KEYS:
        if key in col:
            out[key] = col[key]
        elif key == "l":
            out[key] = out["k"]
        else:
            out[key] = COLUMN_DEFAULTS[key]
    return out


def _null_runs(values):
    out = []
    append = out.append
    run = 0
    for value in values:
        if value is None:
            run += 1
            continue
        if run:
            append(None if run == 1 else _MARK + "-" + _b62(run))
            run = 0
        append(value)
    if run:
        append(None if run == 1 else _MARK + "-" + _b62(run))
    return out


_PLAIN = (int, float, bool)


def _by_column(rows):
    return list(zip(*rows))


class _Packer:
    def __init__(self):
        self.counts = collections.Counter()
        self.refs = {}
        self.strings = []
        self.shared = []
        self._shared_at = {}

    # -- pass 1: how often each string is written --------------------------
    def count(self, value):
        kind = type(value)
        if kind is str:
            self.counts[value] += 1
        elif kind is list or kind is tuple:
            self.count_list(value)
        elif kind is dict:
            self.count_list(list(value))
            self.count_list(list(value.values()))

    def count_list(self, values):
        counts = self.counts
        for value in values:
            kind = type(value)
            if kind is str:
                counts[value] += 1
            elif kind is list or kind is dict or kind is tuple:
                self.count(value)

    def count_cells(self, values):
        """A column of cells, counted at C speed (Counter.update): numbers
        and None are counted too and never tabled."""
        try:
            self.counts.update(values)
        except TypeError:
            self.count_list(values)

    def choose(self):
        """Table each string that is shorter written once; the most written
        get the shortest references. Every other string that starts with
        the marker maps to itself with one more marker in front."""
        many = sorted(((n, str(s)) for s, n in self.counts.items()
                       if n > 1 and isinstance(s, str) and len(s) > 2),
                      key=lambda item: -item[0])
        refs = self.refs
        for n, text in many:
            ref = _MARK + _b62(len(self.strings))
            if n * len(text) <= len(text) + 1 + n * len(ref):
                continue
            refs[text] = ref
            self.strings.append(text)
        for text in self.counts:
            if (isinstance(text, str) and text[:1] == _MARK
                    and text not in refs):
                refs[str(text)] = _MARK + str(text)
        self.counts = None

    # -- pass 2: write -------------------------------------------------------
    def enc(self, value):
        kind = type(value)
        if kind is str:
            return self.refs.get(value, value)
        if kind is list or kind is tuple:
            return self.enc_list(value)
        if kind is dict:
            get = self.refs.get
            return {get(key, key) if type(key) is str else self.enc(key):
                    self.enc(item) for key, item in value.items()}
        if isinstance(value, str):
            # A str subclass is written as the plain string it is. Never
            # counted, so never tabled -- but escaped like any other.
            text = str(value)
            return self.refs.get(text) or (_MARK + text if text[:1] == _MARK
                                           else text)
        return value

    def enc_list(self, values):
        get = self.refs.get
        enc = self.enc
        return [get(value, value) if type(value) is str
                else value if value is None or type(value) in _PLAIN
                else enc(value) for value in values]

    def column(self, values):
        """One column of cells: strings by reference, null runs. A cell is
        None, a number or a str (encode_cell), so one dict lookup writes it
        -- a str subclass finds its plain twin's entry, since every counted
        string that needs one has one (choose)."""
        nulls = values.count(None)
        if nulls == len(values):
            return _null_runs(values)
        get = self.refs.get
        try:
            # A number, None or True maps to itself: every key is a str.
            out = [get(v, v) for v in values]
        except TypeError:                   # an unhashable cell
            out = self.enc_list(values)
        return _null_runs(out) if nulls > 1 else out

    def share(self, value, key):
        """A container repeated verbatim, stored once in `x`."""
        index = self._shared_at.get(key)
        if index is None:
            index = self._shared_at[key] = len(self.shared)
            self.shared.append(self.enc(value))
        return _MARK + "*" + _b62(index)


def pack_island(island):
    """The island as the page stores it. See "the stored form" above."""
    packer = _Packer()
    records = island["records"]
    width = len(island["fields"])
    canonical = [r["c"] for r in records if "c" in r]
    if any(len(cells) != width for cells in canonical):
        raise ValueError("a record's canonical cells are not one per field")
    segments = [seg for view in island["views"] for seg in view["segments"]]
    by_column = {}
    for seg in segments:
        rows = seg["rows"]
        if rows and len({len(row) for row in rows}) == 1:
            by_column[id(seg)] = _by_column(rows)

    # pass 1
    columns = _by_column(canonical)
    for col in columns:
        packer.count_cells(col)
    for seg in segments:
        for key, value in seg.items():
            if key == "rows" and id(seg) in by_column:
                for col in by_column[id(seg)]:
                    packer.count_cells(col)
            elif key == "cols":
                packer.count([_slim_column(c) for c in value])
            else:
                packer.count(value)
    for record in records:
        for key, value in record.items():
            if key != "c":
                packer.count(value)
    for key, value in island.items():
        if key == "member_cols":
            packer.count([_slim_column(c) for c in value])
        elif key not in ("records", "views"):
            packer.count(value)
    for view in island["views"]:
        for key, value in view.items():
            if key != "segments":
                packer.count(value)
                packer.count(key)
    packer.choose()

    # pass 2
    out_records = {
        "n": len(records),
        "noc": [i for i, r in enumerate(records) if "c" not in r],
        "c": [packer.column(col) for col in columns],
        "r": [{k: (packer.share(v, ("a", tuple(v.items())))
                   if k == "a" else packer.enc(v))
               for k, v in record.items() if k != "c"}
              for record in records],
    }
    heads = []
    for head in island["heads"]:
        out = {}
        for k, v in head.items():
            out[k] = (packer.share(v, ("p", tuple(map(tuple, v))))
                      if k == "p" and v else packer.enc(v))
        heads.append(out)
    views = []
    for view in island["views"]:
        out_view = {}
        for k, v in view.items():
            if k != "segments":
                out_view[k] = packer.enc(v)
                continue
            out_view[k] = []
            for seg in v:
                out_seg = {}
                for key, value in seg.items():
                    if key == "rows" and id(seg) in by_column:
                        out_seg[key] = {"n": len(value),
                                        "c": [packer.column(col) for col
                                              in by_column[id(seg)]]}
                    elif key == "cols":
                        out_seg[key] = packer.enc(
                            [_slim_column(c) for c in value])
                    else:
                        out_seg[key] = packer.enc(value)
                out_view[k].append(out_seg)
        views.append(out_view)
    data = {}
    for k, v in island.items():
        if k == "records":
            data[k] = out_records
        elif k == "heads":
            data[k] = heads
        elif k == "views":
            data[k] = views
        elif k == "member_cols":
            data[k] = packer.enc([_slim_column(c) for c in v])
        else:
            data[k] = packer.enc(v)
    return {"schema": island["schema"], "pack": PACK_VERSION,
            "s": packer.strings, "x": packer.shared, "d": data}


def unpack_island(packed):
    """The island a packed one stands for: what boot.js's unpackIsland
    makes in the page, in Python, so a test can hold the packer to
    build_island without a browser."""
    if packed.get("pack") != PACK_VERSION:
        raise ValueError("not a version-%d packed island" % PACK_VERSION)
    strings = packed["s"]
    shared = []

    def text(value):
        if value[:1] != _MARK:
            return value
        if value[1:2] == _MARK:
            return value[1:]
        if value[1:2] == "*":
            return copy.deepcopy(shared[_unb62(value[2:])])
        return strings[_unb62(value[1:])]

    def dec(value):
        if isinstance(value, str):
            return text(value)
        if isinstance(value, list):
            out = []
            for item in value:
                if isinstance(item, str) and item[:2] == _MARK + "-":
                    out.extend([None] * _unb62(item[2:]))
                else:
                    out.append(dec(item))
            return out
        if isinstance(value, dict):
            return {text(k): dec(v) for k, v in value.items()}
        return value

    def rows_of(value, count=None):
        columns = [dec(col) for col in value]
        if not columns:
            return [[] for _ in range(count or 0)]
        return [list(row) for row in zip(*columns)]

    for item in packed["x"]:
        shared.append(dec(item))
    island = {}
    for k, v in packed["d"].items():
        if k == "records":
            cells = rows_of(v["c"])
            without = set(v["noc"])
            records, at = [], 0
            for i, rest in enumerate(v["r"]):
                record = {}
                if i not in without:
                    record["c"] = cells[at]
                    at += 1
                record.update(dec(rest))
                records.append(record)
            island[k] = records
        elif k == "views":
            views = []
            for view in v:
                out_view = {}
                for key, value in view.items():
                    if key != "segments":
                        out_view[key] = dec(value)
                        continue
                    out_view[key] = []
                    for seg in value:
                        out_seg = {}
                        for name, item in seg.items():
                            if name == "rows" and isinstance(item, dict):
                                out_seg[name] = rows_of(item["c"], item["n"])
                            elif name == "cols":
                                out_seg[name] = [_full_column(c)
                                                 for c in dec(item)]
                            else:
                                out_seg[name] = dec(item)
                        out_view[key].append(out_seg)
                views.append(out_view)
            island[k] = views
        elif k == "member_cols":
            island[k] = [_full_column(c) for c in dec(v)]
        else:
            island[k] = dec(v)
    return island


#: Written as JSON escapes, so the island text holds no "<" at all and no
#: evidence string can close the element that carries it (spec: "What the
#: island never contains"). U+2028/2029 are escaped for older parsers.
_JSON_ESCAPES = (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                 ("\u2028", "\\u2028"), ("\u2029", "\\u2029"))


def island_json(island):
    """The island as JSON text. Every cell already passed _safe_text on its
    way in (encode_cell). This adds the one substitution json.dumps does
    not make (a lone surrogate elsewhere, such as in a label or an
    identity line, or a DEL, which json.dumps leaves raw), made once over
    the serialised text, which is cheaper than walking every value.

    It is _safe_text's substitution with the backslash written as a JSON
    escape: _safe_text's "\\uD800" pasted raw into JSON text would be read
    back as the JSON escape for the surrogate it replaced (and "\\x7F" is
    not a JSON escape at all), so a reader gets exactly the string
    _safe_text makes. json.dumps writes every other control character,
    the tags included, as a JSON escape."""
    text = json.dumps(island, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False)
    text = forensic_engine._LONE_SURROGATE.sub(
        lambda m: "\\\\u%04X" % ord(m.group()), text)
    text = forensic_engine._NONCHARACTER.sub(
        lambda m: "\\\\u%04X" % ord(m.group()), text)
    text = forensic_engine._ILLEGAL_TEXT.sub(
        lambda m: "\\\\x%02X" % ord(m.group()), text)
    for raw, escaped in _JSON_ESCAPES:
        text = text.replace(raw, escaped)
    return text


# --- the page ------------------------------------------------------------------

_ASSET_DIR = pathlib.Path(__file__).resolve().parent / "html_package_assets"


def asset_dir():
    """Where the page's template, stylesheet and scripts are read from.
    From source, beside this module. In a PyInstaller build, where the
    spec's `datas` put them under sys._MEIPASS (packaging/webcache.spec):
    a frozen module's __file__ is not a promise that a data file sits
    beside it."""
    base = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and base:
        return pathlib.Path(base) / "webcache" / "shell" / "html_package_assets"
    return _ASSET_DIR

#: The page's code, concatenated in THIS order into one inline script.
#: main.js is always last: it freezes the read-only API and calls start().
ASSET_ORDER = ("util.js", "boot.js", "model.js", "grid.js", "filter.js",
               "dialog.js", "export_csv.js", "xlsx.js", "main.js")

_PLACEHOLDERS = ("@@CSP@@", "@@STYLE@@", "@@DATA@@", "@@SCRIPT@@")


def _asset(name):
    """One asset, LF-only. The browser hashes an inline block after HTML
    newline normalisation (CRLF -> LF), so a CRLF would make the page
    refuse its own script."""
    text = (asset_dir() / name).read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def page_script():
    body = "\n".join(_asset(name) for name in ASSET_ORDER)
    return "(function () {\n\"use strict\";\n" + body + "\n})();\n"


def page_style():
    return _asset("page.css")


def csp_source_hash(text):
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "'sha256-%s'" % base64.b64encode(digest).decode("ascii")


def content_security_policy(script, style):
    """The page's security policy: no network of any kind, and only the
    two inline blocks this file was written with may run or apply."""
    return ("default-src 'none'; script-src %s; style-src %s; "
            "img-src 'none'; font-src 'none'; connect-src 'none'; "
            "media-src 'none'; object-src 'none'; frame-src 'none'; "
            "worker-src 'none'; manifest-src 'none'; base-uri 'none'; "
            "form-action 'none'"
            % (csp_source_hash(script), csp_source_hash(style)))


def render_page(data_json, script=None, style=None):
    """The whole page as text. The template is split on its four
    placeholders and the parts joined, so nothing inserted is ever scanned
    for a placeholder again -- an evidence string reading "@@SCRIPT@@"
    stays text."""
    script = page_script() if script is None else script
    style = page_style() if style is None else style
    for name, block, closer in (("script", script, "</script"),
                                ("style", style, "</style")):
        if "\r" in block:
            raise ValueError("the %s block holds a carriage return; the "
                             "browser would hash different text" % name)
        if closer in block.lower():
            raise ValueError("the %s block contains %s" % (name, closer))
        if name == "script" and "<!--" in block and "<script" in block.lower():
            raise ValueError("the script block holds '<!--' with '<script'; "
                             "the parser would not end it at </script>")
    if "<" in data_json or "\r" in data_json:
        raise ValueError("the data island must hold no '<' and no carriage "
                         "return")
    values = {"@@CSP@@": content_security_policy(script, style),
              "@@STYLE@@": style, "@@DATA@@": data_json,
              "@@SCRIPT@@": script}
    rest = _asset("page.html")
    parts = []
    for placeholder in _PLACEHOLDERS:
        before, found, rest = rest.partition(placeholder)
        if not found:
            raise ValueError("page.html lacks %s" % placeholder)
        parts.append(before)
        parts.append(values[placeholder])
    if any(p in rest for p in _PLACEHOLDERS):
        raise ValueError("page.html repeats a placeholder")
    parts.append(rest)
    return "".join(parts)


#: The page's own "Records in this report" headings (boot.js countsTable),
#: so the provenance sidecar names each count by the unit the page shows.
_SEG_LIVE = "live records"
_SEG_CARVED = "recovered records (carves and stubs)"
_SEG_OTHER = "not single records (aggregates, raw rows)"
_RECORD_UNITS = (("live", "live records"), ("carved", "carved records"),
                 ("stub", "deleted-record stubs"),
                 ("other", "other records (cookies, HSTS pins, "
                           "certificates, containers)"))


def island_counts(island):
    """What the page written from `island` holds, by unit -- for the
    provenance sidecar, which must never understate its file. Per segment
    the same three counts the page's "Records in this report" table
    shows; the distinct records the page stores, by the kind its record
    dialog states; the raw table rows; and the aggregate members."""
    heads, records = island["heads"], island["records"]
    kind_of = {}
    members = set()
    per_segment = []
    raw_rows = 0
    for view in island["views"]:
        for seg in view["segments"]:
            live = carved = other = 0
            for o in seg["org"]:
                label = seg["origins"][o]
                if label == export_formats._LIVE_CELL:
                    live += 1
                elif label == provenance.CARVED_ORIGIN:
                    carved += 1
                else:
                    other += 1
            per_segment.append({"view": view["label"],
                                "segment": seg["label"],
                                "rows": len(seg["rows"]), _SEG_LIVE: live,
                                _SEG_CARVED: carved, _SEG_OTHER: other})
            if view["key"] == "raw":
                raw_rows += len(seg["rows"])
            for rec, hd in zip(seg["rec"], seg["hd"]):
                if rec >= 0:
                    kind_of.setdefault(rec, heads[hd]["k"])
            for refs in seg.get("mem") or ():
                for ref in refs or ():
                    members.add(ref)
                    head = records[ref].get("mh")
                    if head is not None:
                        kind_of.setdefault(ref, heads[head]["k"])
    distinct = {unit: 0 for _kind, unit in _RECORD_UNITS}
    units = dict(_RECORD_UNITS)
    for index in range(len(records)):
        distinct[units[kind_of.get(index, "other")]] += 1
    distinct["total"] = len(records)
    return {"distinct_records": distinct,
            "rows_per_segment": per_segment,
            "rows_total": sum(s["rows"] for s in per_segment),
            "raw_table_rows": raw_rows,
            "aggregate_members": len(members)}


class PackagePaths(list):
    """[page, .sha256 sidecar], plus `counts`: island_counts() of the
    island the page was written from."""
    counts = None


def write_package(snapshot, path, generated_utc=None):
    """Write the page (atomically: the file exists only once complete),
    then <path>.sha256 in sha256sum format. Returns [path, sidecar] as a
    PackagePaths carrying what the page holds (island_counts)."""
    if generated_utc is None:
        generated_utc = datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    island = build_island(snapshot, generated_utc)
    data = render_page(island_json(pack_island(island))).encode("utf-8")
    with forensic_engine.atomic_path(path) as tmp:
        with open(tmp, "wb") as fh:
            fh.write(data)
    side = path + ".sha256"
    with forensic_engine.atomic_write(side, newline="\n",
                                      encoding="utf-8") as fh:
        fh.write("%s  %s\n" % (hashlib.sha256(data).hexdigest(),
                               os.path.basename(path)))
    written = PackagePaths([path, side])
    written.counts = island_counts(island)
    return written
