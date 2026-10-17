"""RecordsView: the generic record-table machinery HistoryView used to
carry entirely on its own -- the debounced/live filter split, the count
line, the "filter: ..." description, the constant-column chip, the empty-
filtered-table message, set_caveat, refresh_theme, the export button,
Ctrl+F/Escape, declarative quick-filter chips, and -- new in this base --
an optional segmented switcher for a view with more than one record set
(File Access: file-access records + downloads; Cookies & HSTS: three).

Exercised here against small, throwaway concrete subclasses rather than
HistoryView -- test_history_view.py already pins HistoryView's own
behaviour byte-for-byte and must keep passing UNCHANGED; this file proves
the BASE class's own generic contract, independent of any one subclass,
which is what makes it reusable by File Access, and whatever comes next.
"""
import datetime

import pytest
from PySide6.QtTest import QTest

from webcache.widgets.column_spec import Column
from webcache.widgets.record_filter import Condition
from webcache.views.records_view import QuickFilter, RecordSet, RecordsView


def _rows(n, key="Name", carved_every=5):
    out = []
    for i in range(n):
        out.append({
            "Name": "item-%d" % i,
            "Flag": bool(i % 3 == 0),
            "Origin": "Carved (deleted/unflushed)" if i % carved_every == 0
                     else "Live record",
        })
    return out


_SINGLE_COLUMNS = [
    Column("Name", "Name", 200, kind="text", field="Name"),
    Column("Flag", "Flag", 80, kind="flag"),
    Column("Origin", "Origin", 150, kind="text", field="Origin"),
]

_OTHER_COLUMNS = [
    Column("Size", "Size", 100, kind="size", field="Size"),
]


class _OneSegmentView(RecordsView):
    """The ordinary shape -- one RecordSet, HistoryView's own shape."""

    def __init__(self, quick_filters=(), parent=None):
        super().__init__(
            record_sets=[RecordSet("only", "Only Segment", _SINGLE_COLUMNS,
                                   subtitle=lambda n: "%s thing(s) seen." % n)],
            header_icon="grid", header_title="Only Segment",
            quick_filters=quick_filters, parent=parent)


class _TwoSegmentView(RecordsView):
    """File Access's shape -- two named record sets sharing one table."""

    def __init__(self, quick_filters=(), parent=None):
        super().__init__(
            record_sets=[
                RecordSet("primary", "Primary", _SINGLE_COLUMNS,
                          subtitle=lambda n: "%s primary." % n),
                RecordSet("secondary", "Secondary", _OTHER_COLUMNS,
                          subtitle=lambda n: "%s secondary." % n),
            ],
            header_icon="grid", header_title="Two Segments",
            quick_filters=quick_filters, parent=parent)


# --- the legacy single-segment public surface -------------------------------

def test_single_segment_view_exposes_the_legacy_public_attributes(qtbot):
    v = _OneSegmentView()
    v.set_records(_rows(10))
    qtbot.addWidget(v)
    for attr in ("filter_box", "count_label", "table", "export_button",
                "caveat", "header", "COLUMNS"):
        assert hasattr(v, attr), "RecordsView must expose %r" % attr
    assert v.table.model().rowCount() == 10
    assert "10" in v.count_label.text()


def test_set_records_signature_matches_the_old_history_call(qtbot):
    """MainWindow and every HistoryView test call set_records(rows,
    note=None) directly -- this must keep working unchanged for a
    single-segment view."""
    v = _OneSegmentView()
    qtbot.addWidget(v)
    v.set_records(_rows(3), note="a caveat")
    assert "a caveat" in v.line_text()


def test_a_single_segment_view_has_no_switcher(qtbot):
    v = _OneSegmentView()
    qtbot.addWidget(v)
    assert v._switcher_buttons == {}


def test_export_button_emits_exportrequested(qtbot):
    v = _OneSegmentView()
    v.set_records(_rows(4))
    qtbot.addWidget(v)
    with qtbot.waitSignal(v.exportRequested, timeout=1000):
        v.export_button.click()


def test_export_button_shows_the_shown_count(qtbot):
    v = _OneSegmentView()
    v.set_records(_rows(4))
    qtbot.addWidget(v)
    assert "4" in v.export_button.text()


# --- declarative quick filters ----------------------------------------------

def test_declaring_no_quick_filters_produces_no_chip_row(qtbot):
    v = _OneSegmentView(quick_filters=())
    qtbot.addWidget(v)
    assert v._quick_filters == []


def test_a_declared_quick_filter_gets_its_named_attribute(qtbot):
    from webcache.widgets.quick_filter_chip import QuickFilterChip

    qf = [QuickFilter("chip_flag", "Flag only", "primary", "Flag", values={True})]
    v = _OneSegmentView(quick_filters=qf)
    qtbot.addWidget(v)
    assert isinstance(v.chip_flag, QuickFilterChip)


def test_a_values_based_quick_filter_narrows_the_table(qtbot):
    qf = [QuickFilter("chip_flag", "Flag only", "primary", "Flag", values={True})]
    v = _OneSegmentView(quick_filters=qf)
    v.set_records(_rows(30))
    qtbot.addWidget(v)
    total = v.table.model().rowCount()
    v.chip_flag.setChecked(True)
    shown = v.table.model().rowCount()
    assert 0 < shown < total
    assert all(v.table.model().row_at(i)["Flag"] for i in range(shown))


def test_a_condition_based_quick_filter_narrows_the_table(qtbot):
    qf = [QuickFilter("chip_carved", "Carved only", "error", "Origin",
                      condition=Condition("begins with", "Carved"))]
    v = _OneSegmentView(quick_filters=qf)
    v.set_records(_rows(30))
    qtbot.addWidget(v)
    total = v.table.model().rowCount()
    v.chip_carved.setChecked(True)
    shown = v.table.model().rowCount()
    assert 0 < shown < total
    assert all(v.table.model().row_at(i)["Origin"].startswith("Carved")
              for i in range(shown))


def test_a_checked_chip_survives_a_fresh_set_records_call(qtbot):
    """set_records always builds a brand new model -- a checked chip must
    keep filtering the new rows, the same discipline HistoryView already
    pinned (test_history_view.py), now proved at the base level."""
    qf = [QuickFilter("chip_flag", "Flag only", "primary", "Flag", values={True})]
    v = _OneSegmentView(quick_filters=qf)
    v.set_records(_rows(30))
    qtbot.addWidget(v)
    v.chip_flag.setChecked(True)
    v.set_records(_rows(40, key="Name"))
    assert v.chip_flag.isChecked() is True
    shown = v.table.model().rowCount()
    assert 0 < shown < 40
    assert all(v.table.model().row_at(i)["Flag"] for i in range(shown))


def test_typed_filter_text_survives_a_fresh_set_records_call(qtbot):
    """A second set_records() on the SAME segment -- exactly what a second
    Open Evidence or a recovery merge does -- always builds a brand new
    model (RecordsTable.set_records' own docstring). A checked quick-
    filter chip already survives this refresh (the test just above);
    typed free-text filtering must give the same guarantee, or the box
    keeps showing a search term the model has silently stopped applying
    -- the count line then disagrees with what is actually on screen.
    This project has already fixed four separate "filter that silently
    matches nothing" bugs; this is the same family."""
    v = _OneSegmentView()
    v.set_records(_rows(30))
    qtbot.addWidget(v)
    v.filter_box.setText("item-1")
    v.table.model().set_text("item-1")
    shown_before = v.table.model().rowCount()
    assert 0 < shown_before < 30

    v.set_records(_rows(40, key="Name"))  # a fresh model, same segment

    assert v.filter_box.text() == "item-1"  # the box is not silently cleared
    model = v.table.model()
    shown_after = model.rowCount()
    assert 0 < shown_after < 40
    for i in range(shown_after):
        assert "item-1" in model.row_at(i)["Name"]
    # box, count line, and model must all agree
    assert v.count_label.text() == "{:,} of {:,} records".format(shown_after, 40)


def test_clear_all_filters_unchecks_every_chip(qtbot):
    qf = [QuickFilter("chip_flag", "Flag only", "primary", "Flag", values={True})]
    v = _OneSegmentView(quick_filters=qf)
    v.set_records(_rows(30))
    qtbot.addWidget(v)
    v.chip_flag.setChecked(True)
    assert v.table.model().rowCount() < 30
    v.clear_all_filters()
    assert v.chip_flag.isChecked() is False
    assert v.table.model().rowCount() == 30


# --- basis badges: applied by the base, over every segment's columns -------

def test_basis_badges_are_applied_to_every_segment_not_just_the_first(qtbot):
    v = _TwoSegmentView()
    qtbot.addWidget(v)
    primary_size_col = next(c for rs in v._record_sets for c in rs.columns
                            if rs.key == "primary" and c.key == "Origin")
    secondary_col = next(c for rs in v._record_sets for c in rs.columns
                         if rs.key == "secondary" and c.key == "Size")
    assert primary_size_col.badge is not None
    assert secondary_col.badge is not None


def test_a_column_declaring_no_field_gets_no_badge(qtbot):
    v = _OneSegmentView()
    qtbot.addWidget(v)
    flag_col = next(c for c in v.COLUMNS if c.key == "Flag")
    assert flag_col.field is None
    assert flag_col.badge is None


# --- the subtitle hook -------------------------------------------------------

def test_subtitle_hook_receives_the_real_row_count(qtbot):
    v = _OneSegmentView()
    v.set_records(_rows(17))
    qtbot.addWidget(v)
    assert "17 thing(s) seen." in v.header._subtitle.text()


# --- keyboard: Ctrl+F focuses, Escape clears --------------------------------

def test_ctrl_f_focuses_the_filter_box(qtbot):
    from PySide6.QtCore import Qt

    v = _OneSegmentView()
    v.set_records(_rows(5))
    qtbot.addWidget(v)
    v.resize(900, 600)
    v.show()
    qtbot.waitExposed(v)
    v.activateWindow()
    qtbot.wait(50)
    v.table.setFocus()
    QTest.keyClick(v, Qt.Key_F, Qt.ControlModifier)
    assert v.filter_box.hasFocus()


# --- the segmented switcher --------------------------------------------------

def test_a_two_segment_view_renders_one_button_per_segment(qtbot):
    v = _TwoSegmentView()
    qtbot.addWidget(v)
    assert set(v._switcher_buttons.keys()) == {"primary", "secondary"}


def test_a_switcher_button_names_its_segment_and_its_row_count(qtbot):
    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(5))
    qtbot.addWidget(v)
    assert "Primary" in v._switcher_buttons["primary"].text()
    assert "5" in v._switcher_buttons["primary"].text()


def test_set_records_for_a_non_active_segment_updates_its_count_without_switching(qtbot):
    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(5))
    qtbot.addWidget(v)
    v.set_records_for("secondary", [{"Size": 1}, {"Size": 2}, {"Size": 3}])
    # Still showing "primary" -- the columns on screen are still Name/Flag/Origin.
    assert [c.key for c in v.table.model().columns] == ["Name", "Flag", "Origin"]
    assert "Secondary" in v._switcher_buttons["secondary"].text()
    assert "3" in v._switcher_buttons["secondary"].text()


def test_switching_segments_swaps_columns_and_rows(qtbot):
    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(5))
    v.set_records_for("secondary", [{"Size": 1}, {"Size": 2}, {"Size": 3}])
    qtbot.addWidget(v)

    v._switch_segment("secondary")

    assert [c.key for c in v.table.model().columns] == ["Size"]
    assert v.table.model().rowCount() == 3
    assert [c.key for c in v.COLUMNS] == ["Size"]


def test_switching_segments_resets_a_typed_text_filter(qtbot):
    """A filter typed against one segment's columns must never silently
    carry over onto a different segment's columns -- that is exactly this
    project's "filter that silently matches nothing" failure class."""
    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(5))
    v.set_records_for("secondary", [{"Size": 1}, {"Size": 2}, {"Size": 3}])
    qtbot.addWidget(v)

    v.filter_box.setText("item-1")
    v.table.model().set_text("item-1")
    assert v.table.model().rowCount() < 5

    v._switch_segment("secondary")

    assert v.filter_box.text() == ""
    assert v.table.model().rowCount() == 3


def test_switching_segments_resets_a_header_funnel_filter(qtbot):
    """A header funnel condition lives on the OLD model's RecordFilter;
    set_records() (called via _switch_segment) always builds a brand new
    model, so switching segments must never leave a stale filter that
    reads as still in force but targets a column the new segment lacks."""
    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(5))
    v.set_records_for("secondary", [{"Size": 1}, {"Size": 2}, {"Size": 3}])
    qtbot.addWidget(v)

    v.table.model().set_values("Flag", {True})
    assert v.table.model().filter.has_filters()

    v._switch_segment("secondary")

    assert v.table.model().filter.has_filters() is False


def test_switching_segments_updates_the_switcher_selection(qtbot):
    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(5))
    v.set_records_for("secondary", [{"Size": 1}])
    qtbot.addWidget(v)

    v._switch_segment("secondary")

    assert v._switcher_buttons["secondary"].isChecked() is True
    assert v._switcher_buttons["primary"].isChecked() is False


def test_actually_clicking_the_switcher_button_switches_the_segment(qtbot):
    """Not v._switch_segment(key) called directly (every test above does
    that) -- a REAL QTest.mouseClick on the widget, going through the
    exact signal Qt itself delivers on a real click. This is what caught
    a real bug during on-screen verification: QPushButton.clicked is
    clicked(bool checked=false), a DEFAULT-valued C++ parameter, and a
    functools.partial-wrapped slot connected to it is silently called
    with NO arguments at all -- PySide6 cannot introspect a partial the
    way it can a lambda, so it takes the zero-arg overload. Every other
    test in this file called the internal method directly and could not
    have caught that; only a real click through the real widget can."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(5))
    v.set_records_for("secondary", [{"Size": 1}, {"Size": 2}])
    qtbot.addWidget(v)

    QTest.mouseClick(v._switcher_buttons["secondary"], Qt.LeftButton)

    assert [c.key for c in v.table.model().columns] == ["Size"]
    assert v.table.model().rowCount() == 2
    assert v._switcher_buttons["secondary"].isChecked() is True


# --- the genuine empty state: RecordSet.empty_text reaches the table -------

def test_record_set_generates_a_fallback_empty_text_when_none_is_given():
    """A future RecordSet that forgets to write its own sentence still
    names the record set by its own label, rather than leaving an
    examiner with no explanation at all."""
    rs = RecordSet("widgets", "Widgets", _SINGLE_COLUMNS)
    assert "Widgets" in rs.empty_text


def test_a_record_sets_own_empty_text_is_kept_verbatim():
    rs = RecordSet("widgets", "Widgets", _SINGLE_COLUMNS,
                   empty_text="No Widgets in this exhibit — a bespoke reason.")
    assert rs.empty_text == "No Widgets in this exhibit — a bespoke reason."


def test_a_genuinely_empty_single_segment_view_shows_the_declared_reason(qtbot):
    class _View(RecordsView):
        def __init__(self, parent=None):
            super().__init__(
                record_sets=[RecordSet("only", "Only Segment", _SINGLE_COLUMNS,
                                       empty_text="No Only Segment records here.")],
                header_icon="grid", header_title="Only Segment", parent=parent)

    v = _View()
    v.set_records([])
    qtbot.addWidget(v)

    assert v.table.showing_genuine_empty_state() is True
    assert v.table.empty_state_text() == "No Only Segment records here."


def test_a_populated_single_segment_view_never_shows_the_empty_state(qtbot):
    v = _OneSegmentView()
    v.set_records(_rows(3))
    qtbot.addWidget(v)
    assert v.table.showing_genuine_empty_state() is False


def test_filtering_a_populated_view_to_zero_never_trips_the_genuine_empty_state(qtbot):
    """The two empty states must never be confusable: RecordsView wires
    RecordSet.empty_text into the table on every render, but the table
    itself is what refuses to show it once a filter -- not a lack of
    rows -- is why nothing is visible. This proves that refusal holds
    even when the ACTIVE view definitely has an empty_text declared."""
    v = _OneSegmentView()
    v.set_records(_rows(5))
    qtbot.addWidget(v)

    v.table.model().set_values("Flag", set())
    assert v.table.model().rowCount() == 0

    assert v.table.showing_genuine_empty_state() is False
    assert v.table.empty_state_text() == v.table.empty_message()  # the filters sentence, never the reason
    assert "Clear filters" in v.table.empty_state_text()


def test_switching_to_an_empty_segment_shows_that_segments_own_reason(qtbot):
    """File Access's own shape: "file access" has rows, "downloads" does
    not. Switching segments must show DOWNLOADS' reason, not primary's,
    stale, and not primary's reason bleeding across the switch."""
    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(3))
    v.set_records_for("secondary", [])
    qtbot.addWidget(v)

    assert v.table.showing_genuine_empty_state() is False  # primary is active, has rows

    v._switch_segment("secondary")

    assert v.table.showing_genuine_empty_state() is True
    assert "Secondary" in v.table.empty_state_text()


def test_switching_away_from_an_empty_segment_clears_its_overlay(qtbot):
    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(3))
    v.set_records_for("secondary", [])
    qtbot.addWidget(v)

    v._switch_segment("secondary")
    assert v.table.showing_genuine_empty_state() is True

    v._switch_segment("primary")
    assert v.table.showing_genuine_empty_state() is False


# --- [10] switching segments must reset scroll, since the column set -----
# just changed. Reproduced on the real exhibit: scroll Cookies to its
# right edge, switch to HSTS Pins (a narrower segment), and the grid
# painted COMPLETELY EMPTY -- no headers, no rows -- while the count line
# still read the true row count. Confirmed by grep: nothing under
# webcache/views/ or records_table.py ever calls horizontalScrollBar,
# verticalScrollBar or scrollToTop -- no reset exists anywhere.
#
# The real invariant is that a scroll offset must be re-validated
# whenever the COLUMN SET changes. _switch_segment is the only path in
# this class that ever changes it: set_records_for on the segment
# already active always re-renders the SAME RecordSet.columns, so a
# data refresh (a second load, a recovery merge) must NOT reset scroll
# -- the last test below proves that side of the invariant too.
#
# This is unrelated to go_to() navigation between DIFFERENT views on
# MainWindow's own QStackedWidget, which an earlier audit specifically
# praised this port for PRESERVING (the earlier version destroyed it) --
# that stack never rebuilds a model, so nothing here touches it.

#: A dedicated pair of segments for the horizontal-scroll test below,
#: rather than _TwoSegmentView's own primary/secondary -- with only ONE
#: column, secondary's per-item horizontal range collapses to exactly 0
#: the instant the viewport is narrow enough to prove anything about
#: primary, which would make this test pass on EITHER fixed or unfixed
#: code (nothing to clamp a stale value DOWN TO but 0 either way) and
#: prove nothing. Two columns on each side keeps a genuine, nonzero
#: post-switch range so a stale value surviving the switch is
#: distinguishable from one that was properly reset.
_WIDE_COLUMNS = [Column("A", "A", 300, kind="text", field="A"),
                Column("B", "B", 300, kind="text", field="B"),
                Column("C", "C", 300, kind="text", field="C")]
#: 600 each, not 150: the toolbar gained the Hide identical columns button
#: which raises the view's minimum width, so two 150 px columns no
#: longer overflow the smallest viewport the view can take.
_NARROW_COLUMNS = [Column("X", "X", 600, kind="text", field="X"),
                   Column("Y", "Y", 600, kind="text", field="Y")]


class _WideNarrowView(RecordsView):
    def __init__(self, parent=None):
        super().__init__(
            record_sets=[
                RecordSet("wide", "Wide", _WIDE_COLUMNS,
                          subtitle=lambda n: "%s wide." % n),
                RecordSet("narrow", "Narrow", _NARROW_COLUMNS,
                          subtitle=lambda n: "%s narrow." % n),
            ],
            header_icon="grid", header_title="Wide/Narrow", parent=parent)


def test_switching_segments_resets_the_horizontal_scroll_position(qtbot):
    v = _WideNarrowView()
    v.set_records_for("wide", [{"A": "a", "B": "b", "C": "c"}])
    v.set_records_for("narrow", [{"X": "x", "Y": "y"}])
    qtbot.addWidget(v)
    v.resize(220, 400)
    v.show()
    qtbot.waitExposed(v)
    bar = v.table.horizontalScrollBar()
    bar.setValue(bar.maximum())
    assert bar.maximum() > 0, (
        "the fixture must actually scroll for this to mean anything")
    assert bar.value() > 0

    v._switch_segment("narrow")
    # The scroll range is recomputed on the next event-loop pass; at this
    # toolbar width (Hide identical columns, F33) it is not yet current
    # when the switch returns.
    qtbot.wait(50)

    assert v.table.horizontalScrollBar().maximum() > 0, (
        "the fixture must still have room to scroll after switching too, "
        "or a value of 0 would prove nothing")
    assert v.table.horizontalScrollBar().value() == 0, (
        "switching to a narrower segment left the horizontal scroll "
        "position scrolled past every one of its columns")


def test_switching_segments_resets_the_vertical_scroll_position(qtbot):
    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(200))
    v.set_records_for("secondary", [{"Size": 1}, {"Size": 2}, {"Size": 3}])
    qtbot.addWidget(v)
    v.resize(600, 120)
    v.show()
    qtbot.waitExposed(v)
    bar = v.table.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert bar.maximum() > 0, (
        "the fixture must actually scroll for this to mean anything")
    assert bar.value() > 0

    v._switch_segment("secondary")

    assert v.table.verticalScrollBar().value() == 0, (
        "switching to a shorter segment left the vertical scroll "
        "position scrolled past every one of its rows")


def test_a_same_column_data_refresh_does_not_reset_scroll(qtbot):
    """The invariant is a COLUMN-SET change, not "any render at all" --
    set_records_for on the segment already on screen re-renders with the
    SAME RecordSet.columns every time (a second Open Evidence, a
    recovery merge landing more rows), and must leave an examiner's
    scroll position alone."""
    v = _TwoSegmentView()
    v.set_records_for("primary", _rows(200))
    qtbot.addWidget(v)
    v.resize(600, 120)
    v.show()
    qtbot.waitExposed(v)
    bar = v.table.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert bar.value() > 0, (
        "the fixture must actually scroll for this to mean anything")

    v.set_records_for("primary", _rows(200))  # same segment, same columns

    assert v.table.verticalScrollBar().value() > 0, (
        "a same-column data refresh must not steal the examiner's own "
        "scroll position")


# --- the two additive base changes Timeline needs ------------------------
#
# Both are additive: annotate_basis EXTRACTS the badge loop __init__
# already ran, and initial_key defaults to None so "first declared wins"
# is unchanged for every view that existed before Timeline.

def test_annotate_basis_is_reachable_without_an_instance():
    """A subclass with a SECOND table (Timeline's per-period pane) has to
    annotate that table's own columns, and it does so BEFORE the base
    constructor has finished -- so this cannot be an ordinary bound
    method that needs a fully-built view."""
    from webcache.engine import evidence_model

    columns = [Column("CleanUrl", "Address", 200, kind="url",
                      field="CleanUrl"),
               Column("Nothing", "Nothing", 80, kind="text")]
    RecordsView.annotate_basis(columns)

    basis = evidence_model.basis_of("CleanUrl")
    assert columns[0].badge == evidence_model.BASIS_SHORT[basis]
    assert evidence_model.BASIS_DEFINITION[basis] in columns[0].badge_tooltip
    assert columns[1].badge is None, (
        "a column that names no field cites nothing, and must not acquire "
        "a badge that would read as a citation")
    assert columns[1].badge_tooltip is None


def test_the_base_annotates_its_record_sets_through_that_same_function(qtbot):
    """ONE copy of the rule. A column in a sub-table must not end up with
    a differently-computed badge from the identical column in a record
    set -- which is exactly what a second inline loop would eventually
    produce."""
    v = _OneSegmentView()
    qtbot.addWidget(v)
    from_base = next(c for c in v.COLUMNS if c.key == "Name")

    fresh = [Column("Name", "Name", 200, kind="text", field="Name")]
    RecordsView.annotate_basis(fresh)

    assert from_base.badge == fresh[0].badge
    assert from_base.badge_tooltip == fresh[0].badge_tooltip


class _InitialKeyView(RecordsView):
    """Two segments declared coarse-last, opened on the SECOND one --
    Timeline's own shape: its grains must READ fine-to-coarse while
    OPENING on day."""

    def __init__(self, initial_key=None, parent=None):
        super().__init__(
            record_sets=[RecordSet("primary", "Primary", _SINGLE_COLUMNS),
                         RecordSet("secondary", "Secondary", _OTHER_COLUMNS)],
            header_icon="grid", header_title="Two Segments",
            initial_key=initial_key, parent=parent)


def test_initial_key_opens_on_the_named_segment_not_the_first(qtbot):
    v = _InitialKeyView(initial_key="secondary")
    qtbot.addWidget(v)
    assert v._active_key == "secondary"
    assert [c.key for c in v.COLUMNS] == [c.key for c in _OTHER_COLUMNS]
    assert v._switcher_buttons["secondary"].isChecked()
    assert not v._switcher_buttons["primary"].isChecked()


def test_no_initial_key_still_means_first_declared_wins(qtbot):
    """The default must not change the six views that existed before it."""
    v = _InitialKeyView()
    qtbot.addWidget(v)
    assert v._active_key == "primary"


def test_an_unknown_initial_key_falls_back_to_the_first_segment(qtbot):
    """A typo in a subclass must not leave the view with an active key no
    RecordSet answers to -- every lookup after that would raise."""
    v = _InitialKeyView(initial_key="no-such-segment")
    qtbot.addWidget(v)
    assert v._active_key == "primary"


# --- the count line: what it calls a row, and what it does when long ------

def test_the_count_noun_is_records_for_a_view_of_records(qtbot):
    """Unchanged for every view that existed before the noun was
    nameable."""
    v = _OneSegmentView()
    qtbot.addWidget(v)
    v.set_records(_rows(3))
    assert v.count_label.text().startswith("3 records")
    assert RecordsView.COUNT_NOUN == "records"


def test_the_count_line_wraps_instead_of_clipping(qtbot):
    """A note can carry three sentences (Timeline's does: what is on the
    timeline, the silences, and what a silence is not). Clipped at the
    window edge, the last two are simply not on screen -- which for a
    caveat is the same as not having written it."""
    v = _OneSegmentView()
    qtbot.addWidget(v)
    assert v.count_label.wordWrap() is True


def test_the_count_rows_side_labels_are_top_aligned(qtbot):
    """The count label wraps, so this row is as tall as the note beside
    it. Looked at on screen at 1280px with Location's six-line note: the
    "Identical in all N" chip rendered as a tall empty bordered box with
    one line floating in the middle. Both side widgets align to the top of
    the paragraph they annotate."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QHBoxLayout, QLayout

    view = _OneSegmentView()
    qtbot.addWidget(view)
    wanted = {view._constant_chip, view._filter_desc_label}
    found = {}
    stack = [view.layout()]
    while stack:
        layout = stack.pop()
        if layout is None:
            continue
        for i in range(layout.count()):
            item = layout.itemAt(i)
            child = item.layout()
            if isinstance(child, QLayout):
                stack.append(child)
            widget = item.widget()
            if widget in wanted and isinstance(layout, QHBoxLayout):
                found[widget] = item.alignment()
    assert set(found) == wanted, found
    for widget, alignment in found.items():
        assert alignment & Qt.AlignTop, widget


# --- _header_extra: the SECOND layout seam --------------------------------
#
# Both additions below are additive and default-off, so the eight views
# that existed before them render byte-for-byte as they did. They exist
# because Search and Findings each need something the base could not
# express: chrome ABOVE the filter bar that is not a table (a query bar,
# a corpus banner), and a count noun that changes per SEGMENT rather than
# per view.


class _HeaderExtraView(RecordsView):
    """A view that pins its own widget between header and switcher."""

    _extra = None

    def __init__(self, parent=None):
        super().__init__(
            record_sets=[RecordSet("a", "A", _SINGLE_COLUMNS),
                         RecordSet("b", "B", _OTHER_COLUMNS)],
            header_icon="grid", header_title="Extra", parent=parent)

    def _header_extra(self):
        from PySide6.QtWidgets import QLabel
        if self._extra is None:
            self._extra = QLabel("the query bar")
        return self._extra


def test_the_base_pins_no_extra_header_widget_by_default(qtbot):
    """Declare none, render none -- the same discipline chips and the
    switcher already keep, so no existing view's layout moves a pixel."""
    v = _OneSegmentView()
    qtbot.addWidget(v)
    assert v._header_extra() is None


def test_a_declared_header_extra_sits_between_the_header_and_the_switcher(qtbot):
    from PySide6.QtWidgets import QVBoxLayout

    v = _HeaderExtraView()
    qtbot.addWidget(v)
    root = v.layout()
    assert isinstance(root, QVBoxLayout)
    order = []
    for i in range(root.count()):
        item = root.itemAt(i)
        order.append(item.widget() if item.widget() is not None else item.layout())
    assert order.index(v.header) < order.index(v._extra), (
        "the extra chrome must sit BELOW the view header")
    # The switcher is a layout, not a widget: it is the first QHBoxLayout
    # after the extra.
    extra_at = order.index(v._extra)
    assert any(item is not None and not hasattr(item, "setText")
               for item in order[extra_at + 1:]), (
        "the switcher must still come after the extra chrome")


def test_the_header_extra_hook_is_called_exactly_once(qtbot):
    """Same contract as _table_area: called once from the base
    constructor, and idempotent -- a second ask must return the SAME
    widget rather than reparent one out of the layout it is in."""
    v = _HeaderExtraView()
    qtbot.addWidget(v)
    assert v._header_extra() is v._extra
    assert v._extra.parent() is not None


def test_the_header_extra_is_built_after_the_table_and_filter_box_exist(qtbot):
    """An override may reference self.table/self.filter_box -- Search's
    query bar does exactly that."""

    class _Peeker(RecordsView):
        seen = None

        def __init__(self):
            super().__init__(
                record_sets=[RecordSet("a", "A", _SINGLE_COLUMNS)],
                header_icon="grid", header_title="Peek")

        def _header_extra(self):
            from PySide6.QtWidgets import QLabel
            _Peeker.seen = (self.table is not None,
                            self.filter_box is not None)
            return QLabel("x")

    v = _Peeker()
    qtbot.addWidget(v)
    assert _Peeker.seen == (True, True)


# --- RecordSet.count_noun: the noun at SEGMENT granularity ----------------

class _NounView(RecordsView):
    COUNT_NOUN = "records"

    def __init__(self, parent=None):
        super().__init__(
            record_sets=[
                RecordSet("plain", "Plain", _SINGLE_COLUMNS),
                RecordSet("hits", "Hits", _SINGLE_COLUMNS,
                          count_noun="hits"),
            ],
            header_icon="grid", header_title="Nouns", parent=parent)


def test_a_record_set_declares_no_count_noun_by_default():
    """No existing RecordSet passes one, so no existing count line
    changes by a character."""
    assert RecordSet("k", "K", _SINGLE_COLUMNS).count_noun is None


def test_a_segments_own_noun_wins_over_the_views(qtbot):
    """Timeline's COUNT_NOUN = "periods" already established that the
    noun is load-bearing; this is that rule one level down, for a view
    whose segments count six different things."""
    v = _NounView()
    qtbot.addWidget(v)
    v.set_records_for("plain", _rows(3))
    v.set_records_for("hits", _rows(2))
    assert v.count_label.text().startswith("3 records")
    v._switch_segment("hits")
    assert v.count_label.text().startswith("2 hits")


def test_a_segment_with_no_noun_falls_back_to_the_views_own(qtbot):
    v = _NounView()
    qtbot.addWidget(v)
    v._switch_segment("hits")
    v._switch_segment("plain")
    v.set_records(_rows(4))
    assert v.count_label.text().startswith("4 records")
