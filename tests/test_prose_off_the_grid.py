"""Tool-written explanatory prose that is the same text for
a record kind is not evidence; it lives once in a header tooltip, never in
every row. The stored row keeps the value, so every export still has it."""
from PySide6.QtCore import Qt


def _header_tip(view, key):
    model = view.table.model()
    keys = [c.key for c in model.columns]
    return model.headerData(keys.index(key), Qt.Horizontal, Qt.ToolTipRole)


def _hidden(view, key):
    """Hidden by declaration (an optional column), not merely because every
    row happened to match."""
    cols = view.table.model().columns
    keys = [c.key for c in cols]
    return (cols[keys.index(key)].optional
            and view.table.isColumnHidden(keys.index(key)))


def test_hsts_prose_is_in_the_header_tooltip_not_in_every_row(qtbot):
    from webcache.views.cookies import CookiesView
    view = CookiesView()
    qtbot.addWidget(view)
    rows = [{"Domain": "h%d.example.test" % i,
             "Corroborated": "yes" if i % 2 else "NO",
             "Significance": ("Host also appears in history/cache records, "
                              "which corroborates the pin." if i % 2 else
                              "No other record for this host survives. A pin "
                              "is set by an HTTPS response."),
             "HostAttribution": ("Pin covers subdomains" if i % 3 else
                                 "Pin is host-specific"),
             "IncludeSubdomains": "yes" if i % 3 else "no"}
            for i in range(6)]
    view.set_records_for("hsts", rows)
    view._switch_segment("hsts")
    assert _hidden(view, "Significance")
    assert _hidden(view, "HostAttribution")
    tip = _header_tip(view, "Corroborated")
    assert "No other record for this host survives" in tip
    assert "corroborates the pin" in tip
    # the stored rows still carry it (exports read the rows)
    assert view._segment_rows["hsts"][0]["Significance"]


def test_the_entryid_gap_interpretation_is_a_header_tooltip(qtbot):
    from webcache.views.iocs import FindingsView
    view = FindingsView()
    qtbot.addWidget(view)
    view.set_records_for("entryid_gaps", [
        {"ContainerId": i, "ContainerName": "C%d" % i, "Live": i,
         "Missing": 1, "Recovered": 0, "GapRuns": 1,
         "Interpretation": "IDs absent from the sequence. Consistent with "
                           "deletion, with automatic cache scavenging.",
         "_record": None, "_kind": "entryid_gap", "_records": []}
        for i in range(3)])
    view._switch_segment("entryid_gaps")
    assert _hidden(view, "Interpretation")
    assert "Consistent with deletion" in _header_tip(view, "GapRuns")


def test_the_deceptive_host_assessment_is_a_header_tooltip(qtbot):
    from webcache.views.iocs import FindingsView
    view = FindingsView()
    qtbot.addWidget(view)
    view.set_records_for("deceptive_hostnames", [
        {"Host": "h%d.example.test" % i, "Decoded": "x", "Skeleton": "y",
         "Records": 1, "Why": "mixed script",
         "Assessment": "Compare against the domain it resembles before "
                       "drawing any conclusion.",
         "_record": None, "_kind": "deceptive_host", "_records": []}
        for i in range(3)])
    view._switch_segment("deceptive_hostnames")
    assert _hidden(view, "Assessment")
    assert "Compare against the domain it resembles" in \
        _header_tip(view, "Why")


def test_the_location_assessment_is_a_header_tooltip(qtbot):
    from webcache.views.location import LocationView
    view = LocationView()
    qtbot.addWidget(view)
    view.set_records_for("fixes", [
        {"Assessment": "The device reported this position %d." % i,
         "Accuracy": 10.0 * i} for i in range(3)])
    assert _hidden(view, "Assessment")
    tip = _header_tip(view, "Accuracy")
    assert "not that any particular person was present" in tip
