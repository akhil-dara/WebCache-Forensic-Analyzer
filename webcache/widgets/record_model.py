"""The table model: roles in, rows out.

Which rows, and in what order, is decided in record_filter.py, in plain
Python. This class maps the surviving rows onto Qt roles and publishes
resets.

QTableView builds delegates only for the rows on screen, so a 100,000-row
table costs the same to display as a 20-row one.
"""
import datetime
import functools
import time
import types

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (QApplication, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem)

from ..provenance import (AGGREGATE_MIXED, AGGREGATE_RECOVERED,
                          CONTAINER_NOT_DETERMINABLE, NOT_A_RECORD,
                          row_origin_label)
from ..shell import glyphs, theme
from . import copyable, time_format
from .column_spec import display_text
from .record_filter import RecordFilter

#: The raw, untouched value -- for Explain, copy and export.
ROLE_RAW = Qt.UserRole
#: The whole row dict -- for the detail dialog and drill-through callbacks.
ROLE_ROW = Qt.UserRole + 1
#: True/False, cheaply, for a view or delegate that wants a non-colour
#: carved indicator (a glyph, a row decoration) rather than relying on the
#: ForegroundRole colour alone. See the ForegroundRole branch in data():
#: colour carries the same signal, but colour alone is not a guaranteed
#: carrier -- colour-vision deficiency, a greyscale print of a screenshot,
#: or a high-contrast theme can all erase a colour-only distinction.
ROLE_IS_CARVED = Qt.UserRole + 2

# Carved rows keep the live text colours and carry a `carved_row`
# background tint, the "Carved" origin label and an amber edge on the
# origin cell.
#
# Colours are read through theme.color(), never baked in at import time,
# so a theme switch applies.
#
# foreground() caches the QColor per role and theme: data() runs for every
# visible cell on every repaint, and a full repaint (each filter
# keystroke, sort or clear) can request it hundreds of times. The cache is
# keyed by theme name, which is sufficient because a palette is never
# modified while its name is current.
_fg_cache = {}
_fg_cache_name = None


def foreground(role):
    """The QColor for one styling role, cached per theme.

    Public: the record detail dialog paints a carved record's values in
    the same colours, so the grid and the dialog share one colour source
    and change together on a theme switch.
    """
    global _fg_cache_name
    name = theme.current_name()
    if name != _fg_cache_name:
        _fg_cache.clear()
        _fg_cache_name = name
    color = _fg_cache.get(role)
    if color is None:
        color = theme.color(role)
        _fg_cache[role] = color
    return color

#: The vertical header's DisplayRole for a carved row: a marker that does
#: not rely on colour. It is on the row axis, so no column operation (hide,
#: reorder, sort, resize) can remove it.
#:
#: The leading origin column states the origin in words on every row.
ORIGIN_LABEL_LIVE = "Live"
ORIGIN_LABEL_CARVED = "Carved"
#: an aggregate row's own words, derived from its members.
ORIGIN_LABEL_MIXED = AGGREGATE_MIXED
ORIGIN_LABEL_RECOVERED = AGGREGATE_RECOVERED
#: A row that is neither a record nor a population of records.
ORIGIN_LABEL_NONE = NOT_A_RECORD
#: Every label a row can carry, for the header's width floor.
ORIGIN_LABELS_RECORD = (ORIGIN_LABEL_LIVE, ORIGIN_LABEL_CARVED)
ORIGIN_LABELS_AGGREGATE = (ORIGIN_LABEL_LIVE, ORIGIN_LABEL_MIXED,
                           ORIGIN_LABEL_RECOVERED, ORIGIN_LABEL_NONE)
MIXED_ROW_TOOLTIP = "An aggregate: some members are live, some recovered."
RECOVERED_ONLY_TOOLTIP = "An aggregate: every member was recovered (carved)."
NOT_A_RECORD_TOOLTIP = "Neither a record nor a population of records."
#: The column's heading, painted in the table's corner.
ORIGIN_HEADING = "Origin"
#: The live row's full sentence, for the tooltip and accessible text.
LIVE_ROW_TOOLTIP = "A live record, read from the database's own tables."
#: The unabbreviated fact, for AccessibleTextRole/AccessibleDescriptionRole
#: and the tooltip -- neither is pixel-constrained the way the header's own
#: rendered width is.
CARVED_ROW_TOOLTIP = ("Recovered from unallocated space or the transaction "
                       "log -- not a live record.")

#: What a link cell adds to its tooltip.
#:
#: Link cells (a Domain to the Domains view, a container name to its ESE
#: table) look like text, so the tooltip names both routes: double-click
#: opens what the value refers to, Ctrl+Enter opens the record the value
#: is on.
LINK_ACTIVATION_HINT = ("Double-click to follow this value. "
                        "Ctrl+Enter opens this record instead.")
#: What a copy-link cell adds to its tooltip: Location's MapsUrl/OsmUrl,
#: whose on_click copies the link rather than opening it (a map provider
#: is a third party, so the link is never opened). Ctrl+Enter still opens
#: the record. The cell reads as plain text with a copy glyph.
COPY_ACTIVATION_HINT = ("Double-click to copy this value. "
                        "Ctrl+Enter opens this record instead.")


@functools.lru_cache(maxsize=4)
def _copy_icon_for(theme_name):
    return glyphs.icon("copy", theme.color("muted"), 12)


def _copy_icon():
    return _copy_icon_for(theme.current_name())


def _format(value, numeric, kind=None):
    """A wrapper over column_spec.display_text, the one formatter shared
    by the grid, the search box, the value picker and every text filter
    operator. Keeps the (value, numeric, kind=...) signature by passing a
    lightweight stand-in for a Column."""
    return display_text(value, types.SimpleNamespace(kind=kind, numeric=numeric))


def _is_carved(row):
    return str(row.get("Origin", "")).startswith("Carved")


def paint_selection_bar(painter, option, index):
    """A 3px accent bar on the left edge of a selected row's first visible
    cell: the row is found by shape as well as by fill, on any tint."""
    if not option.state & QStyle.State_Selected:
        return
    widget = option.widget
    header = getattr(widget, "horizontalHeader", None)
    if header is not None and header().visualIndex(index.column()) != 0:
        return
    painter.save()
    painter.fillRect(option.rect.left(), option.rect.top(), 3,
                     option.rect.height(), theme.color("primary"))
    painter.restore()


class BackgroundRoleDelegate(QStyledItemDelegate):
    """Paints Qt.BackgroundRole itself, before the style paints the item.

    Once the application's QSS defines any rule for `QTableView::item`
    (theme.py's padding/border-bottom rule), QStyleSheetStyle paints
    CE_ItemViewItem itself and ignores the model's Qt.BackgroundRole.
    ForegroundRole still works, because it flows through the palette.

    So the role's colour is filled first, and the rest of the paint
    (padding, border, selection, text) is left to the style.
    `opt.backgroundBrush` is cleared to NoBrush so the style's background
    handling cannot paint over the fill.
    """

    def paint(self, painter, option, index):
        # initStyleOption FIRST and its backgroundBrush used for the fill:
        # it already asked the model for BackgroundRole, and asking again
        # here doubled that role on every painted cell.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        bg = opt.backgroundBrush
        if bg.style() != Qt.NoBrush:
            painter.save()
            painter.fillRect(option.rect, bg)
            painter.restore()
        opt.backgroundBrush = QBrush(Qt.NoBrush)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        paint_selection_bar(painter, option, index)


class RecordTableModel(QAbstractTableModel):
    """Wraps list[dict] rows behind a RecordFilter."""

    #: Emitted after any reset, for views that show a count line.
    layoutRefreshed = Signal()

    def __init__(self, columns, rows, parent=None):
        super().__init__(parent)
        self.columns = list(columns)
        self._origin_cache = {}
        #: Exposed on purpose. Reach for it read-only (e.g.
        #: visible(), .value_counts()) -- calling a MUTATING method
        #: (set_text, set_values, set_condition, clear_all, sort, set_rows)
        #: directly on .filter bypasses every reset-publishing wrapper below
        #: and leaves the view showing stale rows with no signal telling it
        #: to repaint. Go through the model's own same-named methods instead.
        self.filter = RecordFilter(rows, self.columns)
        for name in ("set_text", "set_values", "set_condition", "set_post",
                     "set_column_filter", "clear_all"):
            setattr(self, name, self._publishing(getattr(self.filter, name)))
        #: Bumped on every row-set change, so a prebuild chain started for
        #: an earlier row set stops at its next step.
        self._prebuild_generation = 0
        self._schedule_haystack_prebuild()

    # --- idle haystack prebuild -------------------------------------------

    def _schedule_haystack_prebuild(self):
        """Build the search haystack in idle steps of
        RecordFilter.HAYSTACK_CHUNK rows, one zero-delay timer each, so the
        first keystroke does not build all of it at once (132-179 ms at
        20k rows, un-debounced). Each step yields to the event loop; the
        model as the timer's context drops pending steps if it is
        destroyed first."""
        self._prebuild_generation += 1
        generation = self._prebuild_generation
        QTimer.singleShot(0, self, lambda: self._prebuild_step(generation, 0))

    #: Wall-clock budget for one idle step: small chunks are built until
    #: this much time has passed, then the step yields to the event loop.
    #: Time-sliced rather than a fixed row count, so each step does as much
    #: as it can without becoming a stall itself.
    PREBUILD_STEP_MS = 8.0

    def _prebuild_step(self, generation, start):
        if generation != self._prebuild_generation:
            return
        deadline = time.perf_counter() + self.PREBUILD_STEP_MS / 1000.0
        nxt = start
        while nxt is not None:
            nxt = self.filter.build_haystack_chunk(nxt, 250)
            if time.perf_counter() >= deadline:
                break
        if nxt is not None:
            QTimer.singleShot(
                0, self, lambda: self._prebuild_step(generation, nxt))

    def _publishing(self, fn):
        """Any filter change is a reset. Wrapping here means no caller can
        change the filter and forget to tell the view.

        try/finally guarantees endResetModel() always runs, even if `fn`
        raises -- e.g. set_rows fed malformed rows from a recovery scan
        merging carved records in mid-session. Without this, an exception
        would strand the model between beginResetModel() and
        endResetModel() forever: modelReset never fires, and any attached
        view is left showing stale or blank data with no error visible.
        The exception itself still propagates after cleanup; only the
        model's own bookkeeping is protected.
        """
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            self.beginResetModel()
            try:
                return fn(*args, **kwargs)
            finally:
                self.endResetModel()
                self.layoutRefreshed.emit()
        return wrapped

    # --- Qt interface ----------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.filter.visible_count

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    #: Roles this model never answers. A paint asks for every one of them
    #: on every cell; each is refused before the row lookup.
    _NEVER = frozenset({Qt.FontRole, Qt.CheckStateRole,
                        Qt.SizeHintRole, Qt.StatusTipRole, Qt.WhatsThisRole})

    #: The only roles the vertical (origin) header answers.
    _VERTICAL_HEADER_ROLES = frozenset({
        Qt.DisplayRole, ROLE_IS_CARVED, Qt.AccessibleTextRole,
        Qt.AccessibleDescriptionRole, Qt.ToolTipRole})

    def origin_label(self, row):
        """Live / Carved for a record; Live / Mixed / Recovered only for an
        aggregate, from its members; "\u2014" for a row that is neither. Cached
        by row identity: rows are never replaced in place, and an
        aggregate's members are counted once, not on every paint."""
        key = id(row)
        cached = self._origin_cache.get(key)
        if cached is not None and cached[0] is row:
            return cached[1]
        label = row_origin_label(row)
        # The row is kept beside its label so a recycled id() can never
        # serve another row's answer.
        self._origin_cache[key] = (row, label)
        return label

    def _row_is_carved(self, row):
        if "Origin" in row:
            return _is_carved(row)
        return self.origin_label(row) == ORIGIN_LABEL_RECOVERED

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DecorationRole and index.isValid():
            # A copy-only link reads as text with a copy glyph: the only
            # decoration any cell carries.
            col = self.columns[index.column()]
            if col.on_click_copies and col.is_link:
                return _copy_icon()
            return None
        if role in self._NEVER or not index.isValid():
            return None
        col = self.columns[index.column()]
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if col.numeric else None
        row = self.filter.visible()[index.row()]
        value = row.get(col.key)

        if role == Qt.DisplayRole:
            # The real Column, not _format's per-call SimpleNamespace
            # stand-in: this runs for every painted cell.
            return display_text(value, col)
        if role == ROLE_RAW:
            return value
        if role == ROLE_ROW:
            return row
        if role == ROLE_IS_CARVED:
            return self._row_is_carved(row)
        if role == Qt.ToolTipRole:
            text = ("" if value is None
                    else time_format.tooltip_text(value)
                    if isinstance(value, datetime.datetime) else str(value))
            if col.is_link_for(row):
                # Appended even when the cell is empty: the record behind a
                # blank Domain is as openable as any other.
                #
                # The hint depends on what activating the cell does: follow
                # the value, or (Location's map links) copy it. This
                # application makes no network request, so a copy-only cell
                # is never described as opening a map.
                hint = (COPY_ACTIVATION_HINT if col.on_click_copies
                        else LINK_ACTIVATION_HINT)
                return copyable.literal_tooltip(
                    "%s\n\n%s" % (text, hint) if text else hint)
            basis = row.get(col.basis_key) if col.basis_key else None
            if basis:
                # this cell's own basis.
                text = "%s\n\nBasis: %s" % (text, basis)
            # Escaped: a value starting with a tag must not render as
            # markup in the tooltip (see copyable.literal_tooltip).
            return copyable.literal_tooltip(text)
        if role == Qt.ForegroundRole:
            # carved rows read as TEXT. The carved fact is carried by
            # BackgroundRole below, the "Carved" origin label and the
            # amber edge on the origin cell -- three carriers, none of
            # them the text colour.
            if col.is_link_for(row):
                # A copy-only link is text, not a link: nothing is
                # followed, so nothing is painted as followable.
                return (foreground("text") if col.on_click_copies
                        else foreground("url"))
            if value is None or value == "" or value == CONTAINER_NOT_DETERMINABLE:
                return foreground("muted")
            if col.kind in ("time", "time_local"):
                return foreground("time_text")
            return foreground("text")
        if role == Qt.BackgroundRole:
            return foreground("carved_row") if self._row_is_carved(row) else None
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Vertical:
            # Refused before the row lookup: a theme switch re-polishes the
            # application and asks every header for many roles per section,
            # so roles not answered here return early.
            if role not in self._VERTICAL_HEADER_ROLES:
                return None
            row = self.filter.visible()[section]
            label = self.origin_label(row)
            if role == Qt.DisplayRole:
                return label
            if role == ROLE_IS_CARVED:
                return label in (ORIGIN_LABEL_CARVED, ORIGIN_LABEL_RECOVERED)
            if role in (Qt.AccessibleTextRole, Qt.AccessibleDescriptionRole,
                        Qt.ToolTipRole):
                return {ORIGIN_LABEL_CARVED: CARVED_ROW_TOOLTIP,
                        ORIGIN_LABEL_MIXED: MIXED_ROW_TOOLTIP,
                        ORIGIN_LABEL_RECOVERED: RECOVERED_ONLY_TOOLTIP,
                        ORIGIN_LABEL_NONE: NOT_A_RECORD_TOOLTIP}.get(
                            label, LIVE_ROW_TOOLTIP)
            return None
        if role == Qt.DisplayRole:
            return self.columns[section].label
        if role == Qt.ToolTipRole:
            c = self.columns[section]
            text = c.field or c.key
            if c.badge_tooltip:
                text = "%s \u2014 %s\n\n%s" % (
                    c.label, text, c.badge_tooltip)
            if c.note:
                text = "%s\n\n%s" % (text, c.note)
            said = self.column_filter_text(c.key)
            if said:
                text = ("%s\n\nFiltered: %s\nRight-click the heading to "
                        "change it." % (text, said))
            return text
        return None

    def column_filter_text(self, key):
        """What filters column KEY, in the grid's own words, or None when
        nothing does -- the heading's mark and tooltip read this."""
        said = []
        cond = self.filter.condition_for(key)
        if cond is not None:
            column = next((c for c in self.columns if c.key == key), None)
            said.append(cond.describe(column))
        allowed = self.filter.allowed_values(key)
        if allowed is not None:
            n = len(allowed)
            said.append("%s %s ticked" % (format(n, ","),
                                          "value" if n == 1 else "values"))
        return "; ".join(said) or None

    # --- convenience -----------------------------------------------------

    def row_at(self, index_row):
        return self.filter.visible()[index_row]

    def column_at(self, index_col):
        return self.columns[index_col]

    def value_counts(self, key):
        return self.filter.value_counts(key)

    # --- the Origin column's own filter -----------------------------------

    #: The post-filter key the Origin filter is held under. Not a column:
    #: Origin is the vertical header, labelled per row by origin_label.
    ORIGIN_KEY = "_origin"

    def origin_counts(self):
        """[(label, rows)] over EVERY row, in the order labels first appear
        -- what the heading's menu offers, whatever is filtered now."""
        counts = {}
        for row in self.filter.rows:
            label = self.origin_label(row)
            counts[label] = counts.get(label, 0) + 1
        return list(counts.items())

    def origin_filter(self):
        """The origin labels kept, or None when Origin is not filtered."""
        fn = self.filter.post_for(self.ORIGIN_KEY)
        return getattr(fn, "allowed", None)

    def set_origin_filter(self, allowed):
        """Keep only rows whose painted origin label is in `allowed`; None
        clears it. Matches the label the grid shows, so the filter and the
        column can never disagree."""
        sentences = self.filter.sentences
        if allowed is None:
            sentences.pop(self.ORIGIN_KEY, None)
            self.set_post(self.ORIGIN_KEY, None)
            return
        allowed = frozenset(allowed)

        def keep(rows):
            return [r for r in rows if self.origin_label(r) in allowed]
        keep.allowed = allowed
        order = [label for label, _n in self.origin_counts()]
        named = [label for label in order if label in allowed]
        sentences[self.ORIGIN_KEY] = (
            keep, "Origin: Is %s" % " or ".join(named) if named
            else "Origin: none selected (matches nothing)")
        self.set_post(self.ORIGIN_KEY, keep)

    def chip_text(self):
        return self.filter.chip_text()

    def sort_by(self, key, descending=False):
        self._publishing(self.filter.sort)(key, descending)

    def set_rows(self, rows):
        self._publishing(self.filter.set_rows)(rows)
        self._schedule_haystack_prebuild()

    def refresh(self):
        """Republish after the caller has changed the filter."""
        self._republish()

    def _republish(self):
        self.beginResetModel()
        self.endResetModel()
        self.layoutRefreshed.emit()
