"""Mounting the viewer: the dialog's bottom pane, and the Table Browser.

Unit 2 left a placeholder here that said, in words, that the hex and
strings viewer was not built yet. This is what replaces it -- and the one
assertion that matters most is
test_the_carve_tab_prints_an_offset_an_examiner_can_seek_to. Everything
else in this application describes evidence; that tab is the only surface
that hands the examiner a number they can paste into a different tool and
check this one against.

The Table Browser route is here for the same reason recovery_loader's own
docstring gives for its "built, but never wired" warning. blobs_for_cells
makes any binary column of any ESE table readable, including columns
nobody wrote a decoder for -- and a capability with no route to it is
indistinguishable from one that does not exist.
"""
import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget

from webcache.shell import blob_source, record_detail
from webcache.shell.record_detail import BlobViewerDialog, RecordDetailDialog
from webcache.widgets import hex_view
from webcache.widgets.hex_view import BlobPane

from tests.test_detail_fields import (carved_string_row, carved_struct_row,
                                      cert_row, cookie_row, history_row)


@pytest.fixture
def exhibit(tmp_path):
    """A stand-in exhibit with a recognisable byte at every position."""
    path = tmp_path / "WebCacheV01.dat"
    path.write_bytes(bytes(range(256)) * 64)
    return str(path)


@pytest.fixture
def build(qtbot):
    """Dialogs built and torn down by hand -- WA_DeleteOnClose means
    pytest-qt's own teardown would close an already-deleted C++ object,
    exactly as tests/test_record_detail_dialog.py documents."""
    built = []

    def make(row, **kwargs):
        dialog = RecordDetailDialog(row, **kwargs)
        built.append(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)
        return dialog

    yield make
    for dialog in built:
        try:
            dialog.close()
        except RuntimeError:
            pass


# --- the bottom pane ----------------------------------------------------

def test_a_record_with_a_blob_mounts_a_real_viewer(build):
    dialog = build(history_row())
    assert isinstance(dialog.blob_area, QTabWidget)
    assert dialog.blob_area.count() == 1
    assert isinstance(dialog.blob_area.widget(0), BlobPane)


def test_the_tab_is_named_for_the_blob_and_states_its_size(build):
    dialog = build(cert_row())
    label = dialog.blob_area.tabText(0)
    assert "Certificate blob" in label
    assert "202" in label


def test_a_record_with_no_blobs_has_no_bottom_pane_at_all(build):
    """No empty box and no "(no data)" placeholder where nothing applies."""
    dialog = build(cookie_row())
    assert dialog.blob_area is None


def test_the_blob_area_is_given_real_room(build):
    """Unit 2's placeholder was capped to a note's height. A viewer is not
    a note: a ratio assertion can pass offscreen while the real window
    looks wrong, so this is an explicit pixel floor."""
    dialog = build(history_row())
    assert dialog.blob_area.minimumHeight() >= hex_view.MIN_PANE_HEIGHT_PX
    assert dialog.blob_area.maximumHeight() > 1000


def test_every_blob_the_binary_group_lists_has_a_tab(build):
    row = history_row()
    row["_record"]["RequestHeaders_raw"] = b"GET / HTTP/1.1\r\nHost: x\r\n"
    dialog = build(row)
    assert dialog.blob_area.count() == 2
    from webcache.shell import detail_fields
    binary = [g for g in dialog.groups
              if g.name == detail_fields.G_BINARY][0]
    assert len(binary.fields) == dialog.blob_area.count()


# --- the carve window ---------------------------------------------------

def test_a_carved_record_gets_a_bytes_at_the_carve_offset_tab(build, exhibit):
    dialog = build(carved_struct_row(), db_path=exhibit)
    labels = [dialog.blob_area.tabText(i)
              for i in range(dialog.blob_area.count())]
    assert any("carve offset" in label.lower() for label in labels)


def test_a_carved_string_artifact_gets_one_too(build, exhibit):
    """A bare URL out of page slack has no columns at all -- the bytes
    around where it was found are the ONLY thing there is to look at."""
    dialog = build(carved_string_row(), db_path=exhibit)
    assert dialog.blob_area is not None
    assert dialog.blob_area.count() == 1


def test_the_carve_tab_prints_an_offset_an_examiner_can_seek_to(build,
                                                                exhibit):
    """The acceptance criterion for this whole unit.

    The dump's first row must carry the true FILE offset of the window,
    and the header must state the record's own offset as bare hex, so
    both can be pasted into another tool and compared.
    """
    row = carved_struct_row(Offset=8200)
    dialog = build(row, db_path=exhibit)
    pane = [dialog.blob_area.widget(i)
            for i in range(dialog.blob_area.count())
            if "carve offset" in dialog.blob_area.tabText(i).lower()][0]
    first = pane.hex_view.text_view.toPlainText().splitlines()[0]
    start = pane.source.window_start
    assert first.startswith("%08X" % start)
    with open(exhibit, "rb") as handle:
        handle.seek(start)
        expected = handle.read(16)
    assert " ".join("%02X" % b for b in expected) in first
    assert "0x00002008" in [copy for _l, _s, copy in pane.header_rows]


def test_without_an_exhibit_path_no_carve_window_is_invented(build):
    """No database open, no claim about what sits at an offset in it."""
    dialog = build(carved_string_row())
    assert dialog.blob_area is None


def test_the_carve_pane_carries_its_verification_sentence(build, exhibit):
    dialog = build(carved_struct_row(), db_path=exhibit)
    pane = dialog.blob_area.widget(dialog.blob_area.count() - 1)
    assert "read back from the evidence" in pane.verification_label.text()


# --- reaching the tabs from the field list ------------------------------

def test_enter_on_a_binary_field_row_focuses_that_blobs_tab(build):
    row = history_row()
    row["_record"]["RequestHeaders_raw"] = b"GET / HTTP/1.1\r\nHost: x\r\n"
    dialog = build(row)
    from webcache.shell import detail_fields
    fields = detail_fields.flatten(dialog.groups)
    target = [f for f in fields if f.blob_key == "RequestHeaders_raw"][0]
    dialog.blob_area.setCurrentIndex(0)
    dialog.activate_field(fields.index(target))
    current = dialog.blob_area.currentWidget()
    assert current.blob_key == "RequestHeaders_raw"


def test_enter_on_a_binary_row_does_not_copy_instead(build):
    """A Binary row's value is a summary line this tool composed. Copying
    it would put "202 bytes · Binary · SHA-256 ..." on the clipboard as
    though it were a stored value."""
    dialog = build(cert_row())
    from webcache.shell import detail_fields
    fields = detail_fields.flatten(dialog.groups)
    index = [i for i, f in enumerate(fields) if f.blob_key][0]
    dialog.activate_field(index)
    assert "tab" in dialog.status_label.text().lower()


def test_ctrl_e_exports_the_blob_whose_tab_is_showing(build, monkeypatch):
    row = history_row()
    row["_record"]["RequestHeaders_raw"] = b"GET / HTTP/1.1\r\n"
    dialog = build(row)
    dialog.blob_area.setCurrentIndex(1)
    asked = []
    monkeypatch.setattr(type(dialog.blob_area.widget(1)), "export_blob",
                        lambda self: asked.append(self.blob_key))
    dialog.keyPressEvent(_key_event(Qt.Key_E, Qt.ControlModifier))
    assert asked == ["RequestHeaders_raw"]


def _key_event(key, modifiers):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    return QKeyEvent(QEvent.KeyPress, key, modifiers)


# --- lifecycle ----------------------------------------------------------

def test_the_dialog_drops_its_blob_sources_on_close(build, exhibit):
    """A FileWindowBlob holds a kilobyte and a MemoryBlob holds a pointer
    into the parser. A dialog that kept either would keep the exhibit."""
    dialog = build(carved_struct_row(), db_path=exhibit)
    assert dialog.blobs
    dialog.close()
    assert dialog.blobs == []


# --- one wording for a busy clipboard -----------------------------------

def test_the_clipboard_busy_message_has_one_definition():
    from webcache.shell import record_detail
    assert record_detail.CLIPBOARD_BUSY is hex_view.CLIPBOARD_BUSY


# --- the Table Browser: any binary column of any table ------------------

def test_a_bytes_cell_in_the_table_browser_offers_to_view_its_bytes(qtbot):
    from webcache.views.browser import TableBrowserView
    view = TableBrowserView()
    qtbot.addWidget(view)
    view._render_page(_page_with_blob())
    menu = view._build_grid_context_menu(view.grid.model().index(0, 1))
    labels = [action.text() for action in menu.actions()]
    assert any("bytes" in label.lower() for label in labels)


def test_a_cell_with_no_bytes_offers_no_viewer(qtbot):
    from webcache.views.browser import TableBrowserView
    view = TableBrowserView()
    qtbot.addWidget(view)
    view._render_page(_page_with_blob())
    menu = view._build_grid_context_menu(view.grid.model().index(0, 0))
    labels = [action.text() for action in menu.actions()]
    assert not any("bytes" in label.lower() for label in labels)


def test_the_view_bytes_action_emits_the_column_and_its_bytes(qtbot):
    from webcache.views.browser import TableBrowserView
    view = TableBrowserView()
    qtbot.addWidget(view)
    page = _page_with_blob()
    view._render_page(page)
    seen = []
    view.blobRequested.connect(lambda name, data: seen.append((name, data)))
    view.request_cell_bytes(0, 1)
    assert seen == [("ResponseHeaders", page["rows"][0][1]["raw"])]


def _page_with_blob():
    return {
        "columns": ["EntryId", "ResponseHeaders"],
        "rows": [[{"type": "int", "text": "5", "raw": None},
                  {"type": "bytes", "text": "72 bytes",
                   "raw": b"\x89PNG\r\n\x1a\n" + b"marker-in-a-blob" + b"\x00" * 48}]],
        "row_count": 1, "offset": 0, "limit": 200,
        "display_name": "Container_4", "type": "History", "directory": "",
    }


# --- the standalone viewer dialog ---------------------------------------

def test_a_blob_viewer_dialog_shows_the_pane_and_names_its_column(qtbot):
    src = blob_source.MemoryBlob("ResponseHeaders", b"\x89PNG" + b"\x00" * 60,
                                 "ResponseHeaders")
    dialog = BlobViewerDialog(src)
    qtbot.addWidget(dialog)
    dialog.show()
    assert isinstance(dialog.pane, BlobPane)
    assert "ResponseHeaders" in dialog.windowTitle()


def test_the_viewer_dialog_says_which_table_the_bytes_came_from(qtbot):
    src = blob_source.MemoryBlob("ResponseHeaders", b"\x00" * 64, "x")
    dialog = BlobViewerDialog(src, context="Container_4")
    qtbot.addWidget(dialog)
    assert "Container_4" in dialog.context_label.text()


# --- MainWindow wiring --------------------------------------------------

def test_the_detail_dialog_is_handed_the_exhibit_path(qtbot, exhibit):
    from webcache.shell.main_window import MainWindow

    class _Parser:
        db_path = exhibit

    window = MainWindow()
    qtbot.addWidget(window)
    window._parser = _Parser()
    dialog = window._show_record_detail(carved_struct_row())
    try:
        assert dialog.db_path == exhibit
        assert dialog.blob_area is not None
    finally:
        dialog.close()
        window.close()


def test_the_table_browser_is_wired_to_the_blob_viewer(qtbot):
    """Proved BY EMITTING, not by counting receivers.

    QObject.receivers takes a C++ signature string and refuses a
    SignalInstance outright, so the counting form does not even run here
    -- and Unit 2 already settled that emitting is the stronger proof
    anyway: a connection to the WRONG slot counts exactly the same as a
    connection to the right one.
    """
    from webcache.shell.main_window import MainWindow
    window = MainWindow()
    qtbot.addWidget(window)
    view = window._ensure_view_built("browser")
    view._render_page(_page_with_blob())
    before = len(window._detail_dialogs)
    view.request_cell_bytes(0, 1)
    assert len(window._detail_dialogs) == before + 1
    dialog = window._detail_dialogs[-1]
    try:
        assert isinstance(dialog, BlobViewerDialog)
        assert "marker-in-a-blob" in dialog.pane.all_strings_text()
    finally:
        dialog.close()
        window.close()


def test_opening_a_second_exhibit_closes_an_open_blob_viewer(qtbot):
    from webcache.shell.main_window import MainWindow
    window = MainWindow()
    qtbot.addWidget(window)
    dialog = window._show_blob("ResponseHeaders", b"\x00" * 64)
    assert dialog.isVisible() or dialog is not None
    window._close_record_dialogs()
    assert window._detail_dialogs == []
    window.close()


def test_the_exhibit_path_reaches_a_dialog_opened_from_another_dialog(
        qtbot, exhibit):
    """Dialogs stack, and a drilled-to record has to be able to read the
    same exhibit the one it came from could."""
    from webcache.shell.main_window import MainWindow

    class _Parser:
        db_path = exhibit

    window = MainWindow()
    qtbot.addWidget(window)
    window._parser = _Parser()
    first = window._show_record_detail(carved_struct_row())
    second = window._show_record_detail(carved_string_row())
    try:
        assert second.db_path == exhibit
        assert second.blob_area is not None
    finally:
        first.close()
        second.close()
        window.close()


def test_the_export_directory_default_is_never_the_evidence_folder(exhibit):
    """Belt and braces on the rule the widget already tests: settings
    keeps the two directories apart, and nothing joins them."""
    from webcache.shell import settings
    assert settings.DEFAULTS["last_export_dir"] == ""
    assert os.path.dirname(exhibit) != settings.DEFAULTS["last_export_dir"]


def test_the_dialog_gives_the_viewer_the_height_it_asks_for(build, exhibit):
    """Found by looking. The dialog trusted QTabWidget.minimumSizeHint,
    which does not add up a word-wrapped label's needs, and handed the
    carve viewer 332px when it needed 400-odd -- so the header rows
    painted over each other and the button row came out half off the
    pane, with this file entirely green.

    PREMISE NARROWED, not dropped. The viewer is now foldable and opens
    folded wherever honouring its floor would leave the record's own
    fields in the minority -- so "the viewer gets what it asks for" is a
    claim about an OPEN viewer, and the test unfolds it before measuring.
    The guarantee itself is unchanged and is still the one that matters:
    while it is open, nothing may squeeze it under its measured minimum.
    """
    dialog = build(carved_struct_row(), db_path=exhibit)
    dialog.resize(1340, 800)
    dialog.show()
    dialog.blob_region.set_expanded(True)
    _fields_px, blob_px = dialog._splitter.sizes()
    pane = dialog.blob_area.widget(dialog.blob_area.count() - 1)
    assert blob_px >= pane.minimumHeight()


def test_the_record_keeps_readable_rows_beside_its_bytes(build, exhibit):
    """Both halves usable. The viewer's minimum must not be allowed to
    reduce a 69-field record to a single visible row."""
    dialog = build(carved_struct_row(), db_path=exhibit)
    dialog.resize(1340, 900)
    dialog.show()
    fields_px, _blob_px = dialog._splitter.sizes()
    assert fields_px >= record_detail._FIELDS_FLOOR_PX


def test_the_dialog_can_still_be_sized_to_1100_700_with_a_multi_string_blob(
        build, exhibit):
    """hex_view.StringsList's header QLabel was built with no
    setWordWrap, so its non-wrapping minimumSizeHint prints the whole
    "Strings (N) -- the list scrolls; every one of them is here" sentence
    on one line -- about 696px -- once the blob carries more than
    SCROLL_HINT_ROWS (15) strings, which is every real response-headers or
    certificate blob. That propagates up through the splitter to the
    dialog's own minimum width, refusing any resize below roughly 1558px.
    """
    data = b"\x00".join(b"str%04d" % i for i in range(50))
    row = carved_struct_row()
    row["_record"]["ResponseHeaders_raw"] = data
    dialog = build(row, db_path=exhibit)
    dialog.resize(1100, 700)
    assert dialog.width() <= 1100, (
        "the dialog refused to shrink to 1100px with a multi-string blob "
        "open (got %dpx)" % dialog.width())
