"""indicator_loader.indicator_rows(): one row per DISTINCT (kind, value)
indicator found inside URLs and paths -- see indicator_loader.py's own
module docstring.

Pure-function tests, no Qt needed -- mirrors test_domain_loader.py's own
stub-testable contract: entries are plain dicts, not a real WebCacheParser.
"""
from webcache.shell.indicator_loader import indicator_rows


def _entry(**overrides):
    base = {"Url": "https://example.com/a", "CleanUrl": "https://example.com/a"}
    base.update(overrides)
    return base


# --- basic shape -----------------------------------------------------------

def test_a_windows_sid_is_reported_with_high_confidence():
    rows = indicator_rows([_entry(Url="https://example.com/?u=S-1-5-21-1-2-3-500")])
    row = next(r for r in rows if r["Kind"] == "Windows SID")
    assert row["Value"] == "S-1-5-21-1-2-3-500"
    assert row["Conf"] == "High"
    assert row["Records"] == 1
    assert row["Why"]
    assert row["Decoded"]


def test_no_url_intel_in_an_ordinary_url_yields_no_rows():
    rows = indicator_rows([_entry(Url="https://example.com/plain/page")])
    assert rows == []


def test_records_counts_every_occurrence_of_the_same_value():
    rows = indicator_rows([
        _entry(Url="https://example.com/?u=S-1-5-21-1-2-3-500"),
        _entry(Url="https://other.example/?u=S-1-5-21-1-2-3-500"),
    ])
    row = next(r for r in rows if r["Kind"] == "Windows SID")
    assert row["Records"] == 2


def test_two_different_values_of_the_same_kind_are_two_rows():
    rows = indicator_rows([
        _entry(Url="https://example.com/?u=S-1-5-21-1-2-3-500"),
        _entry(Url="https://example.com/?u=S-1-5-21-1-2-3-501"),
    ])
    sids = [r for r in rows if r["Kind"] == "Windows SID"]
    assert {r["Value"] for r in sids} == {"S-1-5-21-1-2-3-500",
                                          "S-1-5-21-1-2-3-501"}


# --- confidence: never a fabricated default ---------------------------------

def test_confidence_is_a_readable_label_not_the_raw_engine_string():
    rows = indicator_rows([_entry(Url="https://example.com/?u=S-1-5-21-1-2-3-500")])
    row = next(r for r in rows if r["Kind"] == "Windows SID")
    assert row["Conf"] in ("High", "Medium", "Low")


def test_an_undeterminable_confidence_is_labelled_not_determinable():
    """The engine's own Finding objects always carry HIGH/MEDIUM/LOW --
    this defends the display layer against a future or malformed finding
    that does not, rather than silently defaulting it to something
    plausible: never invent a confidence."""
    from webcache.shell import indicator_loader
    assert indicator_loader._confidence_label("") == "Not determinable"
    assert indicator_loader._confidence_label(None) == "Not determinable"
    assert indicator_loader._confidence_label("bogus") == "Not determinable"


# --- carved entries: a URL that only exists in deleted data still counts ---

def test_carved_entries_are_scanned_too():
    rows = indicator_rows(
        [], [_entry(Url="https://gone.example/?u=S-1-5-21-1-2-3-500")])
    row = next(r for r in rows if r["Kind"] == "Windows SID")
    assert row["Records"] == 1


def test_a_carved_candidate_with_no_url_at_all_is_skipped_not_crashed():
    rows = indicator_rows([], [{"CleanUrl": ""}, {}])
    assert rows == []


def test_live_and_carved_occurrences_of_the_same_value_are_combined():
    rows = indicator_rows(
        [_entry(Url="https://a.example/?u=S-1-5-21-1-2-3-500")],
        [_entry(Url="https://b.example/?u=S-1-5-21-1-2-3-500")])
    row = next(r for r in rows if r["Kind"] == "Windows SID")
    assert row["Records"] == 2


# --- sort order --------------------------------------------------------

def test_rows_are_sorted_by_kind_then_by_records_descending():
    rows = indicator_rows([
        _entry(Url="https://a.example/?u=S-1-5-21-1-2-3-500"),
        _entry(Url="https://b.example/?u=S-1-5-21-1-2-3-501"),
        _entry(Url="https://c.example/?u=S-1-5-21-1-2-3-501"),
    ])
    sids = [r for r in rows if r["Kind"] == "Windows SID"]
    assert sids[0]["Records"] >= sids[1]["Records"]
