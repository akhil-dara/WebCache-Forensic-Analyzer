"""Positions the device reported to servers, which it can be told to fake.

The caveat is carried by the structure of the view, not only by a sentence:

1. "Times differ by" is a column. The device controls the fix time but not
   the cache write, so the difference between them is a cross-check; as a
   sortable, filterable column it takes one right-click.
2. "Fix time read as" names the encoding decoded, or that none was safe.
3. The headings say whose claim it is: "Fix time - device said",
   "Accuracy claimed (m)", "Reported source", "Source record",
   "Latitude, Longitude (as stored)". No heading asserts a position.
4. The Assessment column repeats geolocation._assess's non-attribution
   sentence, in the engine's wording, on every row.
5. The grid note and the caveat line carry what a column cannot.

There is no confidence column, badge or score. A fix's weight is carried
by four columns read together: the accuracy the device supplied (or "not
supplied"; never rounded, averaged or defaulted), the reported source, the
source record (live or carved, styled as such) and the assessment.

A place is a summary, so clicking it opens the fixes it summarises, with
the request URL, live or carved origin and claimed accuracy of each.

Map links are text, copied and never opened (tests/test_no_open_paths.py);
the view states that opening one would send the position to the provider.

Three tables: Fixes, Places and Raw records. Raw records are the source
records that yielded at least one fix, with every canonical field, carved
ones labelled: the same fields each position export writes after the
fix's own columns.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel,
                               QPushButton, QWidget)

from ..engine.geolocation import ASSESSMENT_GUIDE
from ..shell.location_loader import (DEFAULT_GROUPING, EMPTY_FIXES_TEXT,
                                     EMPTY_PLACES_TEXT, EMPTY_RECORDS_TEXT,
                                     GROUPINGS, LINK_NOTE, grouping_for,
                                     record_fields)
from ..widgets import copyable
from ..widgets.column_spec import Column

#: The data Origin column's heading beside the grid's own "Origin" marker.
ORIGIN_DETAIL_HEADING = "Origin detail"
from .records_view import RecordSet, RecordsView

#: What one row of each set IS, in the count line. A fix and a place are
#: not the same quantity and the line must not call them both "records".
COUNT_NOUNS = {"fixes": "position fixes", "places": "places",
               "records": "source records"}



def _copy_label(_url):
    """A map link's CELL: what a click does. The URL is built from the
    coordinates beside it and ran to three clipped lines a row; the whole
    of it is the tooltip, the copy and every export."""
    return "Copy link"

def _fix_columns(view=None):
    """The fixes grid, built per view: a Column with an on_click holds a
    reference to the view that owns it."""
    copy_maps = copy_osm = None
    if view is not None:
        copy_maps = lambda row: view._copy(row, "MapsUrl", "Google Maps link")   # noqa: E731
        copy_osm = lambda row: view._copy(row, "OsmUrl", "OpenStreetMap link")   # noqa: E731
    return [
        # "device said", not "Fix time". The device controls this value.
        Column("FixTimeUtc", "Fix time — device said (UTC)", 200, kind="time"),
        # Which reading was applied: ISO as written, a Windows FILETIME,
        # epoch milliseconds, or that the value could not be safely
        # decoded.
        Column("FixTimeFormat", "Fix time read as", 165, kind="text"),
        # The one time on this row the device did not control. Field
        # ModifiedTime, the column it was read from, for the basis badge.
        Column("RecordTimeShown", "Cache wrote (UTC)", 180, kind="time",
               field="ModifiedTime", basis_key="RecordTimeNote",
               sort_by="RecordTimeUtc"),
        # THE CROSS-CHECK, as a value. See the module docstring.
        Column("Disagreement", "Times differ by", 155, kind="text",
               sort_by="DisagreementSeconds"),
        # repr, every digit as stored. Rounding is applied only in Place,
        # at the grouping chosen above the switcher.
        Column("Coords", "Latitude, Longitude (as stored)", 280, kind="flag"),
        Column("Place", "Place (as grouped)", 175, kind="flag"),
        # A number or (not supplied), never a blank and never a default.
        Column("Accuracy", "Accuracy claimed (m)", 165, kind="num",
               note=ASSESSMENT_GUIDE),
        Column("Provider", "Reported source", 155, kind="text"),
        Column("Origin", "Source record", 185, kind="flag", field="Origin"),
        Column("Parameter", "From URL parameter", 170, kind="text"),
        Column("ContainerType", "Record type", 130, kind="text",
               field="ContainerType"),
        # The engine's own prose, verbatim, on every record and in every
        # export; off the grid by default, its reading guide in the
        # Accuracy heading's tooltip.
        Column("Assessment", "What this fix is worth", 380, kind="text",
               optional=True),
        Column("Url", "Request URL", 420, kind="url", field="CleanUrl"),
        # COPIED, never opened. See LINK_NOTE.
        Column("MapsUrl", "Google Maps", 135, kind="url", on_click=copy_maps,
               on_click_copies=True, short=_copy_label),
        Column("OsmUrl", "OpenStreetMap", 145, kind="url", on_click=copy_osm,
               on_click_copies=True, short=_copy_label),
    ]


def _place_columns(view=None):
    drill = copy_maps = copy_osm = None
    if view is not None:
        drill = view.show_fixes_at
        copy_maps = lambda row: view._copy(row, "MapsUrl", "Google Maps link")   # noqa: E731
        copy_osm = lambda row: view._copy(row, "OsmUrl", "OpenStreetMap link")   # noqa: E731
    return [
        # THE DRILL, not a copy. See the module docstring.
        Column("Coords", "Latitude, Longitude (as grouped)", 215,
               kind="flag", on_click=drill),
        Column("Fixes", "Fixes", 80, kind="num"),
        # A count, not a flag: a place can hold live and recovered fixes
        # together.
        Column("Carved", "From deleted", 110, kind="carved"),
        # Text, not a number: a range across the cluster ("±12–140 m"),
        # or a statement that none was supplied. A single number would
        # have to be a mean, a precision no fix claimed.
        Column("Accuracy", "Accuracy claimed", 195, kind="text"),
        Column("FirstSeen", "First reported", 175, kind="time"),
        Column("LastSeen", "Last reported", 175, kind="time"),
        # multi_source: providers are device-reported strings that may
        # themselves contain ", ", so the joined text cannot be re-split
        # safely. location_loader.places() carries the pre-split list
        # under "ProvidersValues".
        Column("Providers", "Reported source", 155, kind="text", multi=True,
               multi_source="ProvidersValues"),
        Column("MapsUrl", "Google Maps", 135, kind="url", on_click=copy_maps,
               on_click_copies=True, short=_copy_label),
        Column("OsmUrl", "OpenStreetMap", 145, kind="url", on_click=copy_osm,
               on_click_copies=True, short=_copy_label),
    ]


#: One short sentence each: the header subtitle does not grow for
#: wrapped lines. Longer text belongs in the count-line note, which wraps.
def _fixes_subtitle(count):
    return ("%s position fix%s, read out of request URLs."
            % (format(count, ","), "" if count == 1 else "es"))


def _places_subtitle(count, grouping=DEFAULT_GROUPING):
    return ("%s distinct place%s, grouped by %s."
            % (format(count, ","), "" if count == 1 else "s",
               grouping_for(grouping).description))


def _record_columns():
    """Every canonical field, Origin first: the record behind the fix, as
    the exports write it."""
    # Widths are a starting point: RecordsTable's heading floor widens any
    # column whose heading needs more, measured in the font it paints.
    columns = [Column("Fixes", "Fixes from this record", 150, kind="num")]
    for key, header in record_fields():
        if key == "Origin":
            # The vertical header already reads "Origin" (ORIGIN_HEADING);
            # the data column takes "Origin detail", as History,
            # Headers and Deleted Records do. Key unchanged.
            header = ORIGIN_DETAIL_HEADING
        # Url/CleanUrl take the Position fixes width, so a long URL does
        # not wrap to a row taller than the viewport.
        width = 420 if key in ("Url", "CleanUrl") else 170
        columns.append(Column(key, header, width, kind="text",
                              field="Origin" if key == "Origin" else None))
    return columns


def _records_subtitle(count):
    return ("%s source record%s that reported at least one position, "
            "every field shown." % (format(count, ","),
                                    "" if count == 1 else "s"))


class LocationView(RecordsView):
    #: Text to put on the clipboard, and what it is, for the status line.
    #: MainWindow owns the clipboard; the view only reports the request.
    copyRequested = Signal(str, str)
    #: The examiner chose another grouping scale (a GROUPINGS key). The
    #: shell regroups -- it owns the fixes, as it owns the clipboard.
    groupingChanged = Signal(str)

    _grouping_bar = None
    _grouping = DEFAULT_GROUPING

    def __init__(self, parent=None):
        super().__init__(
            record_sets=[
                RecordSet("fixes", "Position fixes", _fix_columns(self),
                          subtitle=_fixes_subtitle,
                          empty_text=EMPTY_FIXES_TEXT,
                          default_sort=("FixTimeUtc", True),
                          count_noun=COUNT_NOUNS["fixes"]),
                RecordSet("places", "Places", _place_columns(self),
                          subtitle=lambda n: _places_subtitle(n, self._grouping),
                          empty_text=EMPTY_PLACES_TEXT,
                          count_noun=COUNT_NOUNS["places"]),
                RecordSet("records", "Raw records", _record_columns(),
                          subtitle=_records_subtitle,
                          empty_text=EMPTY_RECORDS_TEXT,
                          count_noun=COUNT_NOUNS["records"]),
            ],
            header_icon="pin", header_title="Location",
            initial_key="fixes", parent=parent)
        # a fix row is never taller than three lines; the "+N more
        # lines" marker and Enter show the rest.
        self.table.set_line_cap(3)

    # --- the count line's own noun ---------------------------------------

    @property
    def COUNT_NOUN(self):
        """A row is a position fix on one segment and a place on the
        other; the count line names which (see K_PLACE)."""
        return COUNT_NOUNS.get(getattr(self, "_active_key", ""),
                               COUNT_NOUNS["fixes"])

    # --- how places are grouped -----------------------------------------

    def _switcher_trailing(self):
        """The grouping switch, at the right of the segment row. It governs
        every segment: each fix's Place column and the drill from a place
        to its fixes follow it. A WiFi fix typically claims ~100 m, so at
        ~11 m one building splits into many places by ordinary jitter. The
        scale in force is stated by the subtitle and the note; each
        button's tooltip says what it groups by."""
        if self._grouping_bar is not None:
            return self._grouping_bar
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(copyable.selectable(QLabel("Group places:")))
        self.grouping_buttons = {}
        group = QButtonGroup(bar)
        group.setExclusive(True)
        for g in GROUPINGS:
            button = QPushButton(g.label)
            button.setCheckable(True)
            button.setChecked(g.key == self._grouping)
            button.setToolTip("Group fixes by %s. Applies to Places and "
                              "to each fix's Place." % g.description)
            button.clicked.connect(
                lambda _c=False, k=g.key: self._set_grouping(k))
            group.addButton(button)
            row.addWidget(button)
            self.grouping_buttons[g.key] = button
        self._grouping_bar = bar
        return bar

    def grouping(self):
        return self._grouping

    def show_grouping(self, key):
        """Show `key` as the grouping in force, without announcing it: the
        shell calls this when it regroups on that scale."""
        self._grouping = grouping_for(key).key
        self.grouping_buttons[self._grouping].setChecked(True)
        if self._active_key == "places":
            self._render_active_segment()      # the subtitle names it

    def _set_grouping(self, key):
        if key == self._grouping:
            return
        self.show_grouping(key)
        self.groupingChanged.emit(self._grouping)

    # --- a place drills to its fixes -------------------------------------

    def show_fixes_at(self, place_row):
        """Open the fixes this place summarises, with the request URL each
        was read from, its live or carved origin, and its record.

        The exact-value match holds because location_loader labels every
        fix's Place with the same function, at the same grouping, that
        labels the place.
        """
        coords = (place_row or {}).get("Coords")
        if not coords:
            return
        # Clears the filter box and every chip: a filter typed against the
        # places columns would match nothing on the fixes columns.
        self._switch_segment("fixes")
        model = self.table.model()
        if model is not None:
            model.set_values("Place", {coords})

    # --- copy, never open -------------------------------------------------

    def _copy(self, row, key, what):
        text = str((row or {}).get(key) or "")
        if text:
            self.copyRequested.emit(text, what)

    # --- what is on screen, for the wording tests -------------------------

    def visible_text(self):
        """Every literal this view shows, so tests can check that none
        contains "confirm", "proves" or "demonstrates" un-negated.
        """
        texts = [self.header._subtitle.text(), self.count_label.text(),
                 self.caveat._text.text(), LINK_NOTE]
        texts.extend(b.toolTip() for b in self.grouping_buttons.values())
        for rs in self._record_sets:
            texts.append(rs.label)
            texts.append(rs.empty_text)
            texts.append(rs.subtitle(len(self._segment_rows[rs.key])))
            texts.extend(col.label for col in rs.columns)
        return [t for t in texts if t]
