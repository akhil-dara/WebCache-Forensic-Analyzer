"""Where an export may be written, and where it never is.

Nothing this tool writes goes into the evidence folder. This module decides
whether a chosen path is safe; choosing it is the shell's job. Qt-free
except _documents_dir(), which imports Qt locally.

Paths are compared after os.path.realpath and normcase, so a junction or
symlink pointing into the evidence folder is refused like the folder
itself.
"""
import datetime
import os
import re

from . import settings

#: The settings key export destinations are remembered under (never
#: "last_evidence_dir").
LAST_EXPORT_DIR_KEY = "last_export_dir"

#: Added to the filename when the rows written are a subset of the view,
#: so a partial export says so wherever the file goes.
SUBSET_MARKER = "_FILTERED"

#: The three refusals, each defined once.
REFUSE_EXHIBIT = "That is the exhibit itself. Writing there would destroy it."
REFUSE_COMPANION = ("That is %s, one of the files this parse read. It is "
                    "part of the exhibit.")
REFUSE_DIRECTORY = ("That folder holds the evidence. Nothing is written "
                    "into it for the life of the case.")

#: The primary exhibit's extension, used only to word the refusal (the
#: database itself, or a companion file the parse read).
_EXHIBIT_EXTENSIONS = (".dat",)


def _norm(path):
    """The normalised form every comparison uses: realpath, then normcase.
    A path that cannot be resolved falls back to the path as given."""
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))
    except (OSError, ValueError):
        return os.path.normcase(os.path.abspath(path))


def _documents_dir():
    """Imports Qt locally, so this module does not depend on PySide6."""
    try:
        from PySide6.QtCore import QStandardPaths
        found = QStandardPaths.writableLocation(
            QStandardPaths.DocumentsLocation)
    except Exception:
        found = ""
    return found or os.path.expanduser("~")


def default_export_dir():
    """Where a save dialog opens: the last export folder if it still
    exists, else Documents, else home. Never the evidence folder.
    """
    directory = settings.get(LAST_EXPORT_DIR_KEY, "") or ""
    if directory and os.path.isdir(directory):
        return directory
    return _documents_dir()


#: The name's first part when the case has no number.
NO_CASE_PREFIX = "WebCache"
#: The tool's own prefix on a format's default basename, replaced by the
#: case number (or NO_CASE_PREFIX) in the name offered.
_TOOL_PREFIX = "webcache_"


def _name_part(text):
    """A case number as a filename part: letters, digits, "-" and "_"
    only, so a case number can never put a path in the name."""
    part = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text or "")).strip("-_")
    return part[:60]


#: Public name for the filename-part rule, used for what an export holds.
name_part = _name_part


def suggest_name(basename, extension, is_subset, case_number="", when=None):
    """The filename offered in the chooser:
    <case number>_<what>[_FILTERED]_<UTC date-time>.<ext>.

    Exports from several cases, or the same view exported twice, never
    collide and are told apart by their names: the case number leads
    (NO_CASE_PREFIX when none is set) and the UTC time of the export
    ends the stem. See SUBSET_MARKER."""
    when = when or datetime.datetime.now(datetime.timezone.utc)
    what = basename[len(_TOOL_PREFIX):] if basename.startswith(
        _TOOL_PREFIX) else basename
    stem = "%s_%s%s_%s" % (_name_part(case_number) or NO_CASE_PREFIX, what,
                           SUBSET_MARKER if is_subset else "",
                           when.strftime("%Y%m%d-%H%M%SZ"))
    if extension and not extension.startswith("."):
        extension = "." + extension
    return stem + (extension or "")


def evidence_paths(evidence_set, parser):
    """(files, dirs): every path this case must never write into.

    `files` is every file of the exhibit: the evidence set's files, the
    parser's db_path, and every name in parser.source_hashes (the files
    the parse read) resolved against each evidence directory. `dirs` is
    each such file's directory; anything under one is refused.

    With no evidence open both sets are empty.
    """
    files, dirs = set(), set()
    raw = []
    for path in list(getattr(evidence_set, "files", None) or []):
        raw.append(path)
    db_path = getattr(parser, "db_path", "") or ""
    if db_path:
        raw.append(db_path)
    for path in raw:
        files.add(_norm(path))
        dirs.add(_norm(os.path.dirname(os.path.abspath(path))))
    # source_hashes is keyed by basename, so each name is resolved against
    # every directory known to hold evidence.
    for name in (getattr(parser, "source_hashes", None) or {}):
        base = os.path.basename(str(name))
        if not base:
            continue
        for directory in list(dirs):
            files.add(_norm(os.path.join(directory, base)))
    return files, dirs


def refuse_reason(path, evidence_files, evidence_dirs):
    """"" when `path` is safe to write, else the reason. The most specific
    refusal is given: the database itself, a companion file, or the
    evidence folder.
    """
    if not path:
        return ""
    target = _norm(path)
    if target in (evidence_files or ()):
        name = os.path.basename(path)
        if os.path.splitext(name)[1].lower() in _EXHIBIT_EXTENSIONS:
            return REFUSE_EXHIBIT
        return REFUSE_COMPANION % name
    for directory in (evidence_dirs or ()):
        if target == directory or target.startswith(directory + os.sep):
            return REFUSE_DIRECTORY
    return ""


def safe_alternative(path, evidence_dirs):
    """The same filename in a folder outside the evidence folder, offered
    by SafeFolderDialog as its first choice.
    """
    name = os.path.basename(path) or "webcache_export"
    candidate = os.path.join(default_export_dir(), name)
    if refuse_reason(candidate, (), evidence_dirs):
        # The fallback folder is itself inside the evidence folder; home
        # is used instead.
        candidate = os.path.join(os.path.expanduser("~"), name)
    return candidate
