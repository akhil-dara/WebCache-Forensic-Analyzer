"""The table every record-set view uses.

Qt gives a lot free: resize and reorder by dragging, header-click sort,
arrow/PgUp/PgDn/Home/End navigation, rubber-band selection, a native
scrollbar, and header state that serialises for free.

It does NOT give these, and each is real work rather than a line of setup:
Ctrl-click multi-sort (Qt sorts by one column), Ctrl+C as TSV with headers
so it pastes into Excel intact, a context menu, Enter to open a record, link
columns, and F1-to-explain. Calling them "native behaviour" in a design
document would have hidden the work.

The vertical header carries the origin label ("Live"/"Carved", see
ORIGIN_LABEL_* in record_model.py), not anything in this file -- a
column-level trick (a delegate on column 0, say) would be reachable by a
future "hide this column", and this table's whole point is that the marker
cannot be removed that way.
"""
import math
import re

from PySide6.QtCore import (QEvent, QPoint, QPointF, QRect, QRectF, QSize,
                            Qt, QTimer, Signal)
from PySide6.QtGui import (QBrush, QFont, QFontMetrics, QFontMetricsF,
                           QGuiApplication, QKeySequence, QPainter, QPalette,
                           QPolygonF, QShortcut, QTextLayout, QTextOption)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication,
                               QHeaderView, QMenu, QPushButton, QStyle,
                               QStyledItemDelegate, QStyleOptionHeader,
                               QStyleOptionViewItem, QTableView, QToolTip)

from ..provenance import aggregate_members
from ..shell import glyphs, row_locator, theme
from . import basis_badge
from .break_points import (HARD_BREAK_RUN, LONG_RUN, SOFT_BREAK_AFTER, ZWSP,
                           breakable)
from .content_header import blank_columns, constant_columns
from .filter_popup import FilterPopup
from .whole_value import WholeValueWindow
from .bar_delegate import ShareBarDelegate
from .record_model import (CARVED_ROW_TOOLTIP, LIVE_ROW_TOOLTIP,
                           ORIGIN_HEADING, ORIGIN_LABEL_CARVED,
                           ORIGIN_LABELS_AGGREGATE, ORIGIN_LABELS_RECORD,
                           ORIGIN_LABEL_MIXED, ORIGIN_LABEL_NONE,
                           ORIGIN_LABEL_RECOVERED, MIXED_ROW_TOOLTIP,
                           NOT_A_RECORD_TOOLTIP, RECOVERED_ONLY_TOOLTIP,
                           ORIGIN_LABEL_LIVE, ROLE_IS_CARVED, ROLE_RAW,
                           BackgroundRoleDelegate, RecordTableModel, foreground,
                           paint_selection_bar)

#: Padding around a header label. A column squeezed under its own heading is
#: what made six views' filters look dead once already.
_HEADER_PAD_PX = 8

#: QFontMetrics.horizontalAdvance() measures the label glyphs only, not
#: the space theme.py's QHeaderView::section rule reserves around them
#: ("padding: 4px 9px", 9px on each side, plus "border-right: 1px"), nor
#: the hinting and rounding a real font adds. The QSS padding is counted
#: by name rather than as a small constant. (Offscreen tests apply no
#: theme, so the gap does not appear there.) A badge-bearing column's
#: 2*reserve term already exceeds it.
_LABEL_ESTIMATE_SLACK_PX = 16

#: theme.py's QHeaderView::section rule: "padding: 4px 9px" plus a 1px
#: right border.
SECTION_QSS_PAD_X = 9

#: the filtered-empty sentence. %s is RecordFilter.chip_text() --
#: every filter in force, in column labels and the grid's own words.
FILTERED_EMPTY_TEXT = ("No records match the filters in force: %s. "
                       "Clear filters to show every record.")
_SECTION_QSS_BORDER_PX = 1
#: The amber edge a carved row's origin cell carries.
CARVED_EDGE_PX = 3

#: Wait this long after the last trigger before re-measuring the visible
#: rows. One pass per burst of scroll/resize events, not one per event.
_ROW_FIT_DEBOUNCE_MS = 30
#: A grown row can push later rows out of view (and pull none in); the
#: visible set settles within two passes on any real grid.
_ROW_FIT_MAX_PASSES = 3
#: What a cell takes from its column width before its text: theme.py's
#: QTableView::item "padding: 0px 9px" (18) plus the style's text margin
#: on each side (PM_FocusFrameHMargin + 1 = 3, twice), plus 4 to spare.
#: Too large only sends a value to the full measure; too small would
#: skip one that wraps -- so this errs large.
_CELL_TEXT_SLACK_PX = 28

#: The break rules live in break_points.py, shared with WrappingText.
_ZWSP = ZWSP
_SOFT_BREAK_AFTER = SOFT_BREAK_AFTER
_HARD_BREAK_RUN = HARD_BREAK_RUN
_LONG_RUN = LONG_RUN

#: The most lines a wrapped row shows: five of text and, in a cell holding
#: more, a sixth for the "+N more lines" marker, so one long value cannot
#: make a row taller than the viewport. Only the painted cell is capped:
#: copy, tooltip, filter, the record dialog and every export read the
#: whole value from the model.
ROW_LINE_CAP = 6
#: The marker's words. N is the number of wrapped lines NOT painted.
MORE_MARKER = "\u25be +%s more lines"
#: A column that declares no width (Cookies' Value) is auto-sized at most
#: to this -- the widest declared text column -- and wraps from there,
#: rather than growing to a multi-thousand-pixel single line.
MAX_AUTO_COLUMN_PX = 420


def _breakable(text):
    """The display text with invisible break opportunities added.

    Qt's item views wrap with QTextOption::WordWrap, not
    WrapAtWordBoundaryOrAnywhere, so a run with no break opportunity is
    laid out as one long line and clipped at the cell edge without an
    ellipsis. Only what is painted (and measured, so the row grows to
    match) changes; copy, tooltip, filter and export read the model. The
    rules are break_points.breakable's."""
    return breakable(text)


class WrappingDelegate(BackgroundRoleDelegate):
    """BackgroundRoleDelegate (the carved tint -- see its docstring) that,
    while the view wraps, hands the style a value it CAN wrap: see
    _breakable. initStyleOption is the one hook both paint and Qt's own
    sizeHint go through, so the height a row is given and the lines it
    paints are computed from the same text.

    PUBLIC: the ONE delegate for evidence values, on
    every grid and on both whole-value surfaces -- the record dialog's
    field table and the Table Browser's whole-row view -- which with a
    plain delegate cut a 200-character token after two lines."""

    def __init__(self, parent=None, line_cap=None):
        super().__init__(parent)
        #: None: rows grow to their whole content (the record dialog and
        #: the whole-row view, which exist to show all of it). An int:
        #: the grid's cap, ROW_LINE_CAP -- see there.
        self.line_cap = line_cap
        #: (hash, length, text width, font) -> (total lines, the breakable
        #: text of the lines painted). A capped cell's full line count is
        #: laid out once per width, never on every repaint.
        self._layouts = {}
        #: (hash, length, font) -> one-line advance, for long values only:
        #: the row fit, the cap's pre-bound and paint all ask it.
        self._advances = {}
        self._one_line = {}

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if option.features & QStyleOptionViewItem.WrapText and option.text:
            option.text = _breakable(option.text)

    # --- the cap -----------------------------------

    def _caps(self, option):
        return bool(self.line_cap) and bool(
            option.features & QStyleOptionViewItem.WrapText)

    def text_advance(self, text, font):
        """QFontMetrics.horizontalAdvance, remembered for a long value --
        shaping a 300k-character value is ~40 ms, and the fit, the cap's
        pre-bound and paint would each pay it again."""
        if len(text) < 256:
            return QFontMetrics(font).horizontalAdvance(text)
        key = (hash(text), len(text), font.key())
        advance = self._advances.get(key)
        if advance is None:
            if len(self._advances) > 8192:
                self._advances.clear()
            advance = QFontMetrics(font).horizontalAdvance(text)
            self._advances[key] = advance
        return advance

    def line_height(self, font):
        """One wrapped line's height, from the same QTextLayout lines the
        style lays a wrapped cell out with."""
        key = ("line", font.key())
        cached = self._one_line.get(key)
        if cached is None:
            layout = QTextLayout("Xg", font)
            layout.beginLayout()
            line = layout.createLine()
            line.setLineWidth(1000)
            layout.endLayout()
            cached = line.height()
            self._one_line[key] = cached
        return cached

    def cap_height(self, option):
        """The height of a capped row: the style's own one-line cell plus
        (cap - 1) further lines."""
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        key = (option.font.key(), id(style))
        one = self._one_line.get(key)
        if one is None:
            probe = QStyleOptionViewItem(option)
            probe.text = "Xg"
            probe.features |= QStyleOptionViewItem.HasDisplay
            probe.rect = QRect(0, 0, 1000, 20)
            one = style.sizeFromContents(QStyle.CT_ItemViewItem, probe,
                                         QSize(), widget).height()
            self._one_line[key] = one
        return int(math.ceil(one + (self.line_cap - 1)
                             * self.line_height(option.font)))

    def _measured(self, option, index):
        """The style's size for a wrapped cell, asked at the width its text
        is painted in. The style measures at the cell's whole width, but the
        QSS item padding ("padding: 0px 9px") is removed before the text is
        drawn, so the rect handed to the style is narrowed by the same
        amount; otherwise a value near a wrap boundary would get one line
        too few."""
        rect = option.rect
        if (option.features & QStyleOptionViewItem.WrapText
                and rect.width() > 0):
            widget = option.widget
            style = widget.style() if widget is not None else QApplication.style()
            # Asked once per column width: the style sheet's rule lookup
            # is most of the cost, and the padding does not vary by cell.
            key = ("shrink", id(style), rect.width(), option.font.key())
            shrink = self._one_line.get(key)
            if shrink is None:
                probe = QStyleOptionViewItem(option)
                probe.text = "Xg"
                probe.features |= QStyleOptionViewItem.HasDisplay
                shrink = rect.width() - style.subElementRect(
                    QStyle.SE_ItemViewItemText, probe, widget).width()
                if len(self._one_line) > 4096:
                    self._one_line.clear()
                self._one_line[key] = shrink
            if shrink > 0:
                option = QStyleOptionViewItem(option)
                option.rect = QRect(rect.x(), rect.y(),
                                    rect.width() - shrink, rect.height())
        return super().sizeHint(option, index)

    def sizeHint(self, option, index):
        if not self._caps(option):
            return self._measured(option, index)
        cap = self.cap_height(option)
        width = option.rect.width()
        if width > _CELL_TEXT_SLACK_PX:
            # A cheap pre-bound: a value whose one-line width alone is
            # twice the cap's worth of lines is capped without laying it
            # out.
            text = index.data(Qt.DisplayRole)
            if text is not None:
                advance = self.text_advance(str(text), option.font)
                if advance > 2 * self.line_cap * (width - _CELL_TEXT_SLACK_PX):
                    return QSize(width, cap)
        size = self._measured(option, index)
        if size.height() > cap:
            size.setHeight(cap)
        return size

    def _plain_option(self, option, index):
        """The styled option WITHOUT the break points: the capped path
        never hands the style the whole text, so it never pays for making
        all of it breakable."""
        opt = QStyleOptionViewItem(option)
        QStyledItemDelegate.initStyleOption(self, opt, index)
        return opt

    def _text_rect(self, opt):
        """The rect the style lays a cell's text out in: its QSS item
        padding, then its text margin on each side. Asked with a stand-in
        text -- the style would otherwise lay out the whole value just to
        place it."""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        probe = QStyleOptionViewItem(opt)
        probe.text = "Xg"
        rect = style.subElementRect(QStyle.SE_ItemViewItemText, probe, widget)
        margin = style.pixelMetric(QStyle.PM_FocusFrameHMargin, None, widget) + 1
        return rect.adjusted(margin, 0, -margin, 0)

    def _layout_info(self, text, font, width):
        """(total wrapped lines, the breakable text of the first cap - 1
        lines) for `text` at `width` -- or (1, "") for a one-line value."""
        key = (hash(text), len(text), width, font.key())
        info = self._layouts.get(key)
        if info is not None:
            return info
        if len(self._layouts) > 4096:
            self._layouts.clear()
        if "\n" not in text and self.text_advance(text, font) <= width:
            info = (1, "")
        else:
            broken = _breakable(text)
            layout = QTextLayout(broken.replace("\n", "\u2028"), font)
            wrap = QTextOption()
            wrap.setWrapMode(QTextOption.WordWrap)
            layout.setTextOption(wrap)
            layout.beginLayout()
            lines, prefix_end = 0, 0
            shown = max(1, self.line_cap - 1)
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(max(1, width))
                lines += 1
                if lines == shown:
                    prefix_end = line.textStart() + line.textLength()
            layout.endLayout()
            info = (lines, broken[:prefix_end])
        self._layouts[key] = info
        return info

    def capped(self, option, index):
        """None for a cell that shows its whole value; otherwise a dict of
        what paint and the marker's hit test both need. `option.rect` is
        the cell's rect."""
        if not self._caps(option) or option.rect.width() <= 0:
            return None
        opt = self._plain_option(option, index)
        if not opt.text:
            return None
        rect = self._text_rect(opt)
        lines, prefix = self._layout_info(opt.text, opt.font, rect.width())
        if lines <= self.line_cap:
            return None
        height = self.line_height(opt.font)
        shown = max(1, min(self.line_cap - 1,
                           int(rect.height() // max(1.0, height)) - 1))
        block = (shown + 1) * height
        top = rect.top() + max(0.0, (rect.height() - block) / 2.0)
        return {"opt": opt, "rect": rect, "lines": lines, "shown": shown,
                "prefix": prefix, "height": height, "top": top,
                "hidden": lines - shown}

    def marker_rect(self, option, index, info=None):
        """Where the "+N more lines" marker is painted, in the view's
        coordinates, or None for a cell that is not capped."""
        info = info if info is not None else self.capped(option, index)
        if info is None:
            return None
        font = QFont(info["opt"].font)
        font.setWeight(QFont.DemiBold)
        text = MORE_MARKER % format(info["hidden"], ",")
        width = math.ceil(QFontMetricsF(font).horizontalAdvance(text)) + 4
        rect = info["rect"]
        y = info["top"] + info["shown"] * info["height"]
        return QRect(max(rect.left(), rect.right() - width), int(y),
                     min(width, rect.width()), int(math.ceil(info["height"])))

    def paint(self, painter, option, index):
        # Only a row grown to the cap can hold a capped cell: every other
        # cell is painted without a second look at its text.
        if (not self._caps(option)
                or option.rect.height() < self.cap_height(option) - 1):
            return super().paint(painter, option, index)
        info = self.capped(option, index)
        if info is None:
            return super().paint(painter, option, index)
        opt = info["opt"]
        # The cell itself -- tint, selection, border -- with no text: the
        # style would lay all of it out and clip it at the cell's edge.
        bg = index.data(Qt.BackgroundRole)
        if bg is not None:
            painter.save()
            painter.fillRect(option.rect, bg)
            painter.restore()
        opt.text = ""
        opt.backgroundBrush = QBrush(Qt.NoBrush)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        paint_selection_bar(painter, option, index)
        # Only the lines that fit: the prefix, never the whole value.
        fg = index.data(Qt.ForegroundRole)
        if fg is None:
            color = opt.palette.color(QPalette.Text)
        else:
            color = fg.color() if isinstance(fg, QBrush) else fg
        rect = info["rect"]
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(color)
        layout = QTextLayout(info["prefix"].replace("\n", "\u2028"), opt.font)
        wrap = QTextOption()
        wrap.setWrapMode(QTextOption.WordWrap)
        wrap.setAlignment(opt.displayAlignment & Qt.AlignHorizontal_Mask)
        layout.setTextOption(wrap)
        layout.beginLayout()
        y = 0.0
        for _n in range(info["shown"]):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(rect.width())
            line.setPosition(QPointF(0, y))
            y += line.height()
        layout.endLayout()
        layout.draw(painter, QPointF(rect.left(), info["top"]))
        # The marker: its own line, in the accent colour, bottom right.
        marker = self.marker_rect(option, index, info)
        font = QFont(opt.font)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(theme.color("primary"))
        painter.drawText(marker, Qt.AlignRight | Qt.AlignVCenter,
                         MORE_MARKER % format(info["hidden"], ","))
        painter.restore()


#: Qt's QWIDGETSIZE_MAX: a widget's maximum width when none is set.
_QWIDGETSIZE_MAX = 16777215


class _OriginHeaderView(QHeaderView):
    """The vertical header as the origin column: "Live" or "Carved" on
    every row, and a CARVED_EDGE_PX amber edge on a carved one.

    Its width is fixed at floor_width(), computed once; an auto-width
    vertical header recomputes lazily and can shift the horizontal header
    sideways."""

    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self._aggregate = False
        self.setDefaultAlignment(Qt.AlignCenter)

    def set_aggregate(self, on):
        """A table of aggregates can show "Recovered only", which is
        wider than either record label; a record table keeps its width."""
        self._aggregate = bool(on)
        self.setFixedWidth(self.floor_width())

    def painted_font(self):
        """The Live/Carved row labels: this header's font at the QSS
        weight (font-weight: 600). theme.py's size-bearing heading rule is
        horizontal-only, so these keep the widget's size
        (tests/_heading_fit_probe.py)."""
        font = QFont(self.font())
        font.setWeight(QFont.DemiBold)
        return font

    def floor_width(self):
        """Wide enough for both row labels and for ORIGIN_HEADING, which
        the corner button paints as a column heading, measured in
        theme.heading_font()."""
        rows = QFontMetricsF(self.painted_font())
        heading = QFontMetricsF(theme.heading_font())
        widest = max([rows.horizontalAdvance(text) for text in
                      (ORIGIN_LABELS_AGGREGATE if self._aggregate
                       else ORIGIN_LABELS_RECORD)]
                     + [heading.horizontalAdvance(ORIGIN_HEADING)])
        return math.ceil(widest + 2 * SECTION_QSS_PAD_X
                         + _SECTION_QSS_BORDER_PX + CARVED_EDGE_PX
                         + _HEADER_PAD_PX)

    def sizeHint(self):
        """The fixed width and the sections' total length. QHeaderView's
        own hint asks the model for every row's label to find the widest,
        which on a large grid made each restyle (a theme switch) query
        tens of thousands of rows; the width is fixed, so it is not
        measured again."""
        width = self.maximumWidth()
        if width >= _QWIDGETSIZE_MAX:
            width = self.floor_width()
        return QSize(width, self.length())

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        painter.restore()
        model = self.model()
        if model is not None and model.headerData(
                logicalIndex, Qt.Vertical, ROLE_IS_CARVED):
            painter.save()
            painter.fillRect(QRect(rect.left(), rect.top(), CARVED_EDGE_PX,
                                   rect.height()), foreground("carved"))
            painter.restore()


#: The guaranteed provenance column appended to a bulk copy that touches a
#: carved row (see Finding 5 in the copy helpers below). Named distinctly
#: from any view's own "Origin" column so the two can never collide or look
#: like an accidental duplicate -- this one is always present because the
#: copy path put it there, not because the examiner selected it.
_ORIGIN_GUARANTEE_LABEL = "Origin (carved)"


class _ProvenanceHeaderView(QHeaderView):
    """Paints the OBS/DER/INF/CARV basis badge on column headings that
    have one (Origin's is whatever evidence_model.basis_of("Origin")
    returns: CARV).

    Driven by Column.show_badge / Column.badge / Column.badge_tooltip
    (column_spec.py): this class never computes a basis and never imports
    the engine (test_structure.py). The owning view annotates those
    attributes from evidence_model.basis_of() after building its COLUMNS.
    A column with no badge gets none, so a plain fixture Column works too.

    super().paintSection() runs first, so the background, the label and
    any sort indicator are painted by the style and QSS; the badge is
    drawn on top, in a reserved slot at the right of the section, clear of
    the label and of the section's right edge (RESERVED_RIGHT_PX).
    """

    #: Kept clear of the badge on every section: the section's QSS right
    #: padding plus its border (SECTION_QSS_PAD_X + _SECTION_QSS_BORDER_PX),
    #: so the chip sits inside the padding box and never touches the
    #: divider. The label is centred, so the heading floor mirrors this on
    #: the left; it is kept to the minimum so badge columns stay narrow.
    RESERVED_RIGHT_PX = 10
    #: The chip's geometry, read from basis_badge, which the record detail
    #: dialog also uses for its field rows, so both surfaces paint the same
    #: chip. Bound as class attributes for existing readers
    #: (self.BADGE_GAP_PX in _enforce_heading_floor, and the tests).
    BADGE_GAP_PX = basis_badge.BADGE_GAP_PX
    BADGE_PAD_PX = basis_badge.BADGE_PAD_PX
    BADGE_HEIGHT_PX = basis_badge.BADGE_HEIGHT_PX

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        # The chip keeps the font it has always been drawn from (the
        # widget's own, before the heading font below replaces it).
        self._badge_font = basis_badge.badge_font(self.font())
        # The one heading font -- see theme.heading_font.
        self.setFont(theme.heading_font())

    # --- geometry, shared between painting and hit-testing ----------------

    def badge_font_object(self):
        """The font this header paints its chip with, so another surface
        can measure against the same font."""
        return self._badge_font

    def badge_width(self, text):
        return basis_badge.badge_width(self._badge_font, text)

    def painted_font(self):
        """The font a heading is drawn with: theme.heading_font(), set on
        this header in __init__ and written into the QHeaderView::section
        QSS rule from the same definition, so the floor is measured in the
        painted font (tests/_heading_fit_probe.py).
        """
        return QFont(self.font())

    def _chip_rect(self, section_rect, badge_text, visible_right=None,
                   label=""):
        """The badge chip's rect within `section_rect`, or None when there
        is not room for it WHOLE. `visible_right` is the viewport's right
        edge: a section running past it anchors its chip there instead of
        at its own (off-screen) right edge -- a badge is drawn whole
        where it can be seen, or not at all, never as a fragment."""
        right = section_rect.right()
        if visible_right is not None and visible_right < right:
            right = visible_right
        chip_w = self.badge_width(badge_text)
        left_limit = section_rect.left()
        available = right - left_limit - self.RESERVED_RIGHT_PX - self.BADGE_GAP_PX
        if available <= 0 or chip_w > available:
            return None
        chip_h = min(self.BADGE_HEIGHT_PX, section_rect.height() - 4)
        if chip_h < 10:
            return None
        x = right - self.RESERVED_RIGHT_PX - chip_w
        if visible_right is not None and x < 0:
            # Viewport coordinates start at 0: a section scrolled mostly
            # off the LEFT edge would show a chip cut there.
            return None
        if (label and visible_right is not None
                and right < section_rect.right()):
            # Anchored inside: it must still clear the centred label.
            label_right = section_rect.center().x() + QFontMetricsF(
                self.painted_font()).horizontalAdvance(label) / 2.0
            if x - self.BADGE_GAP_PX < label_right:
                return None
        y = section_rect.top() + (section_rect.height() - chip_h) / 2.0
        return QRectF(x, y, chip_w, chip_h)

    def _column_at(self, section):
        model = self.model()
        if model is None or section < 0 or not hasattr(model, "column_at"):
            return None
        try:
            return model.column_at(section)
        except IndexError:
            return None

    # --- painting -----------------------------------------------------

    paint_sort_arrow = True

    #: The arrow's box, inside the section's 9 px left QSS padding.
    SORT_ARROW_W = 7.0
    SORT_ARROW_H = 5.0

    def sort_arrow_rect(self, section_rect):
        """Where the sort arrow is drawn: in the LEFT padding, which every
        heading floor already leaves empty (the label is centred), so no
        floor widens and nothing meets the right-hand basis badge."""
        rect = QRectF(section_rect)
        return QRectF(rect.left() + 1.0,
                      rect.center().y() - self.SORT_ARROW_H / 2.0,
                      self.SORT_ARROW_W, self.SORT_ARROW_H)

    def _paint_sort_arrow(self, painter, rect, logical_index):
        if (not self.paint_sort_arrow or not self.isSortIndicatorShown()
                or logical_index != self.sortIndicatorSection()):
            return
        box = self.sort_arrow_rect(rect)
        down = self.sortIndicatorOrder() == Qt.DescendingOrder
        top, bottom = box.top(), box.bottom()
        points = ([QPointF(box.left(), top), QPointF(box.right(), top),
                   QPointF(box.center().x(), bottom)] if down else
                  [QPointF(box.left(), bottom), QPointF(box.right(), bottom),
                   QPointF(box.center().x(), top)])
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("primary"))
        painter.drawPolygon(QPolygonF(points))
        painter.restore()

    #: A filtered column's heading carries an accent bar along its foot,
    #: as the offline report lights its funnel: what is in force is seen
    #: without opening anything. It takes no width, so no floor moves.
    FILTER_MARK_H = 3.0

    def is_filtered(self, logical_index):
        column = self._column_at(logical_index)
        model = self.model()
        return (column is not None and model is not None
                and hasattr(model, "column_filter_text")
                and model.column_filter_text(column.key) is not None)

    def filter_mark_rect(self, section_rect):
        rect = QRectF(section_rect)
        return QRectF(rect.left() + 1.0, rect.bottom() - self.FILTER_MARK_H,
                      max(0.0, rect.width() - 2.0), self.FILTER_MARK_H)

    def _paint_filter_mark(self, painter, rect, logical_index):
        if not self.is_filtered(logical_index):
            return
        painter.save()
        painter.fillRect(self.filter_mark_rect(rect), theme.color("primary"))
        painter.restore()

    def paintSection(self, painter, rect, logicalIndex):
        super().paintSection(painter, rect, logicalIndex)
        self._paint_sort_arrow(painter, rect, logicalIndex)
        self._paint_filter_mark(painter, rect, logicalIndex)
        column = self._column_at(logicalIndex)
        if column is None or not column.show_badge or not column.badge:
            return
        chip = self._chip_rect(rect, column.badge,
                               visible_right=self.viewport().rect().right(),
                               label=column.label)
        if chip is None:
            return
        painter.save()
        # super().paintSection() painted the label with the style's
        # alignment across the section's full width, centred by default
        # (QHeaderView.defaultAlignment() == AlignHCenter|AlignVCenter), so
        # a label can extend into the badge slot whatever the floor
        # estimate. The reserved zone is repainted in the section's
        # background first, which guarantees the badge never overlaps the
        # label. Inset by 1px on the right and bottom so the QSS section
        # border (theme.py) is not painted over.
        reserved_left = rect.right() - self.RESERVED_RIGHT_PX - chip.width() - self.BADGE_GAP_PX
        erase_rect = QRectF(reserved_left, rect.top(),
                            rect.right() - reserved_left - 1, rect.height() - 1)
        painter.fillRect(erase_rect, theme.color("alt_base"))
        # The chip itself: basis_badge.paint_badge, the SAME call the
        # record detail dialog makes for a field row's chip.
        basis_badge.paint_badge(painter, chip, column.badge, self._badge_font)
        painter.restore()

    # --- the badge's own tooltip ---------------------------------------

    def event(self, e):
        """QHeaderView already shows a per-SECTION tooltip from the model's
        Qt.ToolTipRole (RecordTableModel.headerData -- the field/key name).
        This intercepts only the small badge area within a section and
        shows the abbreviation's full meaning there instead, so an
        examiner meeting "DER" for the first time does not have to guess
        -- everywhere else in the same header cell keeps the existing
        tooltip untouched."""
        if e.type() == QEvent.ToolTip:
            section = self.logicalIndexAt(e.pos())
            column = self._column_at(section)
            if column is not None and column.show_badge and column.badge:
                section_rect = QRectF(
                    self.sectionViewportPosition(section), 0,
                    self.sectionSize(section), self.height())
                chip = self._chip_rect(
                    section_rect, column.badge,
                    visible_right=self.viewport().rect().right(),
                    label=column.label)
                if chip is not None and chip.contains(e.pos()):
                    QToolTip.showText(
                        e.globalPos(),
                        column.badge_tooltip or column.badge, self)
                    e.accept()
                    return True
        return super().event(e)


def _cell_text(model, index):
    """The raw value as a string; "" only for None.

    0, 0.0 and False are values, not missing data; `str(value or "")`
    would turn them into "". Every copy path uses this function.
    """
    value = model.data(index, ROLE_RAW)
    return "" if value is None else str(value)


def _tsv_safe(text):
    """Replace characters that are structural to a TSV consumer (a
    spreadsheet included) with a space.

    A literal tab reads as a column break and a newline (or bare CR) as a
    row break, so a Title or CleanUrl carrying either (plausible in a
    carved record) would shift every column after it or split the row.

    Not applied to a single Copy cell, which round-trips byte-exact (see
    _build_context_menu): one value alone has no column or row to
    misalign.
    """
    return (text.replace("\t", " ").replace("\r\n", " ")
                .replace("\n", " ").replace("\r", " "))


def _alive(widget):
    """False once Qt has deleted the C++ half (WA_DeleteOnClose)."""
    try:
        widget.isVisible()
        return True
    except RuntimeError:
        return False


def _row_is_carved(model, row):
    return bool(model.data(model.index(row, 0), ROLE_IS_CARVED))


def _declares_column(model, key):
    """True if the view's COLUMNS already has a column keyed `key`.

    Used by _copy_row and _copy_column so a view whose COLUMNS includes
    "Origin" (History does) does not get a carved row's Origin twice in a
    row or column copy. copy_selection_as_tsv does not use this: its
    appended column is labelled "Origin (carved)" (_ORIGIN_GUARANTEE_LABEL),
    distinct from "Origin"
    (test_ctrl_c_tsv_appends_origin_when_any_selected_row_is_carved).
    """
    return any(c.key == key for c in model.columns)


class RecordsTable(QTableView):
    #: `object`, not `dict`: PySide6 marshals a dict-typed signal argument,
    #: rebuilding the outer dict and every nested dict as new objects on the
    #: way to the slot (leaf values, blobs included, are shared). A row
    #: carries one reference to its engine record (`row["_record"] is
    #: entry`, asserted per builder), and `object` passes the row itself,
    #: so the detail dialog and anything writing tags or comments works on
    #: the real record. linkActivated below uses `object` for the same
    #: reason.
    recordActivated = Signal(object)
    linkActivated = Signal(object, dict)
    explainRequested = Signal(dict, str)
    #: "Show in database table" / "Show bytes at the carve offset" /
    #: "Show table ... (row deleted ...)". `object`, for the same
    #: identity reason as recordActivated.
    showInTableRequested = Signal(object)
    #: Column visibility was set from outside the Columns menu (a saved
    #: header state restored on launch). The owning view rebuilds its menu
    #: from the Column objects, which restore_column_state has synced.
    columnVisibilityRestored = Signal()
    #: "Search the database for this value": one cell's value, sent to the
    #: shell's database-wide search (MainWindow.search_for). The widget
    #: only reports the request.
    #:
    #: `str`, not `object`: it carries a value, not a record, so there is
    #: no identity to preserve.
    searchRequested = Signal(str)
    #: Put a tag on, or take it off, these rows' records: (rows, tag, on).
    #: An empty tag asks the shell for a new one's name.
    tagRequested = Signal(list, str, bool)
    #: Add a comment to these rows' records.
    commentRequested = Signal(list)
    #: The record under the grid's current row, or None: the selection
    #: moved, or the rows were replaced. The details pane follows it.
    currentRecordChanged = Signal(object)
    #: A right-click (or the platform's context-menu key) on a column
    #: heading. RecordsTable connects it to _open_filter_popup; anything
    #: else may connect to it too.
    filterRequested = Signal(int)

    #: The grid body's "Clear filters" button was pressed. The owning view
    #: clears its box, its chips and the model.
    clearFiltersRequested = Signal()

    #: the set of columns hidden because every visible row holds one
    #: value changed (a filter, a new record set).
    identicalColumnsChanged = Signal()

    #: One neutral glyph for every genuine empty state (see
    #: set_empty_reason/paintEvent below); the wording, per record set
    #: (RecordSet.empty_text), says which record set and why.
    _EMPTY_STATE_ICON = "folder"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sort_keys = []
        #: The most recently opened header FilterPopup, kept so tests can
        #: inspect it and so Python does not collect a visible, non-modal
        #: popup when _open_filter_popup returns.
        self._filter_popup = None
        #: The one ShareBarDelegate this table ever builds -- see
        #: bar_delegate.py for why a delegate and not a widget per row.
        #: Held as an attribute for the same reason _filter_popup above is
        #: one: Qt keeps only a borrowed pointer to a delegate, and a
        #: local would be collected out from under the view the instant
        #: set_records returned.
        self._bar_delegate = ShareBarDelegate(self)
        #: The application's QSS rule for QTableView::item (padding,
        #: border-bottom) makes QStyleSheetStyle paint CE_ItemViewItem and
        #: ignore Qt.BackgroundRole (see BackgroundRoleDelegate), so this
        #: delegate paints the carved tint. Set as the default delegate;
        #: set_records overrides it per column for "bar" columns. The
        #: wrapping subclass keeps the tint.
        self.setItemDelegate(WrappingDelegate(self, line_cap=ROW_LINE_CAP))
        #: Open "Whole value" windows, held so Python does not collect a
        #: non-modal window out from under Qt (the _filter_popup reason).
        self._whole_value_windows = []
        #: id(row dict) -> the height fit_visible_rows measured for it at the
        #: current column geometry, so a sort, a cleared filter or a scroll
        #: back does not measure the same rows again. Emptied by
        #: invalidate_row_hints() on anything that can change a height: a
        #: column resized or moved, Wrap, a theme or font change, a new
        #: record set.
        self._row_hints = {}
        #: The record set's sentence for why it has zero rows with no filter
        #: in force (see set_empty_reason). "" (the default) paints no
        #: overlay: a plain empty table.
        self._empty_reason = ""
        #: fn(rows) -> (tags to offer, {tag: count}, how many of `rows`
        #: can carry a tag), or None. Set by the shell, which owns the case
        #: file; None (no case open) means the menu offers no tagging.
        self.notes_provider = None
        #: The sentence for a record set that can become empty only through
        #: its own filter (SubTable's pane: a period always has at least one
        #: record, so only the pane's filter can leave it with zero rows).
        #: Kept apart from `_empty_reason`, because
        #: showing_genuine_empty_state() is False whenever
        #: model.filter.has_filters() is True. "" means not used.
        self._filtered_empty_reason = ""
        #: Hide-identical is a view preference; exports are unaffected.
        self._hide_identical = False
        self._auto_hidden = set()
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Tab and Ctrl+Tab move between controls; arrows still move
        # between cells. Left on (Qt's default) Tab never left the grid.
        self.setTabKeyNavigation(False)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(False)      # we drive sorting ourselves
        # wrap by default; set_wrap() is the one switch. See the
        # "visible rows only" methods below for why this is affordable at
        # 100,000 rows and ResizeToContents is not. The carved tint is
        # kept: WrappingDelegate IS a BackgroundRoleDelegate, and paints
        # through the style with the view's own options, so the WrapText
        # feature and ElideNone reach it unchanged.
        self._wrap = True
        self._row_fit_timer = QTimer(self)
        self._row_fit_timer.setSingleShot(True)
        self._row_fit_timer.setInterval(_ROW_FIT_DEBOUNCE_MS)
        self._row_fit_timer.timeout.connect(self.fit_visible_rows)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideNone)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.filterRequested.connect(self._open_filter_popup)
        # _ProvenanceHeaderView, not the stock QHeaderView (see its class
        # docstring). Installed before the setup below reads
        # self.horizontalHeader(), so it configures the header that paints.
        self.setHorizontalHeader(_ProvenanceHeaderView(Qt.Horizontal, self))
        header = self.horizontalHeader()
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._header_clicked)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(-1, Qt.AscendingOrder)
        # The funnel's only way in (see the module docstring on
        # FilterPopup): a SEPARATE CustomContextMenu policy from the
        # table's own (self.setContextMenuPolicy above is for per-CELL
        # right-clicks and stays untouched) -- the header is its own
        # widget with its own context-menu policy.
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(
            self._header_context_menu_requested)
        # The heading floor _fit_columns() applies at load is re-enforced on
        # every interactive resize too.
        header.sectionResized.connect(self._enforce_heading_floor)
        # A column that got narrower (or wider) re-wraps its values, and a
        # column dragged to a new place is re-fitted too, so nothing it
        # carries is ever left clipped.
        header.sectionResized.connect(self.invalidate_row_hints)
        header.sectionMoved.connect(self.invalidate_row_hints)
        header.sectionResized.connect(self._schedule_row_fit)
        header.sectionMoved.connect(self._schedule_row_fit)
        # The origin column -- see _OriginHeaderView.
        self.setVerticalHeader(_OriginHeaderView(self))
        vheader = self.verticalHeader()
        vheader.setVisible(True)
        vheader.setFixedWidth(vheader.floor_width())
        # Its heading lives in the corner button QTableView already owns;
        # painted by eventFilter, named for a screen reader and on hover.
        self.corner_button = next(iter(self.findChildren(QAbstractButton)), None)
        if self.corner_button is not None:
            self.corner_button.setAccessibleName(ORIGIN_HEADING)
            self.corner_button.setToolTip(
                "%s — %s: %s  %s: %s" % (ORIGIN_HEADING, ORIGIN_LABEL_LIVE,
                                         LIVE_ROW_TOOLTIP, ORIGIN_LABEL_CARVED,
                                         CARVED_ROW_TOOLTIP))
            self.corner_button.installEventFilter(self)
            # Qt wires the corner to selectAll; here it filters by origin,
            # like every other heading's funnel (Ctrl+A still selects all).
            self.corner_button.clicked.disconnect()
            self.corner_button.clicked.connect(self._open_origin_menu)
            self.corner_button.setCursor(Qt.PointingHandCursor)
            # Right-click too, as on every column heading.
            self.corner_button.setContextMenuPolicy(Qt.CustomContextMenu)
            self.corner_button.customContextMenuRequested.connect(
                lambda _pos: self._open_origin_menu())
        #: The Origin heading's filter menu while open, else None.
        self.origin_menu = None
        # Required for mouseMoveEvent to fire at all while merely hovering
        # -- without it Qt delivers move events only while a button is
        # held, and the link cursor below would never appear.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.doubleClicked.connect(lambda ix: self.activate_cell(ix.row(), ix.column()))
        QShortcut(QKeySequence.Copy, self, self._copy_to_clipboard)
        QShortcut(QKeySequence(Qt.Key_F1), self, self._explain_current_cell)
        # Rows scrolled into view are measured as they arrive. Only the
        # vertical bar: a row is measured over every column
        # (_row_height_hint), so a sideways scroll changes no height.
        # Connected last: the scroll bar routes events through eventFilter,
        # which reads self.corner_button set above.
        self.verticalScrollBar().valueChanged.connect(self._schedule_row_fit)
        # a real button INSIDE the grid body, shown only while a
        # filter has emptied the table.
        self.clear_filters_button = QPushButton("Clear filters", self.viewport())
        self.clear_filters_button.setVisible(False)
        self.clear_filters_button.clicked.connect(self.clearFiltersRequested.emit)

    def eventFilter(self, watched, event):
        if watched is self.corner_button and event.type() == QEvent.Paint:
            painter = QPainter(watched)
            option = QStyleOptionHeader()
            option.initFrom(watched)
            option.rect = watched.rect()
            option.text = ORIGIN_HEADING
            option.textAlignment = Qt.AlignCenter
            option.position = QStyleOptionHeader.OnlyOneSection
            watched.style().drawControl(QStyle.CE_Header, option, painter,
                                        watched)
            model = self.model()
            if model is not None and getattr(model, "origin_filter",
                                             lambda: None)() is not None:
                # Filtered: the same funnel a filtered column carries.
                size = 12
                pix = glyphs.pixmap("funnel", theme.color("primary"), size)
                painter.drawPixmap(watched.width() - size - 5,
                                   (watched.height() - size) // 2, pix)
            painter.end()
            return True
        return super().eventFilter(watched, event)

    # --- the Origin heading's filter ---------------------------------------

    def _open_origin_menu(self):
        """Each origin on screen with its row count, ticked while shown;
        unticking one hides those rows. Built fresh on every open from
        what is in force."""
        model = self.model()
        if model is None or not hasattr(model, "origin_counts"):
            return
        self._close_origin_menu()
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        allowed = model.origin_filter()
        for label, count in model.origin_counts():
            action = menu.addAction("%s (%s)" % (label, format(count, ",")))
            action.setCheckable(True)
            action.setChecked(allowed is None or label in allowed)
            action.setData(label)
            action.toggled.connect(self._apply_origin_menu)
        menu.addSeparator()
        show_all = menu.addAction("Show every origin")
        show_all.setEnabled(allowed is not None)
        show_all.triggered.connect(lambda: self._set_origin(None))
        self.origin_menu = menu
        button = self.corner_button
        menu.popup(button.mapToGlobal(QPoint(0, button.height())))

    def _apply_origin_menu(self, _checked=None):
        menu = self.origin_menu
        if menu is None:
            return
        choices = [a for a in menu.actions() if a.isCheckable()]
        kept = {a.data() for a in choices if a.isChecked()}
        self._set_origin(None if len(kept) == len(choices) else kept)

    def _set_origin(self, allowed):
        model = self.model()
        if model is None:
            return
        self.close_filter_popup()
        model.set_origin_filter(allowed)
        if self.corner_button is not None:
            self.corner_button.update()

    def _close_origin_menu(self):
        menu = self.origin_menu
        self.origin_menu = None
        if menu is not None:
            menu.close()
            menu.deleteLater()

    # --- data ------------------------------------------------------------

    @staticmethod
    def _origin_legend(aggregate):
        text = "%s — %s: %s  %s: %s" % (
            ORIGIN_HEADING, ORIGIN_LABEL_LIVE, LIVE_ROW_TOOLTIP,
            ORIGIN_LABEL_CARVED, CARVED_ROW_TOOLTIP)
        if aggregate:
            text += "  %s: %s  %s: %s  %s: %s" % (
                ORIGIN_LABEL_MIXED, MIXED_ROW_TOOLTIP,
                ORIGIN_LABEL_RECOVERED, RECOVERED_ONLY_TOOLTIP,
                ORIGIN_LABEL_NONE, NOT_A_RECORD_TOOLTIP)
        return text + "  Click to show or hide rows by origin."

    def set_records(self, columns, rows):
        """Show `rows`, replacing the previous model. Called again on the
        same table by every Open Evidence, so the outgoing RecordTableModel
        is disposed of rather than left parented to the table with its rows
        alive.

        A live FilterPopup holds a reference to the model it was opened on
        (self.model = model), so it is closed and scheduled for deletion
        first; deleting the model under an open popup would leave it a
        dangling pointer.
        """
        if self._filter_popup is not None:
            self._filter_popup.close()
            self._filter_popup.deleteLater()
            self._filter_popup = None
        old_model = self.model()
        self.setModel(RecordTableModel(columns, rows, self))
        self.selectionModel().currentRowChanged.connect(
            self._emit_current_record)
        self.currentRecordChanged.emit(None)
        # The origin column is as wide as the words this row set can show;
        # an aggregate row set sizes it for the widest word. Decided from
        # the row set's kind: the first row that is a record or an
        # aggregate determines it, since a view's rows are homogeneous. A
        # leading "not a record" row (origin "—") is stepped over.
        first = next((r for r in rows
                      if not ("_record" in r and r["_record"] is None
                              and aggregate_members(r) is None)), None)
        self.verticalHeader().set_aggregate(
            first is not None and aggregate_members(first) is not None)
        # The corner button's tooltip is the legend for this column: an
        # aggregate table also uses Mixed, Recovered only and a dash.
        self._close_origin_menu()       # it counted the outgoing rows
        if self.corner_button is not None:
            self.corner_button.setToolTip(self._origin_legend(
                self.verticalHeader()._aggregate))
        self._sort_keys = []
        self.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        # A new model has no empty-state sentence; the caller (a RecordsView
        # subclass, or RecoveryView) supplies one with set_empty_reason()
        # after this call, as it re-applies quick filters. Clearing it here
        # means one segment's wording is never painted over another's.
        self._empty_reason = ""
        self._filtered_empty_reason = ""
        # Which column is a bar depends on this column list, and a segment
        # switch can move or remove it, so every column's delegate is set
        # each time; a stale bar delegate would paint over another value.
        for i, col in enumerate(self.model().columns):
            self.setItemDelegateForColumn(
                i, self._bar_delegate if col.kind == "bar" else None)
        self.model().layoutRefreshed.connect(self.viewport().update)
        # A filter or sort is a model reset, and a reset does not give the
        # vertical header fresh sections: QHeaderView.reset() keeps every
        # section's size while the row count is unchanged, so a tall row's
        # height would carry over to whatever record moved there. Every
        # height is reset to the default first, then the rows in view are
        # measured.
        self.model().layoutRefreshed.connect(self._reset_row_heights)
        self.model().layoutRefreshed.connect(self._schedule_row_fit)
        self.model().layoutRefreshed.connect(self._place_clear_button)
        self.invalidate_row_hints()
        self._fit_columns()
        # Hidden is a per-Column view preference (an optional column
        # starts hidden; set_column_hidden flips it) -- re-applied on every
        # fresh model, because setModel resets the header's hidden state.
        # AFTER the fit, so the header keeps the fitted width for the
        # moment the column is shown again.
        for i, col in enumerate(self.model().columns):
            self.setColumnHidden(i, bool(col.hidden))
        self._auto_hidden = set()
        self.model().layoutRefreshed.connect(self._apply_identical)
        self._apply_identical()
        self.viewport().update()
        if old_model is not None:
            old_model.deleteLater()
        self._schedule_row_fit()

    # --- wrapping: visible rows only ------------------------------------

    def set_wrap(self, on):
        """The Wrap switch. Off: every row back to one line, elided at the
        cell edge with the whole value in the tooltip."""
        self._wrap = bool(on)
        self.invalidate_row_hints()
        self.setWordWrap(self._wrap)
        self.setTextElideMode(Qt.ElideNone if self._wrap else Qt.ElideRight)
        self._reset_row_heights()
        self._schedule_row_fit()
        self.viewport().update()

    def is_wrapping(self):
        return self._wrap

    def _reset_row_heights(self):
        """Every row back to the default height, in one call at any row
        count.

        QHeaderView.reset() keeps every section's size while the section
        count is unchanged, and setDefaultSectionSize() resizes only the
        sections still at the old default, so neither resets grown rows.
        resizeSection() per row is correct but slow at 100,000 rows.
        Re-attaching the header to the model, as Qt does for a new model,
        rebuilds the sections at the default size in under a millisecond.
        The header's selection model is re-attached with it, which
        setModel() would otherwise leave unset."""
        model = self.model()
        if model is None:
            return
        vheader = self.verticalHeader()
        vheader.setModel(None)
        vheader.setModel(model)
        vheader.setSelectionModel(self.selectionModel())

    def refit_rows(self):
        """A theme change alters font metrics; the views call this."""
        self.invalidate_row_hints()
        self._schedule_row_fit()

    def set_line_cap(self, lines):
        """The most lines a wrapped row paints (the "+N more lines" marker
        and Enter show the rest). None: no cap."""
        self.itemDelegate().line_cap = lines
        self.invalidate_row_hints()
        self._reset_row_heights()
        self._schedule_row_fit()

    def set_hide_identical(self, on):
        """Hide every column identical in all visible rows: a view
        preference. Exports write every column, and the sidecar names the
        ones hidden on screen. Re-evaluated on every filter change."""
        self._hide_identical = bool(on)
        self._apply_identical()

    def identical_columns(self):
        model = self.model()
        if model is None:
            return []
        return constant_columns(model.columns, model.filter.visible())

    def blank_columns(self):
        """Columns empty in every visible row."""
        model = self.model()
        if model is None:
            return []
        return blank_columns(model.columns, model.filter.visible())

    def _apply_identical(self, announce=True):
        model = self.model()
        if model is None:
            return
        found = ({c.key for c, _v in self.identical_columns()}
                 | {c.key for c in self.blank_columns()}
                 if self._hide_identical else set())
        # A filtered column never folds away: filtered to one value it is
        # identical by construction, and hiding it would hide the filter.
        flt = model.filter
        found = {k for k in found
                 if flt.allowed_values(k) is None and flt.condition_for(k) is None}
        for i, col in enumerate(model.columns):
            hide = bool(col.hidden) or col.key in found
            if self.isColumnHidden(i) != hide:
                self.setColumnHidden(i, hide)
        self._auto_hidden = found
        if announce:
            self.identicalColumnsChanged.emit()

    def auto_hidden_keys(self):
        return set(self._auto_hidden)

    def set_column_hidden(self, key, hidden):
        """Hide or show one column by key -- a view preference (the
        Column object remembers it for the session; exports ignore it)."""
        model = self.model()
        if model is None:
            return
        for i, col in enumerate(model.columns):
            if col.key == key:
                col.hidden = bool(hidden)
                self.setColumnHidden(i, bool(hidden))
                if not hidden:
                    self._enforce_heading_floor(
                        i, 0, self.horizontalHeader().sectionSize(i))
                self.invalidate_row_hints()
                self._schedule_row_fit()
                return

    def invalidate_row_hints(self, *_args):
        """Forget every remembered row height -- see _row_hints."""
        self._row_hints = {}

    def _schedule_row_fit(self, *_args):
        if self._wrap:
            self._row_fit_timer.start()

    def _row_height_hint(self, row, base, fm):
        """The height `row` needs, over EVERY column, or 0 when every value
        fits on one line (the default height then stands).

        Every column, not just those in view: a height that depended on
        the horizontal scroll made the rows under the pointer jump as a
        long column left the view. QTableView.sizeHintForRow over every
        column costs ~0.14 ms a cell (Python data() for ~8 roles), which
        is 37.6 ms for 12 columns and past the 50 ms budget for wider
        grids. So a cheap check comes first: a value with no line break
        whose one-line width fits its column cannot need wrapping, and
        only the cells that fail it get the delegate's full wrapped
        measure -- the SAME delegate and option Qt would use, so the
        height matches what is painted."""
        model = self.model()
        header = self.horizontalHeader()
        grid = 1 if self.showGrid() else 0
        fm_font = base.font
        hint = 0
        for col in range(header.count()):
            if header.isSectionHidden(col):
                continue
            width = header.sectionSize(col)
            index = model.index(row, col)
            text = index.data(Qt.DisplayRole)
            text = "" if text is None else str(text)
            delegate = self.itemDelegateForIndex(index)
            advance = (delegate.text_advance(text, fm_font)
                       if isinstance(delegate, WrappingDelegate)
                       else fm.horizontalAdvance(text))
            if "\n" not in text and advance <= width - _CELL_TEXT_SLACK_PX:
                continue
            option = QStyleOptionViewItem(base)
            # Less the grid line, as QTableView paints (and measures) a
            # cell: a value that fits in exactly `width` wraps at width-1.
            option.rect = QRect(0, 0, width - grid, self.rowHeight(row))
            size = delegate.sizeHint(option, index)
            hint = max(hint, size.height())
        if hint:
            hint += grid       # what sizeHintForRow adds for the grid line
        return hint

    def fit_visible_rows(self):
        """Grow (or shrink) the rows in the viewport to their content.

        Only the viewport's rows, rowAt(0) .. rowAt(bottom), never the
        whole model (QHeaderView.ResizeToContents would measure all 100,000
        rows on every layout). Each is measured over every column (see
        _row_height_hint). Returns how many rows were measured."""
        model = self.model()
        if not self._wrap or model is None or model.rowCount() == 0:
            return 0
        vheader = self.verticalHeader()
        default = vheader.defaultSectionSize()
        base = QStyleOptionViewItem()
        self.initViewItemOption(base)
        fm = QFontMetrics(base.font)
        measured = 0
        # A row's height hint cannot change between passes (same columns,
        # same widths), so a later pass only measures rows it newly
        # brought into view -- the passes exist to catch those. Across
        # fits, _row_hints remembers them by the row itself.
        wants = {}
        hints = self._row_hints
        for _pass in range(_ROW_FIT_MAX_PASSES):
            first = self.rowAt(0)
            if first < 0:
                break
            last = self.rowAt(self.viewport().height() - 1)
            if last < 0:
                last = model.rowCount() - 1
            changed = False
            for row in range(first, last + 1):
                want = wants.get(row)
                if want is None:
                    record = model.row_at(row)
                    # The row itself is kept beside its height, so an id
                    # can never be reused by another row while remembered.
                    held = hints.get(id(record))
                    if held is not None and held[0] is record:
                        want = held[1]
                    else:
                        want = max(default, self._row_height_hint(row, base, fm))
                        hints[id(record)] = (record, want)
                        measured += 1
                    wants[row] = want
                if vheader.sectionSize(row) != want:
                    vheader.resizeSection(row, want)
                    changed = True
            if not changed:
                break
        return measured

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._fill_spare_width()
        self._schedule_row_fit()
        self._place_clear_button()

    def set_bar_unit(self, unit):
        """Name what a kind="bar" column's share is of.

        The bar's tooltip states the percentage "of the busiest <unit> in
        this view", and the unit is set by whoever declared the column;
        this table holds the delegate that paints it.
        """
        self._bar_delegate.set_unit(unit)

    def _fit_columns(self):
        # resizeColumnsToContents() asks the model for every cell of every
        # row; its result is used only where a column declares no width.
        # Most record views declare a width for every column, so columns
        # are measured only when, and only those that, need it.
        needs_content = [i for i, c in enumerate(self.model().columns)
                         if not c.width]
        for i in needs_content:
            self.resizeColumnToContents(i)
            # Measured, then capped, so a very long value cannot make a
            # column wider than the screen; it wraps under the row cap like
            # every declared column.
            if self.horizontalHeader().sectionSize(i) > MAX_AUTO_COLUMN_PX:
                self.horizontalHeader().resizeSection(i, MAX_AUTO_COLUMN_PX)
        header = self.horizontalHeader()
        for i in range(len(self.model().columns)):
            if header.isSectionHidden(i):
                # See _enforce_heading_floor: never resize a hidden section.
                continue
            col = self.model().columns[i]
            want = col.width or header.sectionSize(i)
            header.resizeSection(i, want)
            self._enforce_heading_floor(i, 0, header.sectionSize(i))
        self._fill_spare_width(refit=True)

    #: The kinds that take the grid's spare width, in order of preference.
    _FILL_KINDS = ("url", "path")
    #: A text column at least this wide may take it when no URL or path
    #: column is shown.
    _FILL_TEXT_MIN_PX = 200
    #: Left unused at the right edge: a one-pixel overshoot once produced
    #: a horizontal scrollbar with nothing to scroll to.
    _FILL_GUARD_PX = 2

    def _fill_column(self):
        model = self.model()
        if model is None:
            return None
        header = self.horizontalHeader()
        shown = [i for i, c in enumerate(model.columns)
                 if not header.isSectionHidden(i)]
        for kind in self._FILL_KINDS:
            for i in shown:
                if model.columns[i].kind == kind:
                    return i
        for i in shown:
            col = model.columns[i]
            if col.kind == "text" and (col.width or 0) >= self._FILL_TEXT_MIN_PX:
                return i
        return None

    def _fill_spare_width(self, refit=False):
        """The main text column takes the width no other column uses.

        A column's declared width is its floor; the fill column grows into
        the rest of the viewport, and shrinks back to its floor (never
        below) as the window narrows. Re-run on a window resize and on every
        fit, never on a drag, so a column the examiner resized stays as set
        until the window changes."""
        index = self._fill_column()
        if index is None:
            self._fill = None
            return
        header = self.horizontalHeader()
        col = self.model().columns[index]
        if refit or getattr(self, "_fill", None) is None or self._fill[0] != index:
            self._fill = (index, header.sectionSize(index) if not col.width
                          else max(col.width, header.sectionSize(index)))
        floor = self._fill[1]
        others = sum(header.sectionSize(i) for i in range(header.count())
                     if i != index and not header.isSectionHidden(i))
        room = self.viewport().width() - others - self._FILL_GUARD_PX
        want = max(floor, room)
        if want != header.sectionSize(index):
            header.resizeSection(index, want)

    def _enforce_heading_floor(self, index, old_size, new_size):
        """Keep a column at or above its heading's width, at load
        (_fit_columns) and on every interactive drag. resizeSection() below
        re-emits sectionResized with a size already at the floor, so this
        re-enters once and then does nothing.

        A column with a basis badge (_ProvenanceHeaderView.paintSection)
        needs room for the badge as well as the label. Header labels are
        centred (QHeaderView.defaultAlignment() == AlignHCenter|
        AlignVCenter), so a label of width L extends L/2 either side of the
        midpoint, and keeping its right half clear of a badge reserving
        R + gap + badge_w on the right needs the same allowance mirrored on
        the left: hence `2 * reserve`.

        Centring also halves any margin added once, so the headroom for
        kerning, hinting and rendered ink beyond the measured advance is
        added as `2 * _LABEL_ESTIMATE_SLACK_PX`, giving the full slack on
        the badge side.

        The width constants are read from the header instance that paints,
        so the floor and the paint use the same numbers. This is a floor
        estimate; paintSection's background repaint guarantees that the
        badge never overlaps the label, at worst clipping the label's end.
        """
        model = self.model()
        if model is None or index >= len(model.columns):
            return
        header = self.horizontalHeader()
        if new_size == 0 or header.isSectionHidden(index):
            # A section being hidden: setSectionHidden emits
            # sectionResized(old, 0) while isSectionHidden is still False,
            # so size 0 identifies it (a drag cannot reach 0, because of
            # minimumSectionSize). Clamping here would resize the section
            # mid-hide and shift every later column; the floor is enforced
            # when the column is shown again (set_column_hidden).
            return
        column = model.column_at(index)
        # The weight the QSS PAINTS, not the widget's own -- see
        # _ProvenanceHeaderView.painted_font for why they differ.
        if isinstance(header, _ProvenanceHeaderView):
            label_w = QFontMetricsF(header.painted_font()).horizontalAdvance(
                column.label)
        else:
            label_w = header.fontMetrics().horizontalAdvance(column.label)
        if column.show_badge and column.badge and isinstance(header, _ProvenanceHeaderView):
            reserve = header.badge_width(column.badge) + header.BADGE_GAP_PX + header.RESERVED_RIGHT_PX
            # 2 * _LABEL_ESTIMATE_SLACK_PX, not 1x -- see this method's own
            # docstring on why a single
            # helping of slack only ever delivers HALF of itself as real
            # margin once centering is in play, the same reason `reserve`
            # just above is already doubled.
            floor = label_w + 2 * reserve + 2 * _LABEL_ESTIMATE_SLACK_PX
        else:
            floor = label_w + _HEADER_PAD_PX + _LABEL_ESTIMATE_SLACK_PX
        # resizeSection takes an int, and PySide6 truncates a float towards
        # zero, so ceil() makes the floor a true lower bound.
        floor = math.ceil(floor)
        if new_size < floor:
            header.resizeSection(index, floor)

    # --- sorting ---------------------------------------------------------

    def _header_clicked(self, section):
        key = self.model().column_at(section).key
        ctrl = QGuiApplication.keyboardModifiers() & Qt.ControlModifier
        existing = dict(self._sort_keys)
        desc = not existing.get(key, False) if key in existing else False
        if ctrl:
            self._sort_keys = [(k, d) for k, d in self._sort_keys if k != key]
            self._sort_keys.append((key, desc))
        else:
            self._sort_keys = [(key, desc)]
        self._apply_sort()

    def sort_keys(self):
        return list(self._sort_keys)

    def sort_by_key(self, key, descending):
        """Sort on one column by KEY -- the default order a view declares
        (RecordSet.default_sort) and anything else that is not a header
        click. A key this table does not declare is ignored."""
        model = self.model()
        if model is None or key not in [c.key for c in model.columns]:
            return
        self._sort_keys = [(key, bool(descending))]
        self._apply_sort()

    def _apply_sort(self):
        """Least significant key first: a stable sort applied repeatedly
        leaves the earlier keys intact inside the later one. The primary
        key is mirrored into Qt's sort-indicator state, which the
        header paints as an arrow in the section's left padding."""
        model = self.model()
        for key, desc in reversed(self._sort_keys):
            model.sort_by(key, desc)
        self._sync_sort_indicator()

    def _sync_sort_indicator(self):
        """The indicator always states the model's ACTUAL order. Also run
        after a column-state restore: QHeaderView.restoreState brings back
        the saved indicator section, order and shown flag, which is either
        another column's (saved at HEAD after a header click) or hidden
        (saved before the indicator existed)."""
        header = self.horizontalHeader()
        model = self.model()
        header.setSortIndicatorShown(True)
        if self._sort_keys and model is not None:
            key, desc = self._sort_keys[0]
            section = [c.key for c in model.columns].index(key)
            header.setSortIndicator(
                section, Qt.DescendingOrder if desc else Qt.AscendingOrder)
        else:
            header.setSortIndicator(-1, Qt.AscendingOrder)

    # --- filtering: the funnel's only way in ------------------------------

    def _header_context_menu_requested(self, pos):
        """Right-click (or the platform's context-menu key) on a column
        heading. logicalIndexAt() maps the click to a column by position,
        so a heading that has been drag-reordered opens the popup for the
        column under the cursor.

        Opens FilterPopup directly, in one click; "Copy column name" is
        inside the popup (FilterPopup's copy_name_button)."""
        section = self.horizontalHeader().logicalIndexAt(pos)
        if section < 0:
            return
        self.filterRequested.emit(section)

    def close_filter_popup(self):
        """Close an open header filter popup. The popup seeds itself when it
        opens and writes that state back on OK, so a filter changed
        underneath it (a quick-filter chip, Clear filters) would be undone
        by a stale popup. The examiner reopens it against what is now in
        force."""
        popup = self._filter_popup
        self._filter_popup = None
        if popup is not None:
            popup.close()
            popup.deleteLater()

    def _open_filter_popup(self, section):
        """Open FilterPopup for one column. It seeds itself from the live
        filter state and combines values with conditions (see its module
        docstring). Opened with .show(), not .exec(): a modal .exec() would
        block switching views or opening another column's filter while
        this one is open."""
        model = self.model()
        if model is None or not (0 <= section < len(model.columns)):
            return
        self.close_filter_popup()
        column = model.column_at(section)
        popup = FilterPopup(model, column, self)
        self._filter_popup = popup
        popup.show()

    # --- selection and copy ----------------------------------------------

    def selected_rows(self):
        model = self.model()
        seen, out = set(), []
        for ix in self.selectionModel().selectedIndexes():
            if ix.row() not in seen:
                seen.add(ix.row())
                out.append(model.row_at(ix.row()))
        return out

    def copy_selection_as_tsv(self):
        """A rectangle, with headers, so it pastes into a spreadsheet intact.

        Two guarantees:

        1. A cell inside the selection's bounding rectangle but not
           selected (common with Ctrl-click: SelectItems +
           ExtendedSelection) is blank, so a column the examiner excluded
           is not copied.
        2. If any row in the copy is carved, an "Origin (carved)" column is
           appended for every row, selected or not: a copied carved value
           always carries where it came from.
        """
        ixs = self.selectionModel().selectedIndexes()
        if not ixs:
            return ""
        model = self.model()
        selected = {(i.row(), i.column()) for i in ixs}
        rows = sorted({r for r, _ in selected})
        cols = sorted({c for _, c in selected})
        carved = any(_row_is_carved(model, r) for r in rows)

        header = [model.column_at(c).label for c in cols]
        if carved:
            header.append(_ORIGIN_GUARANTEE_LABEL)
        lines = ["\t".join(header)]
        for r in rows:
            line = [_tsv_safe(_cell_text(model, model.index(r, c)))
                    if (r, c) in selected else "" for c in cols]
            if carved:
                line.append(_tsv_safe(str(model.row_at(r).get("Origin", ""))))
            lines.append("\t".join(line))
        return "\n".join(lines)

    def _copy_to_clipboard(self):
        text = self.copy_selection_as_tsv()
        if text:
            QGuiApplication.clipboard().setText(text)

    def _copy_cell(self, index):
        """Byte-exact and undecorated (see _build_context_menu): a single
        value copy round-trips. A carved value is flagged in the menu
        label, not in the copied text."""
        QGuiApplication.clipboard().setText(_cell_text(self.model(), index))

    def _copy_row(self, row):
        model = self.model()
        values = [_tsv_safe(_cell_text(model, model.index(row, c)))
                  for c in range(model.columnCount())]
        # The row dump already walks every declared column above -- if one
        # of those is "Origin" (History's COLUMNS is), the value is already
        # in `values` and appending it again would just duplicate it with
        # no label to say why. See _declares_column's docstring.
        if _row_is_carved(model, row) and not _declares_column(model, "Origin"):
            values.append(_tsv_safe(str(model.row_at(row).get("Origin", ""))))
        QGuiApplication.clipboard().setText("\t".join(values))

    def _copy_column(self, column):
        model = self.model()
        any_carved = any(_row_is_carved(model, r) for r in range(model.rowCount()))
        # Copying the Origin column itself would otherwise tack its own
        # value onto each line a second time -- see _declares_column.
        is_origin_column = model.column_at(column).key == "Origin"
        lines = []
        for r in range(model.rowCount()):
            value = _tsv_safe(_cell_text(model, model.index(r, column)))
            if any_carved and not is_origin_column:
                value += "\t" + _tsv_safe(str(model.row_at(r).get("Origin", "")))
            lines.append(value)
        QGuiApplication.clipboard().setText("\n".join(lines))

    # --- activation ------------------------------------------------------

    def activate_cell(self, row, column):
        model = self.model()
        record = model.row_at(row)
        col = model.column_at(column)
        # is_link_for(record), not the bare
        # is_link: a link column whose target does not exist for THIS
        # row (a carved record with no ContainerId, say) is not a dead
        # click -- it behaves like any other ordinary cell instead, and
        # opens the record rather than calling on_click with nothing to
        # point at.
        if col.is_link_for(record):
            col.on_click(record)
            self.linkActivated.emit(col, record)
        else:
            self.recordActivated.emit(record)

    def open_record(self, row):
        """Open the detail dialog, whatever the column's kind.

        activate_cell sends a link cell to col.on_click (double-clicking
        History's Domain cell opens Domains), so this is the route to the
        record behind a link cell (Ctrl+Enter and the context menu's Open).
        activate_cell's behaviour is kept (test_path_kind.py,
        test_records_table.py): a double-click on a link follows it.

        A method rather than a lambda in the context menu, so a test can
        call it without a blocking QMenu.exec.

        Out-of-range indices are ignored: a shortcut can fire against a
        stale current index after a filter emptied the table.
        """
        model = self.model()
        if model is None or not (0 <= row < model.rowCount()):
            return
        self.recordActivated.emit(model.row_at(row))

    def _open_current_record(self):
        ix = self.currentIndex()
        if ix.isValid():
            self.open_record(ix.row())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            # Ctrl+Enter is handled HERE rather than as a QShortcut. A
            # QShortcut on a QKeySequence containing Return competes with
            # the view's own Return handling below, and which of the two
            # wins depends on focus and on Qt's shortcut context -- the
            # kind of ambiguity that makes a key work in a test and not in
            # the application. One handler, one decision, in the order
            # written: Ctrl first, plain Return second.
            #
            # Key_Enter as well as Key_Return: they are different keys
            # (numeric keypad vs main block), and binding only one leaves
            # the shortcut dead for anyone using the number pad.
            ix = self.currentIndex()
            if ix.isValid():
                if event.modifiers() & Qt.ControlModifier:
                    self.open_record(ix.row())
                elif self.is_capped(ix):
                    # A capped cell: Enter shows the part not painted.
                    self.show_whole_value(ix)
                else:
                    self.activate_cell(ix.row(), ix.column())
                return
        super().keyPressEvent(event)

    # --- the link affordance ---------------------------------------------

    def mouseMoveEvent(self, event):
        """A pointing cursor over a link cell, since link cells otherwise
        look like text. Set on the viewport, the widget under the pointer
        over a cell; a cursor set on the view would be masked by it.
        """
        index = self.indexAt(event.position().toPoint())
        model = self.model()
        wants_hand = False
        if model is not None and index.isValid():
            # is_link_for(row), not is_link: a row whose link has no target
            # shows no link cursor (as its tooltip offers no link).
            wants_hand = model.column_at(index.column()).is_link_for(
                model.row_at(index.row()))
            marker = self.marker_rect(index)
            if marker is not None and marker.contains(event.position().toPoint()):
                wants_hand = True
        if wants_hand:
            self.viewport().setCursor(Qt.PointingHandCursor)
        else:
            # unsetCursor(), not setCursor(ArrowCursor): the viewport then
            # inherits whatever the window is using -- a wait cursor
            # during a load, for instance -- instead of forcing an arrow
            # over the one widget.
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    # --- the row cap: reaching the whole value --------

    def _cell_option(self, index):
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = self.visualRect(index)
        return option

    def marker_rect(self, index):
        """The "+N more lines" marker's rect for a cell, in viewport
        coordinates, or None when the cell shows its whole value."""
        if not index.isValid() or not self._wrap:
            return None
        delegate = self.itemDelegateForIndex(index)
        if not isinstance(delegate, WrappingDelegate):
            return None
        return delegate.marker_rect(self._cell_option(index), index)

    def is_capped(self, index):
        return self.marker_rect(index) is not None

    def show_whole_value(self, index):
        """The "Whole value" window for one cell: the model's display
        text, whole, and a Copy giving the stored value exactly."""
        model = self.model()
        if model is None or not index.isValid():
            return None
        text = model.data(index, Qt.DisplayRole)
        origin = model.headerData(index.row(), Qt.Vertical, Qt.DisplayRole)
        heading = "%s, row %s (%s)" % (model.column_at(index.column()).label,
                                        format(index.row() + 1, ","), origin)
        window = WholeValueWindow(text, _cell_text(model, index), heading,
                                  self.window())
        self._whole_value_windows = [
            w for w in self._whole_value_windows if _alive(w)] + [window]
        window.show()
        return window

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.position().toPoint())
            marker = self.marker_rect(index)
            if marker is not None and marker.contains(event.position().toPoint()):
                self.setCurrentIndex(index)
                self.show_whole_value(index)
                event.accept()
                return
        super().mousePressEvent(event)

    def _explain_current_cell(self):
        """The context menu advertises 'Explain this value\tF1'; this is
        what makes that true rather than a hint for a keybinding that does
        nothing."""
        ix = self.currentIndex()
        if not ix.isValid():
            return
        model = self.model()
        self.explainRequested.emit(model.row_at(ix.row()), model.column_at(ix.column()).key)

    # --- context menu ----------------------------------------------------

    def _context_menu(self, pos):
        ix = self.indexAt(pos)
        if not ix.isValid():
            return
        menu = self._build_context_menu(ix)
        menu.exec(self.viewport().mapToGlobal(pos))

    def _build_context_menu(self, ix):
        """Split from _context_menu so tests can trigger an action directly
        without popping a real menu (QMenu.exec blocks for input)."""
        model = self.model()
        record, col = model.row_at(ix.row()), model.column_at(ix.column())
        carved = bool(model.data(ix, ROLE_IS_CARVED))
        menu = QMenu(self)
        # Copy, never Open: these paths belong to the examined machine.
        #
        # Copy cell is byte-exact (see _copy_cell); a carved value is
        # flagged in the label, at the moment of copying, never in the
        # copied text.
        # First, before the copy actions: opening the record is the most
        # common use of a right-click on a row. Carved is flagged in the
        # label, as for Copy cell.
        ref = row_locator.source_row(record)
        if ref is not None and ref.kind == row_locator.ORDINAL:
            open_label = "Open this row in Table Browser\tCtrl+Enter"
        else:
            open_label = ("Open this carved record\tCtrl+Enter" if carved
                          else "Open this record\tCtrl+Enter")
        menu.addAction(open_label, lambda: self.open_record(ix.row()))
        if ref is not None and ref.kind != row_locator.ORDINAL:
            menu.addAction(row_locator.action_label(ref),
                           lambda r=record: self.showInTableRequested.emit(r))
        # Every cell, capped or not: the whole value, in its own window.
        menu.addAction("Show whole value\tEnter" if self.is_capped(ix)
                       else "Show whole value",
                       lambda: self.show_whole_value(ix))
        self._add_notes_menu(menu, ix)
        menu.addSeparator()
        cell_label = "Copy cell (carved record)" if carved else "Copy cell"
        menu.addAction(cell_label, lambda: self._copy_cell(ix))
        menu.addAction("Copy row", lambda: self._copy_row(ix.row()))
        menu.addAction("Copy column", lambda: self._copy_column(ix.column()))
        menu.addSeparator()
        menu.addAction("Explain this value\tF1",
                       lambda: self.explainRequested.emit(record, col.key))
        # Search the database (not only the rows on screen, which the
        # filter box covers) for this cell's displayed value; the shell
        # performs the search.
        raw = record.get(col.key)
        value = "" if raw is None else str(raw)
        menu.addAction("Search the database for this value",
                       lambda v=value: self.searchRequested.emit(v))
        return menu

    def _emit_current_record(self, current, _previous=None):
        model = self.model()
        if model is None or not current.isValid():
            self.currentRecordChanged.emit(None)
            return
        self.currentRecordChanged.emit(model.row_at(current.row()))

    def _rows_for_menu(self, ix):
        """The selection's rows when the clicked row is part of it, else
        just the clicked row -- what a right-click acts on everywhere."""
        model = self.model()
        rows = sorted({i.row() for i in self.selectionModel().selectedIndexes()})
        if ix.row() not in rows:
            rows = [ix.row()]
        return [model.row_at(r) for r in rows]

    def _add_notes_menu(self, menu, ix):
        """Tag and Add a comment, over the rows a right-click acts on."""
        provider = self.notes_provider
        if provider is None:
            return
        rows = self._rows_for_menu(ix)
        offered = provider(rows)
        if not offered:
            return
        tags, counts, total = offered
        if not total:
            return
        menu.addSeparator()
        # Parented explicitly: a QMenu created by addMenu(title) is owned
        # by Python in PySide6 and would be collected, actions included,
        # when this method returned.
        sub = QMenu("Tag %s records" % format(total, ",")
                    if total > 1 else "Tag this record", menu)
        menu.addMenu(sub)
        for tag in tags:
            n = counts.get(tag, 0)
            action = sub.addAction(tag)
            action.setCheckable(True)
            action.setChecked(n == total)
            if 0 < n < total:
                action.setToolTip("%s of %s carry it" % (format(n, ","),
                                                        format(total, ",")))
            action.triggered.connect(
                lambda _c=False, t=tag, on=(n < total):
                self.tagRequested.emit(rows, t, on))
        sub.addSeparator()
        sub.addAction("New tag…",
                      lambda: self.tagRequested.emit(rows, "", True))
        menu.addAction("Add a comment…",
                       lambda: self.commentRequested.emit(rows))

    # --- empty states ----------------------------------------------------

    def empty_message(self):
        """No state is a dead end: say what emptied the table -- EVERY
        filter in force, by its column label -- and offer the way back."""
        model = self.model()
        if model is None or model.rowCount():
            return ""
        if not model.filter.has_filters():
            return "No records in this view."
        return FILTERED_EMPTY_TEXT % (model.chip_text() or "a filter")

    def set_empty_reason(self, text):
        """The sentence a genuinely empty record set is painted with (see
        showing_genuine_empty_state). `text` is the owning view's wording
        (RecordSet.empty_text, or RecoveryView's equivalent).

        A view that never calls this shows a plain empty grid under the
        count line.
        """
        self._empty_reason = text or ""
        self.viewport().update()

    def showing_genuine_empty_state(self):
        """True only for a record set empty on its own merits, never one
        narrowed to nothing by a filter (model.filter.has_filters() true),
        which is empty_message()'s case. Returns False then even if an
        empty reason is set, so the two states are never confused.
        """
        model = self.model()
        if model is None or model.rowCount() or model.filter.has_filters():
            return False
        return bool(self._empty_reason)

    def set_filtered_empty_reason(self, text):
        """The sentence for a record set that can become empty only through
        its own filter (SubTable's pane, whose rows are never genuinely
        empty). The mirror of set_empty_reason: this one requires
        model.filter.has_filters() to be True (see
        showing_filtered_empty_state), that one False. Views that never
        call it keep the plain filtered-empty grid and the count line's
        empty_message().
        """
        self._filtered_empty_reason = text or ""
        self.viewport().update()

    def showing_filtered_empty_state(self):
        """True only for a record set whose OWN filter narrowed it to
        zero rows, and only when a caller opted in with
        set_filtered_empty_reason. The exact complement of
        showing_genuine_empty_state's filter check: that one excludes a
        filtered table on purpose (empty_message() already owns that
        wording, in the count line, for every ordinary record set); this
        one exists because SubTable's pane has no count line of its own
        to carry that wording, so the filtered case would otherwise have
        no message anywhere on screen.
        """
        model = self.model()
        if model is None or model.rowCount() or not model.filter.has_filters():
            return False
        return bool(self._filtered_empty_reason)

    def empty_state_text(self):
        """The text paintEvent below draws: "" unless
        showing_genuine_empty_state() or showing_filtered_empty_state() is
        True, so tests can check the sentence without reading pixels. The
        two states are mutually exclusive (one requires has_filters()
        False, the other True)."""
        if self.showing_genuine_empty_state():
            return self._empty_reason
        if self.showing_filtered_empty_state():
            return self._filtered_empty_reason
        model = self.model()
        if (model is not None and not model.rowCount()
                and model.filter.has_filters()):
            return self.empty_message()
        return ""

    def paintEvent(self, event):
        """super() first, so the grid paints normally, including the
        filtered-to-zero case, which keeps a plain empty grid and
        empty_message()'s count-line text. Only an empty state with a
        sentence gets this centred overlay, painted directly onto the
        viewport (as _ProvenanceHeaderView paints its badge) rather than
        as a child widget that would need its own resize and theme
        handling.
        """
        super().paintEvent(event)
        text = self.empty_state_text()
        if not text:
            self._place_clear_button()
            return
        rect = self.viewport().rect()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, True)
        icon_size = 40
        icon_pix = glyphs.pixmap(self._EMPTY_STATE_ICON, theme.color("muted2"), icon_size)
        icon_x = rect.center().x() - icon_size // 2
        icon_y = rect.center().y() - 60
        painter.drawPixmap(icon_x, icon_y, icon_pix)
        text_font = QFont(self.font())
        text_font.setPointSizeF(text_font.pointSizeF() + 1)
        painter.setFont(text_font)
        painter.setPen(theme.color("muted2"))
        margin = 40
        text_rect = QRectF(rect.left() + margin, icon_y + icon_size + 14,
                           rect.width() - 2 * margin, rect.height())
        painter.drawText(text_rect, Qt.AlignHCenter | Qt.TextWordWrap, text)
        painter.end()
        self._place_clear_button()

    def _place_clear_button(self):
        model = self.model()
        show = bool(model is not None and not model.rowCount()
                    and model.filter.has_filters())
        if show:
            button = self.clear_filters_button
            button.adjustSize()
            rect = self.viewport().rect()
            button.move(rect.center().x() - button.width() // 2,
                        rect.center().y() + 70)
        if self.clear_filters_button.isVisible() != show:
            self.clear_filters_button.setVisible(show)

    # --- column state ----------------------------------------------------

    def reset_column_layout(self):
        """Every column back to its declared width, its declared place and
        its default visibility (an optional column hidden): the way back
        from a saved layout that no longer fits. Identical-column folding
        is re-applied over the defaults."""
        model = self.model()
        if model is None:
            return
        header = self.horizontalHeader()
        for logical in range(len(model.columns)):
            visual = header.visualIndex(logical)
            if visual != logical:
                header.moveSection(visual, logical)
        for i, col in enumerate(model.columns):
            col.hidden = bool(col.optional)
            self.setColumnHidden(i, col.hidden)
        self._fit_columns()
        self._apply_identical()
        self.invalidate_row_hints()
        self._schedule_row_fit()
        self.columnVisibilityRestored.emit()

    def save_column_state(self):
        """The header as the examiner arranged it. A column folded away by
        Hide identical columns is saved as shown: the fold depends on this
        exhibit's rows, and restoring it as hidden on another exhibit would
        hide values that differ."""
        header = self.horizontalHeader()
        model = self.model()
        folded = []
        if model is not None:
            folded = [i for i, col in enumerate(model.columns)
                      if col.key in self._auto_hidden and not col.hidden
                      and header.isSectionHidden(i)]
        for i in folded:
            header.setSectionHidden(i, False)
        try:
            return bytes(header.saveState())
        finally:
            for i in folded:
                header.setSectionHidden(i, True)

    def column_signature(self):
        """The identity of the table's current columns, in declared
        (logical) order rather than the header's visual order. Passed to
        restore_column_state() as `signature`, to refuse a state captured
        for a different set of columns (QHeaderView.restoreState() does
        not reject one itself). () for a table with no model yet, which
        never matches a saved signature.
        """
        model = self.model()
        return tuple(c.key for c in model.columns) if model is not None else ()

    def restore_column_state(self, state, signature=None):
        """Restore a saved header state, then re-apply the heading floors.

        QHeaderView.restoreState() sets every section's size directly,
        without sectionResized, so _enforce_heading_floor is re-applied
        afterwards; otherwise a width saved from a cramped window would be
        restored below its heading's floor on every launch.

        `signature`, when given, is compared with column_signature() before
        the header is touched. restoreState() keys on section count and
        position only, and with a mismatched count can leave the header's
        count() different from the model's column count while still
        returning True. A mismatched signature means the state belongs to
        other columns (another segment of a multi-segment view, or an
        older column set), so it is refused and the _fit_columns() layout
        is kept. Without a signature the state is applied unconditionally,
        with the floor re-applied.

        The header.count() check after restoreState() catches the same
        mismatch when there is no signature to check first.
        """
        if not state:
            return
        if signature is not None and tuple(signature) != self.column_signature():
            return
        header = self.horizontalHeader()
        if not header.restoreState(state):
            return
        self._sync_sort_indicator()
        model = self.model()
        if model is None or header.count() != len(model.columns):
            self._fit_columns()
            return
        for i in range(len(model.columns)):
            self._enforce_heading_floor(i, 0, header.sectionSize(i))
        # restoreState also restores which sections are hidden. Column.hidden
        # is what every other reader uses (the next set_records, the Columns
        # menu, the export sidecar's "hidden on screen" list), so it is
        # synced to what the header now shows.
        # Only an optional column can be hidden by the examiner (it has a
        # Columns-menu entry); a restored hide on any other column is an old
        # identical-column fold, and is dropped.
        for i, col in enumerate(model.columns):
            col.hidden = (bool(col.optional) and header.isSectionHidden(i)
                          and col.key not in self._auto_hidden)
        # restoreState showed every section it saved as shown, folded ones
        # included, while the strip still listed them as hidden. Quietly:
        # the strip already names them, and a listener (Deleted Records'
        # URL fit) would otherwise undo the widths just restored.
        self._apply_identical(announce=False)
        self.columnVisibilityRestored.emit()
