"""The chain of custody. Nothing else invents its own.

Four things live here: the evidence set taken at consent, the origin riding
on each row, the view state that produced a screen, and the stamp that goes
into every export.

The rule underneath all of it: the application never asserts what it cannot
explain, and never shows a reconstructed record as if it were a real one.
"""
import datetime
import hashlib
import os

TOOL_VERSION = "5.0.0"

#: The six columns that state where a recovered record came from, written
#: by every export.
PROVENANCE_FIELDS = ("Origin", "Source", "Offset", "Page", "Method",
                     "Confidence")

#: The Origin value every carved row carries; record_model.py and
#: describe_origin() below treat any value that starts with "Carved" as
#: carved. Defined here so detail_fields.py (Qt-free) and
#: recovery_loader.py (which imports PySide6.QtCore) share one spelling.
CARVED_ORIGIN = "Carved (deleted/unflushed)"

#: What every row read from the live database states as its Origin -- on
#: screen (evidence_loader, detail_fields) and in every export
#: (forensic_engine.build_entry_row), so a live row's Origin cell is never
#: blank and never spelled two ways.
LIVE_ORIGIN = "Live record"

#: What an AGGREGATE row (a period, a domain, a place, an indicator) says
#: in the origin column -- derived from its members, never defaulted
#: A row that is neither a record nor a population
#: (a silence, a redirect hop) says NOT_A_RECORD.
AGGREGATE_LIVE = "Live"
AGGREGATE_MIXED = "Mixed"
AGGREGATE_RECOVERED = "Recovered only"
NOT_A_RECORD = "\u2014"


def is_carved_entry(entry):
    """One member's carved-ness: an explicit Origin wins; otherwise
    RecoverySource, which every carved artifact and stub carries and no
    live parser record does (as in detail_fields.row_for_record)."""
    entry = entry or {}
    origin = entry.get("Origin")
    if origin:
        return str(origin).startswith("Carved")
    return bool(entry.get("RecoverySource"))


def aggregate_members(row):
    """The members list an aggregate row carries by reference, or None."""
    row = row or {}
    members = row.get("_members")
    if members is None:
        members = row.get("_records")
    return members


def aggregate_origin(live_count, carved_count):
    if carved_count and not live_count:
        return AGGREGATE_RECOVERED
    if carved_count and live_count:
        return AGGREGATE_MIXED
    if live_count:
        return AGGREGATE_LIVE
    return ""


def row_origin_label(row):
    """The ONE derivation the vertical header and every export share:
    Live / Carved for a record; Live / Mixed / Recovered only for an
    aggregate, from its members; NOT_A_RECORD for a row that is neither."""
    if aggregate_members(row) is not None:
        return aggregate_origin_of(row) or NOT_A_RECORD
    if "_record" in row and row["_record"] is None:
        return NOT_A_RECORD
    return "Carved" if str(row.get("Origin", "")).startswith("Carved") else "Live"


def aggregate_origin_of(row):
    members = aggregate_members(row)
    if members is None:
        return ""
    carved = sum(1 for m in members if is_carved_entry(m))
    return aggregate_origin(len(members) - carved, carved)

#: The value a carved record's ContainerType holds when the string carver
#: (recovery_engine._carve_strings, behind carve_transaction_logs and
#: carve_database_slack) found it. A raw URL string from unallocated space
#: or a transaction log has no ContainerId, because the catalogue entry
#: that would have named one is what was destroyed. This is not "blank"
#: (a value that could have been read) and not a read failure: it is a
#: fact the evidence cannot answer, stated in plain words.
#: recovery_loader.py normalises the engine's None/"" to this spelling,
#: and record_model.py styles it distinctly from a real value.
CONTAINER_NOT_DETERMINABLE = "Not determinable"

#: The same words, used for every other field whose value cannot be known
#: from the evidence: whether a page-slack string carve was an InPrivate
#: visit is unknowable for the same reason, since a bare string has no
#: Flags column.
#:
#: An alias rather than a second constant, so one styling rule covers it
#: and two cells that mean the same thing look the same.
#:
#: It is not "blank" and not False/0/"", which are real values. Anything
#: reading it must treat it as unknown: a non-empty string is truthy, so
#: `if row["IsInPrivate"]` would misread it.
ABSENCE_NOT_DETERMINABLE = CONTAINER_NOT_DETERMINABLE

#: The column exists on this record and holds no value. A fact about the
#: EVIDENCE, not about this tool: the database stored nothing there.
ABSENCE_EMPTY = "(empty)"

#: A carve did not reach this column. Unlike ABSENCE_EMPTY, which asserts
#: the stored value was nothing, this makes no claim about a column the
#: reconstruction did not cover.
ABSENCE_NOT_RECOVERED = "(not recovered)"

#: This field does not exist for this kind of record at all. Mostly the
#: detail dialog simply omits such a row (see detail_fields.fields_for) --
#: an examiner does not need every cookie to state that it has no download
#: path. It is spelled here for the rare case a caller wants to say it
#: explicitly, e.g. a Downloads-specific field on a CARVED downloads
#: record, where the field's absence is itself informative.
ABSENCE_NOT_APPLICABLE = "(not applicable)"

#: The request itself did not carry this value.
#:
#: Used for position fixes: a fix is read from a request URL, and the
#: accuracy, the reported source and the fix time are present only if the
#: application put them there. When one is missing, none of the tokens
#: above is true:
#:
#:   ABSENCE_EMPTY          claims a stored column held nothing; there is
#:                          no column, only a query parameter.
#:   ABSENCE_NOT_DETERMINABLE  claims the evidence cannot answer; it can:
#:                          the parameter is not in the complete URL.
#:   ABSENCE_NOT_RECOVERED  claims a carve fell short; nothing was carved.
#:   ABSENCE_NOT_APPLICABLE claims the field does not exist for this kind
#:                          of row, but a position fix does have an
#:                          accuracy; this one did not report it.
#:
#: The application did not send it. That is a fact about the request and
#: is itself evidence: a fix with no accuracy is a weaker claim than one
#: reported to +-12 m.
ABSENCE_NOT_SUPPLIED = "(not supplied)"

#: Every declared absence token. Anything not in here is a real value.
ABSENCE_TOKENS = (ABSENCE_EMPTY, ABSENCE_NOT_DETERMINABLE,
                  ABSENCE_NOT_RECOVERED, ABSENCE_NOT_APPLICABLE,
                  ABSENCE_NOT_SUPPLIED)

#: The sentence behind each token -- what a tooltip shows an examiner who
#: has not met the distinction before. Five tokens, five DIFFERENT
#: sentences: two that read alike would be one state wearing two names,
#: and the whole point of the vocabulary is that they are not the same
#: fact.
ABSENCE_REASON = {
    ABSENCE_EMPTY:
        "The column exists on this record and holds no value. That is what "
        "the database stores, not a failure to read it.",
    ABSENCE_NOT_DETERMINABLE:
        "This cannot be known from the evidence. The bytes that would have "
        "carried it are exactly what was destroyed, so no value -- not even "
        "an empty one -- can honestly be shown here.",
    ABSENCE_NOT_RECOVERED:
        "This carve did not reach this column. The value may have existed; "
        "these bytes do not carry it.",
    ABSENCE_NOT_APPLICABLE:
        "This field does not exist for this kind of record.",
    ABSENCE_NOT_SUPPLIED:
        "The application that made this request did not include this "
        "value. Its absence is a fact about the request, not a gap in the "
        "parse.",
}


def absence_reason(token):
    """The sentence for an absence token, or "" for anything else.

    Total rather than raising: it is called with any display value, and a
    real value (0, False and "" included) returns "".
    """
    if not isinstance(token, str):
        return ""
    return ABSENCE_REASON.get(token, "")


def is_absence(value):
    """True only for one of the absence tokens above.

    Never truthiness: every token is a non-empty string, so `if value:`
    reads it as present, and 0, False and "" are real values that
    `if not value:` would read as absent.
    """
    return isinstance(value, str) and value in ABSENCE_TOKENS


class EvidenceSet:
    """The files opened, their sizes, and their hashes taken at consent."""

    def __init__(self, files, sizes, hashes):
        self.files = list(files)
        self.sizes = dict(sizes)
        self.hashes = dict(hashes)
        self.opened_utc = datetime.datetime.now(datetime.timezone.utc)

    @classmethod
    def from_paths(cls, paths, should_stop=None, on_bytes=None):
        """Hash every path in order, in 1 MiB chunks.

        should_stop, if given, is polled before each file and after each
        chunk; the first truthy return stops hashing. A partly read file
        contributes nothing to the result: a partial hash is not a hash of
        the file. With should_stop None (the default) no check is made.

        on_bytes(done, total), if given, is called after every chunk with
        the bytes hashed so far across every path and their total, so the
        Open dialog can show progress.
        """
        done, sizes, hashes = [], {}, {}
        total = 0
        if on_bytes is not None:
            for p in paths:
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
        read = 0
        for p in paths:
            if should_stop and should_stop():
                break
            size = os.path.getsize(p)
            h = hashlib.sha256()
            stopped = False
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    if should_stop and should_stop():
                        stopped = True
                        break
                    h.update(chunk)
                    if on_bytes is not None:
                        read += len(chunk)
                        on_bytes(read, total)
            if stopped:
                break
            done.append(p)
            sizes[p] = size
            hashes[p] = h.hexdigest()
        return cls(done, sizes, hashes)

    def verify(self):
        """Which files have changed since they were opened.

        Evidence should not change under an examiner. If it has, that is
        reportable, not something to paper over.
        """
        changed = []
        for p in self.files:
            try:
                h = hashlib.sha256()
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                if h.hexdigest() != self.hashes.get(p):
                    changed.append("%s changed since it was opened" % p)
            except OSError as exc:
                changed.append("%s is no longer readable: %s" % (p, exc))
        return changed


def origin_of(row):
    return row.get("Origin") or LIVE_ORIGIN


def describe_origin(row):
    """One line stating where this record came from.

    For a carved record that means the specific file and byte offset, not a
    generic 'recovered' label -- an examiner has to be able to go back to
    the bytes.
    """
    origin = origin_of(row)
    if not origin.startswith("Carved"):
        container = row.get("ContainerName") or row.get("ContainerType") or ""
        return "%s%s" % (LIVE_ORIGIN, " in %s" % container if container else "")
    bits = [origin]
    # A structured record resolved a real container before this row was
    # built (recovery_loader's carved_history_rows/deleted_records_rows); a
    # raw string carve never had one. The container is stated as not
    # determinable rather than omitted, so it is not read as merely not
    # displayed. `not container` also covers a row with no ContainerType
    # key at all.
    container = row.get("ContainerType")
    if container and container != CONTAINER_NOT_DETERMINABLE:
        bits.append("in %s" % container)
    else:
        bits.append("container not determinable")
    if row.get("Source"):
        bits.append("from %s" % row["Source"])
    # Zero is a valid offset and page number (the first page of a file or
    # of unallocated space), so presence is tested with `is not None`, not
    # truthiness.
    offset = row.get("Offset")
    if offset is not None:
        try:
            bits.append("@ 0x%08X" % int(offset))
        except (TypeError, ValueError):
            # Carved data is damaged data; a byte offset that failed to
            # parse must degrade the display, not raise out of a report.
            bits.append("@ offset %s (unparsed)" % offset)
    page = row.get("Page")
    if page is not None:
        bits.append("(page %s)" % page)
    if row.get("Method"):
        bits.append("by %s" % row["Method"])
    if row.get("Confidence"):
        # Its own clause: "...by Structured record reconstruction
        # confidence high" read as one run-on name.
        if bits:
            bits[-1] += ","
        bits.append("confidence %s" % row["Confidence"])
    return " ".join(bits)


def view_state(model, view_name):
    return {"view": view_name, "filters": model.chip_text(),
            "shown": model.rowCount(), "total": model.filter.total_count}


def export_stamp(evidence, state, shown, total):
    return {
        "tool_version": TOOL_VERSION,
        "exported_utc": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evidence": dict(evidence.hashes),
        "evidence_sizes": dict(evidence.sizes),
        "view_state": dict(state),
        "shown": shown,
        "total": total,
    }
