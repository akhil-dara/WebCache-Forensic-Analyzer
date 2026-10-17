"""Native probe for test_record_dialog_reveal.py. Run as a
SUBPROCESS on the real platform: offscreen Qt has no fonts, so a height
measured there is a substitute font's. Replays exactly what
MainWindow.show_in_database_table does for a carved record: show the
dialog, then reveal the carve-offset bytes at once.

Prints FONT_MISSING, or "avail=<h> frame=<h> close_bottom=<y>
dialog_h=<h> tab=<label>"."""
import pathlib
import sys
import tempfile

from PySide6.QtGui import QFont, QFontInfo, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget


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
    dialog = RecordDetailDialog(row, parent, db_path=str(exhibit))
    dialog.show()
    dialog.reveal_bytes(tab=blob_source.CARVE_TAB_LABEL)
    for _ in range(30):
        app.processEvents()
    tab = ""
    if dialog.blob_region is not None and dialog.blob_region.is_expanded():
        tab = dialog.blobs[dialog.blob_area.currentIndex()].label
    elif dialog._bytes_windows:
        tab = dialog._bytes_windows[-1].source.label
    close = dialog.close_button
    close_bottom = close.mapTo(dialog, close.rect().bottomLeft()).y()
    print("avail=%d frame=%d close_bottom=%d dialog_h=%d tab=%s" % (
        avail.height(), dialog.frameGeometry().height(), close_bottom,
        dialog.height(), tab))


if __name__ == "__main__":
    main()
