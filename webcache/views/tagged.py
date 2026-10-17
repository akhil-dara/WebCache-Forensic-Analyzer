"""Tagged: the examiner's own marks, in one list.

Every record -- live or recovered -- that carries a tag or a comment in
this exhibit's case file, with its tags and comments first and then the
same columns every record list shows. Built on RecordsView, so it
filters, sorts, opens a record and exports exactly like History; the
Tags column filters by tag through its funnel.

The notes themselves live in the case file beside the application, never
in the evidence folder (shell/case_store.py).
"""
from ..widgets.column_spec import Column
from .records_view import RecordSet, RecordsView, member_record_columns

EMPTY_TEXT = ("No record is tagged or commented yet. Right-click any record "
              "in any view, or open one, to add a tag or a comment; it is "
              "listed here and carried into every export.")


def _subtitle(count):
    return ("%s record%s carrying your tags or comments, kept in this "
            "exhibit's case file." % (format(count, ","),
                                      "" if count == 1 else "s"))


class TaggedView(RecordsView):
    COUNT_NOUN = "tagged records"

    def __init__(self, parent=None):
        columns = [
            Column("Tags", "Tags", 180, kind="text", multi=True),
            Column("Comments", "Comments", 260, kind="text"),
        ] + member_record_columns(self)
        super().__init__(
            record_sets=[RecordSet(
                "tagged", "Tagged", columns, subtitle=_subtitle,
                empty_text=EMPTY_TEXT,
                default_sort=("KeyTimeUtc", True))],
            header_icon="tag", header_title="Tagged", parent=parent)
        self.annotate_basis(columns)
