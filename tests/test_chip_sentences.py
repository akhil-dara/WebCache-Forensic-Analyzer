"""A chip is described by what it does, never by
its implementation -- "duplicate carved copies hidden", not "Copies: does
not contain 'copy '" -- in the filter sentence and in an emptied grid."""
from webcache.shell import recovery_loader
from webcache.views.history import HistoryView
from tests.test_copies_and_deleted_records import COPIES, UNIQUE, _engine
from tests.test_visit_twins import build_parser
from webcache.shell.evidence_loader import history_rows_from_parser


def test_hide_duplicate_copies_is_said_in_words(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(recovery_loader.carved_history_rows(
        _engine(COPIES + [UNIQUE])))
    view.chip_hide_copies.click()
    text = view._filter_desc_label.text()
    assert "duplicate carved copies hidden" in text, text
    assert "does not contain" not in text


def test_an_emptied_grid_says_it_in_words_too(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(recovery_loader.carved_history_rows(
        _engine(COPIES + [UNIQUE])))
    view.chip_hide_copies.click()
    view.table.model().set_text("no-such-address-anywhere")
    message = view.table.empty_message()
    assert "duplicate carved copies hidden" in message, message
    assert "does not contain" not in message


def test_one_row_per_visit_is_said_in_words(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(history_rows_from_parser(build_parser()))
    view.chip_one_row_per_visit.click()
    text = view._filter_desc_label.text()
    assert "does not contain" not in text, text
    assert "MSHist" in text
