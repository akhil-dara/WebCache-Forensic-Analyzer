"""What a position fix is worth, and the four defects that made the earlier
Location screen disagree with itself.

1. CARVED-NESS IS DECIDED ONCE. Reading it off
   `(f.get("_entry") or {}).get("Origin")` while setting Origin on the FIX
   would draw carved points in the live colour and report a carved
   count of zero beside a grid that labelled the same rows carved. The
   engine's own ForensicEngine._loc_value has the identical dependency, so
   the invariant is asserted here rather than commented: for every fix,
   fix["Origin"] == _loc_value(fix, "Origin").

2. THE CROSS-CHECK COULD NOT BE PERFORMED. geolocation.collect returns
   FixTimestamp as the raw query-parameter value -- ISO, a Windows
   FILETIME, or epoch seconds/ms/us. Printed verbatim beside a formatted
   UTC string, the two cannot be compared. An
   examiner cannot compare 1718452801000 against "2024-06-15 09:00:01" by
   eye, so the falsifiability the whole design rests on was decorative.
   Here both sides are real datetimes and the difference is its own
   column.

3. FIRST/LAST SEEN WERE ORDERED AS STRINGS. cluster_summary compares the
   raw stamps, so on mixed formats "1718452801000" sorts before
   "2024-06-15 09:00:01" and the pair it reports is simply wrong.

4. A PLACE HAD NO ACCURACY AT ALL. export_location_pdf reads
   p.get("Accuracy") and cluster_summary has never emitted that key, so
   that column renders blank in every location PDF ever written.

Plus the vocabulary rule: Accuracy, Reported source and Fix time read as
(not supplied) when the request did not carry them, never as a blank an
examiner reads as an oversight, and never as an averaged or defaulted
number.
"""
import datetime

import pytest

from webcache.engine import geolocation
from webcache.engine.forensic_engine import ForensicEngine
from webcache.provenance import ABSENCE_NOT_SUPPLIED, CARVED_ORIGIN
from webcache.shell import location_loader, record_kinds

UTC = datetime.timezone.utc

#: 2024-06-15 12:00:01 UTC, as epoch milliseconds.
EPOCH_MS = 1718452801000
EPOCH_MS_UTC = datetime.datetime(2024, 6, 15, 12, 0, 1, tzinfo=UTC)


def _url(lat="51.5074", lon="-0.1278", **params):
    query = "clientlocation=%s|%s" % (lat, lon)
    for key, value in params.items():
        if value is not None:
            query += "&%s=%s" % (key, value)
    return "https://tiles.example.test/v1?" + query


def _live(url, modified="2024-06-15 09:00:01 UTC", **extra):
    entry = {"Url": url, "CleanUrl": url, "ContainerType": "History",
             "EntryId": 41, "ContainerId": 3, "ModifiedTime": modified}
    entry.update(extra)
    return entry


def _artifact(url, **extra):
    """The shape recovery_engine._carve_strings emits: a URL, where it was
    found, and a FILETIME that happened to sit near it. No Origin key --
    which is exactly what made the earlier version's carved count read zero."""
    art = {"Url": url, "Encoding": "ascii", "Source": "V01.log",
           "Region": "log", "Offset": 4096, "InLiveDb": False,
           "NearbyFiletime": datetime.datetime(2024, 6, 15, 9, 0, 1,
                                               tzinfo=UTC)}
    art.update(extra)
    return art


# --- the admission gate and the origin invariant -------------------------

def test_no_evidence_yields_no_fixes():
    assert location_loader.position_fixes([]) == []
    assert location_loader.position_fixes([], []) == []


def test_a_url_with_no_coordinate_reports_no_fix():
    """The ordinary case, and the one the real exhibit turned out to be.
    A cache full of URLs that never carried a position is not a failure to
    parse."""
    assert location_loader.position_fixes(
        [_live("https://www.example.test/search?q=7")]) == []


def test_every_fix_carries_an_origin_the_engine_agrees_with():
    """The plot/grid divergence, asserted rather than commented.
    ForensicEngine._loc_value reads Origin off fix["_entry"]; the grid, the
    plot and the caption read it off the fix. If those two can differ, one
    screen labels a recovered position live."""
    fixes = location_loader.position_fixes(
        [_live(_url())], [_artifact(_url(lat="48.8566", lon="2.3522"))])
    assert len(fixes) == 2
    for fix in fixes:
        assert fix["Origin"] == ForensicEngine._loc_value(fix, "Origin")
    origins = sorted(f["Origin"] for f in fixes)
    assert origins == [CARVED_ORIGIN, "Live record"]


def test_building_fixes_never_writes_an_origin_onto_an_engine_dict():
    """Those dicts are shared with Domains, Indicators, Recovery, the
    Dashboard and every export. A key written here would appear there,
    attributed to a scan that view never ran."""
    live = _live(_url())
    artifact = _artifact(_url(lat="48.8566", lon="2.3522"))
    location_loader.position_fixes([live], [artifact])
    assert "Origin" not in live
    assert "Origin" not in artifact
    assert set(artifact) == set(_artifact(_url()))


def test_a_carved_fix_points_back_at_the_artifact_it_came_from():
    """_carved_entry builds a dict the loader owns, and hangs the real
    artifact off it -- so the fix can be traced to the bytes without the
    artifact being written to."""
    artifact = _artifact(_url())
    fix = location_loader.position_fixes([], [artifact])[0]
    assert fix["_entry"]["_record"] is artifact
    assert fix["_entry"] is not artifact


def test_a_carved_string_with_no_url_at_all_is_skipped():
    assert location_loader.position_fixes([], [{"Source": "V01.log"}]) == []


# --- the two timestamps, decoded ----------------------------------------

def test_epoch_milliseconds_decode_to_a_real_datetime_and_name_the_reading():
    fix = location_loader.position_fixes(
        [_live(_url(clientlocationtimestamp=EPOCH_MS))])[0]
    assert isinstance(fix["FixTimeUtc"], datetime.datetime)
    assert fix["FixTimeUtc"] == EPOCH_MS_UTC
    assert fix["FixTimeFormat"] == "epoch milliseconds"
    # The raw value travels with the reading, so the reading can be checked.
    assert fix["FixTimeRaw"] == str(EPOCH_MS)


def test_an_iso_fix_time_is_read_as_written():
    fix = location_loader.position_fixes(
        [_live(_url(clientlocationtimestamp="2024-06-15T12:00:01Z"))])[0]
    assert fix["FixTimeUtc"] == EPOCH_MS_UTC
    assert fix["FixTimeFormat"] == "ISO-8601 as written"


def test_an_ambiguous_integer_is_not_decoded_into_a_fabricated_time():
    """geolocation.decode_url_timestamp refuses anything that could
    plausibly be an id, a size or a build number. A number read as a date
    puts a time in front of an examiner that nothing supports."""
    fix = location_loader.position_fixes(
        [_live(_url(clientlocationtimestamp="123456"))])[0]
    assert fix["FixTimeUtc"] is None
    assert fix["FixTimeFormat"] == location_loader.NOT_DECODABLE
    assert fix["FixTimeRaw"] == "123456"


def test_no_time_parameter_at_all_reads_as_not_supplied():
    """Distinct from "not decodable": nothing was carried, so nothing
    failed to be read."""
    fix = location_loader.position_fixes([_live(_url())])[0]
    assert fix["FixTimeUtc"] is None
    assert fix["FixTimeFormat"] == ABSENCE_NOT_SUPPLIED
    assert fix["FixTimeRaw"] == ABSENCE_NOT_SUPPLIED


def test_the_cache_write_time_is_a_real_datetime_too():
    """Both sides real datetimes, so kind="time" columns filter and sort.
    A pre-formatted string silently breaks every date-based filter -- the
    failure domain_loader.py already documents."""
    fix = location_loader.position_fixes([_live(_url())])[0]
    assert fix["RecordTimeUtc"] == datetime.datetime(2024, 6, 15, 9, 0, 1,
                                                     tzinfo=UTC)


# --- the disagreement column --------------------------------------------

def test_the_disagreement_is_signed_and_names_which_side_is_ahead():
    """The device controls the fix time and does not control the cache
    write. A cross-check that needs mental arithmetic across two
    differently-encoded columns is one nobody performs."""
    fix = location_loader.position_fixes(
        [_live(_url(clientlocationtimestamp=EPOCH_MS))])[0]
    # Fix at 12:00:01, cache wrote at 09:00:01 -- three hours ahead.
    assert fix["Disagreement"].startswith("+3 h")
    assert "device ahead" in fix["Disagreement"]


def test_a_device_behind_the_cache_reads_as_behind():
    fix = location_loader.position_fixes(
        [_live(_url(clientlocationtimestamp="2024-06-15T08:59:20Z"))])[0]
    assert "41 s" in fix["Disagreement"]
    assert "device behind" in fix["Disagreement"]
    assert fix["Disagreement"].startswith("−")


def test_agreement_reads_as_none_not_as_zero():
    fix = location_loader.position_fixes(
        [_live(_url(clientlocationtimestamp="2024-06-15T09:00:01Z"))])[0]
    assert fix["Disagreement"] == "none"


def test_a_missing_side_reads_as_not_supplied_never_as_zero():
    """"0" would assert an agreement that was never measured."""
    no_fix_time = location_loader.position_fixes([_live(_url())])[0]
    assert no_fix_time["Disagreement"] == ABSENCE_NOT_SUPPLIED
    no_record_time = location_loader.position_fixes(
        [_live(_url(clientlocationtimestamp=EPOCH_MS), modified="")])[0]
    assert no_record_time["Disagreement"] == ABSENCE_NOT_SUPPLIED
    undecodable = location_loader.position_fixes(
        [_live(_url(clientlocationtimestamp="123456"))])[0]
    assert undecodable["Disagreement"] == ABSENCE_NOT_SUPPLIED


# --- coordinates: stored precision on screen, rounding only where labelled

def test_the_coordinate_cell_carries_every_digit_that_was_stored():
    """Rounding evidence for display is exactly what this tool does not
    do. The rounding lives in Place, labelled as the grouping it is."""
    fix = location_loader.position_fixes(
        [_live(_url(lat="51.50735678901234", lon="-0.12775432109876"))],
        grouping="11m")[0]
    assert "51.50735678901234" in fix["Coords"]
    assert "-0.12775432109876" in fix["Coords"]
    assert fix["Place"] == "51.5074, -0.1278"


def test_place_uses_the_same_four_decimal_places_the_cluster_label_does():
    """The drill from a place row to its fixes is an exact-value match on
    this key, so the two spellings have to be produced the same way."""
    fixes = location_loader.position_fixes(
        [_live(_url(lat="51.50741", lon="-0.12779")),
         _live(_url(lat="51.50739", lon="-0.12781"))])
    rows = location_loader.places(fixes)
    assert len(rows) == 1
    assert {f["Place"] for f in fixes} == {rows[0]["Coords"]}


# --- what a fix is worth: never blank, never invented --------------------

def test_accuracy_and_provider_read_as_not_supplied_when_the_request_omitted_them():
    """A blank cell reads as an oversight. The absence is itself a fact
    about the request."""
    fix = location_loader.position_fixes([_live(_url())])[0]
    assert fix["Accuracy"] == ABSENCE_NOT_SUPPLIED
    assert fix["Provider"] == ABSENCE_NOT_SUPPLIED


def test_a_supplied_accuracy_is_the_number_the_device_sent():
    fix = location_loader.position_fixes(
        [_live(_url(clientlocationaccuracy="12", clientlocationprovider="wifi"))])[0]
    assert fix["Accuracy"] == 12.0
    assert fix["Provider"] == "wifi"


def test_the_assessment_is_the_engine_s_own_words_and_carries_the_non_attribution_sentence():
    """This view never writes its own version of that sentence -- one
    wording in the world, not two."""
    fix = location_loader.position_fixes(
        [_live(_url(clientlocationaccuracy="12"))])[0]
    assert fix["Assessment"] == geolocation._assess(12.0, "")
    assert location_loader.NON_ATTRIBUTION in fix["Assessment"]


def test_the_non_attribution_sentence_is_still_the_engine_s_own_wording():
    """The drift guard. The shell appends this literal to the one band
    that lacks it, so if the engine ever rewords its own copy the two
    would silently become two different claims about the same thing."""
    assert location_loader.NON_ATTRIBUTION in geolocation._assess(12.0, "")
    assert location_loader.NON_ATTRIBUTION in geolocation._assess(1000.0, "")


def test_a_fix_that_supplied_no_accuracy_still_carries_the_caveat():
    """geolocation._assess's no-accuracy band ends at "how tightly it
    locates the device is unknown" and carries no non-attribution sentence
    at all -- the one band where it matters most, on the weakest claim on
    the screen. The engine is carried over and may not have that string
    altered, so the shell appends it."""
    fix = location_loader.position_fixes([_live(_url())])[0]
    assert "how tightly it locates the device is unknown" in fix["Assessment"]
    assert location_loader.NON_ATTRIBUTION in fix["Assessment"]


def test_the_caveat_is_never_appended_twice():
    fix = location_loader.position_fixes(
        [_live(_url(clientlocationaccuracy="12"))])[0]
    assert fix["Assessment"].count(location_loader.NON_ATTRIBUTION) == 1


def test_a_fix_carries_the_record_behind_it_by_reference():
    live = _live(_url())
    fix = location_loader.position_fixes([live])[0]
    assert fix["_record"] is live
    assert fix["_kind"] in record_kinds.ALL


def test_a_carved_fix_names_a_carved_kind():
    artifact = _artifact(_url())
    fix = location_loader.position_fixes([], [artifact])[0]
    assert fix["_kind"] in record_kinds.CARVED
    assert fix["_record"] is artifact


# --- places --------------------------------------------------------------

def test_a_place_row_says_it_is_an_aggregate_and_names_its_members():
    fixes = location_loader.position_fixes(
        [_live(_url()), _live(_url(lat="51.50741"))])
    rows = location_loader.places(fixes)
    assert rows[0]["_kind"] is record_kinds.K_PLACE
    assert record_kinds.K_PLACE in record_kinds.AGGREGATES
    assert rows[0]["Fixes"] == 2
    members = rows[0]["_members"]
    assert all(any(m is f for m in members) for f in fixes)


def test_a_place_always_carries_an_accuracy_key():
    """export_location_pdf reads p.get("Accuracy") and cluster_summary has
    never emitted it, so that PDF column renders blank today. Supplying it
    here fixes the export with no engine edit."""
    rows = location_loader.places(
        location_loader.position_fixes([_live(_url())]))
    assert "Accuracy" in rows[0]


def test_a_place_accuracy_is_a_range_never_a_mean():
    """Averaging would invent a precision no single fix claimed. 12 and
    140 must both be on screen, and 76 must not."""
    fixes = location_loader.position_fixes(
        [_live(_url(clientlocationaccuracy="12")),
         _live(_url(clientlocationaccuracy="140"))])
    accuracy = location_loader.places(fixes)[0]["Accuracy"]
    assert "12" in accuracy and "140" in accuracy
    assert "76" not in accuracy
    assert "–" in accuracy or "-" in accuracy


def test_a_place_where_every_fix_agrees_states_one_radius():
    fixes = location_loader.position_fixes(
        [_live(_url(clientlocationaccuracy="30")),
         _live(_url(clientlocationaccuracy="30"))])
    assert location_loader.places(fixes)[0]["Accuracy"] == "±30 m"


def test_a_place_where_nobody_supplied_one_says_not_supplied():
    rows = location_loader.places(
        location_loader.position_fixes([_live(_url())]))
    assert rows[0]["Accuracy"] == ABSENCE_NOT_SUPPLIED


def test_a_mixed_place_states_how_many_fixes_supplied_nothing():
    """A range computed over the fixes that answered, plus the count that
    did not -- so the range is not read as covering every fix."""
    fixes = location_loader.position_fixes(
        [_live(_url(clientlocationaccuracy="12")),
         _live(_url(clientlocationaccuracy="140")),
         _live(_url()), _live(_url())])
    accuracy = location_loader.places(fixes)[0]["Accuracy"]
    assert "12" in accuracy and "140" in accuracy
    assert "2 fixes supplied none" in accuracy


def test_a_place_counts_its_carved_fixes():
    fixes = location_loader.position_fixes([_live(_url())], [_artifact(_url())])
    rows = location_loader.places(fixes)
    assert len(rows) == 1
    assert rows[0]["Fixes"] == 2
    assert rows[0]["Carved"] == 1


def test_first_and_last_seen_are_real_datetimes_ordered_as_times():
    """cluster_summary orders raw strings, so on mixed formats
    "1718452801000" sorts before "2024-06-15 09:00:01" and the pair it
    reports is wrong. Re-derived here from the decoded instants."""
    fixes = location_loader.position_fixes([
        _live(_url(clientlocationtimestamp=EPOCH_MS)),
        _live(_url(clientlocationtimestamp="2024-06-15T07:30:00Z")),
    ])
    row = location_loader.places(fixes)[0]
    assert isinstance(row["FirstSeen"], datetime.datetime)
    assert isinstance(row["LastSeen"], datetime.datetime)
    assert row["FirstSeen"] == datetime.datetime(2024, 6, 15, 7, 30, tzinfo=UTC)
    assert row["LastSeen"] == EPOCH_MS_UTC


def test_a_place_with_no_time_on_any_fix_reports_no_first_or_last():
    fixes = location_loader.position_fixes([_live(_url(), modified="")])
    row = location_loader.places(fixes)[0]
    assert row["FirstSeen"] is None and row["LastSeen"] is None


def test_a_provider_string_containing_the_separator_survives_as_one_value():
    """Provider is a DEVICE-reported string, outside this tool's control --
    a provider that already reports itself as one string containing ", "
    must survive intact in the raw value list a multi-value filter reads
    (Column.multi_source points here), never be re-split by a generic
    ", ".split() that cannot tell it apart from two real values."""
    fixes = location_loader.position_fixes(
        [_live(_url(clientlocationprovider="wifi, cell"))])
    row = location_loader.places(fixes)[0]
    assert row["Providers"] == "wifi, cell"
    assert row["ProvidersValues"] == ["wifi, cell"]


def test_place_providers_never_show_the_absence_token_as_a_source():
    """Provider is overwritten with (not supplied) on the fix, and a
    cluster that joined that string would report the tool's own vocabulary
    as something the device said."""
    fixes = location_loader.position_fixes(
        [_live(_url(clientlocationprovider="wifi")), _live(_url())])
    row = location_loader.places(fixes)[0]
    assert row["Providers"] == "wifi"
    empty = location_loader.places(
        location_loader.position_fixes([_live(_url())]))[0]
    assert empty["Providers"] == ABSENCE_NOT_SUPPLIED


# --- the count lines -----------------------------------------------------

def test_before_a_scan_the_note_says_nobody_has_looked_yet():
    """DOMAIN_CARVED_NOT_SCANNED_NOTE's shape: never show a carved count of
    zero and let it read as "nothing was deleted"."""
    note = location_loader.fixes_note(
        location_loader.position_fixes([_live(_url())]), scan_run=False)
    assert location_loader.CARVED_NOT_SCANNED_NOTE in note


def test_after_a_scan_the_note_states_how_many_came_from_deleted_data():
    fixes = location_loader.position_fixes([_live(_url())], [_artifact(_url())])
    note = location_loader.fixes_note(fixes, scan_run=True)
    assert location_loader.CARVED_NOT_SCANNED_NOTE not in note
    assert "1" in note and "recovered" in note


def test_the_note_states_how_many_fixes_supplied_no_accuracy():
    note = location_loader.fixes_note(
        location_loader.position_fixes([_live(_url())]), scan_run=True)
    assert "no accuracy" in note


def test_the_places_note_states_the_grouping_and_that_a_place_is_a_summary():
    fixes = location_loader.position_fixes([_live(_url())])
    note = location_loader.places_note(fixes, location_loader.places(fixes))
    assert location_loader.grouping_for(
        location_loader.DEFAULT_GROUPING).description in note
    assert "summary" in note.lower()


def test_the_places_note_does_not_promise_a_single_click_does_anything():
    """A single click changes nothing on this grid -- only
    activate_cell (double-click, Enter, or the right-click menu's Open)
    does. "open one, or click its coordinates" reads as a single click
    being enough; it must name an action that actually opens something."""
    fixes = location_loader.position_fixes([_live(_url())])
    note = location_loader.places_note(fixes, location_loader.places(fixes))
    assert "open one, or click its coordinates" not in note, note
    assert "double-click" in note.lower(), note


@pytest.mark.parametrize("word", ["confirm", "proves", "demonstrates"])
def test_no_sentence_this_module_states_claims_more_than_it_can(word):
    for text in (location_loader.CARVED_NOT_SCANNED_NOTE,
                 location_loader.LOCATION_CAVEAT,
                 location_loader.EMPTY_FIXES_TEXT,
                 location_loader.fixes_note(
                     location_loader.position_fixes([_live(_url())]),
                     scan_run=True)):
        assert word not in text.lower()


# --- the exports the fixes feed ------------------------------------------

def test_a_carved_fix_reaches_the_kml_carved_folder_and_a_live_one_does_not(tmp_path):
    """export_location_kml splits on _loc_value(fix, "Origin"). The
    invariant above is what makes this land in the right folder."""
    fixes = location_loader.position_fixes(
        [_live(_url())], [_artifact(_url(lat="48.8566", lon="2.3522"))])
    out = tmp_path / "fixes.kml"
    ForensicEngine().export_location_kml(fixes, str(out))
    text = out.read_text(encoding="utf-8")
    # The FOLDER names, not the <Style id="carved"> definition above them.
    live_at = text.index("<name>Live records")
    carved_at = text.index("<name>Recovered from deleted")
    assert live_at < carved_at
    assert text.count("<Placemark>") == 2
    # One in each folder, not both in one.
    assert text[carved_at:].count("<Placemark>") == 1
    assert text[live_at:carved_at].count("<Placemark>") == 1


def test_the_places_the_pdf_reads_are_a_list_of_dicts():
    """export_location_pdf iterates `places` and calls p.get(...) on each.
    export_runner used to store them with dict(places), which raises on a
    list of dicts before a single byte is written."""
    rows = location_loader.places(
        location_loader.position_fixes([_live(_url())]))
    assert isinstance(rows, list)
    assert all(isinstance(p, dict) for p in rows)
    assert all("Latitude" in p and "Longitude" in p for p in rows)


def test_a_note_never_doubles_a_full_stop():
    """Some clauses are built here and some are whole named sentences that
    end in a period of their own. Looked at on screen: "...to that
    provider.. A fix is..."."""
    for note in (location_loader.fixes_note([], scan_run=False),
                 location_loader.fixes_note(
                     location_loader.position_fixes([_live(_url())]),
                     scan_run=True),
                 location_loader.places_note([], [])):
        assert ".." not in note, note
        assert note.endswith(".")


def test_the_accuracy_clause_is_not_a_double_negative():
    """"None reported no accuracy at all" reads as its own opposite at a
    glance. Say what happened."""
    note = location_loader.fixes_note(
        location_loader.position_fixes(
            [_live(_url(clientlocationaccuracy="12"))]), scan_run=True)
    assert "Every one reported an accuracy" in note
    assert "None reported no accuracy" not in note


# --- the offset-carrying fix time ------------------------------------------
#
# _parse_stamp's own docstring promises "an aware UTC datetime", and every
# caller relies on that: the FixTimeUtc column is HEADED (UTC), and
# record_model._format prints wall-clock digits via strftime without ever
# consulting tzinfo. So a stamp returned in its ORIGINAL offset is rendered
# as though those digits were UTC -- a five-and-a-half-hour error under a
# heading that names its own zone.
#
# This is the same rule history.py already states for AccessedLocal: a
# column must never show a value tagged with a zone it does not claim,
# because a disagreement between the UTC and LOCAL columns is itself the
# evidence a timezone change would leave. A value that only PRETENDS to
# disagree is a fabricated finding.

def test_an_offset_carrying_fix_time_is_converted_not_relabelled():
    """+05:30 09:00:01 is 03:30:01 UTC, and the UTC column must say so."""
    got = location_loader._parse_stamp("2024-06-15T09:00:01+05:30")
    assert got is not None
    assert got.utcoffset() == datetime.timedelta(0), (
        "returned %r, which still carries offset %s -- the FixTimeUtc "
        "column prints wall-clock digits without consulting tzinfo, so "
        "this renders as 09:00:01 under a (UTC) heading"
        % (got, got.utcoffset()))
    assert (got.hour, got.minute, got.second) == (3, 30, 1), (
        "rendered digits would be %02d:%02d:%02d, not the true UTC instant"
        % (got.hour, got.minute, got.second))


def test_a_zulu_stamp_and_its_offset_twin_agree():
    """The same instant written two ways must reach the same value."""
    zulu = location_loader._parse_stamp("2024-06-15T03:30:01Z")
    offset = location_loader._parse_stamp("2024-06-15T09:00:01+05:30")
    assert zulu == offset, "%r != %r" % (zulu, offset)


# --- the anchor is not a write time ----------------------------------------
#
# recovery_engine._carve_strings sets NearbyFiletime for a URL recovered from
# unallocated bytes: a plausible FILETIME that happened to sit NEAR those
# bytes. evidence_model grades it CARVED and describes it as "A plausible
# FILETIME found adjacent to the carved..." -- it is evidence of
# NEIGHBOURHOOD, not of when the record was written.
#
# geolocation.collect reads ModifiedTime as THE CACHE WRITE TIME, and the
# Location grid heads that column "Cache wrote (UTC)". Letting the anchor
# fall into that key therefore promotes "bytes near this stamp" into "the
# cache wrote this record at this instant" -- a claim the evidence does not
# support, on the one screen whose whole subject is where a device was.
#
# The previous code did this deliberately, reasoning that Deleted Records
# already showed the anchor for the same row and two screens should agree.
# But that grid's column is a generic Timestamp; this one names a specific
# act. Two screens agreeing on a wrong label is worse than one being right.

def _string_carve(**over):
    """A string carve: no rebound columns, only a neighbouring FILETIME."""
    art = {"Url": "https://example.invalid/?lat=1.0&lon=2.0",
           "RecoverySource": "unallocated",
           "NearbyFiletime": datetime.datetime(2024, 6, 15, 9, 0, 1,
                                               tzinfo=datetime.timezone.utc)}
    art.update(over)
    return art


def test_a_neighbouring_filetime_is_not_promoted_to_a_write_time():
    entry = location_loader._carved_entry(_string_carve())
    assert not entry.get("ModifiedTime"), (
        "ModifiedTime is %r -- geolocation.collect reads that key as the "
        "cache write time and the grid heads it 'Cache wrote (UTC)', so a "
        "byte-proximity anchor is being presented as the instant the cache "
        "wrote this record" % (entry.get("ModifiedTime"),))


def test_the_anchor_is_still_carried_under_its_own_name():
    """Dropping it from ModifiedTime must not lose it -- it is real evidence
    about the neighbourhood, and stays available under the name that says
    exactly that."""
    entry = location_loader._carved_entry(_string_carve())
    assert entry.get("NearbyFiletime") is not None


def test_a_structured_carve_keeps_its_genuinely_rebound_write_time():
    """The fix must not cost the case where a real column WAS recovered."""
    real = datetime.datetime(2023, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
    entry = location_loader._carved_entry(_string_carve(ModifiedTime=real))
    assert entry.get("ModifiedTime") == real


# --- supplied but unreadable is not absent ---------------------------------
#
# geolocation matches six accuracy parameter names, then does
# `float(accuracy)` inside a try and drops the raw string on ValueError. So
# `&accuracy=high` and `&radius=5km` -- both shapes ACCURACY_PARAMS matches
# -- arrive with AccuracyMetres None and nothing else, and the shell wrote
# ABSENCE_NOT_SUPPLIED, whose declared meaning is "the application did not
# include this value".
#
# The application DID include it. "Absent" and "present but not a number"
# are different facts about the request, and the second is the more
# interesting one: it says the requesting application had a notion of
# accuracy it expressed in some other vocabulary. Showing the examiner the
# value the URL actually carried says more than any absence token could.

def test_geolocation_keeps_the_raw_accuracy_it_could_not_parse():
    fixes = geolocation.extract_from_url(
        "https://example.invalid/?lat=51.5&lon=-0.12&accuracy=high")
    assert fixes, "no fix extracted"
    assert fixes[0].get("AccuracyMetres") is None
    assert fixes[0].get("AccuracyRaw") == "high", (
        "the raw parameter is discarded, so nothing downstream can tell "
        "'absent' from 'present but not a number'")


def test_an_unreadable_accuracy_is_not_reported_as_not_supplied():
    fixes = geolocation.extract_from_url(
        "https://example.invalid/?lat=51.5&lon=-0.12&radius=5km")
    fix = fixes[0]
    fix["_entry"] = {}
    location_loader._shape(fix)
    assert fix["Accuracy"] != ABSENCE_NOT_SUPPLIED, (
        "the URL supplied an accuracy; reporting it as not supplied "
        "misstates what the request contained")
    assert "5km" in str(fix["Accuracy"]), (
        "Accuracy reads %r -- the value the request actually carried "
        "should be visible" % (fix["Accuracy"],))


def test_a_genuinely_absent_accuracy_still_reads_as_not_supplied():
    fixes = geolocation.extract_from_url(
        "https://example.invalid/?lat=51.5&lon=-0.12")
    fix = fixes[0]
    fix["_entry"] = {}
    location_loader._shape(fix)
    assert fix["Accuracy"] == ABSENCE_NOT_SUPPLIED


# --- an assumed zone is an assumption, and must say so ---------------------
#
# _parse_stamp stamps a zoneless ISO value tzinfo=UTC so it can be compared
# with the record's own time at all. That is a reasonable reading, but it is
# a READING: the application that wrote the URL did not say what zone it
# meant. Presented identically to an explicit Z, it becomes the tool's
# assertion rather than the request's.
#
# FixTimeFormat is the column headed "Fix time read as" -- the one place
# that names the reading -- so the assumption belongs there. The test does
# not pin wording; it pins that two different facts are not described
# identically.

def test_a_zoneless_fix_time_is_not_described_like_an_explicit_utc_one():
    zoneless = {"FixTimestamp": "2024-06-15T09:00:01"}
    explicit = {"FixTimestamp": "2024-06-15T09:00:01Z"}
    _, form_zoneless = location_loader._decode_fix_time(zoneless)
    _, form_explicit = location_loader._decode_fix_time(explicit)
    assert form_zoneless != form_explicit, (
        "both read as %r -- a stamp whose zone the tool supplied is "
        "indistinguishable from one the request stated" % (form_explicit,))


def test_the_zoneless_reading_still_produces_the_same_instant():
    """The assumption is unchanged; only its labelling is."""
    stamp, _ = location_loader._decode_fix_time(
        {"FixTimestamp": "2024-06-15T09:00:01"})
    assert stamp is not None
    assert stamp.utcoffset() == datetime.timedelta(0)
    assert (stamp.hour, stamp.minute) == (9, 0)


# --- the disagreement column must sort by what it measures -----------------
#
# _disagreement's own docstring calls this "THE COLUMN THAT MAKES 'which it
# can be told to fake' OPERABLE", and promises a disagreement is something
# an examiner can "find, sort by and filter on". Its value is a formatted
# string, so sorting it ordered lexically and the promise did not hold:
# descending put "-3 h (device behind)" above "+5 d (device ahead)".

def test_a_disagreement_carries_the_magnitude_it_is_sorted_by():
    fix_dt = datetime.datetime(2024, 6, 15, 12, 0, 0,
                               tzinfo=datetime.timezone.utc)
    rec_dt = datetime.datetime(2024, 6, 15, 9, 0, 0,
                               tzinfo=datetime.timezone.utc)
    assert location_loader._disagreement_seconds(fix_dt, rec_dt) == 10800
    assert location_loader._disagreement_seconds(rec_dt, fix_dt) == -10800
    assert location_loader._disagreement_seconds(None, rec_dt) is None


def test_the_disagreement_column_declares_the_sibling_it_sorts_on(qtbot):
    from webcache.views.location import LocationView
    view = LocationView()
    qtbot.addWidget(view)
    cols = [c for rs in view._record_sets for c in rs.columns
            if c.key == "Disagreement"]
    assert cols, "no Disagreement column found"
    assert cols[0].sort_by == "DisagreementSeconds", (
        "sort_by is %r -- the column still orders by its formatted text"
        % (cols[0].sort_by,))


# --- a carved fix whose cache time was not recovered says so ---------------

def test_a_carved_fix_with_no_cache_time_says_not_recovered_not_blank():
    """A blank cell would stand in for an unknown. The column shows the
    absence word, still sorts by the real time, and the cross-check says
    which side is missing rather than that nothing was supplied."""
    from webcache.provenance import ABSENCE_NOT_RECOVERED
    fix = location_loader.position_fixes(
        [], [_artifact(_url(t=EPOCH_MS), NearbyFiletime=None)])[0]
    assert fix["RecordTimeUtc"] is None
    assert fix["RecordTimeShown"] == ABSENCE_NOT_RECOVERED
    assert fix["Disagreement"] == ABSENCE_NOT_RECOVERED


def test_a_fix_with_a_cache_time_shows_the_time_itself():
    fix = location_loader.position_fixes([_live(_url())])[0]
    assert fix["RecordTimeShown"] == fix["RecordTimeUtc"]
    assert isinstance(fix["RecordTimeShown"], datetime.datetime)
