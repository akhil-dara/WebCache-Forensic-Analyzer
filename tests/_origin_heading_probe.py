"""Native probe for test_origin_heading_native.py: the "Origin" corner
heading's painted ink, at launch and after each theme switch. It was drawn
at 12 pt at launch and 9 pt after either switch -- invisible offscreen,
where every font is the same substitute.

Prints FONT_MISSING, SCREEN_TOO_SMALL WxH, or "w0 h0 w1 h1 w2 h2" (logical
px of ink: launch, after one switch, after switching back)."""
import math
import sys
import tempfile
from pathlib import Path

from webcache import paths

_SCRATCH = Path(tempfile.mkdtemp(prefix="origin-heading-"))
paths.settings_path = lambda: _SCRATCH / "settings.json"
paths.cases_dir = lambda: _SCRATCH

from PySide6.QtGui import QFont, QFontInfo, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _ink(button, theme):
    img = button.grab().toImage().convertToFormat(QImage.Format_RGB32)
    dpr = img.devicePixelRatio()
    bg = theme.color("alt_base")
    pad = math.ceil(3 * dpr)

    def differs(x, y):
        c = img.pixelColor(x, y)
        return (abs(c.red() - bg.red()) + abs(c.green() - bg.green())
                + abs(c.blue() - bg.blue())) > 120
    xs = range(pad, img.width() - pad)
    ys = range(pad, img.height() - pad)
    cols = [x for x in xs if any(differs(x, y) for y in ys)]
    rows = [y for y in ys if any(differs(x, y) for x in xs)]
    if not cols:
        return 0.0, 0.0
    return ((max(cols) - min(cols) + 1) / dpr, (max(rows) - min(rows) + 1) / dpr)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))
    if not QFontInfo(app.font()).exactMatch():
        print("FONT_MISSING")
        return
    from tests._native_screen import screen_too_small
    small = screen_too_small(app, 1200, 700)
    if small:
        print(small)
        return
    from webcache.shell import theme
    from webcache.shell.main_window import MainWindow
    from tests.fixtures import make_rows
    win = MainWindow()
    win.showNormal()
    win.resize(1200, 700)
    history = win._ensure_view_built("history")
    history.set_records(make_rows(20))
    win.go_to("history")

    def pump():
        for _ in range(40):
            app.processEvents()
    out = []
    pump()
    out += _ink(history.table.corner_button, theme)
    for _ in range(2):
        win._toggle_theme()
        pump()
        out += _ink(history.table.corner_button, theme)
    print(" ".join("%.1f" % v for v in out))
    win.close()


if __name__ == "__main__":
    main()
