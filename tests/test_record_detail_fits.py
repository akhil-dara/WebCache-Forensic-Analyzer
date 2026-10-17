"""The record dialog never exceeds the screen, and the fields come
first -- eight rows at least, the majority by default, carved bytes
folded until asked for."""
import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QWidget

from webcache.shell import record_detail
from webcache.shell.record_detail import (BlobViewerDialog, FIELDS_MIN_ROWS,
                                          SCREEN_MARGIN_PX, RecordDetailDialog)
from tests.test_detail_fields import carved_struct_row, cert_row, history_row
from tests.test_record_detail_room import (REAL_H, REAL_W, build, themed,  # noqa: F401
                                          visible_field_rows)

#: A 1280x720 work area: smaller than the examiner's, which is the point.
SMALL = QRect(0, 0, 1280, 720).adjusted(SCREEN_MARGIN_PX, SCREEN_MARGIN_PX,
                                        -SCREEN_MARGIN_PX, -SCREEN_MARGIN_PX)
#: A 2560x1440 work area: room for everything.
LARGE = QRect(0, 0, 2560, 1440).adjusted(SCREEN_MARGIN_PX, SCREEN_MARGIN_PX,
                                         -SCREEN_MARGIN_PX, -SCREEN_MARGIN_PX)


def _carved_with_bytes():
    row = carved_struct_row()
    row["_record"] = dict(row["_record"], ResponseHeaders_raw=(
        b"HTTP/1.1 200 OK\r\nServer: synthetic\r\nContent-Type: text/html"
        b"\r\n\r\n"))
    return row


def _within(dlg, room):
    frame = dlg.frameGeometry()
    return frame.width() <= room.width() and frame.height() <= room.height()


def _open(qtbot, row, parent_size=(2600, 1600)):
    """Sized the way MainWindow sizes it -- off its parent -- and NOT
    resized afterwards (the room fixture's build() resizes after show,
    which is an examiner's drag, not the dialog's own sizing).

    qtbot.addWidget() only keeps a WEAKREF (see pytestqt.qtbot._add_widget),
    so `parent` must be kept alive by something else for as long as the
    dialog is used -- stashed on the dialog itself, since a QWidget's own
    Qt-parent relationship does not keep the PARENT's Python wrapper (and
    so its C++ object) alive, only the other way round.
    """
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(*parent_size)
    parent.show()
    dlg = RecordDetailDialog(row, parent)
    dlg._debug_test_parent = parent
    dlg.show()
    qtbot.waitExposed(dlg)
    qtbot.wait(20)
    return dlg


def test_the_dialog_never_opens_bigger_than_the_screen(themed, qtbot,
                                                        monkeypatch):
    monkeypatch.setattr(record_detail, "screen_room", lambda _w: SMALL)
    dlg = _open(qtbot, cert_row())
    assert _within(dlg, SMALL), dlg.frameGeometry()


def test_opening_the_bytes_never_grows_the_dialog_past_the_screen(
        themed, monkeypatch, qtbot):
    monkeypatch.setattr(record_detail, "screen_room", lambda _w: SMALL)
    dlg = _open(qtbot, cert_row())
    dlg.blob_region.toggle_button.click()
    qtbot.wait(20)
    assert _within(dlg, SMALL), dlg.frameGeometry()


def test_a_carved_records_bytes_start_folded_to_their_named_bar(themed, build):
    dlg = build(_carved_with_bytes())
    assert dlg.blob_region is not None
    assert not dlg.blob_region.is_expanded()
    assert "bytes" in dlg.blob_region.toggle_button.full_text()


def test_one_click_shows_them_beside_the_fields_when_they_fit(
        themed, build, monkeypatch, qtbot):
    monkeypatch.setattr(record_detail, "screen_room", lambda _w: LARGE)
    dlg = build(_carved_with_bytes())
    dlg.blob_region.toggle_button.click()
    qtbot.wait(20)
    assert dlg.blob_region.is_expanded()
    assert visible_field_rows(dlg) >= FIELDS_MIN_ROWS


def test_one_click_opens_them_in_their_own_window_when_they_do_not(
        themed, monkeypatch, qtbot):
    monkeypatch.setattr(record_detail, "screen_room", lambda _w: SMALL)
    dlg = _open(qtbot, _carved_with_bytes())
    dlg.blob_region.toggle_button.click()
    qtbot.wait(20)
    assert not dlg.blob_region.is_expanded()
    assert len(dlg._bytes_windows) == 1
    assert isinstance(dlg._bytes_windows[0], BlobViewerDialog)
    assert visible_field_rows(dlg) >= FIELDS_MIN_ROWS
    assert _within(dlg, SMALL)


def test_a_second_click_on_the_folded_bar_does_not_stack_windows(
        themed, monkeypatch, qtbot):
    """The bar stays folded after the own-window
    fallback (it never fit), so a second click looked exactly like the
    first one -- folded, asking to expand -- and opened a SECOND
    BlobViewerDialog for the same blob instead of raising the one
    already open."""
    monkeypatch.setattr(record_detail, "screen_room", lambda _w: SMALL)
    dlg = _open(qtbot, _carved_with_bytes())
    dlg.blob_region.toggle_button.click()
    qtbot.wait(20)
    dlg.blob_region.toggle_button.click()
    qtbot.wait(20)
    assert len(dlg._bytes_windows) == 1


@pytest.mark.parametrize("make", [history_row, cert_row, _carved_with_bytes])
def test_the_field_table_always_shows_at_least_eight_rows(themed, build,
                                                          make, qtbot):
    dlg = build(make())
    dlg.reveal_bytes()
    qtbot.wait(20)
    assert visible_field_rows(dlg) >= FIELDS_MIN_ROWS


def test_the_fields_hold_the_majority_of_the_split(themed, build, qtbot):
    dlg = build(cert_row())
    dlg.reveal_bytes()
    qtbot.wait(20)
    if dlg.blob_region.is_expanded():
        fields, viewer = dlg._splitter.sizes()
        assert fields > viewer
