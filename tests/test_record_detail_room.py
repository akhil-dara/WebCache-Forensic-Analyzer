"""Room: how the record detail dialog divides the space it has.

WHY A SECOND DIALOG FILE. test_record_detail_dialog.py tests what the
dialog SAYS -- that no cell is blank, that a carved record says so four
ways, that a copy reports failure instead of claiming success. This file
tests what the dialog GIVES: how many field rows an examiner can actually
see, whether a button is drawn at the height it needs, and whether the
half of the window that is the record keeps the majority of it.

THE MEASUREMENT PROBLEM THIS FILE SOLVES. Every number here was first
measured wrong. Offscreen, with no stylesheet, a QPushButton hints at
under 30px and a field row is 25px tall -- so "nothing is clipped" and
"seven rows fit" both read as verified on a window where nothing fits and
everything is clipped. Two habits fix it, and both are load-bearing:

  * apply the real theme stylesheet (the `themed` fixture), because
    `QPushButton { padding: 7px 16px }` is where a button's real height
    comes from; and

  * where a property must hold at ANY font, inflate the application font
    (the `big_font` fixture) so a hard-coded pixel constant is smaller
    than what the widget needs on every platform, rather than only on the
    examiner's.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication,
                               QPushButton, QWidget)

from webcache.shell import record_detail, theme
from webcache.shell.record_detail import RecordDetailDialog

from tests.test_detail_fields import cert_row, cookie_row, history_row


#: The real window this task was measured against: a 1279x724 dialog off
#: a maximised main window on a 1920x1080 screen at 125% scaling. Written
#: down rather than passed ad hoc, because a claim about how many rows fit
#: is a claim about a SIZE, and one made against a different size is not
#: the same claim.
REAL_W, REAL_H = 1279, 724


@pytest.fixture(autouse=True)
def _settings_go_somewhere_disposable(tmp_path, monkeypatch):
    """No test in this file may touch the real settings.json.

    autouse, not per-test, and not a matter of remembering: this file
    clicks a control that persists a preference, and an earlier draft of
    it wrote `record_detail_blob_open` straight into the checkout's own
    settings.json -- found by looking, in the file, after a run. A
    harness has done worse here before: an 820x360 window geometry saved
    by one went on to be the size the application opened at on the
    examiner's machine.
    """
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")


@pytest.fixture
def themed():
    """The application's own stylesheet, in force for the test.

    Without it, `QPushButton { padding: 7px 16px }` is not applied and a
    button's sizeHint comes back below the fixed height that clips it on
    the real window -- the test then passes by measuring a window nobody
    uses.

    SUSPECT THE INSTRUMENT. This fixture's first draft restored the
    previous stylesheet on teardown, which looked obviously correct and
    quietly broke every test after the first one in this file:
    theme.apply() is a deliberate no-op when its module-level `_current`
    and `_last_applied_app` already name the app and theme being asked
    for, so stripping the stylesheet while leaving those two untouched
    left the next apply() with nothing to do and the window unstyled. The
    split then measured 37/63 in an unstyled window while the same code
    measured 95/5 in a styled one. Both halves of the guard are put back
    here, so the next apply() is a real one.
    """
    app = QApplication.instance()
    sheet, current, owner = (app.styleSheet(), theme._current,
                             theme._last_applied_app)
    theme.apply(app, "dark")
    yield app
    app.setStyleSheet(sheet)
    theme._current, theme._last_applied_app = current, owner


@pytest.fixture
def big_font(themed):
    """A deliberately oversized application font.

    Makes every widget's own sizeHint exceed the module's fixed pixel
    constants on EVERY platform, so a test about "the button is drawn at
    the height it needs" fails for the real reason on the offscreen
    platform too, instead of only on the machine whose font happens to be
    large enough.
    """
    app = themed
    before = QFont(app.font())
    bigger = QFont(before)
    bigger.setPointSize(before.pointSize() + 8)
    app.setFont(bigger)
    yield app
    app.setFont(before)


@pytest.fixture
def build(qtbot):
    """A dialog at the real window's size, torn down by hand.

    By hand for the reason test_record_detail_dialog.py's own fixture
    documents: WA_DeleteOnClose destroys the C++ object on close and
    pytest-qt's teardown would then call close() on a dead pointer.
    """
    made = []

    def _build(row, w=REAL_W, h=REAL_H, parent_size=None):
        parent = QWidget()
        made.append(parent)
        parent.resize(*(parent_size or (w + 260, h + 120)))
        parent.show()
        dlg = RecordDetailDialog(row, parent)
        made.append(dlg)
        dlg.resize(w, h)
        dlg.show()
        qtbot.waitExposed(dlg)
        # Twice, with the event loop in between: the first resize lands
        # before the dialog has been laid out, so the splitter's own
        # height is still zero and every size computed from it is
        # computed from nothing.
        dlg.resize(w, h)
        qtbot.wait(20)
        return dlg

    yield _build
    for widget in reversed(made):
        try:
            widget.close()
        except RuntimeError:
            pass


def clipped_buttons(widget):
    """Every button drawn shorter than the height it asks for."""
    return [(b.text(), b.height(), b.sizeHint().height())
            for b in widget.findChildren(QPushButton)
            if b.isVisibleTo(widget) and b.height() + 1 < b.sizeHint().height()]


# --- the button row ----------------------------------------------------

def test_no_button_in_the_blob_pane_is_drawn_shorter_than_it_needs(
        big_font, build):
    """MEASURED, on the real window: seven buttons -- the blob pager's
    first/prev/next/last, Copy hex, Copy strings and Export blob -- were
    given a hard 30px when the style and font needed more, and every one
    of them was clipped.

    A fixed pixel height for a styled button is the defect: the number
    was written against one font at one scaling, and any other makes it
    wrong. The fixture inflates the font so that is true on every
    platform this suite runs on, not only on the examiner's.
    """
    dlg = build(cert_row())
    bad = clipped_buttons(dlg)
    assert bad == [], (
        "%d button(s) are drawn shorter than they need: %s"
        % (len(bad), ", ".join("%r %dpx<%dpx" % b for b in bad)))


# --- the split ---------------------------------------------------------

def visible_field_rows(dlg):
    """How many field rows an examiner can actually see at once.

    Counted by walking the real row heights against the real viewport,
    not by dividing by an average: the rows are ResizeToContents and a
    wrapped value is two or three times the height of a plain one, so an
    average over-reports exactly on the records that are worst affected.
    """
    table, used, seen = dlg.table, 0, 0
    for row in range(table.rowCount()):
        height = table.rowHeight(row)
        if used + height > table.viewport().height():
            break
        used += height
        seen += 1
    return seen


def split_percentages(dlg):
    sizes = dlg._splitter.sizes()
    total = sum(sizes) or 1
    return [round(s * 100.0 / total) for s in sizes]


def test_the_field_list_keeps_the_majority_of_the_split(themed, build):
    """MEASURED, on the real 1279x724 window: [166, 332] -- the record got
    a third of the splitter and the hex viewer got two thirds.

    The proportions were backwards. The fields ARE the dialog; the viewer
    is supporting evidence for the one field that has bytes. This asserts
    the direction, in percentages of the splitter's own height, at the
    size the complaint was made about.
    """
    dlg = build(history_row())
    assert dlg.blob_area is not None, "this fixture is meant to have a blob"
    fields_pct, blob_pct = split_percentages(dlg)
    assert fields_pct > blob_pct, (
        "the blob viewer still takes more of the dialog than the record "
        "does: fields %d%%, viewer %d%% (sizes %s)"
        % (fields_pct, blob_pct, dlg._splitter.sizes()))
    assert fields_pct >= 55, (
        "the field list gets only %d%% of the splitter" % fields_pct)


def test_a_record_with_a_blob_shows_a_usable_number_of_fields(themed, build):
    """MEASURED: 67 fields in a 131px viewport at 33px a row -- about
    three visible at once, out of sixty-seven. That is the complaint.

    A row count rather than a pixel count, because rows are what the
    examiner is short of, and a pixel bound would keep reading as
    satisfied if the row height ever grew.
    """
    dlg = build(history_row())
    seen = visible_field_rows(dlg)
    assert seen >= 12, (
        "only %d of %d rows fit on screen (viewport %dpx)"
        % (seen, dlg.table.rowCount(), dlg.table.viewport().height()))


def test_the_viewer_can_be_folded_away_and_says_what_is_behind_it(
        themed, build):
    """Collapsible, but never to nothing.

    A QSplitter's own setCollapsible would drag the pane to zero pixels
    and leave no trace on screen that the record carries any bytes at
    all -- which in this application is not a layout choice, it is
    hiding evidence. Folded, the region keeps a bar naming the blob and
    its size, so what was put away is still stated.
    """
    dlg = build(history_row())
    region = dlg.blob_region
    assert region is not None

    region.set_expanded(False)
    text = region.toggle_button.text()
    label = dlg.blobs[0].label
    assert label in text, (
        "the folded bar does not name the blob: %r" % text)
    assert "{:,}".format(dlg.blobs[0].size) in text, (
        "the folded bar does not state the size: %r" % text)
    assert not dlg.blob_area.isVisible()

    region.set_expanded(True)
    assert dlg.blob_area.isVisible()


def test_folding_the_viewer_gives_its_room_to_the_fields(themed, build):
    """The point of folding it. Asserted as a real gain in ROWS, because
    a splitter that reports new sizes while the table's viewport did not
    actually grow is exactly the kind of thing that reads as verified."""
    dlg = build(history_row())
    dlg.blob_region.set_expanded(True)
    dlg.resize(REAL_W, REAL_H)
    QApplication.processEvents()
    with_viewer = visible_field_rows(dlg)

    dlg.blob_region.set_expanded(False)
    dlg.resize(REAL_W, REAL_H)
    QApplication.processEvents()
    folded = visible_field_rows(dlg)

    assert folded > with_viewer, (
        "folding the viewer freed no rows (%d before, %d after)"
        % (with_viewer, folded))


def test_a_record_with_no_blob_gives_the_whole_split_to_its_fields(
        themed, build):
    """The case an inverted ratio would get wrong.

    Most records carry no bytes at all. Anything expressed as "the
    viewer gets N%" has to mean "of a dialog that HAS a viewer" -- a
    cookie has no second pane, no fold bar and nothing to divide, and
    its field list is the whole surface.
    """
    dlg = build(cookie_row())
    assert dlg.blob_area is None
    assert dlg.blob_region is None
    assert dlg._splitter.count() == 1
    assert visible_field_rows(dlg) == dlg.table.rowCount(), (
        "a record with no blob should show every one of its rows at this "
        "size")


def test_the_fold_is_remembered_for_the_next_record(themed, build, tmp_path):
    """Remembered, so an examiner who works in the bytes sets it once.

    Written to settings only on a DELIBERATE toggle -- see the dialog's
    own note. A dialog that merely opened and closed must not write the
    file at all, which is why this test asserts the file does not exist
    until the toggle happens.
    """
    path = tmp_path / "settings.json"   # where the autouse fixture points

    first = build(history_row())
    assert not path.exists(), (
        "opening a record wrote the settings file without being asked")

    first.blob_region.toggle_button.click()
    wanted = first.blob_region.is_expanded()
    assert path.exists(), "the toggle was not remembered"

    second = build(history_row())
    assert second.blob_region.is_expanded() == wanted


def test_opening_a_binary_field_unfolds_the_viewer(themed, build):
    """Otherwise the one route to the bytes leads to a folded pane.

    activate_field already switches to the blob's tab; with the region
    folded that switched a tab nobody could see, and the status line
    said "Showing ... in the tab below" about a tab that was not below
    anything.
    """
    dlg = build(history_row())
    dlg.blob_region.set_expanded(False)
    for row in range(dlg.table.rowCount()):
        field = dlg.field_at(row)
        if field is not None and field.blob_key:
            dlg.activate_field(dlg._field_index(row))
            break
    else:
        raise AssertionError("no blob-bearing field in this fixture")
    assert dlg.blob_region.is_expanded(), (
        "opening a Binary field left the viewer folded")


# --- the header --------------------------------------------------------

def _top_left_in(widget, dlg):
    return widget.mapTo(dlg, widget.rect().topLeft())


def test_the_title_is_not_flush_against_the_top_of_the_dialog(themed, build):
    """MEASURED: contentsMargins were 11px all round and the identity line
    sat at (11, 11) -- against the window edge, under the title bar, with
    nothing between the chrome and the record's own name.

    Eleven pixels is what a QDialog gets when nobody has decided. This
    asserts that somebody has: a heading needs more room above it than
    the gap between two ordinary rows, and it is the first thing an
    examiner reads.
    """
    dlg = build(history_row())
    top = _top_left_in(dlg.identity_label, dlg)
    assert top.y() >= 16, (
        "the record's title sits %dpx from the top edge" % top.y())
    assert top.x() >= 14, (
        "the record's title sits %dpx from the left edge" % top.x())


def test_the_header_is_separated_from_the_controls_under_it(themed, build):
    """MEASURED: 7px between the origin line and the toolbar -- less than
    the 11px margin around them, so the record's identity read as part of
    the button row rather than as the heading above it."""
    dlg = build(history_row())
    origin_bottom = dlg.origin_label.mapTo(
        dlg, dlg.origin_label.rect().bottomLeft()).y()
    toolbar_top = _top_left_in(dlg.copy_all_button, dlg).y()
    assert toolbar_top - origin_bottom >= 12, (
        "only %dpx between the record's identity and the buttons under it"
        % (toolbar_top - origin_bottom))


# --- copy --------------------------------------------------------------

def field_row(dlg, label):
    for row in range(dlg.table.rowCount()):
        field = dlg.field_at(row)
        if field is not None and field.label == label:
            return row
    raise AssertionError("no %r row in this record" % label)


def captured_copy(dlg, monkeypatch):
    """What the dialog put on the clipboard, without using the real one.

    The Windows clipboard can be held by another application -- three
    checks in this project's older suite already SKIP for it -- and what
    is under test here is WHICH text a key press routes to, not whether
    the platform accepted it.
    """
    box = []

    def _set(text):
        box.append(text)
        return True

    monkeypatch.setattr(dlg, "_set_clipboard", _set)
    return box


def test_ctrl_c_copies_the_value_its_own_menu_says_it_copies(
        themed, build, monkeypatch):
    """THE COPY COMPLAINT, and the concrete defect under it.

    The field menu's first entry reads "Copy value    Ctrl+C" and calls
    copy_field(), which is byte-exact and undecorated. Ctrl+C called
    _copy_selection(), which composes "Clean URL: https://example.test/a"
    -- so the accelerator printed beside an action did something else,
    and an examiner who pressed it and pasted got this tool's label glued
    to the front of the evidence. Cleaning that up by hand, every time,
    is what "copy proper thing not there at all" describes.

    One row selected: the value, exactly as stored.
    """
    dlg = build(history_row())
    row = field_row(dlg, "Clean URL")
    dlg.table.setCurrentCell(row, 1)
    dlg.table.clearSelection()
    dlg.table.selectRow(row)
    copied = captured_copy(dlg, monkeypatch)

    dlg.keyPressEvent(_ctrl_c())

    assert copied == ["https://example.test/a"], (
        "Ctrl+C did not copy the value its own menu advertises: %r"
        % (copied,))


def test_ctrl_c_across_several_rows_still_names_each_field(
        themed, build, monkeypatch):
    """The other half, unchanged and deliberately so. Several values with
    no labels is a column of text nobody can attribute -- the labels earn
    their place the moment there is more than one."""
    dlg = build(history_row())
    first, second = field_row(dlg, "Clean URL"), field_row(dlg, "Domain")
    # MultiSelection off QAbstractItemView, not off the QTableWidget:
    # PySide6 does not re-export the enum on the concrete class, and
    # reaching for it there raises an AttributeError that looks exactly
    # like a dead handler in the code under test.
    dlg.table.setSelectionMode(QAbstractItemView.MultiSelection)
    dlg.table.clearSelection()
    dlg.table.selectRow(first)
    dlg.table.selectRow(second)
    copied = captured_copy(dlg, monkeypatch)

    dlg.keyPressEvent(_ctrl_c())

    assert copied, "Ctrl+C copied nothing at all"
    assert "Clean URL:" in copied[0] and "Domain:" in copied[0], (
        "a multi-row copy dropped the labels: %r" % copied[0])


def test_a_visible_control_copies_the_selected_field(themed, build,
                                                     monkeypatch):
    """The affordance that was missing.

    Per-field copy existed three ways -- right-click, Ctrl+C, Enter --
    and NONE of them is visible. The toolbar offered "Copy all fields"
    and "Copy as TSV", so the only copy an examiner could SEE copied
    sixty-seven fields when they wanted one. A capability with no route
    to it is indistinguishable from one that does not exist, and here
    there were three routes and no sign of any of them.
    """
    dlg = build(history_row())
    assert dlg.copy_field_button is not None
    assert dlg.copy_field_button.isVisibleTo(dlg)
    # A WIDTH, not just isVisibleTo. Found by looking at a screenshot:
    # the button was given QSizePolicy.Ignored, the toolbar row ends in
    # addStretch(1), and the layout handed it 0px -- so it was laid out
    # with an empty label, reported visible and enabled by every check
    # here, and was not on the screen at all. isVisibleTo answers "would
    # this be shown if its parents were", which is not the question.
    assert dlg.copy_field_button.width() >= 40, (
        "the copy control is %dpx wide -- present in the tree and not on "
        "the screen" % dlg.copy_field_button.width())
    assert dlg.copy_field_button.text(), (
        "the copy control has no visible label")

    row = field_row(dlg, "Clean URL")
    dlg.table.clearSelection()
    dlg.table.selectRow(row)
    dlg.table.setCurrentCell(row, 1)
    copied = captured_copy(dlg, monkeypatch)
    dlg.copy_field_button.click()

    assert copied == ["https://example.test/a"]


def test_the_visible_copy_control_names_the_field_it_will_copy(themed, build):
    """A button reading only "Copy field" beside "Copy all fields" is one
    more thing to guess at. Its tooltip names the field the click will
    act on, and it is disabled outright where there is nothing to act
    on -- a heading row copies nothing, and a button that looks live and
    does nothing is worse than one that is plainly not."""
    dlg = build(history_row())
    row = field_row(dlg, "Clean URL")
    dlg.table.clearSelection()
    dlg.table.selectRow(row)
    dlg.table.setCurrentCell(row, 1)
    assert dlg.copy_field_button.isEnabled()
    assert "Clean URL" in dlg.copy_field_button.toolTip()

    heading = next(r for r in range(dlg.table.rowCount())
                   if dlg.is_heading_row(r))
    dlg.table.clearSelection()
    dlg.table.setCurrentCell(heading, 0)
    assert not dlg.copy_field_button.isEnabled()


def test_a_copy_is_confirmed_where_the_examiner_is_looking(themed, build):
    """MEASURED: the status line was drawn at y=659 of a 724px dialog --
    under the splitter, beside the Close button, three hundred pixels
    below the row that was just copied. A confirmation nobody sees is a
    copy an examiner repeats because they cannot tell whether it worked.

    It moves up beside the count line, which is the sentence they already
    read, and gives its old row back to the field list.
    """
    dlg = build(history_row())
    status_y = _top_left_in(dlg.status_label, dlg).y()
    splitter_y = _top_left_in(dlg._splitter, dlg).y()
    assert status_y < splitter_y, (
        "the copy confirmation is still below the field list (status at "
        "y=%d, list starts at y=%d)" % (status_y, splitter_y))


def _ctrl_c():
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    return QKeyEvent(QEvent.KeyPress, Qt.Key_C, Qt.ControlModifier)


# --- opening the viewer on a short dialog ------------------------------

def test_opening_the_viewer_grows_the_dialog_rather_than_crushing_the_record(
        themed, build):
    """MEASURED, after the fold landed: clicking the bar open on the real
    1279x724 window split it [167, 366] -- the viewer at its minimum and
    the record down to FOUR rows, which is the complaint this whole task
    started from, reappearing the moment the bytes are asked for.

    The examiner asked to see the bytes. They did not ask to be left with
    four field rows, and there is room on the screen: the window was
    724px tall on an 816px-high work area. So the dialog takes the room
    that is there, which is exactly what a person would do by hand, up to
    the edge of the screen and no further.
    """
    dlg = build(history_row())
    assert not dlg.blob_region.is_expanded(), (
        "this fixture is meant to open folded at this size")
    before = dlg.height()
    available = record_detail.screen_room(dlg).height()
    assert before < available - 40, (
        "no headroom on this screen to test growing into (%dpx of %dpx)"
        % (before, available))

    dlg.blob_region.toggle_button.click()
    QApplication.processEvents()

    assert dlg.height() > before, (
        "opening the viewer left the dialog at %dpx with %dpx of screen "
        "going spare" % (dlg.height(), available))
    assert dlg.height() <= available, (
        "the dialog grew past the edge of the screen (%dpx of %dpx)"
        % (dlg.height(), available))
    fields_px, _blob_px = dlg._splitter.sizes()
    assert fields_px >= record_detail._FIELDS_FLOOR_PX, (
        "the record still gets only %dpx with the viewer open" % fields_px)


def test_folding_the_viewer_again_does_not_shrink_the_dialog(themed, build):
    """A window that resizes itself when a pane is folded is a window
    arguing with the person using it. Growing to make room is a courtesy;
    taking the room back is not the same thing, because by then the size
    may be the one the examiner wants."""
    dlg = build(history_row())
    dlg.blob_region.toggle_button.click()
    QApplication.processEvents()
    grown = dlg.height()

    dlg.blob_region.toggle_button.click()
    QApplication.processEvents()

    assert dlg.height() == grown


# --- and the copy button, on open ------------------------------------------
#
# The room work put "Copy field" first in the toolbar and routed
# single-row Ctrl+C through it. A screenshot of the real application
# against a real exhibit then showed it GREYED on open, because nothing
# is selected until the examiner clicks -- the same complaint that
# started this work, surviving the fix that was meant to answer it. A
# disabled button says the action is unavailable for this record, which
# is a stronger and wronger claim than saying nothing at all.


def test_a_field_is_selected_as_soon_as_the_record_dialog_opens(themed, build):
    dlg = build(history_row())
    assert dlg.field_at(dlg.table.currentRow()) is not None


def test_the_copy_field_button_is_usable_before_any_click(themed, build):
    dlg = build(history_row())
    assert dlg.copy_field_button.isEnabled()


def test_the_selection_lands_on_a_field_not_on_a_section_heading(themed, build):
    """The first row of this table is a heading ("WHAT THIS RECORD IS"),
    which is not a field and has nothing to copy."""
    dlg = build(history_row())
    assert dlg._rows[dlg.table.currentRow()] is not None
