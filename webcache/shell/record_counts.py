"""The definition of "records", and the unit every count names.

A surface either counts records by DEFINITION ("live + recovered") or
names the other unit it counts."""
import collections

DEFINITION = (
    "A record is one URL-cache entry: a row the parser read from a "
    "container table (live), or one row the recovery scan produced "
    "(recovered: structured and string carves, and deleted-record stubs). "
    "Cookies, HSTS pins, certificates, leak and AppCache rows are items of "
    "their own and are never counted as records.")

#: The unit each nav badge counts, for its tooltip.
BADGE_UNITS = {
    "dashboard": "records (live + recovered)",
    "history": "History records",
    "downloads": "file-access records and downloads",
    "headers": "records carrying HTTP headers",
    "timeline": "dated records",
    "domains": "domains",
    "location": "position fixes",
    "indicators": "indicators",
    "iocs": "findings across six heuristics (not records)",
    "containers": "containers",
    "browser": "tables",
    "recovery": "recovered records",
}


class RecordCounts(collections.namedtuple("RecordCounts", "live recovered")):
    @property
    def total(self):
        return self.live + (self.recovered or 0)


def counts(parser, recovery_rows=None):
    live = len(getattr(parser, "all_entries", None) or ())
    return RecordCounts(live, None if recovery_rows is None
                        else len(recovery_rows))


def _n(value):
    return format(value, ",")


def stub_clause(stubs):
    """The clause that reconciles two totals: a deleted-record stub is a
    recovered record with no URL and no time, so surfaces that count URLs
    or times leave it out."""
    if not stubs:
        return ""
    return ("%s deleted-record stub%s (key only, no URL or time) not "
            "counted here" % (_n(stubs), "" if stubs == 1 else "s"))


def split_text(c, running=None):
    """`running`: None when no scan is in flight; otherwise the scan's
    progress in words ("3 of 10 pages"), or "" before it has reported
    any -- never "not run" while it runs."""
    if c.recovered is None:
        if running is not None:
            return "%s live record%s (recovery running%s)" % (
                _n(c.live), "" if c.live == 1 else "s",
                " (%s)" % running if running else "")
        return "%s live record%s (recovery not run)" % (
            _n(c.live), "" if c.live == 1 else "s")
    return "%s live + %s recovered = %s records" % (
        _n(c.live), _n(c.recovered), _n(c.total))
