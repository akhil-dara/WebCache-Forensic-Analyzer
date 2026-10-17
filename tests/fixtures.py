"""Generated record sets, because CI can never see the real evidence.

A real WebCacheV01.dat carries someone's browsing history, local file paths
and geolocation fixes. It is not in this repository and never will be, so a
runner cannot execute the evidence-backed tests. Anything CI asserts -- widget
behaviour, performance budgets -- runs on these rows instead.

They are deliberately awkward: blank titles, missing timestamps, mixed
origins, real datetime objects rather than pre-formatted strings. A fixture
that is tidier than the evidence tests less than it appears to.
"""
import datetime
import random

from webcache.widgets.column_spec import Column

FIXTURE_COLUMNS = [
    Column("CleanUrl", "Address", 420, kind="url", field="CleanUrl"),
    Column("Title", "Title", 240, kind="text"),
    Column("AccessedUtc", "Last visit (UTC)", 160, kind="time", field="AccessedUtc"),
    Column("AccessedLocal", "Last visit (LOCAL)", 160, kind="time_local",
           field="AccessedLocal"),
    Column("VisitCount", "Visits", 70, kind="num", field="VisitCount"),
    Column("Domain", "Domain", 160, kind="domain"),
    Column("ContainerType", "Container", 110, kind="text"),
    Column("IsInPrivate", "InPrivate", 80, kind="flag"),
    Column("Origin", "Origin", 150, kind="text", field="Origin"),
    Column("Source", "Source file", 150, kind="text", field="Source"),
    Column("Offset", "Offset", 90, kind="num", field="Offset"),
    Column("Confidence", "Confidence", 90, kind="text", field="Confidence"),
]

_HOSTS = ["msn.com", "bing.com", "acroipm2.adobe.com", "login.live.com",
          "static.cdn.net", "outlook.office.com", "google.com", "portal.local"]
_WORDS = ["search", "login", "static", "index", "profile", "report", "nimbus"]
_LOGS = ["WebCacheV01.dat", "V01.log", "V0100123.log", "V010023E.log"]


def make_rows(n, seed=7):
    """n deterministic records, roughly a fifth of them carved."""
    rnd = random.Random(seed)
    base = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    rows = []
    for i in range(n):
        host = rnd.choice(_HOSTS)
        word = rnd.choice(_WORDS)
        carved = (i % 5 == 0)
        # A tenth of records have no usable timestamp -- that is normal in
        # carved data, and blank handling has to be exercised.
        stamped = (i % 10 != 3)
        utc = base + datetime.timedelta(seconds=rnd.randint(0, 60 * 60 * 24 * 400))
        rows.append({
            "CleanUrl": "https://www.%s/%s?q=%d" % (host, word, i),
            "Title": "" if i % 7 == 0 else "%s %s %d" % (host, word, i),
            "AccessedUtc": utc if stamped else None,
            "AccessedLocal": (utc + datetime.timedelta(hours=5, minutes=30)
                              if stamped else None),
            "VisitCount": rnd.randint(1, 400),
            "Domain": host,
            "ContainerType": "History",
            "IsInPrivate": bool(i % 11 == 0),
            "Origin": "Carved (deleted/unflushed)" if carved else "Live record",
            "Source": rnd.choice(_LOGS[1:]) if carved else "",
            "Offset": rnd.randint(0, 1 << 30) if carved else 0,
            "Page": rnd.randint(1, 9000) if carved else 0,
            "Method": rnd.choice(["page-scan", "log-replay"]) if carved else "",
            "Confidence": rnd.choice(["high", "medium", "low"]) if carved else "",
            # Real row keys evidence_loader.history_rows_from_parser() and
            # recovery_loader.carved_history_rows() both carry -- see
            # history.py's quick-filter chips, which read these.
            "SearchTerms": word if i % 4 == 0 else "",
            "IsLocalFile": (i % 13 == 0),
        })
    return rows
