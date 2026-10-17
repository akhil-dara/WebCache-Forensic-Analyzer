"""The blob viewer on screen: paging, panes, copying and export.

blob_reader decides what a line of hex SAYS and is tested with no Qt at
all; this file tests only what painting it adds -- that paging cannot walk
off either end of a blob, that the position label states the total rather
than leaving "is that all of it?" open, that no scrolling region is nested
inside another, that a copy takes the whole blob rather than the page that
happens to be visible, and that an export writes the bytes unchanged and
never defaults into the evidence folder.

That last one is not a nicety. The evidence directory is read-only for the
whole life of the case, and a save dialog pre-pointed at it is one
mis-click away from writing into the exhibit.
"""
import hashlib
import os

import pytest
from PySide6.QtWidgets import QAbstractScrollArea, QFileDialog

from webcache.engine import blob_reader
from webcache.shell import blob_source, settings
from webcache.widgets import hex_view


@pytest.fixture
def big_blob():
    """Three pages and a bit, with a marker in the last page so a copy
    that only took the visible one can be caught."""
    body = bytearray(bytes(range(256)) * 50)          # 12,800 bytes
    body[12_000:12_014] = b"LAST-PAGE-MARK"
    return bytes(body)


@pytest.fixture
def source(big_blob):
    return blob_source.MemoryBlob("Response headers / property store",
                                  big_blob, "ResponseHeaders_raw")


@pytest.fixture
def pane(qtbot, source):
    widget = hex_view.BlobPane(source)
    qtbot.addWidget(widget)
    widget.show()
    return widget


# --- paging -------------------------------------------------------------

def test_paging_cannot_go_past_either_end(qtbot, source):
    """PREMISE CORRECTED BY LOOKING. This first expected the last page to
    start at `size - page_bytes`, which for the 8,108-byte certificate on
    the real exhibit is 4,012 -- 0x0FAC, not a multiple of sixteen -- so
    every row of that page printed twelve bytes out of step with the rows
    another hex editor draws for the same file. The column stayed
    arithmetically correct and stopped being comparable, which is the
    only thing it is for.

    Pages are whole pages. The last one is SHORT rather than shifted.
    """
    view = hex_view.HexView(source)
    qtbot.addWidget(view)
    assert view.offset == 0
    view.go_previous()
    view.go_previous()
    assert view.offset == 0
    for _ in range(20):
        view.go_next()
    last = ((source.size - 1) // blob_reader.HEX_PAGE_BYTES
            ) * blob_reader.HEX_PAGE_BYTES
    assert view.offset == last
    assert view.offset % 16 == 0
    view.go_end()
    assert view.offset == last
    view.go_start()
    assert view.offset == 0


def test_every_page_start_is_sixteen_aligned(qtbot):
    """The rows have to fall on the same boundaries the file's own do, at
    every page, for any size of blob."""
    for size in (17, 4095, 4096, 4097, 8108, 12_801):
        src = blob_source.MemoryBlob("x", bytes(size), "k")
        view = hex_view.HexView(src)
        qtbot.addWidget(view)
        seen = set()
        while view.offset not in seen:
            seen.add(view.offset)
            assert view.offset % 16 == 0, (size, view.offset)
            view.go_next()
        # and the last page really does reach the last byte.
        view.go_end()
        assert view.offset + src.page_bytes >= size, size


def test_the_last_page_says_it_is_the_end(qtbot, source):
    view = hex_view.HexView(source)
    qtbot.addWidget(view)
    view.go_end()
    assert "the end" in view.position_label.text()
    assert "{:,}".format(source.size) in view.position_label.text()


def test_paging_a_blob_smaller_than_one_page_never_moves(qtbot):
    small = blob_source.MemoryBlob("x", b"A" * 32, "k")
    view = hex_view.HexView(small)
    qtbot.addWidget(view)
    view.go_next()
    view.go_end()
    assert view.offset == 0


def test_the_page_shown_is_the_page_asked_for(qtbot, source):
    view = hex_view.HexView(source)
    qtbot.addWidget(view)
    view.go_next()
    text = view.text_view.toPlainText()
    assert text.splitlines()[0].startswith("00001000")


def test_the_position_label_states_the_total(qtbot, source):
    """"bytes 0-4,095 of 12,800" leaves nothing open about whether the
    rest exists. No truncation, and the label proves it."""
    view = hex_view.HexView(source)
    qtbot.addWidget(view)
    label = view.position_label.text()
    assert "{:,}".format(source.size) in label
    assert "4,095" in label or "4,096" in label


def test_a_blob_that_fits_says_it_is_complete(qtbot):
    small = blob_source.MemoryBlob("x", b"A" * 200, "k")
    view = hex_view.HexView(small)
    qtbot.addWidget(view)
    assert "complete" in view.position_label.text()
    assert "200" in view.position_label.text()


def test_the_type_chip_is_content_derived(qtbot):
    png = blob_source.MemoryBlob("Response headers",
                                 b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "k")
    view = hex_view.HexView(png)
    qtbot.addWidget(view)
    assert "PNG" in view.type_chip.text()


def test_the_hash_line_says_whose_hash_it_is(qtbot, source):
    """This is this tool's hash of the bytes as extracted, and it is
    never presented as something the database stores."""
    view = hex_view.HexView(source)
    qtbot.addWidget(view)
    text = view.hash_label.text()
    assert source.sha256[:16] in text
    assert "this tool" in text.lower()


# --- the panes ----------------------------------------------------------

def test_a_blob_pane_shows_hex_decode_and_strings(pane):
    assert pane.hex_view is not None
    assert pane.decode_view is not None
    assert pane.strings_list is not None


def test_a_blob_pane_has_exactly_one_scrolling_region_per_pane(pane):
    """Nested scrollers put two scrollbars a few pixels apart and make
    wheel-scrolling depend on where the pointer happens to be. Each region
    scrolls; none of them scrolls inside another."""
    scrollers = pane.findChildren(QAbstractScrollArea)
    assert scrollers
    for widget in scrollers:
        parent = widget.parentWidget()
        while parent is not None and parent is not pane:
            assert not isinstance(parent, QAbstractScrollArea), (
                "%s scrolls inside %s" % (type(widget).__name__,
                                          type(parent).__name__))
            parent = parent.parentWidget()


def test_the_strings_header_counts_them_and_says_it_scrolls(qtbot):
    data = b"\x00".join(b"str%04d" % i for i in range(600))
    src = blob_source.MemoryBlob("x", data, "k")
    widget = hex_view.StringsList(src)
    qtbot.addWidget(widget)
    assert "600" in widget.header.text()
    assert "scrolls" in widget.header.text()


def test_the_strings_list_is_uncapped_and_reaches_the_last_one(qtbot):
    """String #847 has to be readable: Export blob hands back raw
    bytes, not strings, so the list itself must not be capped."""
    data = b"\x00".join(b"str%04d" % i for i in range(1000))
    src = blob_source.MemoryBlob("x", data, "k")
    widget = hex_view.StringsList(src)
    qtbot.addWidget(widget)
    assert widget.model.rowCount() == 1000
    row = widget.model.data(widget.model.index(846, 0))
    assert "str0846" in row


def test_a_strings_row_prints_the_offset_in_the_same_frame_as_the_hex(qtbot,
                                                                      tmp_path):
    path = tmp_path / "WebCacheV01.dat"
    path.write_bytes(b"\x00" * 4096 + b"marker-string" + b"\x00" * 4096)
    src = blob_source.FileWindowBlob("Bytes", str(path), None, 4096)
    widget = hex_view.StringsList(src)
    qtbot.addWidget(widget)
    rows = [widget.model.data(widget.model.index(r, 0))
            for r in range(widget.model.rowCount())]
    hit = [r for r in rows if "marker-string" in r][0]
    assert hit.startswith("%08X" % 4096)


def test_the_decode_pane_never_shows_an_empty_box(qtbot):
    src = blob_source.MemoryBlob("x", b"\xff" * 64, "k")
    widget = hex_view.BlobPane(src)
    qtbot.addWidget(widget)
    assert widget.decode_view.toPlainText().strip()


# --- copy ---------------------------------------------------------------

def test_copy_full_hex_copies_the_whole_blob_not_the_visible_page(pane,
                                                                  big_blob):
    text = pane.full_hex_text()
    assert "LAST-PAGE-MARK" in text
    assert len(text.splitlines()) == (len(big_blob) + 15) // 16
    assert "LAST-PAGE-MARK" not in pane.hex_view.text_view.toPlainText()


def test_a_modest_hex_copy_asks_nothing(pane):
    asked = []
    assert len(pane.full_hex_text()) < hex_view.CONFIRM_ABOVE_CHARS
    pane.copy_full_hex(confirm=lambda message: asked.append(message) or True)
    assert asked == []


def test_a_very_large_hex_copy_states_the_exact_figure_before_it_happens(qtbot):
    """Never silently refused, never silently truncated -- the examiner is
    told the number and decides."""
    src = blob_source.MemoryBlob("x", bytes(range(256)) * 900, "k")
    widget = hex_view.BlobPane(src)
    qtbot.addWidget(widget)
    asked = []
    total = len(widget.full_hex_text())
    assert total > hex_view.CONFIRM_ABOVE_CHARS
    widget.copy_full_hex(confirm=lambda message: asked.append(message) or False)
    assert len(asked) == 1
    assert "{:,}".format(total) in asked[0]


def test_copy_every_string_takes_all_of_them(qtbot):
    data = b"\x00".join(b"str%04d" % i for i in range(300))
    src = blob_source.MemoryBlob("x", data, "k")
    widget = hex_view.BlobPane(src)
    qtbot.addWidget(widget)
    text = widget.all_strings_text()
    assert text.count("\n") == 299
    assert "str0299" in text


def test_the_carve_header_offers_the_offset_as_bare_hex(qtbot, tmp_path):
    """It pastes straight into another tool's seek box."""
    path = tmp_path / "WebCacheV01.dat"
    path.write_bytes(bytes(range(256)) * 64)
    src = blob_source.FileWindowBlob("Bytes at the carve offset",
                                     str(path), None, 8200)
    widget = hex_view.BlobPane(src)
    qtbot.addWidget(widget)
    assert widget.header_rows
    values = [copy for _label, _shown, copy in src.header_rows()]
    assert "0x00002008" in values


def test_the_carve_pane_carries_the_standing_verification_statement(qtbot,
                                                                    tmp_path):
    path = tmp_path / "WebCacheV01.dat"
    path.write_bytes(bytes(range(256)) * 64)
    src = blob_source.FileWindowBlob("Bytes at the carve offset",
                                     str(path), None, 8200)
    widget = hex_view.BlobPane(src)
    qtbot.addWidget(widget)
    assert widget.verification_label is not None
    assert "read back from the evidence" in widget.verification_label.text()


def test_a_plain_blob_pane_has_no_carve_header(pane):
    assert pane.header_rows == []
    assert pane.verification_label is None


def test_a_failed_carve_read_prints_no_hash_and_no_verification_claim(
        qtbot, tmp_path):
    """BlobSource.__init__ hashes self._data even when it is
    empty, and the carve header's verification statement painted
    unconditionally whenever header_rows existed -- which is ALWAYS, even
    when nothing was read (FileWindowBlob.header_rows() still returns a
    "Nothing was read" row). With an out-of-range offset the pane said
    "Nothing was read -- Offset ... is past the end of ..." and printed a
    SHA-256 and a "these bytes were read back from the evidence" claim
    directly below it -- both describing bytes that were never read."""
    path = tmp_path / "WebCacheV01.dat"
    path.write_bytes(bytes(range(256)) * 64)          # 16,384 bytes
    src = blob_source.FileWindowBlob("Bytes at the carve offset",
                                     str(path), None, 999_999)
    assert src.size == 0
    widget = hex_view.BlobPane(src)
    qtbot.addWidget(widget)
    assert widget.verification_label is not None
    assert "read back from the evidence" not in widget.verification_label.text()
    assert "SHA-256" not in widget.hex_view.hash_label.text()


# --- export -------------------------------------------------------------

def test_export_writes_the_bytes_unchanged(pane, big_blob, tmp_path):
    target = tmp_path / "out.bin"
    ok, message = pane.write_blob(str(target))
    assert ok, message
    written = target.read_bytes()
    assert hashlib.sha256(written).hexdigest() == \
        hashlib.sha256(big_blob).hexdigest()
    assert "{:,}".format(len(big_blob)) in message


def test_export_reports_a_failure_rather_than_claiming_success(pane, tmp_path):
    ok, message = pane.write_blob(str(tmp_path / "nope" / "deep" / "out.bin"))
    assert not ok
    assert message.strip()


def test_the_export_dialog_does_not_default_to_the_evidence_directory(
        pane, monkeypatch, tmp_path):
    """The evidence folder is read-only for the life of the case. A save
    dialog pre-pointed at it is one mis-click from writing there."""
    evidence = str(tmp_path / "evidence")
    os.makedirs(evidence, exist_ok=True)
    monkeypatch.setattr(settings, "get", lambda key, default=None: {
        "last_evidence_dir": evidence, "last_export_dir": ""}.get(key, default))
    start = pane.export_start_path()
    assert os.path.dirname(start) != evidence
    assert evidence not in start


def test_the_export_dialog_remembers_where_the_last_export_went(
        pane, monkeypatch, tmp_path):
    chosen = str(tmp_path / "reports")
    os.makedirs(chosen, exist_ok=True)
    monkeypatch.setattr(settings, "get", lambda key, default=None: {
        "last_evidence_dir": "", "last_export_dir": chosen}.get(key, default))
    assert os.path.dirname(pane.export_start_path()) == chosen


def test_last_export_dir_is_a_declared_setting():
    """Declared in DEFAULTS, so a fresh settings.json has the key rather
    than silently falling back to whatever Qt last used."""
    assert "last_export_dir" in settings.DEFAULTS


def test_the_export_path_ends_in_a_filesystem_safe_name(pane):
    name = os.path.basename(pane.export_start_path())
    assert name.endswith(".bin")
    assert all(c.isalnum() or c in "_.-" for c in name)


# --- an export can never land beside the exhibit -------------------------
#
# export_blob() opened its own QFileDialog and
# handed the chosen path straight to write_blob(), which is a bare
# open(path, "wb") -- nothing here ever called export_target.refuse_reason,
# so an examiner who navigated to the evidence folder wrote straight into
# it. Every other export in this application refuses that destination in
# a dialog, not a status line (see test_export_wiring.py's identical
# check on the CSV/HTML path); this pane must refuse the same way.

def test_choosing_the_evidence_folder_refuses_and_writes_nothing(
        pane, monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    dat = evidence_dir / "WebCacheV01.dat"
    dat.write_bytes(b"x")
    pane.evidence_files = {os.path.normcase(os.path.realpath(str(dat)))}
    pane.evidence_dirs = {os.path.normcase(os.path.realpath(str(evidence_dir)))}
    target = str(evidence_dir / "blob.bin")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (target, "")))
    outcomes = []

    class _FakeSafeFolderDialog:
        CHOSE_SAFE, CHOSE_ELSEWHERE, CANCELLED = 1, 2, 3

        def __init__(self, parent, reason, safe_path):
            outcomes.append((reason, safe_path))

        def exec(self):
            return 0

        def outcome(self):
            return self.CANCELLED

        def path(self):
            return ""

        def deleteLater(self):
            pass

    monkeypatch.setattr(hex_view, "SafeFolderDialog", _FakeSafeFolderDialog)
    result = pane.export_blob()
    assert result is False
    assert outcomes, "a refusal must be a dialog, not a silent write"
    assert "evidence" in outcomes[0][0].lower()
    assert not os.path.exists(target)


# --- the widget layer stays engine-free ---------------------------------

def test_the_page_size_is_read_off_the_source_not_redeclared(source):
    """One definition of 4096, in blob_reader. widgets/ cannot import it,
    so it arrives on the source."""
    import ast
    import pathlib
    path = pathlib.Path(hex_view.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == 4096:
            raise AssertionError("hex_view redeclares the page size")
    assert source.page_bytes == blob_reader.HEX_PAGE_BYTES


# --- what LOOKING found, and the suite could not ------------------------
#
# Every assertion below failed on the real exhibit while this file was
# entirely green. A squeezed QLayout still reports every widget present,
# with the right text, at a position nobody can read -- so "the widget
# exists and says the right thing" is exactly the class of claim that
# cannot catch a layout defect.

#: A realistic pane width: the dialog opens at parent width - 260, and the
#: application's own window is wider than this.
REAL_PANE_PX = 1312


def _carve_pane(qtbot, tmp_path, offset=8200):
    path = tmp_path / "WebCacheV01.dat"
    if not path.exists():
        path.write_bytes(bytes(range(256)) * 64)
    src = blob_source.FileWindowBlob("Bytes at the carve offset",
                                     str(path), None, offset)
    widget = hex_view.BlobPane(src)
    qtbot.addWidget(widget)
    return widget


#: What the decode and strings panes need to be worth reading. An
#: ABSOLUTE floor, deliberately, not a share of the width: the hex pane's
#: own minimum depends on the application stylesheet and the platform
#: font -- measured at 818px bare and 952px under this application's own
#: theme -- so a test asserting a 3:2 SHARE is asserting a property of
#: the font as much as of this widget, and passes or fails depending on
#: which other test last touched the palette. What must hold either way
#: is that the panes beside the dump stay readable.
SIDE_PANE_FLOOR_PX = 320


def test_the_hex_pane_leaves_the_panes_beside_it_readable(qtbot, source):
    """Its own minimum WIDTH must leave room for them.

    Spelled-out button labels ("◀ Previous 4,096 bytes", "Save these
    bytes… (Ctrl+E)") gave this row a minimum of 1,250px, so the splitter
    could never shrink the hex pane and the decode and strings panes
    clipped every line at 307px. A button's label is not worth a pane.
    """
    pane = hex_view.BlobPane(source)
    qtbot.addWidget(pane)
    pane.resize(REAL_PANE_PX, 420)
    pane.show()
    qtbot.waitExposed(pane)
    left_over = REAL_PANE_PX - pane.hex_view.minimumSizeHint().width()
    assert left_over >= SIDE_PANE_FLOOR_PX


def test_the_horizontal_split_is_applied_and_not_merely_declared(qtbot,
                                                                 source):
    """setStretchFactor divides only LEFTOVER space, and a monospace dump
    hints at seventy-eight characters, so on its own it did nothing."""
    pane = hex_view.BlobPane(source)
    qtbot.addWidget(pane)
    pane.resize(REAL_PANE_PX, 420)
    pane.show()
    qtbot.waitExposed(pane)
    _hex_px, side_px = pane._splitter.sizes()
    assert side_px >= SIDE_PANE_FLOOR_PX


def test_the_split_survives_the_application_theme(qtbot, source):
    """The regression guard for the failure that only appeared in a FULL
    suite run: theme.apply installs an application-wide stylesheet that
    widens every button in the row, and this pane's layout has to hold
    under it. Green in isolation and red in the whole suite is exactly
    the shape of a defect that reaches an examiner and never a test."""
    from webcache.shell import theme
    from PySide6.QtWidgets import QApplication
    theme.apply(QApplication.instance(), "dark")
    pane = hex_view.BlobPane(source)
    qtbot.addWidget(pane)
    pane.resize(REAL_PANE_PX, 420)
    pane.show()
    qtbot.waitExposed(pane)
    _hex_px, side_px = pane._splitter.sizes()
    assert side_px >= SIDE_PANE_FLOOR_PX


def test_every_child_of_a_carve_pane_fits_inside_its_own_minimum(qtbot,
                                                                 tmp_path):
    """At the height the pane declares it needs, everything is inside it.

    At a flat 220 and again at 335 the carve header's three rows painted
    on top of each other and the paging buttons were drawn over the dump.
    """
    pane = _carve_pane(qtbot, tmp_path)
    pane.resize(REAL_PANE_PX, pane.minimumHeight())
    pane.show()
    qtbot.waitExposed(pane)
    # The export button is deliberately IN the paging row -- sharing a
    # band with it is the design, not an overlap -- so the stacked
    # children are the ones compared below, and the export button is
    # checked only for being inside the pane.
    children = [("hex dump", pane.hex_view.text_view),
                ("paging row", pane.hex_view.start_button),
                ("verification", pane.verification_label)]
    top = pane.export_button.mapTo(pane, pane.export_button.rect().topLeft())
    bottom = pane.export_button.mapTo(
        pane, pane.export_button.rect().bottomRight())
    assert top.y() >= 0 and bottom.y() <= pane.height()
    bands = []
    for name, child in children:
        top = child.mapTo(pane, child.rect().topLeft())
        bottom = child.mapTo(pane, child.rect().bottomRight())
        assert top.y() >= 0, name
        assert bottom.y() <= pane.height(), (name, bottom.y(), pane.height())
        bands.append((name, top.y(), bottom.y()))
    # AND none of them is drawn on top of another. "Inside the pane"
    # alone has no teeth: a squeezed layout keeps every child within
    # bounds and stacks them, which is exactly what happened -- three
    # header rows painted over each other, all of them "inside".
    for i, (a_name, a_top, a_bottom) in enumerate(bands):
        for b_name, b_top, b_bottom in bands[i + 1:]:
            assert a_bottom <= b_top or b_bottom <= a_top, (
                "%s (%d..%d) overlaps %s (%d..%d)"
                % (a_name, a_top, a_bottom, b_name, b_top, b_bottom))


def test_the_carve_headers_own_rows_never_paint_over_each_other(qtbot,
                                                                tmp_path):
    """The defect exactly. Source file, Record offset and Window shown
    were drawn at the same three y-positions on top of one another, and
    every existing test still found all three labels with the right
    text."""
    pane = _carve_pane(qtbot, tmp_path)
    pane.resize(REAL_PANE_PX, pane.minimumHeight())
    pane.show()
    qtbot.waitExposed(pane)
    from PySide6.QtWidgets import QLabel
    values = [w for w in pane.findChildren(QLabel)
              if w.font().fixedPitch() and w.text()]
    assert len(values) >= len(pane.header_rows)
    bands = sorted((w.mapTo(pane, w.rect().topLeft()).y(),
                    w.mapTo(pane, w.rect().bottomRight()).y())
                   for w in values)
    for (top, bottom), (next_top, _next_bottom) in zip(bands, bands[1:]):
        assert bottom <= next_top, (top, bottom, next_top)


def test_a_carve_pane_asks_for_more_height_than_a_plain_one(qtbot, tmp_path,
                                                            source):
    """Because it carries three header rows and a statement that a plain
    blob pane does not. A single flat constant for both is what put the
    header rows on top of each other."""
    plain = hex_view.BlobPane(source)
    qtbot.addWidget(plain)
    assert (_carve_pane(qtbot, tmp_path).minimumHeight()
            > plain.minimumHeight())


def test_a_split_the_examiner_dragged_is_not_undone(qtbot, source):
    """The automatic sizing runs until the handle is moved, and then
    stops. A window that argues with the person using it is worse than
    one that never helped."""
    pane = hex_view.BlobPane(source)
    qtbot.addWidget(pane)
    pane.resize(REAL_PANE_PX, 420)
    pane.show()
    qtbot.waitExposed(pane)
    pane._remember_the_examiner_moved_it()
    # A split the splitter can actually honour: the hex pane has a
    # minimum width of its own, and asking for less than that would test
    # Qt's clamping rather than this widget's behaviour.
    hex_min = pane.hex_view.minimumSizeHint().width()
    pane._splitter.setSizes([hex_min, REAL_PANE_PX - hex_min])
    dragged = pane._splitter.sizes()[0] / sum(pane._splitter.sizes())
    pane.resize(REAL_PANE_PX + 200, 480)
    qtbot.wait(10)
    hex_px, side_px = pane._splitter.sizes()
    kept = hex_px / (hex_px + side_px)
    automatic = hex_view.HEX_STRETCH / (hex_view.HEX_STRETCH
                                        + hex_view.SIDE_STRETCH)
    assert abs(kept - dragged) < abs(kept - automatic) + 0.01, (
        "the resize pulled the split back toward the automatic ratio")
