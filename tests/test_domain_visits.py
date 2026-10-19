"""How many visits a domain had, from the browser's own visit counter.

Found working "how many times was this site visited": Domains offered a
column headed "Avg visits" that averaged AccessCount -- cache touches,
which this tool states are not visits -- and no visit total at all. The
counter that is a visit count (SPS id 6) is cumulative per address, and
on the exhibit 108 addresses carried it on both a live record and a
recovered older copy, so a plain sum would count those twice."""
from webcache.shell.domain_loader import domain_rows

URL_A = "Visited: u@https://site.test/a"
URL_B = "Visited: u@https://site.test/b"
URL_C = "Visited: u@https://site.test/c"


def _h(url, count=None, **kw):
    e = {"Url": url, "CleanUrl": url.split("@", 1)[1],
         "ContainerType": "History"}
    if count is not None:
        e["SPS_VisitCount"] = count
    e.update(kw)
    return e


def _row():
    live = [_h(URL_A, 5), _h(URL_C)]
    carved = [_h(URL_A, 3, RecoverySource="Structured record reconstruction"),
              _h(URL_B, 2, RecoverySource="Structured record reconstruction"),
              _h(URL_B, 4, RecoverySource="Structured record reconstruction")]
    rows = domain_rows(live, carved)
    return next(r for r in rows if r["Domain"] == "site.test")


def test_each_address_counts_once_live_first_else_its_latest_count():
    row = _row()
    # A: live 5 (the recovered 3 is an older copy); B: 4; C: none.
    assert row["Visits"] == 9
    assert row["VisitsAddresses"] == 2


def test_the_grid_names_cache_touches_and_visits_for_what_they_are(qtbot):
    from webcache.views.domains import DomainsView
    v = DomainsView()
    qtbot.addWidget(v)
    labels = {c.key: c.label for c in v.COLUMNS} if hasattr(v, "COLUMNS") \
        else {c.key: c.label for c in v.table.model().columns}
    assert labels["AccessCount"] == "Mean cache touches"
    assert labels["Visits"] == "Visits (property store)"
    assert "Avg visits" not in labels.values()


def test_the_domain_record_shows_the_same_total():
    from webcache.shell import detail_fields as df
    fields = {f.label: f for g in df.fields_for(_row()) for f in g.fields}
    assert fields["Visits (property store)"].display_value == "9"
    assert fields["Addresses with a visit count"].display_value == "2"


def test_a_domain_with_no_stored_count_shows_none_not_zero():
    """126 cache requests and no visit counter is "no count stored", not
    "visited 0 times"."""
    rows = domain_rows([{"Url": "https://cdn.test/x.png",
                         "CleanUrl": "https://cdn.test/x.png",
                         "ContainerType": "Content"}])
    row = next(r for r in rows if r["Domain"] == "cdn.test")
    assert row["Visits"] is None
    assert row["VisitsAddresses"] == 0
