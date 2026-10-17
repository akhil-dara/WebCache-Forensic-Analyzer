"""Indicators: values carried inside URLs and paths that no column shows.

A cache-busting parameter holding the client's clock, a GUID that names a
network adapter, an account name in a profile path, a drive letter that
marks removable media. Rows come from indicator_loader.indicator_rows();
every finding and its reason come from engine/url_intel.py.

Each row states why it was reported, because presence is not intent. A
confidence of "Not determinable" is a valid value, not an error.
"""
from ..widgets.column_spec import Column
from .records_view import RecordSet, RecordsView


def _indicators_subtitle(count):
    return ("%s distinct indicator value%s found inside URLs and file "
           "paths. Presence is not intent."
           % (format(count, ","), "" if count == 1 else "s"))


class IndicatorsView(RecordsView):
    COUNT_NOUN = "indicators"  # rows are indicators, not records

    def __init__(self, parent=None):
        columns = [
            Column("Kind", "Indicator", 150, kind="flag"),
            Column("Value", "Value", 290, kind="text"),
            Column("Decoded", "What it means", 400, kind="text"),
            Column("Conf", "Confidence", 105, kind="flag"),
            Column("Records", "Records", 90, kind="num"),
            # Which field the value was read from: the same string found in
            # a URL and in a cached filename are different claims. The
            # labels are a fixed, comma-free set, so they split safely.
            Column("Fields", "Found in", 160, kind="text", multi=True),
            Column("Why", "Why this was reported", 430, kind="text"),
        ]
        super().__init__(
            record_sets=[RecordSet(
                "indicators", "Indicators", columns,
                subtitle=_indicators_subtitle,
                empty_text=("No indicators found in these URLs — nothing "
                            "decoded to a hardware address, a timestamp, "
                            "an identifier, an account or a volume."))],
            header_icon="globe", header_title="Indicators",
            parent=parent)
