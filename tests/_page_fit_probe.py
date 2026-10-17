"""Native probe for test_page_fit_native.py:
at the examiner's 1536x793 window, does every screen fit the content
column with no page scroll, after the path that used to break it --
Timeline, a search-hit landing (the nav bar shows), an export (the result
bar shows), then every other view?

Run as a SUBPROCESS on the machine's own platform with the real font: the
suite's offscreen platform has no fonts, so every height measured there
is a substitute font's.

Prints FONT_MISSING, or "SCREENS=<n> BAD=<n>" followed by one line per
screen that scrolls or puts its title, Back button or bottom edge outside
the window:
  <step> <key> scroll_max=<n> scroll_value=<n> title_top=<y> back_top=<y>
  view_bottom=<y> window_h=<h>
"""
import sys
import tempfile
from pathlib import Path

from webcache import paths

_SCRATCH = Path(tempfile.mkdtemp(prefix="page-fit-"))
paths.settings_path = lambda: _SCRATCH / "settings.json"
paths.cases_dir = lambda: _SCRATCH

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QFont, QFontInfo  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402


def _pump(app, n=20):
    for _ in range(n):
        app.processEvents()


def _top(win, widget):
    if widget is None or not widget.isVisible():
        return None
    return widget.mapTo(win, QPoint(0, 0)).y()


def _title(view):
    header = getattr(view, "header", None)
    if header is None:
        return None
    for label in header.findChildren(QLabel):
        if label.isVisible() and label.text().strip():
            return label
    return None


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))
    if not QFontInfo(app.font()).exactMatch():
        print("FONT_MISSING")
        return
    from webcache.provenance import EvidenceSet
    from webcache.shell.evidence_loader import history_rows_from_parser
    from webcache.shell.main_window import MainWindow
    from tests.test_mshist_local_clock import build_parser

    from tests._native_screen import screen_too_small
    small = screen_too_small(app, 1536, 793)
    if small:
        print(small)
        return
    win = MainWindow()
    win.resize(1536, 793)
    win.show()
    _pump(app)
    parser = build_parser()
    parser.db_path = str(_SCRATCH / "WebCacheV01.dat")
    win._on_evidence_loaded(
        {"rows": history_rows_from_parser(parser), "parser": parser},
        EvidenceSet([parser.db_path], {parser.db_path: 1},
                    {parser.db_path: "a" * 64}))
    _pump(app, 60)
    # Found by what it holds, not by an attribute name, so the probe reads
    # the same scroll area before and after the fix.
    from PySide6.QtWidgets import QScrollArea
    area = [a for a in win.findChildren(QScrollArea)
            if a.widget() is win.content_stack][0]
    scroll = area.verticalScrollBar()
    screens, bad = 0, []

    def check(step, key):
        nonlocal screens
        _pump(app, 30)
        # Whatever offset the previous screen was left at must not carry.
        # (Set BEFORE the next go_to by `leave`, below.)
        screens += 1
        view = win.stack.currentWidget()
        h = win.height()
        title = _top(win, _title(view))
        back = (_top(win, win.nav_bar.back_button)
                if win.nav_bar.isVisible() else 0)
        bottom = view.mapTo(win, QPoint(0, view.height())).y()
        status = win.statusBar().mapTo(win, QPoint(0, 0)).y()
        ok = (scroll.maximum() == 0 and scroll.value() == 0
              and (title is None or title >= 0)
              and back is not None and back >= 0
              and bottom <= status)
        if not ok:
            bad.append("%s %s scroll_max=%d scroll_value=%d title_top=%s "
                       "back_top=%s view_bottom=%d status_top=%d window_h=%d"
                       % (step, key, scroll.maximum(), scroll.value(),
                          title, back, bottom, status, h))

    def leave():
        scroll.setValue(scroll.maximum())

    win.go_to("timeline")
    check("1-timeline", "timeline")
    leave()
    # A period selected: the pane shows at least three of its records and
    # the period grid at least four periods.
    timeline = win._ensure_view_built("timeline")
    timeline.table.selectRow(0)
    _pump(app, 30)
    check("1b-timeline-period", "timeline")
    for name, grid, need in (("pane", timeline.pane.table, 3),
                             ("periods", timeline.table, 4)):
        rows_shown = grid.viewport().height() // max(
            1, grid.verticalHeader().defaultSectionSize())
        if grid.model() is not None and grid.model().rowCount() >= need                 and rows_shown < need:
            bad.append("1b-timeline-period %s shows %d rows, needs %d"
                       % (name, rows_shown, need))
    leave()
    # A search-hit landing: the nav bar (Back and the crumb) shows.
    win.go_to("browser", crumb="from: Search hit 1 → Container_1 row 1")
    check("2-hit-landing", "browser")
    leave()
    win.go_to("history")
    win._export_key = None
    win._last_view_scope = {"rows_in_file": 1, "rows_in_record_set": 1}
    # A long path, as a real case folder has: the result bar must never
    # widen the window to hold it (it wraps instead, whole).
    target = str(_SCRATCH / ("case-folder-with-a-long-name-" * 2)
                 / "webcache_history_export_file.csv")
    width = win.width()
    win._on_export_written([target])
    _pump(app, 30)
    if win.width() != width:
        bad.append("3-export window widened from %d to %d"
                   % (width, win.width()))
    check("3-export", "history")
    # nor pushes the sidebar's last row below its fold.
    nav = win.sidebar.nav
    if nav.verticalScrollBar().maximum() != 0:
        bad.append("3-export sidebar scrolls by %d with the result bar up"
                   % nav.verticalScrollBar().maximum())
    for key in win.nav_keys:
        win.go_to(key, crumb="from: Timeline record — probe")
        check("4-after", key)
        leave()
    for key in win.nav_keys:
        win.go_to(key)
        check("5-plain", key)
        leave()
    print("SCREENS=%d BAD=%d" % (screens, len(bad)))
    for line in bad:
        print(line)
    win.close()


if __name__ == "__main__":
    main()
