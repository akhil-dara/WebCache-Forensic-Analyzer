"""Native probe for test_export_formats_and_result.py's dismiss-button check.

Run as a SUBPROCESS on the machine's own platform plugin: the suite's
offscreen platform paints with a different style, and it drew the
dismiss button as a flat glyph while the real Windows style drew it as a
light filled box on the dark bar (seen on screen).

Prints "FONT_MISSING", or "light=<fraction of the button's pixels with
lightness > 0.5>" in the dark theme.
"""
import sys

from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtWidgets import QApplication

from webcache.shell import theme
from webcache.shell.export_result_bar import ExportResultBar


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))
    if not QFontInfo(app.font()).exactMatch():
        print("FONT_MISSING")
        return
    from tests._native_screen import screen_too_small
    small = screen_too_small(app, 1200, 60)
    if small:
        print(small)
        return
    theme.apply(app, "dark")
    bar = ExportResultBar()
    bar.show_result("Exported 1 of 1 rows to x.csv", "C:/out/x.csv")
    bar.resize(1200, 60)
    bar.show()
    for _ in range(5):
        app.processEvents()
    image = bar.close_button.grab().toImage()
    w, h = image.width(), image.height()
    light = sum(1 for x in range(w) for y in range(h)
                if image.pixelColor(x, y).lightnessF() > 0.5)
    print("light=%.3f" % (light / float(max(1, w * h))))


if __name__ == "__main__":
    main()
