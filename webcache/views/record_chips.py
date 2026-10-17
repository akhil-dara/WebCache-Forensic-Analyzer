"""Quick-filter chips shared by the views whose rows are visits.

History and File Access both list visits that can appear more than once:
repeated carves of one record (Copies) and a History record with its
MSHist daily copy (SameVisit). One definition here, so the two views offer
the same chips, filter by the same rule and say the same thing beside the
count -- and neither view imports the other.
"""
from ..widgets.record_filter import Condition
from .records_view import QuickFilter


def hide_shown_twins(visible):
    """"One row per visit": drop an MSHist row only while its History
    twin is among the rows shown; otherwise it is that visit's only record
    on screen and stays."""
    shown = set()
    for row in visible:
        record = row.get("_record") or {}
        if not record.get("MSHistFrom"):
            shown.add((record.get("ContainerName"), record.get("EntryId")))
    kept = []
    for row in visible:
        record = row.get("_record") or {}
        twins = record.get("VisitTwin") or ()
        if (record.get("MSHistFrom") and twins
                and tuple(twins[0]) in shown):
            continue
        kept.append(row)
    return kept


def hide_copies_chip():
    """"Hide duplicate copies": hides the later of identical carved
    copies. Off by default."""
    return QuickFilter("chip_hide_copies", "Hide duplicate copies",
                       "primary", "Copies",
                       condition=Condition("does not contain", "copy "),
                       sentence="duplicate carved copies hidden",
                       counted=False)


def copies_hidden_note(model):
    """What the count line adds while "Hide duplicate copies" is on."""
    later = sum(1 for r in model.filter.rows
                if str(r.get("Copies") or "").startswith("copy "))
    if not later:
        return ""
    return (" — %s duplicate cop%s hidden (left out of Export view; kept in the full case exports)"
            % (format(later, ","), "y" if later == 1 else "ies"))


def one_row_per_visit_chip():
    """"One row per visit", for every view whose rows carry SameVisit."""
    return QuickFilter("chip_one_row_per_visit", "One row per visit",
                       "primary", "SameVisit", post=hide_shown_twins,
                       sentence=("MSHist copies of a visit hidden where its "
                                 "History record is listed"))


def twins_hidden_note(model):
    """What the count line adds while the chip is on: the rows it removed
    on this pass."""
    twins = model.filter.post_removed.get("SameVisit", 0)
    if not twins:
        return ""
    return (" — %s MSHist row%s hidden — each is the same visit as a "
            "History row shown (left out of Export view; kept in the full case exports)"
            % (format(twins, ","), "" if twins == 1 else "s"))
