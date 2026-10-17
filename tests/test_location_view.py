"""Where the device said it was, and everything that keeps that from
reading as where it WAS.

The nav caveat -- "Positions the device reported to servers, which it can
be told to fake" -- is a stronger claim than any user-visible sentence in
an earlier version, whose ancestors for it were a developer-only module
docstring and a code comment. These tests hold it to being structural:

  * Disagreement is a COLUMN, sortable and filterable, because the device
    controls the fix time and does not control the cache write -- so the
    falsifiability is a cross-check an examiner can actually perform;
  * FixTimeFormat names the reading, so no number on a row is a silent
    interpretation;
  * every heading says "reported", "claimed", "device said" or "source
    record", and none asserts a position;
  * the Assessment column repeats the non-attribution sentence on every
    single row, so it cannot be scrolled past once and forgotten.

Plus the two structural rules: a place DRILLS to its fixes rather than
copying a link into a dead end, and map links are copied, never opened.
"""
import datetime

import pytest

from webcache.provenance import ABSENCE_NOT_SUPPLIED, CARVED_ORIGIN
from webcache.shell import location_loader
from webcache.views.location import LocationView

UTC = datetime.timezone.utc


def _entry(lat="51.5074", lon="-0.1278", **params):
    query = "clientlocation=%s|%s" % (lat, lon)
    for key, value in params.items():
        query += "&%s=%s" % (key, value)
    url = "https://tiles.example.test/v1?" + query
    return {"Url": url, "CleanUrl": url, "ContainerType": "History",
            "EntryId": 41, "ContainerId": 3,
            "ModifiedTime": "2024-06-15 09:00:01 UTC"}


def _fixes(entries=None, carved=()):
    return location_loader.position_fixes(
        entries if entries is not None else [_entry()], carved)


@pytest.fixture
def view(qtbot):
    widget = LocationView()
    qtbot.addWidget(widget)
    return widget


def _fill(widget, fixes=None):
    fixes = _fixes() if fixes is None else fixes
    places = location_loader.places(fixes)
    widget.set_records_for("fixes", fixes,
                           note=location_loader.fixes_note(fixes, False))
    widget.set_records_for("places", places,
                           note=location_loader.places_note(fixes, places))
    return fixes, places


def _columns(widget, key):
    return {c.key: c for c in widget._segments_by_key[key].columns}


# --- shape ---------------------------------------------------------------

def test_it_opens_on_the_fixes_not_on_the_places(view):
    """A place is a summary. Opening on the summary invites the row to be
    read as the thing itself."""
    assert view._active_key == "fixes"
    assert [rs.key for rs in view._record_sets] == ["fixes", "places", "records"]


def test_the_fixes_grid_carries_every_field_the_location_exports_write(view):
    """ForensicEngine.LOCATION_FIELDS is what the CSV, the KML and the PDF
    all write. The screen and those files must not be able to hold
    different facts -- so every one of those keys is either a column here
    or is folded into one that is named as such."""
    from webcache.engine.forensic_engine import ForensicEngine
    columns = _columns(view, "fixes")
    folded = {"FixTimestamp": "FixTimeUtc", "RecordTimeUTC": "RecordTimeShown",
              "Latitude": "Coords", "Longitude": "Coords",
              "LatitudeRaw": "Coords", "LongitudeRaw": "Coords",
              "AccuracyMetres": "Accuracy",
              # EntryId and ContainerId identify the record, which the
              # detail dialog shows in full; the grid names its type.
              "EntryId": "ContainerType", "ContainerId": "ContainerType",
              # why the cache time is blank for an MSHist visit with
              # no recovered zone; the grid states it in "Times differ by".
              "RecordTimeNote": "Disagreement"}
    for key, _heading in ForensicEngine.LOCATION_FIELDS:
        assert folded.get(key, key) in columns, key


def test_the_places_grid_shows_the_place_and_what_it_summarises(view):
    columns = _columns(view, "places")
    for key in ("Coords", "Fixes", "Carved", "Accuracy", "FirstSeen",
                "LastSeen", "Providers", "MapsUrl", "OsmUrl"):
        assert key in columns, key


# --- "which it can be told to fake", made structural ---------------------

def test_the_times_differ_by_column_exists_and_sorts(view):
    """The cross-check the whole design rests on. "Every fix whose reported
    time disagrees with the cache by more than an hour" has to be one
    right-click, not mental arithmetic across two encodings."""
    columns = _columns(view, "fixes")
    assert "Disagreement" in columns
    assert columns["Disagreement"].label == "Times differ by"
    fixes, _places = _fill(view)
    model = view.table.model()
    model.sort_by("Disagreement", False)
    assert model.rowCount() == len(fixes)


def test_the_reading_of_the_fix_time_is_named_in_its_own_column(view):
    columns = _columns(view, "fixes")
    assert columns["FixTimeFormat"].label == "Fix time read as"


def test_no_heading_asserts_a_position(view):
    """Every heading that could be read as an assertion says whose claim it
    is instead."""
    labels = {c.key: c.label for c in view._segments_by_key["fixes"].columns}
    assert "device said" in labels["FixTimeUtc"]
    assert "claimed" in labels["Accuracy"]
    assert labels["Provider"] == "Reported source"
    assert labels["Origin"] == "Source record"
    assert "as stored" in labels["Coords"]


def test_the_assessment_repeats_the_non_attribution_sentence_on_every_row(view):
    """Once at the top of a screen is a sentence somebody scrolls past.
    On every row it is a sentence they read with each fix."""
    fixes, _places = _fill(view, _fixes(
        [_entry(clientlocationaccuracy="12"), _entry(lat="48.8566",
                                                     lon="2.3522")]))
    for fix in fixes:
        assert ("not that any particular person was present"
                in fix["Assessment"])


def test_the_grid_says_the_links_are_never_opened(view):
    """Copy, never Open -- and here the CONSEQUENCE is what matters:
    opening one of these would send this position to that provider."""
    text = " ".join(view.visible_text())
    assert "never opened" in text
    assert "sends the position to that provider" in text


def test_the_subtitle_states_the_grouping_a_place_is(view):
    _fill(view)
    view._switch_segment("places")
    from webcache.shell.location_loader import DEFAULT_GROUPING, grouping_for
    assert grouping_for(DEFAULT_GROUPING).description in view.header._subtitle.text()


def test_the_subtitles_stay_short_enough_to_be_read(view):
    """ViewHeader's subtitle is a wrapping QLabel in a QVBoxLayout, which
    does not grow the header for its wrapped height. Looked at on screen:
    a three-line places subtitle had its last line cut in half by the
    switcher row. Everything longer belongs in the count-line note, which
    records_view.py made wrap and grow for exactly this reason."""
    _fill(view)
    for rs in view._record_sets:
        text = rs.subtitle(len(view._segment_rows[rs.key]))
        assert len(text) < 90, (rs.key, len(text), text)


def test_that_a_place_is_a_summary_is_still_said_where_it_wraps(view):
    """It moved OUT of the subtitle, not away: it is in the note beside
    the count, which is the line that can hold it."""
    fixes, places = _fill(view)
    note = location_loader.places_note(fixes, places)
    assert "summary" in note.lower()
    assert "never opened" in note


@pytest.mark.parametrize("word", ["confirm", "proves", "demonstrates"])
def test_no_string_this_view_puts_on_screen_claims_more_than_it_can(view, word):
    _fill(view)
    for text in view.visible_text():
        assert word not in text.lower(), text


# --- absence, not blanks -------------------------------------------------

def test_a_request_that_supplied_no_accuracy_says_so_on_the_row(view):
    fixes, _places = _fill(view)
    model = view.table.model()
    row = model.row_at(0)
    assert row["Accuracy"] == ABSENCE_NOT_SUPPLIED
    assert row["Provider"] == ABSENCE_NOT_SUPPLIED
    assert row["FixTimeFormat"] == ABSENCE_NOT_SUPPLIED


# --- a place drills through ----------------------------------------------

def test_clicking_a_place_switches_to_its_fixes_and_shows_exactly_those(view):
    """The earlier version's place row only copied a Maps link -- its own docstring calls
    that "a dead end for an investigation". Everything that makes a place
    evidence lives on the fixes underneath it."""
    here, there = _entry(), _entry(lat="48.8566", lon="2.3522")
    fixes, places = _fill(view, _fixes([here, here, there]))
    view._switch_segment("places")
    target = [p for p in places if p["Fixes"] == 2][0]

    view.show_fixes_at(target)

    assert view._active_key == "fixes"
    model = view.table.model()
    shown = list(model.filter.visible())
    assert len(shown) == 2
    assert {f["Place"] for f in shown} == {target["Coords"]}


def test_the_place_coordinate_cell_is_the_drill_and_not_a_copy(view):
    column = _columns(view, "places")["Coords"]
    assert column.on_click is not None


def test_drilling_from_a_place_clears_a_filter_typed_against_places(view):
    """_switch_segment's own rule: a filter written for one segment's
    columns must never survive onto another's."""
    _fixes_rows, places = _fill(view)
    view._switch_segment("places")
    view.filter_box.setText("nothing matches this")
    view.show_fixes_at(places[0])
    assert view.filter_box.text() == ""


# --- map links are copied, never opened ----------------------------------

def test_a_map_link_cell_asks_for_a_copy_and_names_what_it_is(view, qtbot):
    fixes, _places = _fill(view)
    seen = []
    view.copyRequested.connect(lambda text, what: seen.append((text, what)))
    for key in ("MapsUrl", "OsmUrl"):
        _columns(view, "fixes")[key].on_click(fixes[0])
    assert [t for t, _w in seen] == [fixes[0]["MapsUrl"], fixes[0]["OsmUrl"]]
    assert all(w for _t, w in seen)


def test_a_place_map_link_copies_too(view):
    _fixes_rows, places = _fill(view)
    seen = []
    view.copyRequested.connect(lambda text, what: seen.append(text))
    _columns(view, "places")["MapsUrl"].on_click(places[0])
    assert seen == [places[0]["MapsUrl"]]


# --- the count line ------------------------------------------------------

def test_the_count_line_counts_fixes_on_one_segment_and_places_on_the_other(view):
    _fill(view, _fixes([_entry(), _entry(lat="48.8566", lon="2.3522")]))
    assert "position fixes" in view.count_label.text()
    view._switch_segment("places")
    assert "places" in view.count_label.text()


def test_the_count_line_never_says_the_same_number_twice(view):
    """Looked at on screen against the real exhibit: the line read
    "0 position fixes - 0 position fixes - carved fixes are not yet
    meaningful". The base writes the count; the note must start at what
    the count does not say. Same duplication the Timeline count line hit,
    and the reason its own COUNT_NOUN exists."""
    _fill(view, _fixes([_entry(), _entry(lat="48.8566", lon="2.3522")]))
    line = view.line_text()
    assert line.startswith("2 position fixes"), line
    assert line.count("position fixes") == 1, line
    view._switch_segment("places")
    line = view.line_text()
    assert line.startswith("2 places"), line
    # "decimal places" is a different phrase and is allowed to appear.
    assert line.count(" places —") + line.count("2 places") == 2, line


def test_the_note_beside_the_count_is_readable_rather_than_clipped(view):
    """The note is three sentences on this view -- what was recovered,
    what claimed no accuracy, and what a fix is not -- and an unwrapped
    label runs it off the window edge, taking the caveat with it. A
    caveat that is not on screen is a caveat that was not written."""
    assert view.count_label.wordWrap() is True


# --- the empty state -----------------------------------------------------

def test_an_exhibit_with_no_fixes_says_why_that_is_a_legitimate_answer(view):
    """The real exhibit this port is built against holds none. An empty
    grid here must not read as a failure to parse."""
    _fill(view, [])
    reason = view.table.empty_state_text()
    assert "No request URL in this exhibit reported a position" in reason
    assert "does not show the device was never located" in reason
    assert "Recover deleted records" in reason


def test_the_empty_state_names_what_was_searched_for(view):
    _fill(view, [])
    reason = view.table.empty_state_text()
    assert "clientlocation" in reason
    assert "lat" in reason and "lon" in reason


# --- carved --------------------------------------------------------------

def test_a_recovered_fix_keeps_its_carved_styling_in_the_grid(view):
    from webcache.widgets import record_model
    artifact = {"Url": _entry()["Url"], "Encoding": "ascii",
                "Source": "V01.log", "Offset": 4096,
                "NearbyFiletime": datetime.datetime(2024, 6, 15, tzinfo=UTC)}
    fixes, _places = _fill(view, _fixes([], [artifact]))
    assert fixes[0]["Origin"] == CARVED_ORIGIN
    assert record_model._is_carved(fixes[0]) is True


def test_a_map_link_cell_says_what_it_does_not_the_clipped_url(view):
    """On a real exhibit every Places row showed "https://www.
    google.com/ +2 more lines" twice: a 120-character URL built from the
    coordinates beside it, clipped to three lines in a 135-pixel column.
    The cell says what a click does; the tooltip, the copy and every
    export carry the whole URL."""
    from PySide6.QtCore import Qt
    from webcache.widgets.column_spec import display_text
    from webcache.widgets.record_model import RecordTableModel
    url = "https://www.google.com/maps/search/?api=1&query=1.5,2.5"
    for key in ("fixes", "places"):
        for name in ("MapsUrl", "OsmUrl"):
            col = _columns(view, key)[name]
            assert display_text(url, col) == "Copy link"
    col = _columns(view, "places")["MapsUrl"]
    model = RecordTableModel([col], [{"MapsUrl": url}])
    import html
    assert url in html.unescape(model.data(model.index(0, 0), Qt.ToolTipRole))
