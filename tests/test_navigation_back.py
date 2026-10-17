"""A drill always has a way back, and says where it came from."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView

from webcache.provenance import EvidenceSet
from webcache.shell.main_window import MainWindow
from webcache.shell.record_kinds import K_HISTORY

_PATH = "C:/case/WebCacheV01.dat"


class _Parser:
    all_entries = []
    db = None
    db_path = _PATH
    containers_meta = []
    container_type_map = {}


def _row(i):
    url = "https://example.test/p%d" % i
    return {"CleanUrl": url, "Domain": "example.test", "Origin": "Live record",
            "_kind": K_HISTORY,
            "_record": {"ContainerId": 1, "EntryId": i, "Url": url,
                        "CleanUrl": url}}


ROWS = [_row(i) for i in range(300)]
ROW = ROWS[7]


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    w._on_evidence_loaded({"rows": [], "parser": _Parser()},
                          EvidenceSet([_PATH], {_PATH: 1}, {_PATH: "a" * 64}))
    w._ensure_view_built("history").set_records(ROWS)
    w.go_to("history")
    return w


def test_show_in_database_table_can_be_undone_with_back(win):
    win.show_in_database_table(ROW)
    assert win.current_key == "browser"
    crumb = win.nav_bar.crumb_label.text()
    assert crumb.startswith("from: History record")
    assert win.nav_bar.back_button.isEnabled()
    assert win.go_back()
    assert win.current_key == "history"


def test_the_breadcrumb_names_the_row_kind_and_identity(win):
    history = win._ensure_view_built("history")
    history.table.selectRow(7)
    win.show_in_database_table(ROW)
    crumb = win.nav_bar.crumb_label.text()
    assert crumb == ("from: History record 8 (on screen): "
                     + ROW["CleanUrl"])
    assert ROW["CleanUrl"] in win.nav_bar.crumb_label.text()


def test_the_breadcrumb_is_plain_copyable_text_that_opens_nothing(win):
    from PySide6.QtCore import Qt as _Qt
    from webcache.widgets.wrapping_text import WrappingText
    win.show_in_database_table(ROW)
    label = win.nav_bar.crumb_label
    assert isinstance(label, WrappingText)
    assert label.textInteractionFlags() == _Qt.TextSelectableByMouse
    assert "<a " not in label.toHtml()
    assert ROW["CleanUrl"] in label.toolTip()
    assert "<a " not in label.toolTip()


def test_a_domain_drill_crumb_names_the_domain(win):
    win._drill_to_domain("domains", ROW)
    assert win.current_key == "domains"
    assert "example.test" in win.nav_bar.crumb_label.text()
    assert win.nav_bar.crumb_label.text().startswith("from: History")


def test_every_navigation_is_recorded_sidebar_clicks_included(win):
    keys = [win.nav.item(i).data(Qt.UserRole) for i in range(win.nav.count())]
    win.nav.setCurrentRow(keys.index("domains"))
    assert win.current_key == "domains"
    win.nav.setCurrentRow(keys.index("timeline"))
    assert win.go_back() and win.current_key == "domains"
    assert win.go_back() and win.current_key == "history"


def test_the_back_tooltip_says_where_back_goes(win):
    tip = win.nav_bar.back_button.toolTip()
    assert "Nothing to go back to" in tip or "Back to" in tip
    win.show_in_database_table(ROW)
    assert "Back to History" in win.nav_bar.back_button.toolTip()
    win.go_back()
    win.go_to("domains")
    assert "Back to History" in win.nav_bar.back_button.toolTip()
    win.go_to("search")
    assert "Back to Domains" in win.nav_bar.back_button.toolTip()


def test_the_back_button_is_an_app_secondary_button_with_a_focus_ring(qtbot):
    from PySide6.QtWidgets import QApplication, QPushButton
    from webcache.shell import theme
    w = MainWindow()
    qtbot.addWidget(w)
    button = w.nav_bar.back_button
    assert isinstance(button, QPushButton)
    assert button.focusPolicy() != Qt.NoFocus
    assert not button.property("accent") and not button.property("outline")
    app = QApplication.instance()
    for name in ("dark", "light"):
        theme.apply(app, name)
        sheet = app.styleSheet()
        assert 'QPushButton[navback="true"]:focus' in sheet
        assert 'QPushButton[navback="true"]:disabled' in sheet
        w.nav_bar.refresh_theme()
        button.setEnabled(True)
        on = button.grab().toImage()
        button.setEnabled(False)
        off = button.grab().toImage()
        assert on != off


def test_alt_left_goes_back(win):
    win.show_in_database_table(ROW)
    QTest.keyClick(win, Qt.Key_Left, Qt.AltModifier)
    assert win.current_key == "history"


def test_backspace_goes_back_from_a_grid_but_not_from_a_text_box(win, qtbot):
    win.show_in_database_table(ROW)
    browser = win._ensure_view_built("browser")
    browser.grid.setFocus()
    QTest.keyClick(browser.grid, Qt.Key_Backspace)
    assert win.current_key == "history"
    win.go_to("browser")
    box = win._ensure_view_built("browser").filter_box
    box.setFocus()
    QTest.keyClick(box, Qt.Key_Backspace)
    assert win.current_key == "browser"


def test_back_is_disabled_with_nowhere_to_go(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    assert not w.back_action.isEnabled()
    assert not w.nav_bar.back_button.isEnabled()
    assert not w.go_back()


def test_a_plain_visit_to_table_browser_clears_the_locate_note(win):
    win.show_in_database_table(ROW)
    browser = win._ensure_view_built("browser")
    assert browser._note_label.text()
    win.go_to("history")
    win.go_to("browser")
    assert browser._note_label.text() == ""
    assert win.nav_bar.crumb_label.text() == ""


def test_back_restores_the_selection_and_the_scroll_position(win, qtbot):
    history = win._ensure_view_built("history")
    table = history.table
    table.selectRow(120)
    table.scrollTo(table.model().index(120, 0), QAbstractItemView.PositionAtTop)
    top = table.verticalScrollBar().value()
    assert top > 0
    win.show_in_database_table(ROWS[120])
    # Something else disturbs the view while the examiner is away.
    table.clearSelection()
    table.verticalScrollBar().setValue(0)
    win.go_back()
    qtbot.waitUntil(lambda: table.verticalScrollBar().value() == top,
                    timeout=2000)
    assert [ix.row() for ix in table.selectionModel().selectedRows()] == [120]


def test_a_locate_answer_after_back_selects_nothing(qtbot, monkeypatch):
    from tests.test_show_in_table import _late_answer, _locating_window
    w, runners = _locating_window(qtbot, monkeypatch)
    w.go_back()
    browser = w._ensure_view_built("browser")
    _late_answer(runners[0])
    assert browser.grid.selectedIndexes() == []
    assert w.current_key != "browser"


def test_a_new_exhibit_clears_the_stack(win):
    win.show_in_database_table(ROW)
    assert win.nav_bar.back_button.isEnabled()
    win._on_evidence_loaded({"rows": [], "parser": _Parser()},
                            EvidenceSet([_PATH], {_PATH: 1},
                                        {_PATH: "b" * 64}))
    assert not win.nav_bar.back_button.isEnabled()
    assert not win.back_action.isEnabled()
    assert not win.go_back()


def _domain_window(win):
    from webcache.shell import domain_loader
    live = [{"Url": "https://a.example.test/p%d" % i,
             "CleanUrl": "https://a.example.test/p%d" % i,
             "ContainerType": "History", "ContainerId": 1, "EntryId": i,
             "AccessCount": 1, "FileSize": 0} for i in range(60)]
    live += [{"Url": "https://b.example.test/x", "CleanUrl":
              "https://b.example.test/x", "ContainerType": "History",
              "ContainerId": 1, "EntryId": 900, "AccessCount": 1,
              "FileSize": 0}]
    view = win._ensure_view_built("domains")
    view.set_records(domain_loader.domain_rows(live, ()))
    return view


def test_back_restores_the_domain_and_its_pane_row(win, qtbot):
    view = _domain_window(win)
    win.go_to("domains")
    assert view.show_domain("a.example.test")
    pane = view.pane.table
    pane.selectRow(30)
    from PySide6.QtWidgets import QAbstractItemView
    pane.scrollTo(pane.model().index(30, 0), QAbstractItemView.PositionAtTop)
    top = pane.verticalScrollBar().value()
    win.go_to("history")
    # Elsewhere, the examiner's drill re-points Domains at another domain.
    assert view.show_domain("b.example.test")
    win.go_back()
    assert win.current_key == "domains"
    qtbot.waitUntil(lambda: view.selected_domain() == "a.example.test",
                    timeout=2000)
    qtbot.waitUntil(
        lambda: [i.row() for i in pane.selectionModel().selectedRows()]
        == [30], timeout=2000)
    if top:
        qtbot.waitUntil(lambda: pane.verticalScrollBar().value() == top,
                        timeout=2000)


def test_back_restores_the_selected_search_hit(win, qtbot):
    from tests.test_search_view import _StubParser, _rows
    from webcache.shell import search_loader
    view = win._ensure_view_built("search")
    view.set_parser(_StubParser())
    view.show_results(search_loader.SearchQuery("needle"), {"rows": _rows(6)})
    win.go_to("search")
    view.table.selectRow(3)
    hit = view._current_row
    assert hit is not None
    win.go_to("history")
    # The same hits come back in another order while the examiner is away.
    rows = list(view.table.model().filter.visible())
    view.show_results(search_loader.SearchQuery("needle"),
                      {"rows": list(reversed(rows))})
    assert view._current_row is not hit
    win.go_back()
    qtbot.waitUntil(lambda: view._current_row is hit, timeout=2000)
    assert [i.row() for i in view.table.selectionModel().selectedRows()] == [2]


# --- a hit lands on its row ---------------------------------------------

def test_a_hits_table_link_and_enter_land_on_the_row(win, monkeypatch):
    from tests.test_hit_landing_and_filetimes import HIT
    browser = win._ensure_view_built("browser")
    landed = []
    monkeypatch.setattr(browser, "show_row",
                        lambda table, ordinal, page=None:
                        landed.append((table, ordinal)) or True)
    win._drill_table_to_browser("browser", HIT)
    assert landed == [("Container_2", 2)]
    assert win.current_key == "browser"
    assert "Row 3" in browser._note_label.text()
    win.go_to("search")
    win._open_search_hit(HIT)
    assert landed[-1] == ("Container_2", 2)


def test_a_recovered_hit_opens_as_a_record(win, monkeypatch):
    opened = []
    monkeypatch.setattr(win, "_show_record_detail", opened.append)
    hit = {"Table": "Recovered records", "Row": 1, "Origin":
           "Carved (deleted/unflushed)", "_kind": "carved_struct",
           "_record": {"Url": "https://example.test/x",
                       "RecoverySource": "unallocated page"}}
    win._open_search_hit(hit)
    assert opened == [hit]


def test_a_keyed_hit_lands_on_the_keyed_row_not_its_row_number(win, monkeypatch):
    """A deleted stub before the hit shifts positions: the search's own
    count (Row 3) and the key's ordinal (7) disagree, and the key wins."""
    from tests.test_hit_landing_and_filetimes import KEYED_HIT
    browser = win._ensure_view_built("browser")
    asked = []
    monkeypatch.setattr(win._parser, "find_row_ordinal",
                        lambda table, key: asked.append((table, key)) or 7,
                        raising=False)
    landed = []
    monkeypatch.setattr(browser, "show_row",
                        lambda table, ordinal, page=None:
                        landed.append((table, ordinal)) or True)
    win._drill_table_to_browser("browser", KEYED_HIT)
    assert asked == [("Container_2", {"EntryId": 4401})]
    assert landed == [("Container_2", 7)]


def test_a_keyed_hit_in_a_large_table_goes_through_the_worker(win, monkeypatch):
    from tests.test_hit_landing_and_filetimes import KEYED_HIT
    from webcache.shell import row_locate_runner
    monkeypatch.setattr(row_locate_runner, "needs_worker", lambda p, t: True)
    started = []
    monkeypatch.setattr(win, "_start_row_locate",
                        lambda ref, browser: started.append(ref))
    win._open_search_hit(KEYED_HIT)
    assert [(r.table, r.key) for r in started] == [
        ("Container_2", {"EntryId": 4401})]
