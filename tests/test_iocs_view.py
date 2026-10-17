"""FindingsView: six RecordSets on one RecordsView switcher, against rows
shaped the way iocs_loader.py actually produces them (see
test_iocs_loader.py for that shape's own tests) -- the same "view only
declares columns, the loader does the shaping" split every RecordsView
subclass in this codebase keeps.

"Heuristics that raise questions, never conclusions" is this view's own
caveat (main_window.NAV_SECTIONS); nothing here re-phrases an engine
finding, and no confidence appears that iocs_loader did not already
supply.
"""
from webcache.views.iocs import FindingsView


def _hit_row(**overrides):
    base = {"Reasons": "tor-onion", "Why": "a Tor hidden service address",
           "Source": "live", "CleanUrl": "http://a.onion/x",
           "AccessedUtc": None}
    base.update(overrides)
    return base


def _gap_row(**overrides):
    base = {"ContainerId": 3, "ContainerName": "History", "Live": 2,
           "Missing": 1, "Recovered": 0, "GapRuns": 1,
           "Interpretation": "IDs absent from the sequence."}
    base.update(overrides)
    return base


def _void_row(**overrides):
    base = {"From": "2024-01-01 00:00:00 UTC", "To": "2024-01-03 00:00:00 UTC",
           "GapHours": 48.0}
    base.update(overrides)
    return base


def _beacon_row(**overrides):
    base = {"Domain": "beacon.example", "Events": 8, "MeanIntervalSec": 300.0,
           "IntervalCV": 0.02, "FirstSeen": "2024-01-01 00:00:00 UTC",
           "LastSeen": "2024-01-01 00:35:00 UTC"}
    base.update(overrides)
    return base


def _host_row(**overrides):
    base = {"Host": "xn--e1aybc.example", "Decoded": "тест.example",
           "Skeleton": "test.example", "Records": 2,
           "Why": "Punycode hostname decodes to “тест.example”",
           "Assessment": "Compare against the domain it resembles before "
                         "drawing any conclusion."}
    base.update(overrides)
    return base


def _hop_row(**overrides):
    base = {"Chain": 1, "Step": 1, "Url": "https://a.example/start",
           "Source": "RedirectUrl column", "InDb": "yes"}
    base.update(overrides)
    return base


# --- the six segments exist, in order, with the right nouns -------------

def test_the_six_segments_are_declared_in_order(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    assert list(v._segments_by_key.keys()) == [
        "ioc_hits", "entryid_gaps", "time_voids", "beaconing",
        "deceptive_hostnames", "redirect_chains"]


def test_the_switcher_has_all_six_buttons(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    assert set(v._switcher_buttons.keys()) == {
        "ioc_hits", "entryid_gaps", "time_voids", "beaconing",
        "deceptive_hostnames", "redirect_chains"}


def test_each_segment_has_its_own_count_noun(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    nouns = {rs.key: rs.count_noun for rs in v._record_sets}
    assert nouns == {
        "ioc_hits": "hits", "entryid_gaps": "containers",
        "time_voids": "silences", "beaconing": "domains",
        "deceptive_hostnames": "hostnames", "redirect_chains": "hops"}


# --- ioc_hits --------------------------------------------------------------

def test_ioc_hits_columns_match_the_loader_shape(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    keys = [c.key for c in v._segments_by_key["ioc_hits"].columns]
    assert keys == ["Reasons", "Source", "CleanUrl", "AccessedUtc", "Why"]


def test_ioc_hits_shows_its_rows_and_the_hit_count(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    v.set_records_for("ioc_hits", [_hit_row(), _hit_row()])
    assert v.table.model().rowCount() == 2
    assert "hits" in v.count_label.text()


# --- entryid_gaps: a real drill to the Table Browser ------------------------

def test_entryid_gaps_columns_match_the_loader_shape(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    keys = [c.key for c in v._segments_by_key["entryid_gaps"].columns]
    assert keys == ["ContainerId", "ContainerName", "Live", "Missing",
                    "Recovered", "GapRuns", "Interpretation"]


def test_the_container_name_column_drills_to_the_table_browser(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    col = next(c for c in v._segments_by_key["entryid_gaps"].columns
              if c.key == "ContainerName")
    assert col.is_link
    got = []
    v.drillRequested.connect(lambda k, row: got.append((k, row)))
    col.on_click(_gap_row())
    assert got == [("browser", _gap_row())]


def test_entryid_gaps_switches_in_and_shows_containers_noun(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    v.set_records_for("entryid_gaps", [_gap_row()])
    v._switch_segment("entryid_gaps")
    # One row here: the noun is counted in the singular ("1 container").
    assert "container" in v.count_label.text()
    assert v.table.model().row_at(0)["Interpretation"] == _gap_row()["Interpretation"]


# --- time_voids: no drill, honest empty text --------------------------------

def test_time_voids_columns_match_the_loader_shape(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    keys = [c.key for c in v._segments_by_key["time_voids"].columns]
    assert keys == ["From", "To", "Length", "GapHours"]
    length = v._segments_by_key["time_voids"].columns[2]
    assert length.sort_by == "GapHours"      # sorts by time, not by text
    assert all(not c.is_link for c in v._segments_by_key["time_voids"].columns)


def test_time_voids_switches_in_and_shows_silences_noun(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    v.set_records_for("time_voids", [_void_row()])
    v._switch_segment("time_voids")
    assert "silence" in v.count_label.text()  # "1 silence"


# --- beaconing: a real drill to History filtered by domain ------------------

def test_beaconing_columns_match_the_loader_shape(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    keys = [c.key for c in v._segments_by_key["beaconing"].columns]
    assert keys == ["Domain", "Events", "MeanIntervalSec", "IntervalCV",
                    "FirstSeen", "LastSeen"]


def test_the_domain_column_drills_to_domains_records(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    col = next(c for c in v._segments_by_key["beaconing"].columns
              if c.key == "Domain")
    assert col.is_link
    got = []
    v.drillRequested.connect(lambda k, row: got.append((k, row)))
    col.on_click(_beacon_row())
    assert got == [("domains", _beacon_row())]


# --- deceptive_hostnames: no drill, engine's own Why/Assessment shown -------

def test_deceptive_hostnames_columns_match_the_loader_shape(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    keys = [c.key for c in v._segments_by_key["deceptive_hostnames"].columns]
    assert keys == ["Host", "Decoded", "Skeleton", "Records", "Why",
                    "Assessment"]
    assert all(not c.is_link
              for c in v._segments_by_key["deceptive_hostnames"].columns)


def test_deceptive_hostnames_switches_in_and_shows_the_engines_assessment(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    v.set_records_for("deceptive_hostnames", [_host_row()])
    v._switch_segment("deceptive_hostnames")
    assert v.table.model().row_at(0)["Assessment"] == _host_row()["Assessment"]


# --- redirect_chains: hops, not chains --------------------------------------

def test_redirect_chains_columns_match_the_loader_shape(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    keys = [c.key for c in v._segments_by_key["redirect_chains"].columns]
    assert keys == ["Chain", "Step", "Url", "Source", "InDb"]


def test_redirect_chains_switches_in_and_shows_hops_noun(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    v.set_records_for("redirect_chains", [_hop_row(), _hop_row(Step=2)])
    v._switch_segment("redirect_chains")
    assert "hops" in v.count_label.text()


# --- the header caveat, the corpus banner, and the watchlist --------------

def test_header_and_caveat_are_reachable(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    assert v.header is not None
    v.set_caveat("Heuristics that raise questions, never conclusions.")


def test_the_header_extra_carries_a_watchlist_box_and_a_scan_button(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    assert v.watchlist_box is not None
    assert v.scan_button is not None


def test_pressing_scan_emits_the_typed_watchlist_text(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    got = []
    v.watchlistScanRequested.connect(got.append)
    v.watchlist_box.setText("evil.example, other.example")
    v.scan_button.click()
    assert got == ["evil.example, other.example"]


def test_the_corpus_note_can_be_set_and_read_back(qtbot):
    v = FindingsView()
    qtbot.addWidget(v)
    v.set_corpus_note("Live tables only. Deleted and unflushed records "
                      "are not being searched.")
    assert "not being searched" in v.corpus_label.text()


def test_header_extra_is_idempotent(qtbot):
    """RecordsView's own contract: called once from the base constructor,
    and must return the SAME widget on a second call or a caller asking
    twice reparents it out of the layout it is in."""
    v = FindingsView()
    qtbot.addWidget(v)
    assert v._header_extra() is v._header_extra()
