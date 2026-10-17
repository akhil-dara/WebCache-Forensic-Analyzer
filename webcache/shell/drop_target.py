"""What a drop onto the window names.

A drop names an exhibit, as the Open Database dialog does, and leads to the
same Open Evidence dialog; nothing here opens, hashes or parses a file. The
decision is made by name only (isdir, splitext, one listdir per folder).

A verdict either names one exhibit or gives a reason it cannot:

    DropVerdict(path="C:\\...\\WebCacheV01.dat", reason="")   -> open this
    DropVerdict(path="", reason="...")                          -> refuse

- one .dat file            -> that file
- a folder                 -> the WebCacheV01.dat directly inside it, if any
- a .dat with its own logs -> the .dat (the logs are in its evidence scope)
- several databases        -> refused, with the count
- any other file           -> refused, by name
- text or a web URL        -> nothing droppable
"""
import os
from collections import namedtuple

from ..engine.ese_parser import evidence_scope

#: A drop names an exhibit or a reason, never both and never neither.
DropVerdict = namedtuple("DropVerdict", "path reason")

#: The name searched for in a dropped folder. A folder holding several
#: .dat files is not resolved to one of them.
PRIMARY_NAME = "webcachev01.dat"

#: What a dropped file must be: by extension, since working copies are
#: often renamed for the case.
EXHIBIT_EXTENSIONS = (".dat",)

NOTHING_LOCAL = ("Nothing that can be opened was dropped — drag a "
                 "WebCacheV01.dat file, or the folder that holds one.")


def _key(path):
    """The form two paths share when they name the same file: QUrl
    returns forward slashes on Windows, and the filesystem is case-
    insensitive."""
    return os.path.normcase(os.path.normpath(path))


def local_paths(mime):
    """The local files a drag carries, normalised; [] for text, web URLs
    and drags that offer no file."""
    if mime is None or not mime.hasUrls():
        return []
    paths = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        local = url.toLocalFile()
        if local:
            paths.append(os.path.normpath(local))
    return paths


def _resolve(path):
    """One dropped item -> (exhibit path, refusal reason). Exactly one of
    the two is ever non-empty."""
    name = os.path.basename(path.rstrip("\\/")) or path
    if os.path.isdir(path):
        try:
            entries = sorted(os.listdir(path))
        except OSError:
            return "", 'The folder "%s" could not be read.' % name
        for entry in entries:
            if entry.lower() == PRIMARY_NAME:
                return os.path.join(path, entry), ""
        # Direct children only: a dropped folder can be a whole volume,
        # and a recursive search could pick one database among several.
        return "", ('The folder "%s" holds no WebCacheV01.dat. Drop the '
                    'database itself, or the folder it sits in.' % name)
    if os.path.splitext(path)[1].lower() in EXHIBIT_EXTENSIONS:
        return path, ""
    return "", ('"%s" is not a WebCache database — a dropped exhibit has '
                'to be a .dat file.' % name)


def _strays(exhibit, paths):
    """Dropped items that this exhibit's evidence set does not include.

    Selecting all files in a WebCache folder drops the database with its
    logs; membership of evidence_scope() decides what belongs. The folder
    the exhibit was found in counts as part of the drop too.
    """
    accounted = {_key(p) for p in evidence_scope(exhibit)}
    accounted.add(_key(exhibit))
    accounted.add(_key(os.path.dirname(exhibit)))
    return [p for p in paths if _key(p) not in accounted]


def classify(paths):
    """The verdict for a whole drop (see the module docstring)."""
    if not paths:
        return DropVerdict("", NOTHING_LOCAL)

    candidates, refusals = [], []
    for path in paths:
        exhibit, reason = _resolve(path)
        if exhibit:
            candidates.append(exhibit)
        else:
            refusals.append(reason)

    unique, seen = [], set()
    for exhibit in candidates:
        if _key(exhibit) not in seen:
            seen.add(_key(exhibit))
            unique.append(exhibit)

    if len(unique) > 1:
        return DropVerdict("", "%d databases were dropped at once — open one "
                               "exhibit at a time." % len(unique))
    if not unique:
        # One refused item is named; several are counted.
        return DropVerdict("", refusals[0] if len(paths) == 1 else
                           "None of the %d dropped items is a WebCache "
                           "database." % len(paths))

    exhibit = unique[0]
    stray = _strays(exhibit, paths)
    if stray:
        return DropVerdict("", '"%s" was dropped alongside %d item(s) that '
                               'are not part of its evidence set — drop the '
                               'database on its own.'
                               % (os.path.basename(exhibit), len(stray)))
    return DropVerdict(exhibit, "")
