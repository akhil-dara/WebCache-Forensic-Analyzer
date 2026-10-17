"""The dialog: what is on screen, and what a copy of it says.

detail_fields.py decides which fields and what wording, and is tested with
no Qt at all (tests/test_detail_fields.py). This file tests only what
painting them adds: that no cell is blank, that a carved record says so in
four independent ways, that filtering announces what it hid, that every
copy path reports failure instead of claiming success, and that opening a
record from an aggregate really opens it.

The single most important assertion here is
test_no_field_row_renders_an_empty_value_cell. A blank cell in this dialog
would say "the database stored nothing", "this cannot be known", "our
carve missed it" and "this field does not apply" with the same zero
pixels, which is the failure the whole absence vocabulary exists to
prevent -- and it is the one that can be reintroduced by a rendering
change with detail_fields.py left untouched.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTableWidget

from webcache import provenance
from webcache.shell import detail_fields as df
from webcache.shell import record_detail
from webcache.shell.record_detail import RecordDetailDialog
from webcache.widgets import hex_view
from webcache.widgets.record_model import CARVED_ROW_TOOLTIP, foreground

from tests.test_detail_fields import (ALL_ROWS, carved_string_row,
                                      carved_struct_row, cert_row,
                                      cookie_row, domain_row, history_row)


@pytest.fixture
def dialog(qtbot):
    """Builds dialogs and tears them down BY HAND.

    Deliberately not qtbot.addWidget: the dialog sets WA_DeleteOnClose, so
    Qt destroys the C++ object the moment it closes, and pytest-qt's own
    teardown then calls close() on a dead pointer -- "libshiboken:
    Internal C++ object already deleted". Every test here that closes a
    dialog would fail in teardown having passed. MainWindow's own registry
    has the same problem and solves it the same way, by tolerating a
    reference whose C++ half is already gone.
    """
    built = []

    def build(row):
        d = RecordDetailDialog(row)
        built.append(d)
        d.show()
        qtbot.waitExposed(d)
        # activateWindow() before any keyboard test, exactly as
        # test_records_view.py already does for its own Ctrl+F/Escape
        # pair: a QShortcut with the default WindowShortcut context is
        # matched against the ACTIVE window, and the offscreen platform
        # does not activate one just because it was shown.
        d.activateWindow()
        # The wait is not padding. Activation needs an event-loop turn
        # even offscreen, and hasFocus() stays False on a widget whose
        # window is not yet active -- so Ctrl+F reads as broken while
        # having called setFocus() perfectly correctly. Verified: without
        # it, QApplication.activeWindow() is still None here.
        # test_records_view.py's own Ctrl+F test does exactly this.
        qtbot.wait(50)
        d.table.setFocus()
        return d

    yield build
    for d in built:
        try:
            d.close()
        except RuntimeError:
            pass
    # Let the deferred deletions actually run before the next test builds
    # a dialog and calls activateWindow(): a half-destroyed window still
    # counts as the active one, and the next test's Ctrl+F then matches
    # against it instead.
    qtbot.wait(1)


def _value_items(dlg):
    """Every VALUE cell that is not a group heading."""
    out = []
    for r in range(dlg.table.rowCount()):
        if dlg.is_heading_row(r):
            continue
        item = dlg.table.item(r, 1)
        if item is not None:
            out.append(item)
    return out


# --- the blank-cell guarantee -------------------------------------------

@pytest.mark.parametrize("name,builder", ALL_ROWS)
def test_no_field_row_renders_an_empty_value_cell(dialog, name, builder):
    dlg = dialog(builder())
    items = _value_items(dlg)
    assert items, name
    for item in items:
        assert item.text().strip(), (name, item.row())


def test_an_absent_value_carries_the_reason_as_its_tooltip(dialog):
    dlg = dialog(history_row())
    absent = [i for i in _value_items(dlg)
              if provenance.is_absence(i.text())]
    assert absent, "the fixture has empty columns; none rendered as absence"
    for item in absent:
        assert provenance.absence_reason(item.text()) in item.toolTip()


def test_a_zero_offset_is_on_screen_as_zero(dialog):
    dlg = dialog(carved_struct_row())
    texts = [i.text() for i in _value_items(dlg)]
    assert any(t.startswith("0 (0x00000000)") for t in texts), texts[:5]


# --- structure ----------------------------------------------------------

def test_the_group_headings_are_spanned_rows_not_fields(dialog):
    dlg = dialog(history_row())
    headings = [r for r in range(dlg.table.rowCount()) if dlg.is_heading_row(r)]
    assert headings
    for r in headings:
        assert dlg.table.columnSpan(r, 0) == 3
    # and they do not inflate the field count the way the earlier version's
    # pseudo-rows did (each carried a copy button that snacked "that
    # field is empty").
    total, _absent = df.counts(dlg.groups)
    assert len(_value_items(dlg)) == total


def test_the_count_line_states_the_total_and_how_many_are_absences(dialog):
    dlg = dialog(history_row())
    total, absent = df.counts(dlg.groups)
    text = dlg.count_label.text()
    assert "{:,}".format(total) in text
    assert str(absent) in text
    assert "nothing truncated" in text


def test_a_record_with_no_blobs_gets_no_empty_blob_pane(dialog):
    """No empty box, and no "(no data)" placeholder, where nothing
    applies."""
    assert dialog(cookie_row()).blob_area is None
    assert dialog(cert_row()).blob_area is not None


def test_the_dialog_is_sized_from_its_parent_not_to_a_fixed_width(qtbot):
    """A fixed 920 is half a maximised screen and forces sideways
    scrolling inside a dialog with half the screen dimmed beside it."""
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(1920, 1080)
    dlg = RecordDetailDialog(history_row(), parent)
    qtbot.addWidget(dlg)
    assert dlg.width() > 920
    assert dlg.width() == max(920, 1920 - 260)


def test_a_small_parent_never_shrinks_the_dialog_below_its_floor(qtbot):
    """PREMISE NARROWED. The 580px floor is the floor for a dialog that
    is only a field list. A record carrying binary data mounts a viewer
    under that list and takes a taller floor -- found by looking, when a
    680px dialog left its splitter 435px to divide between a field table
    and a hex dump and neither fitted. Asserted here on a cookie, which
    has no blobs, and separately below on one that does."""
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(700, 500)
    dlg = RecordDetailDialog(cookie_row(), parent)
    qtbot.addWidget(dlg)
    assert dlg.blob_area is None
    assert dlg.width() == 920 and dlg.height() == 580


def test_a_record_with_a_viewer_takes_a_taller_floor(qtbot):
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(700, 500)
    dlg = RecordDetailDialog(history_row(), parent)
    qtbot.addWidget(dlg)
    assert dlg.blob_area is not None
    assert dlg.height() >= 700


# --- carved: four independent carriers -----------------------------

def test_the_dialog_states_carved_in_words_and_in_its_accessible_name(dialog):
    dlg = dialog(carved_struct_row())
    assert "CARVED RECORD" in dlg.carved_chip.text()
    # Unabbreviated: this surface has no pixel constraint, unlike the
    # grid's one-character vertical-header marker.
    assert CARVED_ROW_TOOLTIP in dlg.carved_chip.toolTip()
    assert CARVED_ROW_TOOLTIP in dlg.accessibleDescription()


def test_a_carved_record_paints_its_values_as_normal_text(dialog):
    dlg = dialog(carved_struct_row())
    # A list, not a set: QColor is unhashable in PySide6.
    carved = [foreground("carved"), foreground("carved_link"),
              foreground("carved_blank")]
    for item in _value_items(dlg):
        assert item.foreground().color() not in carved, item.text()


def test_a_live_record_paints_none_of_its_values_carved(dialog):
    dlg = dialog(history_row())
    assert dlg.carved_chip.isVisible() is False
    for item in _value_items(dlg):
        assert item.foreground().color() != foreground("carved")


def test_a_url_shaped_field_that_opens_nothing_is_not_painted_as_a_link(dialog):
    """The grid (record_model.py) reserves link colour for a cell
    col.is_link actually makes clickable. This dialog painted ANY field
    whose *kind* was url/domain the same colour regardless of whether
    anything here can open it -- Clean URL is real, read-only text with no
    field.target, and nothing in this dialog makes it clickable."""
    dlg = dialog(history_row())
    for r in range(dlg.table.rowCount()):
        if dlg.is_heading_row(r) or dlg.field_at(r).label != "Clean URL":
            continue
        field = dlg.field_at(r)
        assert field.kind == "url"
        assert field.target is None
        item = dlg.table.item(r, 1)
        assert item.foreground().color() != foreground("url")
        return
    raise AssertionError("no Clean URL row")


def test_an_openable_member_row_is_painted_as_a_link(dialog):
    """The other half of the same fix: a row that genuinely opens
    something (field.target is not None) must still get link colour, so
    LOW 9's fix is not "delete the colour", it is "key it off the right
    thing"."""
    dlg = dialog(domain_row())
    for r in range(dlg.table.rowCount()):
        if dlg.is_heading_row(r) or dlg.field_at(r) is None:
            continue
        field = dlg.field_at(r)
        if field.target is None:
            continue
        item = dlg.table.item(r, 1)
        assert item.foreground().color() == foreground("url")
        return
    raise AssertionError("no openable member row found")


def test_the_fields_container_carries_a_carved_border(dialog):
    """A cropped screenshot of the dialog BODY alone still says carved."""
    assert dialog(carved_struct_row()).carved_border_px == 3
    assert dialog(history_row()).carved_border_px == 0


def test_a_damaged_carve_shows_its_banner_above_everything(dialog):
    dlg = dialog(carved_string_row())
    assert dlg.banner is not None
    assert "repairable" in dlg.banner.text()
    assert dlg.groups[0].name == df.G_QUALITY


def test_an_intact_carve_gets_no_banner(dialog):
    assert dialog(carved_struct_row()).banner is None


# --- copy ---------------------------------------------------------------

def test_copy_all_uses_the_displayed_value_so_an_absence_copies_its_words(
        dialog):
    dlg = dialog(history_row())
    text = dlg.copy_all_text()
    assert provenance.ABSENCE_EMPTY in text
    assert "None" not in text.split("\n")


def test_copy_all_includes_group_headings_as_separators(dialog):
    text = dialog(history_row()).copy_all_text()
    assert "— %s —" % df.G_WHEN in text


def test_copy_all_on_a_carved_record_includes_its_provenance(dialog):
    """The one thing byte-exactness does not get to override: a carved
    record pasted into a report with no trace of where it came from is a
    misrepresentation risk -- the same ruling copy_selection_as_tsv
    already makes with its Origin guarantee column."""
    row = carved_struct_row()
    text = dialog(row).copy_all_text()
    assert provenance.describe_origin(row) in text
    assert "CARVED RECORD" in text


def test_copy_all_on_a_live_record_has_no_carved_preamble(dialog):
    assert "CARVED RECORD" not in dialog(history_row()).copy_all_text()


def test_copy_as_tsv_has_a_header_and_three_columns(dialog):
    lines = dialog(history_row()).copy_tsv_text().split("\n")
    assert lines[0] == "Field\tValue\tBasis"
    for line in lines[1:]:
        assert line.count("\t") == 2, line


def test_copy_as_tsv_neutralises_tabs_and_newlines_in_a_value(dialog):
    row = history_row()
    row["_record"]["SomeMultilineValue"] = "a\tb\nc"
    text = dialog(row).copy_tsv_text()
    assert "a\tb\nc" not in text
    assert "a b c" in text


def test_copying_one_field_is_byte_exact_and_undecorated(dialog):
    dlg = dialog(history_row())
    index = [i for i, f in enumerate(df.flatten(dlg.groups))
             if f.label == "Clean URL"][0]
    assert dlg.copy_field(index) is True
    assert QGuiApplication.clipboard().text() == "https://example.test/a"


def test_copying_an_absence_copies_nothing_and_says_so(dialog):
    """Never the literal text "(empty)" into a report, and never a silent
    success either."""
    dlg = dialog(history_row())
    index = [i for i, f in enumerate(df.flatten(dlg.groups))
             if f.absence][0]
    QGuiApplication.clipboard().setText("PREVIOUS")
    assert dlg.copy_field(index) is False
    assert "Nothing to copy" in dlg.status_label.text()
    assert QGuiApplication.clipboard().text() == "PREVIOUS"


def test_copying_a_binary_field_refuses_rather_than_copying_this_tools_summary(
        dialog):
    """Every binary row's value is None; its display_value is a
    summary THIS TOOL composed ("152 bytes ... SHA-256 ..."), not
    something the database stores. copy_field fell back to display_value
    whenever field.value was None, so the context menu's "Copy value" put
    that summary on the clipboard as if it were evidence.
    activate_field's own field.blob_key branch already refuses this exact
    path -- copy_field must refuse it identically."""
    dlg = dialog(history_row())
    fields = df.flatten(dlg.groups)
    index = [i for i, f in enumerate(fields) if f.blob_key][0]
    assert fields[index].value is None
    QGuiApplication.clipboard().setText("PREVIOUS")
    assert dlg.copy_field(index) is False
    assert QGuiApplication.clipboard().text() == "PREVIOUS"


def test_the_field_menu_flags_a_carved_value_in_its_label(dialog):
    dlg = dialog(carved_struct_row())
    menu = dlg.build_field_menu(0)
    assert "carved" in menu.actions()[0].text().lower()


def test_the_field_menu_offers_the_raw_filetime_only_where_there_is_one(dialog):
    dlg = dialog(history_row())
    fields = df.flatten(dlg.groups)
    with_raw = [i for i, f in enumerate(fields) if f.raw_value][0]
    without = [i for i, f in enumerate(fields) if not f.raw_value][0]
    assert any("raw FILETIME" in a.text()
               for a in dlg.build_field_menu(with_raw).actions())
    assert not any("raw FILETIME" in a.text()
                   for a in dlg.build_field_menu(without).actions())


def test_a_clipboard_that_refuses_is_reported_not_claimed_as_success(
        dialog, monkeypatch):
    """setText can fail while another application holds the Windows
    clipboard -- three checks in the older suite already SKIP for exactly
    that. Reporting success anyway is how a report ends up with the
    previous copy's contents in it."""
    dlg = dialog(history_row())
    monkeypatch.setattr(dlg, "_set_clipboard", lambda text: False)
    dlg.copy_all()
    assert "holding the clipboard" in dlg.status_label.text()


# --- filtering ----------------------------------------------------------

def test_filtering_fields_says_how_many_are_hidden(dialog):
    dlg = dialog(history_row())
    total, _absent = df.counts(dlg.groups)
    dlg.apply_filter("url")
    shown = len(_value_items(dlg))
    assert shown < total
    text = dlg.count_label.text()
    assert "filtered" in text
    assert str(total - shown) in text
    assert "hidden by this filter" in text


def test_a_filter_that_matches_nothing_still_says_so(dialog):
    dlg = dialog(history_row())
    total, _ = df.counts(dlg.groups)
    dlg.apply_filter("zzzzz-no-such-field")
    assert _value_items(dlg) == []
    assert str(total) in dlg.count_label.text()


def test_clearing_the_filter_restores_every_field(dialog):
    dlg = dialog(history_row())
    total, _ = df.counts(dlg.groups)
    dlg.apply_filter("url")
    dlg.apply_filter("")
    assert len(_value_items(dlg)) == total
    assert "filtered" not in dlg.count_label.text()


def test_escape_in_the_filter_box_clears_it_and_leaves_the_dialog_open(
        dialog, qtbot):
    """Matches records_view's own Ctrl+F / Escape pair."""
    dlg = dialog(history_row())
    dlg.filter_box.setText("url")
    dlg.apply_filter("url")
    QTest.keyClick(dlg.filter_box, Qt.Key_Escape)
    assert dlg.filter_box.text() == ""
    assert dlg.isVisible()


def test_ctrl_f_focuses_the_filter_box(dialog, qtbot):
    dlg = dialog(history_row())
    QTest.keyClick(dlg, Qt.Key_F, Qt.ControlModifier)
    assert dlg.filter_box.hasFocus()


# --- aggregates drill through -------------------------------------------

def test_a_member_row_opens_that_record_rather_than_copying_it(dialog, qtbot):
    """A summary that copies instead of opening reads as "that is all
    there is"."""
    dlg = dialog(domain_row())
    index = [i for i, f in enumerate(df.flatten(dlg.groups))
             if f.target is not None][0]
    with qtbot.waitSignal(dlg.recordRequested, timeout=1000) as sig:
        dlg.activate_field(index)
    assert isinstance(sig.args[0], dict)
    assert sig.args[0]["_record"] is df.flatten(dlg.groups)[index].value


def test_enter_on_an_ordinary_field_copies_it(dialog):
    dlg = dialog(history_row())
    index = [i for i, f in enumerate(df.flatten(dlg.groups))
             if f.label == "Clean URL"][0]
    QGuiApplication.clipboard().setText("PREVIOUS")
    dlg.activate_field(index)
    assert QGuiApplication.clipboard().text() == "https://example.test/a"


# --- explain ------------------------------------------------------------

def test_f1_asks_for_an_explanation_carrying_the_value_and_its_provenance(
        dialog, qtbot):
    row = carved_struct_row()
    dlg = dialog(row)
    index = [i for i, f in enumerate(df.flatten(dlg.groups))
             if f.label == "Clean URL"][0]
    with qtbot.waitSignal(dlg.explainRequested, timeout=1000) as sig:
        dlg.explain_field(index)
    text = sig.args[0]
    assert "Clean URL" in text
    assert "https://example.test/deleted" in text
    assert provenance.describe_origin(row) in text


def test_an_uncatalogued_field_explains_what_it_can_rather_than_nothing(
        dialog, qtbot):
    dlg = dialog(carved_string_row())
    index = [i for i, f in enumerate(df.flatten(dlg.groups))
             if f.label == "Region of the file"][0]
    with qtbot.waitSignal(dlg.explainRequested, timeout=1000) as sig:
        dlg.explain_field(index)
    assert "Region of the file" in sig.args[0]


# --- badges -------------------------------------------------------------

def test_a_catalogued_field_shows_its_basis_and_an_uncatalogued_one_shows_none(
        dialog):
    row = history_row()
    # UrlHealth is one of roughly fifteen fields this dialog now shows that
    # FIELD_PROVENANCE does not carry. basis_of() would default it to
    # DERIVED and paint a confident chip; it must paint none.
    row["_record"]["UrlHealth"] = "intact"
    dlg = dialog(row)
    badges = {}
    for r in range(dlg.table.rowCount()):
        if dlg.is_heading_row(r):
            continue
        field = dlg.field_at(r)
        item = dlg.table.item(r, 2)
        badges[field.label] = item.data(Qt.DisplayRole) or ""
    assert badges["Clean URL"] == "DER"
    assert badges["URL health"] == ""


def test_a_badge_carries_the_full_definition_and_the_field_description(dialog):
    dlg = dialog(history_row())
    for r in range(dlg.table.rowCount()):
        if dlg.is_heading_row(r) or dlg.field_at(r).label != "Clean URL":
            continue
        tip = dlg.table.item(r, 2).toolTip()
        assert "Derived" in tip
        assert "Computed by this tool" in tip
        return
    raise AssertionError("no Clean URL row")


# --- lifecycle ----------------------------------------------------------

def test_the_dialog_is_modeless_and_deletes_itself_on_close(dialog):
    dlg = dialog(history_row())
    assert dlg.isModal() is False
    assert dlg.testAttribute(Qt.WA_DeleteOnClose) is True


def test_closing_drops_the_reference_to_the_record(dialog):
    """A dialog holds _record references into the parser that produced
    them; keeping one alive after close keeps the exhibit alive too."""
    dlg = dialog(cert_row())
    dlg.close()
    assert dlg.row is None
    assert dlg.groups == []


def test_ctrl_w_closes(dialog, qtbot):
    """Asserted through `destroyed`, not isVisible(): WA_DeleteOnClose
    means Qt has already destroyed the C++ object by the time the key
    handler returns, and asking a deleted object whether it is visible
    raises rather than answering."""
    dlg = dialog(history_row())
    gone = []
    dlg.destroyed.connect(lambda *_: gone.append(1))
    QTest.keyClick(dlg, Qt.Key_W, Qt.ControlModifier)
    qtbot.waitUntil(lambda: bool(gone), timeout=1000)
    assert dlg.row is None


def test_the_dialog_survives_a_row_with_nothing_in_it(dialog):
    """Carved data is damaged data. A dialog that raises on a malformed
    record tells the examiner nothing at all."""
    dlg = dialog({})
    assert isinstance(dlg.table, QTableWidget)
    assert dlg.identity_label.text().strip()


# --- three defects found by looking, not by the suite --------------------

def test_an_aggregate_is_not_headed_as_a_live_record(dialog):
    """On the real exhibit this line read "Live record in Content" above a
    row summarising 345 records."""
    dlg = dialog(domain_row())
    assert not dlg.origin_label.text().startswith("Live record")
    assert "not a single record" in dlg.origin_label.text().lower()


def test_the_filter_box_is_never_narrower_than_its_own_placeholder(dialog):
    """Rendered as "Filter fields (Ctr..." on the real window. A control
    squeezed below its own text is this project's own named defect -- it
    is what made six views' column filters look dead once already."""
    dlg = dialog(history_row())
    box = dlg.filter_box
    needed = box.fontMetrics().horizontalAdvance(box.placeholderText())
    assert box.minimumWidth() >= needed


# --- [9] a long single-token identity must not floor the dialog's width --
#
# identity_label carried neither setWordWrap nor a shrink-permitting size
# policy, so a long unbroken CleanUrl put a floor under the header row's
# own container -- and from there, under the whole dialog -- silently
# refusing resize(1100, 700). Measured floor for a 119-character no-space
# URL: plain QLabel 744px, +setWordWrap 540px (reduces but does not fix --
# word-wrap only breaks at the URL's own few "/" and "&" characters),
# QSizePolicy.Ignored 0px, ElidingLabel 0px.
#
# A SINGLE-TOKEN identity is deliberate: a future change back to
# setWordWrap must not be able to make this pass for the wrong reason.

_LONG_SINGLE_TOKEN_IDENTITY = (
    "https://example.test/reports/quarterly/2026/full-detail-view"
    "?case=alpha&examiner=none&token=" + "a" * 60)


def test_a_long_single_token_identity_does_not_floor_the_header_containers_width(
        dialog):
    """Measured against the header container's OWN minimumSizeHint,
    never identity_label's: under QSizePolicy.Ignored (which
    ElidingLabel sets) the label's own hint still reports the text's
    full natural width -- the size POLICY changes how the parent layout
    CONSUMES that hint, not the hint itself -- so a test written against
    the label passes with the bug still present.
    """
    dlg = dialog(history_row(CleanUrl=_LONG_SINGLE_TOKEN_IDENTITY))
    natural_width = dlg.identity_label.fontMetrics().horizontalAdvance(
        _LONG_SINGLE_TOKEN_IDENTITY)
    container = dlg.identity_label.parentWidget()
    floor = container.minimumSizeHint().width()
    assert floor < natural_width // 2, (
        "the header container is still floored by the identity text's "
        "own natural width (%dpx floor vs a %dpx-wide identity)"
        % (floor, natural_width))


def test_the_dialog_can_still_shrink_to_1100_with_a_long_url_identity(dialog):
    """End to end: the reported symptom was resize(1100, 700) silently
    refused with a long CleanUrl open."""
    dlg = dialog(history_row(CleanUrl=_LONG_SINGLE_TOKEN_IDENTITY))
    dlg.resize(1100, 700)
    assert dlg.width() <= 1100, (
        "the dialog refused to shrink to 1100px with a long single-token "
        "identity open (got %dpx)" % dlg.width())


def test_the_blob_pane_takes_a_viewers_room_without_crowding_the_fields(dialog):
    """PREMISE CHANGED, exactly as this test's own docstring predicted.

    It used to assert a ceiling of 120px, because what sat here was one
    SENTENCE saying the viewer was not built -- and unbounded, that
    sentence claimed a quarter of the dialog and squeezed a 59-field
    record down to nine visible rows. Unit 3 mounts the real hex and
    strings viewer, which should take a viewer's worth of space; a
    ceiling written for a note would now cut a hex dump to two rows.

    What survives unchanged is the FORM of the assertion: an explicit
    pixel bound, never a splitter ratio. Offscreen, a ratio already
    passed while the real window looked wrong -- it can report "verified"
    about the exact thing that is not.
    """
    dlg = dialog(cert_row())
    assert dlg.blob_area is not None
    assert dlg.blob_area.minimumHeight() >= hex_view.MIN_PANE_HEIGHT_PX


def test_a_fields_sub_line_sits_under_its_value_and_is_not_clipped(dialog):
    """Found by looking: "Visits / counted from SPS id6 (property store:
    user visits)" rendered with "visits)" cut off at the row boundary, in
    a dialog whose count line promises "nothing truncated".

    The cause was placing the sub-line in the 250px LABEL column, where it
    wraps to three lines that ResizeToContents did not allow for. It
    belongs under the VALUE -- which is where the design puts it, and
    which is ~1000px wide, so it does not wrap at all.
    """
    dlg = dialog(history_row())
    for r in range(dlg.table.rowCount()):
        if dlg.is_heading_row(r):
            continue
        field = dlg.field_at(r)
        if not field.note:
            continue
        assert dlg.table.item(r, 0).text() == field.label, (
            "the note is in the label column, where it wraps and clips")
        assert field.note in dlg.table.item(r, 1).text()
        return
    raise AssertionError("no field with a note in this fixture")


def test_both_halves_of_a_real_sized_dialog_are_usable(qtbot):
    """PREMISE CORRECTED BY LOOKING. This first asserted that the field
    list keeps the MAJORITY, which sounded right and was the wrong
    invariant: honouring it at a real window size left the viewer at its
    220px floor, where the carve header painted its three rows on top of
    each other and the dump was a few grey bars.

    What actually matters is that BOTH halves are usable -- the viewer
    gets at least its own minimum, and the field list keeps a floor of
    its own -- and that the examiner can drag the rest. A ratio was never
    the point; it was the thing that read as verified while the window
    looked wrong.

    Sized against a REAL parent rather than the 920x580 floor, because
    the floor is not a size any examiner sees and a claim about it would
    be a claim about a window that does not exist.

    PREMISE NARROWED AGAIN, and this time toward the invariant this test
    always meant. The viewer is now foldable, and on a window this size
    it opens folded -- giving the record's fields 94% instead of 38%,
    which is the whole point of the change. "Both halves are usable" is
    therefore a claim about the state where both halves are SHOWN, so
    the test unfolds the viewer and then asserts exactly what it always
    did. tests/test_record_detail_room.py owns the other half: that the
    default state gives the fields the majority.
    """
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(1600, 900)
    parent.show()
    dlg = RecordDetailDialog(cert_row(), parent)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.blob_region.set_expanded(True)
    fields_px, blob_px = dlg._splitter.sizes()
    assert blob_px >= hex_view.MIN_PANE_HEIGHT_PX
    assert blob_px >= dlg.blob_area.minimumSizeHint().height()
    assert fields_px >= record_detail._FIELDS_FLOOR_PX


# --- hiding empty fields ---------------------------------------------------

def test_empty_fields_can_be_hidden_and_the_count_says_so(dialog):
    """A live History record showed 18 of 62 fields as "(empty)", spread
    through the values an examiner is reading. Off by default -- the
    record stays whole -- and when on, the count line says how many are
    hidden, as the field filter does: nothing is hidden quietly."""
    dlg = dialog(history_row())
    shown = lambda: [f for f in dlg._rows if f is not None]
    all_fields = len(shown())
    empty = len([f for f in shown() if f.absence])
    assert empty > 0
    assert not dlg.hide_empty_box.isChecked()
    dlg.hide_empty_box.setChecked(True)
    assert len(shown()) == all_fields - empty
    assert not [f for f in shown() if f.absence]
    text = dlg.count_label.text()
    assert "%d empty" % empty in text and "hidden" in text, text
    dlg.hide_empty_box.setChecked(False)
    assert len(shown()) == all_fields


def test_a_shortened_button_grows_back_when_the_window_does(dialog, qtbot):
    """Seen on screen at 1,740 pixels wide: "Co...", "Explain t...", "Show
    in datab..." -- a button that had once been laid out narrow asked
    only for the width of its SHORTENED label from then on, so it never
    grew back. The preferred width is the full label's."""
    from tests.test_detail_fields import history_row
    dlg = dialog(history_row())
    dlg.show()
    dlg.resize(500, 600)
    qtbot.wait(50)
    dlg.resize(1700, 800)
    qtbot.wait(50)
    for button in (dlg.copy_field_button, dlg.explain_button):
        assert button.text() == button.full_text(), button.text()
