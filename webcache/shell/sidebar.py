"""The nav rail: brand, Open Database, the 16 destinations, the theme pill.

The underlying widget is a QListWidget (MainWindow.nav), so
currentItemChanged, setCurrentRow, count() and item() work as usual. Each
item gets a NavRow through setItemWidget(), which lays out an icon, a
label and a right-aligned count in one row, while keyboard navigation,
current-row tracking and hit-testing stay QListWidget's.

A row widget's background is transparent: theme.py's QSS styles
`QListWidget::item:selected` (background and a left accent border) and
`::item:hover`, which show through every row widget.
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import glyphs, icon, theme
from ..widgets import copyable

SIDEBAR_WIDTH = 208

#: The icon strip: a 15px icon, the row's 8px left padding, the selected
#: row's 2px accent border and the list's own margins, with room to spare.
SIDEBAR_COLLAPSED_WIDTH = 52

#: key -> glyphs.py name. Related views share a glyph: Domains,
#: Containers and Table Browser use "database"; Findings and Integrity use
#: "shield".
NAV_ICONS = {
    "dashboard": "grid", "history": "clock", "downloads": "folder",
    "search": "search", "timeline": "chart", "domains": "database",
    "location": "pin", "indicators": "globe", "iocs": "shield",
    "cookies": "lock", "headers": "folder", "containers": "database",
    "recovery": "trash", "browser": "database", "integrity": "shield",
    "export": "download", "tagged": "tag",
}

#: key -> palette role for that row's count when it is not the selected
#: row. The selected row is always drawn in "primary" (see
#: NavRow.set_selected). Unlisted keys use "muted".
_COUNT_ROLE = {"recovery": "carved"}

#: Row and section-heading heights: small enough that all sixteen
#: destinations and six headings fit the examiner's 816 px work area
#: without scrolling, while each row stays a comfortable click target.
#: Measured natively by tests/_sidebar_fit_probe.py.
_ROW_HEIGHT = 26
_SECTION_HEIGHT = 18

#: A row's ordinary left/right content padding -- unrelated to the
#: scrollbar, present whether or not one is ever shown.
_ROW_PADDING_PX = 8

#: How many characters of a destination's name NavRow._reflow_name keeps
#: on screen however wide its count badge grows, so "Deleted Records" never
#: reads as "Del…". A QLabel does not elide on its own, so the name is
#: elided explicitly. Tested in tests/test_recovery_not_clipped.py.
_NAME_MIN_CHARS = 6

#: The badge's font size for an ordinary count, and for a count of
#: _BADGE_LARGE_DIGITS digits or more. 9 px (6 px is not a number an
#: examiner can read at a glance) still leaves
#: the name its _NAME_MIN_CHARS floor: "1,234,567" at 9 px is ~81 px of the
#: row's ~133 px of content, leaving ~52 px against the ~43 px the name's
#: floor needs. See tests/test_recovery_not_clipped.py's big-count tests.
_BADGE_FONT_PX = 11
_BADGE_FONT_PX_LARGE = 9
_BADGE_LARGE_DIGITS = 5

#: A third, smaller badge font for a count of _BADGE_HUGE_DIGITS digits or
#: more ("1,234,567"). NavRow's labels set only a QSS font-size, so their
#: metrics depend on the font Qt substitutes; where that font is wide,
#: _BADGE_FONT_PX_LARGE leaves too little room for the name's
#: _NAME_MIN_CHARS. This step recovers that width without changing
#: _BADGE_FONT_PX_LARGE (tests/test_recovery_not_clipped.py).
_BADGE_FONT_PX_HUGE = 7
_BADGE_HUGE_DIGITS = 7

#: The nav scrollbar's footprint (theme.py's QListWidget#navList
#: QScrollBar rule: 10px wide, 1px margin each side). Reserved inside each
#: row's layout, on top of _ROW_PADDING_PX, only while the scrollbar is
#: visible (Sidebar._update_scrollbar_reserve), so a right-aligned count
#: badge is never painted under it. QListView narrows rows for the
#: scrollbar by less than it needs and ignores viewport margins for item
#: width, so the reserve is a per-row margin.
_SCROLLBAR_RESERVE_PX = 12


class NavRow(QWidget):
    """One selectable nav destination: icon, label, right-aligned count."""

    def __init__(self, key, label, icon_name, parent=None):
        super().__init__(parent)
        self._compact = False
        #: Whether the nav list currently shows its scrollbar -- see
        #: set_scrollbar_reserve; applied only while expanded.
        self._reserve = False
        self.key = key
        self._icon_name = icon_name
        self._selected = False
        self._count_role = _COUNT_ROLE.get(key, "muted")
        self._count_text = ""
        self._count_unit = ""
        #: The key that jumps here ("Ctrl+3"), or "" -- see set_shortcut.
        self._shortcut = ""
        #: True for a destination that never shows a number (see
        #: main_window._NO_COUNT_KEYS). Independent of `dormant`, which
        #: means evidence is not open yet: this row keeps its dash after
        #: set_dormant(False).
        self._no_count = False
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(15, 15)
        # icon-only, AND inside a clickable row: text selection would
        # swallow the click that navigates (see copyable.py).
        self._icon_label.setProperty(copyable.DECORATIVE, True)
        #: The destination's own full name -- text_label may show less of
        #: it (elided) once _reflow_name runs, but this is what it is
        #: elided FROM, never a lossily-shortened copy of itself.
        self._full_label = label
        self.text_label = QLabel(label)
        # Inside a clickable nav row: making it mouse-selectable would
        # swallow the click that navigates to the destination, and the
        # destination's own name is not a fact an investigator needs to
        # copy out of the sidebar (it is on screen as the view's own
        # ViewHeader title, which IS selectable).
        self.text_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(self.text_label)  # text shown exactly, never as markup
        self.text_label.setStyleSheet("font-size: 12.5px; background: transparent;")
        # A minimum width, like count_label's below: at least
        # _NAME_MIN_CHARS of the name plus the ellipsis stay on screen.
        self.text_label.setMinimumWidth(self._elided_floor_width())
        self.count_label = QLabel("")
        # Same reason as text_label above: inside the same clickable row.
        self.count_label.setProperty(copyable.DECORATIVE, True)
        copyable.plain(self.count_label)  # text shown exactly, never as markup
        self.count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.count_label.setStyleSheet(
            "font-size: 11px; font-family: 'Cascadia Mono', Consolas, monospace; "
            "background: transparent;")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, _ROW_PADDING_PX, 0)
        row.setSpacing(10)
        row.addWidget(self._icon_label)
        row.addWidget(self.text_label, 1)
        row.addWidget(self.count_label)
        self.setFixedHeight(_ROW_HEIGHT)
        self.refresh_theme()

    def set_selected(self, selected):
        self._selected = selected
        weight = "600" if selected else "400"
        self.text_label.setStyleSheet(
            "font-size: 12.5px; font-weight: %s; background: transparent;"
            % weight)
        self._repaint_icon()
        self._repaint_count()

    def set_count(self, text, unit=""):
        self._count_text = text or ""
        self._count_unit = unit or ""
        self._repaint_count()
        self._refresh_tooltip()

    def set_no_count(self):
        """Mark this row as never showing a number (see
        main_window._NO_COUNT_KEYS). Painted like the pre-evidence dash
        (set_dormant/_repaint_count), but kept after set_dormant(False)."""
        self._no_count = True
        self._repaint_count()

    def set_compact(self, compact):
        """The icon strip: name and badge hidden, both still in the
        tooltip and the badge still copyable (build_context_menu reads
        count_label's text, which is kept current while hidden)."""
        self._compact = bool(compact)
        self.text_label.setVisible(not self._compact)
        self.count_label.setVisible(not self._compact)
        # In the icon strip the icon is alone in the row, so it is centred
        # in the strip.
        self.layout().setAlignment(
            self._icon_label,
            Qt.AlignCenter if self._compact else Qt.Alignment())
        self._apply_margins()
        self._refresh_tooltip()

    def _apply_margins(self):
        """The row's margins for its mode: none in the icon strip (the
        icon is centred), the name's padding plus any scrollbar reserve
        when expanded."""
        if self._compact:
            self.layout().setContentsMargins(0, 0, 0, 0)
            return
        right = _ROW_PADDING_PX + (_SCROLLBAR_RESERVE_PX if self._reserve
                                   else 0)
        self.layout().setContentsMargins(8, 0, right, 0)

    def _refresh_tooltip(self):
        """The full name, and the count when there is one -- in BOTH
        modes. Expanded, the name may be elided (_reflow_name); this is
        where it is never cut."""
        count = self.count_label.text()
        if not count or count == "–":
            text = self._full_label
        else:
            text = "%s — %s%s" % (self._full_label, count,
                                  " " + self._count_unit
                                  if self._count_unit else "")
        if self._shortcut:
            text = "%s · %s" % (text, self._shortcut)
        self.setToolTip(copyable.literal_tooltip(text))

    def set_shortcut(self, keys):
        """Name the key that jumps to this view in its tooltip: the
        fastest route between views, otherwise only in the Help menu."""
        self._shortcut = keys
        self._refresh_tooltip()

    def set_scrollbar_reserve(self, active):
        """Widen this row's right content margin by _SCROLLBAR_RESERVE_PX
        while `active` (see that constant). Called on every row by
        Sidebar._update_scrollbar_reserve whenever the nav scrollbar's range
        changes, so it follows a window resize."""
        # Remembered, and applied only while expanded, so the centred icon
        # in the strip is not moved.
        self._reserve = bool(active)
        self._apply_margins()

    def set_dormant(self, dormant):
        """The pre-evidence look: every row dimmed, every count a dash --
        see the consent and first-run artboards, where the
        nav is visibly present but visibly inert until something is open."""
        self.setEnabled(not dormant)
        self.text_label.setStyleSheet(
            "font-size: 12.5px; background: transparent; %s"
            % ("color: %s;" % theme.color("muted").name() if dormant else ""))
        self.setProperty("dormant", dormant)
        self._repaint_icon()
        self._repaint_count()

    def refresh_theme(self):
        self._repaint_icon()
        self._repaint_count()

    def resizeEvent(self, event):
        """The row's OWN width changes on a window resize and whenever
        Sidebar._update_scrollbar_reserve widens/narrows the right margin
        -- both change how much room text_label has left after the icon
        and count_label, so both must re-run the elision, not just a
        count change (_repaint_count already covers that one)."""
        super().resizeEvent(event)
        self._reflow_name()

    def _elided_floor_width(self):
        """The pixel width of the first _NAME_MIN_CHARS of this row's own
        name plus an ellipsis -- the floor _reflow_name never shrinks
        text_label past. Shorter names (e.g. "Search") are never
        artificially widened: the floor is their own full width instead."""
        fm = self.text_label.fontMetrics()
        if len(self._full_label) <= _NAME_MIN_CHARS:
            return fm.horizontalAdvance(self._full_label)
        return fm.horizontalAdvance(self._full_label[:_NAME_MIN_CHARS] + "…")

    def _reflow_name(self):
        """Elide text_label to the room left after the icon, spacing,
        margins and count_label's minimum width.

        Reads count_label.minimumWidth(), the constraint _repaint_count
        set, rather than count_label.width(), which the layout may not have
        applied yet.

        `available` is never raised to _elided_floor_width(): elidedText()
        would then return the full name for a width the label does not
        have, and the label would clip it without an ellipsis. count_label
        has no stretch factor, so an over-constrained row shrinks
        text_label, never count_label (tests/test_recovery_not_clipped.py).
        For very large counts, _repaint_count shrinks the badge's font to
        restore the floor.
        """
        margins = self.layout().contentsMargins()
        reserved = (margins.left() + margins.right()
                    + self._icon_label.width()
                    + self.layout().spacing() * 2
                    + self.count_label.minimumWidth())
        available = max(0, self.width() - reserved)
        fm = self.text_label.fontMetrics()
        self.text_label.setText(
            fm.elidedText(self._full_label, Qt.ElideRight, available))

    def build_context_menu(self):
        """Right-click Copy for the badge's figure, as StatChip offers
        (build_context_menu). The badge is not selectable, so a click on it
        still navigates. Copies the text shown; None when the badge shows a
        dash. Returned rather than shown, so a test can trigger the action
        without a blocking QMenu.exec."""
        figure = self.count_label.text()
        if not figure or figure == "–":
            return None
        menu = QMenu(self)
        action = menu.addAction("Copy")
        action.triggered.connect(
            lambda: QGuiApplication.clipboard().setText(figure))
        return menu

    def contextMenuEvent(self, event):
        menu = self.build_context_menu()
        if menu is None:
            event.ignore()
            return
        menu.exec(event.globalPos())

    def _relayout_now(self):
        """Lay the row out immediately. setMinimumWidth resizes the label in
        place, anchored at its old x, so a badge growing from a dash would
        extend past the viewport until the next LayoutRequest. activate()
        moves it now."""
        layout = self.layout()
        if layout is not None:
            layout.activate()

    def _repaint_icon(self):
        dormant = bool(self.property("dormant"))
        color = theme.color("primary") if (self._selected and not dormant) \
            else theme.color("muted")
        self._icon_label.setPixmap(glyphs.pixmap(self._icon_name, color, 15))

    def _repaint_count(self):
        if self.property("dormant") or self._no_count:
            self.count_label.setText("–")
            self.count_label.setStyleSheet(
                "font-size: %dpx; font-family: 'Cascadia Mono', Consolas, monospace; "
                "background: transparent; color: %s;"
                % (_BADGE_FONT_PX, theme.color("muted").name()))
            self.count_label.setMinimumWidth(
                self.count_label.fontMetrics().horizontalAdvance("–"))
            self.count_label.updateGeometry()
            self._relayout_now()
            self._reflow_name()
            self._refresh_tooltip()
            return
        role = "primary" if self._selected else self._count_role
        self.count_label.setText(self._count_text)
        # A count of six or more digits ("100,000", "1,234,567") at 11px
        # needs more room than a 208px sidebar has once the name keeps
        # _NAME_MIN_CHARS (see _reflow_name). The badge never gives up its
        # own width, so for such counts its font is made smaller (see
        # _BADGE_FONT_PX_LARGE; widths checked in
        # tests/test_recovery_not_clipped.py).
        digits = sum(ch.isdigit() for ch in self._count_text)
        font_px = (_BADGE_FONT_PX_HUGE if digits >= _BADGE_HUGE_DIGITS
                   else _BADGE_FONT_PX_LARGE if digits >= _BADGE_LARGE_DIGITS
                   else _BADGE_FONT_PX)
        self.count_label.setStyleSheet(
            "font-size: %dpx; font-family: 'Cascadia Mono', Consolas, monospace; "
            "background: transparent; color: %s;" % (font_px, theme.color(role).name()))
        # A label sized for its FIRST text keeps that width inside the nav
        # list's item widget, and right alignment then shows only the last
        # digits: "418" read as "8". State the width the text needs.
        self.count_label.setMinimumWidth(
            self.count_label.fontMetrics().horizontalAdvance(
                self.count_label.text()))
        self.count_label.updateGeometry()
        self._relayout_now()
        # The badge's minimum width changed how much room text_label has
        # (see _reflow_name).
        self._reflow_name()
        self._refresh_tooltip()


class _SectionHeader(QLabel):
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        copyable.selectable(self)
        self.setFixedHeight(_SECTION_HEIGHT)
        # 3+1, not 6+4, so the 9.5px heading keeps 14 px inside the
        # 18 px box.
        self.setContentsMargins(8, 3, 8, 1)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.refresh_theme()

    def refresh_theme(self):
        self.setStyleSheet(
            "font-size: 9.5px; font-weight: 700; letter-spacing: 1.1px; "
            "background: transparent; color: %s;"
            % theme.color("muted2").name())


class Sidebar(QWidget):
    #: Open Database as a filled button at the top of the rail.
    openRequested = Signal()
    themeToggleRequested = Signal()
    collapsedChanged = Signal(bool)

    def __init__(self, nav_sections, parent=None):
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_WIDTH)
        self.setAutoFillBackground(True)
        self.setObjectName("sidebar")

        self._rows = {}
        self._headers = []
        self._dormant = True
        self._collapsed = False
        self._section_items = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- brand lockup --------------------------------------------------
        brand = QHBoxLayout()
        brand.setContentsMargins(12, 14, 12, 12)
        brand.setSpacing(8)
        self._brand_icon = QLabel()
        self._brand_icon.setFixedSize(20, 20)
        self._brand_icon.setProperty(copyable.DECORATIVE, True)  # icon-only
        brand.addWidget(self._brand_icon)
        names = QVBoxLayout()
        names.setSpacing(1)
        self._brand_title = copyable.selectable(QLabel("WebCache"))
        self._brand_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self._brand_subtitle = copyable.selectable(QLabel("Forensic Analyzer"))
        self._brand_subtitle.setStyleSheet(
            "font-size: 10px; letter-spacing: 0.3px; color: %s;"
            % theme.color("muted").name())
        names.addWidget(self._brand_title)
        names.addWidget(self._brand_subtitle)
        brand.addLayout(names, 1)
        root.addLayout(brand)

        # -- primary action ---------------------------------------------
        button_row = QHBoxLayout()
        button_row.setContentsMargins(12, 0, 12, 12)
        self._button_row = button_row
        self.open_button = QPushButton("Open Database")
        theme.mark_accent(self.open_button)
        self.open_button.setFixedHeight(38)
        self.open_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.open_button.clicked.connect(self.openRequested.emit)
        button_row.addWidget(self.open_button)
        root.addLayout(button_row)

        # -- nav --------------------------------------------------------
        self.nav = QListWidget()
        # navList: theme.py scopes a higher-contrast, wider scrollbar to
        # this object name specifically -- see that QSS block for why. Not
        # given to QListWidget in general, since a table or dialog list
        # with room to spare doesn't need the same emphasis.
        self.nav.setObjectName("navList")
        self.nav.setFrameShape(QListWidget.NoFrame)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Scrollbar as needed, set explicitly: below a certain window
        # height the sixteen destinations and six headings do not fit, and
        # the rail scrolls. The QSS below gives the scrollbar a handle with
        # enough contrast against the sidebar background to be seen, so
        # every destination is reachable at any window height (see
        # tests/test_sidebar.py).
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.nav.setFocusPolicy(Qt.NoFocus)
        self.nav.setContentsMargins(0, 0, 0, 0)
        self.nav.setUniformItemSizes(False)
        self.nav.viewport().setContentsMargins(0, 4, 0, 4)
        for section, items in nav_sections:
            if section:
                self._add_section(section)
            for key, label, _caveat in items:
                self._add_row(key, label)
        root.addWidget(self.nav, 1)
        # rangeChanged signals that the scrollbar's need changed (min ==
        # max: nothing to scroll, and Qt.ScrollBarAsNeeded hides it), so the
        # row reserve follows live resizes (see _update_scrollbar_reserve
        # and _SCROLLBAR_RESERVE_PX). Applied once at the start as well.
        self.nav.verticalScrollBar().rangeChanged.connect(
            self._update_scrollbar_reserve)
        self._update_scrollbar_reserve()

        # -- theme switcher pill ------------------------------------------
        pill_wrap = QVBoxLayout()
        pill_wrap.setContentsMargins(12, 10, 12, 12)
        self._pill_wrap = pill_wrap
        self.theme_pill = QPushButton()
        self.theme_pill.setFlat(True)
        self.theme_pill.setFixedHeight(32)
        self.theme_pill.setCursor(QCursor(Qt.PointingHandCursor))
        self.theme_pill.setObjectName("themePill")
        self.theme_pill.clicked.connect(self.themeToggleRequested.emit)
        pill_wrap.addWidget(self.theme_pill)

        self.collapse_button = QPushButton()
        self.collapse_button.setObjectName("sidebarCollapse")
        self.collapse_button.setFlat(True)
        self.collapse_button.setFixedHeight(28)
        self.collapse_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.collapse_button.clicked.connect(
            lambda: self.set_collapsed(not self._collapsed))
        pill_wrap.addWidget(self.collapse_button)

        root.addLayout(pill_wrap)

        self.refresh_theme()

    # --- construction helpers ---------------------------------------------

    def _add_section(self, title):
        item = QListWidgetItem()
        item.setFlags(Qt.NoItemFlags)
        item.setSizeHint(QSize(SIDEBAR_WIDTH - 16, _SECTION_HEIGHT))
        self.nav.addItem(item)
        self._section_items.append(item)
        header = _SectionHeader(title)
        self.nav.setItemWidget(item, header)
        self._headers.append(header)

    def _add_row(self, key, label):
        item = QListWidgetItem()
        item.setData(Qt.UserRole, key)
        item.setSizeHint(QSize(SIDEBAR_WIDTH - 16, _ROW_HEIGHT))
        self.nav.addItem(item)
        row = NavRow(key, label, NAV_ICONS.get(key, "grid"))
        row.set_dormant(self._dormant)
        self.nav.setItemWidget(item, row)
        self._rows[key] = row

    def _update_scrollbar_reserve(self, *_range):
        """min == max means the nav has nothing to scroll -- the same
        condition Qt.ScrollBarAsNeeded itself uses to hide the scrollbar
        -- so this stays in lockstep with the scrollbar's own visibility
        without depending on whichever order Qt happens to update
        isVisible() versus emit rangeChanged() in. `*_range` absorbs
        rangeChanged's (minimum, maximum) when called as a slot; the
        explicit no-arg call right after construction (Sidebar.__init__)
        re-reads the scrollbar's own current range instead.
        """
        vscroll = self.nav.verticalScrollBar()
        active = vscroll.maximum() > vscroll.minimum()
        for row in self._rows.values():
            row.set_scrollbar_reserve(active)

    # --- public API ----------------------------------------------------

    def set_current(self, key):
        for i in range(self.nav.count()):
            item = self.nav.item(i)
            k = item.data(Qt.UserRole)
            row = self._rows.get(k)
            if row is not None:
                row.set_selected(k == key)

    def set_count(self, key, value, unit=""):
        row = self._rows.get(key)
        if row is not None:
            row.set_count(format(value, ",") if isinstance(value, int)
                          else str(value), unit)

    def set_no_count(self, key):
        row = self._rows.get(key)
        if row is not None:
            row.set_no_count()

    def count_of(self, key):
        """(text, unit) a row's badge shows, or None. Read by the offline
        report, so its badges match this sidebar."""
        row = self._rows.get(key)
        if row is None:
            return None
        return (getattr(row, "_count_text", "") or "",
                getattr(row, "_count_unit", "") or "")

    def set_loaded(self, loaded):
        """Flips every nav row (never the brand or Open Database) between
        the dimmed pre-evidence look and its real, countable state -- see
        NavRow.set_dormant. Called once by MainWindow on the first
        successful Open Evidence."""
        self._dormant = not loaded
        for row in self._rows.values():
            row.set_dormant(self._dormant)

    def set_collapsed(self, collapsed):
        """Every row keeps its icon, its tooltip (name and count) and
        its right-click Copy; section headings, names, badges and the
        brand words fold away."""
        self._collapsed = bool(collapsed)
        self.setFixedWidth(SIDEBAR_COLLAPSED_WIDTH if self._collapsed
                           else SIDEBAR_WIDTH)
        self._brand_title.setVisible(not self._collapsed)
        self._brand_subtitle.setVisible(not self._collapsed)
        for item in self._section_items:
            item.setHidden(self._collapsed)
        # Each item's width follows the strip, so its icon is laid out
        # inside it.
        item_width = (SIDEBAR_COLLAPSED_WIDTH if self._collapsed
                      else SIDEBAR_WIDTH - 16)
        for i in range(self.nav.count()):
            item = self.nav.item(i)
            item.setSizeHint(QSize(item_width, item.sizeHint().height()))
        for row in self._rows.values():
            row.set_compact(self._collapsed)
        self.nav.doItemsLayout()
        # The foot and the Open button: narrower margins and no QSS
        # padding in the strip, or a 28 px button has -6 px for its glyph.
        side = 8 if self._collapsed else 12
        self._button_row.setContentsMargins(side, 0, side, 12)
        self._pill_wrap.setContentsMargins(side, 10, side, 12)
        for button in (self.open_button, self.collapse_button, self.theme_pill):
            theme.set_compact(button, self._collapsed)
        self._paint_open_button()
        self._paint_pill()
        self._paint_collapse_button()
        self.collapsedChanged.emit(self._collapsed)

    def _paint_open_button(self):
        """Its folder icon in the strip, its words when expanded. Also
        called from refresh_theme, so the icon takes the new palette's
        colour."""
        self.open_button.setText("" if self._collapsed else "Open Database")
        self.open_button.setToolTip("Open Database" if self._collapsed else "")
        self.open_button.setIcon(
            glyphs.icon("folder", theme.color("on_primary"), 16)
            if self._collapsed else QIcon())

    def is_collapsed(self):
        return self._collapsed

    def _paint_collapse_button(self):
        # A drawn chevron in the strip: needs no font, legible at any size.
        self.collapse_button.setIcon(
            glyphs.icon("chevron_right", theme.color("primary"), 16)
            if self._collapsed else QIcon())
        self.collapse_button.setText("" if self._collapsed else "«  Collapse")
        # Sized from its own words: never narrower than
        # the label plus the stylesheet's side padding. 0 in the strip,
        # where the icon alone sizes it.
        self.collapse_button.setMinimumWidth(
            0 if self._collapsed else
            self.collapse_button.fontMetrics().horizontalAdvance(
                self.collapse_button.text()) + 2 * 12 + 4)
        self.collapse_button.setToolTip(
            "Expand the sidebar" if self._collapsed
            else "Collapse the sidebar to icons")

    def refresh_theme(self):
        """Repaint what this widget draws itself rather than through QSS
        (drawn icons and inline per-row colours) after apply() has switched
        PALETTES. QSS-owned parts repaint when
        QApplication.setStyleSheet() runs."""
        # The application's own mark, distinct from the "shield" glyph the
        # Findings and Integrity rows use. The hole colour is the sidebar's
        # background.
        self._brand_icon.setPixmap(icon.mark_pixmap(
            20, theme.color("primary"), theme.color("window")))
        for row in self._rows.values():
            row.refresh_theme()
        for header in self._headers:
            header.refresh_theme()
        self._paint_open_button()
        self._paint_pill()
        self._paint_collapse_button()

    def _paint_pill(self):
        # worded as the action it performs, not as a status ("Emerald
        # · dark" read like a label); the current theme is in the tooltip.
        target = "light" if theme.current_name() == "dark" else "dark"
        icon = glyphs.icon("moon", theme.color("primary"), 14)
        self.theme_pill.setIcon(icon)
        self.theme_pill.setToolTip("Switch to the %s theme (current: %s)"
                                   % (target, theme.current_label()))
        self.theme_pill.setText("" if self._collapsed
                                else "  Switch to %s theme" % target)
        p = dict(theme.PALETTES[theme.current_name()])
        # Its own sheet outranks the app's QPushButton[compact] rule, so
        # the strip's no-padding, centred icon is said here as well.
        p["pad"], p["align"] = (("0px", "center") if self._collapsed
                                else ("0 10px", "left"))
        self.theme_pill.setStyleSheet("""
            QPushButton#themePill {
                background: %(alt_base)s; border: 1px solid %(border)s;
                border-radius: 6px; padding: %(pad)s; text-align: %(align)s;
                font-size: 11.5px; color: %(text)s;
            }
            QPushButton#themePill:hover { border: 1px solid %(primary)s; }
            QPushButton#themePill:focus { border: 2px solid %(primary)s; }
        """ % p)
