"""Hex, strings and a structured decode of one blob. Purely visual.

Engine-free, like every module under widgets/ (tests/test_structure.py).
It is given a BlobSource and asks it for pages, strings, a decode, a hash
and a name, without knowing whether the bytes came from a database column
or were read from the exhibit. The page size comes from
`source.page_bytes`, so it has one definition.

THE OFFSET COLUMN prints `source.base_offset + position`: the offset in
the blob for a column value, the offset in the file for a carve window,
so a copied offset can be found at the same row in any hex editor.

THREE PANES, THREE SCROLLERS, NONE NESTED: hex on the left, decode over
strings on the right, in splitters with drag handles, so each pane
scrolls on its own.

THE STRINGS LIST IS NOT CAPPED. It is a QListView over a minimal model,
virtualised, so its length costs nothing. "Export blob" exports raw bytes,
not strings, and on a blob no decoder understands the strings are often
the only readable content.
"""
import os

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QListView,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QSizePolicy, QSplitter, QVBoxLayout, QWidget)

from . import copyable
from ..shell import export_target, settings, theme
from ..shell.export_dialogs import SafeFolderDialog

#: Above this many characters, a "copy the whole dump" is confirmed with
#: the exact figure first. A 388 KB blob is about 1.9 MB of text, and
#: putting that on the clipboard without a word is the kind of surprise
#: that makes an examiner distrust the next thing the tool does.
CONFIRM_ABOVE_CHARS = 1_000_000

#: Reported instead of a success message when another application holds
#: the clipboard (a real condition on Windows). Imported by
#: shell/record_detail.py, so both surfaces use the same words.
CLIPBOARD_BUSY = "Another application is holding the clipboard — try again"

#: The strings header says so when the list is longer than a screenful.
#: Fifteen visible rows out of six hundred, with the scrollbar not yet
#: noticed, gives no sense of how much is below.
SCROLL_HINT_ROWS = 15

#: A 3:2 split, as splitter stretch factors, so the examiner can drag it and the numbers are a
#: starting point rather than a decision made for them.
HEX_STRETCH, SIDE_STRETCH = 3, 2

#: A minimum height for the pane, so mounting it under a field table
#: cannot squeeze the hex dump away: the sum of the parts below.
MIN_PANE_HEIGHT_PX = 300

#: The dump's own minimum, rather than whatever the chrome leaves. Five
#: rows (eighty bytes) are enough to read a header or recognise a
#: structure, and each further row would come from the field list above;
#: the pane pages and the handle drags for the rest.
HEX_MIN_ROWS = 5

#: Floors for the two right-hand panes, for the same reason.
DECODE_MIN_PX = 70
STRINGS_MIN_PX = 90

#: The minimum height for a button in this pane; the height itself is
#: measured (button_height below). A fixed height would clip a styled
#: button whose padding and font need more.
BUTTON_HEIGHT_PX = 30

#: Breathing room under the last button row -- see BlobPane.__init__.
PANE_BOTTOM_MARGIN_PX = 6

#: What a QVBoxLayout puts between two stacked children by default here.
#: Counted explicitly: it belongs to no child, so a height computed by
#: adding the children up is short by one of these per gap -- which is
#: how the bottom button row came out half off the pane.
LAYOUT_SPACING_PX = 6


def button_height(widget):
    """The height a button in `widget` needs, under the current style and
    font.

    Measured off a real QPushButton parented to `widget`: sizeHint()
    polishes it against the application stylesheet, so the theme's
    padding is counted, which font metrics alone cannot see.

    BUTTON_HEIGHT_PX is the floor, so an unusually small hint cannot
    collapse the row, and _needed_height has a lower bound to rely on.

    The probe carries the longest label in this pane, so it is measured as
    the buttons beside it are.
    """
    probe = QPushButton("Export blob…", widget)
    probe.setVisible(False)
    needed = max(BUTTON_HEIGHT_PX, probe.sizeHint().height())
    probe.setParent(None)
    probe.deleteLater()
    return needed


def mono_font(base=None):
    """A fixed-pitch font, requested by style hint rather than by name,
    so a machine without a named family still gets a monospace face and
    the hex dump keeps its columns.
    """
    font = QFont(base) if base is not None else QFont()
    font.setStyleHint(QFont.Monospace)
    font.setFamily("Consolas")
    font.setFixedPitch(True)
    return font


def _monospace_view():
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setLineWrapMode(QPlainTextEdit.NoWrap)
    view.setFont(mono_font())
    # Selectable, so an examiner can drag bytes straight out of the dump.
    view.setTextInteractionFlags(Qt.TextSelectableByMouse
                                 | Qt.TextSelectableByKeyboard)
    return view


def set_clipboard(text):
    """True only when the text really landed.

    QGuiApplication.clipboard().setText can fail outright while another
    application holds the Windows clipboard. Reporting success anyway is
    how a report ends up carrying the PREVIOUS copy's contents.
    """
    try:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)
        return clipboard.text() == text
    except Exception:                      # noqa: BLE001
        return False


class _StringsModel(QAbstractListModel):
    """One row per recovered string. Minimal on purpose: a QListView over
    this is virtualised, which is what makes an uncapped list free."""

    def __init__(self, rows, base_offset, parent=None):
        super().__init__(parent)
        self._rows = rows
        self._base = base_offset

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        offset, encoding, text = self._rows[index.row()]
        # The SAME frame of reference as the hex column beside it, so a
        # string's offset and the dump's offset name the same byte.
        line = "%08X  %-10s  %s" % (self._base + offset, encoding, text)
        # The strings ARE evidence bytes: escaped in the tooltip so one
        # that starts with a tag is shown, not rendered.
        return (copyable.literal_tooltip(line) if role == Qt.ToolTipRole
                else line)


class StringsList(QWidget):
    """Every printable run in the blob, in offset order, uncapped."""

    def __init__(self, source, parent=None):
        super().__init__(parent)
        rows = source.strings()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.header = copyable.selectable(QLabel(self._header_text(len(rows))))
        self.header.setStyleSheet("color: %s;" % theme.color("carved").name())
        # Without this, Qt's non-wrapping
        # minimumSizeHint measures the WHOLE scroll-hint sentence on one
        # line -- about 696px -- once count > SCROLL_HINT_ROWS, which is
        # every real response-headers or certificate blob. That propagated
        # up through this pane's splitter to the dialog's own minimum
        # width, refusing to shrink the dialog below roughly 1558px.
        self.header.setWordWrap(True)
        layout.addWidget(self.header)

        self.model = _StringsModel(rows, source.base_offset, self)
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setFont(mono_font())
        self.view.setWordWrap(False)
        self.view.setUniformItemSizes(True)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self.view, 1)

    @staticmethod
    def _header_text(count):
        text = "Strings (%s)" % "{:,}".format(count)
        if count > SCROLL_HINT_ROWS:
            # The word, so it is clear how much more there is below.
            text += " — the list scrolls; every one of them is here"
        return text


class HexView(QWidget):
    """A paged hex dump printing offsets in the source's own frame."""

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
        self.offset = 0
        #: Measured once and shared with the owning BlobPane, so the
        #: bottom row (this view's four pager buttons and the pane's three
        #: actions, in one layout) has one height.
        self.button_px = button_height(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        head = QHBoxLayout()
        self.type_chip = copyable.selectable(QLabel(source.detected_type))
        self.type_chip.setToolTip(
            "Detected from the blob's own magic bytes, not from the column "
            "it is stored in — so a column that is supposed to hold headers "
            "and actually holds an image says so.")
        self.type_chip.setStyleSheet(
            "color: %s; border: 1px solid %s; border-radius: 3px; "
            "padding: 1px 6px;" % (theme.color("url").name(),
                                   theme.color("border").name()))
        head.addWidget(self.type_chip)
        self.position_label = copyable.selectable(QLabel(""))
        head.addWidget(self.position_label, 1)
        layout.addLayout(head)

        # The full digest, never abbreviated. The note that this tool
        # computed it (the database does not store it) is on the line and
        # in the tooltip.
        #
        # Shown only when bytes were read (source.size): an empty read,
        # such as an out-of-range carve offset, has nothing to hash.
        hash_text = ("SHA-256 (this tool's, not stored by the database): %s"
                    % source.sha256) if source.size else ""
        self.hash_label = QLabel(hash_text)
        self.hash_label.setWordWrap(True)
        self.hash_label.setToolTip(
            "Computed by this tool over the bytes exactly as extracted. It "
            "is not a value the database stores, and no relationship to any "
            "stored thumbprint is claimed.")
        copyable.selectable(self.hash_label)
        self.hash_label.setSizePolicy(QSizePolicy.Ignored,
                                      QSizePolicy.Preferred)
        self.hash_label.setStyleSheet(
            "color: %s;" % theme.color("muted2").name())
        layout.addWidget(self.hash_label)

        self.text_view = _monospace_view()
        # Six rows, always. Left to fill whatever the chrome does not
        # want, the dump is the pane's only elastic child and therefore
        # the one that vanishes first.
        self.text_view.setMinimumHeight(
            HEX_MIN_ROWS * self.text_view.fontMetrics().lineSpacing() + 12)
        layout.addWidget(self.text_view, 1)

        # Paging lives in a layout the OWNER can add to, so a BlobPane's
        # three actions share this row instead of claiming another one.
        # Vertical space in this pane is not free: every row of chrome
        # comes out of the dump, which is the only thing here that is
        # evidence.
        self.paging_bar = QHBoxLayout()
        page = "{:,}".format(source.page_bytes)
        # Short labels, with the full sentence in the tooltip, so the row's
        # minimum width lets the splitter give the decode and strings panes
        # room. Start and End are glyph-only (the least-used controls);
        # Prev and Next keep their words.
        self.start_button = QPushButton("⏮")
        self.prev_button = QPushButton("◀ Prev")
        self.next_button = QPushButton("Next ▶")
        self.end_button = QPushButton("⏭")
        for button, slot, tip in (
                (self.start_button, self.go_start, "Back to the first byte"),
                (self.prev_button, self.go_previous,
                 "The previous %s bytes" % page),
                (self.next_button, self.go_next, "The next %s bytes" % page),
                (self.end_button, self.go_end, "The last page")):
            button.setAutoDefault(False)
            button.setFixedHeight(self.button_px)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            self.paging_bar.addWidget(button)
        layout.addLayout(self.paging_bar)

        self.refresh()

    def set_button_height(self, px):
        """Apply a height to the pager's buttons, so the owning pane can
        give the whole shared row one height."""
        self.button_px = px
        for button in (self.start_button, self.prev_button,
                       self.next_button, self.end_button):
            button.setFixedHeight(px)

    # --- paging ----------------------------------------------------------

    def max_offset(self):
        """The last page start, always a whole number of pages in.

        Clamping to `size - page_bytes` would start the last page at an
        offset that is not a multiple of sixteen, so its rows would not
        line up with the rows a hex editor draws for the same file. With
        whole pages the last page is short rather than shifted, as in any
        hex editor. Never negative: a blob smaller than one page has one
        page, starting at zero.
        """
        if self.source.size <= self.source.page_bytes:
            return 0
        return ((self.source.size - 1) // self.source.page_bytes
                ) * self.source.page_bytes

    def set_offset(self, value):
        self.offset = max(0, min(int(value), self.max_offset()))
        self.refresh()

    def go_start(self):
        self.set_offset(0)

    def go_previous(self):
        self.set_offset(self.offset - self.source.page_bytes)

    def go_next(self):
        self.set_offset(self.offset + self.source.page_bytes)

    def go_end(self):
        self.set_offset(self.max_offset())

    # --- painting --------------------------------------------------------

    def refresh(self):
        self.text_view.setPlainText("\n".join(self.source.hex_page(self.offset)))
        self.position_label.setText(self._position_text())
        for button in (self.start_button, self.prev_button):
            button.setEnabled(self.offset > 0)
        for button in (self.next_button, self.end_button):
            button.setEnabled(self.offset < self.max_offset())

    def _position_text(self):
        """States its own completeness.

        A pane that shows 4,096 bytes of a 388,204-byte blob and says
        nothing leaves "is that all of it?" open, which is the question
        this application exists to answer before it is asked.
        """
        size = self.source.size
        if not size:
            return "No bytes to show."
        if size <= self.source.page_bytes:
            return "%s bytes (complete)" % "{:,}".format(size)
        last = min(size, self.offset + self.source.page_bytes) - 1
        text = "bytes %s–%s of %s" % ("{:,}".format(self.offset),
                                      "{:,}".format(last),
                                      "{:,}".format(size))
        if last == size - 1:
            # So the last page does not read as though it might have been
            # cut off at a page boundary with more beyond it.
            text += " — the end"
        return text


class BlobPane(QWidget):
    """One blob: hex beside its decode and its strings, with the three
    actions that get it out of the application."""

    def __init__(self, source, parent=None, evidence_files=(),
                evidence_dirs=()):
        super().__init__(parent)
        self.source = source
        self.blob_key = getattr(source, "field_key", "")
        self.header_rows = list(source.header_rows())
        # Where the exhibit lives, so export_blob can refuse to write
        # beside it -- see the module-level note on export_blob below.
        # Sets, not whatever iterable arrives, so a caller passing the
        # same list twice does not change comparison semantics.
        self.evidence_files = set(evidence_files or ())
        self.evidence_dirs = set(evidence_dirs or ())
        self.verification_label = None
        # Measured before the carve header is built, because its Copy
        # buttons are laid out first and _needed_height counts their rows.
        # self.hex_view.button_px is reconciled with this below; both are
        # measured under the same style.
        self.button_px = button_height(self)
        self.setMinimumHeight(MIN_PANE_HEIGHT_PX)

        layout = QVBoxLayout(self)
        # A bottom margin, so the action buttons do not sit flush against
        # the pane's edge and look clipped.
        layout.setContentsMargins(0, 0, 0, PANE_BOTTOM_MARGIN_PX)

        if self.header_rows:
            layout.addWidget(self._build_carve_header())

        splitter = QSplitter(Qt.Horizontal)
        self.hex_view = HexView(source)
        # One height for the whole bottom row: the pager's four buttons
        # (HexView's) and this pane's three actions share one QHBoxLayout.
        self.button_px = max(self.button_px, self.hex_view.button_px)
        self.hex_view.set_button_height(self.button_px)
        splitter.addWidget(self.hex_view)

        side = QSplitter(Qt.Vertical)
        self.decode_view = _monospace_view()
        self.decode_view.setPlainText("\n".join(source.decode_lines()))
        self.decode_view.setMinimumHeight(DECODE_MIN_PX)
        side.addWidget(self.decode_view)
        # If extracting strings fails, the strings pane is omitted and the
        # decode takes the whole right-hand region, with one scroller.
        try:
            self.strings_list = StringsList(source)
            self.strings_list.setMinimumHeight(STRINGS_MIN_PX)
            side.addWidget(self.strings_list)
        except Exception:                      # noqa: BLE001
            self.strings_list = None
        splitter.addWidget(side)
        splitter.setStretchFactor(0, HEX_STRETCH)
        splitter.setStretchFactor(1, SIDE_STRETCH)
        self._splitter = splitter
        self._split_applied = False
        splitter.splitterMoved.connect(self._remember_the_examiner_moved_it)
        layout.addWidget(splitter, 1)

        # Into the HEX VIEW's own paging row, not a row of their own.
        self.status_label = copyable.selectable(QLabel(""))
        self.status_label.setStyleSheet(
            "color: %s;" % theme.color("muted").name())
        # Ignored horizontally: a status line reading "Wrote 388,204 raw
        # bytes to ..." must not be able to set a floor under the whole
        # pane's width and push the splitter beside it out of shape.
        self.status_label.setSizePolicy(QSizePolicy.Ignored,
                                        QSizePolicy.Preferred)
        self._build_actions(self.hex_view.paging_bar)
        self.hex_view.paging_bar.addWidget(self.status_label, 1)
        self.setMinimumHeight(self._needed_height())

    # --- construction ----------------------------------------------------

    def _build_carve_header(self):
        """Only a carve window has one; a column value is described by
        its tab label and type chip.

        A grid of fixed height, so Qt cannot compress the rows below their
        minimum and paint them over each other.
        """
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        grid = QGridLayout(box)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        for row, (label, shown, copy_text) in enumerate(self.header_rows):
            name = copyable.selectable(QLabel(label))
            name.setMinimumWidth(110)
            name.setStyleSheet("color: %s;" % theme.color("muted2").name())
            grid.addWidget(name, row, 0)
            value = QLabel(shown)
            copyable.selectable(value)
            value.setFont(mono_font())
            grid.addWidget(value, row, 1)
            button = QPushButton("Copy")
            button.setAutoDefault(False)
            button.setFixedHeight(self.button_px)
            grid.setRowMinimumHeight(row, self.button_px + 2)
            button.clicked.connect(
                lambda _checked=False, text=copy_text, what=label:
                self._copy(text, "Copied %s." % what.lower()))
            grid.addWidget(button, row, 2)

        row = len(self.header_rows)
        # Only when bytes were read (source.size): header_rows() is
        # non-empty even for an empty read, which states that nothing was
        # read.
        verification_text = (
            getattr(self.source, "verification_statement", "")
            if getattr(self.source, "size", 0) else "")
        self.verification_label = copyable.selectable(QLabel(verification_text))
        self.verification_label.setWordWrap(True)
        self.verification_label.setStyleSheet(
            "color: %s;" % theme.color("muted2").name())
        grid.addWidget(self.verification_label, row, 0, 1, 2)

        if getattr(self.source, "verify_supported", False):
            # Beside the statement rather than under it: evidence should
            # not change under an examiner, and the offer to check costs
            # a button, not a row of the pane the dump needs.
            self.verify_button = QPushButton("Verify this file")
            self.verify_button.setFixedHeight(self.button_px)
            self.verify_button.setToolTip(
                "Re-hash this file and compare it with the hash taken when "
                "it was opened.")
            self.verify_button.setAutoDefault(False)
            self.verify_button.clicked.connect(self.verify_file)
            grid.addWidget(self.verify_button, row, 2)
        return box

    def showEvent(self, event):
        """Apply the 3:2 split once, by width.

        setStretchFactor divides only the space left after each child's
        size hint, and a hex dump hints at seventy-eight characters, so
        the split is set explicitly.
        """
        super().showEvent(event)
        self._apply_split()

    def resizeEvent(self, event):
        """Re-applied until the handle is dragged: the first showEvent can
        arrive while the splitter still has zero width.
        """
        super().resizeEvent(event)
        self._apply_split()

    def _remember_the_examiner_moved_it(self, *_args):
        self._split_applied = True

    def _apply_split(self):
        if self._split_applied:
            return
        width = self._splitter.width()
        if width <= 0:
            return
        total = HEX_STRETCH + SIDE_STRETCH
        hex_px = int(width * HEX_STRETCH / total)
        self._splitter.setSizes([hex_px, max(1, width - hex_px)])

    def _needed_height(self):
        """What this pane needs, counted from its parts.

        Qt's minimumSizeHint does not add up a word-wrapped label's needs
        here, and a layout squeezed below its minimum paints its rows over
        each other, so the parts are counted explicitly.
        """
        line = self.fontMetrics().lineSpacing()
        # the dump, plus the type/position row and the hash row above it
        needed = HEX_MIN_ROWS * line + 12 + 2 * (line + 6)
        needed += self.button_px + 14            # paging/actions/status row
        if self.header_rows:
            needed += len(self.header_rows) * (self.button_px + 6)
            needed += line + 6                   # the verification sentence
            needed += 22                         # the frame's own margins
        # The layout's spacing between the children it stacks, which is
        # not part of any child's height.
        needed += 6 * LAYOUT_SPACING_PX
        return max(MIN_PANE_HEIGHT_PX, needed + PANE_BOTTOM_MARGIN_PX)

    def _build_actions(self, bar):
        carved = bool(self.header_rows)
        self.copy_hex_button = QPushButton("Copy hex")
        self.copy_hex_button.setToolTip(
            "Copy the WHOLE dump, not the page on screen.")
        self.copy_hex_button.clicked.connect(lambda: self.copy_full_hex())
        self.copy_strings_button = QPushButton("Copy strings")
        self.copy_strings_button.setToolTip(
            "Copy every recovered string, not just the visible ones.")
        self.copy_strings_button.clicked.connect(self.copy_all_strings)
        self.export_button = QPushButton(
            "Save bytes…" if carved else "Export blob…")
        self.export_button.setToolTip(
            "Ctrl+E — write these bytes to a file, byte for byte, with no "
            "encoding step.")
        self.export_button.clicked.connect(self.export_blob)
        for button in (self.copy_hex_button, self.copy_strings_button,
                       self.export_button):
            button.setAutoDefault(False)
            button.setFixedHeight(self.button_px)
            bar.addWidget(button)
        return bar

    # --- text ------------------------------------------------------------

    def full_hex_text(self):
        """The WHOLE dump, regardless of which page is on screen."""
        return "\n".join(self.source.full_hex())

    def all_strings_text(self):
        rows = self.source.strings()
        return "\n".join(
            "%08X  %-10s  %s" % (self.source.base_offset + off, enc, text)
            for off, enc, text in rows)

    # --- copy ------------------------------------------------------------

    def _copy(self, text, message):
        if not text:
            self._report(False, "Nothing to copy — there are no bytes here.",
                         warn=True)
            return False
        ok = set_clipboard(text)
        self._report(ok, message if ok else CLIPBOARD_BUSY, warn=not ok)
        return ok

    def _report(self, ok, message, warn=False):
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color: %s;" % theme.color("warn" if warn or not ok
                                       else "muted").name())
        return ok

    def copy_full_hex(self, confirm=None):
        """Never refused or truncated without saying so.

        Above CONFIRM_ABOVE_CHARS the examiner is told the exact figure and
        decides. `confirm` is injectable, so a test can answer without a
        modal dialog.
        """
        text = self.full_hex_text()
        if len(text) > CONFIRM_ABOVE_CHARS:
            ask = confirm if confirm is not None else self._ask
            message = ("This will put %s characters on the clipboard. "
                       "Continue?" % "{:,}".format(len(text)))
            if not ask(message):
                return self._report(False, "Not copied.", warn=True)
        return self._copy(text, "Copied %s hex lines."
                          % "{:,}".format(text.count("\n") + 1 if text else 0))

    def _ask(self, message):
        return QMessageBox.question(
            self, "Copy the whole dump?", message,
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    def copy_all_strings(self):
        return self._copy(self.all_strings_text(), "Copied every string.")

    def verify_file(self):
        message = self.source.verify()
        return self._report("unchanged" in message, message,
                            warn="unchanged" not in message)

    # --- export ----------------------------------------------------------

    def export_start_path(self):
        """Where the save dialog opens, and what it is called there.

        Seeded from "last_export_dir" and NEVER from "last_evidence_dir".
        The evidence folder is read-only for the whole life of the case;
        a save dialog pre-pointed at it is one mis-click from writing
        into the exhibit, and the fact that nothing has done so yet is
        not a mechanism.
        """
        directory = settings.get("last_export_dir", "") or ""
        if not directory or not os.path.isdir(directory):
            directory = self._documents_dir()
        return os.path.join(directory, self.source.suggested_filename())

    @staticmethod
    def _documents_dir():
        # Imported here rather than at module scope so the fallback is
        # visible at the one place it applies.
        from PySide6.QtCore import QStandardPaths
        found = QStandardPaths.writableLocation(
            QStandardPaths.DocumentsLocation)
        return found or os.path.expanduser("~")

    def write_blob(self, path):
        """(ok, message). Byte for byte, with no encoding step.

        Does not record last_export_dir: the folder is remembered when the
        examiner chooses one, in export_blob, so a write alone never changes
        persisted settings.
        """
        data = self.source.all_bytes()
        try:
            with open(path, "wb") as handle:
                handle.write(data)
        except OSError as exc:
            return False, "Could not write %s: %s" % (os.path.basename(path),
                                                      exc)
        return True, "Wrote %s raw bytes to %s." % ("{:,}".format(len(data)),
                                                    os.path.basename(path))

    def export_blob(self):
        """Choose a destination and write the blob. A refused destination
        (inside the evidence folder) reopens SafeFolderDialog at a safe
        alternative with the file name kept, as
        MainWindow._choose_export_path does, until a safe folder is chosen
        or the examiner cancels.
        """
        start = self.export_start_path()
        while True:
            path, _filter = QFileDialog.getSaveFileName(
                self, "Save these bytes", start,
                "Raw bytes (*.bin);;All files (*)")
            if not path:
                return False
            reason = export_target.refuse_reason(
                path, self.evidence_files, self.evidence_dirs)
            if not reason:
                break
            safe = export_target.safe_alternative(path, self.evidence_dirs)
            dialog = SafeFolderDialog(self, reason, safe)
            dialog.exec()
            outcome, chosen = dialog.outcome(), dialog.path()
            dialog.deleteLater()
            if outcome == SafeFolderDialog.CHOSE_SAFE:
                path = chosen
                break
            if outcome == SafeFolderDialog.CANCELLED:
                return self._report(
                    False, "Export cancelled — nothing was written.",
                    warn=True)
            start = safe
        ok, message = self.write_blob(path)
        if ok:
            settings.save(
                last_export_dir=os.path.dirname(os.path.abspath(path)))
        return self._report(ok, message, warn=not ok)
