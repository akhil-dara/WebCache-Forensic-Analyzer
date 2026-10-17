"""The record detail dialog: every value a record carries, on one surface.

Opened from any record table with double-click or Enter
(RecordsTable.recordActivated, connected by MainWindow to
_show_record_detail). A grid shows a dozen columns of a record the engine
parses fifty-odd fields from; this dialog shows all of them.

Which fields, in what order, with what wording, and what a missing one
says are decided in detail_fields.py, tested without a QApplication; this
file paints exactly what fields_for() returns.

It lives in shell/ because it needs the engine (through detail_fields),
which widgets/ may not import, and a module in views/ could not be
imported by the record views. The table reports only that a record was
activated; the shell decides what that opens.

One scroller per region: the root is a vertical QSplitter rather than a
scroll area with the blob pane nested inside the field list, so each
region scrolls on its own.

The field list is a QTableWidget, not a QTreeWidget, which elides long
values; nothing in this dialog is truncated, and a long carved URL wraps
to full height.
"""
from PySide6.QtCore import QEvent, QItemSelectionModel, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QFont, QGuiApplication, QTextDocument
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter,
                               QTabWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

import html
import math
import types

from .. import provenance
from ..widgets import basis_badge, copyable
from ..widgets.wrapping_text import WrappingText
from ..widgets.hex_view import CLIPBOARD_BUSY, MIN_PANE_HEIGHT_PX, BlobPane
from ..widgets.records_table import WrappingDelegate
from ..widgets.record_model import CARVED_ROW_TOOLTIP, foreground
from .case_notes_bar import CaseNotesBar
from . import blob_source, detail_fields, export_target, settings, theme
from . import row_locator
from .record_kinds import K_TOMBSTONE

#: Fixed, so the badge and value columns line up on every row.
PROPERTY_LABEL_WIDTH = 250

#: The dialog is sized from its parent, never to a constant, so it fits
#: the screen without sideways scrolling.
MIN_WIDTH, MIN_HEIGHT = 920, 580
PARENT_MARGIN_W, PARENT_MARGIN_H = 260, 220

#: Painted down the left edge of the fields container for a carved record,
#: so a cropped screenshot of the dialog BODY alone still says carved.
CARVED_BORDER_PX = 3

#: The sentence a carved copy is prefixed with. Byte-exactness does not get
#: to override this: a carved record pasted into a report with no trace of
#: its provenance is a misrepresentation risk, which is the same ruling
#: copy_selection_as_tsv already makes with its Origin guarantee column.
CARVED_COPY_PREAMBLE = (
    "CARVED RECORD — recovered from unallocated space or the transaction "
    "log, not a live record.")

#: CLIPBOARD_BUSY is imported from widgets/hex_view.py rather than spelled
#: again here. Both surfaces report the same real Windows condition, and
#: two copies of a sentence that must match are two sentences that will
#: not (tests/test_record_detail_blobs.py asserts the same OBJECT).

#: Frame, margins and the clear button -- width the placeholder's own font
#: metrics cannot see.
_FILTER_BOX_CHROME_PX = 44

#: How much of the dialog the viewer opens at, before its own minimum is
#: applied. The viewer needs room but must not crowd out the field list,
#: so it opens at a fraction and can be dragged from there. On a short
#: dialog the viewer's floor (300px pane + 32px tab strip) takes
#: precedence over this fraction.
_BLOB_OPENING_FRACTION = 0.38

#: The share of the splitter the field list must keep for the viewer to
#: be worth opening at all. This is the number the whole unit turns on.
#:
#: The fields ARE the dialog. The viewer is supporting evidence for the
#: one field that has bytes -- and it costs 332px whether the record has
#: five fields or sixty-nine. On the examiner's real window the splitter
#: is 538px, so honouring the viewer's floor leaves the record 206px:
#: five rows out of sixty-seven. There is no division of 538px that
#: gives a 332px viewer AND a majority to the fields; the arithmetic
#: says the dialog is too short for both, and no ratio can argue with
#: that.
#:
#: So the viewer is only OPENED where it fits inside the minority. Where
#: it does not, it opens FOLDED -- to a bar that names the blob and
#: states its size, never to nothing, because a pane that vanishes
#: without trace is not a layout decision in a forensic tool. One click,
#: Ctrl+B, or activating the Binary field unfolds it, and the choice is
#: remembered.
_FIELDS_MAJORITY = 0.60

#: The field list's own floor, so the viewer's minimum cannot squeeze the
#: record down to two rows. Roughly six rows plus the header: enough that
#: the dialog still reads as a record with bytes attached rather than as
#: a hex editor with a caption.
_FIELDS_FLOOR_PX = 200

#: Whether the viewer was left open. None until the examiner has chosen;
#: then the geometry rule above applies, otherwise the stored choice
#: does.
BLOB_OPEN_KEY = "record_detail_blob_open"

#: A dialog carrying a viewer needs more of the screen than one that is
#: only a field list, so it takes a taller floor and a smaller margin off
#: its parent, leaving room for both the field table and the hex viewer.
MIN_HEIGHT_WITH_VIEWER = 700
PARENT_MARGIN_H_WITH_VIEWER = 120

#: The tab strip above a BlobPane, which the pane's own minimum does not
#: include.
_TAB_BAR_PX = 32

#: What a toolbar button still asks for once its own label is
#: discounted -- see ElidingButton. Wide enough to stay hittable and to
#: show the first word, narrow enough that four of them plus the filter
#: box leave the dialog free to be dragged to 1100px.
_TOOLBAR_FLOOR_PX = 72

#: The theme's own QPushButton left/right padding, which ElidingButton has
#: to allow for when it elides: font metrics cannot see a stylesheet, and
#: eliding to the raw width puts the last characters under the border.
_FOLD_BAR_PADDING_PX = 16

#: Room around the dialog's contents, and under its heading, so the title
#: reads as a heading rather than sitting against the window edge. The
#: space is not taken from the field list: merging the status line into
#: the count line's row (see _build_toolbar) returns more than these
#: margins cost.
DIALOG_MARGIN_X, DIALOG_MARGIN_TOP, DIALOG_MARGIN_BOTTOM = 16, 18, 12
HEADER_GAP_PX = 14

#: Qt's QWIDGETSIZE_MAX: what setMaximumHeight is given to mean "no
#: maximum". PySide6 does not export the constant from QtWidgets.
NO_MAXIMUM_PX = 16_777_215

#: Kept clear between the dialog and every edge of the screen's work
#: area. The dialog is never larger than the work area minus this.
SCREEN_MARGIN_PX = 24

#: The field list never shows fewer rows than this.
FIELDS_MIN_ROWS = 8

#: Said when the bytes cannot sit beside eight fields on this screen.
BYTES_IN_OWN_WINDOW = ("Not enough height on this screen for the bytes "
                       "beside the fields — opened them in their own window.")


def screen_room(widget):
    """The work area of the screen `widget` is on, minus SCREEN_MARGIN_PX
    on every side. None when there is no screen at all."""
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return None
    m = SCREEN_MARGIN_PX
    return screen.availableGeometry().adjusted(m, m, -m, -m)


def fit_to_screen(dialog):
    """Shrink `dialog` to screen_room() and move it inside it. The title
    bar and borders count against the room. Returns True if it moved or
    resized."""
    room = screen_room(dialog)
    if room is None:
        return False
    frame = dialog.frameGeometry()
    chrome_w = max(0, frame.width() - dialog.width())
    chrome_h = max(0, frame.height() - dialog.height())
    width = min(dialog.width(), room.width() - chrome_w)
    height = min(dialog.height(), room.height() - chrome_h)
    changed = (width, height) != (dialog.width(), dialog.height())
    if changed:
        dialog.resize(width, height)
    frame = dialog.frameGeometry()
    x = min(max(frame.left(), room.left()), room.right() + 1 - frame.width())
    y = min(max(frame.top(), room.top()), room.bottom() + 1 - frame.height())
    if (x, y) != (frame.left(), frame.top()):
        dialog.move(dialog.x() + x - frame.left(), dialog.y() + y - frame.top())
        changed = True
    return changed


def _tsv_safe(text):
    """Tabs and newlines are structural to a TSV consumer, so they are
    replaced, as records_table._tsv_safe does; otherwise a value would
    shift every field after it.
    """
    return (str(text).replace("\t", " ").replace("\r\n", " ")
            .replace("\n", " ").replace("\r", " "))


def build_blob_tabs(blobs, evidence_files=(), evidence_dirs=()):
    """One BlobPane per blob, in the order given.

    Module-level, and used by BOTH surfaces that mount a viewer inside
    another dialog -- this file's record detail, and the Table Browser's
    row view. The tab LABEL carries the size, so the amount of data
    behind a tab is visible before it is opened: an examiner should not
    have to click a tab to find out it holds 388 KB. The evidence paths
    travel with it, because a pane that does not know where the exhibit
    lives is a pane whose export cannot refuse to write beside it.
    """
    tabs = QTabWidget()
    tabs.setMinimumHeight(MIN_PANE_HEIGHT_PX)
    for source in blobs:
        pane = BlobPane(source, evidence_files=evidence_files,
                        evidence_dirs=evidence_dirs)
        tabs.addTab(pane, "%s · %s bytes"
                    % (source.label, "{:,}".format(source.size)))
        tabs.setTabToolTip(tabs.count() - 1, source.origin_note)
    return tabs


def splitter_room(splitter):
    """The height a splitter can give its panes, which is not its height.

    The 4px drag handle belongs to neither pane, so setSizes() must be
    computed against the height less the handle; otherwise Qt takes the
    difference from the first pane.
    """
    handles = max(0, splitter.count() - 1)
    return splitter.height() - handles * splitter.handleWidth()


def viewer_minimum(tabs, region):
    """The smallest an open viewer may be, its fold bar included.

    The panes' own measured minimum, not the tab widget's hint:
    QTabWidget.minimumSizeHint does not add up a word-wrapped label's
    needs.
    """
    panes = [tabs.widget(i) for i in range(tabs.count())]
    tabs_px = max([MIN_PANE_HEIGHT_PX]
                  + [p.minimumHeight() + _TAB_BAR_PX for p in panes])
    return tabs_px + region.bar_height()


def viewer_fits_beside_the_fields(total, wanted):
    """Whether an open viewer still leaves the list the majority.

    The fields ARE the surface; the viewer is supporting evidence for the
    one field that has bytes, and it costs the same 332px whether the
    record has five fields or sixty-nine. Where it does not fit inside
    the minority, the region opens FOLDED -- to a bar naming the bytes,
    never to nothing.
    """
    return (total - wanted) >= total * _FIELDS_MAJORITY


def divide_for_viewer(splitter, region, total, wanted,
                      fields_floor=_FIELDS_FLOOR_PX):
    """Give the viewer its minimum, or its share, but never the floor the
    list above it needs.

    Folded, the region costs its bar and every other pixel goes to the
    list. Open, it takes the larger of its own minimum and the opening
    fraction -- capped so the list keeps `fields_floor`, unless even both
    floors do not fit, where the viewer's minimum wins and the examiner
    drags: a hex dump squeezed to two rows is not a viewer.
    """
    if not region.is_expanded():
        bar = region.bar_height()
        splitter.setSizes([max(1, total - bar), bar])
        return
    blob_px = max(wanted, int(total * _BLOB_OPENING_FRACTION))
    blob_px = min(blob_px, max(wanted, total - fields_floor))
    splitter.setSizes([max(1, total - blob_px), blob_px])


def grow_for_the_viewer(dialog, shortfall):
    """Use spare screen height rather than squeeze the field list.

    When the viewer opens, the dialog grows into unused work-area height
    so the record keeps its rows.

    It only grows, and only up to the screen's work area: shrinking would
    undo a size the examiner chose, and growing past availableGeometry
    would put the button box under the taskbar. Returns True when it
    resized, so the caller can re-divide against the new height.
    """
    if shortfall <= 0:
        return False
    room = screen_room(dialog)
    if room is None:
        return False
    frame = dialog.frameGeometry()
    # The title bar and borders, which count against the work area and
    # are not part of height().
    chrome = max(0, frame.height() - dialog.height())
    wanted = min(dialog.height() + shortfall, room.height() - chrome)
    if wanted <= dialog.height():
        return False
    # Move up first, only as far as the growth needs and never above the
    # top of the work area, so the dialog can grow even when it sits low
    # on the screen. It never moves down, and does not move at all when it
    # already fits.
    top = max(room.top(), min(frame.top(),
                              room.bottom() + 1 - (wanted + chrome)))
    if top < frame.top():
        dialog.move(dialog.x(), dialog.y() - (frame.top() - top))
    dialog.resize(dialog.width(), wanted)
    return True



class _StripCell(QLabel):
    """A provenance strip cell: prefers the width of its whole text, and
    keeps a word-wrapping label's small minimum."""

    def sizeHint(self):
        hint = super().sizeHint()
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setHtml(self.text())
        width = int(doc.idealWidth()) + 2 * self.margin() + 4
        return QSize(max(hint.width(), width), hint.height())

class ElidingButton(QPushButton):
    """A button that can shrink below its own text.

    A QPushButton's minimumSizeHint includes its whole label, so a long
    fold-bar caption or one more toolbar button would set a minimum width
    for the whole dialog and stop it being resized narrower.

    This button is laid out Preferred, with a minimumSizeHint that counts
    `floor_px` instead of the text; the full text is kept and shown on
    hover, and the visible text is elided to the width the button gets.
    """

    def __init__(self, text="", floor_px=0, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._hover_note = ""
        #: What the button asks for once its text is discounted: 0 for a
        #: full-width bar, which has a row to itself; a real number for a
        #: button in a row, so it stays large enough to click.
        self.floor_px = floor_px
        # Preferred, not Ignored: in a row ending in addStretch(1), Ignored
        # would let the layout give the button zero width. Preferred asks
        # for the full label and accepts minimumSizeHint (the floor) when
        # the row is short.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        if text:
            self.set_full_text(text)

    def set_full_text(self, text, hover_note=""):
        self._full_text = text or ""
        self._hover_note = hover_note or ""
        self.setToolTip(copyable.literal_tooltip(
            "\n".join(x for x in (self._full_text, self._hover_note) if x)))
        # Named for the screen reader off the UNELIDED text: what the bar
        # says must not depend on how wide the window happens to be.
        self.setAccessibleName(self._full_text)
        self._reelide()

    def full_text(self):
        return self._full_text

    def sizeHint(self):
        """What the button ASKS for: its FULL label. QPushButton measures
        whatever text it currently shows, and once a narrow layout had
        elided that to "Co..." the button asked only for "Co..." from then
        on -- seen at 1,740 pixels wide, with the row's stretch taking the
        rest. The elided text is what it shows, never what it wants."""
        hint = super().sizeHint()
        shown = self.fontMetrics().horizontalAdvance(self.text())
        full = self.fontMetrics().horizontalAdvance(self._full_text)
        # At least the room _reelide leaves the text, or a button sized
        # to its hint would still elide its last letters.
        hint.setWidth(max(hint.width() + max(0, full - shown),
                          full + 2 * _FOLD_BAR_PADDING_PX + 2))
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(min(self.floor_px, hint.width()))
        return hint

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reelide()

    def _reelide(self):
        # The style's own horizontal padding, which the font metrics do
        # not know about -- eliding to the full width leaves the last
        # characters under the button's border.
        room = max(0, self.width() - 2 * _FOLD_BAR_PADDING_PX)
        self.setText(self.fontMetrics().elidedText(
            self._full_text, Qt.ElideRight, room))


class BlobRegion(QWidget):
    """The blob viewer, with a bar above it that folds it away.

    Not QSplitter.setCollapsible, which drags the pane to zero pixels and
    leaves nothing on screen to say the record carries bytes. Folded, this
    keeps a bar naming the blob and its byte count, one click from being
    read.

    Folding sets the region's maximum height as well as hiding the tabs:
    hiding alone would leave the region's minimum in place, and the
    splitter would keep reserving the viewer's height. Folded, the
    maximum and the minimum are both the bar.
    """

    #: The fold changed: (expanded, deliberate). The dialog re-divides the
    #: splitter on every change, so a fold always frees its space, and
    #: remembers only deliberate ones. A signal, so the region knows
    #: nothing about settings.
    foldChanged = Signal(bool, bool)

    def __init__(self, tabs, summary, parent=None):
        super().__init__(parent)
        self.tabs = tabs
        self._summary = summary
        self._expanded = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.toggle_button = ElidingButton()
        self.toggle_button.setAutoDefault(False)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(True)
        # Left-aligned like a disclosure row rather than centred like a
        # command button: it heads the region beneath it.
        self.toggle_button.setStyleSheet("QPushButton { text-align: left; }")
        self.toggle_button.clicked.connect(
            lambda checked: self.set_expanded(checked, deliberate=True))
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.tabs, 1)

        self._bar_px = max(self.toggle_button.sizeHint().height(),
                           self.toggle_button.minimumSizeHint().height())
        self._relabel()

    # --- the fold ---------------------------------------------------------

    def is_expanded(self):
        return self._expanded

    def bar_height(self):
        """What the region costs the splitter when folded, measured from
        the button rather than a constant."""
        return self._bar_px + 2

    def expanded_minimum(self):
        """What the region costs the splitter when open: the bar plus
        everything the tab widget's own minimum asks for."""
        return self.bar_height() + max(self.tabs.minimumHeight(),
                                       self.tabs.minimumSizeHint().height())

    def set_expanded(self, expanded, deliberate=False):
        # Applied unconditionally, including when the state is already
        # what is being asked for: the constructor leaves _expanded True
        # with no minimum or maximum written, so the first call has real
        # geometry work to do even though it changes nothing.
        self._expanded = bool(expanded)
        self.tabs.setVisible(self._expanded)
        self.toggle_button.setChecked(self._expanded)
        if self._expanded:
            self.setMaximumHeight(NO_MAXIMUM_PX)
            self.setMinimumHeight(self.expanded_minimum())
        else:
            # Both, in this order: a minimum still at the open height would
            # conflict with the maximum.
            self.setMinimumHeight(self.bar_height())
            self.setMaximumHeight(self.bar_height())
        self._relabel()
        self.foldChanged.emit(self._expanded, bool(deliberate))

    def _relabel(self):
        arrow = "▾" if self._expanded else "▸"
        action = "hide" if self._expanded else "show"
        self.toggle_button.set_full_text(
            "%s  %s" % (arrow, self._summary),
            "Ctrl+B — %s the bytes this record carries. The fields above "
            "are the record; this is the raw data behind one of them."
            % action)


class RecordDetailDialog(QDialog):
    """One record, every field, modeless.

    Modeless and stacking: a record opened from another dialog leaves the
    first open behind it, so no Back button is needed.
    """

    #: A member row of an aggregate was activated. MainWindow turns this
    #: into another RecordDetailDialog.
    recordRequested = Signal(object)
    #: F1 on a field. Carries the fully composed text; MainWindow shows it
    #: in the SAME ExplainDialog the grid's F1 uses. A signal rather than
    #: constructing ExplainDialog here, because main_window imports this
    #: module and importing it back would be a cycle.
    explainRequested = Signal(str)
    #: "Show in database table" / "Show table ... (row deleted ...)"
    #:: MainWindow opens Table Browser. A carved record's action
    #: never emits -- it reveals this dialog's own bytes.
    showInTableRequested = Signal(object)

    #: A tag or comment was saved on this record.
    caseNotesChanged = Signal()

    def __init__(self, row, parent=None, db_path="", evidence_set=None,
                 case=None, author=""):
        """`db_path` and `evidence_set` come from MainWindow, never from
        the row.

        A carved record names its source file by BASENAME, so the window
        behind the "Bytes at the carve offset" tab can only be resolved
        against the exhibit the shell currently has open. Passed
        explicitly rather than sniffed off the parent: a dialog opened
        from another dialog has a RecordDetailDialog for a parent, and a
        drilled-to record has to be able to read the same exhibit the one
        it came from could.
        """
        super().__init__(parent)
        self.row = row if isinstance(row, dict) else {}
        self.db_path = db_path or ""
        self.evidence_set = evidence_set
        # Every BlobPane this dialog mounts needs
        # to know where the exhibit lives so its own export can refuse to
        # write beside it -- computed once, here, rather than in each
        # pane, so a carved record's several blobs (and the drilled
        # dialogs opened from them) all refuse against the SAME exhibit.
        self._evidence_files, self._evidence_dirs = export_target.evidence_paths(
            self.evidence_set, types.SimpleNamespace(db_path=self.db_path))
        self.groups = detail_fields.fields_for(self.row)
        self._all_groups = self.groups
        self._rows = []          # table row -> DetailField or None (heading)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("Record detail")
        self.is_carved = str(self.row.get("Origin") or "").startswith("Carved")
        self.carved_border_px = CARVED_BORDER_PX if self.is_carved else 0
        self.blob_area = None
        self.blob_region = None
        self._bytes_windows = []
        self._splitter_sized = False
        self._fold_decided = False
        # Built BEFORE the layout, because whether there is a bottom pane
        # at all depends on what came back: a carved record with no blobs
        # of its own still has the bytes at its carve offset, and a live
        # record with none has nothing and gets no pane.
        self.blobs = blob_source.blobs_for(self.row, self.db_path,
                                           self.evidence_set)

        # Sized AFTER blobs_for, because whether there is a viewer
        # decides how much height this dialog needs -- see
        # MIN_HEIGHT_WITH_VIEWER.
        floor = MIN_HEIGHT_WITH_VIEWER if self.blobs else MIN_HEIGHT
        margin = (PARENT_MARGIN_H_WITH_VIEWER if self.blobs
                  else PARENT_MARGIN_H)
        if parent is not None:
            self.resize(max(MIN_WIDTH, parent.width() - PARENT_MARGIN_W),
                        max(floor, parent.height() - margin))
        else:
            self.resize(MIN_WIDTH, floor)
        # Clamped here and again in showEvent: before the dialog is on
        # screen, widget.screen() can only guess (usually the primary
        # screen), so on a secondary screen with a different work area the
        # second clamp, after the platform places the window, is the one
        # that holds.
        fit_to_screen(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(DIALOG_MARGIN_X, DIALOG_MARGIN_TOP,
                                DIALOG_MARGIN_X, DIALOG_MARGIN_BOTTOM)
        root.addWidget(self._build_header())
        # The examiner's own notes on this record: tags and comments,
        # saved to the case file as they are made.
        self.notes_bar = CaseNotesBar(case, [self.row], author=author,
                                      parent=self)
        self.notes_bar.changed.connect(self.caseNotesChanged.emit)
        root.addWidget(self.notes_bar)
        self.banner = self._build_banner()
        if self.banner is not None:
            root.addWidget(self.banner)
        root.addLayout(self._build_toolbar())

        # The count line and the copy confirmation share one row, so the
        # confirmation appears near what was copied, and the field list
        # keeps the height a separate status row would take.
        summary = QHBoxLayout()
        self.count_label = copyable.selectable(QLabel())
        self.count_label.setWordWrap(True)
        summary.addWidget(self.count_label, 1)
        # Off by default: the record is shown whole. On, fields that state
        # why they have no value are hidden, and the count line says how
        # many. On this row rather than the toolbar, so the toolbar's
        # minimum width stays small enough for the dialog to shrink.
        self.hide_empty_box = QCheckBox("Hide empty fields")
        self.hide_empty_box.toggled.connect(
            lambda _on: self.apply_filter(self.filter_box.text()))
        self.status_label = copyable.selectable(QLabel(""))
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # Ignored horizontally, like hex_view's own status label: "Copied
        # Response headers / property store." must not be able to put a
        # floor under the whole dialog's width.
        self.status_label.setSizePolicy(QSizePolicy.Ignored,
                                        QSizePolicy.Preferred)
        self.status_label.setStyleSheet(
            "color: %s;" % theme.color("muted").name())
        summary.addWidget(self.status_label, 1)
        # Last, at the row's right end: under the filter box, the other
        # control that narrows the list.
        summary.addWidget(self.hide_empty_box)
        root.addLayout(summary)

        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.splitterMoved.connect(self._remember_the_examiner_moved_it)
        self._splitter.addWidget(self._build_fields())
        # The bottom pane exists only when the record carries bytes: no
        # empty box and no "(no data)" placeholder.
        if self.blobs:
            self.blob_area = self._build_blob_tabs()
            self.blob_region = BlobRegion(self.blob_area,
                                          self._blob_summary())
            self.blob_region.foldChanged.connect(self._fold_changed)
            self._splitter.addWidget(self.blob_region)
            self._splitter.setStretchFactor(0, 1)
            self._splitter.setStretchFactor(1, 0)
            # Sized in showEvent: at construction the splitter is not laid
            # out, and sizes computed now would be rescaled by Qt.
        # The fields and the bytes scroll inside the dialog, so their
        # minimums (eight field rows, the viewer's floor) do not become the
        # window's minimum and push Close off the screen.
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        self.body_scroll.setWidget(self._splitter)
        root.addWidget(self.body_scroll, 1)

        buttons = QDialogButtonBox()
        close = buttons.addButton("Close", QDialogButtonBox.AcceptRole)
        self.close_button = close
        close.setDefault(False)
        close.setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._populate()
        self._refresh_copy_field_button()
        self._wire_keys()
        if self.is_carved:
            self.setAccessibleName("Carved record detail")
            self.setAccessibleDescription(CARVED_ROW_TOOLTIP)
        else:
            self.setAccessibleName("Record detail")
            self.setAccessibleDescription(
                "Every field this live record carries.")

    # --- construction ----------------------------------------------------

    def _build_header(self):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        line = QHBoxLayout()
        self.carved_chip = copyable.selectable(QLabel(
            detail_fields.STUB_TITLE
            if self.row.get("_kind") == K_TOMBSTONE else "CARVED RECORD"))
        self.carved_chip.setToolTip(CARVED_ROW_TOOLTIP)
        self.carved_chip.setAccessibleDescription(CARVED_ROW_TOOLTIP)
        # Spelled out in full, unlike the grid's one-character vertical
        # header marker -- this surface has no pixel constraint, so nothing
        # here needs abbreviating to "C".
        self.carved_chip.setStyleSheet(
            "color: %s; border: 1px solid %s; border-radius: 3px; "
            "padding: 1px 6px; font-weight: bold;"
            % (theme.color("carved").name(), theme.color("carved").name()))
        self.carved_chip.setVisible(self.is_carved)
        line.addWidget(self.carved_chip)

        # the identity line WRAPS and stays whole and copyable.
        # WrappingText, not a QLabel: a long unbroken URL wraps at any
        # character instead of flooring the dialog's width, and nothing
        # is cut.
        identity = detail_fields.identity_of(self.row)
        self.identity_label = WrappingText(identity)
        font = QFont(self.identity_label.font())
        font.setBold(True)
        self.identity_label.setFont(font)
        line.addWidget(self.identity_label, 1)
        layout.addLayout(line)

        self.origin_label = QLabel(detail_fields.origin_line(self.row))
        copyable.selectable(self.origin_label)
        self.origin_label.setWordWrap(True)
        self.origin_label.setStyleSheet(
            "color: %s;" % theme.color("muted2").name())
        layout.addWidget(self.origin_label)

        # the other record of the same visit, named as a
        # plain, copyable identity -- never a link, never an opener.
        self.twin_label = QLabel(detail_fields.twin_line(self.row))
        self.twin_label.setTextFormat(Qt.PlainText)
        copyable.selectable(self.twin_label)
        self.twin_label.setWordWrap(True)
        self.twin_label.setStyleSheet(
            "color: %s;" % theme.color("muted2").name())
        self.twin_label.setVisible(bool(self.twin_label.text()))
        layout.addWidget(self.twin_label)

        # Labelled, under the one-line origin sentence. The
        # sentence above already says WHAT this row is ("Carved (deleted/
        # unflushed)"); this strip says WHERE it came from, as facts an
        # examiner can read at a glance instead of parsing out of a run-on
        # sentence lower down. [] for a live record: no strip is built.
        facts = detail_fields.provenance_facts(self.row)
        self.provenance_strip = None
        if facts:
            strip = QWidget()
            lay = QHBoxLayout(strip)
            lay.setContentsMargins(0, 4, 0, 0)
            lay.setSpacing(18)
            for label, value in facts:
                cell = _StripCell("<span style='color:%s'>%s</span>&nbsp; <b>%s</b>"
                              % (theme.color("muted").name(),
                                 html.escape(label), html.escape(value)))
                # Markup on purpose, every value escaped above -- declared,
                # never left to AutoText's guess.
                cell.setTextFormat(Qt.RichText)
                # Mouse only, per copyable.py: TextSelectableByKeyboard
                # makes a QLabel accept keyboard focus, which would pull
                # every strip cell into the dialog's Tab chain. A
                # selectable label already gets Qt's standard right-click
                # Copy and Ctrl+C on a mouse selection -- keyboard focus
                # is not required for "everything visible is copyable".
                copyable.selectable(cell)
                # setWordWrap, as origin_label above: without it a QLabel's
                # minimumSizeHint is its full single-line width (a long
                # Method or Source string), which would set the dialog's
                # minimum width (test_record_detail_blobs.py's 1100x700
                # test).
                cell.setWordWrap(True)
                # ...but a wrapping label PREFERS far less width than its
                # text, so "Method  Structured record reconstruction" folded
                # onto three lines beside an empty strip. _StripCell prefers
                # its whole text and keeps the wrapping minimum: one line
                # when there is room, wrapped when there is not, so the
                # floor above holds.
                lay.addWidget(cell)
            lay.addStretch(1)
            layout.addWidget(strip)
            self.provenance_strip = strip
        # Under the heading, inside the header's own box rather than as
        # layout spacing outside it: spacing between two siblings is
        # split by Qt when either is squeezed, and this gap is what makes
        # the two lines above read as a heading rather than as the first
        # row of the toolbar.
        layout.addSpacing(HEADER_GAP_PX)
        return box

    def _build_banner(self):
        """Only when the carve is not intact.

        A mis-bounded string is flagged before it can be read as a
        recorded URL. An intact carve gets no banner, so the banner keeps
        its meaning.
        """
        quality = [g for g in self.groups
                   if g.name == detail_fields.G_QUALITY]
        if not quality:
            return None
        parts = ["%s: %s" % (f.label, f.display_value)
                 for f in quality[0].fields if not f.absence]
        label = copyable.selectable(
            QLabel("  ·  ".join(parts) or quality[0].fields[0].display_value))
        label.setWordWrap(True)
        label.setStyleSheet(
            "color: %s; border: 1px solid %s; border-radius: 3px; "
            "padding: 6px;"
            % (theme.color("warn").name(), theme.color("warn").name()))
        return label

    def _build_toolbar(self):
        bar = QHBoxLayout()
        # First, before "Copy all fields": copying one field is the most
        # common copy, and the button makes it visible (it is also on the
        # context menu, Ctrl+C and Enter). An ElidingButton, so a fourth
        # label in this row does not set the dialog's minimum width; its
        # floor is about the word "Copy" plus padding.
        self.copy_field_button = ElidingButton("Copy field",
                                               floor_px=_TOOLBAR_FLOOR_PX)
        self.copy_field_button.clicked.connect(
            lambda: self.copy_field(self._current_index()))
        self.copy_all_button = QPushButton("Copy all fields")
        self.copy_all_button.clicked.connect(self.copy_all)
        self.copy_tsv_button = QPushButton("Copy as TSV")
        self.copy_tsv_button.clicked.connect(self.copy_tsv)
        # ElidingButton for the same reason: the source action
        # made a sixth control in this row, and with every label rigid the
        # row's minimum passed 1100px again. At any real width all of them
        # show whole; only a window squeezed below the labels elides.
        self.explain_button = ElidingButton("Explain this record",
                                            floor_px=_TOOLBAR_FLOOR_PX)
        self.explain_button.clicked.connect(self._explain_record)
        # From this record to its raw row, its bytes, or its table.
        # ElidingButton: a stub's label names a table and a key and can be
        # long; the full text is the tooltip.
        self._source_ref = row_locator.source_row(self.row)
        self.source_button = ElidingButton(floor_px=_TOOLBAR_FLOOR_PX)
        if self._source_ref is None:
            self.source_button.setVisible(False)
        else:
            self.source_button.set_full_text(
                row_locator.action_label(self._source_ref))
        self.source_button.clicked.connect(self._show_source)
        for button in (self.copy_field_button, self.copy_all_button,
                       self.copy_tsv_button, self.explain_button,
                       self.source_button):
            button.setAutoDefault(False)
            bar.addWidget(button)
        bar.addStretch(1)
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filter fields (Ctrl+F)")
        self.filter_box.setClearButtonEnabled(True)
        # Never narrower than its placeholder text, so "Filter fields
        # (Ctrl+F)" is not cut off. The clear button and the frame take
        # width the font metrics do not include, hence the allowance.
        needed = self.filter_box.fontMetrics().horizontalAdvance(
            self.filter_box.placeholderText())
        self.filter_box.setMinimumWidth(needed + _FILTER_BOX_CHROME_PX)
        self.filter_box.setMaximumWidth(needed + 2 * _FILTER_BOX_CHROME_PX)
        self.filter_box.textChanged.connect(self.apply_filter)
        bar.addWidget(self.filter_box)
        return bar

    def _build_fields(self):
        frame = QFrame()
        self._fields_frame = frame
        if self.is_carved:
            frame.setStyleSheet(
                "QFrame { border-left: %dpx solid %s; }"
                % (CARVED_BORDER_PX, theme.color("carved").name()))
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(CARVED_BORDER_PX + 2, 0, 0, 0)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Field", "Value", "Basis"])
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(0, PROPERTY_LABEL_WIDTH)
        self.table.setColumnWidth(2, 60)
        # Rows size to their CONTENT, which is what lets a 2,000-character
        # carved URL wrap to full height instead of being elided.
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        # As in RecordsTable: the QSS rule for QTableView::item makes
        # QStyleSheetStyle paint the item and ignore Qt.BackgroundRole, so
        # the carved tint set in _add_field needs this delegate (see
        # record_model.BackgroundRoleDelegate). WrappingDelegate, a
        # BackgroundRoleDelegate, also breaks a run with no break
        # opportunity rather than cutting it at the cell edge. ElideNone:
        # nothing here is shortened.
        self.table.setItemDelegate(WrappingDelegate(self.table))
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setItemDelegateForColumn(2, basis_badge.BadgeDelegate(self.table))
        self.table.itemDoubleClicked.connect(
            lambda item: self.activate_field(self._field_index(item.row())))
        # currentCellChanged, not itemSelectionChanged: a keyboard
        # examiner arrowing down the list moves the CURRENT cell, and
        # with SelectRows that also moves the selection -- but the
        # current cell is what copy_field acts on, so the button has to
        # track the same thing the action does or it will be enabled for
        # one row and copy another.
        self.table.currentCellChanged.connect(
            lambda *_a: self._refresh_copy_field_button())
        self.table.itemSelectionChanged.connect(
            self._refresh_copy_field_button)
        layout.addWidget(self.table)
        return frame

    def _refresh_copy_field_button(self):
        """What "Copy field" will act on, said before it is pressed.

        Disabled outright on a heading row: a button that looks live and
        does nothing is worse than one that plainly is not, and a heading
        is a spanned row with no field behind it at all.
        """
        field = self._field(self._current_index())
        self.copy_field_button.setEnabled(field is not None)
        if field is None:
            self.copy_field_button.setToolTip(
                "Ctrl+C — select a field in the list below to copy its "
                "value.")
            return
        self.copy_field_button.setToolTip(
            "Ctrl+C — copy the value of “%s” exactly as stored, "
            "with no label in front of it. Right-click the row for the "
            "labelled copy and the raw FILETIME." % field.label)

    def _has_blobs(self):
        return bool(self.blobs)

    def _build_blob_tabs(self):
        """One tab per blob, in blobs_for's order: the record's own bytes
        first and the carve window last.

        Built by the module-level builder, which the Table Browser's row
        view also uses (table_row_detail.py), so tab labels, tooltips and
        export guards are the same on both.
        """
        return build_blob_tabs(self.blobs, self._evidence_files,
                               self._evidence_dirs)

    def _blob_summary(self):
        """What the fold bar says the region holds.

        Names the blob and its size in the SAME words the tab label uses,
        so a folded region and an open one describe the same thing. With
        several blobs it counts them rather than listing them -- a bar
        that wraps to two lines is a bar that costs the fields a row.
        """
        first = self.blobs[0]
        head = "%s · %s bytes" % (first.label, "{:,}".format(first.size))
        if len(self.blobs) > 1:
            head = "%s, and %d more" % (head, len(self.blobs) - 1)
        return "Bytes: %s" % head

    def blob_pane_for(self, blob_key):
        """The tab index showing the blob stored under `blob_key`, or -1.

        Matched on the key, not the tab label, which carries a formatted
        size.
        """
        if self.blob_area is None:
            return -1
        for index in range(self.blob_area.count()):
            if self.blob_area.widget(index).blob_key == blob_key:
                return index
        return -1

    def toggle_blob_region(self):
        """Ctrl+B, and the fold bar's own click. Returns the new state,
        or None where the record carries no bytes at all -- there is
        nothing to fold and nothing to say about it."""
        if self.blob_region is None:
            self.status_label.setText(
                "This record carries no binary data.")
            self.status_label.setStyleSheet(
                "color: %s;" % theme.color("muted").name())
            return None
        self.blob_region.set_expanded(not self.blob_region.is_expanded(),
                                      deliberate=True)
        return self.blob_region.is_expanded()

    def show_blob_region(self):
        """Unfold, if folded. Not deliberate: opening a Binary field is
        navigation to one value, not a layout preference, so nothing is
        written to settings. The fold bar and Ctrl+B state a preference;
        this only makes the tab being switched to visible."""
        self.reveal_bytes()

    def open_bytes_window(self):
        """The bytes of the current tab in their own viewer window.

        One window per blob per dialog. When the viewer cannot fit beside
        the fields, each click falls back to this and the fold reverts (see
        _fold_changed), so an open window for the same blob is found and
        raised rather than a second one opened. Matched by field_key
        (hex_view.BlobPane.blob_key), since blobs_for() may return a new
        BlobSource each call.
        """
        if not self.blobs:
            return None
        index = self.blob_area.currentIndex() if self.blob_area is not None else 0
        source = self.blobs[max(0, index)]
        key = getattr(source, "field_key", "")
        for window in self._bytes_windows:
            if (window.source is not None
                    and getattr(window.source, "field_key", "") == key):
                window.raise_()
                window.activateWindow()
                return window
        window = BlobViewerDialog(
            source, self, context=detail_fields.identity_of(self.row),
            db_path=self.db_path, evidence_set=self.evidence_set)
        window.destroyed.connect(
            lambda *_a, w=window: self._bytes_windows.remove(w)
            if w in self._bytes_windows else None)
        self._bytes_windows.append(window)
        window.show()
        return window

    def _show_source(self):
        ref = self._source_ref
        if ref is None:
            return
        if ref.kind == row_locator.CARVED:
            if self.reveal_bytes(tab=blob_source.CARVE_TAB_LABEL) is None:
                # The carve window is read from the exhibit; without it (or
                # with the offset outside it) there are no bytes, and the
                # button says so.
                self.status_label.setText(
                    "No bytes at the carve offset can be shown: the file "
                    "this record was carved from is not the exhibit open "
                    "now, or the offset is not in it.")
            return
        self.showInTableRequested.emit(self.row)

    def _cap_height(self):
        """Never taller than the screen's work area, title bar included."""
        room = screen_room(self)
        if room is None:
            return
        chrome = max(0, self.frameGeometry().height() - self.height())
        cap = max(1, room.height() - chrome)
        if self.maximumHeight() != cap:
            self.setMaximumHeight(cap)
        if self.height() > cap:
            self.resize(self.width(), cap)

    def select_blob_tab(self, label):
        """Show the blob tab whose label is `label` -- by name, never by
        position: a carved record with its own response headers has them
        first and the carve window last."""
        if self.blob_area is None:
            return False
        for index, source in enumerate(self.blobs):
            if source.label == label:
                self.blob_area.setCurrentIndex(index)
                return True
        return False

    def reveal_bytes(self, tab=None):
        """Show the bytes: beside the fields when they fit after growing to
        the screen, otherwise in their own window (BYTES_IN_OWN_WINDOW).
        `tab` names the blob to show (the carve window for "Show bytes at
        the carve offset") and is selected before unfolding or opening a
        window. Used by Show bytes at the carve offset and by activating a
        Binary field."""
        if self.blob_region is None:
            return None
        if tab is not None and not self.select_blob_tab(tab):
            return None
        if not self.blob_region.is_expanded():
            self.blob_region.set_expanded(True)
        self._cap_height()
        if self.blob_region.is_expanded():
            return self.blob_region
        return self.open_bytes_window()

    def current_blob_pane(self):
        if self.blob_area is None:
            return None
        return self.blob_area.currentWidget()

    def export_focused_blob(self):
        """Ctrl+E. The blob whose tab is showing, never "the first one"."""
        pane = self.current_blob_pane()
        if pane is None:
            self.status_label.setText(
                "This record carries no binary data to export.")
            return False
        return pane.export_blob()

    def _wire_keys(self):
        """Escape is handled by an installed filter; every other key in
        keyPressEvent below.

        Not QShortcut: these dialogs stack, and a QShortcut's
        WindowShortcut context matches QApplication.activeWindow(), which
        with several dialogs alive is ambiguous; Ctrl+W must close the
        dialog the examiner is looking at. WindowShortcut also fires only
        while the platform considers the dialog active, and
        WidgetWithChildrenShortcut only while a focus widget is set.
        RecordsTable handles Ctrl+Enter the same way.
        """
        self.filter_box.installEventFilter(self)
        self.table.installEventFilter(self)

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        if ctrl and key == Qt.Key_W:
            self.close()
            return
        if ctrl and key == Qt.Key_F:
            self.filter_box.setFocus()
            self.filter_box.selectAll()
            return
        if ctrl and key == Qt.Key_C:
            self.copy_all() if shift else self._copy_selection()
            return
        if ctrl and key == Qt.Key_E:
            self.export_focused_blob()
            return
        if ctrl and key == Qt.Key_B:
            self.toggle_blob_region()
            return
        if key == Qt.Key_F1:
            self.explain_field(self._current_index())
            return
        if key in (Qt.Key_Return, Qt.Key_Enter) and not self.filter_box.hasFocus():
            # BEFORE super(): QDialog treats Enter as "press the default
            # button", which here would accept and close the dialog. Enter
            # on a field row must copy that field (or open that record),
            # not throw away the record being read.
            self.activate_field(self._current_index())
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        """Escape in the filter box clears it and keeps the dialog open.

        See _wire_keys for why this is an event filter rather than a
        QShortcut. Returning True CONSUMES the key so QDialog's own
        Escape-closes-the-dialog handling never sees it -- but only while
        there is a filter in force. With the box already empty, Escape
        falls through and closes the dialog.
        """
        if event.type() != QEvent.KeyPress:
            return super().eventFilter(watched, event)
        if (watched is self.filter_box and event.key() == Qt.Key_Escape
                and self.filter_box.text()):
            self.filter_box.setText("")
            return True
        if watched is self.table and event.key() in (
                Qt.Key_Return, Qt.Key_Enter, Qt.Key_F1):
            # QAbstractItemView consumes Enter (it means "edit this cell"
            # to a view, even with NoEditTriggers set), so it never reaches
            # the dialog's own keyPressEvent by propagation. Intercepted
            # here instead, before the view sees it.
            self.keyPressEvent(event)
            return True
        return super().eventFilter(watched, event)

    # --- populating ------------------------------------------------------

    def _populate(self, needle=""):
        """Rebuild the table from self.groups, keeping only fields that
        match `needle`. A group with nothing left is dropped entirely --
        an empty heading says a group exists and has no fields, which is
        not what a filter did."""
        # Captured BEFORE setRowCount(0), which drops the current row:
        # _populate runs on every filter keystroke, and a filter that
        # still shows the selected field must not deselect it.
        held = self.field_at(self.table.currentRow())
        # By key, not label: the key is this field's stable identity
        # (detail_fields.DetailField), the label is prose that may be
        # reworded.
        held_key = held.key if held is not None else None
        self.table.setRowCount(0)
        self._rows = []
        hide_empty = self.hide_empty_box.isChecked()
        for group in self.groups:
            visible = [f for f in group.fields if _matches(f, needle)
                       and not (hide_empty and f.absence)]
            if not visible:
                continue
            self._add_heading(group.name)
            for field in visible:
                self._add_field(field)
        self._resize_rows()
        self._restore_or_choose_a_field(held_key)
        self._refresh_count(needle)

    def _restore_or_choose_a_field(self, held_key):
        """Keep the examiner's field selected, or select one if none is.

        On open nothing is selected, which would leave "Copy field"
        disabled as if copying were unavailable for this record.

        Never lands on a section heading (self._rows holds None for those),
        and prefers a field that carries a value, since an absent one
        leaves the button disabled anyway.
        """
        rows = range(len(self._rows))
        if held_key is not None:
            back = next((r for r in rows
                         if self._rows[r] is not None
                         and self._rows[r].key == held_key), None)
            if back is not None:
                return self._select_only(back)
        pick = next((r for r in rows
                     if self._rows[r] is not None
                     and self._rows[r].absence is None), None)
        if pick is None:
            pick = next((r for r in rows if self._rows[r] is not None), None)
        if pick is not None:
            self._select_only(pick)

    def _select_only(self, row):
        """Select exactly this row, whatever modifier keys Qt believes are
        held.

        With Ctrl held, setCurrentCell() adds to the selection rather than
        replacing it. This is the dialog's own initial selection, so it is
        always exactly one row.
        """
        self.table.setCurrentCell(row, 0, QItemSelectionModel.ClearAndSelect
                                   | QItemSelectionModel.Rows)

    def _resize_rows(self):
        """Re-measure every row against the current column width.

        A word-wrapped cell's height depends on its column's width, and the
        value column stretches, so rows are re-measured when the width
        changes; otherwise a long value would wrap to more lines than its
        row holds and its last line would be clipped.
        """
        if self.table is not None:
            self.table.resizeRowsToContents()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_rows()
        self._apply_splitter_sizes()

    def showEvent(self, event):
        super().showEvent(event)
        # Again now the title bar exists, since it counts against the room.
        fit_to_screen(self)
        self._cap_height()
        self._fields_frame.setMinimumHeight(self._fields_floor())
        self._apply_splitter_sizes()
        self._cap_height()

    def _remember_the_examiner_moved_it(self, *_args):
        """Once the handle has been dragged, the split is theirs.

        Without this the automatic sizing below would undo a deliberate
        drag on the next resize -- a window that argues with the person
        using it.
        """
        self._splitter_sized = True

    def _apply_splitter_sizes(self, force=False):
        """Re-applied on every resize until the examiner drags the handle,
        so the split always matches the dialog's current height.
        """
        """Divide the splitter, re-applied until the handle is dragged.

        Measured against the SPLITTER's own height rather than the
        dialog's: the header, toolbar, count line and button box take a
        hundred-odd pixels the dialog knows about and the splitter does
        not, and sizes computed from the wrong one are rescaled by Qt
        into a split nobody chose.
        """
        if self.blob_region is None or (self._splitter_sized and not force):
            return
        total = self._splitter_room()
        if total <= 0:
            return

        self._decide_the_fold(total)
        divide_for_viewer(self._splitter, self.blob_region, total,
                          self._viewer_minimum(),
                          fields_floor=self._fields_floor())

    def _grow_for_the_viewer(self):
        """Use spare screen height rather than squeeze the record.

        When the viewer opens, the dialog grows into unused work-area height
        so the field list keeps its rows.

        It only grows, and only up to the screen's work area: shrinking
        would undo a size the examiner chose, and growing past
        availableGeometry would put the button box under the taskbar.
        Nothing here moves the window; if there is no room below it, Qt
        clamps and the examiner can drag the splitter.
        """
        if self.blob_region is None:
            return
        viewer_min = self._viewer_minimum()
        # Two needs; the larger wins. Both floors must fit (viewer_min +
        # fields_floor), but the viewer's minimum is fixed while
        # fields_floor is eight rows at the current font, which can be
        # shorter than the viewer's minimum. The second term asks for the
        # total viewer_fits_beside_the_fields would have opened the pane
        # at, so the fields keep _FIELDS_MAJORITY.
        needed = max(viewer_min + self._fields_floor(),
                     math.ceil(viewer_min / (1 - _FIELDS_MAJORITY)))
        shortfall = needed - self._splitter_room()
        if not grow_for_the_viewer(self, shortfall):
            return
        # Bring the layout up to date before measuring. A resize from
        # inside showEvent, before the window is exposed, delivers no
        # resizeEvent, and layout().activate() does nothing unless the
        # layout's cached geometry is marked stale, so it is invalidated
        # first.
        if self.layout() is not None:
            self.layout().invalidate()
            self.layout().activate()
        # The splitter is in a scroll area, whose viewport is resized only
        # by an event not yet delivered here; it is applied now so the fit
        # check measures the current height.
        self._settle_body()
        # Re-divided here rather than left to the resize event, because a
        # resize the platform refuses delivers no event at all.
        self._apply_splitter_sizes(force=True)

    def _settle_body(self):
        """Bring the splitter to the scroll area's current viewport now."""
        area = self.body_scroll
        area.widget().resize(
            max(area.viewport().width(), area.widget().minimumSizeHint().width()),
            max(area.height() - 2 * area.frameWidth(),
                area.widget().minimumSizeHint().height()))

    def _splitter_room(self):
        """What the splitter can really show: never more than the scroll
        area's own viewport. The splitter is stretched to its minimum size
        hint when that exceeds the viewport, and measuring THAT made an
        unfittable viewer look as if it fitted -- it then opened inline
        with all but a line of it scrolled out of sight."""
        area = self.body_scroll
        handles = max(0, self._splitter.count() - 1)
        seen = (area.height() - 2 * area.frameWidth()
                - handles * self._splitter.handleWidth())
        return min(splitter_room(self._splitter), seen)

    def _viewer_minimum(self):
        return viewer_minimum(self.blob_area, self.blob_region)

    def _fields_floor(self):
        """The height the first FIELDS_MIN_ROWS rows take (rows are
        ResizeToContents, so a wrapped value counts at its real height),
        plus the header, never below _FIELDS_FLOOR_PX. A record with fewer
        rows is padded with default-height ones."""
        header = self.table.horizontalHeader().sizeHint().height()
        count = self.table.rowCount()
        rows = sum(self.table.rowHeight(r)
                   for r in range(min(FIELDS_MIN_ROWS, count)))
        rows += (max(0, FIELDS_MIN_ROWS - count)
                 * self.table.verticalHeader().defaultSectionSize())
        return max(_FIELDS_FLOOR_PX, header + rows + 2 * self.table.frameWidth())

    def _viewer_fits(self):
        return (self._splitter_room()
                >= self._fields_floor() + self._viewer_minimum())

    def _decide_the_fold(self, total):
        """Once per dialog, and only where the examiner has not already
        said.

        A stored preference wins outright -- an examiner who works in the
        bytes should set it once. With nothing stored, the geometry
        decides: the viewer opens only where its own minimum still leaves
        the field list _FIELDS_MAJORITY of the splitter. On the real
        1279x724 window it does not (332px of 538 is 62%), so it opens
        folded, which is the whole point: five rows of a sixty-seven
        field record becomes thirteen, and the bytes stay one click away
        with a bar that names them.
        """
        if self._fold_decided:
            return
        self._fold_decided = True
        if self.is_carved:
            # A carved record's bytes start folded to their named bar,
            # whatever was stored: the recovered fields come first.
            self.blob_region.set_expanded(False)
            return
        stored = settings.get(BLOB_OPEN_KEY, None)
        if isinstance(stored, bool):
            self.blob_region.set_expanded(stored)
            return
        self.blob_region.set_expanded(
            viewer_fits_beside_the_fields(total, self._viewer_minimum()))

    def _fold_changed(self, expanded, deliberate):
        """Re-divide always; remember only a DELIBERATE toggle. An open
        that cannot sit beside FIELDS_MIN_ROWS rows even after growing to
        the screen folds back; if the examiner asked for it, the bytes
        open in their own window instead (8 rows + a 332px viewer do not
        fit an 816px work area)."""
        if deliberate:
            settings.save(**{BLOB_OPEN_KEY: bool(expanded)})
        if expanded:
            if deliberate and self.is_carved:
                # The fold bar on a carved record names the carve window,
                # not whichever blob happens to be first.
                self.select_blob_tab(blob_source.CARVE_TAB_LABEL)
            self._grow_for_the_viewer()
            if not self._viewer_fits():
                self.blob_region.set_expanded(False)
                if deliberate:
                    self.open_bytes_window()
                    self._report(True, BYTES_IN_OWN_WINDOW)
                return
        self._apply_splitter_sizes(force=True)

    def _add_heading(self, name):
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(name.upper())
        font = QFont(item.font())
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QBrush(theme.color("muted2")))
        item.setFlags(Qt.ItemIsEnabled)
        self.table.setItem(row, 0, item)
        # A REAL spanned row, not a pseudo-field: a pseudo-field would
        # count toward the field total and carry a copy button that
        # copies nothing.
        self.table.setSpan(row, 0, 1, 3)
        self._rows.append(None)

    def _add_field(self, field):
        row = self.table.rowCount()
        self.table.insertRow(row)

        label = QTableWidgetItem(field.label)
        label.setToolTip(field.label if not field.note
                         else "%s\n%s" % (field.label, field.note))
        self.table.setItem(row, 0, label)

        # The sub-line goes under the VALUE, not under the label -- "from
        # ModifiedTime (visit written)" sits beneath the time it explains.
        # Put in the 250px label column it wrapped to three lines and
        # ResizeToContents clipped the last mid-word ("...user visits)"),
        # in a dialog whose own count line promises nothing is truncated.
        # The value column is four times wider and stretches, so the same
        # sentence does not wrap at all.
        shown = field.display_value
        if field.note:
            shown = "%s\n%s" % (field.display_value, field.note)
        value = QTableWidgetItem(shown)
        tip = field.display_value
        if field.absence:
            tip = "%s\n\n%s" % (field.display_value,
                                provenance.absence_reason(field.absence))
        if field.note:
            tip = "%s\n\n%s" % (tip, field.note)
        value.setToolTip(copyable.literal_tooltip(tip))
        # Link colour keyed on field.target, not field.kind, as the grid
        # (record_model.py) colours only cells that are clickable: a
        # kind="url" field (Clean URL, Raw URL, ...) opens nothing here,
        # while an aggregate member (kind="text", target set) opens its own
        # dialog.
        openable = field.target is not None
        if field.absence:
            value.setForeground(QBrush(foreground("muted")))
        elif openable:
            value.setForeground(QBrush(foreground("url")))
        elif field.kind == "time":
            value.setForeground(QBrush(foreground("primary")))
        else:
            value.setForeground(QBrush(foreground("text")))
        if self.is_carved:
            # As in the grid: normal text on the carved tint, beside the
            # amber left edge of the fields frame (CARVED_BORDER_PX) and the
            # CARVED RECORD chip.
            tint = QBrush(foreground("carved_row"))
            label.setBackground(tint)
            value.setBackground(tint)
        self.table.setItem(row, 1, value)

        short, tooltip = detail_fields.basis_badge(
            field.field, carved=self.is_carved,
            record=self.row.get("_record") or self.row)
        badge = QTableWidgetItem(short or "")
        badge.setToolTip(tooltip)
        if short:
            badge.setForeground(QBrush(_badge_colour(short)))
        if self.is_carved:
            badge.setBackground(QBrush(foreground("carved_row")))
        self.table.setItem(row, 2, badge)
        self._rows.append(field)

    def _refresh_count(self, needle):
        total, absent = detail_fields.counts(self._all_groups)
        shown = len([f for f in self._rows if f is not None])
        if self.hide_empty_box.isChecked() and not needle:
            self.count_label.setText(
                "Showing %s of %s fields — %d empty %s hidden." % (
                    "{:,}".format(shown), "{:,}".format(total), absent,
                    "field" if absent == 1 else "fields"))
            self.count_label.setStyleSheet(
                "color: %s;" % theme.color("warn").name())
            return
        if needle:
            hidden = total - shown
            self.count_label.setText(
                "Showing %s of %s fields — filtered. %s %s hidden by this "
                "filter." % ("{:,}".format(shown), "{:,}".format(total),
                             "{:,}".format(hidden),
                             "field is" if hidden == 1 else "fields are"))
            # A filter may hide fields, but always says how many.
            self.count_label.setStyleSheet(
                "color: %s;" % theme.color("warn").name())
            return
        self.count_label.setText(
            "%s fields — every value this record carries, nothing "
            "truncated. %d of them state why they have no value."
            % ("{:,}".format(total), absent))
        self.count_label.setStyleSheet(
            "color: %s;" % theme.color("muted2").name())

    # --- lookups ---------------------------------------------------------

    def is_heading_row(self, table_row):
        return (0 <= table_row < len(self._rows)
                and self._rows[table_row] is None)

    def field_at(self, table_row):
        if 0 <= table_row < len(self._rows):
            return self._rows[table_row]
        return None

    def _field_index(self, table_row):
        """The index into detail_fields.flatten(self.groups) for a table
        row, or -1 for a heading."""
        field = self.field_at(table_row)
        if field is None:
            return -1
        fields = detail_fields.flatten(self.groups)
        for index, candidate in enumerate(fields):
            if candidate is field:
                return index
        return -1

    def _current_index(self):
        return self._field_index(self.table.currentRow())

    def _field(self, index):
        fields = detail_fields.flatten(self.groups)
        if 0 <= index < len(fields):
            return fields[index]
        return None

    # --- filtering -------------------------------------------------------

    def apply_filter(self, text):
        self._populate((text or "").strip().lower())

    # --- activation ------------------------------------------------------

    def show_all_members(self):
        """List every member record of this aggregate, in place of the
        first ones and the "Show all" row."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.groups = detail_fields.fields_for(self.row, all_members=True)
            self._populate(self.filter_box.text().strip().lower()
                           if hasattr(self, "filter_box") else "")
        finally:
            QApplication.restoreOverrideCursor()

    def activate_field(self, index):
        """Enter, or a double-click, on a field row."""
        field = self._field(index)
        if field is None:
            return
        if field.key == "aggregate:member_overflow":
            self.show_all_members()
            return
        if field.target is not None:
            self.recordRequested.emit(field.target)
            return
        if field.blob_key:
            # A Binary row's value is a summary line THIS TOOL composed
            # ("202 bytes · Binary · SHA-256 …"). Copying it would put an
            # annotation on the clipboard dressed as a stored value, and
            # the useful thing to do with a blob is look at it.
            index = self.blob_pane_for(field.blob_key)
            if index >= 0:
                # Unfold first, so the tab switched to is visible and the
                # status line's "in the tab below" is true.
                self.show_blob_region()
                self.blob_area.setCurrentIndex(index)
                self.blob_area.currentWidget().setFocus()
                self.status_label.setText(
                    "Showing %s in the tab below." % field.label)
                self.status_label.setStyleSheet(
                    "color: %s;" % theme.color("muted").name())
                return
        self.copy_field(index)

    def explain_field(self, index):
        field = self._field(index)
        if field is None:
            return
        described = ""
        if field.field:
            _short, tooltip = detail_fields.basis_badge(
                field.field, carved=self.is_carved,
                record=self.row.get("_record") or self.row)
            described = tooltip
        parts = ["Field: %s" % field.label,
                 "Value: %s" % field.display_value]
        if field.note:
            parts.append(field.note)
        if described:
            parts.append(described)
        if field.absence:
            parts.append(provenance.absence_reason(field.absence))
        parts.append(provenance.describe_origin(self.row))
        self.explainRequested.emit("\n\n".join(p for p in parts if p))

    def _explain_record(self):
        self.explainRequested.emit(
            "%s\n\n%s"
            % (detail_fields.identity_of(self.row),
               provenance.describe_origin(self.row)))

    # --- copy ------------------------------------------------------------

    def _set_clipboard(self, text):
        """True when the text reached the clipboard.

        QGuiApplication.clipboard().setText can fail while another
        application holds the Windows clipboard; that is reported rather
        than claimed as success.
        """
        try:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(text)
            return clipboard.text() == text
        except Exception:
            return False

    def _report(self, ok, message):
        self.status_label.setText(message if ok else CLIPBOARD_BUSY)
        self.status_label.setStyleSheet(
            "color: %s;" % theme.color("muted" if ok else "warn").name())
        return ok

    def copy_field(self, index):
        """Byte-exact and undecorated, as RecordsTable._copy_cell. A carved
        value is flagged in the menu label, not in the copied text.

        An absence copies nothing, so this tool's "(empty)" never appears in
        a report as if it were a stored value.
        """
        field = self._field(index)
        if field is None:
            return False
        if field.absence:
            self.status_label.setText(
                "Nothing to copy — that field has no value (%s)."
                % field.display_value)
            self.status_label.setStyleSheet(
                "color: %s;" % theme.color("warn").name())
            return False
        if field.value is None:
            # A binary row's value is None; its display_value is a summary
            # this tool composed ("152 bytes ... SHA-256 ..."), not stored
            # data, so Copy value and Ctrl+C refuse it, as activate_field
            # does (which opens the blob's tab instead).
            self.status_label.setText(
                "Nothing to copy — %s has no plain-text value; open its "
                "tab below to see the bytes." % field.label)
            self.status_label.setStyleSheet(
                "color: %s;" % theme.color("warn").name())
            return False
        return self._report(self._set_clipboard(str(field.value)),
                            "Copied %s." % field.label)

    def copy_field_with_name(self, index):
        field = self._field(index)
        if field is None:
            return False
        return self._report(
            self._set_clipboard("%s: %s" % (field.label, field.display_value)),
            "Copied %s with its name." % field.label)

    def copy_field_raw(self, index):
        field = self._field(index)
        if field is None or field.raw_value is None:
            return False
        return self._report(self._set_clipboard(str(field.raw_value)),
                            "Copied the raw FILETIME for %s." % field.label)

    def _copy_selection(self):
        """Ctrl+C. One row copies the value alone, matching "Copy
        value\tCtrl+C" in the field menu (copy_field()). Several rows keep
        their labels, so a pasted column of values names each value.
        """
        rows = {ix.row() for ix in self.table.selectedIndexes()}
        if not rows:
            rows = {self.table.currentRow()}
        fields = [self.field_at(r) for r in sorted(rows)]
        fields = [f for f in fields if f is not None]
        if not fields:
            return False
        if len(fields) == 1:
            # Through copy_field, not a second byte-exact path of its
            # own: that is where an absence refuses rather than copying
            # the word "(empty)", and where a Binary row refuses rather
            # than copying a summary this tool composed. A parallel
            # implementation here would be one that forgets both.
            only = [r for r in sorted(rows) if self.field_at(r) is not None][0]
            return self.copy_field(self._field_index(only))
        text = "\n".join("%s: %s" % (f.label, f.display_value) for f in fields)
        return self._report(self._set_clipboard(text),
                            "Copied %d field(s)." % len(fields))

    def copy_all_text(self):
        lines = []
        if self.is_carved:
            lines.append(CARVED_COPY_PREAMBLE)
            lines.append(provenance.describe_origin(self.row))
            lines.append("")
        for group in self.groups:
            lines.append("— %s —" % group.name)
            for field in group.fields:
                # The DISPLAYED value, so an absence copies as its
                # sentence rather than as Python's "None".
                lines.append("%s: %s" % (field.label, field.display_value))
            lines.append("")
        return "\n".join(lines).rstrip("\n")

    def copy_tsv_text(self):
        lines = ["Field\tValue\tBasis"]
        for field in detail_fields.flatten(self.groups):
            short, _tip = detail_fields.basis_badge(
                field.field, carved=self.is_carved,
                record=self.row.get("_record") or self.row)
            lines.append("%s\t%s\t%s" % (_tsv_safe(field.label),
                                         _tsv_safe(field.display_value),
                                         short or ""))
        return "\n".join(lines)

    def copy_all(self):
        return self._report(self._set_clipboard(self.copy_all_text()),
                            "Copied every field.")

    def copy_tsv(self):
        return self._report(self._set_clipboard(self.copy_tsv_text()),
                            "Copied every field as TSV.")

    # --- the field context menu ------------------------------------------

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        index = self._field_index(row)
        if index < 0:
            return
        self.build_field_menu(index).exec(
            self.table.viewport().mapToGlobal(pos))

    def build_field_menu(self, index):
        """Split from _context_menu so a test can trigger an action
        without popping a real menu (QMenu.exec blocks for input) -- the
        same reason RecordsTable._build_context_menu is separate."""
        field = self._field(index)
        menu = QMenu(self)
        if field is None:
            return menu
        # Copy, never Open. Nothing here launches a path.
        label = "Copy value (carved record)" if self.is_carved else "Copy value"
        menu.addAction("%s\tCtrl+C" % label, lambda: self.copy_field(index))
        menu.addAction("Copy field name and value",
                       lambda: self.copy_field_with_name(index))
        if field.raw_value is not None:
            menu.addAction("Copy this field's raw FILETIME",
                           lambda: self.copy_field_raw(index))
        if field.target is not None:
            menu.addAction("Open this record",
                           lambda: self.recordRequested.emit(field.target))
        menu.addSeparator()
        menu.addAction("Explain this field\tF1",
                       lambda: self.explain_field(index))
        return menu

    # --- lifecycle -------------------------------------------------------

    def closeEvent(self, event):
        """Drop the record references.

        Every field holds a value from the parser that produced it, so a
        still-referenced dialog would keep the whole exhibit alive; the
        BlobSource objects are dropped for the same reason.
        """
        for window in list(self._bytes_windows):
            try:
                window.close()
            except RuntimeError:
                pass
        self._bytes_windows = []
        self.row = None
        self.groups = []
        self._all_groups = []
        self._rows = []
        # A FileWindowBlob holds bytes read from the exhibit and a
        # MemoryBlob a reference into the parser, so references are dropped
        # on close and do not keep the exhibit in memory.
        self.blobs = []
        super().closeEvent(event)


class BlobViewerDialog(QDialog):
    """One blob on its own, with no record around it.

    The same surface as the detail dialog's bottom pane (the same
    BlobPane, copy conventions and modeless stacking), opened from the
    Table Browser, where a cell is a raw ESE value. blobs_for_cells turns
    any bytes cell of any table into a viewable blob, including columns no
    decoder reads.
    """

    def __init__(self, source, parent=None, context="", db_path="",
                evidence_set=None):
        super().__init__(parent)
        self.source = source
        # As in RecordDetailDialog: the pane needs to know where the
        # exhibit lives so its export refuses to write beside it, and a
        # Table Browser cell has no evidence context of its own, so the
        # opener supplies it.
        evidence_files, evidence_dirs = export_target.evidence_paths(
            evidence_set, types.SimpleNamespace(db_path=db_path or ""))
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("Bytes — %s" % source.label)
        # This dialog is ALL viewer, so it always takes the taller floor.
        if parent is not None:
            self.resize(
                max(MIN_WIDTH, parent.width() - PARENT_MARGIN_W),
                max(MIN_HEIGHT_WITH_VIEWER,
                    parent.height() - PARENT_MARGIN_H_WITH_VIEWER))
        else:
            self.resize(MIN_WIDTH, MIN_HEIGHT_WITH_VIEWER)

        root = QVBoxLayout(self)
        title = copyable.selectable(QLabel(source.label))
        font = QFont(title.font())
        font.setBold(True)
        title.setFont(font)
        root.addWidget(title)

        # Where the bytes came from, stated rather than implied. A hex
        # dump with no provenance line is a picture of some bytes.
        self.context_label = QLabel(
            ("%s  ·  %s" % (context, source.origin_note)) if context
            else source.origin_note)
        self.context_label.setWordWrap(True)
        copyable.selectable(self.context_label)
        self.context_label.setStyleSheet(
            "color: %s;" % theme.color("muted2").name())
        root.addWidget(self.context_label)

        self.pane = BlobPane(source, evidence_files=evidence_files,
                             evidence_dirs=evidence_dirs)
        root.addWidget(self.pane, 1)

        buttons = QDialogButtonBox()
        close = buttons.addButton("Close", QDialogButtonBox.AcceptRole)
        close.setDefault(False)
        close.setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def keyPressEvent(self, event):
        ctrl = bool(event.modifiers() & Qt.ControlModifier)
        if ctrl and event.key() in (Qt.Key_W,):
            self.close()
            return
        if ctrl and event.key() == Qt.Key_E:
            self.pane.export_blob()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.source = None
        super().closeEvent(event)


def _matches(field, needle):
    if not needle:
        return True
    return (needle in field.label.lower()
            or needle in field.display_value.lower()
            or needle in str(field.key).lower())


def _badge_colour(short):
    """The chip's colour for one basis, read at call time so a theme
    switch applies (see record_model.foreground()).
    """
    return {"OBS": theme.color("primary_text"), "DER": theme.color("url"),
            "INF": theme.color("carved"), "CARV": theme.color("warn")}.get(
                short, theme.color("primary_text"))
