"""Places are grouped at a scale the examiner chooses: exact stored
coordinates, or by distance at ~11 m, ~110 m or ~1.1 km. WiFi fixes
typically claim ~100 m, so at ~11 m one building splits into many places by
ordinary jitter. ~110 m is the default; every choice is stated."""
from webcache.shell import location_loader
from webcache.shell.location_loader import DEFAULT_GROUPING, GROUPINGS

from tests.test_location_loader import _live, _url

# Three fixes ~30-60 m apart (one building), and one ~5 km away.
HOME = [("18.4200100", "-39.6299900"), ("18.4202500", "-39.6298100"),
        ("18.4198000", "-39.6303000")]
AWAY = [("18.4650000", "-39.5900000")]


def _fixes(grouping=None):
    entries = [_live(_url(lat=a, lon=b)) for a, b in HOME + AWAY]
    return location_loader.position_fixes(entries, grouping=grouping)


def test_the_four_groupings_and_their_default():
    assert [g.key for g in GROUPINGS] == ["exact", "11m", "110m", "1km"]
    assert DEFAULT_GROUPING == "110m"


def test_110_m_keeps_one_building_one_place():
    rows = location_loader.places(_fixes(), grouping="110m")
    assert sorted(r["Fixes"] for r in rows) == [1, 3]


def test_11_m_splits_it_by_jitter_as_before():
    rows = location_loader.places(_fixes(), grouping="11m")
    assert len(rows) == 4


def test_exact_groups_only_identical_stored_coordinates():
    fixes = _fixes() + _fixes()          # every coordinate seen twice
    rows = location_loader.places(fixes, grouping="exact")
    assert sorted(r["Fixes"] for r in rows) == [2, 2, 2, 2]
    assert {r["Coords"] for r in rows} == {"%s, %s" % p for p in HOME + AWAY}


def test_a_fix_s_place_label_matches_its_place_row_at_every_grouping():
    """The drill from a place to its fixes is an exact match on this key."""
    for g in GROUPINGS:
        fixes = _fixes(grouping=g.key)
        rows = location_loader.places(fixes, grouping=g.key)
        assert {f["Place"] for f in fixes} == {r["Coords"] for r in rows}, g.key


def test_the_note_states_the_grouping_in_force():
    fixes = _fixes()
    for g in GROUPINGS:
        note = location_loader.places_note(
            fixes, location_loader.places(fixes, grouping=g.key), grouping=g.key)
        assert g.description in note, (g.key, note)


def test_a_rounding_boundary_never_splits_one_building():
    """Grouping by rounding cuts a grid line through some building at
    every scale. Two fixes 2 m apart either side of a 3-decimal rounding
    boundary are one place at every scale but exact."""
    entries = [_live(_url(lat="18.4160000", lon="-39.6285100")),
               _live(_url(lat="18.4160000", lon="-39.6284900"))]
    for g in ("11m", "110m", "1km"):
        fixes = location_loader.position_fixes(entries, grouping=g)
        assert len(location_loader.places(fixes, grouping=g)) == 1, g


def test_a_place_is_labelled_by_a_position_that_was_reported():
    """Never a mean: the label is the stored position most fixes sit
    around, at the grouping's decimals."""
    rows = location_loader.places(_fixes(), grouping="110m")
    home = max(rows, key=lambda r: r["Fixes"])
    lat, lon = home["Coords"].split(", ")
    reported = {("%.3f" % float(a), "%.3f" % float(b)) for a, b in HOME}
    assert (lat, lon) in reported
