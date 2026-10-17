"""Standalone native probe for test_label_fit_native.py: every visible
word-wrapped QLabel on the first-run screen and on the drop overlay is
given at least the height its own text needs at its own width.

Run as a SUBPROCESS on the platform's own default plugin, for the reason
_recovery_fit_probe.py gives: the suite's offscreen platform has no fonts,
and the D2 clip (a 430 px label asked its height at the column's 480 px)
only shows with the real one.

Prints "FONT_MISSING", or "CHECKED=<n> CLIPPED=<m>" then one line per
clipped label.
"""
import sys
import tempfile
from pathlib import Path

from webcache import paths

# Never the examiner's own settings: nothing here should write any, and
# if something ever does it lands in a scratch file.
_SCRATCH = Path(tempfile.mkdtemp(prefix="label-fit-"))
paths.settings_path = lambda: _SCRATCH / "settings.json"
paths.cases_dir = lambda: _SCRATCH

from PySide6.QtGui import QFont, QFontInfo  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from webcache.shell import sidebar, theme  # noqa: E402
from webcache.shell.drop_overlay import DropOverlay  # noqa: E402
from webcache.shell.first_run import FirstRunView  # noqa: E402

#: Maximised at 1536 logical px, less the expanded and the collapsed sidebar.
WIDTHS = (1536 - sidebar.SIDEBAR_WIDTH, 1536 - sidebar.SIDEBAR_COLLAPSED_WIDTH)
HEIGHT = 780
#: Synthetic, long enough to wrap to several lines at the card's width.
LONG_REFUSAL = ("This is not a WebCacheV01.dat database and nothing here can "
                "be opened as one; drop the database file itself, or use "
                "Open Database to choose it from its folder instead.")


def _pump(app, n=10):
    for _ in range(n):
        app.processEvents()


def clipped(root, where):
    checked, bad = 0, []
    for label in root.findChildren(QLabel):
        if not (label.isVisible() and label.wordWrap() and label.width() > 0):
            continue
        checked += 1
        need = label.heightForWidth(label.width())
        if need > label.height():
            bad.append("%s %r w=%d h=%d need=%d" % (
                where, label.text()[:24], label.width(), label.height(), need))
    return checked, bad


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))
    if not QFontInfo(app.font()).exactMatch():
        print("FONT_MISSING")
        return
    from tests._native_screen import screen_too_small
    small = screen_too_small(app, 1536 - 52, 780)
    if small:
        print(small)
        return
    theme.apply(app, "dark")
    checked, bad = 0, []
    for width in WIDTHS:
        view = FirstRunView()
        view.resize(width, HEIGHT)
        view.show()
        _pump(app)
        c, b = clipped(view, "first-run@%d" % width)
        checked, bad = checked + c, bad + b
        view.close()

        host = QWidget()
        host.resize(width, HEIGHT)
        host.show()
        overlay = DropOverlay(host)
        overlay.show_for("refused", LONG_REFUSAL, LONG_REFUSAL)
        _pump(app)
        c, b = clipped(overlay, "overlay@%d" % width)
        checked, bad = checked + c, bad + b
        host.close()
    print("CHECKED=%d CLIPPED=%d" % (checked, len(bad)))
    for line in bad:
        print(line)


if __name__ == "__main__":
    main()
