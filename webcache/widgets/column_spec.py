"""One grid column, declared by a view.

Carried over from ui_grid.Column with its full signature. The two attributes
an earlier design draft dropped are the two that matter most: on_click is
every drill-through in the application, and numeric decides whether a column
sorts as a number or as text.

Width is QHeaderView's job, so no width arithmetic lives here.
"""
import datetime

from .time_format import format_dt

from ..spellings import other_spellings

#: Valid column kinds. Drive colour, alignment, sort key, and which filter
#: operators the popup offers for the column.
#:
#: "path" is a local file path (File Access's "Local file path" and "Saved
#: to"). Not "url": a path is never styled as a link (record_model.py keys
#: links off Column.is_link/on_click, which a path column never sets), and
#: a location on the examined machine is copied, never opened. It filters
#: like any other string field (record_filter.OPERATORS_BY_KIND).
#: "bar" is the one drawn kind: a 0..1 share, painted by widgets/
#: bar_delegate.ShareBarDelegate rather than printed. Not in the numeric
#: set below, which would thousands-separate and right-align it; it
#: filters with the numeric operators (">= 0.5" is a real filter).
#: "offset" is a byte position (a carved record's Offset). Numeric for
#: sort and filter like "num", but displayed as "0x%08X", the form the
#: record dialog uses for the same position (record_model._format).
KINDS = ("text", "url", "num", "time", "time_local", "flag", "size",
         "domain", "count", "carved", "only_carved", "types", "path",
         "bar", "offset")


class Column:
    """One grid column.

    key       key into the row dict
    label     header text; defaults to the key
    width     starting pixel width; None lets the header size it
    kind      one of KINDS
    field     provenance field name; adds a basis badge to the header
    on_click  callback(row): makes the cell a link, for drilling from a
              reference to the thing it refers to
    on_click_copies
        False (the default) when activating the cell follows the value
        somewhere (Domain to Domains, a container name to its table).
        True when activating it copies the value instead, as for
        Location's map links: a map provider is a third party, so the
        link is copied, never opened. record_model.py words the tooltip
        from this.
    link_enabled
        callable(row) -> bool, or None (the default: every row). For a
        link column where some rows have nothing to follow, such as a
        carved record with no ContainerName; is_link_for() reads it, so
        such a row shows no link cursor or tooltip.

    multi     True when a cell holds a MULTI_SEPARATOR-joined list; the
              value picker then offers the individual values
    multi_source
        The row key holding the pre-split list of values, for a multi
        column whose elements may themselves contain MULTI_SEPARATOR
        (", "), such as a device-reported provider string. None (the
        default) splits the joined value with split_multi(), which is
        safe for a comma-free vocabulary this tool generates.

    optional  True for a column that starts hidden and is shown from the
              view's "Columns" menu (records_view.RecordsView.
              columns_button). Hiding is a view preference only: exports
              write every column.

    badge / badge_tooltip
        The header basis badge's short text (e.g. "DER") and its tooltip.
        Not constructor arguments: widgets/ may not import the engine
        (test_structure.py), so the view that builds the COLUMNS list sets
        them after construction on any Column with a `field`. Both stay
        None otherwise, and no badge is painted (see show_badge).
    """

    __slots__ = ("key", "label", "width", "kind", "field", "numeric",
                 "sort_by",
                 "on_click", "on_click_copies", "link_enabled", "hidden",
                 "is_empty", "constant", "badge", "badge_tooltip", "multi",
                 "multi_source", "optional", "note", "basis_key", "blank_text",
                 "short")

    def __init__(self, key, label=None, width=None, kind="text", field=None,
                 on_click=None, sort_by=None, on_click_copies=False,
                 link_enabled=None, multi=False, multi_source=None,
                 optional=False, note=None, basis_key=None, blank_text=None,
                 short=None):
        if kind not in KINDS:
            raise ValueError("unknown column kind %r; expected one of %s"
                             % (kind, ", ".join(KINDS)))
        self.key = key
        #: fn(text) -> the text a CELL shows, for a column whose value is a
        #: sentence too long for a grid cell. The grid, search box and
        #: value picker all read display_text, so an examiner still
        #: filters on what they see; the tooltip, the record dialog and
        #: every export keep the value whole.
        self.short = short
        self.label = key if label is None else label
        self.width = width
        self.kind = kind
        self.field = field
        self.numeric = kind in ("num", "count", "size", "offset")
        self.on_click = on_click
        #: See the class docstring's "on_click_copies" section. Ignored
        #: (never even read) when on_click is None -- a non-link column
        #: has no activation to word a hint about either way.
        self.on_click_copies = on_click_copies
        #: See the class docstring's "link_enabled" section. Ignored
        #: (is_link_for degrades straight to is_link) when None.
        self.link_enabled = link_enabled
        #: Another row key to ORDER this column by, while still DISPLAYING
        #: its own. For a column whose text is a formatted rendering of
        #: something measurable -- a duration written "+1 d 2 h (device
        #: ahead)" -- lexical order is meaningless and the magnitude lives
        #: in a sibling key. None (the default) sorts on this column's own
        #: value, which is what every existing column does.
        self.sort_by = sort_by
        #: A column an examiner can show from the view's "Columns" menu;
        #: it starts hidden. Hidden is a VIEW preference: every export
        #: still writes the column, and the provenance sidecar lists it as
        #: hidden on screen.
        self.optional = bool(optional)
        #: Explanatory prose that is the same for every row of a kind
        #:: stated ONCE, in this column's header tooltip, never in a
        #: cell. The rows keep their own stored values, so exports do too.
        self.note = note
        #: Another row key holding THIS cell's own basis, in words: a
        #: column whose rows are on different footings --
        #: UTC as stored beside UTC derived from a LOCAL value -- says so
        #: per cell, in the tooltip. None for every other column.
        self.basis_key = basis_key
        #: What an EMPTY cell means in this column, for the filter list and
        #: the filter line ("(live record, not carved)"). The cell itself
        #: stays empty and exports keep the empty value. None: "(blank)".
        self.blank_text = blank_text
        self.hidden = self.optional
        #: Set by the model once the data is known.
        self.is_empty = False
        #: The single value this column holds in every row, when it holds only
        #: one. None means it varies, which is the normal case.
        self.constant = None
        #: Set by the owning view, never by this constructor -- see the
        #: class docstring's "badge / badge_tooltip" section.
        self.badge = None
        self.badge_tooltip = None
        self.multi = bool(multi)
        self.multi_source = multi_source

    @property
    def is_link(self):
        return self.on_click is not None

    def is_link_for(self, row):
        """Whether ONE ROW's cell reads as a
        link -- is_link, narrowed by link_enabled when the column
        declared one. Every consumer that has a specific row in hand
        (record_model.py's tooltip/foreground, records_table.py's cursor
        and activate_cell) reads this instead of the bare is_link
        property, so a link column whose target does not exist for a
        particular row never shows the pointing-hand cursor or the
        "follow this value" tooltip for it, and never calls on_click
        with nothing to point at."""
        if not self.is_link:
            return False
        if self.link_enabled is None:
            return True
        return bool(self.link_enabled(row))

    @property
    def show_badge(self):
        return bool(self.field)

    def __repr__(self):
        return "Column(%r, kind=%r)" % (self.key, self.kind)


def display_text(value, column):
    """The text a cell shows. The grid, the search box, the value picker
    and every text operator use this, so filtering on what is visible
    always finds it: "Yes"/"No", thousands-separated numbers and "0x%08X"
    offsets are matched as displayed.

    `column` needs only `kind` and `numeric` attributes: the grid passes
    the real Column, record_model._format a lightweight stand-in. A
    `column` of None (a filter on an undeclared key) is tolerated.
    """
    if value is None or value == "":
        return ""
    short = getattr(column, "short", None)
    if short is not None and isinstance(value, str):
        return short(value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if getattr(column, "kind", None) == "offset" and isinstance(value, int):
        return "0x%08X" % value
    if isinstance(value, datetime.datetime):
        # Written with the examiner's chosen pattern (time_format), which
        # never reads tzinfo: each time column's heading states its zone.
        return format_dt(value)
    if getattr(column, "numeric", False) and isinstance(value, (int, float)):
        return "{:,}".format(value)
    return str(value)


#: How a multi-value cell joins its values (domain_loader's ", ".join).
MULTI_SEPARATOR = ", "


def blank_label(column):
    """How an empty value of `column` is named wherever a filter lists or
    states it."""
    return getattr(column, "blank_text", None) or "(blank)"


def split_multi(value):
    """The individual values of one multi-value cell. A blank cell is ONE
    blank value, so "(blank)" stays pickable."""
    if value is None or value == "":
        return [value]
    return str(value).split(MULTI_SEPARATOR)


#: Separates the spellings inside one searchable_text value, and the cells
#: of one row in the grid's search haystack. It cannot occur in typed
#: text, so a search never matches across two spellings or two cells.
SEARCH_SEP = "\x00"


def searchable_text(value, column):
    """What a search box matches for one value: the text the grid paints
    (display_text), plus, on a numeric column that is not an offset, the
    value's plain unseparated digits, so "12345" finds "12,345".

    The grid's search (record_filter's haystack) and the value picker's
    search (filter_popup) both use this, so they agree on what a value
    contains. An offset is found by its hex; a flag by "Yes"/"No".
    Not lowercased: callers fold case once, for the whole string."""
    text = display_text(value, column)
    if (getattr(column, "numeric", False)
            and getattr(column, "kind", None) != "offset"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)):
        return text + SEARCH_SEP + str(value)
    # An address is shown percent-encoded but typed as words: "tax docs"
    # must find "Tax%20docs" (see webcache/spellings.py).
    others = other_spellings(text)
    return SEARCH_SEP.join([text] + others) if others else text
