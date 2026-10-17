"""Read the exhibit back at a carve offset, so the carve can be checked.

A recovered record states its source file and byte offset; this module
reads the bytes there at display time, so anyone can open the same file in
any hex editor and verify them. Bytes are re-read rather than stored at
scan time, because what is read from the exhibit can be verified and a
stored snapshot cannot.

Every open uses mode "rb". The carved `source` value is reduced to a
basename before it is joined to the evidence directory, so damaged bytes
cannot direct a read outside the folder that was opened.
"""
import os

from .blob_reader import CARVE_WINDOW

__all__ = ["CARVE_WINDOW", "read_carve_window", "offset_within"]


def _resolve(db_path, source):
    """(path, note fragment): the file the bytes are read from.

    The database's directory plus the basename of `source`. If that file
    is gone (a carved transaction log since deleted), the database itself
    is read instead, and the note says so.
    """
    directory = os.path.dirname(os.path.abspath(db_path))
    db_name = os.path.basename(db_path)
    name = os.path.basename(str(source or "")).strip()
    if not name or name == db_name:
        return db_path, db_name
    candidate = os.path.join(directory, name)
    if os.path.isfile(candidate):
        return candidate, name
    return db_path, ("%s is not in the evidence folder — these bytes were "
                     "read from %s instead" % (name, db_name))


def read_carve_window(db_path, source, offset, window=CARVE_WINDOW):
    """(data, window_start, note) around `offset` in the carve's source file.

    The window is centred on the offset and aligned to 16 bytes, so its
    rows fall on the same boundaries as a hex editor's view of the file.

    `note` is always a non-empty sentence, including when `data` is empty:
    an empty read is a statement about the read, not about the evidence.
    """
    if offset is None:
        return b"", 0, ("This record carries no source offset, so there is "
                        "nothing to read back from the exhibit.")
    try:
        position = int(offset)
    except (TypeError, ValueError):
        return b"", 0, ("Offset %r is not a number, so no position in the "
                        "exhibit can be derived from it." % (offset,))
    if position < 0:
        return b"", 0, ("Offset %s is negative; no position in the exhibit "
                        "corresponds to it." % "{:,}".format(position))

    path, resolved_note = _resolve(db_path, source)
    name = os.path.basename(path)
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return b"", 0, "Could not read %s: %s" % (name, exc)
    if position >= size:
        return b"", 0, ("Offset %s is past the end of %s (%s bytes)."
                        % ("{:,}".format(position), name,
                           "{:,}".format(size)))

    window = max(16, int(window))
    start = max(0, (position - window // 2) & ~0xF)
    try:
        with open(path, "rb") as handle:
            handle.seek(start)
            data = handle.read(window)
    except OSError as exc:
        return b"", 0, "Could not read %s: %s" % (name, exc)

    if not data:
        return b"", start, ("Nothing could be read from %s at offset %s, "
                            "although the file reports %s bytes."
                            % (name, "{:,}".format(start),
                               "{:,}".format(size)))
    inside = offset_within(position, start, len(data))
    return data, start, (
        "%s bytes read from %s at 0x%08X — the record begins %s bytes in. "
        "%s" % ("{:,}".format(len(data)), name, start,
                "{:,}".format(inside), resolved_note))


def offset_within(position, start, length):
    """Where the record begins inside the window, clamped to the bytes
    actually read, so the marker never lands on a row that is not there.
    """
    try:
        return max(0, min(max(0, int(length) - 1), int(position) - int(start)))
    except (TypeError, ValueError):
        return 0
