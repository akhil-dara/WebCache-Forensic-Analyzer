"""Tab through the window: every stop shows where the keyboard is, no stop
is empty, and the sidebar's order is the order on screen."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from webcache.shell import theme
from webcache.shell.main_window import MainWindow


def _ring_on_focus(widget, other):
    other.setFocus()
    QApplication.processEvents()
    before = widget.grab().toImage().pixelColor(widget.width() // 2, 0)
    widget.setFocus()
    QApplication.processEvents()
    after = widget.grab().toImage().pixelColor(widget.width() // 2, 0)
    return before, after


def test_the_outline_export_button_shows_the_ring(qtbot):
    theme.apply(QApplication.instance(), "dark")
    host = QWidget()
    QVBoxLayout(host)
    button = QPushButton("Export view (392)")
    button.setProperty("outline", True)
    other = QPushButton("elsewhere")
    host.layout().addWidget(button)
    host.layout().addWidget(other)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    host.activateWindow()
    before, after = _ring_on_focus(button, other)
    assert after == theme.color("primary"), (before.name(), after.name())
    assert before != after


def test_the_theme_toggle_shows_the_ring(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.activateWindow()
    before, after = _ring_on_focus(w.sidebar.theme_pill,
                                   w.sidebar.collapse_button)
    assert after == theme.color("primary"), (before.name(), after.name())


def test_the_page_scroll_area_is_not_a_tab_stop(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    assert w._content_scroll.focusPolicy() == Qt.NoFocus


def test_open_database_comes_first_in_the_sidebar(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.activateWindow()
    w.sidebar.open_button.setFocus()
    QApplication.processEvents()
    w.focusNextChild()
    QApplication.processEvents()
    assert QApplication.focusWidget() is w.sidebar.theme_pill


def _assert_ring(qtbot, view, target):
    """`view` hosted whole (its parts stay owned by it); `target` focused."""
    theme.apply(QApplication.instance(), "dark")
    host = QWidget()
    QVBoxLayout(host)
    other = QPushButton("elsewhere")
    host.layout().addWidget(view)
    host.layout().addWidget(other)
    host.resize(900, 700)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    host.activateWindow()
    target.setFocusPolicy(Qt.StrongFocus) if target.focusPolicy() == Qt.NoFocus else None
    before, after = _ring_on_focus(target, other)
    assert after == theme.color("primary"), (before.name(), after.name())
    assert before != after


def test_the_table_browser_list_shows_the_ring(qtbot):
    from webcache.views.browser import TableBrowserView
    view = TableBrowserView()
    view.table_list.addItem("Container_1")
    _assert_ring(qtbot, view, view.table_list)


def test_the_headers_pane_shows_the_ring(qtbot):
    from webcache.views.headers import HeaderPane
    pane = HeaderPane()
    pane.set_row({"CleanUrl": "https://example.test/", "ContainerName": "Content",
                  "ResponseHeaders": {"_status_line": "HTTP/1.1 200 OK",
                                      "Content-Type": "text/html"}})
    _assert_ring(qtbot, pane, pane.scroll)


def test_the_export_page_shows_the_ring(qtbot):
    from webcache.views.export import ExportView
    view = ExportView()
    _assert_ring(qtbot, view, view.scroll)
