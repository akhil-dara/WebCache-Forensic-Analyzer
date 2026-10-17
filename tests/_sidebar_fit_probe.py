"""Native probe: at the examiner's 1536x793 window (an 816 px
work area less the title bar), is every nav row -- the CASE section
included -- visible without scrolling the sidebar, and do the two foot
buttons (the theme button and Collapse) show their words and sit inside
the sidebar?

Prints FONT_MISSING, or one line of key=value facts:
  scroll_max   the nav's vertical scroll range (0 = nothing below the fold)
  last_bottom  the last nav row's bottom edge in the nav viewport
  viewport     the nav viewport's height
  pill_room / pill_need         the theme button's content width (QSS
  collapse_room / collapse_need padding applied) and what its icon and
                                text need
  collapse_bottom / sidebar_h   the Collapse button's bottom edge in the
                                sidebar, and the sidebar's height
  collapse_room_h / collapse_need_h  the Collapse button's content height
                                (QSS padding applied) and its font's line
                                height
"""
import sys
import tempfile
from pathlib import Path

from webcache import paths

_SCRATCH = Path(tempfile.mkdtemp(prefix="sidebar-fit-"))
paths.settings_path = lambda: _SCRATCH / "settings.json"
paths.cases_dir = lambda: _SCRATCH

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QFont, QFontInfo  # noqa: E402
from PySide6.QtWidgets import (QApplication, QStyle,  # noqa: E402
                               QStyleOptionButton)


def _room(button):
    option = QStyleOptionButton()
    button.initStyleOption(option)
    return button.style().subElementRect(
        QStyle.SE_PushButtonContents, option, button).width()


def _room_h(button):
    option = QStyleOptionButton()
    button.initStyleOption(option)
    return button.style().subElementRect(
        QStyle.SE_PushButtonContents, option, button).height()


def _need(button):
    need = button.fontMetrics().horizontalAdvance(button.text())
    if not button.icon().isNull():
        need += button.iconSize().width()
    return need


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))
    if not QFontInfo(app.font()).exactMatch():
        print("FONT_MISSING")
        return
    from webcache.shell.main_window import MainWindow
    from tests._native_screen import screen_too_small
    small = screen_too_small(app, 1536, 793)
    if small:
        print(small)
        return
    win = MainWindow()
    win.resize(1536, 793)
    win.show()
    for _ in range(20):
        app.processEvents()
    side = win.sidebar
    nav = side.nav
    last = nav.item(nav.count() - 1)
    collapse = side.collapse_button
    bottom = collapse.mapTo(side, QPoint(0, collapse.height())).y()
    print("scroll_max=%d last_bottom=%d viewport=%d pill_room=%d pill_need=%d "
          "collapse_room=%d collapse_need=%d collapse_bottom=%d sidebar_h=%d "
          "collapse_room_h=%d collapse_need_h=%d"
          % (nav.verticalScrollBar().maximum(),
             nav.visualItemRect(last).bottom(), nav.viewport().height(),
             _room(side.theme_pill), _need(side.theme_pill),
             _room(collapse), _need(collapse), bottom, side.height(),
             _room_h(collapse), collapse.fontMetrics().height()))
    win.close()


if __name__ == "__main__":
    main()
