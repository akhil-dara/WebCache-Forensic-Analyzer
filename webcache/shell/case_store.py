"""Opening the case file for the exhibit on screen.

The case file (engine/case_db.py) holds tags, comments, bookmarks, saved
searches and case metadata. It lives in paths.cases_dir(), with the
application and never beside the exhibit: the evidence folder is never
written to, and a PyInstaller temporary directory would be deleted on exit.

It is keyed by the evidence's SHA-256, not its path, so the same exhibit
copied to another folder or workstation reaches the same case file.
"""
import datetime
import json
import logging

from .. import paths
from ..engine.case_db import CaseDb

_LOG = logging.getLogger(__name__)

#: How much of the digest names the file: 16 hex characters (64 bits) is
#: collision-free in practice and readable. Every export records the full
#: hash.
KEY_LENGTH = 16

#: The suffix, so case files are recognisable in a folder listing.
SUFFIX = ".case.sqlite"


def evidence_key(evidence_set):
    """The SHA-256 this case file is keyed by, or "".

    The first file's hash: evidence_scope() lists the .dat first, and the
    transaction logs, which Windows rewrites, after it.
    """
    hashes = getattr(evidence_set, "hashes", None) or {}
    files = getattr(evidence_set, "files", None) or []
    for path in files:
        digest = hashes.get(path)
        if digest:
            return digest
    for digest in hashes.values():
        if digest:
            return digest
    return ""


def case_path_for(evidence_set):
    """Where this exhibit's case file lives, or None with no hash."""
    digest = evidence_key(evidence_set)
    if not digest:
        return None
    return paths.cases_dir() / ("%s%s" % (digest[:KEY_LENGTH], SUFFIX))


def open_case(evidence_set):
    """An open CaseDb for this exhibit, or None.

    None, never an exception, for every failure: no evidence, no hash, an
    unwritable cases directory (read-only media), a corrupt case file. The
    application stays usable without a case file.
    """
    path = case_path_for(evidence_set)
    if path is None:
        return None
    try:
        return CaseDb().open(str(path))
    except Exception as exc:                          # noqa: BLE001
        _LOG.warning("Could not open the case file at %s: %s", path, exc)
        return None


#: Every occasion this exhibit was opened: when, and each file with its
#: SHA-256 and size. Appended, never overwritten.
OPEN_LOG_META_KEY = "evidence_opened"


def record_open(case, evidence_set):
    """Append one open to the case file. False, never an exception, when
    there is no case file."""
    if case is None or evidence_set is None:
        return False
    hashes = getattr(evidence_set, "hashes", None) or {}
    sizes = getattr(evidence_set, "sizes", None) or {}
    entry = {
        "opened_utc": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": [{"path": p, "sha256": hashes.get(p, ""),
                   "bytes": sizes.get(p, 0)}
                  for p in (getattr(evidence_set, "files", None) or [])],
    }
    try:
        existing = json.loads(case.get_meta(OPEN_LOG_META_KEY) or "[]")
        if not isinstance(existing, list):
            existing = []
    except (ValueError, TypeError):
        existing = []
    existing.append(entry)
    try:
        case.set_meta(OPEN_LOG_META_KEY, json.dumps(existing))
    except Exception as exc:                          # noqa: BLE001
        _LOG.warning("Could not record the open in the case file: %s", exc)
        return False
    return True
