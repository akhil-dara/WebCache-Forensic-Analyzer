"""What the Help menu says, and what F1 says about an empty cell. Qt-free,
so every sentence here is testable on its own."""
from .. import provenance
from ..engine import evidence_model

ABOUT_TEXT = (
    "WebCache Forensic Analyzer %s\n\n"
    "Reads a WebCacheV01.dat (Internet Explorer / Edge Legacy / WinINet "
    "cache) read-only, recovers deleted records from unallocated space and "
    "the transaction logs, and states the provenance of every value. The "
    "evidence folder is never written to; paths shown belong to the "
    "examined machine and are copied, never opened.\n\n"
    "Released under the GNU Affero General Public License v3.0.\n"
    "© 2026 Akhil Dara." % provenance.TOOL_VERSION)

SHORTCUTS = [
    ("Ctrl+O", "Open evidence"),
    ("Ctrl+1 … Ctrl+9", "The first nine views"),
    ("Alt+Left", "Back to the previous view"),
    ("Backspace", "Back, when no text box has focus"),
    ("Ctrl+F", "Filter the records on screen"),
    ("Esc", "Clear every filter / close a dialog"),
    ("Enter", "Follow a link cell, or show a capped value whole"),
    ("Ctrl+Enter", "Open the record under the cursor"),
    ("F1", "Explain the value under the cursor"),
    ("Ctrl+C", "Copy the selection (a carved row is labelled)"),
    ("Ctrl+E", "Export this view"),
    ("Ctrl+Shift+E", "Export & Report"),
    ("Tab / Shift+Tab", "Move between controls; arrows move between cells"),
]

#: The Origin column's values, as its own tooltips state them.
ORIGIN_LEGEND = [
    ("Live", "a live record, read from the database's own tables."),
    ("Carved", "recovered from unallocated space or the transaction log; "
               "not a live record."),
    ("Mixed", "an aggregate: some members are live, some recovered."),
    ("Recovered only", "an aggregate: every member was recovered (carved)."),
    ("—", "neither a record nor a population of records."),
]


def shortcuts_text():
    """keys<TAB>description lines: what Copy yields, and what the dialog
    lays out as two aligned columns."""
    return "\n".join("%s\t%s" % (k, a) for k, a in SHORTCUTS)


def badge_legend_text():
    lines = ["Every column heading and every field in a record carries a "
             "basis badge: how the value was obtained.\n"]
    for basis in evidence_model.BASIS_ORDER:
        lines.append("%s  %s — %s" % (evidence_model.BASIS_SHORT[basis],
                                          basis.capitalize(),
                                          evidence_model.BASIS_DEFINITION[basis]))
    lines.append("\nThe Origin column:\n")
    for label, meaning in ORIGIN_LEGEND:
        lines.append("%s  — %s" % (label, meaning))
    return "\n".join(lines)


def explain_empty(column_label, field, carved):
    """Why a cell is empty, and what it would hold."""
    why = ("This recovered record's carve did not reach a value for this "
           "column: a carve reconstructs only what survived."
           if carved else
           "The live record stores nothing in this field.")
    meaning = evidence_model.describe(field) if field else ""
    would = ("This column would hold: %s" % meaning if meaning else
             "This column would hold the record's \"%s\"." % column_label)
    return "The cell is empty. %s\n\n%s" % (why, would)
