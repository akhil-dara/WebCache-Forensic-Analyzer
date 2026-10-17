"""The format catalogue, and the two writers no engine function does.

Qt-free: a catalogue is data and a CSV writer is a file, and neither needs
a window open to be checked. The engine is imported (this is shell/, which
is allowed to) only to prove the writers route timestamps through the
SAME excel_datetime() the workbook writer already uses -- the named past
defect was two writers drifting apart, so a test that checked only one of
them would be the same mistake in a new place.
"""
import csv
import datetime
import os

import pytest

from webcache.engine import forensic_engine
from webcache.provenance import CARVED_ORIGIN
from webcache.shell import export_formats as F
from webcache.shell import record_kinds
from webcache.widgets.column_spec import Column


# --- the catalogue ------------------------------------------------------

def test_every_declared_format_is_fully_described():
    assert F.CATALOGUE, "an empty catalogue is a page with nothing on it"
    for fmt in F.CATALOGUE:
        assert fmt.key and fmt.title, fmt.key
        assert fmt.description, "%s has no description" % fmt.key
        assert fmt.group in (F.G_COURT, F.G_GENERAL, F.G_POSITION,
                             F.G_BUNDLE), fmt.key
        assert fmt.icon, fmt.key
        assert fmt.writes in ("file", "directory"), fmt.key
        if fmt.writes == "file":
            assert fmt.extension.startswith("."), fmt.key
        assert fmt.default_basename, fmt.key


def test_every_capability_token_a_format_names_has_a_reason_literal():
    """A card that greys out without saying why is a dead control."""
    for fmt in F.CATALOGUE:
        for token in fmt.requires:
            assert token in F.UNAVAILABLE_REASON, (
                "%s requires %r with no sentence to show for it"
                % (fmt.key, token))
            assert len(F.UNAVAILABLE_REASON[token]) > 20, token


def test_the_catalogue_keys_are_unique():
    keys = [f.key for f in F.CATALOGUE]
    assert len(keys) == len(set(keys))


def test_the_position_formats_are_declared():
    """A format silently missing from the page reads as a format this
    tool does not have."""
    position = [f.key for f in F.formats_in(F.G_POSITION)]
    assert set(position) == {"loc_csv", "loc_kml", "loc_json",
                             "loc_xlsx"}


def test_no_position_format_asks_for_an_acknowledgement():
    """The position consent gate is removed; a card that still
    promised one would describe a step that no longer happens."""
    for fmt in F.formats_in(F.G_POSITION):
        assert "acknowledg" not in fmt.description.lower(), fmt.key


def test_formats_in_returns_catalogue_order_not_a_per_call_sort():
    court = [f.key for f in F.formats_in(F.G_COURT)]
    assert court == [f.key for f in F.CATALOGUE if f.group == F.G_COURT]


def test_availability_answers_for_every_key_always():
    caps = F.capabilities(None, [], None, None)
    avail = F.availability(caps)
    assert set(avail) == {f.key for f in F.CATALOGUE}
    for key, (ok, reason) in avail.items():
        assert ok is False, key
        assert reason, "%s is disabled with no reason" % key


def test_an_available_format_carries_an_empty_reason():
    caps = F.capabilities(object(), [{"Url": "x"}], {"total_entries": 1}, None)
    ok, reason = F.availability(caps)["csv"]
    assert ok is True
    assert reason == ""


def test_position_stays_unavailable_when_no_fix_was_found():
    """An exhibit whose URLs never reported a position is the ordinary
    case, and it is what the real exhibit this port was built against
    turned out to be."""
    caps = F.capabilities(object(), [{"Url": "x"}], {"total_entries": 1}, None)
    for key in ("loc_csv", "loc_kml"):
        ok, reason = F.availability(caps)[key]
        assert ok is False
        assert reason == F.UNAVAILABLE_REASON["location_fixes"]


def test_capabilities_called_without_fixes_still_answers_false():
    """Every existing caller passes four arguments. The token has to stay
    False for them rather than becoming a KeyError or a silent True."""
    caps = F.capabilities(object(), [{"Url": "x"}], {"t": 1}, None)
    assert caps["location_fixes"] is False


def test_one_position_fix_is_what_makes_the_three_cards_available():
    caps = F.capabilities(object(), [{"Url": "x"}], {"t": 1}, None,
                          location_fixes=[{"Latitude": 51.5,
                                           "Longitude": -0.1}])
    assert caps["location_fixes"] is True
    for key in ("loc_csv", "loc_kml"):
        ok, reason = F.availability(caps)[key]
        assert ok is True, reason


def test_the_unavailable_reason_states_the_fact_not_a_phase_that_has_ended():
    """It used to say the Location view "is not built in this phase". That
    phase has ended, and a card explaining itself with a stale roadmap
    tells an examiner nothing about their exhibit."""
    reason = F.UNAVAILABLE_REASON["location_fixes"]
    assert "phase" not in reason.lower()
    # The distinction the catalogue's own docstring insists on: nothing
    # was found is not the same as nobody has looked.
    assert "Recover deleted records" in reason
    assert "no cached URL reported a position" in reason


def test_position_formats_say_no_evidence_is_open_when_nothing_is_open():
    """loc_csv/loc_kml/loc_pdf declared ONLY the location_fixes
    token, whose reason is a statement about an EXHIBIT ("No position
    fixes were found in this exhibit..."). capabilities() defaults
    location_fixes to () (False) whether evidence is open with none
    found OR nothing is open at all, so with NO database open those
    three cards stated the exhibit-shaped sentence too -- while every
    other card on the page correctly said no evidence is open."""
    caps = F.capabilities(None, [], None, None)
    for key in ("loc_csv", "loc_kml"):
        ok, reason = F.availability(caps)[key]
        assert ok is False
        assert reason == F.UNAVAILABLE_REASON["entries"], (key, reason)


def test_pdf_names_the_missing_library_not_a_generic_failure():
    caps = F.capabilities(object(), [{"Url": "x"}], {"t": 1}, None)
    caps["reportlab"] = False
    ok, reason = F.availability(caps)["pdf"]
    assert ok is False
    assert "reportlab" in reason


# --- origin_cell --------------------------------------------------------

def test_origin_cell_tells_the_three_kinds_of_row_apart():
    assert F.origin_cell({"_kind": record_kinds.K_HISTORY}) == "Live record"
    assert F.origin_cell({"Origin": CARVED_ORIGIN}) == CARVED_ORIGIN
    assert F.origin_cell(
        {"_kind": record_kinds.K_DOMAIN}) == "Aggregate (not a record)"


def test_an_aggregate_never_borrows_a_records_vocabulary():
    row = {"_kind": record_kinds.K_INDICATOR, "Origin": "Live record"}
    assert F.origin_cell(row) == "Aggregate (not a record)"


# --- write_view_csv -----------------------------------------------------

def _cols():
    return [Column("CleanUrl", "Address", 400, kind="url"),
            Column("Count", "Visits", 80, kind="num"),
            Column("When", "Last visit (UTC)", 160, kind="time"),
            Column("Same", "Container", 100, kind="text")]


def _rows():
    return [
        {"CleanUrl": "a", "Count": 2, "Same": "c1",
         "When": datetime.datetime(2026, 2, 17, 16, 50, 9),
         "_kind": record_kinds.K_HISTORY},
        {"CleanUrl": "b", "Count": 1, "Same": "c1", "When": None,
         "Origin": CARVED_ORIGIN, "Source": "V01.log",
         "_kind": record_kinds.K_CARVED_STRUCT},
    ]


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def test_the_file_holds_exactly_the_rows_given_in_the_order_given(tmp_path):
    path = str(tmp_path / "out.csv")
    scope = {}
    n = F.write_view_csv(_rows(), _cols(), path, scope)
    body = _read(path)
    assert n == 2
    assert len(body) == 3, "one header plus two rows"
    assert [r[0] for r in body[1:]] == ["a", "b"]


def test_origin_and_recordsource_are_always_appended(tmp_path):
    """A carved row must stay distinguishable in a CSV whose view never
    declared an Origin column."""
    path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), path, {})
    header, live, carved = _read(path)
    assert header[-2:] == ["Origin", "RecordSource"]
    assert live[-2] == "Live record"
    assert carved[-2] == CARVED_ORIGIN
    assert carved[-1] == "V01.log"


def test_a_hidden_constant_column_is_still_in_the_file(tmp_path):
    """The table hides it because it holds one value; that value is still
    a fact about the file."""
    cols = _cols()
    cols[3].hidden = True
    cols[3].constant = "c1"
    path = str(tmp_path / "out.csv")
    scope = {}
    F.write_view_csv(_rows(), cols, path, scope)
    header = _read(path)[0]
    assert "Container" in header


def test_every_datetime_cell_goes_through_excel_datetime(tmp_path):
    """The named regression: a workbook full of text-not-date timestamps.
    export_xlsx already calls excel_datetime; this writer is the other
    one, and a test that trusted either would be the same mistake twice.
    """
    path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), path, {})
    cell = _read(path)[1][2]
    assert cell == forensic_engine.excel_datetime(
        "2026-02-17 16:50:09"), cell
    assert "T" not in cell, "an ISO T separator is not what Excel parses"


def test_a_non_timestamp_column_holding_a_date_shaped_value_is_not_rewritten(
        tmp_path):
    """_clean() ran excel_datetime() over EVERY
    string cell, not only genuine timestamp columns. excel_datetime()
    matches anything date-shaped, so a stored value that merely LOOKS like
    a timestamp -- "2026-02-17T16:50:09Z" sitting in an ordinary text
    column -- came out "2026-02-17 16:50:09": the export silently rewrote
    what the database actually stored. Only a column the view itself
    declared kind="time"/"time_local" may go through the date helper.
    """
    cols = _cols()                      # "Same" is declared kind="text"
    rows = [{"CleanUrl": "a", "Count": 1, "When": None,
             "Same": "2026-02-17T16:50:09Z", "_kind": record_kinds.K_HISTORY}]
    path = str(tmp_path / "out.csv")
    F.write_view_csv(rows, cols, path, {})
    body = _read(path)
    assert body[1][3] == "2026-02-17T16:50:09Z", (
        "a non-timestamp column must reproduce the stored value unchanged")


def test_a_formula_leading_value_is_written_byte_identical_and_counted(
        tmp_path):
    rows = [{"CleanUrl": "=SUM(A1:A9)", "Count": 1, "Same": "", "When": None,
             "_kind": record_kinds.K_HISTORY},
            {"CleanUrl": "@here", "Count": 1, "Same": "", "When": None,
             "_kind": record_kinds.K_HISTORY}]
    path = str(tmp_path / "out.csv")
    scope = {}
    F.write_view_csv(rows, _cols(), path, scope)
    body = _read(path)
    assert body[1][0] == "=SUM(A1:A9)", (
        "changing a stored value to make a spreadsheet behave is evidence "
        "tampering")
    assert body[2][0] == "@here"
    assert scope["formula_values"] == 2


def test_a_negative_number_is_not_counted_as_a_formula(tmp_path):
    rows = [{"CleanUrl": "a", "Count": -5, "Same": "", "When": None,
             "_kind": record_kinds.K_HISTORY}]
    scope = {}
    F.write_view_csv(rows, _cols(), str(tmp_path / "o.csv"), scope)
    assert scope["formula_values"] == 0


def test_a_lone_surrogate_does_not_truncate_the_file(tmp_path):
    """Carved bytes decode to lone surrogates routinely; unsanitised they
    abort the write mid-file and leave a CSV that looks complete."""
    rows = [{"CleanUrl": "bad\ud800value", "Count": 1, "Same": "",
             "When": None, "_kind": record_kinds.K_CARVED_STRING}]
    path = str(tmp_path / "out.csv")
    F.write_view_csv(rows, _cols(), path, {})
    assert len(_read(path)) == 2


def test_the_file_only_appears_once_it_is_complete(tmp_path):
    """atomic_write: existence means the export finished."""
    path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), path, {})
    assert os.path.exists(path)
    assert not os.path.exists(path + ".partial")


# --- the sidecar --------------------------------------------------------

def _stamp():
    return {"tool_version": "5.0.0", "exported_utc": "2026-09-01T00:00:00Z",
            "evidence": {"C:\\ex\\WebCacheV01.dat": "ab" * 32},
            "evidence_sizes": {"C:\\ex\\WebCacheV01.dat": 10},
            "shown": 1, "total": 2}


def _scope(**over):
    base = {"view": "history", "view_label": "History",
            "columns": ["Address", "Visits"], "hidden_columns": ["Container"],
            "rows_in_file": 1, "rows_in_view": 1, "rows_in_record_set": 2,
            "text_filter": "example", "chip_text": 'search "example"',
            "conditions": {"Count": "> 3"}, "values": {"Domain": ["a", "b"]},
            "is_subset": True, "live_rows": 1, "carved_rows": 0,
            "recovery_scan_run": False, "unit": "records"}
    base.update(over)
    return base


def test_a_filtered_sidecar_states_the_subset_in_capitals(tmp_path):
    csv_path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), csv_path, {})
    side = F.write_view_provenance(csv_path, _stamp(), _scope(), caution=0)
    text = open(side, encoding="utf-8").read()
    assert side.endswith(".provenance.txt")
    assert "THIS IS A FILTERED SUBSET, NOT THE WHOLE VIEW" in text
    assert "example" in text
    assert "> 3" in text
    assert "Re-run with filters cleared for the whole view" in text


def test_an_unfiltered_sidecar_says_so_plainly(tmp_path):
    csv_path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), csv_path, {})
    side = F.write_view_provenance(
        csv_path, _stamp(),
        _scope(is_subset=False, text_filter="", chip_text="", conditions={},
               values={}, rows_in_file=2, rows_in_view=2,
               rows_in_record_set=2), caution=0)
    text = open(side, encoding="utf-8").read()
    assert "THIS IS A FILTERED SUBSET" not in text
    assert "No filter was in force" in text


def test_the_sidecar_hashes_the_csv_it_sits_beside(tmp_path):
    import hashlib
    csv_path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), csv_path, {})
    side = F.write_view_provenance(csv_path, _stamp(), _scope(), caution=0)
    digest = hashlib.sha256(open(csv_path, "rb").read()).hexdigest()
    assert digest in open(side, encoding="utf-8").read()


def test_the_sidecar_carries_the_same_bom_as_the_csv_beside_it(tmp_path):
    """The .provenance.txt sidecar was written
    BOM-less UTF-8 (encoding="utf-8") while the CSV beside it is
    deliberately utf-8-sig -- and the sidecar's own content is not ASCII
    (an em dash on its very first line: "... version %s -- export
    provenance"). Opened by a Windows tool that guesses encoding from
    bytes, a BOM-less file with non-ASCII bytes in it reads as mojibake.
    Judge this from the RAW BYTES, never from what a console prints.
    """
    csv_path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), csv_path, {})
    side = F.write_view_provenance(csv_path, _stamp(), _scope(), caution=0)
    raw = open(side, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf"), (
        "sidecar is not UTF-8 BOM (utf-8-sig), unlike the CSV it sits "
        "beside")


def test_the_sidecar_states_the_tool_version_the_status_bar_shows(tmp_path):
    from webcache import provenance
    csv_path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), csv_path, {})
    side = F.write_view_provenance(csv_path, _stamp(), _scope(), caution=0)
    assert provenance.TOOL_VERSION in open(side, encoding="utf-8").read()


def test_the_caution_block_appears_only_when_there_is_something_to_caution(
        tmp_path):
    csv_path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), csv_path, {})
    quiet = F.write_view_provenance(csv_path, _stamp(), _scope(), caution=0)
    assert "CAUTION" not in open(quiet, encoding="utf-8").read()
    loud = F.write_view_provenance(csv_path, _stamp(), _scope(), caution=4)
    text = open(loud, encoding="utf-8").read()
    assert "CAUTION" in text and "4" in text
    assert "not altered" in text


def test_the_sidecar_states_the_carved_split_and_whether_a_scan_ran(tmp_path):
    csv_path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), csv_path, {})
    side = F.write_view_provenance(
        csv_path, _stamp(), _scope(live_rows=1, carved_rows=1,
                                   recovery_scan_run=True), caution=0)
    text = open(side, encoding="utf-8").read()
    assert "ORIGIN" in text
    assert "1 live" in text and "1 carved" in text


def test_a_sidecar_that_cannot_be_written_never_loses_the_csv(tmp_path):
    csv_path = str(tmp_path / "out.csv")
    F.write_view_csv(_rows(), _cols(), csv_path, {})
    missing = str(tmp_path / "nowhere" / "deep" / "out.csv")
    assert F.write_view_provenance(missing, _stamp(), _scope(), 0) == ""
    assert os.path.exists(csv_path)


# --- header pairs (Unit 2's writer, declared here) ----------------------

def test_header_pairs_csv_carries_direction_and_ordinal(tmp_path):
    rows = [{"CleanUrl": "a", "ContainerId": 3, "EntryId": 9,
             "ModifiedTime": None, "_kind": record_kinds.K_HISTORY,
             "_pairs": [("response", 0, "(status line)", "HTTP/1.1 200", False),
                        ("response", 1, "Set-Cookie", "x=1", True),
                        ("request", 0, "Host", "h", False)]}]
    path = str(tmp_path / "pairs.csv")
    n = F.write_header_pairs_csv(rows, path, {})
    body = _read(path)
    assert n == 3
    assert body[0][:2] == ["Url", "Container"]
    assert "Direction" in body[0] and "Ordinal" in body[0]
    assert body[0][-2:] == ["Origin", "RecordSource"]
    assert body[1][body[0].index("Direction")] == "response"


def test_header_pairs_values_are_not_rewritten_as_dates(tmp_path):
    """The same defect, worse here: the mangled
    column is a real HTTP header's own NAME/VALUE content, not a fact this
    tool derived. Verified against the real exhibit: a stored response
    header value of "2026-02-17T16:50:09Z" was written as
    "2026-02-17 16:50:09". ModifiedTime -- "Stored (UTC)" -- IS a genuine
    timestamp and must still be normalised; Header/Value must not be.
    """
    rows = [{"CleanUrl": "a", "ContainerId": 3, "EntryId": 9,
             "ModifiedTime": datetime.datetime(2026, 2, 17, 16, 50, 9),
             "_kind": record_kinds.K_HISTORY,
             "_pairs": [("response", 0, "Date", "2026-02-17T16:50:09Z", False),
                        ("response", 1, "Expires",
                         "2026-02-17 16:50:09 UTC", False)]}]
    path = str(tmp_path / "pairs.csv")
    F.write_header_pairs_csv(rows, path, {})
    body = _read(path)
    header = body[0]
    value_col = header.index("Value")
    stored_col = header.index("Stored (UTC)")
    assert body[1][value_col] == "2026-02-17T16:50:09Z", (
        "a stored header VALUE must never be rewritten by the date helper")
    assert body[2][value_col] == "2026-02-17 16:50:09 UTC"
    assert body[1][stored_col] == forensic_engine.excel_datetime(
        "2026-02-17 16:50:09")


# --- a filter's true size, not just the shown 20 --------------

def test_the_sidecar_lists_every_filter_value(tmp_path):
    """scope_from_view truncated each value
    filter to sorted(...)[:20] BEFORE write_view_provenance ever saw it,
    so write_view_provenance's own `more = len(values) - len(shown)`
    computed on already-truncated data and was always 0. Verified with a
    57-value filter: the sidecar listed 20 values and stopped, with no
    ellipsis, no count, no "+37 more". An examiner reading only the
    sidecar has no way to know the filter had more than 20 values -- and
    the whole point of the sidecar is that the export is reproducible.
    """
    from webcache.widgets import record_filter

    columns = [Column("Domain", "Domain", 100, kind="domain")]
    rows = [{"Domain": "host%03d.test" % i, "CleanUrl": "a",
             "_kind": record_kinds.K_HISTORY} for i in range(60)]

    class _Model:
        def __init__(self):
            self.columns = columns
            self.filter = record_filter.RecordFilter(rows, columns)

        def rowCount(self):
            return self.filter.visible_count

        def chip_text(self):
            return ""

    model = _Model()
    allowed = {"host%03d.test" % i for i in range(57)}
    model.filter.set_values("Domain", allowed)

    scope = F.scope_from_view(object(), "history", "History", model)
    path = str(tmp_path / "out.csv")
    F.write_view_csv(model.filter.visible(), columns, path, scope)
    side = F.write_view_provenance(path, _stamp(), scope, caution=0)
    text = open(side, encoding="utf-8").read()
    line = next(l for l in text.splitlines() if "Value filter" in l)
    # Every value, not the first 20 and a count: the
    # line exists so the subset can be reproduced, and "+37 more" cannot.
    for value in sorted(allowed):
        assert value in line, value
    assert "more" not in line, line
