""""""
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from webcache.shell import theme
from webcache.shell.main_window import MainWindow
from webcache.views.history import HistoryView
from tests.fixtures import make_rows


@pytest.fixture
def view(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records(make_rows(50))
    v.resize(1500, 800)
    v.show()
    qtbot.waitExposed(v)
    return v


def test_tab_leaves_the_grid(view):
    view.table.setFocus()
    view.table.setCurrentIndex(view.table.model().index(0, 0))
    QTest.keyClick(view.table, Qt.Key_Tab)
    assert QApplication.focusWidget() is not view.table


def test_a_focused_control_has_a_visible_ring(view):
    theme.apply(QApplication.instance())
    assert ":focus" in view.chip_inprivate.styleSheet()
    assert "QPushButton:focus" in QApplication.instance().styleSheet()


def test_a_headings_tooltip_explains_its_badge(view):
    model = view.table.model()
    section = [c.key for c in model.columns].index("VisitCount")
    tip = model.headerData(section, Qt.Horizontal, Qt.ToolTipRole)
    # The browser's own visit counter: its meaning is documented outside
    # Microsoft, so the badge is INF and the tooltip says why.
    assert "INF (Inferred)" in tip


def test_a_badge_past_the_viewport_edge_moves_in_or_is_not_drawn(view):
    header = view.table.horizontalHeader()
    section = QRectF(900, 0, 300, 28)
    chip = header._chip_rect(section, "DER", visible_right=1100)
    assert chip is not None and chip.right() <= 1100
    assert header._chip_rect(section, "DER", visible_right=905) is None


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_help_explains_the_tool_the_keys_and_the_badges(win):
    from webcache import provenance
    assert provenance.TOOL_VERSION in win.help_about_action.data()
    dialog = win._show_help("About", win.help_about_action.data())
    assert dialog.isVisible()
    assert "Alt+Left" in win.help_shortcuts_action.data()
    legend = win.help_badges_action.data()
    for short in ("OBS", "DER", "INF", "CARV"):
        assert short in legend
    for origin in ("Live", "Mixed", "Recovered only"):
        assert origin in legend
    help_action = win.menuBar().actions()[-1]
    assert help_action.text().replace("&", "") == "Help"
    assert len(help_action.menu().actions()) >= 3


def test_help_about_names_no_url(win):
    assert "http" not in win.help_about_action.data().lower()


def test_f1_on_an_empty_cell_says_why_and_what_it_would_hold(win):
    history = win._ensure_view_built("history")
    history.set_records([dict(make_rows(1)[0], Title="",
                              Origin="Live record")])
    win.go_to("history")
    text = win._explain_text_for(history.table.model().row_at(0), "Title")
    assert "empty" in text.lower()
    assert "would hold" in text.lower()
    assert "Page title" in text or "page title" in text
