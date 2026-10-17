"""Positions the device reported to servers: LocationView's fixes, and the
places they group into.

Qt-free. This layer calls geolocation and reshapes what it returns.

CARVED-NESS IS DECIDED ONCE, ON THE FIX. ForensicEngine._loc_value, which
every location export uses, reads fix["_entry"].get("Origin"). A carved
fix's `_entry` is a dict this module owns, carrying Origin, so the grid
and the exports give the same answer (tests/test_location_loader.py).

NOTHING THE ENGINE OWNS IS WRITTEN TO. `_carved_entry` builds a new dict
with the artifact as `_record`; the artifacts in engine.all_artifacts()
and structured_records are shared with Domains, Indicators, Recovery, the
Dashboard and every export. A live entry's Origin is written on the fix,
never on the parser record.

THE CROSS-CHECK. geolocation.collect returns FixTimestamp as the raw
query-parameter value: ISO-8601, a Windows FILETIME, or epoch seconds,
milliseconds or microseconds. geolocation.decode_url_timestamp turns it
into a datetime, the reading is named in its own column, the raw value is
kept beside it, and the signed difference from the cache-write time is a
column that sorts and filters.

Both time columns are aware UTC datetimes, so kind="time" columns filter
and sort correctly.

A PLACE STATES A RANGE, NEVER A MEAN. The accuracy of a place is the
range across its fixes: averaging 12 m and 140 m would state a precision
no fix claimed. FirstSeen/LastSeen are derived from the decoded instants,
since raw stamps of mixed formats do not sort chronologically as strings.
"""
import datetime
import math

from ..engine import forensic_engine, geolocation, local_clock
from ..provenance import (ABSENCE_NOT_RECOVERED, ABSENCE_NOT_SUPPLIED,
                          CARVED_ORIGIN, LIVE_ORIGIN)
from . import record_kinds
from .record_kinds import K_PLACE

class Grouping:
    """One scale places can be grouped at. `radius_m` None means exact:
    only fixes whose stored coordinates are identical are one place.
    Otherwise a place is a reported position and every fix within
    `radius_m` of it, labelled at `decimals`. `description` follows "by"
    in every subtitle and note, and says what the scale is on the ground."""
    __slots__ = ("key", "label", "radius_m", "decimals", "description")

    def __init__(self, key, label, radius_m, decimals, description):
        self.key, self.label = key, label
        self.radius_m, self.decimals = radius_m, decimals
        self.description = description


#: The scales an examiner chooses between on the Places tab. A WiFi fix
#: typically claims ~100 m, so at ~11 m one building splits into many
#: places by ordinary jitter; ~110 m is the default.
#:
#: Grouped by distance, not by rounding: any fixed rounding grid cuts a
#: line through some place at every scale, splitting it in two.
GROUPINGS = (
    Grouping("exact", "Exact", None, None, "identical stored coordinates"),
    Grouping("11m", "~11 m", 11, 4,
             "distance: within 11 m of a reported position"),
    Grouping("110m", "~110 m", 110, 3,
             "distance: within 110 m of a reported position"),
    Grouping("1km", "~1.1 km", 1100, 2,
             "distance: within 1.1 km of a reported position"),
)
DEFAULT_GROUPING = "110m"
_GROUPING_BY_KEY = {g.key: g for g in GROUPINGS}

_EARTH_M = 6371008.8


def grouping_for(key):
    """The Grouping for `key`; the default for anything unknown."""
    return _GROUPING_BY_KEY.get(key) or _GROUPING_BY_KEY[DEFAULT_GROUPING]


def _stored(fix):
    return (fix.get("LatitudeRaw") or repr(fix["Latitude"]),
            fix.get("LongitudeRaw") or repr(fix["Longitude"]))


def _distance_m(a, b):
    """Great-circle distance between two fixes, in metres."""
    lat1, lon1 = math.radians(a["Latitude"]), math.radians(a["Longitude"])
    lat2, lon2 = math.radians(b["Latitude"]), math.radians(b["Longitude"])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * _EARTH_M * math.asin(min(1.0, math.sqrt(h)))


def _group(fixes, g):
    """[(label, seed, members)], most fixes first, each fix in exactly one.

    Exact: one group per stored coordinate pair. Otherwise the fix with
    the most others within radius_m becomes a place, takes every
    unplaced fix within radius_m of it, and the next densest unplaced
    fix starts the next -- so no member is more than radius_m from the
    reported position its place is labelled by, and no grid line can
    split a building. Neighbours are found through a grid of radius-sized
    cells, so this stays linear in the number of fixes. Deterministic:
    ties fall to the stored coordinates.
    """
    fixes = list(fixes or ())
    if g.radius_m is None:
        grouped = {}
        for fix in fixes:
            grouped.setdefault(_stored(fix), []).append(fix)
        groups = [("%s, %s" % key, members[0], members)
                  for key, members in grouped.items()]
        groups.sort(key=lambda t: (-len(t[2]), t[0]))
        return groups

    cell_deg = g.radius_m / 111320.0

    def cell(fix):
        lat = fix["Latitude"]
        shrink = max(math.cos(math.radians(lat)), 0.01)
        return (math.floor(lat / cell_deg),
                math.floor(fix["Longitude"] * shrink / cell_deg))

    grid = {}
    for i, fix in enumerate(fixes):
        grid.setdefault(cell(fix), []).append(i)

    def near(i):
        ci, cj = cell(fixes[i])
        out = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for j in grid.get((ci + di, cj + dj), ()):
                    if _distance_m(fixes[i], fixes[j]) <= g.radius_m:
                        out.append(j)
        return out

    neighbours = [near(i) for i in range(len(fixes))]
    order = sorted(range(len(fixes)),
                   key=lambda i: (-len(neighbours[i]), _stored(fixes[i])))
    placed = [False] * len(fixes)
    labels = set()
    groups = []
    for i in order:
        if placed[i]:
            continue
        members = [j for j in neighbours[i] if not placed[j]]
        for j in members:
            placed[j] = True
        seed = fixes[i]
        label = "%.*f, %.*f" % (g.decimals, seed["Latitude"],
                                g.decimals, seed["Longitude"])
        # Two places whose reported positions print alike must still be
        # two drill keys.
        base, n = label, 2
        while label in labels:
            label, n = "%s (%d)" % (base, n), n + 1
        labels.add(label)
        groups.append((label, seed, [fixes[j] for j in sorted(members)]))
    groups.sort(key=lambda t: -len(t[2]))
    return groups


def label_fixes(fixes, grouping=None):
    """Set each fix's Place to its place at `grouping`, so the drill from a
    place row to its fixes (an exact match on this key) holds at every
    grouping."""
    g = grouping_for(grouping or DEFAULT_GROUPING)
    for label, _seed, members in _group(fixes, g):
        for fix in members:
            fix["Place"] = label
    return fixes

#: geolocation._assess's closing sentence, verbatim.
#:
#: Three of the four accuracy bands end "...It establishes what the device
#: claimed, not that any particular person was present." The band for a
#: fix that supplied no accuracy does not, and that fix is the weakest
#: claim on the screen. The engine's prose is not altered; the shell
#: appends this sentence when the assessment does not already carry it,
#: so there is one wording, and it reaches the CSV, the KML and the PDF,
#: which all read fix["Assessment"]. tests/test_location_loader.py checks
#: that this literal appears verbatim in an accuracy-supplied assessment.
NON_ATTRIBUTION = ("It establishes what the device claimed, not that any "
                   "particular person was present.")

#: A value was carried and no reading of it is safe. Distinct from
#: ABSENCE_NOT_SUPPLIED (nothing was carried). Not an absence token: the
#: value is there, in FixTimeRaw.
NOT_DECODABLE = "not decodable"

#: What "the device is ahead of the cache" and its opposite are called.
#: Named rather than inlined so the two sentences cannot drift apart.
_AHEAD = "device ahead"
_BEHIND = "device behind"

#: U+2212 MINUS SIGN, not a hyphen: this sits in a column beside signed
#: numbers and a hyphen reads as a dash.
_MINUS = "−"

#: Shown when no recovery scan has run, so a carved count of zero is not
#: read as "no position was deleted". main_window.py uses this constant.
CARVED_NOT_SCANNED_NOTE = (
    "carved fixes are not yet meaningful — no recovery scan has run for "
    "this exhibit; run Evidence ▸ Recover deleted records to search "
    "deleted and unflushed URLs for positions too")

#: Map links are copied, never opened, and opening one would send the
#: position to the provider. In the count line, which wraps, rather than
#: the header subtitle, which does not.
LINK_NOTE = ("Map links are copied, never opened. Opening one in a "
             "browser sends the position to that provider.")

#: What a position fix is and is not, beside the number it qualifies.
LOCATION_CAVEAT = (
    "A fix is what the device told a server. Fix time is the device's own "
    "claim and Cache wrote is not — they answer different questions and "
    "can disagree. Accuracy is the radius the application supplied; a "
    "WiFi fix locates a building, not a room. Treat a position as "
    "evidence of what was reported, not of where the device was.")

#: The empty state: what was searched for, and why an empty result is a
#: legitimate answer rather than a failure.
EMPTY_FIXES_TEXT = (
    "No request URL in this exhibit reported a position. Every URL was "
    "searched for the parameters that carry one — a latitude/longitude "
    "pair in a single value (%s), and separate latitude and longitude "
    "parameters (%s / %s) — and none of them appeared.\n\n"
    "This does not show the device was never located. Run Evidence ▸ "
    "Recover deleted records: positions are often found only in deleted "
    "or unflushed URLs."
    % (", ".join(geolocation.PAIR_PARAMS),
       ", ".join(geolocation.LAT_PARAMS),
       ", ".join(geolocation.LON_PARAMS)))

#: The Places set's own empty state -- reachable only when there are no
#: fixes, since every fix belongs to exactly one place.
EMPTY_PLACES_TEXT = (
    "No position fixes were found, so there is nothing to group into "
    "places. See the Position fixes tab for what was searched for.")


# --- fixes ---------------------------------------------------------------

def position_fixes(live_entries, carved_entries=(), grouping=None):
    """Every position any URL in this exhibit reported, live and carved.

    `live_entries` is parser.all_entries, unmodified. `carved_entries` is
    the union domain_loader/timeline_loader take (engine.
    structured_records + engine.all_artifacts()); an empty sequence before
    a recovery scan has run, so the carved count is zero.

    Returns the fix dicts geolocation.collect built (its own copies), with
    the shell's keys added. Nothing in `live_entries` or `carved_entries`
    is modified.
    """
    fixes = []

    for fix in geolocation.collect(live_entries):
        # Written on the fix, never on the parser record. A live entry has
        # no Origin key, and ForensicEngine._loc_value answers "Live record"
        # for it; this is the same answer, where the grid reads it.
        fix["Origin"] = "Live record"
        fixes.append(fix)

    wrapped = [_carved_entry(artifact) for artifact in carved_entries or ()
               if (artifact or {}).get("Url") or (artifact or {}).get("CleanUrl")]
    for fix in geolocation.collect(wrapped):
        fix["Origin"] = CARVED_ORIGIN
        fixes.append(fix)

    for fix in fixes:
        _shape(fix)
    return label_fixes(fixes, grouping)


def _carved_entry(artifact):
    """A dict this module owns, standing in for a carved record.

    geolocation.collect stores what it is given as fix["_entry"], and
    ForensicEngine._loc_value reads Origin from it, so Origin is set here
    rather than on the artifact. The artifact travels as `_record`, by
    reference, so a fix can be traced to its bytes without anything being
    written to it.
    """
    artifact = artifact or {}
    url = artifact.get("Url") or artifact.get("CleanUrl") or ""
    return {
        "Url": url,
        "CleanUrl": artifact.get("CleanUrl") or url,
        # collect() reads ModifiedTime, then AccessedTime, as the cache
        # write time ("Cache wrote (UTC)"). A structured carve keeps the real
        # column. A string carve has only a FILETIME found near it in the
        # bytes, which says where it was, not when anything was written, so
        # it travels under its own name below and this key stays empty.
        "ModifiedTime": (None if local_clock.is_unplaced(artifact)
                         else _carved_stamp(artifact)),
        # A carved MSHist visit on the LOCAL clock with no recovered zone:
        # the reason its cache-write time is blank (engine/local_clock.py),
        # which geolocation.collect carries onto the fix, so _carved_stamp
        # does not fall through to AccessedTime.
        "RecordTimeNote": (local_clock.clock_note(artifact)
                           if local_clock.is_unplaced(artifact) else ""),
        # Not a write time: carried so the fix can say which bytes it was
        # found beside. evidence_model grades it CARVED ("A plausible
        # FILETIME found adjacent to the carved ...").
        "NearbyFiletime": artifact.get("NearbyFiletime"),
        "ContainerType": artifact.get("ContainerType") or "",
        "EntryId": artifact.get("EntryId"),
        "ContainerId": artifact.get("ContainerId"),
        "Origin": CARVED_ORIGIN,
        "_record": artifact,
    }


def _carved_stamp(artifact):
    """The carved record's own write time, or None when it has none.

    NearbyFiletime is not a fallback (see the call site): a string carve
    has no write time, and the nearby value travels separately.
    """
    for key in ("ModifiedTime", "AccessedTime", "CreationTime"):
        value = artifact.get(key)
        if value:
            return value
    return None


def _shape(fix):
    """The shell's own keys, added to one fix in place."""
    entry = fix.get("_entry") or {}
    record = entry.get("_record")
    carved = str(fix.get("Origin") or "").startswith("Carved")

    fix_dt, fix_format = _decode_fix_time(fix)
    record_dt = _parse_stamp(fix.get("RecordTimeUTC"))

    fix["FixTimeUtc"] = fix_dt
    fix["FixTimeFormat"] = fix_format
    fix["FixTimeRaw"] = str(fix.get("FixTimestamp") or "") or ABSENCE_NOT_SUPPLIED
    fix["RecordTimeUtc"] = record_dt
    fix["Disagreement"] = _disagreement(fix_dt, record_dt)
    if record_dt is None and fix.get("RecordTimeNote"):
        # Not "not supplied": the cache time exists, on a clock this tool
        # cannot convert. Say which, in the row.
        fix["Disagreement"] = UNPLACED_DISAGREEMENT
    # What the "Cache wrote" column SHOWS. A carved URL often has no cache
    # write time at all, and a blank cell would stand in for that unknown;
    # the column sorts by RecordTimeUtc, which stays a real datetime.
    fix["RecordTimeShown"] = record_dt
    if record_dt is None and carved and not fix.get("RecordTimeNote"):
        fix["RecordTimeShown"] = ABSENCE_NOT_RECOVERED
        fix["Disagreement"] = ABSENCE_NOT_RECOVERED
    # What the column ORDERS by: the text above is a rendering, and lexical
    # order over it is meaningless -- see Column.sort_by.
    fix["DisagreementSeconds"] = _disagreement_seconds(fix_dt, record_dt)

    # The strings exactly as the URL carried them. Rounding is applied
    # only in Place, labelled as the grouping.
    fix["Coords"] = "%s, %s" % (
        fix.get("LatitudeRaw") or repr(fix["Latitude"]),
        fix.get("LongitudeRaw") or repr(fix["Longitude"]))

    # The number the device sent, or the statement that it sent none;
    # never rounded, averaged or defaulted. Kept under its own key so
    # ProviderRaw/AccuracyMetres stay available for the range arithmetic
    # in places() below.
    # Three outcomes: metres is None both for "no accuracy in the URL" and
    # for an accuracy float() could not read. Where a value was supplied,
    # the value is shown as sent.
    metres = fix.get("AccuracyMetres")
    raw = str(fix.get("AccuracyRaw") or "").strip()
    if metres is not None:
        fix["Accuracy"] = metres
    elif raw:
        fix["Accuracy"] = "%s (not a number of metres)" % raw
    else:
        fix["Accuracy"] = ABSENCE_NOT_SUPPLIED
    provider = str(fix.get("Provider") or "")
    fix["ProviderRaw"] = provider
    fix["Provider"] = provider or ABSENCE_NOT_SUPPLIED

    # See NON_ATTRIBUTION: the no-accuracy band of the engine's own
    # assessment is the one that omits the sentence, and it is the band
    # where it matters most.
    assessment = str(fix.get("Assessment") or "").strip()
    if assessment and NON_ATTRIBUTION not in assessment:
        assessment = "%s %s" % (assessment, NON_ATTRIBUTION)
    fix["Assessment"] = assessment

    fix["_record"] = record if carved else entry
    fix["_kind"] = (record_kinds.kind_for_carved(record or {}) if carved
                    else record_kinds.kind_for_entry(entry))




def _decode_fix_time(fix):
    """(datetime | None, what the reading was) for one fix's own stamp.

    Three outcomes:

      ABSENCE_NOT_SUPPLIED  the URL carried no time parameter; the
                            application did not send one.
      NOT_DECODABLE         it carried one and no reading is safe:
                            decode_url_timestamp refuses anything that
                            could be an id, a size or a build number.
      a format name         the reading, named, beside the raw value.
    """
    raw = str(fix.get("FixTimestamp") or "").strip()
    if not raw:
        return None, ABSENCE_NOT_SUPPLIED
    decoded, form = geolocation.decode_url_timestamp(raw)
    if not decoded:
        return None, NOT_DECODABLE
    stamp = _parse_stamp(decoded)
    if stamp is None:
        # decode_url_timestamp's ISO branch returns the text AS WRITTEN,
        # which can be a shape datetime cannot parse back. Refusing here
        # is the same discipline the engine applies one level down.
        return None, NOT_DECODABLE
    # A zone this tool assumed is not a zone the request stated:
    # _parse_stamp reads an unzoned stamp as UTC so it can be compared with
    # the record's time, and the "Fix time read as" column says so.
    if not _states_its_zone(decoded):
        form = "%s, no zone stated - read as UTC" % form
    return stamp, form


def _states_its_zone(decoded):
    """True when the value itself carries a zone, rather than being given one."""
    if isinstance(decoded, datetime.datetime):
        return decoded.tzinfo is not None
    text = str(decoded or "").strip()
    if not text:
        return False
    if text.endswith("Z") or text.endswith(" UTC"):
        return True
    # An offset is +HH:MM / -HH:MM at the end, never the date's own hyphens.
    tail = text[10:] if len(text) > 10 else ""
    return "+" in tail or "-" in tail


def _parse_stamp(value):
    """One timestamp, however it arrived, as an aware UTC datetime.

    Total rather than raising: this is called with a raw query-parameter
    value, an engine-formatted string, and a datetime a carve pulled out
    of nearby bytes. Anything unreadable comes back None, which every
    caller already treats as "no time", rather than taking a dialog with
    it.
    """
    if isinstance(value, datetime.datetime):
        # astimezone, not a bare return: an aware datetime that is not
        # already UTC would otherwise reach a column headed (UTC) still
        # carrying its own offset -- see the module-level note below.
        return (value.astimezone(datetime.timezone.utc) if value.tzinfo
                else value.replace(tzinfo=datetime.timezone.utc))
    text = str(value or "").strip().replace(" UTC", "").replace(" LOCAL", "")
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    # An offset-carrying stamp is converted to UTC, not just accepted:
    # FixTimeUtc is headed (UTC), and record_model._format renders the
    # wall-clock digits without consulting tzinfo, so an unconverted
    # 09:00:01+05:30 would print five and a half hours from the instant it
    # names. A column never shows a value in a zone it does not claim.
    return (stamp.astimezone(datetime.timezone.utc) if stamp.tzinfo
            else stamp.replace(tzinfo=datetime.timezone.utc))


#: The cross-check's text when the cache-write time is an MSHist LOCAL
#: value with no recovered zone (engine/local_clock.py).
UNPLACED_DISAGREEMENT = ("not measurable: the cache time is LOCAL only "
                         "(no time zone was recovered)")


def _disagreement(fix_dt, record_dt):
    """How far the device's own claim is from when the cache wrote it.

    The device controls the fix time but not the cache write, so a
    disagreement can be found, sorted and filtered ("every fix more than
    an hour off" is one right-click).

    ABSENCE_NOT_SUPPLIED when either side is missing, never "0", which
    would assert an agreement that was not measured.
    """
    if fix_dt is None or record_dt is None:
        return ABSENCE_NOT_SUPPLIED
    seconds = int(round((fix_dt - record_dt).total_seconds()))
    if seconds == 0:
        return "none"
    sign = "+" if seconds > 0 else _MINUS
    which = _AHEAD if seconds > 0 else _BEHIND
    return "%s%s (%s)" % (sign, duration_text(abs(seconds)), which)


def _disagreement_seconds(fix_dt, record_dt):
    """The signed magnitude behind _disagreement's text, which the column
    sorts by. None when either side is missing; _sort_key ranks None last,
    so an unmeasured disagreement never sorts as zero.
    """
    if fix_dt is None or record_dt is None:
        return None
    return int(round((fix_dt - record_dt).total_seconds()))


def duration_text(seconds):
    """At most two units, largest first. "3 h 12 m", "41 s", "2 d 4 h"."""
    if seconds < 60:
        return "%d s" % seconds
    if seconds < 3600:
        return _two("m", seconds // 60, "s", seconds % 60)
    if seconds < 86400:
        return _two("h", seconds // 3600, "m", (seconds % 3600) // 60)
    return _two("d", seconds // 86400, "h", (seconds % 86400) // 3600)


def _two(big_unit, big, small_unit, small):
    text = "%d %s" % (big, big_unit)
    if small:
        text += " %d %s" % (small, small_unit)
    return text


# --- places --------------------------------------------------------------

def places(fixes, grouping=None):
    """One row per distinct position at `grouping` (GROUPINGS; default
    DEFAULT_GROUPING), most fixes first.

    Each row is an aggregate: `_kind` is K_PLACE (the detail dialog states
    that the row is not a record), `_record` is None (there is no single
    record), and `_members` references every fix counted, so "14 fixes"
    can be opened.
    """
    g = grouping_for(grouping or DEFAULT_GROUPING)
    rows = []
    for label, seed, members in _group(fixes, g):
        lat, lon = label.split(" (")[0].split(", ", 1)
        summary = {
            "Latitude": seed["Latitude"],
            "Longitude": seed["Longitude"],
            "Fixes": len(members),
            "MapsUrl": geolocation.maps_url(lat, lon),
            "OsmUrl": geolocation.osm_url(lat, lon),
            "Grouping": g.description,
        }
        stamps = [f["FixTimeUtc"] or f["RecordTimeUtc"] for f in members]
        stamps = [s for s in stamps if s is not None]
        providers = sorted({f["ProviderRaw"] for f in members if f["ProviderRaw"]})
        summary.update({
            "Coords": label,
            "Accuracy": _accuracy_range(members),
            "Carved": sum(1 for f in members
                          if str(f.get("Origin") or "").startswith("Carved")),
            # Derived from the decoded instants: raw stamps of mixed
            # formats do not sort chronologically as strings.
            "FirstSeen": min(stamps) if stamps else None,
            "LastSeen": max(stamps) if stamps else None,
            # From the raw provider values: fix["Provider"] holds the
            # absence token where none was supplied, which is this tool's
            # wording, not something the device said.
            "Providers": ", ".join(providers) if providers
                         else ABSENCE_NOT_SUPPLIED,
            # The pre-split list beside the joined text (see
            # views/location.py's Providers column, multi_source): a
            # provider string can itself contain ", ".
            "ProvidersValues": providers,
            "_kind": K_PLACE,
            "_record": None,
            "_members": members,
        })
        rows.append(summary)
    return rows


def _accuracy_range(members):
    """The radius range across a cluster, never a mean.

    A mean of 12 m and 140 m is 76 m, a precision no fix claimed. Four
    shapes; the mixed one states that some fixes supplied no accuracy, so
    the range is not read as covering all of them.
    """
    supplied = [f["AccuracyMetres"] for f in members
                if f.get("AccuracyMetres") is not None]
    missing = len(members) - len(supplied)
    if not supplied:
        return ABSENCE_NOT_SUPPLIED
    low, high = min(supplied), max(supplied)
    text = ("±%s m" % _metres(low) if low == high
            else "±%s–%s m" % (_metres(low), _metres(high)))
    if missing:
        text += " (%d fix%s supplied none)" % (missing,
                                               "" if missing == 1 else "es")
    return text


def _metres(value):
    """A radius as the device sent it: no thousands separator, and no
    ".0" grown onto a whole number."""
    return "%d" % value if float(value).is_integer() else "%g" % value


# --- raw records ---------------------------------------------------------

#: The Raw records set's own empty state.
EMPTY_RECORDS_TEXT = (
    "No record reported a position, so there are no source records to "
    "show. See the Position fixes tab for what was searched for.")


def record_fields():
    """[(key, header)] for the Raw records grid: Origin first, then every
    other canonical field in ENTRY_FIELDS order."""
    fields = [(k, h) for k, h, _g in forensic_engine.ENTRY_FIELDS]
    return ([f for f in fields if f[0] == "Origin"]
            + [f for f in fields if f[0] != "Origin"])


def _fix_is_carved(fix):
    return str(fix.get("Origin") or "").startswith("Carved")


def source_records(fixes):
    """One row per source record that yielded at least one fix, with every
    canonical field (from the engine's canonical_record_row, the path every
    export takes), how many fixes it yielded, and the record itself by
    reference. Carved-ness is read from the fix, where position_fixes set
    it, so a carved record keeps the carved Origin.

    Identity is the record object: two fixes from one URL are one row
    counting two, and two records with the same URL are two rows.
    """
    rows = []
    by_record = {}
    for fix in fixes or ():
        record = fix.get("_record")
        if not isinstance(record, dict):
            continue
        row = by_record.get(id(record))
        if row is None:
            carved = _fix_is_carved(fix)
            row = forensic_engine.canonical_record_row(
                record, carved=True if carved else None)
            row["Origin"] = CARVED_ORIGIN if carved else LIVE_ORIGIN
            row["Fixes"] = 0
            row["_record"] = record
            row["_kind"] = fix.get("_kind")
            by_record[id(record)] = row
            rows.append(row)
        row["Fixes"] += 1
    return rows


def records_note(fixes):
    """The count line's note beside Raw records. As in fixes_note, the
    count to its left is not repeated."""
    rows = source_records(fixes)
    carved = sum(1 for r in rows
                 if str(r.get("Origin") or "").startswith("Carved"))
    return _sentences([
        "each yielded at least one of the %s position fix%s — %s live, "
        "%s carved" % (_n(len(list(fixes or ()))),
                       "" if len(list(fixes or ())) == 1 else "es",
                       _n(len(rows) - carved), _n(carved)),
        "Every field of each record is shown, raw FILETIMEs and ids "
        "included, as the position exports write it",
        LOCATION_CAVEAT])


# --- the count lines -----------------------------------------------------

def fixes_note(fixes, scan_run):
    """The count line's note beside the Position fixes grid.

    It does not repeat the count, which RecordsView._update_count writes
    to its left ("41 position fixes"); "38 of them" refers back to it.

    In order: how much of the set was recovered (or that no scan has
    run), how much claims no accuracy, and the caveat, stated at the
    number.
    """
    fixes = list(fixes or ())
    carved = sum(1 for f in fixes
                 if str(f.get("Origin") or "").startswith("Carved"))
    no_accuracy = sum(1 for f in fixes if f.get("AccuracyMetres") is None)

    if scan_run:
        parts = ["%s of them recovered from deleted or unflushed URLs"
                 % _n(carved)]
    else:
        parts = [CARVED_NOT_SCANNED_NOTE]
    if fixes:
        # "None reported no accuracy" is a double negative and reads as
        # its own opposite at a glance. Say what happened instead.
        parts.append("%s reported no accuracy at all" % _n(no_accuracy)
                     if no_accuracy else "Every one reported an accuracy")
    parts.append(LINK_NOTE)
    parts.append(LOCATION_CAVEAT)
    return _sentences(parts)


def places_note(fixes, places_rows, grouping=None):
    """The count line's note beside the Places grid.

    The line to its left already gives the number of places, so this
    gives how many fixes they were grouped from, the grouping and its size
    on the ground, and that a place is a summary: "one place, 14 fixes" is
    not a place the device was.
    """
    fixes = list(fixes or ())
    # Opened with double-click, Enter, or the context menu's Open, for a
    # place row and its Coords cell alike.
    g = grouping_for(grouping or DEFAULT_GROUPING)
    return ("grouped from %s fix%s by %s. A place is a "
            "summary of the fixes underneath it — double-click one, or "
            "double-click its coordinates, to see them. %s %s"
            % (_n(len(fixes)), "" if len(fixes) == 1 else "es",
               g.description, LINK_NOTE, LOCATION_CAVEAT))


def _sentences(parts):
    """Join clauses into one line without doubling a full stop: some
    parts are bare clauses and some are sentences (LINK_NOTE,
    LOCATION_CAVEAT) that end in a period of their own.
    """
    cleaned = [part.rstrip().rstrip(".") for part in parts if part]
    return ". ".join(cleaned) + "." if cleaned else ""


def _n(value):
    return format(value, ",")
