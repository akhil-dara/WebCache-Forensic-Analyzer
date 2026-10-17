"""Native probe for the reveal rule. Runs as a SUBPROCESS on
the real platform (offscreen Qt has no fonts). For each reveal path prints
one line: "<path> inline=<0|1> region_h=<visible h> region_min=<h> windows=<n>
tab=<label>" -- `tab` is the tab of whichever surface holds the bytes."""
import pathlib
import sys
import tempfile

from PySide6.QtGui import QFont, QFontInfo, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget


def _state(dialog, path):
    for _ in range(30):
        QApplication.processEvents()
    inline = bool(dialog.blob_region is not None
                  and dialog.blob_region.is_expanded())
    tab = ""
    if inline:
        tab = dialog.blobs[dialog.blob_area.currentIndex()].label
    elif dialog._bytes_windows:
        tab = dialog._bytes_windows[-1].source.label
    # What the examiner SEES of the viewer: the part of it inside the
    # scroll area's viewport, not the height the splitter gave it.
    view = dialog.body_scroll.viewport()
    top = dialog.blob_region.mapTo(view, dialog.blob_region.rect().topLeft()).y()
    seen = (min(top + dialog.blob_region.height(), view.height())
            - max(top, 0))
    print("%s inline=%d region_h=%d region_min=%d windows=%d tab=%s" % (
        path, inline, seen if inline else 0, dialog._viewer_minimum(),
        len(dialog._bytes_windows), tab))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Segoe UI"))
    if not QFontInfo(app.font()).exactMatch():
        print("FONT_MISSING")
        return
    from webcache.shell import blob_source, theme
    from webcache.shell.record_detail import RecordDetailDialog
    from tests.test_detail_fields import carved_struct_row
    theme.apply(app, "dark")
    folder = pathlib.Path(tempfile.mkdtemp())
    exhibit = folder / "WebCacheV01.dat"
    exhibit.write_bytes(bytes(range(256)) * 256)
    row = carved_struct_row(Offset=4096, Page=1)
    row["_record"] = dict(row["_record"], Offset=4096, ResponseHeaders_raw=(
        b"HTTP/1.1 200 OK\r\nServer: synthetic\r\n\r\n"))
    parent = QWidget()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    parent.resize(avail.width(), avail.height() - 23)
    parent.show()
    for path in ("reveal", "foldbar"):
        dialog = RecordDetailDialog(row, parent, db_path=str(exhibit))
        dialog.show()
        if path == "reveal":
            dialog.reveal_bytes(tab=blob_source.CARVE_TAB_LABEL)
        else:
            dialog.blob_region.toggle_button.click()
        _state(dialog, path)


if __name__ == "__main__":
    main()
