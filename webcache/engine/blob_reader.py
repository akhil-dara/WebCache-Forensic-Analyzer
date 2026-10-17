"""Bytes made readable: a hex dump, the strings inside, a structured decode.

Pure functions and the two numbers that size a page and a carve window.
No Qt, no I/O, no state, so the blob viewer's behaviour is tested headless
(tests/test_blob_reader.py) and widgets/hex_view.py only lays out panes.

THE OFFSET. hex_lines takes a base_offset because the left column must be
a position in the source. For a blob from a database column, byte 0 of the
blob is byte 0 of what is examined. For a window read from the middle of
an exhibit file it is not: the printed offset is the position in the file,
so a value copied from this pane can be found at that offset in any hex
editor.

NOTHING IS MATERIALISED. A hex dump of a large blob is megabytes of text.
hex_lines is called one page at a time, and extract_strings/
decode_blob_lines once per blob by a viewer that discards the result with
its dialog. No loader calls them.

NOTHING RAISES. These functions run on bytes from unallocated space or a
damaged database; a malformed blob renders as a decode error inside the
pane, never as an exception that removes the pane.
"""
import re

from . import download_decoder, sps_decoder

#: One page of hex. Big enough that most blobs in the sample fit whole,
#: small enough that a 388 KB certificate does not build 24,000 lines of
#: text to show sixteen of them.
HEX_PAGE_BYTES = 4096

#: The window read back around a carve offset. Declared here, beside the
#: page size, so the two numbers that bound what a viewer holds are
#: together.
CARVE_WINDOW = 1024

#: Sixteen, because every other hex editor an examiner will cross-check
#: against uses sixteen, and a row that does not line up with theirs makes
#: comparing two dumps a manual exercise.
BYTES_PER_LINE = 16

#: The hex column's exact width: 16 pairs plus 15 separating spaces. A
#: short final row is padded to this so its ASCII column stays under the
#: ASCII column of every row above it.
HEX_COLUMN_WIDTH = BYTES_PER_LINE * 3 - 1

#: A printable run worth reporting. Four is the conventional floor (the
#: same one download_decoder already uses); below it, arbitrary binary
#: produces more noise than signal.
MIN_STRING_RUN = 4

#: UTF-16LE first, so a wide string is claimed by the wide pattern rather
#: than shredded into single-character ASCII runs by the narrow one.
_STRING_RUN = re.compile(
    rb"(?:[\x20-\x7e]\x00){%d,}|[\x20-\x7e]{%d,}"
    % (MIN_STRING_RUN, MIN_STRING_RUN))

#: What an SPS property id without a documented meaning is labelled.
#: sps_decoder.KNOWN_HISTORY_PROPS names two ids (6 and 24), both derived
#: rather than documented by Microsoft; any other id is stated as
#: undocumented rather than given a plausible name.
NO_DOCUMENTED_MEANING = "— meaning not documented"

#: What the decode pane says when the bytes have no structured reading
#: (usually a raw carve window), so an empty pane is never shown.
NO_DECODE = "(no structured decode for these bytes)"

#: What identifies a Windows certificate-store entry: its own four-byte
#: marker at offset 4. Checked BEFORE anything speculative runs, because a
#: blob that names itself should be named rather than guessed at.
CERT_MARKER, CERT_MARKER_AT = b"CERT", 4
CERT_BLOB_NOTE = "Windows CERT blob (TLS certificate store entry)"

#: The caveat above a reading of bytes nothing identified. It goes before
#: the reading, so it is read before the labels are. Without it, a
#: certificate that contains a URL could read as a download record.
SPECULATIVE_DECODE = (
    "Nothing identifies these bytes. What follows is the download-record "
    "decoder's reading of them, offered because it grades its own "
    "confidence — treat it as a hypothesis to check against the hex and "
    "the strings, not as a finding.")

def hex_lines(data, start, count, base_offset=0):
    """One formatted hex row per BYTES_PER_LINE bytes of data[start:].

    The offset printed is `base_offset + start + i`: the row's position in
    its source, the blob for a MemoryBlob (base_offset 0) and the exhibit
    file for a FileWindowBlob (base_offset = the window start).

    `count` is clamped to the data, so paging past the end yields fewer
    rows, never padding.
    """
    try:
        buf = memoryview(data)
    except TypeError:
        return []
    start = max(0, int(start))
    end = min(len(buf), start + max(0, int(count)))
    out = []
    for pos in range(start, end, BYTES_PER_LINE):
        chunk = bytes(buf[pos:pos + BYTES_PER_LINE])
        hexpart = " ".join("%02X" % b for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append("%08X  %-*s  %s"
                   % (base_offset + pos, HEX_COLUMN_WIDTH, hexpart, ascii_part))
    return out


def extract_strings(data):
    """Every printable run of MIN_STRING_RUN+ characters, in offset order.

    Returns [(offset, "ascii"|"utf-16-le", text)]. Not capped: for a blob
    no decoder understands, these strings are the only readable content.

    The encoding is decided from the bytes: a UTF-16LE run has 0x00 in
    every odd position, and an ASCII run (0x20-0x7e only) never contains
    one.
    """
    if not data:
        return []
    try:
        raw = bytes(data)
    except TypeError:
        return []
    out = []
    for match in _STRING_RUN.finditer(raw):
        run = match.group()
        try:
            if len(run) >= 2 * MIN_STRING_RUN and not any(run[1::2]):
                out.append((match.start(), "utf-16-le",
                            run.decode("utf-16-le", "replace")))
            else:
                out.append((match.start(), "ascii",
                            run.decode("ascii", "replace")))
        except (UnicodeDecodeError, ValueError):
            continue
    return out


def _value_text(prop):
    """One property value, rendered without claiming anything about it.

    A VT_FILETIME prints as its raw integer here. The decoded form of id
    24 is stated once, in the summary above, WITH its "local time"
    caveat -- printing a formatted timestamp beside seven other property
    ids would invite it to be read as another UTC column.
    """
    value = prop.get("value")
    if isinstance(value, (bytes, bytearray)):
        return "%d bytes: %s" % (len(value), bytes(value).hex(" ").upper())
    if value is None:
        return "(no value)"
    text = str(value)
    return text if text.strip() else "(empty)"


def _sps_lines(data):
    forensics = sps_decoder.extract_history_forensics(data)
    lines = []
    if forensics.get("visit_count") is not None:
        lines.append("Visit count (SPS id 6): %d" % forensics["visit_count"])
    if forensics.get("last_visit_local") is not None:
        # Labelled LOCAL every time: every other timestamp column in this
        # database is UTC (see sps_decoder's module docstring).
        lines.append(
            "Last visit (SPS id 24): %s  — LOCAL time, not UTC "
            "(raw FILETIME %s)"
            % (forensics["last_visit_local"].strftime("%Y-%m-%d %H:%M:%S"),
               forensics.get("last_visit_local_raw")))
    if forensics.get("page_title"):
        lines.append("Page title: %s" % forensics["page_title"])

    sets = forensics.get("property_sets") or []
    if not sets:
        lines.append("The 1SPS signature is present but no property set "
                     "parsed out of these bytes.")
        return lines
    for pset in sets:
        lines.append("")
        lines.append("— property set FMTID %s (at offset 0x%08X)"
                     % (pset.get("fmtid", ""), pset.get("offset", 0)))
        # Every property, sorted by id, including those without a known
        # meaning; this is the only place they are shown.
        for pid in sorted(pset.get("properties") or {}):
            prop = pset["properties"][pid]
            lines.append("    id %-4d %-34s [%s] = %s"
                         % (pid, prop.get("name") or NO_DOCUMENTED_MEANING,
                            prop.get("vt_name", ""), _value_text(prop)))
            if prop.get("meaning"):
                lines.append("           %s" % prop["meaning"])
            if not prop.get("decoded_ok", True):
                lines.append("           (this value did not decode cleanly "
                             "— the raw bytes are in the hex pane)")
    return lines


def _http_lines(data):
    text = bytes(data).decode("utf-8", errors="replace")
    return [line for line in text.split("\r\n") if line.strip()]


def _download_lines(data):
    decoded = download_decoder.decode_download_blob(bytes(data))
    lines = ["Download record confidence: %s" % decoded.get("confidence")]
    if decoded.get("confidence") == "none":
        lines.append("Nothing in these bytes anchors as a download record. "
                     "The strings pane is the reading of last resort.")
        return lines
    for label, key in (("Local path", "local_path"),
                       ("Source URL", "source_url"),
                       ("File size", "file_size"),
                       ("GUID", "guid"),
                       ("GUID offset", "guid_offset"),
                       ("Download time (UTC)", "download_time_utc"),
                       ("Download time (raw FILETIME)", "download_time_raw")):
        value = decoded.get(key)
        if value is not None:
            lines.append("%s: %s" % (label, value))
    # Every note, in full: they give the byte offset a FILETIME was found
    # at and whether the GUID came from the fixed header or from string
    # content, so the examiner can weigh the match.
    for note in decoded.get("notes") or ():
        lines.append("Note: %s" % note)
    return lines


def decode_blob_lines(data, column_name=""):
    """The structured reading of a blob, as lines of text.

    States the detected class first, so it is clear the decode was chosen
    from the content, not from the column. `column_name` is only printed;
    it never steers the decode.

    Never raises: a decode failure renders as "(decode error: ...)" inside
    the returned lines.
    """
    if not data:
        return ["Detected class: empty", NO_DECODE]
    lines = []
    try:
        raw = bytes(data)
        klass = sps_decoder.classify_response_headers(raw)
        lines.append("Detected class: %s" % klass)
        if column_name:
            lines.append("Stored in column: %s" % column_name)
        marked_cert = raw[CERT_MARKER_AT:CERT_MARKER_AT + len(CERT_MARKER)]             == CERT_MARKER
        if klass == "sps":
            lines.extend(_sps_lines(raw))
        elif klass == "http":
            lines.extend(_http_lines(raw))
        elif marked_cert:
            # It named itself, so name it -- and do NOT run a download
            # decoder over a certificate. Its strings are still in the
            # strings pane, where a string is a string rather than a
            # "Source URL".
            lines.append(CERT_BLOB_NOTE)
            lines.append("These bytes identify themselves, so no "
                         "speculative decode is attempted. Their readable "
                         "content is in the strings pane.")
        else:
            lines.append(SPECULATIVE_DECODE)
            lines.extend(_download_lines(raw))
        if marked_cert and klass in ("sps", "http"):
            # A blob that carries the marker AND parsed as something else
            # is worth naming either way.
            lines.append(CERT_BLOB_NOTE)
    except Exception as exc:          # noqa: BLE001 -- see module docstring
        lines.append("(decode error: %s)" % exc)
    if len(lines) <= 1:
        lines.append(NO_DECODE)
    return lines


def hex_dump(data, base_offset=0):
    """The whole dump, for the clipboard.

    Separate from hex_lines' paging, so Copy always copies the whole blob,
    not the page on screen. BlobPane.copy_full_hex states the character
    count first.
    """
    return hex_lines(data, 0, len(data or b""), base_offset)

