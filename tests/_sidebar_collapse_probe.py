"""Standalone native probe for test_sidebar_collapse.py's geometry checks.

The collapsed strip once hid every nav icon at x = 87 of a 52 px strip,
and drew its expand glyph into a button whose QSS padding left it no
room -- while every isVisible() assert passed. Geometry is the only honest
check, and the button padding is only real with the real style and font,
so this runs as a SUBPROCESS on the platform's own plugin (see
_recovery_fit_probe.py for why the offscreen one cannot be used).

Prints "FONT_MISSING", or one "KEY=value" line per fact:
  STRIP=<w>              the collapsed sidebar's width
  ICON <key> <l> <r> <w> each nav icon's left/right edge in the sidebar
                         and its painted pixmap width
  BUTTON <name> <room> <need>
                         the width the style leaves for a foot button's
                         content (SE_PushButtonContents, QSS padding
                         applied) and the width its icon or text needs
"""
import sys
import tempfile
from pathlib import Path

from webcache import paths

_SCRATCH = Path(tempfile.mkdtemp(prefix="sidebar-probe-"))
paths.settings_path = lambda: _SCRATCH / "settings.json"
paths.cases_dir = lambda: _SCRATCH

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QFont, QFontInfo  # noqa: E402
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QStyle,  # noqa: E402
                               QStyleOptionButton, QWidget)

from webcache.shell import sidebar as sb, theme  # noqa: E402
from webcache.shell.main_window import NAV_SECTIONS  # noqa: E402


def _pump(app, n=10):
    for _ in range(n):
        app.processEvents()


def _room(button):
    option = QStyleOptionButton()
    button.initStyleOption(option)
    return button.style().subElementRect(
        QStyle.SE_PushButtonContents, option, button).width()


def _need(button):
    if button.text():
        return button.fontMetrics().horizontalAdvance(button.text())
    if not button.icon().isNull():
        return button.iconSize().width()
    return 1 << 20            # nothing to show at all is never enough room


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))
    if not QFontInfo(app.font()).exactMatch():
        print("FONT_MISSING")
        return
    from tests._native_screen import screen_too_small
    small = screen_too_small(app, 1536, 816)
    if small:
        print(small)
        return
    theme.apply(app, "dark")
    host = QWidget()
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    side = sb.Sidebar(NAV_SECTIONS)
    side.set_loaded(True)
    lay.addWidget(side)
    lay.addWidget(QWidget(), 1)
    host.resize(1536, 816)
    host.show()
    _pump(app)
    side.set_collapsed(True)
    _pump(app, 20)
    print("STRIP=%d" % side.width())
    for key, row in side._rows.items():
        label = row._icon_label
        left = label.mapTo(side, QPoint(0, 0)).x()
        pix = label.pixmap()
        width = int(round(pix.width() / pix.devicePixelRatio())) if pix else 0
        # The painted pixmap is centred in the label; its left edge:
        ink_left = left + (label.width() - width) // 2
        print("ICON %s %d %d %d %d" % (key, ink_left, ink_left + width, width,
                                       int(label.isVisible())))
    for name, button in (("collapse", side.collapse_button),
                         ("open", side.open_button),
                         ("theme", side.theme_pill)):
        print("BUTTON %s %d %d" % (name, _room(button), _need(button)))
    host.close()


if __name__ == "__main__":
    main()
