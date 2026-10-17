"""The case-notes bar: tags and comments on the record in front of the
examiner, one click each, saved to the case file as they are made."""
import pytest

from webcache.engine.case_db import CaseDb
from webcache.shell import case_notes
from webcache.shell.case_notes_bar import CaseNotesBar
from tests.test_case_notes import _live


@pytest.fixture
def case(tmp_path):
    db = CaseDb().open(str(tmp_path / "case.wccase"))
    yield db
    db.close()


def _bar(qtbot, case, rows):
    bar = CaseNotesBar(case, rows, author="J. Examiner")
    qtbot.addWidget(bar)
    return bar


def test_a_preset_tag_is_one_click_on_and_one_click_off(qtbot, case):
    bar = _bar(qtbot, case, [_live(1)])
    seen = []
    bar.changed.connect(lambda: seen.append(1))
    bar.tag_button("Relevant").click()
    assert case_notes.tags_of(case, _live(1)) == ["Relevant"]
    assert bar.tag_button("Relevant").isChecked()
    bar.tag_button("Relevant").click()
    assert case_notes.tags_of(case, _live(1)) == []
    assert seen == [1, 1]


def test_a_new_tag_is_typed_once_and_then_offered(qtbot, case):
    bar = _bar(qtbot, case, [_live(1)])
    bar.new_tag_box.setText("Exfil")
    bar.new_tag_box.returnPressed.emit()
    assert case_notes.tags_of(case, _live(1)) == ["Exfil"]
    assert bar.tag_button("Exfil").isChecked()
    assert bar.new_tag_box.text() == ""


def test_a_comment_is_added_with_enter_and_listed(qtbot, case):
    bar = _bar(qtbot, case, [_live(1)])
    bar.comment_box.setText("Seen in two logs")
    bar.comment_box.returnPressed.emit()
    assert [c["comment"] for c in case_notes.comments_of(case, _live(1))] == [
        "Seen in two logs"]
    assert "Seen in two logs" in bar.comments_text()
    assert "J. Examiner" in bar.comments_text()
    assert bar.comment_box.text() == ""


def test_a_selection_shows_how_many_carry_each_tag(qtbot, case):
    case_notes.set_tag(case, [_live(1)], "Suspicious", True)
    bar = _bar(qtbot, case, [_live(1), _live(2)])
    button = bar.tag_button("Suspicious")
    assert not button.isChecked(), "only one of two carries it"
    assert "1 of 2" in button.toolTip()
    button.click()
    assert case_notes.tag_counts(case, [_live(1), _live(2)]) == {
        "Suspicious": 2}


def test_a_row_that_is_not_a_record_says_why_it_cannot_be_tagged(qtbot, case):
    bar = _bar(qtbot, case, [{"Domain": "a.test"}])
    assert not bar.tag_button("Relevant").isVisible()
    assert "not a record" in bar.status_text().lower()


def test_without_a_case_file_the_bar_says_so(qtbot):
    bar = CaseNotesBar(None, [_live(1)])
    qtbot.addWidget(bar)
    assert "case file" in bar.status_text().lower()


def test_the_record_dialog_carries_the_notes_bar(qtbot, case):
    from webcache.shell.record_detail import RecordDetailDialog
    from tests.test_detail_fields import history_row
    row = history_row()
    row["_record"] = dict(row.get("_record") or {}, ContainerId=6, EntryId=9)
    dlg = RecordDetailDialog(row, case=case, author="J. Examiner")
    try:
        dlg.notes_bar.tag_button("Suspicious").click()
        assert case_notes.tags_of(case, row) == ["Suspicious"]
    finally:
        dlg.close()


def test_the_window_opens_the_dialog_with_the_case(qtbot, tmp_path):
    """MainWindow hands its open case and the examiner's name to every
    record dialog it opens."""
    from webcache.shell import main_window as mw
    win = mw.MainWindow()
    qtbot.addWidget(win)
    win._case = CaseDb().open(str(tmp_path / "c.wccase"))
    win._case.set_meta("examiner", "J. Examiner")
    dlg = win._show_record_detail(_live(5))
    try:
        assert dlg.notes_bar._case is win._case
        assert dlg.notes_bar._author == "J. Examiner"
    finally:
        dlg.close()
        win._case.close()


# --- the grid's right-click menu -----------------------------------------

def _grid(qtbot, rows):
    from webcache.widgets.column_spec import Column
    from webcache.widgets.records_table import RecordsTable
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records([Column("CleanUrl", "Address", 300, kind="url")], rows)
    return t


def _menu_actions(menu):
    out = {}
    for action in menu.actions():
        if action.menu() is not None:
            out[action.text()] = {a.text(): a for a in action.menu().actions()}
        else:
            out[action.text()] = action
    return out


def test_right_click_tags_the_whole_selection(qtbot, case):
    from PySide6.QtCore import QItemSelectionModel
    rows = [_live(1), _live(2), _live(3)]
    t = _grid(qtbot, rows)
    t.notes_provider = lambda rs: (case_notes.known_tags(case),
                                   case_notes.tag_counts(case, rs), len(rs))
    sel = t.selectionModel()
    for r in (0, 2):
        sel.select(t.model().index(r, 0),
                   QItemSelectionModel.Select | QItemSelectionModel.Rows)
    seen = []
    t.tagRequested.connect(lambda rs, tag, on: seen.append((rs, tag, on)))
    menu = t._build_context_menu(t.model().index(0, 0))
    tag_menu = _menu_actions(menu)["Tag 2 records"]
    tag_menu["Relevant"].trigger()
    (picked, tag, on), = seen
    assert [r["CleanUrl"] for r in picked] == [rows[0]["CleanUrl"],
                                               rows[2]["CleanUrl"]]
    assert (tag, on) == ("Relevant", True)


def test_without_a_case_the_menu_offers_no_tagging(qtbot):
    t = _grid(qtbot, [_live(1)])
    menu = t._build_context_menu(t.model().index(0, 0))
    assert not any(k.startswith("Tag") for k in _menu_actions(menu))


def test_the_window_saves_a_tag_from_the_menu_and_says_so(qtbot, tmp_path):
    from webcache.shell import main_window as mw
    win = mw.MainWindow()
    qtbot.addWidget(win)
    win._case = CaseDb().open(str(tmp_path / "c.wccase"))
    try:
        win._tag_rows([_live(1), _live(2)], "Relevant", True)
        assert case_notes.tag_counts(win._case, [_live(1), _live(2)]) == {
            "Relevant": 2}
        assert "2 records" in win.status_message()
        assert "Relevant" in win.status_message()
    finally:
        win._case.close()


def test_tags_are_never_cut_in_a_narrow_pane_they_wrap(qtbot, case):
    """A chip keeps its whole label ("Suspicious", "Not relevant") and the
    row wraps onto a second line instead of squeezing the chips."""
    bar = CaseNotesBar(case, [_live(1)], author="J", compact=True)
    qtbot.addWidget(bar)
    bar.resize(300, 400)
    bar.show()
    qtbot.waitExposed(bar)
    chips = [bar.tag_button(t) for t in case_notes.known_tags(case)]
    for chip in chips:
        assert chip.width() >= chip.sizeHint().width(), chip.text()
    rows = {chip.geometry().top() for chip in chips}
    assert len(rows) > 1
