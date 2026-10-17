"""The application palette, as a QPalette plus the application's QSS.

Emerald on near-black.

PALETTES["dark"] holds the design's "emerald-dark" values (a #30363D
border, a #8B949E muted text, and so on). The "light" palette is a tuned
analogue of the dark values, held to the same contrast and role tests.

Applying a theme sets the QPalette and the stylesheet; both are needed.
current_label() reads back what was applied, not what was requested.
"""
import tempfile
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from . import glyphs

#: Where the combo-box drop-down arrow glyphs (see _ensure_combo_arrow_assets
#: below) get painted to disk. QSS `image: url(...)` needs a real file Qt
#: can load from -- this app ships no QtSvg/shipped asset files (see
#: glyphs.py's own module docstring on why) -- so glyphs.pixmap's own
#: chevron_down glyph is written out here once per colour instead. A plain
#: OS temp directory, not paths.app_dir(): app_dir() can be a read-only
#: install directory under a frozen build, and this is disposable render
#: output, not case data.
_ASSET_DIR = Path(tempfile.gettempdir()) / "webcache-qt-theme-assets"


def _combo_arrow_path(color_hex):
    """A filename keyed by colour, not theme name, so a retuned palette
    references a new file rather than a stale one. String arithmetic only,
    so it is safe at import time while PALETTES is built, before any
    QApplication exists."""
    return (_ASSET_DIR / ("combo_arrow_%s.png" % color_hex.lstrip("#").lower())).as_posix()


def _dash_mark_path(color_hex):
    """The dash drawn inside a partly-selected box."""
    return (_ASSET_DIR / ("dash_%s.png" % color_hex.lstrip("#").lower())).as_posix()


def _check_mark_path(color_hex):
    """Like _combo_arrow_path: the tick drawn inside a checked box, keyed
    by the colour it is painted in."""
    return (_ASSET_DIR / ("check_%s.png" % color_hex.lstrip("#").lower())).as_posix()


PALETTES = {
    "dark": {
        # -- Core surfaces, darkest to lightest --
        "window": "#0D1117",         # C_BG -- the outermost background
        "base": "#161B22",           # C_SURFACE -- sidebar, cards, table body
        "alt_base": "#1C2333",       # C_SURFACE2 -- selected nav row, header row
        "surface3": "#252D3A",       # C_SURFACE3 -- badge/chip fill
        "row_alt": "#131920",        # C_ROW_ALT -- the table's zebra stripe
        "border": "#30363D",         # C_BORDER

        # -- Accents --
        # timestamps get their own role (WCAG AA 4.5:1 on base,
        # row_alt and carved_row); on dark it is the accent itself (10:1).
        "time_text": "#00E59E",
        "primary": "#00E59E",        # C_ACCENT -- emerald; the one identity colour
        # Emerald as TEXT. Equal to primary here; the light theme needs a
        # darker one (its primary is 2.8-3.2:1 on its own surfaces).
        "primary_text": "#00E59E",
        # Text on emerald (filled buttons, selected text): dark in both
        # themes, for contrast on the green.
        "on_primary": "#0D1117",
        "secondary": "#00B87A",      # C_ACCENT_DIM
        "url": "#58A6FF",            # C_ACCENT2 -- links, URLs, references
        "warn": "#F0883E",           # C_WARN
        "error": "#F85149",          # C_DANGER
        "carved": "#D29922",         # C_GOLD -- the carved/deleted-record family
        # A filled, low-saturation green wash -- used by the "Local files
        # only" filled quick-filter chip. Distinct from "primary" itself:
        # this is a SURFACE colour something sits on top of, not a mark
        # drawn in emerald.
        "success_bg": "#17251F",
        # record_model.py's carved-cell variants: a carved cell that is
        # ALSO a link (brighter amber-gold, never the live link's blue --
        # a carved record must never be styled to look like a live
        # drill-through) and a carved cell that is blank (a muted, dark
        # amber, so it never collapses into the plain grey used for a
        # blank LIVE cell). Both stay in the same amber/gold family as
        # "carved" itself -- see record_model.py's own module docstring
        # on why the HUE is the carried signal, not the exact shade.
        "carved_link": "#E0B15C", "carved_blank": "#8A6A2E",
        # a carved row's background. Subtle on purpose: the text on it
        # is the normal text colour; the tint, the "Carved" origin label
        # and the amber edge carry the fact together.
        "carved_row": "#241F14",
        # a row Table Browser LANDED on. The accent at 30% over the
        # table body: 2.07:1 against base, 2.11:1 against row_alt, and
        # the normal text on it at 7.1:1. alt_base, the everyday
        # selection, is 1.1:1 -- a row an examiner cannot find.
        "row_selected": "#0F5847",

        # -- Text --
        "text": "#E6EDF3",           # C_TEXT
        "muted": "#8B949E",          # C_TEXT2
        "muted2": "#848B96",         # C_TEXT3 -- the tightest prose surface (caveats)

        # Tooltip panel: the app's own secondary surface/text, not Qt's
        # platform default (a pale system-yellow panel against this
        # near-black window would look broken, not themed).
        "tooltip_base": "#161B22", "tooltip_text": "#E6EDF3",
        # Links: the theme's own accents, so a stock Qt hyperlink is never
        # rendered in Qt's default blue either.
        "link": "#58A6FF", "link_visited": "#00B87A",
        # Disabled group: dim but legible against #0D1117, so a disabled
        # control (e.g. Open Evidence mid-load) reads as unavailable.
        "disabled_text": "#4B5560", "disabled_highlight": "#1D2A26",
    },
    "light": {
        "window": "#F5F7FA", "base": "#FFFFFF", "alt_base": "#EAF3EE",
        "surface3": "#DCE8E2", "row_alt": "#EFF6F1", "border": "#D3DAE3",

        # 6.1:1 on white, 5.6:1 on row_alt, 5.5:1 on carved_row.
        "time_text": "#00704E",
        "primary": "#00A472", "primary_text": "#00704E", "on_primary": "#101418", "secondary": "#0E8C7C", "url": "#1A5FB4",
        "warn": "#9A6500", "error": "#B3242C", "carved": "#9A6500",
        "success_bg": "#E3F3EA",
        "carved_link": "#8A5A00", "carved_blank": "#6B5220",
        "carved_row": "#FBF3E1",
        # 1.98:1 against base, 1.80:1 against row_alt, 1.79:1 against
        # carved_row; text on it 9.35:1.
        "row_selected": "#6FC9AB",

        "text": "#101418", "muted": "#5B6570", "muted2": "#5B7081",

        "tooltip_base": "#EAF3EE", "tooltip_text": "#101418",
        "link": "#1A5FB4", "link_visited": "#0E8C7C",
        "disabled_text": "#A2ABB4", "disabled_highlight": "#D7EBE2",
    },
}

# Every palette also carries its own combo-drop-down arrow
# paths, keyed off that SAME palette's text/disabled_text colours -- see
# _combo_arrow_path's docstring. Static string values only (no QPixmap
# built here), so this is safe at import time; _ensure_combo_arrow_assets
# is what actually paints the files, and only apply() ever calls it.
for _pal in PALETTES.values():
    _pal["combo_arrow"] = _combo_arrow_path(_pal["text"])
    _pal["combo_arrow_disabled"] = _combo_arrow_path(_pal["disabled_text"])
    _pal["check_mark"] = _check_mark_path(_pal["window"])
    _pal["dash_mark"] = _dash_mark_path(_pal["window"])
del _pal

_current = "dark"
#: The app instance apply() last succeeded against, alongside _current;
#: both must match for a call to be skipped (see apply()).
_last_applied_app = None


def color(role, name=None):
    return QColor(PALETTES[name or _current][role])


def current_label():
    return "Emerald · %s" % _current


def current_name():
    """The key into PALETTES that current_label()/color() are reading --
    "dark" or "light". Public, unlike _current itself, so a caller that
    needs the whole palette dict (sidebar.py's theme pill, painting its own
    QSS fragment) does not have to reach past the module's own leading
    underscore to get it."""
    return _current


#: The real, application-wide QSS. Formatted against one palette's dict, so
#: every %(role)s below resolves to that theme's own hex string.
#:
#: QSS is not CSS: there is no box-shadow, no gap, no flexbox. A design that
#: leans on an inset box-shadow for a selected nav row's left accent bar
#: (see sidebar.py) is approximated here with a real `border-left` instead
#: -- it shifts row content by the border's own width rather than painting
#: on top of it the way an inset shadow would, which is the closest QSS
#: gets.
_STYLESHEET = """
    QMainWindow, QDialog {
        background: %(window)s;
    }
    QWidget {
        color: %(text)s;
        selection-background-color: %(primary)s;
        selection-color: %(on_primary)s;
    }
    QToolTip {
        background: %(tooltip_base)s;
        color: %(tooltip_text)s;
        border: 1px solid %(border)s;
        padding: 5px 8px;
        border-radius: 4px;
    }

    QMenuBar {
        background: %(window)s;
        color: %(text)s;
        border-bottom: 1px solid %(border)s;
        padding: 2px;
    }
    QMenuBar::item {
        background: transparent;
        padding: 4px 10px;
        border-radius: 4px;
    }
    QMenuBar::item:selected, QMenuBar::item:pressed {
        background: %(alt_base)s;
    }
    QMenu {
        background: %(base)s;
        color: %(text)s;
        border: 1px solid %(border)s;
        padding: 4px;
    }
    QMenu::item {
        padding: 6px 26px 6px 14px;
        border-radius: 4px;
    }
    QMenu::item:selected {
        background: %(alt_base)s;
        color: %(text)s;
    }
    QMenu::item:disabled {
        color: %(disabled_text)s;
    }
    QMenu::separator {
        height: 1px;
        background: %(border)s;
        margin: 4px 8px;
    }

    /* The nav rail. Rows are drawn by sidebar.py's own item widgets; this
       QSS only owns the selection/hover background so it shows through a
       transparent row widget -- see sidebar.py's module docstring for why
       that split, not QSS alone, is what draws a nav row. */
    QListWidget, QListView#valueList {
        background: %(base)s;
        border: none;
        outline: 0;
    }
    /* Room for the focus ring: Qt does not re-lay out a frame when
       :focus adds a border to a borderless list, so the ring never drew.
       The nav list and the Open dialog's file list take no focus and keep
       no border. */
    QListView#valueList, QListWidget {
        border: 2px solid transparent;
    }
    QListWidget#navList, QListWidget#scopeList {
        border: none;
    }
    /* A scroll area that is a Tab stop because arrow and Page keys scroll
       it (the Headers pane, the Export page): the same reserved ring. */
    QScrollArea#keyScroll {
        border: 2px solid transparent;
    }
    QScrollArea#keyScroll:focus {
        border: 2px solid %(primary)s;
    }
    /* Typed into (case notes) or selected by keyboard (the hex dump). */
    QPlainTextEdit {
        background: %(window)s;
        color: %(text)s;
        border: 1px solid %(border)s;
        border-radius: 6px;
        selection-background-color: %(primary)s;
        selection-color: %(on_primary)s;
    }
    QPlainTextEdit:focus {
        border: 1px solid %(primary)s;
    }
    QListWidget::item {
        border: none;
        border-left: 2px solid transparent;
        border-radius: 6px;
        padding: 0px;
    }
    QListWidget::item:selected {
        background: %(alt_base)s;
        border-left: 2px solid %(primary)s;
        /* Its own colour: otherwise the global selection-color (the
           window colour) wins, and Table Browser's selected table name
           was dark on dark. The nav rail paints its own row widgets. */
        color: %(text)s;
    }
    QListWidget::item:hover:!selected {
        background: %(row_alt)s;
    }
    /* The Open dialog's file list: rows are toggled, never selected, so
       the list itself paints no hover or selection; the row's own frame
       carries one hover cue. */
    QListWidget#scopeList::item,
    QListWidget#scopeList::item:hover,
    QListWidget#scopeList::item:selected {
        background: transparent;
        border: none;
    }
    QFrame#scopeRow {
        border-radius: 6px;
        background: transparent;
    }
    QFrame#scopeRow:hover {
        background: %(row_alt)s;
    }

    /* The filter popup. Its value list must not inherit the nav
       rail's accent bar, and its hovered/selected text keeps full
       contrast -- the global selection-color is the window colour, which
       is dark text on a dark selection in this list. */
    QDialog#filterPopup {
        background: %(base)s;
        border: 1px solid %(border)s;
    }
    QFrame#filterTitle {
        background: %(alt_base)s;
        border-bottom: 1px solid %(border)s;
    }
    QDialog#filterPopup QListWidget::item,
    QDialog#filterPopup QListView#valueList::item {
        color: %(text)s;
        border: none;
        border-radius: 3px;
        padding: 2px 4px;
    }
    QDialog#filterPopup QListWidget::item:hover,
    QDialog#filterPopup QListView#valueList::item:hover {
        color: %(text)s;
        background: %(row_alt)s;
    }
    QDialog#filterPopup QListWidget::item:selected,
    QDialog#filterPopup QListView#valueList::item:selected {
        color: %(text)s;
        background: %(row_selected)s;
    }
    /* The only checkable QListWidget in the app is
       this popup's value list, and with no indicator rule at all it fell
       back to unstyled native rendering -- a ticked value showed a bare
       check mark and an unticked one showed nothing, no box outline, so
       "ticked" and "not a row at all" were indistinguishable. Same box
       language as QCheckBox::indicator below, so the two checkbox looks
       in the app agree. */
    QListWidget::indicator, QListView#valueList::indicator {
        width: 15px;
        height: 15px;
        border: 1.5px solid %(border)s;
        border-radius: 3px;
        background: %(window)s;
    }
    QListWidget::indicator:hover, QListView#valueList::indicator:hover {
        border: 1.5px solid %(primary)s;
    }
    QListWidget::indicator:checked,
    QListView#valueList::indicator:checked {
        background: %(primary)s;
        border: 1.5px solid %(primary)s;
        image: url(%(check_mark)s);
    }
    /* The popup's year/month/day tree -- same box language. */
    QTreeView::item {
        min-height: 24px;
    }
    QTreeView::indicator {
        width: 15px;
        height: 15px;
        border: 1.5px solid %(border)s;
        border-radius: 3px;
        background: %(window)s;
    }
    QTreeView::indicator:hover {
        border: 1.5px solid %(primary)s;
    }
    QTreeView::indicator:checked {
        background: %(primary)s;
        border: 1.5px solid %(primary)s;
        image: url(%(check_mark)s);
    }
    QTreeView::indicator:indeterminate {
        background: %(secondary)s;
        border: 1.5px solid %(secondary)s;
        image: url(%(dash_mark)s);
    }

    QHeaderView::section {
        background: %(alt_base)s;
        color: %(text)s;
        font-weight: 600;
        border: none;
        border-right: 1px solid %(border)s;
        border-bottom: 1px solid %(border)s;
        padding: 4px 9px;
    }
    /* Column headings: painted in theme.heading_font(), the size written
       here by apply() from the same definition RecordsTable's header
       measures with. Horizontal only -- the origin column's Live/Carved
       row labels keep the size they have always had. */
    QHeaderView::section:horizontal {
        font-size: @HEADING_PT@pt;
    }
    /* The header paints its own sort arrow in the left padding
       (records_table._ProvenanceHeaderView); the style's own arrow would
       take room from the label and meet the basis badge on the right. */
    QHeaderView::up-arrow, QHeaderView::down-arrow {
        image: none;
        width: 0px;
        height: 0px;
    }
    /* "Origin", painted in the corner: the heading size and weight too.
       Without them it took the button's own font, which a theme switch
       re-polishes to the 9 pt item-view font -- 12 pt at launch, 9 pt
       after either toggle (measured natively). */
    QTableCornerButton::section {
        font-size: @HEADING_PT@pt;
        font-weight: 600;
        background: %(alt_base)s;
        border: none;
        border-right: 1px solid %(border)s;
        border-bottom: 1px solid %(border)s;
    }
    QTableView {
        background: %(base)s;
        alternate-background-color: %(row_alt)s;
        gridline-color: transparent;
        border: 1px solid %(border)s;
        border-radius: 8px;
        outline: 0;
        selection-background-color: %(row_selected)s;
        selection-color: %(text)s;
    }
    QTableView::item {
        padding: 0px 9px;
        border-bottom: 1px solid %(alt_base)s;
    }
    /* EVERY grid: a selected row has to be FOUND (an alt_base selection
       measures 1.02-1.13:1 on base, zebra and carved tint). row_selected is 1.8-2.1:1 on all three; the delegate adds
       an accent bar on the first column. */
    QTableView::item:selected {
        background: %(row_selected)s;
        color: %(text)s;
    }
    /* Table Browser's grid also marks its row NUMBER. */
    QTableView#browserGrid::item:selected {
        background: %(row_selected)s;
        color: %(text)s;
    }
    QTableView#browserGrid QHeaderView::section:vertical:checked {
        background: %(row_selected)s;
        color: %(text)s;
    }

    QLineEdit {
        background: %(window)s;
        color: %(text)s;
        border: 1px solid %(border)s;
        border-radius: 6px;
        padding: 6px 10px;
        selection-background-color: %(primary)s;
        selection-color: %(on_primary)s;
    }
    QLineEdit:focus {
        border: 1px solid %(primary)s;
    }
    QLineEdit:disabled {
        color: %(disabled_text)s;
    }

    /* An enabled style for every combo box, in both themes. */
    QComboBox {
        color: %(text)s;
        background: %(window)s;
        border: 1px solid %(border)s;
        border-radius: 6px;
        padding: 5px 10px;
    }
    QComboBox:hover, QComboBox:focus {
        border: 1px solid %(primary)s;
    }
    QComboBox:disabled {
        color: %(disabled_text)s;
    }
    QComboBox::drop-down {
        border: none;
        width: 20px;
    }
    /* Once QSS touches ::drop-down at all, Qt drops
       its own native arrow glyph -- verified directly, the box painted
       with no arrow whatsoever, reading as a plain text field rather
       than a menu. image: url(...) needs a real file; see
       _ensure_combo_arrow_assets. */
    QComboBox::down-arrow {
        image: url(%(combo_arrow)s);
        width: 12px;
        height: 12px;
    }
    QComboBox::down-arrow:disabled {
        image: url(%(combo_arrow_disabled)s);
    }
    QComboBox QAbstractItemView {
        color: %(text)s;
        background: %(base)s;
        border: 1px solid %(border)s;
        selection-color: %(text)s;
        selection-background-color: %(alt_base)s;
        outline: 0;
    }

    QPushButton {
        background: %(alt_base)s;
        color: %(text)s;
        border: 1px solid %(border)s;
        border-radius: 6px;
        padding: 7px 16px;
    }
    QPushButton:hover {
        border: 1px solid %(primary)s;
    }
    QPushButton:pressed {
        background: %(border)s;
    }
    /* A toggle that is in force -- segment switchers, Wrap, Hide identical
       columns, the Timeline clock, Deleted Records' methods. Here, not
       per widget, so it follows every theme toggle. Before
       :focus, so the keyboard ring still shows on a checked button. */
    QPushButton:checked {
        background: %(success_bg)s;
        border: 1px solid %(secondary)s;
        /* The LABEL says "in force", not only the fill: a focus ring is
           brighter than this border, and beside an unchecked focused
           button the ring read as the choice. A ring never recolours a
           label. Colour only, never weight: Qt sizes a button from its
           unchecked font, so a bolder checked label clipped "Hide
           identical columns" and the first letter of a switcher. */
        color: %(primary_text)s;
    }
    QPushButton:checked:hover {
        border: 1px solid %(primary)s;
    }
    /* Where the keyboard is, always visible. */
    QPushButton:focus, QToolButton:focus, QCheckBox:focus,
    QComboBox:focus, QListWidget:focus, QTableView:focus,
    QListView#valueList:focus, QTreeWidget:focus {
        border: 2px solid %(primary)s;
    }
    QPushButton:disabled {
        color: %(disabled_text)s;
        border: 1px solid %(border)s;
        background: %(alt_base)s;
    }
    /* The one filled, emerald button style -- Open Database, Export,
       Hash and open. Selected with dynamic property "accent" (see
       widgets.py's button() helper), since plain QSS has no way to tell
       "this button is the primary action" from "this button is not". */
    QPushButton[accent="true"] {
        background: %(primary)s;
        color: %(on_primary)s;
        border: 1px solid %(primary)s;
        font-weight: 600;
    }
    QPushButton[accent="true"]:hover {
        background: %(secondary)s;
        border: 1px solid %(secondary)s;
    }
    QPushButton[accent="true"]:pressed {
        background: %(secondary)s;
    }
    QPushButton[accent="true"]:disabled {
        background: %(disabled_highlight)s;
        border: 1px solid %(disabled_highlight)s;
        color: %(disabled_text)s;
    }
    /* A second, quieter emphasis: the design's Export button -- an emerald
       border and label on the ordinary surface colour, not a filled
       button. Distinct dynamic property from "accent" so a button can be
       "the loud one" (Open Database, Hash and open) or "the noted one"
       (Export view) without the two ever being confused in a stylesheet
       selector. */
    QPushButton[outline="true"] {
        background: %(alt_base)s;
        color: %(primary_text)s;
        border: 1px solid %(secondary)s;
        font-weight: 600;
    }
    /* After the outline rule's own border, which would otherwise hide
       where the keyboard is. */
    QPushButton[outline="true"]:focus {
        border: 2px solid %(primary)s;
    }
    QPushButton[outline="true"]:hover {
        border: 1px solid %(primary)s;
    }
    QPushButton[outline="true"]:disabled {
        color: %(disabled_text)s;
        border: 1px solid %(border)s;
    }
    /* The Back button above the views: an ordinary secondary button,
       trimmed, with a ring when the keyboard has it. */
    QPushButton[navback="true"] {
        padding: 3px 12px;
    }
    QPushButton[navback="true"]:focus {
        border: 2px solid %(primary)s;
        padding: 2px 11px;
    }
    QPushButton[navback="true"]:disabled {
        color: %(disabled_text)s;
        border: 1px solid %(border)s;
        background: %(window)s;
    }
    /* A button squeezed to an icon (the collapsed sidebar's foot and Open
       buttons): the 16 px side padding above would leave a 28 px button
       less than no room for its glyph. */
    QPushButton[compact="true"] {
        padding: 0px;
    }
    /* The sidebar's Collapse button is 28 px tall: the 7 px padding above
       left its label 12 px of a 21 px line, cut at the top and bottom.
       Trimmed vertically only; the focus ring's 2 px
       border takes one pixel of padding back. */
    QPushButton#sidebarCollapse {
        padding: 2px 12px;
    }
    QPushButton#sidebarCollapse:focus {
        padding: 1px 11px;
    }
    QPushButton#sidebarCollapse[compact="true"] {
        padding: 0px;
    }
    /* The view header's Guide button is 28 px tall too; trimmed the
       same way so its label is not cut at the bottom. */
    QPushButton#headerHelp {
        padding: 2px 14px;
    }
    QPushButton#headerHelp:focus {
        padding: 1px 13px;
    }

    QCheckBox {
        color: %(text)s;
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 15px;
        height: 15px;
        border: 1.5px solid %(border)s;
        border-radius: 3px;
        background: %(window)s;
    }
    QCheckBox::indicator:hover {
        border: 1.5px solid %(primary)s;
    }
    QCheckBox::indicator:checked {
        background: %(primary)s;
        border: 1.5px solid %(primary)s;
        image: url(%(check_mark)s);
    }

    QCalendarWidget QTableView {
        border: none;
        background: %(base)s;
        selection-background-color: %(primary)s;
        selection-color: %(on_primary)s;
    }
    QCalendarWidget QAbstractItemView::item {
        padding: 0px;
        border: none;
    }
    QCalendarWidget QWidget#qt_calendar_navigationbar {
        background: %(base)s;
    }
    QCalendarWidget QToolButton {
        color: %(text)s;
        background: transparent;
        padding: 2px 6px;
    }

    QRadioButton {
        color: %(text)s;
        spacing: 8px;
    }
    QRadioButton::indicator {
        width: 14px;
        height: 14px;
        border: 1.5px solid %(muted)s;
        border-radius: 8px;
        background: %(window)s;
    }
    QRadioButton::indicator:hover {
        border: 1.5px solid %(primary)s;
    }
    QRadioButton::indicator:checked {
        border: 1.5px solid %(primary)s;
        background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5,
                                    fx: 0.5, fy: 0.5,
                                    stop: 0 %(primary)s, stop: 0.5 %(primary)s,
                                    stop: 0.56 %(window)s, stop: 1 %(window)s);
    }

    QScrollBar:vertical {
        background: transparent;
        width: 12px;
        margin: 2px 2px 2px 0px;
    }
    QScrollBar::handle:vertical {
        background: %(border)s;
        border-radius: 5px;
        min-height: 24px;
    }
    QScrollBar::handle:vertical:hover {
        background: %(muted)s;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 12px;
        margin: 0px 2px 2px 2px;
    }
    QScrollBar::handle:horizontal {
        background: %(border)s;
        border-radius: 5px;
        min-width: 24px;
    }
    QScrollBar::handle:horizontal:hover {
        background: %(muted)s;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
        background: transparent;
    }

    /* The nav's own scrollbar, scoped to sidebar.py's QListWidget#navList
       and overriding the ordinary vertical rule above. Not a cosmetic
       preference -- see NavRow/Sidebar's own comment: the ordinary
       handle colour (the "border" role) has almost no contrast against
       the sidebar background, and a scrollbar an examiner cannot see is
       not a real affordance for the two destinations, Integrity and
       Export & Report, that only exist below the fold at ordinary window
       heights. "muted" is the same grey this app already uses for
       ordinary label text against this exact background, so it is
       legible by construction rather than a new colour invented for
       this one rule. Wider too (10px vs 12px is barely different in
       absolute terms, but min-height is what actually matters here --
       a short handle on a nearly-full list reads as a sliver even at
       full contrast). */
    QListWidget#navList QScrollBar:vertical {
        background: transparent;
        width: 10px;
        margin: 4px 1px 4px 1px;
    }
    QListWidget#navList QScrollBar::handle:vertical {
        background: %(muted)s;
        border-radius: 4px;
        min-height: 32px;
    }
    QListWidget#navList QScrollBar::handle:vertical:hover {
        background: %(primary)s;
    }
    QListWidget#navList QScrollBar::add-line:vertical,
    QListWidget#navList QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QListWidget#navList QScrollBar::add-page:vertical,
    QListWidget#navList QScrollBar::sub-page:vertical {
        background: transparent;
    }

    QStatusBar {
        background: %(window)s;
        color: %(muted)s;
        border-top: 1px solid %(border)s;
    }
    QStatusBar::item {
        border: none;
    }

    QProgressBar {
        background: %(surface3)s;
        border: none;
        border-radius: 2px;
        max-height: 5px;
        min-height: 5px;
    }
    QProgressBar::chunk {
        background: %(primary)s;
        border-radius: 2px;
    }

    QSplitter::handle {
        background: %(border)s;
    }

    QScrollArea {
        background: transparent;
        border: none;
    }
"""


def _mark(widget, prop):
    """Set a dynamic QSS-selector property (see QPushButton[accent="true"]
    and [outline="true"] above) and make Qt re-evaluate the stylesheet for
    this widget immediately.

    setProperty() alone does not restyle a widget that is already
    polished, because the style caches which rules apply to it;
    unpolish()+polish() invalidates that cache for this one widget.
    """
    widget.setProperty(prop, True)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_compact(widget, on):
    """Turn QPushButton[compact="true"] (no padding) on or off for one
    button, re-polished at once -- see _mark."""
    widget.setProperty("compact", bool(on))
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def unmark(widget, prop):
    """Undo a _mark: the property off and the style re-evaluated."""
    widget.setProperty(prop, False)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def mark_accent(widget):
    """The one filled, emerald button style -- Open Database, Export
    (the sidebar/first-run one; the History view's own Export button uses
    mark_outline instead -- see theme's QSS comment on why there are two),
    Hash and open."""
    _mark(widget, "accent")


def mark_outline(widget):
    """The quieter emerald-border style -- see the QSS comment on
    QPushButton[outline="true"]."""
    _mark(widget, "outline")


#: Placeholder in _STYLESHEET for the heading size, filled by apply() from
#: heading_font() -- a token rather than a %-key so the palette dicts stay
#: the only thing _STYLESHEET is %-formatted with.
_HEADING_PT_TOKEN = "@HEADING_PT@"


def heading_font():
    """The font every table heading is painted and measured with.

    A style-sheet font is resolved against the application font
    (QFont("Segoe UI") is 12 pt in Qt 6), while a header widget's own
    font() reports the platform's 9 pt item-view font. Measuring one and
    painting the other would clip every heading.

    So one definition is used twice: apply() writes its point size and
    weight into the QHeaderView::section rule, and RecordsTable's header
    views setFont() it, so painted_font() and the width floor match what
    is painted. The size is set explicitly: a QFont copied from
    QFont("Segoe UI") leaves its size unresolved, and setFont() would keep
    the widget's 9 pt."""
    base = QApplication.font()
    font = QFont(base.family())
    size = base.pointSizeF()
    font.setPointSizeF(size if size > 0 else 9.0)
    font.setWeight(QFont.Weight.DemiBold)
    return font


def _heading_pt():
    return "%g" % heading_font().pointSizeF()


def apply(app, name="dark"):
    """Set the palette and the stylesheet; either alone leaves half the
    window in the previous theme.

    _current is written last, after both calls return, so if either raises
    current_label() still reports the theme on screen.

    A no-op when `app` already has `name` applied. QApplication.
    setStyleSheet() re-polishes every widget in the process, so repeating
    it for every MainWindow construction (as tests do) grows more
    expensive with each window still alive.

    Both _current and _last_applied_app must match: _current starts as
    "dark" when this module is imported, before apply() has run, so a
    check on the name alone would skip the first apply(app, "dark") and
    leave the platform default on screen. _last_applied_app is set with
    _current, after both calls return.
    """
    global _current, _last_applied_app
    if app is _last_applied_app and name == _current:
        return
    p = PALETTES[name]
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(p["window"]))
    pal.setColor(QPalette.Base, QColor(p["base"]))
    pal.setColor(QPalette.AlternateBase, QColor(p["row_alt"]))
    pal.setColor(QPalette.WindowText, QColor(p["text"]))
    pal.setColor(QPalette.Text, QColor(p["text"]))
    pal.setColor(QPalette.ButtonText, QColor(p["text"]))
    pal.setColor(QPalette.Button, QColor(p["alt_base"]))
    pal.setColor(QPalette.Highlight, QColor(p["primary"]))
    pal.setColor(QPalette.HighlightedText, QColor(p["on_primary"]))
    pal.setColor(QPalette.PlaceholderText, QColor(p["muted"]))
    pal.setColor(QPalette.ToolTipBase, QColor(p["tooltip_base"]))
    pal.setColor(QPalette.ToolTipText, QColor(p["tooltip_text"]))
    pal.setColor(QPalette.Link, QColor(p["link"]))
    pal.setColor(QPalette.LinkVisited, QColor(p["link_visited"]))
    # The Disabled group: without this, a disabled control (e.g.
    # open_evidence_action mid-load) falls back to Qt's platform default --
    # a grey picked for a light theme -- rendered against this near-black
    # emerald palette. Set explicitly so "disabled" reads as deliberate.
    disabled_text = QColor(p["disabled_text"])
    pal.setColor(QPalette.Disabled, QPalette.WindowText, disabled_text)
    pal.setColor(QPalette.Disabled, QPalette.Text, disabled_text)
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, disabled_text)
    pal.setColor(QPalette.Disabled, QPalette.Highlight,
                 QColor(p["disabled_highlight"]))
    app.setPalette(pal)
    _ensure_combo_arrow_assets(p)
    app.setStyleSheet((_STYLESHEET % p).replace(_HEADING_PT_TOKEN,
                                                _heading_pt()))
    _current = name
    _last_applied_app = app


def _ensure_combo_arrow_assets(p):
    """Paint the two combo-arrow PNGs `p["combo_arrow"]` and
    `p["combo_arrow_disabled"]` point at, if they are not on disk.

    Called only from apply(), which always has a live QApplication:
    constructing a QPixmap before one exists aborts the process. The paths
    are computed separately, as plain strings, while PALETTES is built
    (see _combo_arrow_path), because a QSS rule must reference the path
    before any QApplication exists, while the file itself need not exist
    yet.
    """
    for key, color_key, glyph, stroke in (
            ("combo_arrow", "text", "chevron_down", 2.0),
            ("combo_arrow_disabled", "disabled_text", "chevron_down", 2.0),
            ("check_mark", "window", "check", 2.2),
            ("dash_mark", "window", "dash", 2.4)):
        path = Path(p[key])
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        pixmap = glyphs.pixmap(glyph, QColor(p[color_key]),
                               size=12, stroke=stroke)
        pixmap.save(str(path), "PNG")
