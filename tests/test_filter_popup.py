"""The filter popup: a values panel and a condition panel, combined with AND.

'i told all to be displayed in filter, not partial search and all, we
don't have millions of rows to do that' -- the earlier version capped its value
picker, and an examiner searching for a name that was PRESENT in the data
got no hits. Every distinct value has to render here, no cap, no streaming,
no "load more".

Values and conditions combine rather than replace (Excel discards ticked
values the moment a text filter is typed; for evidence work that is
dangerous, because afterwards nobody can say what produced the rows on
screen). And "in the last N days" anchors to the newest value actually in
the column, not to today's date -- examiners work from an image captured in
the past, and an examiner must never have to guess which window they are
looking at, so the popup has to show the resolved date, not just apply it
silently.
"""
import datetime

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QWidget

from webcache.widgets.filter_popup import FilterPopup
from webcache.widgets.record_filter import Condition
from webcache.widgets.record_model import RecordTableModel
from tests.fixtures import FIXTURE_COLUMNS, make_rows


def _domain_col():
    return next(c for c in FIXTURE_COLUMNS if c.key == "Domain")


def _time_col():
    return next(c for c in FIXTURE_COLUMNS if c.key == "AccessedUtc")


def _flag_col():
    return next(c for c in FIXTURE_COLUMNS if c.key == "IsInPrivate")


@pytest.fixture
def popup(qtbot):
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(2_000))
    p = FilterPopup(model, _domain_col())
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    return p


@pytest.fixture
def time_popup(qtbot):
    """A popup on a TIME column, so 'in the last N days' is actually on
    offer -- Domain's kind ("domain") only gets the text operators."""
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(2_000))
    p = FilterPopup(model, _time_col())
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    return p


@pytest.fixture
def flag_popup(qtbot):
    """A popup on a FLAG column -- its cells paint "Yes"/"No", never the
    raw True/False (see column_spec.display_text), so this is the fixture
    that can actually prove the value picker's item TEXT and item DATA
    disagree on purpose."""
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(2_000))
    p = FilterPopup(model, _flag_col())
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    return p


# --- the values panel: every distinct value, no cap ------------------------

def test_every_distinct_value_is_listed_with_no_cap(popup):
    """'i told all to be displayed in filter, not partial search and all,
    we don't have millions of rows to do that'."""
    distinct = {r["Domain"] for r in popup.model.filter.rows}
    assert popup.values_list.count() == len(distinct)


def test_no_cap_holds_at_realistic_scale_not_just_eight_values(qtbot):
    """Domain only has 8 distinct values in the fixtures -- a hidden cap of
    any plausible size would pass the test above without actually proving
    anything. The incident this popup exists to prevent was a capped list
    at real scale: an examiner searched for a name that was PRESENT and
    got no hits. CleanUrl embeds the row index (see fixtures.py), so it is
    unique per row -- 2,000 distinct values at n=2,000 -- which is the
    scale that actually pins the guarantee."""
    rows = make_rows(2_000)
    distinct = {r["CleanUrl"] for r in rows}
    assert len(distinct) == 2_000  # sanity: the fixture really is unique per row
    model = RecordTableModel(list(FIXTURE_COLUMNS), rows)
    col = next(c for c in FIXTURE_COLUMNS if c.key == "CleanUrl")
    p = FilterPopup(model, col)
    qtbot.addWidget(p)
    assert p.values_list.count() == len(distinct)


def test_each_value_shows_its_count(popup):
    total = sum(int(popup.values_list.item(i).text().rsplit("(", 1)[1].rstrip(")").replace(",", ""))
                for i in range(popup.values_list.count()))
    assert total == 2_000


def test_the_search_box_has_focus_on_open(popup):
    assert popup.search_box.hasFocus()


def test_searching_narrows_the_list_and_clearing_restores_it(popup, qtbot):
    before = popup.values_list.count()
    QTest.keyClicks(popup.search_box, "msn")
    qtbot.waitUntil(lambda: popup.visible_value_count() < before, timeout=2000)
    popup.search_box.clear()
    qtbot.waitUntil(lambda: popup.visible_value_count() == before, timeout=2000)


def test_a_search_matching_nothing_says_so(popup, qtbot):
    QTest.keyClicks(popup.search_box, "zzzz-nothing")
    qtbot.waitUntil(lambda: popup.visible_value_count() == 0, timeout=2000)
    assert "No values match" in popup.status_text()


def test_search_does_not_match_a_values_rendered_count(popup, qtbot):
    """The needle must match a value's own content, never the '(1,234)'
    count suffix rendered next to it. None of the fixture's Domain hosts
    contain the digit "5" (only 'acroipm2.adobe.com' has any digit at
    all, and it's a "2"), so under correct matching a search for "5" must
    hide every item -- regardless of what any host's count happens to
    contain."""
    QTest.keyClicks(popup.search_box, "5")
    qtbot.waitUntil(lambda: popup.visible_value_count() == 0, timeout=2000)


def test_select_none_then_apply_shows_no_rows(popup):
    popup.select_none()
    popup.apply()
    assert popup.model.rowCount() == 0


def test_select_all_then_apply_restores_every_row(popup):
    popup.select_none()
    popup.apply()
    popup.select_all()
    popup.apply()
    assert popup.model.rowCount() == 2_000


def test_select_all_after_a_search_only_admits_the_searched_subset(popup, qtbot):
    """select_all()/select_none() apply to the values currently SHOWN, not
    to every distinct value -- an Excel-like reading, deliberately kept.
    Narrow first, deselect everything, narrow again, then hit All: only
    the narrowed-to subset should come back. A regression to "All means
    every distinct value regardless of the search box" would silently
    restore rows an examiner had deliberately excluded."""
    popup.select_none()
    before = popup.values_list.count()
    QTest.keyClicks(popup.search_box, "msn")
    qtbot.waitUntil(lambda: popup.visible_value_count() < before, timeout=2000)
    popup.select_all()
    popup.apply()
    assert popup.model.rowCount() > 0
    for i in range(popup.model.rowCount()):
        assert popup.model.row_at(i)["Domain"] == "msn.com"


def test_an_emptied_selection_is_never_read_as_no_filter(popup):
    """An empty allowed-value set means NONE selected, not 'no filter'.
    Conflating the two once made an examiner believe they were looking at
    everything when they were looking at nothing."""
    popup.select_none()
    popup.apply()
    assert popup.model.filter.allowed_values("Domain") == set()
    assert popup.model.rowCount() == 0


def test_ticking_a_value_shown_as_yes_filters_by_the_raw_true(flag_popup):
    """The value picker's item TEXT is display text ("Yes"/"No" for a flag
    column, per column_spec.display_text) but its DATA role (Qt.UserRole)
    stays the raw value -- so an examiner who ticks the item labelled
    "Yes" must end up filtering on the raw True every row actually stores,
    not on the string "Yes" (which is never a row's IsInPrivate value at
    all). End-to-end through the real widget: read the rendered item
    text, tick only "Yes" via the same check_only() the popup's own search
    box uses, apply, and check both the filter's own bookkeeping
    (allowed_values) and the rows that actually survive."""
    model = flag_popup.model
    raw_true_rows = [r for r in model.filter.rows if r["IsInPrivate"] is True]
    assert raw_true_rows, "fixture must contain at least one True row"

    labels_by_raw_value = {
        flag_popup.values_list.item(i).data(Qt.UserRole):
            flag_popup.values_list.item(i).text()
        for i in range(flag_popup.values_list.count())
    }
    assert labels_by_raw_value[True].startswith("Yes")
    assert labels_by_raw_value[False].startswith("No")

    flag_popup.check_only({True})
    assert flag_popup.apply()

    assert model.filter.allowed_values("IsInPrivate") == {True}
    visible = model.filter.visible()
    assert len(visible) == len(raw_true_rows)
    assert visible and all(r["IsInPrivate"] is True for r in visible)


def test_escape_closes_the_popup(popup, qtbot):
    QTest.keyClick(popup, Qt.Key_Escape)
    qtbot.waitUntil(lambda: not popup.isVisible(), timeout=2000)


# --- the condition panel: operators offered by column kind ------------------

@pytest.mark.parametrize("col", FIXTURE_COLUMNS, ids=[c.key for c in FIXTURE_COLUMNS])
def test_operators_offered_match_the_column_kind(qtbot, col):
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(200))
    p = FilterPopup(model, col)
    qtbot.addWidget(p)
    offered = [p.operator_box.itemText(i) for i in range(p.operator_box.count())]
    from webcache.widgets.record_filter import operators_for
    # "(no condition)" first, so ticking values alone adds no condition
    # then the operators this kind takes.
    assert offered == ["(no condition)"] + list(
        operators_for(col, model.value_counts(col.key)))


def test_second_operand_appears_only_for_between(popup):
    popup.operator_box.setCurrentText("contains")
    assert not popup.operand_b.isVisible()


def test_second_operand_appears_for_between_on_a_numeric_column(qtbot):
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(200))
    col = next(c for c in FIXTURE_COLUMNS if c.key == "VisitCount")
    p = FilterPopup(model, col)
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    p.operator_box.setCurrentText("between")
    assert p.operand_b.isVisible()


def test_no_operand_shown_for_is_blank(popup):
    popup.operator_box.setCurrentText("is blank")
    assert not popup.operand_a.isVisible()
    assert not popup.operand_b.isVisible()


def test_invalid_regex_is_flagged_inline_not_raised(popup):
    popup.operator_box.setCurrentText("matches regex")
    popup.operand_a.setText("([unclosed")
    popup.apply()
    assert "regex" in popup.status_text().lower()


def test_between_with_only_the_first_operand_is_refused_not_silently_empty(qtbot):
    """Condition itself builds a one-sided "between" without .error (see
    its docstring), and it then matches nothing for every row -- an
    unexplained empty table, exactly the class of bug the engine guards
    against. The popup must catch this at the
    UI layer and say why, rather than silently applying a condition that
    can never match anything."""
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(200))
    col = next(c for c in FIXTURE_COLUMNS if c.key == "VisitCount")
    p = FilterPopup(model, col)
    qtbot.addWidget(p)
    p.operator_box.setCurrentText("between")
    p.operand_a.setText("10")
    ok = p.apply()
    assert ok is False
    assert "between" in p.status_text().lower()
    assert p.model.filter.condition_for("VisitCount") is None
    assert p.model.rowCount() == 200  # nothing was silently applied


# --- the OK button, driven for real -----------------------------------------
# Every test above calls popup.apply() directly. That proves apply() works
# but never proves the button is actually wired to it -- a severed
# buttons.accepted.connect(self._ok) would go undetected. These drive the
# real QDialogButtonBox with QTest.mouseClick instead.

def test_ok_button_click_stays_open_and_flags_status_on_invalid_regex(popup, qtbot):
    ok_button = popup.button_box.button(QDialogButtonBox.Ok)
    popup.operator_box.setCurrentText("matches regex")
    popup.operand_a.setText("([unclosed")
    QTest.mouseClick(ok_button, Qt.LeftButton)
    # A dialog that closes on invalid input has silently applied nothing --
    # staying open, with the reason visible, is the behaviour that matters.
    assert popup.isVisible()
    assert "regex" in popup.status_text().lower()


def test_ok_button_click_applies_and_closes_on_a_valid_condition(popup, qtbot):
    ok_button = popup.button_box.button(QDialogButtonBox.Ok)
    popup.operator_box.setCurrentText("contains")
    popup.operand_a.setText("login")
    QTest.mouseClick(ok_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: not popup.isVisible(), timeout=2000)
    assert popup.model.rowCount() > 0
    for i in range(popup.model.rowCount()):
        assert "login" in str(popup.model.row_at(i)["Domain"]).lower()


# --- values and condition combine, they never replace ----------------------

def test_condition_alone_restricts_the_column(popup):
    popup.operator_box.setCurrentText("contains")
    popup.operand_a.setText("login")
    popup.apply()
    assert popup.model.rowCount() > 0
    for i in range(popup.model.rowCount()):
        assert "login" in str(popup.model.row_at(i)["Domain"]).lower()


def test_values_and_condition_combine_to_their_intersection(popup):
    """Both panels apply to the SAME column (this popup is opened on
    Domain), and the result must be exactly their intersection: ticked
    AND matching the condition -- not either alone.

    'login.live.com' is the only fixture host containing "login"; ticking
    it alongside two hosts that do NOT, then filtering by "contains
    login", must leave only rows for that one host."""
    popup.check_only({"msn.com", "bing.com", "login.live.com"})
    popup.operator_box.setCurrentText("contains")
    popup.operand_a.setText("login")
    popup.apply()
    assert popup.model.rowCount() > 0
    for i in range(popup.model.rowCount()):
        assert popup.model.row_at(i)["Domain"] == "login.live.com"


def test_values_filter_still_applies_once_a_condition_is_also_typed(popup):
    """The decisive case: Excel would DISCARD the ticked values the moment
    a text filter is applied, so a condition matching a host that was
    never ticked would still show it. Here the only host matching
    "contains login" ('login.live.com') is deliberately left UNTICKED --
    if the values filter were being replaced instead of combined, rows for
    it would still appear. They must not: the result must be empty."""
    popup.check_only({"msn.com", "bing.com"})
    popup.operator_box.setCurrentText("contains")
    popup.operand_a.setText("login")
    popup.apply()
    assert popup.model.rowCount() == 0


# --- reopening the popup must not silently drop an active condition --------
# The values panel is seeded from the live filter on
# construction (_populate reads allowed_values()), but the condition panel
# was not -- a second popup on an already-filtered column came up with blank
# operator/operand fields, and apply() (called after touching only the
# values panel, as any "reopen the filter" flow does) then overwrote the
# live condition with None. The rows came BACK, silently -- worse than
# Excel's failure mode, because a fuller table reads as more complete, which
# is the direction a false conclusion travels.

def test_reopening_the_popup_preserves_an_already_applied_condition(qtbot):
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(2_000))
    col = _domain_col()

    first = FilterPopup(model, col)
    qtbot.addWidget(first)
    first.operator_box.setCurrentText("contains")
    first.operand_a.setText("login")
    first.apply()
    filtered_count = model.rowCount()
    assert 0 < filtered_count < 2_000

    # A second popup on the SAME model and column, as any "reopen the
    # filter" flow constructs -- this is the exact reproduction the
    # reviewer gave: it must come up already showing the live condition,
    # not blank fields.
    second = FilterPopup(model, col)
    qtbot.addWidget(second)
    assert second.operator_box.currentText() == "contains"
    assert second.operand_a.text() == "login"

    # Touch only the values panel (as an examiner narrowing the tick list
    # on an already-filtered column would) and apply -- the condition must
    # survive untouched.
    second.select_all()
    ok = second.apply()
    assert ok is True
    assert model.rowCount() == filtered_count
    assert model.filter.condition_for("Domain").describe() == 'contains "login"'
    for i in range(model.rowCount()):
        assert "login" in str(model.row_at(i)["Domain"]).lower()


def test_reopening_seeds_both_operands_of_a_between_condition(qtbot):
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(200))
    col = next(c for c in FIXTURE_COLUMNS if c.key == "VisitCount")
    model.set_condition("VisitCount", Condition("between", "10", "300"))
    filtered_count = model.rowCount()
    assert 0 < filtered_count < 200

    p = FilterPopup(model, col)
    qtbot.addWidget(p)
    assert p.operator_box.currentText() == "between"
    assert p.operand_a.text() == "10"
    assert p.operand_b.text() == "300"

    ok = p.apply()
    assert ok is True
    assert model.rowCount() == filtered_count


def test_reopening_with_no_active_condition_leaves_the_fields_blank(popup):
    """The seeding must not invent a condition that was never there --
    a freshly opened popup on an unfiltered column starts blank."""
    assert popup.operand_a.text() == ""
    assert popup.operand_b.text() == ""


# --- the anchor: "in the last N days" measures from the evidence -----------
# The anchor is the newest non-blank value in the
# column, never today's date, because an examiner works from a disk image
# captured in the past and an empty table reads as "no activity" -- a false
# negative in the most dangerous direction. This popup must show the
# resolved window, not just silently apply it.

def test_anchor_label_hidden_until_the_anchor_operator_is_chosen(time_popup):
    assert not time_popup.anchor_label.isVisible()
    time_popup.operator_box.setCurrentText("before")
    assert not time_popup.anchor_label.isVisible()


def test_choosing_in_the_last_n_days_shows_the_resolved_anchor_date(time_popup):
    newest = max(r["AccessedUtc"] for r in time_popup.model.filter.rows
                 if r["AccessedUtc"])
    time_popup.operator_box.setCurrentText("in the last N days")
    assert time_popup.anchor_label.isVisible()
    assert newest.strftime("%Y-%m-%d") in time_popup.anchor_label.text()


def test_the_anchor_shown_is_not_todays_date(time_popup):
    """The fixture rows run from 2024-01-01 across at most ~400 days, so
    their newest timestamp never reaches this year. The label is allowed
    (and expected) to spell out "not today's date" as a clarifying
    affordance -- what must never happen is the resolved date itself
    silently BEING today, which is what a from-today anchor would produce."""
    time_popup.operator_box.setCurrentText("in the last N days")
    text = time_popup.anchor_label.text()
    assert datetime.date.today().strftime("%Y-%m-%d") not in text


def test_anchor_label_explains_when_the_column_has_no_dated_value(qtbot):
    """A column that is entirely blank for this row set has no anchor to
    resolve. Matching nothing is safe; claiming a window with no evidence
    behind it would not be."""
    rows = make_rows(50)
    for r in rows:
        r["AccessedUtc"] = None
    model = RecordTableModel(list(FIXTURE_COLUMNS), rows)
    p = FilterPopup(model, _time_col())
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    p.operator_box.setCurrentText("in the last N days")
    assert p.anchor_label.isVisible()
    assert p.anchor_label.text()  # says SOMETHING, not left blank
    p.operand_a.setText("7")
    p.apply()
    assert p.model.rowCount() == 0


def test_applying_in_the_last_n_days_matches_only_rows_inside_the_window(time_popup):
    newest = max(r["AccessedUtc"] for r in time_popup.model.filter.rows
                 if r["AccessedUtc"])
    time_popup.operator_box.setCurrentText("in the last N days")
    time_popup.operand_a.setText("7")
    time_popup.apply()
    assert time_popup.model.rowCount() > 0
    for i in range(time_popup.model.rowCount()):
        value = time_popup.model.row_at(i)["AccessedUtc"]
        assert value is not None
        assert (newest - value).total_seconds() <= 7 * 86400


# --- emptied_by(): a qualified string when a column carries both -----------
# RecordFilter.emptied_by() returns a BARE column key ("Domain") when only
# one kind of filter is active, but a QUALIFIED one ("Domain (values)" /
# "Domain (condition)") when the column carries both a values filter and a
# condition together. Any status text built from it must handle either
# shape without assuming the bare form.

def test_status_names_the_bare_column_when_only_the_values_filter_is_active(popup):
    popup.select_none()
    popup.apply()
    assert popup.model.rowCount() == 0
    assert popup.model.filter.emptied_by() == "Domain"
    assert "Domain" in popup.status_text()


def test_status_handles_the_qualified_form_when_the_column_carries_both(popup):
    """Ticking exactly one real host (so the values set is non-empty, not
    the 'nothing ticked' case) and pairing it with a condition that matches
    nothing forces emptied_by() to report which of the two is actually
    responsible -- the qualified '<key> (condition)' form -- because
    dropping the condition alone (leaving the tick) restores rows, while
    dropping the tick alone (leaving the condition) would not."""
    popup.check_only({"msn.com"})
    popup.operator_box.setCurrentText("contains")
    popup.operand_a.setText("zzzz-impossible-substring")
    popup.apply()
    assert popup.model.rowCount() == 0
    assert popup.model.filter.emptied_by() == "Domain (condition)"
    # The popup's own status text must not choke on the qualified form --
    # no split/parse that assumes a bare key -- and should surface it.
    assert "Domain (condition)" in popup.status_text()


# --- non-modal: the rest of the app must stay reachable ---------------------
# setModal(True) made this application-modal -- while it was open, nothing
# else in the app could be clicked, not even the sidebar. That contradicted
# _open_filter_popup's own docstring ("an examiner filtering one column
# should not be prevented from switching views") and was the user's original
# complaint about this port: unable to reach other menus.

def test_popup_is_not_application_modal(popup):
    assert not popup.isModal()
    assert popup.windowModality() != Qt.ApplicationModal


def test_losing_focus_to_another_window_closes_the_popup(popup, qtbot):
    """Non-modal alone would leave a popup nobody ever explicitly closes
    sitting on screen forever once the examiner clicks elsewhere. It has
    to close itself the moment focus genuinely leaves it for a different
    window -- the same way a QComboBox dropdown or QMenu already does."""
    other = QWidget()
    qtbot.addWidget(other)
    other.show()
    qtbot.waitExposed(other)
    other.setFocus(Qt.OtherFocusReason)
    qtbot.waitUntil(lambda: not popup.isVisible(), timeout=2000)


def test_losing_focus_cancels_rather_than_applies(popup, qtbot):
    """Closing via focus-out must go through one of the SAME two existing
    paths (apply via OK, cancel via Cancel/Escape) rather than invent a
    third. It cancels: an examiner mid-edit who clicks away has not
    pressed OK, and nothing typed but never applied may leak into the
    live filter -- the same guarantee Escape already gives."""
    popup.operator_box.setCurrentText("contains")
    popup.operand_a.setText("login")  # typed, never applied
    other = QWidget()
    qtbot.addWidget(other)
    other.show()
    qtbot.waitExposed(other)
    other.setFocus(Qt.OtherFocusReason)
    qtbot.waitUntil(lambda: not popup.isVisible(), timeout=2000)
    assert popup.model.filter.condition_for("Domain") is None
    assert popup.model.rowCount() == 2_000


def test_focus_moving_between_the_popups_own_child_widgets_does_not_close_it(popup, qtbot):
    """Only a focus move to a genuinely OTHER window should close the
    popup -- moving focus between its own fields (as every existing test
    in this file already does via QTest.keyClicks / setCurrentText) must
    not."""
    popup.search_box.setFocus(Qt.OtherFocusReason)
    popup.operand_a.setFocus(Qt.OtherFocusReason)
    popup.values_list.setFocus(Qt.OtherFocusReason)
    assert popup.isVisible()


# --- a NoFocus widget elsewhere in the app must still close the popup ------
# CRITICAL, on-screen verification against the real exhibit: clicking the
# SIDEBAR nav (the most ordinary way an examiner "moves on") left the popup
# sitting open on screen. QApplication.focusChanged never fires for that
# click at all -- sidebar.py deliberately sets self.nav.setFocusPolicy(Qt.
# NoFocus), so the nav never becomes the focus WIDGET no matter what is
# clicked inside it. Window ACTIVATION is the signal that still fires:
# clicking anywhere inside another top-level window activates it at the OS
# level regardless of which child widget the click landed on.

def test_activating_a_different_window_closes_the_popup_even_with_no_focus_widget(
        popup, qtbot):
    """windowHandle().requestActivate() is the reliable, direct way to
    simulate 'a click landed on some other window' independent of any
    particular widget's own focus policy -- exactly the mechanism a real
    click on the sidebar's NoFocus nav list relies on, which setFocus()
    alone (the mechanism the tests above use) does not exercise at all."""
    other = QWidget()
    qtbot.addWidget(other)
    other.show()
    qtbot.waitExposed(other)
    other.windowHandle().requestActivate()
    qtbot.waitUntil(lambda: not popup.isVisible(), timeout=2000)


def test_opening_the_operator_combos_own_dropdown_does_not_close_the_popup(
        time_popup, qtbot):
    """A QComboBox's drop-down list is its OWN top-level window (Qt::Popup)
    -- verified directly, opening one fires the identical window-
    activation signal the test above relies on to close the popup. Qt
    marks that window's transientParent as the window that opened it
    (this dialog's own), which is what tells the two apart; without
    walking that chain, choosing an operator would close the very popup
    the operator box lives in."""
    time_popup.operator_box.showPopup()
    qtbot.wait(50)
    assert time_popup.isVisible()
    time_popup.operator_box.hidePopup()


# --- the picker's own search matches what it shows -------

def _picker(qtbot, column, rows):
    cols = [column]
    model = RecordTableModel(cols, rows)
    p = FilterPopup(model, column)
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    return p


def _search(p, text):
    """Type, then run the (debounced) search now rather than waiting."""
    p.search_box.clear()
    QTest.keyClicks(p.search_box, text)
    p._apply_value_search()


def _visible_values(p):
    return [p.values_list.item(i).data(Qt.UserRole)
            for i in range(p.values_list.count())
            if not p.values_list.item(i).isHidden()]


def test_picker_search_yes_finds_the_true_item_on_a_flag_column(flag_popup):
    """The items read "Yes (123)"; typing "yes" must find that item."""
    _search(flag_popup, "yes")
    assert _visible_values(flag_popup) == [True]
    assert flag_popup.status_text() == ""


def test_picker_search_0x_finds_every_offset_item(qtbot):
    from webcache.widgets.column_spec import Column
    col = Column("Offset", "Offset", 90, kind="offset")
    rows = [{"Offset": v} for v in (0x3B0523, 0x10, 0x7FFF0000)]
    p = _picker(qtbot, col, rows)
    _search(p, "0x")
    assert sorted(_visible_values(p)) == sorted([0x3B0523, 0x10, 0x7FFF0000])
    _search(p, "0x003B0523")
    assert _visible_values(p) == [0x3B0523]


def test_picker_search_finds_a_size_by_its_separated_and_plain_digits(qtbot):
    from webcache.widgets.column_spec import Column
    col = Column("FileSize", "Size", 90, kind="size")
    rows = [{"FileSize": v} for v in (12345, 999)]
    p = _picker(qtbot, col, rows)
    _search(p, "12,345")
    assert _visible_values(p) == [12345]
    _search(p, "12345")
    assert _visible_values(p) == [12345]


def test_one_searchable_text_rule_for_grid_search_and_picker():
    from webcache.widgets import column_spec
    rule = getattr(column_spec, "searchable_text", None)
    assert rule is not None, "column_spec.searchable_text is missing"
    col = column_spec.Column("FileSize", "Size", 90, kind="size")
    assert "12,345" in rule(12345, col) and "12345" in rule(12345, col)
    off = column_spec.Column("Offset", "Offset", 90, kind="offset")
    assert rule(16, off) == "0x00000010"
    flag = column_spec.Column("F", "F", 90, kind="flag")
    assert rule(True, flag) == "Yes"


# --- a column of 100,000 distinct values opens at once -----------------------

def test_a_hundred_thousand_distinct_values_open_in_well_under_a_second(qtbot):
    import time
    rows = make_rows(100_000)
    for i, row in enumerate(rows):
        row["Domain"] = "host%06d.example.test" % i
    model = RecordTableModel(list(FIXTURE_COLUMNS), rows)
    model.value_counts("Domain")          # the count is cached; time the list
    started = time.perf_counter()
    p = FilterPopup(model, _domain_col())
    qtbot.addWidget(p)
    built = time.perf_counter() - started
    assert p.values_list.count() == 100_000
    # It took 7.6 s as one QListWidgetItem per value; the bound is loose
    # for a loaded machine and still far below that.
    assert built < 2.5, "%.2fs to build the value list" % built
    started = time.perf_counter()
    p.search_box.setText("host04")
    p._apply_value_search()
    assert p.visible_value_count() == 10_000
    # Untouched, the search selects exactly what it finds.
    assert len(p.chosen_values()) == 10_000
    p.select_none()
    assert time.perf_counter() - started < 1.0
    # None then clears the values on show; the search had already left
    # the hidden ones unticked, so nothing is ticked.
    assert p.chosen_values() == set()


def test_a_tick_changed_through_the_view_is_what_apply_reads(popup):
    view_model = popup.values_list.model()
    first = view_model.index(0)
    value = view_model.data(first, Qt.UserRole)
    # A click reaches the model as an int, not a Qt.CheckState.
    assert view_model.setData(first, 0, Qt.CheckStateRole)
    assert popup.values_list.item(0).checkState() == Qt.Unchecked
    chosen = popup.chosen_values()
    assert chosen is not None and value not in chosen


def test_a_long_value_wraps_inside_the_list_instead_of_running_past_it(qtbot):
    """Seen on screen after the list became model-backed: an address ran
    past the list behind a horizontal scrollbar, cut off. test_no_elision
    only read the wrap flag, which stayed on throughout."""
    rows = make_rows(40)
    long = "feedback-hub:?tabid=2&categoryid=20&searchString=" + "x" * 120
    rows[3]["Domain"] = long
    model = RecordTableModel(list(FIXTURE_COLUMNS), rows)
    p = FilterPopup(model, _domain_col())
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    lst = p.values_list
    qtbot.waitUntil(lambda: lst.visualRect(lst.model().index(0)).height() > 0)
    width = lst.viewport().width()
    for row in range(lst.model().rowCount()):
        assert lst.visualRect(lst.model().index(row)).width() <= width
    assert lst.horizontalScrollBar().maximum() == 0
    row = next(r for r in range(lst.model().rowCount())
               if lst.model().index(r).data(Qt.UserRole) == long)
    line = lst.fontMetrics().height()
    assert lst.visualRect(lst.model().index(row)).height() >= 3 * line


def test_a_value_with_spaces_gets_every_line_the_painter_sets(qtbot):
    """Breaks at word boundaries take more lines than breaks anywhere; a
    row measured the second way lost its last line ("0x80131500")."""
    rows = make_rows(40)
    value = "feedback-hub:?tabid=2&categoryid=20&searchString=Code: 0x80131500"
    rows[3]["Domain"] = value
    model = RecordTableModel(list(FIXTURE_COLUMNS), rows)
    p = FilterPopup(model, _domain_col())
    qtbot.addWidget(p)
    p.resize(300, p.height())
    p.show()
    qtbot.waitExposed(p)
    lst = p.values_list
    ix = next(lst.model().index(r) for r in range(lst.model().rowCount())
              if lst.model().index(r).data(Qt.UserRole) == value)
    qtbot.waitUntil(lambda: lst.visualRect(ix).height() > 0)
    metrics = lst.fontMetrics()
    # Greedy word wrap, done by hand: the line count the painter needs.
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
    opt = QStyleOptionViewItem()
    lst.itemDelegate().initStyleOption(opt, ix)
    opt.rect = lst.visualRect(ix)
    width = lst.style().subElementRect(QStyle.SE_ItemViewItemText, opt, lst).width()
    lines, current = 1, ""
    for word in ix.data(Qt.DisplayRole).split(" "):
        trial = (current + " " + word) if current else word
        if metrics.horizontalAdvance(trial) <= width - 4:
            current = trial
        else:
            lines += 1
            current = word
    assert lines >= 3
    assert lst.visualRect(ix).height() >= lines * metrics.height()
