import pytest
import shiboken6
from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolTip

from webcache.widgets.column_spec import Column
from webcache.widgets.record_model import (ORIGIN_LABEL_CARVED, ORIGIN_LABEL_LIVE,
                                            ROLE_IS_CARVED, ROLE_RAW)
from webcache.widgets.records_table import _HEADER_PAD_PX, RecordsTable
from tests.fixtures import FIXTURE_COLUMNS, make_rows


@pytest.fixture
def table(qtbot):
    t = RecordsTable()
    t.set_records(list(FIXTURE_COLUMNS), make_rows(500))
    qtbot.addWidget(t)
    # 1500, not 1400: _LABEL_ESTIMATE_SLACK_PX (records_table.py) widened
    # the plain-column floor to account for theme.py's real QSS section
    # padding, which pushed every FIXTURE_COLUMNS row past 1400px wide --
    # see test_vertical_header_does_not_clip_a_column_used_by_header_
    # click_sorting's own docstring for the real, functional failure a
    # too-narrow viewport causes (a header click on a partially-visible
    # section auto-scrolls, silently moving every later column before a
    # second click lands).
    # 1600, not 1500: the origin column now reads "Carved" and is
    # ~50px wider than the clipped "C" it replaced.
    t.resize(1600, 700)
    t.show()
    qtbot.waitExposed(t)
    return t


def test_clicking_a_header_sorts_and_clicking_again_reverses(table, qtbot):
    header = table.horizontalHeader()
    col = [c.key for c in FIXTURE_COLUMNS].index("VisitCount")
    x = header.sectionPosition(col) + header.sectionSize(col) // 2
    QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=QPoint(x, 5))
    first_asc = table.model().row_at(0)["VisitCount"]
    QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=QPoint(x, 5))
    first_desc = table.model().row_at(0)["VisitCount"]
    assert first_desc >= first_asc


def test_ctrl_click_adds_a_second_sort_column(table, qtbot):
    """Qt sorts by one column only. Multi-sort is ours to implement."""
    header = table.horizontalHeader()
    keys = [c.key for c in FIXTURE_COLUMNS]
    d, v = keys.index("Domain"), keys.index("VisitCount")
    for col, mod in ((d, Qt.NoModifier), (v, Qt.ControlModifier)):
        x = header.sectionPosition(col) + header.sectionSize(col) // 2
        QTest.mouseClick(header.viewport(), Qt.LeftButton, mod, QPoint(x, 5))
    rows = [table.model().row_at(i) for i in range(table.model().rowCount())]
    same_domain = [r for r in rows if r["Domain"] == rows[0]["Domain"]]
    counts = [r["VisitCount"] for r in same_domain]
    assert counts == sorted(counts), "second sort key not applied within the first"


def test_ctrl_c_copies_a_rectangular_selection_as_tsv_with_headers(table):
    """It must paste into Excel intact -- that is the point."""
    table.selectRow(0)
    tsv = table.copy_selection_as_tsv()
    lines = tsv.splitlines()
    assert len(lines) == 2
    assert lines[0].split("\t")[0] == "Address"
    assert lines[1].split("\t")[0] == table.model().row_at(0)["CleanUrl"]


def test_copy_puts_it_on_the_clipboard(table, qtbot):
    table.selectRow(0)
    QTest.keyClick(table, Qt.Key_C, Qt.ControlModifier)
    assert "Address" in QGuiApplication.clipboard().text()


def test_enter_opens_the_record(table, qtbot):
    table.selectRow(3)
    with qtbot.waitSignal(table.recordActivated, timeout=1000) as sig:
        QTest.keyClick(table, Qt.Key_Return)
    assert sig.args[0]["CleanUrl"] == table.model().row_at(3)["CleanUrl"]


def test_a_link_column_emits_linkActivated_rather_than_opening_the_record(qtbot):
    seen = []
    cols = [Column("Domain", "Domain", 160, kind="domain", on_click=seen.append),
            Column("VisitCount", "Visits", 70, kind="num")]
    t = RecordsTable()
    t.set_records(cols, make_rows(50))
    qtbot.addWidget(t)
    t.resize(600, 400)
    t.show()
    qtbot.waitExposed(t)
    with qtbot.waitSignal(t.linkActivated, timeout=1000):
        t.activate_cell(0, 0)
    assert t.model().column_at(0).is_link


def test_set_records_deletes_the_outgoing_model(table, qtbot):
    """Every successful Open Evidence calls set_records() again on the
    SAME RecordsTable. Before this fix, setModel() silently replaced the
    old RecordTableModel with a new one, but the old model -- parented to
    this table -- was never disposed: it stayed alive, still holding its
    full row list, for the life of the process. Every Open Evidence
    leaked one."""
    old_model = table.model()
    table.set_records(list(FIXTURE_COLUMNS), make_rows(10))
    qtbot.wait(50)  # let the deferred delete actually run
    assert not shiboken6.isValid(old_model), (
        "the outgoing model must be deleted, not merely orphaned")
    assert table.model().rowCount() == 10


def test_set_records_clears_a_live_filter_popup_referencing_the_old_model(table, qtbot):
    """A FilterPopup holds a direct reference to the model it was opened
    against (FilterPopup.__init__: self.model = model). Deleting the
    outgoing model out from under a still-open popup -- left open across
    an Open Evidence, a real if unusual sequence since the popup is
    non-modal -- would leave that popup holding a dangling C++ pointer the
    instant the deferred delete actually runs. This proves the popup is
    closed and detached FIRST, before the model it points at is ever
    scheduled for deletion."""
    table.filterRequested.emit(0)
    popup = table._filter_popup
    assert popup is not None
    assert popup.model is table.model()

    table.set_records(list(FIXTURE_COLUMNS), make_rows(10))
    qtbot.wait(50)

    assert table._filter_popup is None, (
        "a filter popup opened against the outgoing model must not be "
        "left referencing a model that is about to be deleted")


def test_empty_selection_names_the_column_and_offers_a_way_back(table):
    """No state is a dead end."""
    table.model().set_values("Domain", set())
    assert table.model().rowCount() == 0
    assert "Domain" in table.empty_message()
    assert "Clear filters" in table.empty_message()


def test_no_filter_and_no_rows_reads_differently_from_an_emptied_filter(qtbot):
    t = RecordsTable()
    t.set_records(list(FIXTURE_COLUMNS), [])
    qtbot.addWidget(t)
    assert "Clear filters" not in t.empty_message()


# --- the genuine empty state: distinct from a filter emptying the table ----

def test_a_genuinely_empty_table_shows_no_overlay_until_a_reason_is_set(qtbot):
    """A caller that never heard of set_empty_reason (an older test, or a
    view not yet updated) gets exactly the old behaviour back: no
    overlay, nothing painted."""
    t = RecordsTable()
    t.set_records(list(FIXTURE_COLUMNS), [])
    qtbot.addWidget(t)
    assert t.showing_genuine_empty_state() is False
    assert t.empty_state_text() == ""


def test_set_empty_reason_turns_on_the_genuine_empty_state(qtbot):
    t = RecordsTable()
    t.set_records(list(FIXTURE_COLUMNS), [])
    qtbot.addWidget(t)
    t.set_empty_reason("No Widgets in this exhibit.")
    assert t.showing_genuine_empty_state() is True
    assert t.empty_state_text() == "No Widgets in this exhibit."


def test_genuine_empty_state_never_shows_when_there_are_rows(qtbot):
    t = RecordsTable()
    t.set_records(list(FIXTURE_COLUMNS), make_rows(5))
    qtbot.addWidget(t)
    t.set_empty_reason("should never show -- there are rows")
    assert t.showing_genuine_empty_state() is False
    assert t.empty_state_text() == ""


def test_filtered_to_zero_never_shows_the_genuine_empty_state(table):
    """The two states this defect is about must never be confusable: a
    table emptied by a FILTER keeps empty_message()'s own wording and
    must never also trip the genuine-empty overlay, even when a reason
    happens to be set (as it always will be in real use -- a view sets
    it once per record set, independent of whatever the filter box is
    doing)."""
    table.set_empty_reason("No Widgets in this exhibit.")
    table.model().set_values("Domain", set())
    assert table.model().rowCount() == 0

    assert table.showing_genuine_empty_state() is False
    assert table.empty_state_text() == table.empty_message()  # the filters sentence, never the reason
    # the filtered case keeps reading exactly as it always has
    assert "Domain" in table.empty_message()
    assert "Clear filters" in table.empty_message()


def test_clearing_the_filter_that_emptied_it_does_not_retroactively_show_the_reason(table):
    """Restoring rows after Show All Records must land back on "there are
    rows, no overlay" -- not leave the genuine-empty overlay armed for
    the instant before the model actually repopulates."""
    table.set_empty_reason("No Widgets in this exhibit.")
    table.model().set_values("Domain", set())
    assert table.model().rowCount() == 0

    table.model().clear_all()
    assert table.model().rowCount() > 0
    assert table.showing_genuine_empty_state() is False


def test_a_new_set_records_call_clears_the_previous_reason(qtbot):
    """A segment switch (File Access's "file access" -> "downloads") or a
    fresh Open Evidence must not paint a STALE record set's wording over
    the new one's -- see set_records' own comment on why this is cleared
    before the caller gets a chance to set the real one."""
    t = RecordsTable()
    t.set_records(list(FIXTURE_COLUMNS), [])
    t.set_empty_reason("No Widgets in this exhibit.")
    qtbot.addWidget(t)
    assert t.showing_genuine_empty_state() is True

    t.set_records(list(FIXTURE_COLUMNS), [])
    assert t.showing_genuine_empty_state() is False
    assert t.empty_state_text() == ""


def test_column_widths_round_trip_through_settings(table):
    table.horizontalHeader().resizeSection(0, 321)
    state = table.save_column_state()
    table.horizontalHeader().resizeSection(0, 100)
    table.restore_column_state(state)
    assert table.horizontalHeader().sectionSize(0) == 321


def test_restoring_a_saved_state_never_leaves_a_column_below_its_heading(qtbot):
    """QHeaderView.restoreState() sets every section's size wholesale and
    does NOT go through sectionResized -- _enforce_heading_floor (the
    "never squeeze a column below its heading" rule, see that method's own
    docstring) only ever fires on an interactive drag, so it never runs
    for a restore. A width saved once from a cramped window is then
    re-applied verbatim on every later launch, permanently: this is what
    produced headings reading "Ac", "Last v", "ast vis" on a real launch.

    The sub-floor state is authored by disconnecting the very hook under
    test before resizing -- the only way to get a genuinely sub-floor
    state INTO a header that (correctly) refuses to let an interactive
    drag create one in the first place. That is exactly the shape of a
    state saved by an older build, or from a squeezed window, and is a
    faithful stand-in for it.
    """
    source = RecordsTable()
    source.set_records(list(FIXTURE_COLUMNS), make_rows(5))
    qtbot.addWidget(source)
    sheader = source.horizontalHeader()
    sheader.sectionResized.disconnect(source._enforce_heading_floor)
    for i in range(len(FIXTURE_COLUMNS)):
        sheader.resizeSection(i, 5)
    state = source.save_column_state()

    target = RecordsTable()
    target.set_records(list(FIXTURE_COLUMNS), make_rows(5))
    qtbot.addWidget(target)
    target.restore_column_state(state)

    theader = target.horizontalHeader()
    fm = theader.fontMetrics()
    for i, c in enumerate(FIXTURE_COLUMNS):
        assert theader.sectionSize(i) >= fm.horizontalAdvance(c.label) + 8, (
            "column %r restored below its own heading floor" % c.label)


_ALT_COLUMNS = [
    Column("Alt1", "Something else entirely", 200, kind="text"),
    Column("Alt2", "A totally different label", 200, kind="text"),
]


def test_restore_column_state_ignores_a_state_saved_for_different_columns(qtbot):
    """column_state is persisted keyed by VIEW, not by the exact column set
    that view happened to show when it was captured -- a multi-segment
    view (File Access: file-access records vs downloads; Cookies & HSTS:
    cookies vs HSTS vs certificates) reuses the SAME RecordsTable/settings
    key across segments with DIFFERENT COLUMNS, and a view's own COLUMNS
    can also change between releases.

    QHeaderView.restoreState() keys purely on section COUNT/position, with
    no notion of what a section actually MEANS, and applying a state saved
    for a differently-shaped column set was observed to desync the
    header's own count() from its model's real column count (restoreState
    still returns True). A saved state whose signature does not match the
    table's current columns must be refused outright, leaving whatever
    _fit_columns() already applied untouched.
    """
    source = RecordsTable()
    source.set_records(list(_ALT_COLUMNS), make_rows(3))
    qtbot.addWidget(source)
    state = source.save_column_state()
    signature = source.column_signature()

    target = RecordsTable()
    target.set_records(list(FIXTURE_COLUMNS), make_rows(3))
    qtbot.addWidget(target)
    theader = target.horizontalHeader()
    before = [theader.sectionSize(i) for i in range(len(FIXTURE_COLUMNS))]

    target.restore_column_state(state, signature=signature)

    assert theader.count() == len(FIXTURE_COLUMNS), (
        "a mismatched restore desynced the header from its own model")
    after = [theader.sectionSize(i) for i in range(len(FIXTURE_COLUMNS))]
    assert after == before, (
        "a state saved for a different column set must not be applied")


def test_the_plain_heading_floor_carries_the_same_safety_margin_the_badge_floor_does(table):
    """_enforce_heading_floor's badge branch already carries a +6px
    safety margin because horizontalAdvance() is only an ESTIMATE of
    what the style actually renders -- its own comment: "'Last visit
    (UTC)' rendered its closing ')' cut off at this formula's exact,
    unpadded floor". Verified against the real, on-screen application
    (not this offscreen harness, where fontMetrics happens to be exact
    since no QSS theme is applied): restoring a column state that put a
    PLAIN (non-badge) column at exactly its bare label_w + _HEADER_PAD_PX
    floor rendered visibly clipped -- "Title" painted as "itl". The
    badge branch's margin does not help a column with no badge; the
    plain branch needs its own.
    """
    header = table.horizontalHeader()
    fm = header.fontMetrics()
    for i, c in enumerate(table.model().columns):
        assert not (c.show_badge and c.badge), (
            "fixture must stay badge-free for this to test the plain branch")
        bare_floor = fm.horizontalAdvance(c.label) + _HEADER_PAD_PX
        header.resizeSection(i, bare_floor)
        assert header.sectionSize(i) > bare_floor, (
            "%r's floor carries no safety margin beyond the bare, "
            "unpadded estimate" % c.label)


def test_a_column_is_never_squeezed_below_its_heading(table):
    """Squeezing a column under its label is what broke the filters before.

    Measured with the HEADER's own fontMetrics, not the view's -- a header
    can legitimately use a different font than the body, and the floor this
    constraint enforces is about what the header itself needs to render its
    own label, not about the body font."""
    header = table.horizontalHeader()
    fm = header.fontMetrics()
    for i, c in enumerate(table.model().columns):
        assert header.sectionSize(i) >= fm.horizontalAdvance(c.label) + 8


def test_dragging_a_column_narrower_than_its_heading_is_clamped(table):
    """The floor _fit_columns() applies only helps once, at load time. A
    user dragging a column edge afterward is the scenario the constraint
    actually exists for."""
    header = table.horizontalHeader()
    fm = header.fontMetrics()
    header.resizeSection(0, 5)
    floor = fm.horizontalAdvance(table.model().column_at(0).label) + 8
    assert header.sectionSize(0) >= floor


def test_f1_emits_explain_requested_for_the_current_cell(table, qtbot):
    """The context menu advertises 'Explain this value\tF1' -- the
    shortcut has to actually exist, or the hint lies."""
    ix = table.model().index(2, 0)
    table.setCurrentIndex(ix)
    with qtbot.waitSignal(table.explainRequested, timeout=1000) as sig:
        QTest.keyClick(table, Qt.Key_F1)
    assert sig.args[0]["CleanUrl"] == table.model().row_at(2)["CleanUrl"]
    assert sig.args[1] == table.model().column_at(0).key


# --- carved/live: a non-colour marker, structurally immune to hiding, ------
# --- sorting, filtering, and resizing any data column ---------------------

def test_carved_row_is_distinguishable_without_reading_any_colour_role(table):
    """Colour dies under colour-vision deficiency, a greyscale print of an
    exhibit, and a high-contrast Windows theme. This reads only the
    VERTICAL header's DisplayRole text -- never Qt.ForegroundRole, never a
    palette -- and must still be able to tell a carved row from a live one.

    The label is a word on every row, "Live" or "Carved"; the
    single letter it replaced rendered clipped.
    """
    model = table.model()
    carved_row = next(r for r in range(model.rowCount())
                       if model.data(model.index(r, 0), ROLE_IS_CARVED))
    live_row = next(r for r in range(model.rowCount())
                     if not model.data(model.index(r, 0), ROLE_IS_CARVED))
    assert model.headerData(carved_row, Qt.Vertical, Qt.DisplayRole) == ORIGIN_LABEL_CARVED
    assert model.headerData(live_row, Qt.Vertical, Qt.DisplayRole) == ORIGIN_LABEL_LIVE


def test_carved_row_accessible_text_spells_it_out_in_full(table):
    """The visual glyph is compact for width reasons; the accessible text a
    screen reader announces is under no such pixel constraint and carries
    the unabbreviated fact instead of repeating "C"."""
    model = table.model()
    carved_row = next(r for r in range(model.rowCount())
                       if model.data(model.index(r, 0), ROLE_IS_CARVED))
    live_row = next(r for r in range(model.rowCount())
                     if not model.data(model.index(r, 0), ROLE_IS_CARVED))
    carved_text = model.headerData(carved_row, Qt.Vertical, Qt.AccessibleTextRole)
    assert "not a live record" in carved_text.lower()
    assert carved_text != ORIGIN_LABEL_CARVED, "accessible text must not just repeat the glyph"
    assert "live record" in model.headerData(
        live_row, Qt.Vertical, Qt.AccessibleTextRole).lower()


def test_carved_marker_survives_a_sort(table):
    """The marker is re-derived from ROLE_IS_CARVED on every headerData
    call, keyed by the row now occupying each visual position -- so
    re-sorting must not strand it on the wrong row."""
    table.model().sort_by("VisitCount", True)
    model = table.model()
    checked_carved = checked_live = False
    for r in range(model.rowCount()):
        is_carved = bool(model.data(model.index(r, 0), ROLE_IS_CARVED))
        marker = model.headerData(r, Qt.Vertical, Qt.DisplayRole)
        assert marker == (ORIGIN_LABEL_CARVED if is_carved else ORIGIN_LABEL_LIVE)
        checked_carved = checked_carved or is_carved
        checked_live = checked_live or not is_carved
    assert checked_carved and checked_live, "fixture must exercise both cases"


def test_hiding_every_column_does_not_remove_the_carved_marker(table):
    """The marker lives on the vertical header, an axis no column-level
    operation can reach -- unlike a marker painted inside a data column,
    which vanishes the instant that column is hidden. Column.hidden is not
    wired up anywhere in this app yet, but QTableView's own
    setColumnHidden works regardless of that, so this is testable."""
    model = table.model()
    carved_row = next(r for r in range(model.rowCount())
                       if model.data(model.index(r, 0), ROLE_IS_CARVED))
    for c in range(model.columnCount()):
        table.setColumnHidden(c, True)
    assert model.headerData(carved_row, Qt.Vertical, Qt.DisplayRole) == ORIGIN_LABEL_CARVED
    assert table.verticalHeader().isVisible()


def test_vertical_header_does_not_clip_a_column_used_by_header_click_sorting(table):
    """The regression, pinned directly. Domain is one of the two columns
    test_ctrl_click_adds_a_second_sort_column clicks by computed
    coordinate; at this fixture's window size it was fully inside the
    horizontal viewport with no vertical header, but an 8-character-wide
    one (the first cut of the old marker) clipped it -- and clicking a
    PARTIALLY visible header section auto-scrolls the view, silently
    moving every later column's on-screen position before the second
    click. If a future change widens the origin column again, this test
    fails on its own, before a header-click test starts misfiring for a
    reason that looks unrelated to the marker."""
    header = table.horizontalHeader()
    domain = [c.key for c in FIXTURE_COLUMNS].index("Domain")
    right_edge = header.sectionPosition(domain) + header.sectionSize(domain)
    assert right_edge <= header.viewport().width()


# --- copy paths: falsy values, TSV escaping, true selection, and the ------
# --- carved provenance guarantee --------

def _copy_cell_action(menu):
    """The "Copy cell" entry, FOUND BY LABEL rather than by position.

    THE PREMISE THAT STOPPED BEING TRUE: Copy cell was the first action in
    this menu, and these tests reached for actions()[0]. It is now the
    second -- "Open this record	Ctrl+Enter" and a separator go above it,
    because the detail dialog is what an examiner most often wants from a
    right-click on a record and until it existed the record's other fifty
    values had no route to the screen at all.

    Located by label so the next insertion above it does not silently
    change what these assert. What they check -- that a byte-exact copy
    survives a falsy value, and that a carved record is flagged in the
    LABEL rather than in the copied text -- is untouched.
    """
    for action in menu.actions():
        if action.text().startswith("Copy cell"):
            return action
    raise AssertionError("no Copy cell action in %r"
                         % [a.text() for a in menu.actions()])


def test_copy_cell_preserves_falsy_values(table):
    """0 and False are legitimate values, not missing data. `str(x or "")`
    silently turns either into "" -- which an examiner reads as *no data*
    when the truth is *the value is zero* (finding 1)."""
    model = table.model()
    offset_col = [c.key for c in FIXTURE_COLUMNS].index("Offset")
    row = next(r for r in range(model.rowCount())
               if model.data(model.index(r, offset_col), ROLE_RAW) == 0)
    menu = table._build_context_menu(model.index(row, offset_col))
    _copy_cell_action(menu).trigger()
    assert QGuiApplication.clipboard().text() == "0"

    private_col = [c.key for c in FIXTURE_COLUMNS].index("IsInPrivate")
    row2 = next(r for r in range(model.rowCount())
                if model.data(model.index(r, private_col), ROLE_RAW) is False)
    menu2 = table._build_context_menu(model.index(row2, private_col))
    _copy_cell_action(menu2).trigger()
    assert QGuiApplication.clipboard().text() == "False"


def test_copy_row_preserves_falsy_values(table):
    model = table.model()
    offset_col = [c.key for c in FIXTURE_COLUMNS].index("Offset")
    row = next(r for r in range(model.rowCount())
               if model.data(model.index(r, offset_col), ROLE_RAW) == 0)
    table._copy_row(row)
    assert QGuiApplication.clipboard().text().split("\t")[offset_col] == "0"


def test_copy_column_preserves_falsy_values(table):
    model = table.model()
    offset_col = [c.key for c in FIXTURE_COLUMNS].index("Offset")
    table._copy_column(offset_col)
    values = [line.split("\t")[0]
              for line in QGuiApplication.clipboard().text().split("\n")]
    assert "0" in values


def test_copy_cell_label_names_a_carved_record_but_stays_byte_exact(table):
    """Ruling: Copy cell must round-trip byte-exact, so a carved value is
    never decorated. Instead the MENU ITSELF says so, at the moment of
    copying (finding 5)."""
    model = table.model()
    carved_row = next(r for r in range(model.rowCount())
                       if model.data(model.index(r, 0), ROLE_IS_CARVED))
    live_row = next(r for r in range(model.rowCount())
                     if not model.data(model.index(r, 0), ROLE_IS_CARVED))
    carved_menu = table._build_context_menu(model.index(carved_row, 0))
    live_menu = table._build_context_menu(model.index(live_row, 0))
    assert _copy_cell_action(carved_menu).text() == "Copy cell (carved record)"
    assert _copy_cell_action(live_menu).text() == "Copy cell"
    _copy_cell_action(carved_menu).trigger()
    assert QGuiApplication.clipboard().text() == str(model.row_at(carved_row)["CleanUrl"])


def test_copy_row_appends_origin_when_carved_and_not_already_a_column(qtbot):
    """Copy row's bare value dump must carry provenance for a carved row
    even when the view never declared an Origin column -- fidelity of a
    bulk copy means carrying where a value came from, not just the value
    (finding 5)."""
    cols = [Column("CleanUrl", "Address", 300, kind="url"),
            Column("VisitCount", "Visits", 70, kind="num")]
    rows = make_rows(50)
    t = RecordsTable()
    t.set_records(cols, rows)
    qtbot.addWidget(t)
    model = t.model()
    carved_row = next(r for r in range(model.rowCount())
                       if model.data(model.index(r, 0), ROLE_IS_CARVED))
    live_row = next(r for r in range(model.rowCount())
                     if not model.data(model.index(r, 0), ROLE_IS_CARVED))

    t._copy_row(carved_row)
    assert (model.row_at(carved_row)["Origin"]
            in QGuiApplication.clipboard().text().split("\t"))

    t._copy_row(live_row)
    assert (model.row_at(live_row)["Origin"]
            not in QGuiApplication.clipboard().text().split("\t"))


def test_copy_column_appends_origin_for_every_row_when_any_row_is_carved(table):
    """A consistent shape across every row in the copy, not just the
    carved ones -- so pasted rows still line up (finding 5)."""
    model = table.model()
    offset_col = [c.key for c in FIXTURE_COLUMNS].index("Offset")
    assert any(model.data(model.index(r, 0), ROLE_IS_CARVED)
               for r in range(model.rowCount())), "fixture must include a carved row"
    table._copy_column(offset_col)
    lines = QGuiApplication.clipboard().text().split("\n")
    assert all(len(line.split("\t")) == 2 for line in lines)


def test_copy_column_stays_single_field_when_nothing_carved_is_included(table):
    """No format bloat when there is nothing to flag."""
    table.model().set_values("Origin", {"Live record"})
    assert table.model().rowCount() > 0
    offset_col = [c.key for c in FIXTURE_COLUMNS].index("Offset")
    table._copy_column(offset_col)
    lines = QGuiApplication.clipboard().text().split("\n")
    assert all("\t" not in line for line in lines)


def test_ctrl_c_tsv_appends_origin_when_any_selected_row_is_carved(table):
    """'whether or not it was selected': the examiner selected only the
    URL cell, not Origin -- the guarantee column shows up anyway
    (finding 5)."""
    model = table.model()
    url_col = [c.key for c in FIXTURE_COLUMNS].index("CleanUrl")
    carved_row = next(r for r in range(model.rowCount())
                       if model.data(model.index(r, 0), ROLE_IS_CARVED))
    table.clearSelection()
    table.selectionModel().select(model.index(carved_row, url_col),
                                   QItemSelectionModel.Select)
    tsv = table.copy_selection_as_tsv()
    lines = tsv.splitlines()
    assert lines[0].split("\t")[-1] == "Origin (carved)"
    assert lines[1].split("\t")[-1] == model.row_at(carved_row)["Origin"]


def test_ctrl_c_tsv_omits_origin_column_when_nothing_selected_is_carved(table):
    model = table.model()
    url_col = [c.key for c in FIXTURE_COLUMNS].index("CleanUrl")
    live_row = next(r for r in range(model.rowCount())
                     if not model.data(model.index(r, 0), ROLE_IS_CARVED))
    table.clearSelection()
    table.selectionModel().select(model.index(live_row, url_col),
                                   QItemSelectionModel.Select)
    tsv = table.copy_selection_as_tsv()
    assert "Origin" not in tsv.splitlines()[0]


def test_tsv_escapes_embedded_tabs_and_newlines(qtbot):
    """A Title or CleanUrl containing a literal tab/newline/CR -- plausible
    in a carved record, per fixtures.py's own docstring -- must not
    silently shift columns or split a row when pasted into Excel
    (finding 2)."""
    rows = make_rows(5)
    rows[0]["Title"] = "one\ttwo\nthree\rfour"
    rows[0]["Origin"] = "Live record"  # isolate this test from finding 5's
    t = RecordsTable()                 # Origin-append behaviour
    t.set_records(list(FIXTURE_COLUMNS), rows)
    qtbot.addWidget(t)
    t.selectRow(0)
    tsv = t.copy_selection_as_tsv()
    lines = tsv.splitlines()
    assert len(lines) == 2, "an unescaped newline/CR split the data row in two"
    assert len(lines[1].split("\t")) == len(FIXTURE_COLUMNS), \
        "an unescaped tab shifted a column"
    assert "one two three four" in tsv


def test_tsv_blanks_cells_outside_a_non_contiguous_selection(table):
    """Ctrl-click selects scattered cells; the widget enables non-contiguous
    selection (SelectItems + ExtendedSelection). A rectangular TSV export
    must not silently include cells the examiner never selected
    (finding 3)."""
    model = table.model()
    url_col = [c.key for c in FIXTURE_COLUMNS].index("CleanUrl")
    visits_col = [c.key for c in FIXTURE_COLUMNS].index("VisitCount")
    sel = table.selectionModel()
    table.clearSelection()
    sel.select(model.index(0, url_col), QItemSelectionModel.Select)
    sel.select(model.index(1, visits_col), QItemSelectionModel.Select)
    tsv = table.copy_selection_as_tsv()
    lines = tsv.splitlines()
    header = lines[0].split("\t")
    row0 = lines[1].split("\t")
    row1 = lines[2].split("\t")
    # row 0's VisitCount cell and row 1's CleanUrl cell were never selected
    assert row0[header.index("Visits")] == ""
    assert row1[header.index("Address")] == ""
    # the cells that WERE selected still come through
    assert row0[header.index("Address")] == str(model.row_at(0)["CleanUrl"])
    assert row1[header.index("Visits")] == str(model.row_at(1)["VisitCount"])


# --- Origin guarantee must not duplicate a column the view already has ----

def test_copy_row_does_not_duplicate_origin_when_the_view_already_declares_it(table):
    """FIXTURE_COLUMNS (like History's own COLUMNS) already declares an
    "Origin" column, so a bare row dump already carries the value once. The
    unconditional append used to tack it on a second time with no label to
    say why -- redundant, not a disclosure risk (the two values always
    agree), but sloppy in an artefact meant for a report."""
    model = table.model()
    origin_col = [c.key for c in FIXTURE_COLUMNS].index("Origin")
    carved_row = next(r for r in range(model.rowCount())
                       if model.data(model.index(r, 0), ROLE_IS_CARVED))
    table._copy_row(carved_row)
    values = QGuiApplication.clipboard().text().split("\t")
    origin_value = str(model.row_at(carved_row)["Origin"])
    assert values[origin_col] == origin_value
    assert values.count(origin_value) == 1


def test_copy_column_does_not_duplicate_origin_when_copying_the_origin_column_itself(table):
    """Copying the Origin column on a carved row must not tack its own
    value onto the line a second time."""
    model = table.model()
    origin_col = [c.key for c in FIXTURE_COLUMNS].index("Origin")
    assert any(model.data(model.index(r, 0), ROLE_IS_CARVED)
               for r in range(model.rowCount())), "fixture must include a carved row"
    table._copy_column(origin_col)
    lines = QGuiApplication.clipboard().text().split("\n")
    assert all("\t" not in line for line in lines)


def test_copy_column_still_appends_origin_for_a_different_carved_column(table):
    """The guard is scoped to copying Origin itself -- copying any OTHER
    column on a row set that includes carved rows must still get the
    guarantee, exactly as before this fix (finding 5 is unaffected)."""
    model = table.model()
    offset_col = [c.key for c in FIXTURE_COLUMNS].index("Offset")
    table._copy_column(offset_col)
    lines = QGuiApplication.clipboard().text().split("\n")
    assert all(len(line.split("\t")) == 2 for line in lines)


# --- header basis badges (_ProvenanceHeaderView) ---------------------------

def _badge_columns(width=460):
    """Two columns, one carrying a resolved badge (as history.py would set
    it after annotating from evidence_model.basis_of()), one with no
    `field` at all -- a plain fixture-shaped Column, so this exercises the
    same "nothing set it, so nothing paints" path FIXTURE_COLUMNS already
    relies on."""
    address = Column("CleanUrl", "Address", width, kind="url", field="CleanUrl")
    address.badge = "DER"
    address.badge_tooltip = "DER (Derived) — computed by this tool from observed values."
    title = Column("Title", "Title", 240, kind="text")
    return [address, title]


def test_a_column_with_no_field_paints_no_badge(qtbot):
    cols = _badge_columns()
    t = RecordsTable()
    t.set_records(cols, make_rows(5))
    qtbot.addWidget(t)
    assert cols[1].show_badge is False
    assert cols[1].badge is None


def test_a_wide_badge_column_gets_a_chip_that_stays_inside_the_section(qtbot):
    cols = _badge_columns(width=460)
    t = RecordsTable()
    t.set_records(cols, make_rows(5))
    qtbot.addWidget(t)
    header = t.horizontalHeader()
    header.resizeSection(0, 460)
    rect = QRectF(0, 0, header.sectionSize(0), header.height())
    chip = header._chip_rect(rect, cols[0].badge)
    assert chip is not None
    assert chip.left() >= rect.left()
    assert chip.right() <= rect.right() - header.RESERVED_RIGHT_PX + 0.01
    assert chip.top() >= rect.top() and chip.bottom() <= rect.bottom()


def test_the_badge_never_overlaps_a_section_too_narrow_to_hold_it(qtbot):
    """"Never overlap" wins over "always show" -- see _ProvenanceHeaderView's
    own docstring. A section with barely enough room for the label and
    none for RESERVED_RIGHT_PX + the chip must simply omit the badge."""
    cols = _badge_columns()
    t = RecordsTable()
    t.set_records(cols, make_rows(5))
    qtbot.addWidget(t)
    header = t.horizontalHeader()
    tiny = QRectF(0, 0, 24, header.height())
    assert header._chip_rect(tiny, cols[0].badge) is None


def test_the_heading_floor_reserves_room_for_the_badge():
    """_enforce_heading_floor must reserve enough width for
    _ProvenanceHeaderView.paintSection to never have to cut into the label
    -- otherwise a narrow badge-bearing column (Visits, 70px in
    HistoryView.COLUMNS) could load at a width with nowhere honest to put
    the chip. Doubled, not single: Qt's own header alignment is CENTRED
    (verified directly -- QHeaderView.defaultAlignment() ==
    AlignHCenter|AlignVCenter), so half the label sits on EACH side of the
    section's midpoint, and only the right half needs to clear the badge --
    the same allowance has to be mirrored to keep that half clear too."""
    col = Column("VisitCount", "Visits", 20, kind="num", field="VisitCount")
    col.badge = "DER"
    t = RecordsTable()
    t.set_records([col], make_rows(5))
    header = t.horizontalHeader()
    reserve = header.badge_width("DER") + header.BADGE_GAP_PX + header.RESERVED_RIGHT_PX
    expected_floor = header.fontMetrics().horizontalAdvance("Visits") + 2 * reserve
    assert header.sectionSize(0) >= expected_floor


def test_the_badge_never_visually_overlaps_the_label_even_at_the_floor(qtbot):
    """The floor above is a best-effort ESTIMATE of what a centred label
    needs; paintSection's own background-repaint (see its docstring) is
    what actually GUARANTEES no overlap regardless of font/style. Proven
    here at the label's OWN worst case -- a column resized to exactly the
    computed floor -- by checking the repainted erase zone reaches every
    pixel _chip_rect claims for the chip: if it did not, a stray label
    pixel could still show through under the badge."""
    col = Column("AccessedUtc", "Last visit (UTC)", 20, kind="time",
                field="AccessedUtc")
    col.badge = "DER"
    t = RecordsTable()
    t.set_records([col], make_rows(5))
    qtbot.addWidget(t)
    header = t.horizontalHeader()
    rect = QRectF(0, 0, header.sectionSize(0), header.height())
    chip = header._chip_rect(rect, col.badge)
    assert chip is not None
    # The erase zone paintSection repaints starts to the LEFT of the chip
    # (BADGE_GAP_PX further out) and reaches the chip's own right edge +
    # RESERVED_RIGHT_PX -- i.e. it fully contains the chip with margin on
    # both sides, so nothing painted before it (the label) can still be
    # showing at the chip's own boundary.
    erase_left = rect.right() - header.RESERVED_RIGHT_PX - chip.width() - header.BADGE_GAP_PX
    assert erase_left <= chip.left()
    assert rect.right() - header.RESERVED_RIGHT_PX >= chip.right() - 0.5


def test_a_column_with_a_badge_but_no_field_still_paints_nothing():
    """show_badge is driven by `field`, not by `badge` alone -- a Column
    nobody annotated correctly (field is None) must never paint a stray
    chip just because .badge happens to be set."""
    col = Column("Title", "Title", 240, kind="text")
    col.badge = "DER"  # deliberately inconsistent: no field, but a badge
    assert col.show_badge is False


def test_hovering_the_badge_shows_its_tooltip_and_elsewhere_does_not(qtbot):
    cols = _badge_columns(width=460)
    t = RecordsTable()
    t.set_records(cols, make_rows(5))
    qtbot.addWidget(t)
    t.resize(900, 400)
    t.show()
    qtbot.waitExposed(t)
    header = t.horizontalHeader()
    header.resizeSection(0, 460)
    rect = QRectF(0, 0, header.sectionSize(0), header.height())
    chip = header._chip_rect(rect, cols[0].badge)
    assert chip is not None

    on_badge = chip.center().toPoint()
    ev = QHelpEvent(QEvent.ToolTip, on_badge, header.mapToGlobal(on_badge))
    assert header.event(ev) is True
    assert QToolTip.text() == cols[0].badge_tooltip

    # Elsewhere in the SAME section (far from the chip): the hit-test
    # rectangle itself must exclude it -- checked directly against the
    # geometry _ProvenanceHeaderView.event() actually consults, rather than
    # QToolTip's global text() after hideText(), which offscreen/headless
    # Qt does not reliably clear (verified directly: it keeps reporting the
    # last shown text regardless), making it useless as a "did NOT show"
    # signal in this test environment.
    off_badge = QPointF(4, 4)  # inside the section, nowhere near the chip
    assert not chip.contains(off_badge)


# --- the bar column's delegate -------------------------------------------
#
# One delegate instance, held by the table, applied per COLUMN INDEX and
# cleared per column index on every set_records -- because a segment
# switch can move which index is the bar, or remove it entirely.

_BAR_COLUMNS = [Column("Period", "Period", 120, kind="text"),
                Column("Share", "Relative volume", 190, kind="bar")]
_NO_BAR_COLUMNS = [Column("Share", "Share", 190, kind="num"),
                   Column("Period", "Period", 120, kind="text")]
_BAR_ROWS = [{"Period": "2024-06-15", "Share": 1.0},
             {"Period": "2024-06-16", "Share": 0.25}]


def test_a_bar_column_gets_the_share_bar_delegate(qtbot):
    from webcache.widgets.bar_delegate import ShareBarDelegate

    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records(list(_BAR_COLUMNS), list(_BAR_ROWS))
    assert isinstance(t.itemDelegateForColumn(1), ShareBarDelegate)


def test_a_non_bar_column_has_no_share_bar_delegate(qtbot):
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records(list(_BAR_COLUMNS), list(_BAR_ROWS))
    assert t.itemDelegateForColumn(0) is None


def test_the_delegate_is_cleared_when_the_columns_no_longer_hold_a_bar(qtbot):
    """A segment switch rebuilds the model with entirely different
    columns. Left in place, the delegate would go on painting a bar over
    whatever value now sits at that index -- the same class of failure the
    base's own scroll reset and filter clear exist to prevent."""
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records(list(_BAR_COLUMNS), list(_BAR_ROWS))
    t.set_records(list(_NO_BAR_COLUMNS), list(_BAR_ROWS))
    assert t.itemDelegateForColumn(0) is None
    assert t.itemDelegateForColumn(1) is None


def test_the_table_holds_one_delegate_instance_across_renders(qtbot):
    """Held as an attribute so Python cannot collect it out from under Qt
    -- the same reason _filter_popup is an attribute and not a local."""
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records(list(_BAR_COLUMNS), list(_BAR_ROWS))
    first = t.itemDelegateForColumn(1)
    t.set_records(list(_BAR_COLUMNS), list(_BAR_ROWS))
    assert t.itemDelegateForColumn(1) is first


# --- the floor must measure the font the header actually PAINTS -----------
#
# theme.py's QSS carries `QHeaderView::section { font-weight: 600 }`, so a
# heading is drawn semibold. _enforce_heading_floor sized it from
# header.fontMetrics(), which is the WIDGET's font -- regular weight. Every
# heading was therefore reserved 3-5 px less room than it needs, in the one
# method whose own comment says reusing the same constants the painter uses
# "is what keeps the floor and the paint logic from silently drifting
# apart".
#
# The margin absorbed it, so nothing was visibly clipped in the shipping
# configuration -- this closes the underestimate rather than a symptom.

def test_the_heading_floor_measures_the_weight_the_qss_paints(qtbot):
    """The floor must size from painted_font(), not the widget's own.

    Asserting "semibold is wider" directly does NOT work here: this
    environment has no font directory (QFontDatabase warns about it), so
    Segoe UI is absent and the fallback reports identical advances for
    both weights -- 192.0 == 192.0. A width assertion would pass
    vacuously on a machine that has the font and fail confusingly on one
    that does not.

    So this drives the wiring instead: hand the header a painted_font()
    that is unmistakably wider and check the floor grows with it. That
    holds on any font, and it is the actual contract -- the floor reads
    the painter's font rather than the widget's.
    """
    from PySide6.QtGui import QFont
    from webcache.widgets.column_spec import Column
    from webcache.widgets.records_table import RecordsTable

    table = RecordsTable()
    qtbot.addWidget(table)
    header = table.horizontalHeader()
    assert header.painted_font().weight() == QFont.Weight.DemiBold, (
        "painted_font() does not carry the weight the QSS paints")

    col = Column("K", "Last visit (UTC)", 60, kind="text", field="AccessedTime")
    col.badge, col.badge_tooltip = "DER", "Derived"
    table.set_records([col], [{"K": "x"}])
    narrow = header.sectionSize(0)

    huge = QFont(header.font())
    huge.setPointSizeF(header.font().pointSizeF() * 4)
    header.painted_font = lambda: huge
    table.set_records([col], [{"K": "x"}])
    assert header.sectionSize(0) > narrow, (
        "the floor did not grow with painted_font (%d -> %d), so it is "
        "still sizing from the widget font"
        % (narrow, header.sectionSize(0)))


# --- do not measure content nobody asked to be measured -------------------
#
# _fit_columns called resizeColumnsToContents() unconditionally. That asks
# the model for every cell of every row so Qt can find the widest content --
# then the loop right after it overrides the result with `col.width` for
# every column that declares one.
#
# Measured on the real application, first click on File Access with an 854
# row exhibit: 966 ms, of which _fit_columns was 1.078 s of a 1.103 s build
# and record_model.data() was called 75,866 times. File Access declares a
# width for all sixteen of its columns, so every one of those calls was
# discarded. History, holding MORE rows (927), renders in 40 ms.
#
# Only two views have any width=None column at all (cookies and search, two
# each), and those must keep working -- hence the second test.

def test_a_table_whose_columns_all_declare_widths_measures_no_content(qtbot):
    from webcache.widgets.column_spec import Column
    from webcache.widgets.records_table import RecordsTable

    table = RecordsTable()
    qtbot.addWidget(table)
    calls = []
    table.resizeColumnsToContents = lambda *a, **k: calls.append(1)

    cols = [Column("A", "Alpha", 120, kind="text"),
            Column("B", "Beta", 90, kind="num")]
    table.set_records(cols, [{"A": "x" * 80, "B": i} for i in range(500)])

    assert calls == [], (
        "resizeColumnsToContents ran %d time(s) even though every column "
        "declares a width, so every measurement is discarded" % len(calls))
    hdr = table.horizontalHeader()
    assert hdr.sectionSize(0) >= 120 and hdr.sectionSize(1) >= 90, (
        "declared widths were not applied")


def test_a_column_without_a_width_is_still_sized_from_its_content(qtbot):
    """The two views that rely on this must not regress."""
    from webcache.widgets.column_spec import Column
    from webcache.widgets.records_table import RecordsTable

    table = RecordsTable()
    qtbot.addWidget(table)
    cols = [Column("A", "Alpha", 120, kind="text"),
            Column("B", "Beta", None, kind="text")]
    table.set_records(cols, [{"A": "x", "B": "a value long enough to matter"}
                             for _ in range(50)])
    hdr = table.horizontalHeader()
    assert hdr.sectionSize(1) > 60, (
        "the width=None column collapsed to %d px instead of being sized "
        "from its content" % hdr.sectionSize(1))
