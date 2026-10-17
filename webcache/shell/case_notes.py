"""Tags and comments on records, as every surface applies them: the
record dialog, the details pane, a grid's right-click menu and the Tagged
view. Qt-free.

A note attaches to a record, live or recovered, keyed by
engine.case_db.CaseDb.record_key. An aggregate (a domain, a period, a
place) or a raw table row has no record identity and cannot carry one.

Notes are kept in the case file, never in the evidence folder.
"""
from ..engine.case_db import CaseDb

#: Offered first on every surface, in this order.
PRESET_TAGS = ("Relevant", "Suspicious", "Follow up", "Not relevant")


def record_entry(row):
    """The engine record a row stands for, or None when it has none."""
    if not isinstance(row, dict):
        return None
    entry = row.get("_record")
    if not isinstance(entry, dict):
        return None
    if entry.get("RecoverySource") or entry.get("EntryId") is not None:
        return entry
    return None


def is_taggable(row):
    return record_entry(row) is not None


def _entries(rows):
    seen, out = set(), []
    for row in rows or ():
        entry = record_entry(row)
        if entry is None:
            continue
        key = CaseDb.record_key(entry)
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def tags_of(case, row):
    entry = record_entry(row)
    if case is None or entry is None:
        return []
    return case.tags_for_entry(entry)


def comments_of(case, row):
    entry = record_entry(row)
    if case is None or entry is None:
        return []
    return case.comments_for_entry(entry)


def tag_counts(case, rows):
    """{tag: how many records of `rows` carry it}."""
    counts = {}
    if case is None:
        return counts
    for entry in _entries(rows):
        for tag in case.tags_for_entry(entry):
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def set_tag(case, rows, tag, on):
    """Put `tag` on (or take it off) every record of `rows`. Returns how
    many records changed."""
    tag = (tag or "").strip()
    if not tag:
        raise ValueError("A tag needs a name.")
    if case is None:
        return 0
    changed = 0
    for entry in _entries(rows):
        has = tag in case.tags_for_entry(entry)
        if on and not has:
            case.add_tag(CaseDb.record_key(entry), tag)
            changed += 1
        elif not on and has:
            for key in CaseDb.record_keys(entry):
                case.remove_tag(key, tag)
            changed += 1
    return changed


def add_comment(case, rows, text, author=""):
    """Add one comment to every record of `rows`. Returns how many."""
    text = (text or "").strip()
    if not text:
        raise ValueError("A comment needs text.")
    if case is None:
        return 0
    entries = _entries(rows)
    for entry in entries:
        case.add_comment(CaseDb.record_key(entry), text, author or "")
    return len(entries)


def known_tags(case):
    """Every tag worth offering: the presets, then the case's own."""
    own = [tag for tag, _n in (case.tag_counts() if case is not None else ())]
    return list(PRESET_TAGS) + sorted(t for t in own if t not in PRESET_TAGS)
