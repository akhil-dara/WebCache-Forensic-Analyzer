"""TimelineView: four grains as four record sets, and a period that opens.

GRANULARITY IS A RecordSet, NOT A PILL ROW. Three properties fall out of
that and are tested here rather than reimplemented: the switcher button
already states how many buckets each grain produces BEFORE it is pressed;
switching clears the filter box (a text filter typed as a day label
matches nothing at month grain, and "a filter that silently matches
nothing" is the failure this codebase has fixed four times); and the
column KEYS are identical across grains, so switching does not throw away
the examiner's scroll position.

A PERIOD DRILLS TO ITS RECORDS. the earlier version's timeline hid the period grid to
make room for the record list and had no way back that survived a
re-render. Here both live in one splitter and the pane is re-read from the
model on every refresh, so a filter that removes the selected period
clears the pane rather than leaving it describing a row that is gone.
"""
import datetime

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt

from webcache.shell import timeline_loader
from webcache.views.timeline import PANE_EMPTY, PANE_NOTE, TimelineView

_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


def _filetime(*args):
    dt = datetime.datetime(*args, tzinfo=datetime.timezone.utc)
    return int((dt - _EPOCH).total_seconds() * 10_000_000)


def _entry(day=15, **overrides):
    base = {
        "Url": "https://a.example/page",
        "CleanUrl": "https://a.example/page",
        "ContainerType": "History",
        "ContainerId": 3,
        "ContainerName": "History",
        "EntryId": 1,
        "ModifiedTime_raw": _filetime(2024, 6, day, 9, 0, 0),
    }
    base.update(overrides)
    return base


@pytest.fixture
def view(qtbot):
    v = TimelineView()
    qtbot.addWidget(v)
    v.resize(1280, 800)
    return v


def _loaded(view, entries=None, carved=()):
    entries = entries if entries is not None else [
        _entry(day=1, EntryId=1), _entry(day=1, EntryId=2),
        _entry(day=20, EntryId=3)]
    inputs = timeline_loader.timeline_inputs(entries, carved)
    view.set_inputs(inputs)
    for grain, _label, _plural in timeline_loader.GRAINS:
        rows = timeline_loader.period_rows(inputs, grain)
        view.set_records_for(
            grain, rows,
            note=timeline_loader.grain_note(inputs, rows, grain,
                                            scan_run=False))
    return inputs


# --- the four grains ------------------------------------------------------

def test_the_grains_are_declared_fine_to_coarse(view):
    assert [rs.key for rs in view._record_sets] == \
        ["minute", "hour", "day", "month"]


def test_the_view_opens_on_the_day_grain_not_the_first_declared(view):
    assert view._active_key == timeline_loader.DEFAULT_GRAIN == "day"
    assert view._switcher_buttons["day"].isChecked()


def test_each_switcher_button_states_its_own_bucket_count(view):
    _loaded(view)
    assert view._switcher_buttons["day"].text() == "By day (2)"
    assert view._switcher_buttons["month"].text() == "By month (1)"


# --- the period columns ---------------------------------------------------

def test_the_period_columns_match_the_spec(view):
    assert [c.key for c in view.COLUMNS] == [
        "Period", "PeriodStart", "Records", "Share", "Carved", "GapBefore",
        "Types", "Domains"]


def test_the_period_column_is_text_not_time(view):
    """A month bucket is "2024-06", which no date parser reads. A time
    kind here would offer before/after/between operators that match
    nothing forever -- and "%Y-..." strings already sort
    lexicographically == chronologically."""
    assert next(c for c in view.COLUMNS if c.key == "Period").kind == "text"


def test_the_real_instant_has_its_own_time_column(view):
    col = next(c for c in view.COLUMNS if c.key == "PeriodStart")
    assert col.kind == "time"


def test_relative_volume_is_the_one_bar_column_in_the_tree(view):
    assert next(c for c in view.COLUMNS if c.key == "Share").kind == "bar"


def test_from_deleted_is_a_count_column_not_a_flag(view):
    """A flag would say the whole period was carved; a period holds live
    and recovered records together."""
    assert next(c for c in view.COLUMNS if c.key == "Carved").kind == "carved"


@pytest.mark.parametrize("grain,expected", [
    ("minute", "Empty minutes before"), ("hour", "Empty hours before"),
    ("day", "Empty days before"), ("month", "Empty months before")])
def test_the_gap_column_is_labelled_in_the_grains_own_unit(view, grain,
                                                           expected):
    columns = view._segments_by_key[grain].columns
    assert next(c for c in columns if c.key == "GapBefore").label == expected


def test_no_period_column_is_a_link(view):
    """Selection drives the pane; a link column would fight the pane for
    the same gesture. Ctrl+Enter is the second route to the aggregate
    dialog and it is already there."""
    for grain, _label, _plural in timeline_loader.GRAINS:
        for col in view._segments_by_key[grain].columns:
            assert col.on_click is None, (grain, col.key)


def test_every_grain_gets_its_own_column_objects(view):
    """Distinct Column objects per grain, so the base's badge loop cannot
    annotate the same object four times -- and identical KEYS, so
    switching grain does not reset the examiner's scroll."""
    day = view._segments_by_key["day"].columns
    month = view._segments_by_key["month"].columns
    assert [c.key for c in day] == [c.key for c in month]
    assert all(a is not b for a, b in zip(day, month))


# --- switching ------------------------------------------------------------

def test_switching_grain_clears_the_filter_box(view, qtbot):
    _loaded(view)
    view.filter_box.setText("2024-06-01")
    view._switch_segment("month")
    assert view.filter_box.text() == ""


def test_switching_grain_leaves_the_scroll_position_alone(view, qtbot):
    entries = [_entry(day=(i % 28) + 1, EntryId=i,
                      ModifiedTime_raw=_filetime(2024, 6, (i % 28) + 1, i % 24))
               for i in range(300)]
    _loaded(view, entries)
    view.show()
    qtbot.waitExposed(view)
    bar = view.table.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert bar.value() > 0, "the fixture must actually scroll"

    view._switch_segment("hour")

    assert view.table.verticalScrollBar().value() > 0, (
        "the column KEYS are identical across grains, so a grain switch "
        "must not throw the scroll position away")


def test_the_bar_tooltip_names_the_grain_currently_on_screen(view):
    _loaded(view)
    assert "day" in view.table._bar_delegate.tooltip_for(0.5)
    view._switch_segment("hour")
    assert "hour" in view.table._bar_delegate.tooltip_for(0.5)


# --- the pane -------------------------------------------------------------

def test_the_pane_invites_a_selection_rather_than_opening_blank(view):
    _loaded(view)
    assert view.pane.prompt_text()
    assert view.pane.visible_rows() == []


def test_selecting_a_period_fills_the_pane_with_its_records(view):
    _loaded(view)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(model.rowCount() - 1, 0), QItemSelectionModel.SelectCurrent)

    rows = view.pane.visible_rows()
    assert len(rows) == 2
    assert "2024-06-01" in view.pane.heading_text()
    assert "2 records" in view.pane.heading_text()


def test_the_pane_paints_a_message_when_its_own_filter_empties_it(view):
    """A value-filter inside the pane that no row satisfies must
    not leave the pane a blank rectangle -- it must say the filter, not
    the period, emptied it. Reproduces the real-exhibit repro: select a
    period, then value-filter ContainerType in the pane to a value no
    pane row carries."""
    _loaded(view)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    assert view.pane.visible_rows()

    view.pane.table.model().set_values("ContainerType", {"NoSuchType"})

    assert view.pane.visible_rows() == []
    assert view.pane.table.empty_state_text() == PANE_EMPTY


def test_the_pane_note_does_not_promise_a_single_click_does_anything():
    """A single click on a row changes nothing -- only
    activate_cell (double-click, Enter, or the right-click menu's Open)
    opens a record. "Click any record for every stored field" reads as a
    single click being enough."""
    assert "Click any record" not in PANE_NOTE, PANE_NOTE
    assert "double-click" in PANE_NOTE.lower(), PANE_NOTE


def test_the_pane_says_live_and_recovered_are_shown_together(view):
    _loaded(view)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    # On the heading line, as Domains'.
    assert "live and recovered together" in view.pane.heading.text()


def test_filtering_the_selected_period_away_clears_the_pane(view):
    """HeadersView's lesson: a filter change refreshes the layout WITHOUT
    emitting currentRowChanged, and the current index is a row NUMBER --
    it does not move when the rows underneath it do."""
    _loaded(view)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(model.rowCount() - 1, 0), QItemSelectionModel.SelectCurrent)
    assert view.pane.visible_rows()

    view.filter_box.setText("2024-06-20")
    view._apply_text()

    assert view.pane.visible_rows() == []
    assert view.pane.prompt_text()


def test_selecting_a_period_survives_a_filter_keystroke_that_removes_nothing(view):
    """Every model refresh -- including a filter keystroke that
    removes NO rows -- goes through beginResetModel/endResetModel, which
    resets the table's own selection. The pane re-synced from
    table.currentIndex() (a row NUMBER), so it lost the selection even
    though the selected period was still on screen, untouched, at the
    same row."""
    _loaded(view)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    assert view.pane.visible_rows()

    view.filter_box.setText("2024-06")
    view._apply_text()

    assert model.rowCount() == 2, "the fixture must filter out nothing"
    assert view.pane.visible_rows(), (
        "a filter that removed no rows must not lose the pane's selection")


def test_a_bars_share_recomputes_against_the_peak_still_in_view(view):
    """Share was computed ONCE in period_rows, against the peak
    of the WHOLE unfiltered bucket set -- and the bar's own tooltip
    reads "N% of the busiest day in this view". Filtering the busiest
    day out of the view left every remaining bar still measured against
    a row that is no longer on screen: no bar reached full width, and
    "in this view" was false."""
    entries = [_entry(day=1, EntryId=i) for i in range(3)] + \
        [_entry(day=10, EntryId=10)]
    _loaded(view, entries)
    model = view.table.model()
    before = {r["Period"]: r["Share"] for r in model.filter.visible()}
    assert before["2024-06-01"] == 1.0
    assert before["2024-06-10"] < 1.0

    view.filter_box.setText("2024-06-10")
    view._apply_text()

    visible = model.filter.visible()
    assert [r["Period"] for r in visible] == ["2024-06-10"]
    assert visible[0]["Share"] == 1.0, (
        "the remaining bar's share must be measured against the peak "
        "that is still in view, not one that has been filtered out")


def test_switching_grain_clears_the_pane(view):
    """A pane still showing the previous grain's period would be
    describing rows that no longer exist."""
    _loaded(view)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    assert view.pane.visible_rows()

    view._switch_segment("month")

    assert view.pane.visible_rows() == []


def test_the_pane_columns_carry_the_same_basis_badges_the_grid_does(view):
    by_key = {c.key: c for c in view.PERIOD_RECORD_COLUMNS}
    assert by_key["CleanUrl"].badge, "a column naming a field must cite it"
    assert by_key["KeyTimeBasis"].badge is None, (
        "a column that names no field cites nothing")
    for key in ("KeyTimeUtc", "LocalTime", "ContainerName", "IsInPrivate"):
        assert by_key[key].badge, key


def test_the_container_column_in_the_pane_drills_to_the_table_browser(view):
    seen = []
    view.drillRequested.connect(lambda key, row: seen.append((key, row)))
    col = next(c for c in view.PERIOD_RECORD_COLUMNS
               if c.key == "ContainerName")
    col.on_click({"ContainerId": 3})
    assert seen and seen[0][0] == "browser"


def test_the_container_column_is_not_a_link_when_the_row_has_no_container(view):
    """A carved row can have ContainerName "" and ContainerId
    None -- a bare string carve (record_kinds.K_CARVED_STRING)
    reconstructs no columns at all. Declaring on_click for every row
    made a blank Container cell still show the pointing-hand cursor and
    the "double-click to follow" tooltip, and activating it went
    nowhere."""
    col = next(c for c in view.PERIOD_RECORD_COLUMNS
               if c.key == "ContainerName")
    assert col.is_link_for({"ContainerId": 3}) is True
    assert col.is_link_for({"ContainerId": None}) is False
    assert col.is_link_for({}) is False


def test_the_pane_export_button_promises_the_visible_count(view):
    _loaded(view)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(model.rowCount() - 1, 0), QItemSelectionModel.SelectCurrent)
    assert "(2)" in view.pane.export_button.text()


def test_the_pane_export_is_its_own_signal(view, qtbot):
    _loaded(view)
    model = view.table.model()
    view.table.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.SelectCurrent)
    with qtbot.waitSignal(view.periodRecordsExportRequested, timeout=500):
        view.pane.export_button.click()


def test_the_table_area_is_idempotent(view):
    """Called once from the base constructor -- but a second call must
    return the SAME splitter, never reparent the table out of the layout
    it is already in."""
    assert view._table_area() is view._table_area()
    assert view._table_area().orientation() == Qt.Vertical


# --- what the view says ---------------------------------------------------

def test_the_subtitle_repeats_the_silence_caveat_at_every_grain(view):
    for grain, _label, _plural in timeline_loader.GRAINS:
        text = view._segments_by_key[grain].subtitle(97)
        assert "no cached activity" in text, grain
        assert "does not mean no activity" in text, grain


def test_the_subtitle_says_only_populated_periods_are_listed(view):
    text = view._segments_by_key["day"].subtitle(97)
    assert "Periods without records are not listed" in text


def test_the_empty_state_names_the_three_columns_a_period_is_read_from(view):
    text = view._segments_by_key["day"].empty_text
    for column in ("ModifiedTime", "AccessedTime", "CreationTime"):
        assert column in text


def test_no_string_this_view_shows_overstates_what_it_has(view):
    texts = [view._segments_by_key[g].empty_text
             for g, _l, _p in timeline_loader.GRAINS]
    texts += [view._segments_by_key[g].subtitle(3)
              for g, _l, _p in timeline_loader.GRAINS]
    texts += [view.pane.prompt_text(), timeline_loader.SILENCE_CAVEAT]
    for text in texts:
        lowered = text.lower()
        for word in ("confirm", "proves", "demonstrates"):
            assert word not in lowered, (word, text)


def test_a_table_of_periods_does_not_call_its_rows_records(view):
    """The count line sits centimetres from a note reading "610 of 610
    records carry a usable timestamp". Calling the two period rows
    "records" as well puts two different quantities under one word, in one
    line."""
    _loaded(view)
    assert view.count_label.text().startswith("2 periods")
