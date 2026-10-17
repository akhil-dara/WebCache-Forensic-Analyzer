"""Standalone probe for test_recovery_provenance_visible.py's real-screen
column-fit assertion.

Run as a SUBPROCESS, never imported directly by a test under this
suite's own QApplication: conftest.py forces QT_QPA_PLATFORM=offscreen
before any PySide6 import, and this suite's offscreen platform plugin
registers ZERO font families here (QFontDatabase.families() == [] --
verified directly; see webcache/shell/sidebar.py's own comment on the
same fact) -- every width in the offscreen harness is measured against a
fixed-advance substitute font, not the real app's Segoe UI. A column-fit
check that hard-codes "must end inside the viewport" needs the REAL font
theme.py's QSS and RecordsTable's floor formulas are actually tuned
against, or it is checking an unrelated, environment-specific number, not
the real requirement.

Run with the interpreter's OWN default platform (no QT_QPA_PLATFORM
override) rather than fighting conftest's process-wide offscreen default,
which cannot be changed once any test in this session has created the
one, process-wide QApplication -- a fresh subprocess is the only way to
get a real, non-offscreen platform inside this suite at all. This mirrors
tests/test_fixtures.py's own subprocess pattern for exactly the same
"needs a fresh interpreter" reason.

Prints one line: either "FONT_MISSING" (the real Segoe UI font is not
actually installed on whatever machine runs this -- the caller must skip,
not fail, since there is nothing real left to measure) or
"viewport=<n> Source=<r> Timestamp=<r> Offset=<r> Method=<r> Confidence=<r>
MethodRoom=<px>"
-- Timestamp (UTC) is the default sort column, so it
must be on screen too, and Page moved right of Confidence to make room;
where each <r> is that column's right edge in the SAME coordinate space
as viewport.
"""
import sys

from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtWidgets import QApplication

from webcache.shell import sidebar, theme
from webcache.views.recovery import RecoveryView
from tests.test_recovery_view import _rows


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))
    if not QFontInfo(app.font()).exactMatch():
        print("FONT_MISSING")
        return
    theme.apply(app, "dark")

    from tests._native_screen import screen_too_small
    small = screen_too_small(app, 1536 - sidebar.SIDEBAR_WIDTH, 800)
    if small:
        print(small)
        return
    v = RecoveryView()
    v.set_records(_rows(200))
    v.resize(1536 - sidebar.SIDEBAR_WIDTH, 800)
    v.show()
    app.processEvents()

    table = v.table
    header = table.horizontalHeader()
    order = [c.key for c in table.model().columns]
    viewport = table.viewport().width()
    parts = ["viewport=%d" % viewport]
    for name in ("Source", "Timestamp", "Offset", "Method", "Confidence"):
        idx = order.index(name)
        right = header.sectionViewportPosition(idx) + header.sectionSize(idx)
        parts.append("%s=%d" % (name, right))
    # MethodRoom: what the Method column has left once its LONGEST value
    # and the cell's QSS padding (0 9px) are on one line. Negative means
    # every such row wraps to two lines.
    from PySide6.QtGui import QFontMetrics
    from webcache.engine.recovery_engine import METHOD_LABELS
    from webcache.shell.recovery_loader import TOMBSTONE_METHOD
    widest = max(QFontMetrics(table.font()).horizontalAdvance(m)
                 for m in METHOD_LABELS + (TOMBSTONE_METHOD,))
    method = header.sectionSize(order.index("Method"))
    parts.append("MethodRoom=%d" % (method - widest - 2 * 9 - 4))
    print(" ".join(parts))


if __name__ == "__main__":
    main()
