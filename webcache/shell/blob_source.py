"""Bytes, and where they came from, behind one interface.

widgets/hex_view.py paints hex, strings and a decode, and may not import
the engine (tests/test_structure.py). BlobSource is the boundary: the
shell builds an object that pages, hashes and exports, and the widget does
not need to know whether the bytes came from a database column or were
read from the exhibit file.

Two implementations; the difference is the offset.

MemoryBlob wraps a bytes object already in memory, the same object
row["_record"]["ResponseHeaders_raw"] holds, never a copy: all_bytes()
returns the original and read() slices a memoryview. base_offset is 0,
because byte 0 of a blob is byte 0 of what is examined.

FileWindowBlob reads a window from the exhibit at display time, and its
base_offset is where the window starts in the file, so the bytes can be
checked against any hex editor.

Nothing here opens anything: reading is carve_reader's, hashing is
hashlib's, and no path is handed to the operating system
(tests/test_no_open_paths.py).
"""
import hashlib
import os
import re

from ..engine import blob_reader, carve_reader, ese_parser
from .. import provenance
from .record_kinds import (K_CARVED_STRING, K_CARVED_STRUCT, K_CERT,
                           K_DOWNLOAD, K_FILE_ACCESS, K_HISTORY)

#: The blobs a record can carry and their labels, declared once:
#: detail_fields uses it for its Binary field rows and blobs_for for its
#: tabs, so Enter on a Binary row opens the tab of the same name.
BLOB_FIELDS = (("ResponseHeaders_raw", "Response headers / property store"),
               ("RequestHeaders_raw", "Request headers"),
               ("Blob_raw", "Certificate blob (DER)"))

#: Which record kinds carry which of the above.
_KIND_BLOBS = {
    K_HISTORY: ("ResponseHeaders_raw", "RequestHeaders_raw"),
    K_FILE_ACCESS: ("ResponseHeaders_raw", "RequestHeaders_raw"),
    K_DOWNLOAD: ("ResponseHeaders_raw", "RequestHeaders_raw"),
    K_CARVED_STRUCT: ("ResponseHeaders_raw", "RequestHeaders_raw"),
    K_CERT: ("Blob_raw",),
}

#: The kinds whose bytes are not in the parser at all, only at an offset.
_CARVED_KINDS = (K_CARVED_STRUCT, K_CARVED_STRING)

CARVE_TAB_LABEL = "Bytes at the carve offset"

#: The statement above a carve window: the record was found at this
#: offset, and these are the bytes there. One line at the pane's width.
VERIFICATION_STATEMENT = (
    "These bytes were read back from the evidence just now; nothing in the "
    "evidence folder is written to. The same file at the same offset in any "
    "hex editor should show these rows.")

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9_.-]")
_FILENAME_MAX = 60


def _safe_name(label):
    name = _UNSAFE_FILENAME.sub("_", str(label or ""))[:_FILENAME_MAX]
    return name.strip("_") or "blob"


class BlobSource:
    """One blob, and everything a viewer needs to say about it.

    Subclasses supply the bytes and the base offset; everything else --
    the hash, the content-derived type, the paging, the lazy string and
    decode lists -- is decided once, here, so the two implementations
    cannot describe the same bytes differently.
    """

    #: Read from the source rather than redeclared in widgets/, so the
    #: page size has one definition (blob_reader.HEX_PAGE_BYTES).
    page_bytes = blob_reader.HEX_PAGE_BYTES

    #: True only where an opening hash exists to compare against.
    verify_supported = False

    def __init__(self, label, data, field_key="", base_offset=0,
                 origin_note="", note=""):
        self.label = label
        self.field_key = field_key
        self._data = data if isinstance(data, (bytes, bytearray)) else b""
        self.base_offset = int(base_offset)
        self.origin_note = origin_note
        self.note = note
        self.size = len(self._data)
        # Decided from the content, never from the column, so a column
        # expected to hold headers that holds a PNG is reported as PNG.
        self.detected_type = ese_parser.detect_blob_type(bytes(self._data))
        # THIS TOOL'S hash of the bytes as extracted. Never claimed to
        # relate to any value the database stores -- a certificate
        # record's own Thumbprint has an underivable relationship to this
        # number and asserting one would be inventing a fact.
        self.sha256 = hashlib.sha256(bytes(self._data)).hexdigest()
        self._strings = None
        self._decode = None

    # --- bytes -----------------------------------------------------------

    def all_bytes(self):
        """The ORIGINAL object where there is one. See the module
        docstring on why this is not a defensive copy."""
        return self._data

    def read(self, start, count):
        view = memoryview(self._data)
        start = max(0, int(start))
        return bytes(view[start:start + max(0, int(count))])

    # --- rendering, all lazy ---------------------------------------------

    def hex_page(self, start, count=None):
        return blob_reader.hex_lines(
            self._data, start, self.page_bytes if count is None else count,
            self.base_offset)

    def full_hex(self):
        """Every line, for the clipboard. Not cached: it is megabytes of
        text for a large blob, and is wanted once if at all."""
        return blob_reader.hex_dump(self._data, self.base_offset)

    def decode_lines(self):
        if self._decode is None:
            self._decode = self._build_decode()
        return self._decode

    def strings(self):
        if self._strings is None:
            self._strings = blob_reader.extract_strings(self._data)
        return self._strings

    def _build_decode(self):
        return blob_reader.decode_blob_lines(self._data, self.field_key)

    # --- export ----------------------------------------------------------

    def suggested_filename(self):
        return _safe_name(self.label) + ".bin"

    # --- the pane's own header -------------------------------------------

    def header_rows(self):
        """[(label, displayed value, text to copy)]. Empty for a blob that
        is simply a column value -- there is nothing to state about it
        that the tab label and the type chip do not already say."""
        return []

    def verify(self):
        return ("No opening hash is available in this session, so there is "
                "nothing to compare this file against.")


class MemoryBlob(BlobSource):
    """A blob already resident in the parser, wrapped by reference."""

    def __init__(self, label, data, field_key=""):
        super().__init__(
            label, data, field_key=field_key, base_offset=0,
            origin_note=(
                "These bytes are the value of the %s column on this record, "
                "as the parser read it when the exhibit was opened. Offsets "
                "below are positions within the blob itself."
                % (field_key or "source")))


class FileWindowBlob(BlobSource):
    """A window read back out of the exhibit around a carve offset.

    The signature carries `source` as well as `db_path`, which §3.7's own
    mechanics require: a carved record names its file by BASENAME and the
    read has to be resolved inside the evidence directory rather than
    steered by whatever a damaged record happens to hold.
    """

    def __init__(self, label, db_path, source, record_offset,
                 window=carve_reader.CARVE_WINDOW, evidence_set=None):
        data, start, note = carve_reader.read_carve_window(
            db_path, source, record_offset, window)
        self.db_path = db_path
        self.source = source
        self.record_offset = record_offset
        self.window_start = start
        self.requested_window = window
        self.verification_statement = VERIFICATION_STATEMENT
        self._evidence_set = evidence_set
        super().__init__(label, data, field_key="", base_offset=start,
                         origin_note=note, note=note)
        self.resolved_path = self._resolved_path(db_path, source)
        self.verify_supported = self._can_verify()

    @staticmethod
    def _resolved_path(db_path, source):
        directory = os.path.dirname(os.path.abspath(db_path or ""))
        name = os.path.basename(str(source or "")).strip()
        if name:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
        return db_path or ""

    def _build_decode(self):
        """A raw window has no structured reading, and says so.

        Running the download decoder over arbitrary bytes and reporting
        on the result would dress a coincidence up as a finding.
        """
        return [blob_reader.NO_DECODE]

    def suggested_filename(self):
        """Named after where the bytes came from, not what they are --
        carve_0001A4F0.bin records the offset in the file itself."""
        try:
            return "carve_%08X.bin" % int(self.record_offset)
        except (TypeError, ValueError):
            return "carve_window.bin"

    def header_rows(self):
        if not self.size:
            return [("Nothing was read", self.note, self.note)]
        name = os.path.basename(self.resolved_path) or "(unknown file)"
        try:
            position = int(self.record_offset)
        except (TypeError, ValueError):
            position = self.window_start
        inside = carve_reader.offset_within(position, self.window_start,
                                            self.size)
        return [
            ("Source file", name, name),
            ("Record offset", "%s   (0x%08X)" % ("{:,}".format(position),
                                                 position),
             "0x%08X" % position),
            ("Window shown",
             "%s bytes from 0x%08X — the record begins %s bytes in"
             % ("{:,}".format(self.size), self.window_start,
                "{:,}".format(inside)),
             "0x%08X" % self.window_start),
        ]

    # --- has the exhibit moved under us? ---------------------------------

    def _matching_file(self):
        """The evidence set's own spelling of this path, or None.

        Compared with normcase/abspath rather than string equality: the
        evidence set stores the path the examiner chose and this module
        resolves its own, and on Windows those can differ in case and
        separator while naming the same file.
        """
        if self._evidence_set is None or not self.resolved_path:
            return None
        mine = os.path.normcase(os.path.abspath(self.resolved_path))
        for path in getattr(self._evidence_set, "files", ()):
            if os.path.normcase(os.path.abspath(path)) == mine:
                return path
        return None

    def _can_verify(self):
        path = self._matching_file()
        return bool(path and self._evidence_set.hashes.get(path))

    def verify(self):
        """Re-hash THIS file and compare it with its opening hash.

        Evidence should not change under an examiner. If it has, that is
        reportable rather than something to paper over -- so the exact
        wording EvidenceSet.verify() already produces is passed straight
        through rather than softened.
        """
        path = self._matching_file()
        if not path:
            return super().verify()
        single = provenance.EvidenceSet(
            [path], {path: self._evidence_set.sizes.get(path, 0)},
            {path: self._evidence_set.hashes.get(path, "")})
        changed = single.verify()
        if changed:
            return changed[0]
        return "%s — unchanged since it was opened." % os.path.basename(path)


# --- what a row offers --------------------------------------------------

def blobs_for(row, db_path="", evidence_set=None):
    """Every blob a row can show, in tab order.

    The record's OWN blobs first and the carve window last: a carved
    record that also recovered a property store has something the
    database itself stored, and that is the stronger reading of the two.

    A carve window is offered only when there is an exhibit path to read
    it from. With no database open there is no claim to make about what
    sits at an offset in it, and inventing an empty tab that says so
    would be a placeholder where nothing applies.
    """
    if not isinstance(row, dict):
        return []
    kind = row.get("_kind")
    record = row.get("_record")
    out = []
    if isinstance(record, dict):
        labels = dict(BLOB_FIELDS)
        for key in _KIND_BLOBS.get(kind, ()):
            data = record.get(key)
            # Empty blobs are SKIPPED, not shown as an empty tab: a tab
            # with nothing in it says "there is binary data here" and
            # then fails to show any.
            if isinstance(data, (bytes, bytearray)) and len(data):
                out.append(MemoryBlob(labels.get(key, key), data, key))
    if kind in _CARVED_KINDS and db_path:
        # Two carved row builders (carved_file_access_rows,
        # carved_downloads_rows) keep Offset/Source only on row["_record"],
        # so this falls back to it as detail_fields._merged_source does.
        # Offset 0 is a valid offset (the file's first byte), so absence
        # is tested with `is None`, never truthiness.
        rec = record if isinstance(record, dict) else {}
        source_val = row.get("Source") or rec.get("Source")
        offset_val = row.get("Offset")
        if offset_val is None:
            offset_val = rec.get("Offset")
        out.append(FileWindowBlob(
            CARVE_TAB_LABEL, db_path, source_val, offset_val,
            evidence_set=evidence_set))
    return out


def blobs_for_cells(columns, cells):
    """Every bytes cell of one Table Browser row, labelled by its column.

    Any binary column of any ESE table, including one no decoder reads,
    gets a hex dump and a strings list.
    """
    out = []
    for index, cell in enumerate(cells or ()):
        if not isinstance(cell, dict):
            continue
        data = cell.get("raw")
        if not isinstance(data, (bytes, bytearray)) or not len(data):
            continue
        name = (columns[index] if index < len(columns or ())
                else "column %d" % (index + 1))
        out.append(MemoryBlob(name, data, name))
    return out
