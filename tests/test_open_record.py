"""Opening a record, and saying so on screen.

RecordsTable has emitted recordActivated since it was written and NOTHING
has ever listened. Double-click and Enter are, today, a silent no-op on
all seven record tables -- the signature defect this codebase names in
recovery_loader.py's own docstring ("built, but never wired"). These tests
cover the table half: the three routes into the signal, and the fact that
a link cell now looks like something you can act on.

TWO GAPS THE EXISTING ROUTES LEAVE

(a) A LINK CELL CAN NEVER OPEN ITS RECORD. activate_cell routes a link
    column to col.on_click and emits linkActivated instead, so
    double-clicking History's Domain cell drills to Domains and there is
    no way at all to reach the record behind it. activate_cell's
    behaviour is pinned by test_path_kind.py and test_records_table.py
    and is NOT changed here -- open_record() is an explicit override that
    a link column cannot intercept, bound to Ctrl+Enter.

(b) NOBODY KNOWS THE DRILL-THROUGHS EXIST. Three link columns drill
    somewhere useful and look exactly like text. A pointing cursor and a
    tooltip that names both routes cost nothing and are the difference
    between a feature and a rumour.
"""
import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

from webcache.widgets.column_spec import Column
from webcache.widgets.record_model import LINK_ACTIVATION_HINT
from webcache.widgets.records_table import RecordsTable

from tests.fixtures import make_rows
from tests.test_literal_tooltips import shown


@pytest.fixture
def copy_link_table(qtbot):
    """A table whose first column is a COPY link -- the exact
    shape Location's MapsUrl/OsmUrl columns are (views/location.py). The
    cell's activation copies the value; it never opens or follows
    anything."""
    copied = []
    cols = [Column("MapsUrl", "Google Maps", 160, kind="url",
                   on_click=copied.append, on_click_copies=True),
            Column("VisitCount", "Visits", 70, kind="num")]
    rows = make_rows(20)
    table = RecordsTable()
    table.set_records(cols, rows)
    qtbot.addWidget(table)
    table.resize(700, 400)
    table.show()
    qtbot.waitExposed(table)
    table.copied = copied
    return table


@pytest.fixture
def disabled_link_table(qtbot):
    """A table whose first column is a link for MOST rows but not
    all -- the exact shape Timeline's pane ContainerName column is: a
    carved row can have ContainerId None, and link_enabled says so per
    row rather than the column being a link unconditionally."""
    drilled = []
    cols = [Column("ContainerName", "Container", 160, kind="text",
                   on_click=drilled.append,
                   link_enabled=lambda row: row.get("ContainerId") is not None),
            Column("VisitCount", "Visits", 70, kind="num")]
    rows = make_rows(20)
    rows[0]["ContainerId"] = None    # the row with no target
    rows[1]["ContainerId"] = 3       # an ordinary row, target present
    table = RecordsTable()
    table.set_records(cols, rows)
    qtbot.addWidget(table)
    table.resize(700, 400)
    table.show()
    qtbot.waitExposed(table)
    table.drilled = drilled
    return table


@pytest.fixture
def link_table(qtbot):
    """A table whose FIRST column is a drill-through link -- the exact
    shape History has, where Domain drills to the Domains view."""
    drilled = []
    cols = [Column("Domain", "Domain", 160, kind="domain",
                   on_click=drilled.append),
            Column("CleanUrl", "Address", 300, kind="url"),
            Column("VisitCount", "Visits", 70, kind="num")]
    rows = make_rows(20)
    rows[2]["Origin"] = "Carved (unallocated page)"
    table = RecordsTable()
    table.set_records(cols, rows)
    qtbot.addWidget(table)
    table.resize(700, 400)
    table.show()
    qtbot.waitExposed(table)
    table.drilled = drilled
    return table


# --- (a) the route a link column cannot intercept -----------------------

def test_open_record_emits_recordactivated_for_the_row_it_names(link_table, qtbot):
    with qtbot.waitSignal(link_table.recordActivated, timeout=1000) as sig:
        link_table.open_record(4)
    assert sig.args[0] is link_table.model().row_at(4)


def test_the_row_arrives_as_the_same_object_not_a_marshalled_copy(
        link_table, qtbot):
    """Signal(dict) does NOT pass a dict through -- PySide6 marshals it,
    rebuilding the outer row AND every nested dict as new objects.
    Verified directly: with Signal(dict), `received is row` and
    `received["_record"] is entry` are both False.

    That matters here specifically. Unit 1's entire design is "the row
    carries ONE POINTER to the engine record, never a copy", measured and
    asserted per loader with `row["_record"] is entry`. A marshalling
    signal quietly rebuilds that record dict on the way to the dialog, so
    the identity the loaders guarantee stops holding at exactly the
    boundary where a consumer first uses it -- and any future consumer
    that writes a tag or a comment onto row["_record"] would be writing
    into a throwaway.

    Signal(object) passes the object itself. linkActivated already uses
    `object` for its Column argument, so this is the file's own idiom.
    """
    row = link_table.model().row_at(6)
    row["_record"] = {"probe": object()}
    with qtbot.waitSignal(link_table.recordActivated, timeout=1000) as sig:
        link_table.open_record(6)
    received = sig.args[0]
    assert received is row
    assert received["_record"] is row["_record"]


def test_open_record_works_on_a_link_column_where_activate_cell_cannot(
        link_table, qtbot):
    """The defect this closes. Column 0 is a link, so activate_cell(0, 0)
    drills and never reaches the record."""
    link_table.setCurrentIndex(link_table.model().index(0, 0))
    with qtbot.waitSignal(link_table.recordActivated, timeout=1000):
        link_table.open_record(0)
    assert link_table.drilled == [], "open_record must not also drill"


def test_ctrl_enter_opens_the_record_from_a_link_cell(link_table, qtbot):
    link_table.setCurrentIndex(link_table.model().index(3, 0))
    with qtbot.waitSignal(link_table.recordActivated, timeout=1000) as sig:
        QTest.keyClick(link_table, Qt.Key_Return, Qt.ControlModifier)
    assert sig.args[0] is link_table.model().row_at(3)
    assert link_table.drilled == []


def test_ctrl_enter_also_works_on_the_numeric_keypad_enter(link_table, qtbot):
    """Key_Enter (keypad) and Key_Return are different keys; binding only
    one leaves the shortcut dead for anyone using the number pad."""
    link_table.setCurrentIndex(link_table.model().index(1, 0))
    with qtbot.waitSignal(link_table.recordActivated, timeout=1000):
        QTest.keyClick(link_table, Qt.Key_Enter, Qt.ControlModifier)


def test_plain_enter_on_a_link_column_still_drills(link_table, qtbot):
    """activate_cell is pinned by test_path_kind.py and test_records_
    table.py. This adds a route; it does not change one."""
    link_table.activate_cell(2, 0)
    assert len(link_table.drilled) == 1


def test_open_record_out_of_range_is_ignored_not_raised(link_table):
    """A shortcut fires against whatever the current index happens to be,
    including none at all after a filter emptied the table."""
    link_table.open_record(-1)
    link_table.open_record(10_000)


# --- the context menu ---------------------------------------------------

def _live_row(table):
    """make_rows() marks roughly every fourth row carved, so "row 0" is
    not reliably live. Pick one by asking."""
    model = table.model()
    for r in range(model.rowCount()):
        if not str(model.row_at(r).get("Origin", "")).startswith("Carved"):
            return r
    raise AssertionError("the fixture produced no live rows")


def test_the_context_menu_offers_open_this_record_first(link_table):
    ix = link_table.model().index(_live_row(link_table), 1)
    menu = link_table._build_context_menu(ix)
    labels = [a.text() for a in menu.actions()]
    assert "Open this record" in labels[0]
    assert "Ctrl+Enter" in labels[0]
    assert 0 < [i for i, t in enumerate(labels) if "Copy cell" in t][0]


def test_the_context_menu_flags_a_carved_record_in_the_open_label(link_table):
    """The same at-the-moment-of-acting flagging Copy cell already does.
    An examiner opening a carved record should be told so by the control
    they are about to click, not only by the dialog that appears after."""
    carved = [r for r in range(link_table.model().rowCount())
              if str(link_table.model().row_at(r).get("Origin", "")).startswith("Carved")][0]
    menu = link_table._build_context_menu(link_table.model().index(carved, 1))
    assert "carved" in menu.actions()[0].text().lower()


def test_the_menus_open_action_really_emits_the_signal(link_table, qtbot):
    """A menu entry with no handler behind it is this project's own named
    defect class -- "Explain this value\\tF1" shipped inert once already."""
    menu = link_table._build_context_menu(link_table.model().index(5, 0))
    with qtbot.waitSignal(link_table.recordActivated, timeout=1000) as sig:
        menu.actions()[0].trigger()
    assert sig.args[0] is link_table.model().row_at(5)


# --- (b) the affordance -------------------------------------------------

def _move_to(table, row, column):
    point = QPointF(table.visualRect(table.model().index(row, column)).center())
    table.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, point, Qt.NoButton,
                                     Qt.NoButton, Qt.NoModifier))


def test_the_table_tracks_the_mouse_so_the_cursor_can_change_at_all(link_table):
    """Without this, mouseMoveEvent only fires while a button is held and
    the cursor never changes during ordinary hovering."""
    assert link_table.hasMouseTracking() is True


def test_hovering_a_link_cell_shows_a_pointing_cursor(link_table):
    _move_to(link_table, 1, 0)
    assert link_table.viewport().cursor().shape() == Qt.PointingHandCursor


def test_hovering_an_ordinary_cell_restores_the_plain_cursor(link_table):
    _move_to(link_table, 1, 0)
    _move_to(link_table, 1, 2)
    assert link_table.viewport().cursor().shape() != Qt.PointingHandCursor


def test_hovering_off_the_rows_entirely_restores_the_plain_cursor(link_table):
    _move_to(link_table, 1, 0)
    link_table.mouseMoveEvent(QMouseEvent(
        QEvent.MouseMove, QPointF(5, 5000), Qt.NoButton, Qt.NoButton,
        Qt.NoModifier))
    assert link_table.viewport().cursor().shape() != Qt.PointingHandCursor


def test_a_link_cell_says_how_to_open_it(link_table):
    model = link_table.model()
    tip = model.data(model.index(0, 0), Qt.ToolTipRole)
    assert LINK_ACTIVATION_HINT in tip
    assert str(model.row_at(0)["Domain"]) in tip


def test_the_hint_names_both_routes_because_they_do_different_things(link_table):
    """One opens the thing the value refers to; the other opens the record
    the value is on. An examiner who only learns the first has no way to
    reach the second."""
    assert "double-click" in LINK_ACTIVATION_HINT.lower()
    assert "Ctrl+Enter" in LINK_ACTIVATION_HINT


def test_an_ordinary_cell_tooltip_is_still_only_the_value(link_table):
    model = link_table.model()
    tip = model.data(model.index(0, 2), Qt.ToolTipRole)
    assert shown(tip) == str(model.row_at(0)["VisitCount"])
    assert LINK_ACTIVATION_HINT not in tip


def test_a_copy_link_cell_says_copy_not_follow(copy_link_table):
    """MapsUrl/OsmUrl declare on_click handlers that COPY, which
    makes Column.is_link true -- and record_model previously attached
    LINK_ACTIVATION_HINT ("Double-click to follow this value") to every
    link cell regardless. Given this project's "Copy, never Open" rule
    the behaviour is right and the wording was wrong: the tooltip at the
    point of action must say the cell copies, not that it opens a map."""
    model = copy_link_table.model()
    tip = model.data(model.index(0, 0), Qt.ToolTipRole)
    assert LINK_ACTIVATION_HINT not in tip, tip
    assert "double-click" in tip.lower() and "copy" in tip.lower(), tip
    assert "follow" not in tip.lower(), tip


def test_an_empty_link_cell_still_carries_the_hint(link_table):
    """A blank cell is the one an examiner is LEAST likely to try
    clicking, and dropping the hint there would hide the affordance
    exactly where it is least discoverable."""
    model = link_table.model()
    rows = list(model.filter.visible())
    rows[0]["Domain"] = ""
    model.set_rows(rows)
    tip = model.data(model.index(0, 0), Qt.ToolTipRole)
    assert LINK_ACTIVATION_HINT in tip


# --- a link column whose target does not exist for every row -----

def test_a_row_with_no_target_gets_no_link_tooltip(disabled_link_table):
    """A blank link cell is still a link if is_link is a column-only
    property -- it shows the "double-click to follow" hint even though
    activating it goes nowhere. link_enabled makes the column say, per
    row, when there genuinely is nothing to follow."""
    model = disabled_link_table.model()
    no_target_tip = model.data(model.index(0, 0), Qt.ToolTipRole)
    has_target_tip = model.data(model.index(1, 0), Qt.ToolTipRole)
    assert LINK_ACTIVATION_HINT not in no_target_tip, no_target_tip
    assert LINK_ACTIVATION_HINT in has_target_tip, has_target_tip


def test_a_row_with_no_target_gets_no_pointing_cursor(disabled_link_table):
    _move_to(disabled_link_table, 0, 0)
    assert (disabled_link_table.viewport().cursor().shape()
            != Qt.PointingHandCursor)
    _move_to(disabled_link_table, 1, 0)
    assert (disabled_link_table.viewport().cursor().shape()
            == Qt.PointingHandCursor)


def test_activating_a_row_with_no_target_opens_the_record_instead(
        disabled_link_table, qtbot):
    """Not a dead click: the exact lesson this module's own docstring
    states for a link column that could not reach its record at all. A
    cell that is not a link for THIS row behaves like any other ordinary
    cell -- double-click opens the record, and on_click is never called
    with nothing to point at."""
    with qtbot.waitSignal(disabled_link_table.recordActivated,
                          timeout=1000) as sig:
        disabled_link_table.activate_cell(0, 0)
    assert sig.args[0] is disabled_link_table.model().row_at(0)
    assert disabled_link_table.drilled == [], (
        "on_click must not be called for a row with no target")


def test_activating_a_row_with_a_target_still_drills(disabled_link_table):
    disabled_link_table.activate_cell(1, 0)
    assert disabled_link_table.drilled == [
        disabled_link_table.model().row_at(1)]
