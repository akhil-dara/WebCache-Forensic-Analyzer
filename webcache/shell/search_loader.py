"""Shaping and wording for the Search view (the loader half of
search_loader/search_runner). No Qt and no widgets; the only engine read
is the one bounded re-read hit_field_rows makes through a parser it is
given.

WHICH SEARCH THIS IS. Everything here shapes the output of
WebCacheParser.search_all_tables, which searches the database: every table
dissect enumerates (MSysObjects/MSysObjectsShadow/MSysObjids, HSTS,
dependency, AppCache and LeakFiles included, which no view interprets) and
every column of every row, decoded once, plus the hex, ASCII and
UTF-16-LE readings of any binary value that did not decode to text.

ForensicEngine.search is not used here. It searches the parsed record set,
which is what each record view's filter box does over its rows, and "no
hits" would then mean something weaker. views/search.py states which
search runs, in its subtitle.

TWO ABSENCES IN THE URL COLUMN. A hit in a table with no Url column
(MSysObjects, PartitionsEx) and a hit in a table whose Url cell is empty
are different facts, so search_rows writes ABSENCE_NOT_APPLICABLE for the
first and ABSENCE_EMPTY for the second.

BOTH READINGS OF EVERY COLUMN. The engine's result carries the matched
cell as stored (match_raw/match_raw_type). hit_field_rows gives every
column its stored reading with one bounded re-read,
get_table_rows_raw(table, limit=1, offset=row_index - 1), the same call
the Table Browser makes per page. When it returns nothing, every stored
cell reads RAW_REREAD_FAILED rather than a blank.
"""
from .. import provenance
from ..spellings import other_spellings
from . import record_kinds

#: The scope combo's "search everything" sentinel. NOT "" -- an empty
#: string is what the ENGINE reads as "every table", and a combo whose
#: first item carried it would be indistinguishable from a combo that had
#: never been filled. table_filter_for() is the one place the two
#: vocabularies meet.
ALL_TABLES = "__ALL__"

#: The scope that searches only the recovered records (the Deleted
#: Records rows a recovery scan produced). "All" covers them too; a
#: single-table scope does not, and the count line says so.
RECOVERED_SCOPE = "__RECOVERED__"

#: The key prefix of a scope-combo group heading (a table type). The view
#: disables those items; table_filter_for maps one to "every table" in
#: case a heading is ever selected programmatically.
GROUP_PREFIX = "__GROUP__:"

#: What a recovered hit's Table cell reads. Not a table name: recovered
#: records are not in any table, which is the point of them.
RECOVERED_TABLE = "Recovered records"

#: characters (or, inside a blob, characters' worth of bytes) shown
#: either side of the match.
KWIC_RADIUS = 40
_ELLIPSIS = "…"

#: What a stored cell reads when the bounded re-read returned nothing.
#:
#: get_table_rows_raw returns ([], []) both for a table it could not read
#: and for an empty one, so this does not claim which happened.
#:
#: Not one of provenance.ABSENCE_TOKENS, none of which is true here: the
#: bytes exist (a hit was found in this row), nothing was carved, and the
#: column applies.
RAW_REREAD_FAILED = "(could not re-read)"

#: Evidence is open and nothing has been searched. Says what Search does
#: and roughly how long it takes, since it reads every table.
IDLE_TEXT = ("Nothing has been searched yet. Type a keyword and press "
             "Search — every table and every column of this database is "
             "read, which takes a few seconds on a small exhibit and "
             "longer on a large one.")

#: A search is running. The window stays usable for its whole duration --
#: that is the entire reason the scan runs on its own thread and its own
#: file handle -- so this says so rather than leaving an examiner to
#: guess whether the application is alive.
SEARCHING_TEXT = ("Searching every table… the window stays usable, and "
                  "Cancel is in the status bar.")

#: A search was cancelled. An empty grid after a cancellation must not
#: read like a completed search that found nothing; nothing partial is
#: reported (see shell/search_runner.py), and this says so.
CANCELLED_TEXT = ("Search cancelled. No results are shown for an "
                  "incomplete search.")

#: A finished search with no hits. `%s` is the keyword, filled by
#: no_hits_text(), because the sentence is true only of the keyword
#: searched for.
NO_HITS_TEXT = ("No cell in any searched table contains '%s'. Only "
                "stored data is searched, not what was typed or visited.")

#: Printed under the query bar, on every render. Three facts an examiner
#: cannot get from anywhere else on this screen: that tables no view
#: interprets are searched too, that binary values are searched in full
#: rather than by their preview, and that a hit "inside blob" is real
#: even though the Table Browser will not show it in that cell.
SCOPE_NOTE = ("Searches the database's own tables and columns — "
              "including tables no view interprets — and, once recovery "
              "has run, the recovered records' fields read from the "
              "carved bytes. Binary values are searched in full: hex, "
              "ASCII/UTF-8 and UTF-16. A hit marked "
              "'inside blob' is real but is not visible in that cell in "
              "the Table Browser.")


class SearchQuery:
    """One search, captured whole when it was requested.

    Compared by identity when a result arrives, so a result is never shown
    under a later query's keyword and count line.

    `known_hashes` travels with the query because the worker opens its own
    parser (see shell/search_runner.py), so the exhibit is not hashed
    again.
    """
    __slots__ = ("keyword", "table_filter", "scope_label", "db_path",
                 "known_hashes", "recovered_rows", "include_recovered",
                 "clock")

    def __init__(self, keyword, table_filter="", scope_label="All tables",
                 db_path="", known_hashes=None, recovered_rows=None,
                 include_recovered=True, clock=None):
        self.keyword = keyword
        self.table_filter = table_filter or ""
        self.scope_label = scope_label
        self.db_path = db_path or ""
        self.known_hashes = known_hashes
        #: The Deleted Records rows at the moment the search was requested,
        #: or None when no recovery scan had finished. Captured rather than
        #: re-read, so the count line states what this search covered even
        #: if a scan finishes during it.
        self.recovered_rows = recovered_rows
        #: False for a single-table scope: the recovered records exist but
        #: are outside the scope, and the count line says how many.
        self.include_recovered = bool(include_recovered)
        #: local_clock.clock_snapshot of the parse on screen: the worker's
        #: own parser never parses entries, and an MSHist ModifiedTime is
        #: read on this clock. None: no exhibit clock.
        self.clock = clock


# --- scope ----------------------------------------------------------------

def scope_options(parser, recovered_count=None):
    """[(key, label), ...]: All, Recovered records (when a scan has run),
    then every table grouped by type under a heading whose key starts with
    GROUP_PREFIX (the view disables those). Groups and names are sorted,
    so the list is the same on every open."""
    options = [(ALL_TABLES, "All tables and recovered records")]
    if recovered_count is not None:
        options.append((RECOVERED_SCOPE,
                        "Recovered records (%s)" % format(recovered_count, ",")))
    names = sorted(getattr(parser, "table_names", None) or ())
    typer = getattr(parser, "get_table_type", None)
    groups = {}
    for name in names:
        group = typer(name) if callable(typer) else "Tables"
        groups.setdefault(group or "Other", []).append(name)
    for group in sorted(groups):
        options.append((GROUP_PREFIX + group, "— %s —" % group))
        for name in groups[group]:
            options.append((name, "    " + parser.get_table_display_name(name)))
    return options


def table_filter_for(scope):
    """The engine's own table_filter for a combo selection. The sentinel
    (and nothing selected at all) become "", which search_all_tables
    reads as every table; so does a group heading. RECOVERED_SCOPE maps
    to itself -- it is the view's one way to say "recovered only", and
    MainWindow._search_query_for never hands it to the engine."""
    if scope in (None, ALL_TABLES) or str(scope).startswith(GROUP_PREFIX):
        return ""
    return scope


# --- keyword in context --------------------------------------------

def _printable(ch):
    return ch if (ch.isprintable() and ch not in "\r\n\t") else " "


def _fold_find(chars, keyword):
    """(first, end) indices into `chars` (one decoded character per item,
    "" for an undecodable unit) of the first case-insensitive match of
    `keyword`, or None. Folding is done PER CHARACTER in decoded text, so
    a character whose case-fold changes length (U+0130, U+00DF) still
    maps back to the unit it came from, and nothing is ever lower-cased
    as raw bytes. An empty needle never matches."""
    needle = (keyword or "").casefold()
    if not needle:
        return None
    folded, owner = [], []
    for i, ch in enumerate(chars):
        f = ch.casefold() if ch else "\x00"
        folded.append(f)
        owner.extend([i] * len(f))
    at = "".join(folded).find(needle)
    if at < 0:
        return None
    return owner[at], owner[at + len(needle) - 1] + 1


def keyword_context(text, keyword, radius=KWIC_RADIUS):
    """(snippet, start): `radius` characters either side of the first
    case-insensitive match, marked with an ellipsis where cut; ("", -1)
    when the keyword is not in the text. Control and format characters
    (a bidi override included) read as a space, so a snippet is always
    one plain line."""
    text = "" if text is None else str(text)
    span = _fold_find(list(text), keyword)
    if span is None:
        return "", -1
    first, end = span
    a, b = max(0, first - radius), min(len(text), end + radius)
    body = "".join(_printable(c) for c in text[a:b])
    return ((_ELLIPSIS if a else "") + body
            + (_ELLIPSIS if b < len(text) else "")), first


def plain_prefix(text, limit=2 * KWIC_RADIUS):
    """The first `limit` characters of `text` as one plain line -- what a
    Context cell shows when no snippet can be cut (a match in the hex
    rendering of a value, say), never the whole multi-line value."""
    text = "" if text is None else str(text)
    body = "".join(_printable(c) for c in text[:limit])
    return body + (_ELLIPSIS if len(text) > limit else "")


def _utf8_units(data):
    """[(char, byte offset, byte length)] for `data` read as UTF-8; an
    invalid byte is ("", offset, 1)."""
    units, i, n = [], 0, len(data)
    while i < n:
        b = data[i]
        if b < 0x80:
            units.append((chr(b), i, 1))
            i += 1
            continue
        size = (2 if 0xC2 <= b <= 0xDF else 3 if 0xE0 <= b <= 0xEF
                else 4 if 0xF0 <= b <= 0xF4 else 0)
        if size and i + size <= n:
            try:
                units.append((data[i:i + size].decode("utf-8"), i, size))
                i += size
                continue
            except UnicodeDecodeError:
                pass
        units.append(("", i, 1))
        i += 1
    return units


def _utf16_units(data):
    """[(char, byte offset, byte length)] for `data` read as UTF-16LE from
    offset 0 -- EVEN offsets only, the only alignment a UTF-16 string in
    a blob this tool reads is taken to have. A lone surrogate is ("",
    offset, 2)."""
    units, i, n = [], 0, len(data) // 2 * 2
    while i < n:
        u = data[i] | (data[i + 1] << 8)
        if 0xD800 <= u <= 0xDBFF and i + 4 <= n:
            u2 = data[i + 2] | (data[i + 3] << 8)
            if 0xDC00 <= u2 <= 0xDFFF:
                units.append((data[i:i + 4].decode("utf-16-le"), i, 4))
                i += 4
                continue
        units.append(("" if 0xD800 <= u <= 0xDFFF else chr(u), i, 2))
        i += 2
    return units


def blob_context(data, keyword, radius=KWIC_RADIUS):
    """(snippet, byte offset, encoding) of `keyword` inside binary `data`.

    Searched in the encodings a blob can actually hold, as DECODED TEXT
    and case-folded there: ASCII/UTF-8 first, then UTF-16LE
    at even offsets. The snippet is `radius` characters either side of
    the match, decoded in the encoding that matched -- never Latin-1, so
    there is no mojibake -- with undecodable and control bytes as a
    middle dot. The encoding is "ASCII" when every matched byte is below
    0x80, else "UTF-8", or "UTF-16LE". ("", None, None) when the keyword
    is in neither -- and always for an empty keyword."""
    data = bytes(data or b"")
    needle = (keyword or "").casefold()
    if not needle or not data:
        return "", None, None
    for encoding in ("UTF-8", "UTF-16LE"):
        if encoding == "UTF-8":
            quick = data.decode("utf-8", "replace")
        else:
            quick = data[:len(data) // 2 * 2].decode("utf-16-le", "replace")
        # A cheap necessary condition first: the per-character decode
        # below is only paid for a blob that can match.
        if needle not in quick.casefold():
            continue
        units = _utf8_units(data) if encoding == "UTF-8" else _utf16_units(data)
        span = _fold_find([u[0] for u in units], keyword)
        if span is None:
            continue
        first, end = span
        a, b = max(0, first - radius), min(len(units), end + radius)
        body = "".join(c if (c and c.isprintable() and c not in "\r\n\t")
                       else "\u00b7" for c, _o, _n in units[a:b])
        snippet = ((_ELLIPSIS if a else "") + body
                   + (_ELLIPSIS if b < len(units) else ""))
        if encoding == "UTF-8" and all(n == 1 for _c, _o, n in units[first:end]):
            encoding = "ASCII"
        return snippet, units[first][1], encoding
    return "", None, None


# --- the result rows ------------------------------------------------------

def search_rows(results, keyword=""):
    """One row per hit, shaped for views/search.py's columns.

    Fifteen keys: the thirteen declared columns plus `_kind` and
    `_result`. The engine result is held by reference, not copied: the
    detail pane is built from it, and results take about 2.5 KB per hit.

    `Context` is the keyword in context: about KWIC_RADIUS characters
    either side of the match. The whole value is in MatchedValue/RawValue
    (the Columns menu, the pane, every export). `BlobOffset` is the
    match's byte position inside a binary value, None for a text value,
    and `BlobEncoding` the encoding it matched in ("ASCII", "UTF-8",
    "UTF-16LE"; "" for a text value).
    """
    rows = []
    for result in results or ():
        cells = result.get("row") or {}
        # TWO DIFFERENT FACTS, and the vocabulary spells both -- see the
        # module docstring. Never a blank, which spells neither.
        if "Url" not in cells:
            url = provenance.ABSENCE_NOT_APPLICABLE
        else:
            url = cells.get("Url") or provenance.ABSENCE_EMPTY
        context, offset, encoding = "", None, None
        if result.get("match_raw_type") == "binary" and result.get("match_raw"):
            try:
                data = bytes.fromhex(str(result["match_raw"]).replace(" ", ""))
            except ValueError:
                data = b""
            context, offset, encoding = blob_context(data, keyword)
        if not context:
            context, _start = keyword_context(result.get("match_value"), keyword)
        if not context:
            # No snippet can be cut (a match in the hex rendering, say):
            # one plain capped line, never the whole value.
            context = plain_prefix(result.get("match_value"))
        rows.append({
            "Table": result.get("table") or "",
            "Container": result.get("container_name") or "",
            "TableType": result.get("table_type") or "",
            # 1-based ordinal WITHIN THE TABLE. Not an EntryId, and the
            # subtitle says so: two rows of two different tables can
            # carry the same number and mean nothing to each other.
            "Row": result.get("row_index") or 0,
            # EVERY matched column, never "four of nine".
            "MatchedColumns": ", ".join(result.get("matched_columns") or ()),
            "FoundIn": "inside blob" if result.get("match_in_blob") else "value",
            "Context": context,
            "BlobOffset": offset,
            "BlobEncoding": encoding or "",
            "MatchedValue": result.get("match_value") or "",
            "RawType": result.get("match_raw_type") or "",
            "RawValue": result.get("match_raw") or "",
            "Url": url,
            "_kind": record_kinds.K_TABLE_ROW,
            "_result": result,
        })
    return rows


def recovered_hits(keyword, recovered_rows):
    """Every recovered record (a Deleted Records row) holding
    `keyword`, case-insensitively, in a field READ FROM THE CARVED BYTES
    -- recovery_loader.SEARCHED_FIELDS, the one declared list, and never
    a label this tool wrote. Shaped like search_rows'
    rows, plus Origin, `_kind` and `_record` (by reference): a recovered
    hit IS a record and opens as one. Row is the record's 1-based
    position in the Deleted Records list."""
    from .recovery_loader import searched_values
    kw = (keyword or "").lower()
    hits = []
    if not kw:
        return hits
    for ordinal, row in enumerate(recovered_rows or (), 1):
        matched, first = [], None
        for name, value, whole in searched_values(row):
            if isinstance(value, bytes):
                snippet, at, encoding = blob_context(value, keyword)
                if at is None:
                    continue
                shown = snippet
            elif whole:
                if value.lower() != kw:
                    continue
                shown, at = value, None
            else:
                if _fold_find(list(value), keyword) is None and not any(
                        _fold_find(list(alt), keyword) is not None
                        for alt in other_spellings(value)):
                    continue
                shown, at = value, None
            if name not in matched:
                matched.append(name)
            first = first or (shown, at, value,
                              encoding if at is not None else "")
        if not matched:
            continue
        shown, at, raw, encoding = first
        context = (shown if at is not None
                   else keyword_context(shown, keyword)[0]
                   or plain_prefix(shown))
        hits.append({
            "Table": RECOVERED_TABLE,
            "Container": row.get("ContainerType") or "",
            "TableType": "Recovered (carved)",
            "Row": ordinal,
            "MatchedColumns": ", ".join(matched),
            "FoundIn": "recovered record",
            "Context": context,
            "BlobOffset": at,
            "BlobEncoding": encoding,
            "MatchedValue": shown if at is None else context,
            "RawType": "binary" if at is not None else "text",
            "RawValue": (" ".join("%02X" % b for b in raw)
                         if at is not None else raw),
            "Url": row.get("CleanUrl") or provenance.ABSENCE_EMPTY,
            "Origin": provenance.CARVED_ORIGIN,
            "_kind": row.get("_kind"),
            "_record": row.get("_record") or {},
        })
    return hits


def recovered_field_rows(hit, keyword=""):
    """The pane's rows for a RECOVERED hit: every field of the recovered
    record, whether it holds the keyword, and its value -- decoded (the
    text, or a binary value's keyword-in-context reading) and as stored
    (hex for bytes). There is no database row to re-read: the record IS
    the carve."""
    record = (hit or {}).get("_record") or {}
    matched = set(str((hit or {}).get("MatchedColumns") or "").split(", "))
    rows = []
    for name, value in record.items():
        if str(name).startswith("_"):
            continue
        if isinstance(value, (bytes, bytearray)):
            decoded = (blob_context(value, keyword)[0]
                       or plain_prefix(bytes(value).decode("utf-8",
                                                           "replace")))
            stored = " ".join("%02X" % b for b in bytes(value))
        else:
            decoded = "" if value is None else str(value)
            stored = decoded
        rows.append({
            "Column": name,
            "Matched": "yes" if name in matched else "no",
            "Decoded": decoded,
            "Stored": stored,
            "_kind": record_kinds.K_TABLE_ROW,
        })
    return rows


def recovered_sentence(result):
    """What the count line says about recovered records, always: searched
    (N), NOT searched (N, why), or not recovered yet."""
    state = (result or {}).get("recovered")
    if state is None:
        return ("recovered records: recovery has not run for this exhibit, "
                "so none were searched")
    count, searched, why = state
    noun = "recovered record%s" % ("" if count == 1 else "s")
    if searched:
        return ("%s %s searched (the fields read from the carved bytes)"
                % (format(count, ","), noun))
    return "%s %s NOT searched (%s)" % (format(count, ","), noun, why)


def as_sentence(text):
    """Upper-case the first letter and add a full stop -- never
    str.capitalize(), which would lower-case "NOT"."""
    return text[:1].upper() + text[1:] + "."


# --- the detail pane ------------------------------------------------------

def hit_field_rows(parser, result):
    """Every column of the row a hit was found in, decoded and as stored.

    Decoded values come from result["row"], captured during the search, so
    the pane shows what the search matched against.

    Stored values come from one bounded re-read at the hit's offset (see
    the module docstring). A re-read that returns nothing (or raises)
    leaves every stored cell reading RAW_REREAD_FAILED, never a blank,
    which would read as "the database stored nothing there".
    """
    result = result or {}
    cells = result.get("row") or {}
    matched = set(result.get("matched_columns") or ())
    table = result.get("table") or ""
    ordinal = result.get("row_index") or 0

    columns, raw_rows = [], []
    if parser is not None and table and ordinal:
        try:
            columns, raw_rows = parser.get_table_rows_raw(
                table, limit=1, offset=ordinal - 1)
        except Exception:
            # A table that raised during the search can still be named by a
            # hit (the exception may have come later in the scan), so this
            # degrades rather than propagates.
            columns, raw_rows = [], []

    stored_by_column = {}
    if columns and raw_rows:
        for name, value in zip(columns, raw_rows[0]):
            stored_by_column[name] = parser.raw_rendering(value)

    # The decoded row is the canonical column list: the search pass built
    # it by walking the table's own columns in order, and it is complete
    # even when the re-read is not.
    names = list(cells) or list(columns)
    rows = []
    for name in names:
        rows.append({
            "Column": name,
            # Literal "yes"/"no", never a blank: a blank in this cell
            # would read as "not matched" for every unmatched column AND
            # for a column the pane failed to decide about.
            "Matched": "yes" if name in matched else "no",
            "Decoded": cells.get(name, ""),
            "Stored": stored_by_column.get(name, RAW_REREAD_FAILED),
            "_kind": record_kinds.K_TABLE_ROW,
        })
    return rows


def reread_failed(rows):
    """True when the re-read behind `rows` came back with nothing.

    Takes the ALREADY-BUILT rows rather than re-deriving them: a second
    hit_field_rows call would pay the bounded re-read a second time for
    an answer the first one already contains, and the two could in
    principle disagree.
    """
    return any(row.get("Stored") is RAW_REREAD_FAILED for row in rows or ())


# --- the wording ----------------------------------------------------------

def no_hits_text(keyword, result=None):
    """NO_HITS_TEXT for `keyword`, plus -- when the search's result is
    given -- what it says about the recovered records: a zero over
    the database alone is not a zero over the evidence."""
    text = NO_HITS_TEXT % (keyword,)
    if result is not None:
        text += " " + as_sentence(recovered_sentence(result))
    return text


def skipped_sentence(skipped):
    """What was not searched, and what that means for this result.

    "" when nothing was skipped, so the caveat appears only when it
    applies.
    """
    skipped = list(skipped or ())
    if not skipped:
        return ""
    names = ", ".join(str(entry[0] if isinstance(entry, (tuple, list))
                          else entry) for entry in skipped)
    return ("%d table(s) could not be read and were NOT searched: %s. A "
            "keyword absent from this result may still be present in them."
            % (len(skipped), names))


def result_note(query, result):
    """The count line's note: what was searched for, over how much."""
    result = result or {}
    note = ("'%s' across %s table(s) · %s row(s) scanned"
            % (getattr(query, "keyword", ""),
               format(result.get("tables") or 0, ","),
               format(result.get("rows_scanned") or 0, ",")))
    note += " · " + recovered_sentence(result)
    sentence = skipped_sentence(result.get("skipped"))
    if sentence:
        note += " — " + sentence
    return note


# --- what the export sidecar needs ---------------------------------------

def export_scope(results):
    """The five facts a Search export's provenance sidecar has to state
    that no other view's does. {} when nothing has been searched, so the
    sidecar's SEARCH block is gated on presence and no other view's file
    changes by a byte."""
    if not results:
        return {}
    query, result = results
    result = result or {}
    return {
        "search_keyword": getattr(query, "keyword", ""),
        "search_scope_label": getattr(query, "scope_label", ""),
        "tables_searched": result.get("tables") or 0,
        "rows_scanned": result.get("rows_scanned") or 0,
        "tables_skipped": [str(entry[0] if isinstance(entry, (tuple, list))
                               else entry)
                           for entry in (result.get("skipped") or ())],
    }
