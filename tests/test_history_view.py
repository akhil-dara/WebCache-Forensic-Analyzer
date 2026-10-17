import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from webcache.views.history import HistoryView
from tests.fixtures import make_rows


@pytest.fixture
def view(qtbot):
    v = HistoryView()
    v.set_records(make_rows(2_000))
    qtbot.addWidget(v)
    v.resize(1500, 800)
    v.show()
    qtbot.waitExposed(v)
    return v


def test_the_table_shows_every_record(view):
    assert view.table.model().rowCount() == 2_000
    assert "2,000" in view.count_label.text()


def test_carved_records_are_included(view):
    """A page that was visited and then deleted was still visited. Carved
    History records were invisible in this view for months."""
    origins = {view.table.model().row_at(i)["Origin"]
               for i in range(view.table.model().rowCount())}
    assert any(o.startswith("Carved") for o in origins)


def test_carved_records_state_their_source_file(view):
    carved = next(view.table.model().row_at(i)
                  for i in range(view.table.model().rowCount())
                  if view.table.model().row_at(i)["Origin"].startswith("Carved"))
    assert carved["Source"]


def test_typing_in_the_filter_box_narrows_the_table(view, qtbot):
    QTest.keyClicks(view.filter_box, "msn")
    qtbot.waitUntil(lambda: view.table.model().rowCount() < 2_000, timeout=3000)
    assert "of 2,000" in view.count_label.text()


def test_clearing_the_filter_box_restores_every_row(view, qtbot):
    QTest.keyClicks(view.filter_box, "msn")
    qtbot.waitUntil(lambda: view.table.model().rowCount() < 2_000, timeout=3000)
    view.filter_box.clear()
    qtbot.waitUntil(lambda: view.table.model().rowCount() == 2_000, timeout=3000)


def test_ctrl_f_focuses_the_filter_box(view, qtbot):
    view.table.setFocus()
    QTest.keyClick(view, Qt.Key_F, Qt.ControlModifier)
    assert view.filter_box.hasFocus()


def test_escape_clears_the_filter(view, qtbot):
    QTest.keyClicks(view.filter_box, "msn")
    qtbot.waitUntil(lambda: view.table.model().rowCount() < 2_000, timeout=3000)
    QTest.keyClick(view.filter_box, Qt.Key_Escape)
    qtbot.waitUntil(lambda: view.table.model().rowCount() == 2_000, timeout=3000)


def test_every_column_sorts_both_ways(view):
    model = view.table.model()
    for col in model.columns:
        model.sort_by(col.key, False)
        model.sort_by(col.key, True)
    assert model.rowCount() == 2_000


def test_the_domain_column_drills_through(view, qtbot):
    col = next(c for c in view.COLUMNS if c.key == "Domain")
    assert col.is_link
    with qtbot.waitSignal(view.drillRequested, timeout=1000) as sig:
        col.on_click(view.table.model().row_at(0))
    assert sig.args[0] == "domains"


def test_an_emptied_filter_offers_a_way_back(view, qtbot):
    """The count line beneath the filter box -- not RecordsTable.empty_
    message() called directly -- is what an examiner actually reads.
    _update_count() is the ONLY place that writes count_label, and before
    the fix in HistoryView._update_count it never consulted empty_message()
    at all: filtering to zero rows showed a bare '0 of 2,000 records' with
    no indication which filter did it or how to undo it. Asserting against
    view.count_label.text() (not view.table.empty_message()) is what makes
    this test fail if that wiring is ever removed again."""
    QTest.keyClicks(view.filter_box, "zzzz-nothing-matches")
    qtbot.waitUntil(lambda: view.table.model().rowCount() == 0, timeout=3000)
    assert "Clear filters" in view.table.empty_state_text()
    view.clear_all_filters()
    assert view.table.model().rowCount() == 2_000
    assert "Clear filters" not in view.count_label.text()


def test_zero_records_because_none_exist_reads_differently_from_an_emptied_filter(qtbot):
    """'No records' and 'your filter matched nothing' are different
    situations and must not read the same on screen -- pinned at the
    HistoryView level (not just RecordsTable.empty_message(), which
    test_records_table.py already covers) because it is count_label.text()
    an examiner actually looks at."""
    v = HistoryView()
    v.set_records([])
    qtbot.addWidget(v)
    assert "Clear filters" not in v.count_label.text()


# --- header basis badges: real evidence_model.basis_of(), not a mock ------

def test_columns_are_annotated_with_a_real_basis_badge(view):
    """history.py's own annotation loop, driven by evidence_model.
    basis_of() -- never a hard-coded per-column table (see column_spec.
    Column's docstring on why this cannot live in the widget itself)."""
    address = next(c for c in view.COLUMNS if c.key == "CleanUrl")
    assert address.badge == "DER"
    assert "Derived" in address.badge_tooltip

    # Origin is graded CARVED in evidence_model.py -- a row's live/carved
    # status IS the recovery act, the same basis Confidence/Offset/Method
    # carry -- so its real badge is CARV, not the design mockup's OBS. This
    # pins that as the CORRECT, honest answer, not a bug to "fix" toward
    # matching the mockup's placeholder letters.
    origin = next(c for c in view.COLUMNS if c.key == "Origin")
    assert origin.badge == "CARV"
    assert "Carved" in origin.badge_tooltip


def test_a_column_declaring_no_field_gets_no_badge(view):
    title = next(c for c in view.COLUMNS if c.key == "Title")
    assert title.field is None
    assert title.badge is None


# --- quick-filter chips -----------------------------------------------------

def test_inprivate_chip_narrows_to_inprivate_rows_only(view):
    total = view.table.model().rowCount()
    view.chip_inprivate.setChecked(True)
    shown = view.table.model().rowCount()
    assert 0 < shown < total
    assert all(view.table.model().row_at(i)["IsInPrivate"]
              for i in range(shown))
    view.chip_inprivate.setChecked(False)
    assert view.table.model().rowCount() == total


def test_has_search_terms_chip_narrows_to_rows_carrying_a_search_term(view):
    total = view.table.model().rowCount()
    view.chip_search_terms.setChecked(True)
    shown = view.table.model().rowCount()
    assert 0 < shown < total
    assert all(view.table.model().row_at(i)["SearchTerms"]
              for i in range(shown))
    view.chip_search_terms.setChecked(False)
    assert view.table.model().rowCount() == total


def test_local_files_chip_narrows_to_local_file_rows_only(view):
    total = view.table.model().rowCount()
    view.chip_local_files.setChecked(True)
    shown = view.table.model().rowCount()
    assert 0 < shown < total
    assert all(view.table.model().row_at(i)["IsLocalFile"]
              for i in range(shown))
    view.chip_local_files.setChecked(False)
    assert view.table.model().rowCount() == total


def test_toggling_a_chip_updates_the_count_line(view):
    before = view.count_label.text()
    view.chip_inprivate.setChecked(True)
    after = view.count_label.text()
    assert after != before
    assert "of 2,000" in after
    view.chip_inprivate.setChecked(False)
    assert "of 2,000" not in view.count_label.text()


def test_a_checked_chip_is_named_in_the_filter_description(view):
    """The filter chip line (record_model.chip_text(), shown beside the
    count) must keep telling the truth about what is in force -- a chip
    that filters silently, with nothing on screen naming it, is exactly
    the "filter that silently matches nothing [an examiner cannot audit]"
    class of bug this project has already fixed four times."""
    view.chip_search_terms.setChecked(True)
    assert "Has search terms" in view._filter_desc_label.text()


def test_clear_all_filters_unchecks_every_chip_and_restores_every_row(view):
    view.chip_inprivate.setChecked(True)
    view.chip_search_terms.setChecked(True)
    view.chip_local_files.setChecked(True)
    assert view.table.model().rowCount() < 2_000

    view.clear_all_filters()

    assert view.chip_inprivate.isChecked() is False
    assert view.chip_search_terms.isChecked() is False
    assert view.chip_local_files.isChecked() is False
    assert view.table.model().rowCount() == 2_000


def test_a_checked_chip_survives_a_second_set_records_call(view):
    """A recovery scan finishing calls HistoryView.set_records() again with
    a BRAND NEW model (RecordsTable.set_records always builds one -- see
    its own docstring). A chip left checked must keep filtering the NEW
    rows, not silently point at a filter the fresh model never applied --
    the count line would read as though every row matched while the chip
    still claimed only InPrivate ones were shown."""
    view.chip_inprivate.setChecked(True)
    assert 0 < view.table.model().rowCount() < 2_000

    view.set_records(make_rows(500, seed=99))

    assert view.chip_inprivate.isChecked() is True
    shown = view.table.model().rowCount()
    assert 0 < shown < 500
    assert all(view.table.model().row_at(i)["IsInPrivate"] for i in range(shown))


def test_an_unchecked_chip_stays_unchecked_across_set_records(view):
    """The no-op path: nothing checked, nothing should get filtered in a
    freshly loaded row set either."""
    view.set_records(make_rows(300, seed=3))
    assert view.chip_inprivate.isChecked() is False
    assert view.chip_search_terms.isChecked() is False
    assert view.chip_local_files.isChecked() is False
    assert view.table.model().rowCount() == 300


def test_an_exhibit_with_no_history_records_shows_a_real_empty_state(qtbot):
    """An exhibit whose History container simply held nothing live is a
    real, legitimate outcome -- not a decode failure and not a filter
    hiding rows. This is the sentence an examiner reads for it."""
    v = HistoryView()
    v.set_records([])
    qtbot.addWidget(v)
    assert v.table.showing_genuine_empty_state() is True
    assert "History" in v.table.empty_state_text()
