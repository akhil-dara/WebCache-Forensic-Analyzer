"""RecoveryView (Deleted Records): the same filter/count/clear-filters
mechanism History already has, plus the one control History does not need
-- a button that starts a scan.

Row data is generated with tests.fixtures.make_rows for the filter/count
tests below, exactly as test_history_view.py does -- this view's COLUMNS
are a different shape (Timestamp/ContainerType/Offset/Page/Method in place
of AccessedUtc/AccessedLocal/VisitCount/Domain/IsInPrivate), but the
underlying RecordsTable/RecordTableModel machinery being exercised is
identical, so a subset of fixture rows re-keyed onto this view's own column
keys is enough to prove the same mechanism works here too.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from webcache.views.recovery import (NOT_SCANNED_NOTE, SCAN_FOUND_NOTHING_NOTE,
                                     RecoveryView)


def _rows(n):
    """Rows shaped for RecoveryView.COLUMNS -- CleanUrl/Title/Timestamp/
    ContainerType/Origin/Source/Offset/Page/Method/Confidence -- built
    directly rather than through tests.fixtures.make_rows, whose rows are
    keyed for HistoryView's different column set."""
    rows = []
    for i in range(n):
        carved_kind = "structured" if i % 2 == 0 else "string-carve"
        rows.append({
            "CleanUrl": "https://msn.com/%d" % i if i % 3 else "https://login.live.com/%d" % i,
            "Title": "" if carved_kind == "string-carve" else "Page %d" % i,
            "Timestamp": None,
            "ContainerType": "History" if carved_kind == "structured" else "",
            "Origin": "Carved (deleted/unflushed)",
            "Source": "WebCacheV01.dat" if carved_kind == "structured" else "V01.log",
            "Offset": i * 4096,
            "Page": i if carved_kind == "structured" else None,
            "Method": ("Structured record reconstruction" if carved_kind == "structured"
                      else "Transaction log"),
            "Confidence": "high" if i % 2 else "medium",
        })
    return rows


@pytest.fixture
def view(qtbot):
    v = RecoveryView()
    v.set_records(_rows(2_000))
    qtbot.addWidget(v)
    v.resize(1500, 800)
    v.show()
    qtbot.waitExposed(v)
    return v


# --- before any scan: no table population, an honest note -----------------

def test_no_scan_yet_note_names_how_to_get_the_rest(qtbot):
    """Unlike the earlier version's static live-only note, this one is not
    just present before a scan -- it says how to get the rest, which the
    old note never did."""
    v = RecoveryView()
    qtbot.addWidget(v)
    assert "recover deleted records" in NOT_SCANNED_NOTE.lower()


def test_the_view_starts_with_no_table_model_until_a_scan_or_load_populates_it():
    """Mirrors HistoryView's own pre-load state exactly (see that view's
    own construction) -- and is what keeps this view from inflating the
    whole QStackedWidget's minimum size hint before any exhibit is even
    open (a real regression this project hit once already)."""
    v = RecoveryView()
    assert v.table.model() is None


# --- the recover button: the one control History does not need ------------

def test_recover_button_exists_and_starts_enabled(qtbot):
    v = RecoveryView()
    qtbot.addWidget(v)
    assert v.recover_button.isEnabled()
    assert "recover" in v.recover_button.text().lower()


def test_clicking_recover_button_emits_recover_requested(qtbot):
    v = RecoveryView()
    qtbot.addWidget(v)
    with qtbot.waitSignal(v.recoverRequested, timeout=1000):
        QTest.mouseClick(v.recover_button, Qt.LeftButton)


def test_set_scanning_true_disables_the_button_and_relabels_it(qtbot):
    v = RecoveryView()
    qtbot.addWidget(v)
    v.set_scanning(True)
    assert not v.recover_button.isEnabled()
    assert v.recover_button.text() != "Recover deleted records…"


def test_set_scanning_false_re_enables_the_button(qtbot):
    v = RecoveryView()
    qtbot.addWidget(v)
    v.set_scanning(True)
    v.set_scanning(False)
    assert v.recover_button.isEnabled()
    assert v.recover_button.text() == "Recover deleted records…"


def test_the_timestamp_column_has_no_badge_with_no_provenance_entry(qtbot):
    """Timestamp declared field="Timestamp", absent from
    evidence_model.FIELD_PROVENANCE, so it defaulted through basis_of() to
    DERIVED -- and this column deliberately mixes two different kinds of
    evidence in one cell (a structured record's real AccessedTime, and a
    string carve's merely-nearby FILETIME, per this view's own module
    docstring), so no single badge could honestly describe it even with a
    real catalogue entry. field=None: no badge guessed."""
    from webcache.engine import evidence_model
    assert "Timestamp" not in evidence_model.FIELD_PROVENANCE
    v = RecoveryView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "Timestamp")
    assert col.field is None


# --- the table, once populated: same mechanism History already has --------

def test_the_table_shows_every_record(view):
    assert view.table.model().rowCount() == 2_000
    assert "2,000" in view.count_label.text()


def test_every_row_is_stamped_carved(view):
    origins = {view.table.model().row_at(i)["Origin"]
              for i in range(view.table.model().rowCount())}
    assert all(o.startswith("Carved") for o in origins)


def test_typing_in_the_filter_box_narrows_the_table(view, qtbot):
    QTest.keyClicks(view.filter_box, "login")
    qtbot.waitUntil(lambda: view.table.model().rowCount() < 2_000, timeout=3000)
    assert "of 2,000" in view.count_label.text()


def test_clearing_the_filter_box_restores_every_row(view, qtbot):
    QTest.keyClicks(view.filter_box, "login")
    qtbot.waitUntil(lambda: view.table.model().rowCount() < 2_000, timeout=3000)
    view.filter_box.clear()
    qtbot.waitUntil(lambda: view.table.model().rowCount() == 2_000, timeout=3000)


def test_ctrl_f_focuses_the_filter_box(view, qtbot):
    view.table.setFocus()
    QTest.keyClick(view, Qt.Key_F, Qt.ControlModifier)
    assert view.filter_box.hasFocus()


def test_escape_clears_the_filter(view, qtbot):
    QTest.keyClicks(view.filter_box, "login")
    qtbot.waitUntil(lambda: view.table.model().rowCount() < 2_000, timeout=3000)
    QTest.keyClick(view.filter_box, Qt.Key_Escape)
    qtbot.waitUntil(lambda: view.table.model().rowCount() == 2_000, timeout=3000)


def test_every_column_sorts_both_ways(view):
    model = view.table.model()
    for col in model.columns:
        model.sort_by(col.key, False)
        model.sort_by(col.key, True)
    assert model.rowCount() == 2_000


def test_an_emptied_filter_offers_a_way_back(view, qtbot):
    QTest.keyClicks(view.filter_box, "zzzz-nothing-matches")
    qtbot.waitUntil(lambda: view.table.model().rowCount() == 0, timeout=3000)
    assert "Clear filters" in view.table.empty_state_text()
    view.clear_all_filters()
    assert view.table.model().rowCount() == 2_000
    assert "Clear filters" not in view.count_label.text()


def test_zero_records_after_a_scan_that_found_nothing_reads_differently_from_an_emptied_filter(
        qtbot):
    v = RecoveryView()
    v.set_records([])
    qtbot.addWidget(v)
    assert "Clear filters" not in v.count_label.text()


# --- the genuine empty state: two DIFFERENT legitimate reasons -------------

def test_before_any_scan_the_genuine_empty_state_says_no_scan_has_run(qtbot):
    v = RecoveryView()
    qtbot.addWidget(v)
    v.set_records([], note=NOT_SCANNED_NOTE)

    assert v.table.showing_genuine_empty_state() is True
    assert v.table.empty_state_text() == NOT_SCANNED_NOTE


def test_after_a_scan_that_found_nothing_the_reason_differs_from_not_scanned_yet(qtbot):
    """SCAN_FOUND_NOTHING_NOTE, not NOT_SCANNED_NOTE -- an examiner who
    already ran the scan must not be told to go run it, and one who has
    not must not be told the scan already came back empty."""
    v = RecoveryView()
    qtbot.addWidget(v)
    v.set_records([], note=None)  # MainWindow's own shape for this case

    assert v.table.showing_genuine_empty_state() is True
    assert v.table.empty_state_text() == SCAN_FOUND_NOTHING_NOTE
    assert v.table.empty_state_text() != NOT_SCANNED_NOTE


def test_a_populated_scan_result_shows_no_genuine_empty_state(view):
    assert view.table.showing_genuine_empty_state() is False


def test_filtering_the_populated_view_to_zero_never_trips_the_genuine_empty_state(view, qtbot):
    QTest.keyClicks(view.filter_box, "zzzz-nothing-matches")
    qtbot.waitUntil(lambda: view.table.model().rowCount() == 0, timeout=3000)

    assert view.table.showing_genuine_empty_state() is False
    assert view.table.empty_state_text() == view.table.empty_message()  # F17
    assert "Clear filters" in view.table.empty_state_text()


def test_a_note_survives_filtering_and_clearing(qtbot):
    """Mirrors test_wiring.py's
    test_live_only_note_survives_filtering_and_navigation for History --
    a note passed to set_records() must still be on screen after a filter
    keystroke, not just in the instant right after it was set."""
    v = RecoveryView()
    v.set_records(_rows(200), note="180 live, 20 recovered")
    qtbot.addWidget(v)
    assert "180 live, 20 recovered" in v.count_label.text()

    QTest.keyClicks(v.filter_box, "login")
    qtbot.waitUntil(lambda: v.table.model().rowCount() < 200, timeout=3000)
    assert "180 live, 20 recovered" in v.count_label.text()

    v.clear_all_filters()
    assert "180 live, 20 recovered" in v.count_label.text()


def test_typed_filter_text_survives_a_recovery_merges_fresh_set_records_call(qtbot):
    """set_records() always builds a brand new model (RecordsTable.
    set_records' own docstring) -- exactly what happens when a second
    recovery scan merges newly carved rows into what is already on
    screen, or a second Open Evidence reloads the exhibit. Left alone,
    the box kept showing the examiner's typed search term while the
    fresh model silently stopped applying it: box, count line, and model
    all told a different story. This project has already fixed four
    separate "filter that silently matches nothing" bugs -- this is the
    same family, just reached through a data refresh instead of a header
    funnel."""
    v = RecoveryView()
    v.set_records(_rows(200))
    qtbot.addWidget(v)
    v.filter_box.setText("login")
    v.table.model().set_text("login")
    shown_before = v.table.model().rowCount()
    assert 0 < shown_before < 200

    v.set_records(_rows(260))  # a fresh model -- what a merged re-scan does

    assert v.filter_box.text() == "login"  # the box is not silently cleared
    model = v.table.model()
    shown_after = model.rowCount()
    assert 0 < shown_after < 260
    for i in range(shown_after):
        assert "login" in model.row_at(i)["CleanUrl"]
    assert v.count_label.text() == "{:,} of {:,} recovered records".format(shown_after, 260)  # the unit is named


def test_the_hidden_columns_note_looks_like_every_other_views(view, qtbot):
    """It was a plain, larger label in the chip row; every other view shows
    the same fact as a small pill under the count."""
    from webcache.views.history import HistoryView
    other = HistoryView()
    qtbot.addWidget(other)
    assert view.identical_chip.styleSheet() == other._constant_chip.styleSheet()
    assert view.identical_chip.styleSheet()


def test_an_empty_hidden_columns_note_takes_no_room(qtbot):
    v = RecoveryView()
    qtbot.addWidget(v)
    v.set_records([])
    assert not v.identical_chip.isVisibleTo(v)
