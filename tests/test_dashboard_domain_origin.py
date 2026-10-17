"""Each Top 10 Domains row on the Dashboard says
whether its records are live, recovered only, or both -- the same words
the Domains view's origin column uses."""
from collections import Counter

from webcache.provenance import (AGGREGATE_LIVE, AGGREGATE_MIXED,
                                 AGGREGATE_RECOVERED)
from webcache.shell import dashboard_data
from webcache.views.dashboard import DashboardView
from tests.test_dashboard_case_card import _stats


def _row(url):
    return {"CleanUrl": url, "_kind": "carved_struct"}


def test_each_top_domain_names_its_origin(qtbot):
    live = _stats()
    live["top_domains"] = Counter({"kept.example.test": 5,
                                   "both.example.test": 2})
    merged = dashboard_data.merge_recovered_into_stats(live, [
        _row("https://gone.example.test/a"),
        _row("https://gone.example.test/b"),
        _row("https://both.example.test/c")])
    view = DashboardView()
    qtbot.addWidget(view)
    view.set_data(merged)
    words = {row.domain: getattr(row, "origin_word", "")
             for row in view._domain_rows}
    assert words == {"kept.example.test": AGGREGATE_LIVE,
                     "both.example.test": AGGREGATE_MIXED,
                     "gone.example.test": AGGREGATE_RECOVERED}


def test_top_domains_count_recovered_records_as_the_domains_view_does():
    """One label, one number: the Dashboard counted carved fragments the
    Domains view leaves out ("bhttp://..." became "[App: bhttp]"), so
    "[Not a URL]" read 184 on one and 167 on the other on a real machine.
    Both now apply domain_loader.counts_as_a_url."""
    from webcache.shell import domain_loader
    torn = {"Url": "bhttp://torn.example/x", "RecoverySource": "page slack"}
    whole = {"Url": "Visited: a@file:///C:/x.txt", "RecoverySource": "page slack"}
    rows = [{"CleanUrl": "bhttp://torn.example/x", "_kind": "carved_string",
             "_record": torn},
            {"CleanUrl": "file:///C:/x.txt", "_kind": "carved_string",
             "_record": whole}]
    merged = dashboard_data.merge_recovered_into_stats(_stats(), rows)
    assert merged["top_domains_recovered"] == Counter({"[Local File]": 1})
    domains = {r["Domain"]: r["Carved"]
               for r in domain_loader.domain_rows([], [torn, whole])}
    assert domains == {"[Local File]": 1}
