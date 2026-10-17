"""A ", "-joined cell filters by its individual values.
chips speak the column's label and the grid's own words."""
from webcache.views.domains import DomainsView
from webcache.widgets.column_spec import Column, split_multi
from webcache.widgets.filter_popup import FilterPopup
from webcache.widgets.record_filter import Condition, RecordFilter
from webcache.widgets.record_model import RecordTableModel
from tests.fixtures import FIXTURE_COLUMNS, make_rows

COLS = [Column("Domain", "Domain", 200, kind="domain"),
        Column("ContainerType", "Container types", 170, kind="types",
               multi=True)]
ROWS = [{"Domain": "a.test", "ContainerType": "History, Content"},
        {"Domain": "b.test", "ContainerType": "Content"},
        {"Domain": "c.test", "ContainerType": "Cookies"},
        {"Domain": "d.test", "ContainerType": ""}]


def _domains(rf):
    return sorted(r["Domain"] for r in rf.visible())


def test_a_column_is_single_valued_unless_it_says_otherwise():
    assert Column("x").multi is False


def test_split_multi_keeps_a_blank_as_one_blank_value():
    assert split_multi("History, Content") == ["History", "Content"]
    assert split_multi("") == [""]
    assert split_multi(None) == [None]


def test_the_value_list_offers_individual_values_with_row_counts():
    rf = RecordFilter(ROWS, COLS)
    assert dict(rf.value_counts("ContainerType")) == {
        "History": 1, "Content": 2, "Cookies": 1, "": 1}


def test_ticking_values_matches_a_row_containing_any_of_them():
    rf = RecordFilter(ROWS, COLS)
    rf.set_values("ContainerType", {"History", "Cookies"})
    assert _domains(rf) == ["a.test", "c.test"]
    rf.set_values("ContainerType", {"Content"})
    assert _domains(rf) == ["a.test", "b.test"]


def test_text_operators_still_match_the_whole_cell():
    rf = RecordFilter(ROWS, COLS)
    rf.set_condition("ContainerType", Condition("equals", "Content"))
    assert _domains(rf) == ["b.test"]


def test_emptied_by_understands_a_multi_value_filter():
    rf = RecordFilter(ROWS, COLS)
    rf.set_values("ContainerType", {"History"})
    rf.set_condition("Domain", Condition("equals", "b.test"))
    assert rf.visible() == []
    assert rf.emptied_by() is not None


def test_the_popup_lists_individual_values(qtbot):
    model = RecordTableModel(COLS, ROWS)
    popup = FilterPopup(model, COLS[1])
    qtbot.addWidget(popup)
    labels = [popup.values_list.item(i).text()
              for i in range(popup.values_list.count())]
    assert "Content  (2)" in labels
    assert not any("History, Content" in label for label in labels)


def test_domains_marks_its_container_types_column_multi(qtbot):
    view = DomainsView()
    qtbot.addWidget(view)
    col = next(c for rs in view._record_sets for c in rs.columns
               if c.key == "ContainerType")
    assert col.multi is True


# --- ------------------------------------------------------------------

INPRIVATE = Column("IsInPrivate", "InPrivate", 80, kind="flag")


def test_a_flag_condition_reads_is_yes_or_is_no():
    assert Condition("equals", "True").describe(INPRIVATE) == "Is Yes"
    assert Condition("equals", "False").describe(INPRIVATE) == "Is No"
    assert Condition("equals", "no").describe(INPRIVATE) == "Is No"
    assert Condition("does not equal", "Yes").describe(INPRIVATE) == "Is not Yes"


def test_describe_without_a_column_is_unchanged():
    assert Condition("contains", "login").describe() == 'contains "login"'


def test_a_values_chip_uses_the_label_and_the_display_text():
    rf = RecordFilter(make_rows(50), FIXTURE_COLUMNS)
    rf.set_values("IsInPrivate", {True})
    assert rf.chip_text() == "InPrivate: Is Yes"
    assert "IsInPrivate" not in rf.chip_text()
    assert "True" not in rf.chip_text()


def test_a_condition_chip_uses_the_label():
    rf = RecordFilter(make_rows(50), FIXTURE_COLUMNS)
    rf.set_condition("CleanUrl", Condition("contains", "msn"))
    assert rf.chip_text() == 'Address: contains "msn"'


def test_many_values_are_counted_not_listed():
    rf = RecordFilter(make_rows(200), FIXTURE_COLUMNS)
    domains = {r["Domain"] for r in make_rows(200)}
    keep = set(sorted(domains)[:4])
    rf.set_values("Domain", keep)
    assert rf.chip_text() == "Domain: 4 of %d values" % len(domains)


def test_a_key_with_no_column_uses_the_label_it_was_given():
    rf = RecordFilter(make_rows(50), FIXTURE_COLUMNS)
    rf.extra_labels["SearchTerms"] = "Has search terms"
    rf.set_condition("SearchTerms", Condition("is not blank"))
    assert rf.chip_text() == "Has search terms: is not blank"


# --- is a general rule, not scoped to Domains -----------
# Providers (location.py), Fields (indicators.py) and MatchedColumns
# (search.py) are also ", "-joined lists and were missed the first time.

def test_location_marks_its_providers_column_multi(qtbot):
    from webcache.views.location import _place_columns
    col = next(c for c in _place_columns() if c.key == "Providers")
    assert col.multi is True


def test_indicators_marks_its_fields_column_multi(qtbot):
    from webcache.views.indicators import IndicatorsView
    view = IndicatorsView()
    qtbot.addWidget(view)
    col = next(c for rs in view._record_sets for c in rs.columns
               if c.key == "Fields")
    assert col.multi is True


def test_search_marks_its_matched_columns_column_multi(qtbot):
    from webcache.views.search import SearchView
    view = SearchView()
    qtbot.addWidget(view)
    col = next(c for rs in view._record_sets for c in rs.columns
               if c.key == "MatchedColumns")
    assert col.multi is True


# --- an element that itself contains ", " must not be mis-split ---------
# Providers is device-reported text, outside this tool's control -- a
# provider string containing a literal ", " must survive as ONE value,
# never be torn into two. The column must supply the raw pre-split list
# (Column.multi_source) rather than let split_multi() re-guess it from
# the already-joined display text.

RAW_COLS = [
    Column("Place", "Place", 120, kind="text"),
    Column("Providers", "Reported source", 155, kind="text", multi=True,
           multi_source="ProvidersValues"),
]
RAW_ROWS = [
    {"Place": "p1", "Providers": "gps, wifi, cell",
     "ProvidersValues": ["gps", "wifi", "cell"]},
    {"Place": "p2", "Providers": "wifi, cell",
     # ONE device-reported string that itself contains ", " -- a naive
     # split_multi() on the display text would read this as two values
     # ("wifi" and "cell") indistinguishable from p1's real two values.
     "ProvidersValues": ["wifi, cell"]},
]


def test_a_value_containing_the_separator_is_not_torn_apart():
    rf = RecordFilter(RAW_ROWS, RAW_COLS)
    counts = dict(rf.value_counts("Providers"))
    # p1 contributes "gps", "wifi", "cell" (3 real, split values).
    # p2 contributes ONE value, "wifi, cell" (its raw string, untouched).
    assert counts == {"gps": 1, "wifi": 1, "cell": 1, "wifi, cell": 1}


def test_ticking_the_combined_value_matches_only_its_own_row():
    rf = RecordFilter(RAW_ROWS, RAW_COLS)
    rf.set_values("Providers", {"wifi, cell"})
    assert [r["Place"] for r in rf.visible()] == ["p2"]
    # Ticking the real, individually-reported "wifi" must never also
    # match p2 -- p2 never reported "wifi" alone.
    rf.set_values("Providers", {"wifi"})
    assert [r["Place"] for r in rf.visible()] == ["p1"]


def test_the_popup_shows_the_raw_value_never_a_guessed_split(qtbot):
    model = RecordTableModel(RAW_COLS, RAW_ROWS)
    popup = FilterPopup(model, RAW_COLS[1])
    qtbot.addWidget(popup)
    labels = [popup.values_list.item(i).text()
              for i in range(popup.values_list.count())]
    assert "wifi, cell  (1)" in labels
    assert "wifi  (1)" in labels
    assert "cell  (1)" in labels
