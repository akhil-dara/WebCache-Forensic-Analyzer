"""Entry point.

High-DPI scaling is Qt 6's default. At exit, aboutToQuit calls
consent.shutdown_workers(), so a worker still hashing evidence on a slow
device is asked to stop and given a bounded wait.

WEBCACHE_SELFSHOT makes the application save a screenshot of its own
window, rendered by Qt (QWidget.grab()), for on-screen verification of a
packaged build; it works with the screen locked or the window covered.
When the variable is unset nothing is scheduled.
"""
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# Absolute imports: PyInstaller runs this file as a top-level script with
# no parent package, where a relative import fails.
from webcache.shell.consent import shutdown_workers
from webcache.shell.icon import build_icon
from webcache.shell.main_window import MainWindow


def install_shutdown_handler(app):
    """Bind app.aboutToQuit to the worker shutdown. Separate from main()
    so it can be tested without starting the event loop."""
    app.aboutToQuit.connect(shutdown_workers)


def _maybe_self_shot(window):
    """Save a screenshot of `window` to WEBCACHE_SELFSHOT once, after
    WEBCACHE_SELFSHOT_MS (default 4000). Does nothing, and schedules no
    timer, unless WEBCACHE_SELFSHOT is set."""
    path = os.environ.get("WEBCACHE_SELFSHOT")
    if not path:
        return
    delay_ms = int(os.environ.get("WEBCACHE_SELFSHOT_MS", "4000"))
    QTimer.singleShot(delay_ms, lambda: window.grab().save(path))


def self_test(out_path):
    """`WebCacheAnalyzer.exe --self-test OUT.json`, run against every
    built package before release: builds the main window off screen,
    reads every asset the offline report needs and imports every lazily
    loaded export module, then writes the result (including where this
    copy keeps its files) and exits 0 only if all of it worked."""
    import json
    import traceback
    from webcache import paths, provenance
    report = {"ok": False, "version": provenance.TOOL_VERSION}
    try:
        app = QApplication.instance() or QApplication([sys.argv[0]])
        window = MainWindow()
        from webcache.shell import html_package
        report["page_bytes"] = (len(html_package.page_script())
                                + len(html_package.page_style()))
        import dissect.esedb  # noqa: F401
        import openpyxl  # noqa: F401
        import reportlab  # noqa: F401
        report.update(
            views=window.stack.count(),
            installed=paths.is_installed(),
            data_dir=str(paths.data_dir()),
            cases_dir=str(paths.cases_dir()),
            settings=str(paths.settings_path()),
            ok=True)
        window.deleteLater()
        app.processEvents()
    except Exception:                                  # noqa: BLE001
        report["error"] = traceback.format_exc()
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return 0 if report["ok"] else 1


#: How often (seconds) Python hands the GIL between threads. The GUI thread
#: needs the GIL for every paint and every slot; while a worker parses or
#: carves, the default 5 ms made each of those wait, and grids stalled for
#: up to a second during a recovery scan. 0.5 ms keeps the window responsive
#: at no measurable cost to the workers.
SWITCH_INTERVAL_S = 0.0005


def keep_the_window_responsive():
    """Shorten the interpreter's thread switch interval (see
    SWITCH_INTERVAL_S)."""
    sys.setswitchinterval(SWITCH_INTERVAL_S)


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--self-test":
        # Off screen: no one is there to see a window.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        return self_test(sys.argv[2])
    keep_the_window_responsive()
    app = QApplication(sys.argv)
    app.setApplicationName("WebCache Forensic Analyzer")
    app.setOrganizationName("WebCache")
    # "Segoe UI" by name: Qt's generic "Sans Serif" alias can resolve to a
    # font that renders some characters with the wrong glyphs.
    app.setFont(QFont("Segoe UI"))
    # On the QApplication, so every window and dialog inherits it.
    app.setWindowIcon(build_icon())
    install_shutdown_handler(app)
    window = MainWindow()
    # MainWindow sizes itself (saved geometry, or its default).
    window.show()
    _maybe_self_shot(window)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
