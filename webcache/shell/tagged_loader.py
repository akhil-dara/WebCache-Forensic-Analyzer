"""The Tagged view's rows: every record, live or recovered, that carries
a tag or a comment in this exhibit's case file.

Rows are timeline_loader.member_record_rows -- the same shape every
record list in the application uses, so the record dialog, the basis
badges, the carved styling and Export view all apply unchanged -- with
two cells of the examiner's own added: Tags and Comments.
"""
from ..engine.case_db import CaseDb
from . import timeline_loader

#: Between two comments in the one Comments cell.
COMMENT_SEPARATOR = " | "


def _noted_keys(case):
    return set(case.all_tags()) | set(case.all_comments())


def tagged_rows(case, live_entries, recovered_entries=()):
    """[row] for every record of either list carrying a tag or comment."""
    if case is None:
        return []
    keys = _noted_keys(case)
    if not keys:
        return []
    live = [e for e in live_entries or ()
            if any(k in keys for k in CaseDb.record_keys(e))]
    carved = [e for e in recovered_entries or ()
              if any(k in keys for k in CaseDb.record_keys(e))]
    entries = live + carved
    rows = timeline_loader.member_record_rows(
        entries, carved_ids={id(e) for e in carved})
    for row, entry in zip(rows, entries):
        row["Tags"] = ", ".join(case.tags_for_entry(entry))
        row["Comments"] = COMMENT_SEPARATOR.join(
            c["comment"] for c in case.comments_for_entry(entry))
    return rows
