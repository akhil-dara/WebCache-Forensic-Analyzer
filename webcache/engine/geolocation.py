"""
Geolocation recovered from URLs.

Applications embed the device's position in request URLs: news feeds,
weather widgets, maps, ad calls. Those coordinates remain in the cache long
after the page is gone: a position, an accuracy, how it was obtained, and
when.

What a fix is, and is not
-------------------------
A coordinate in a URL is what the device *told a server* its position was.
It is OBSERVED (the digits are in the stored URL), but it establishes that
the device reported that position, not that a particular person was there.
A WiFi-derived fix has an accuracy radius of tens or hundreds of metres,
the device may have been wrong, and a position can be overridden or
spoofed. Every finding therefore carries its accuracy and its provider, and
the assessment says what it supports.

Everything here is computed from the URL alone. Nothing is looked up and no
network request is made; the map links are text for the examiner to copy.
"""

import re
from urllib.parse import parse_qs, unquote, urlparse

from . import local_clock

# Parameters that carry a latitude/longitude pair in one value, separated by
# "|", "," or ";". Names are matched case-insensitively.
PAIR_PARAMS = (
    "clientlocation", "location", "latlng", "latlon", "ll", "coords",
    "coordinates", "geo", "position", "point", "center", "centre",
)

# Parameters that carry one half of a pair.
LAT_PARAMS = ("lat", "latitude", "y", "clientlatitude", "userlat")
LON_PARAMS = ("lon", "lng", "long", "longitude", "x", "clientlongitude",
              "userlon", "userlng")

# Context that travels with a fix when the application supplies it.
ACCURACY_PARAMS = ("clientlocationaccuracy", "accuracy", "acc", "radius",
                   "uncertainty", "horizontalaccuracy")
PROVIDER_PARAMS = ("clientlocationprovider", "locationprovider", "provider",
                   "positionsource", "source")
TIME_PARAMS = ("clientlocationtimestamp", "locationtimestamp", "geotimestamp",
               "positiontimestamp", "fixtime")

# A coordinate pair in one string. Requires a decimal point on both halves so
# that ordinary integer pairs (page sizes, ids, versions) do not match.
_PAIR = re.compile(r"^\s*(-?\d{1,3}\.\d+)\s*[|,;]\s*(-?\d{1,3}\.\d+)\s*$")
_NUMBER = re.compile(r"^\s*-?\d{1,3}\.\d+\s*$")


def _valid(lat, lon):
    """Both halves in range, and not the null island placeholder."""
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    # 0,0 is in the Gulf of Guinea and is overwhelmingly a default or a
    # cleared value rather than a real position.
    return not (abs(lat) < 1e-9 and abs(lon) < 1e-9)


def maps_url(lat, lon):
    """A Google Maps link for a fix. Text only — nothing is fetched. The
    arguments are embedded exactly as given: callers pass the strings the
    URL carried, or a place's own labelled rounding."""
    return "https://www.google.com/maps?q=%s,%s" % (lat, lon)


def osm_url(lat, lon):
    """An OpenStreetMap link, for an examiner who would rather not use Google."""
    return ("https://www.openstreetmap.org/?mlat=%s&mlon=%s#map=17/%s/%s"
            % (lat, lon, lat, lon))


def _first(qs_lower, names):
    for name in names:
        values = qs_lower.get(name)
        if values and str(values[0]).strip():
            return unquote(str(values[0]).strip())
    return ""


def extract_from_url(url):
    """Every position this URL reports, as a list of dicts.

    Returns [] when the URL carries none. A dict has: Latitude, Longitude,
    Parameter (which parameter held it), AccuracyMetres, Provider,
    FixTimestamp, MapsUrl, OsmUrl and Assessment.
    """
    if not url or "?" not in url:
        return []
    try:
        parsed = urlparse(url)
        raw_qs = parse_qs(parsed.query, keep_blank_values=False)
    except ValueError:
        return []
    if not raw_qs:
        return []

    # Case-insensitive view of the query string.
    qs = {}
    for key, values in raw_qs.items():
        qs.setdefault(key.lower(), []).extend(values)

    accuracy = _first(qs, ACCURACY_PARAMS)
    provider = _first(qs, PROVIDER_PARAMS)
    fix_time = _first(qs, TIME_PARAMS)

    found = []
    seen = set()

    def add(lat, lon, parameter, lat_raw, lon_raw):
        if not _valid(lat, lon):
            return
        key = (round(lat, 7), round(lon, 7))
        if key in seen:
            return
        seen.add(key)
        try:
            metres = float(accuracy) if accuracy else None
        except ValueError:
            metres = None
        found.append({
            "Latitude": lat,
            "Longitude": lon,
            # the parameter strings exactly as the URL carried them,
            # after percent-decoding. The floats above are for sorting,
            # clustering and range checks; every display and export shows
            # these.
            "LatitudeRaw": lat_raw,
            "LongitudeRaw": lon_raw,
            "Parameter": parameter,
            "AccuracyMetres": metres,
            # The parameter AS THE URL CARRIED IT. metres is None both when
            # no accuracy was sent and when one was sent in a vocabulary
            # float() cannot read ("high", "5km"). Those are different facts
            # about the request, and without the raw string nothing
            # downstream can tell them apart.
            "AccuracyRaw": accuracy or "",
            "Provider": provider,
            "FixTimestamp": fix_time,
            "MapsUrl": maps_url(lat_raw, lon_raw),
            "OsmUrl": osm_url(lat_raw, lon_raw),
            "Assessment": _assess(metres, provider),
        })

    # Pair-in-one-value parameters.
    for name in PAIR_PARAMS:
        for value in qs.get(name, []):
            match = _PAIR.match(unquote(str(value)))
            if match:
                try:
                    add(float(match.group(1)), float(match.group(2)), name,
                        match.group(1), match.group(2))
                except ValueError:
                    continue

    # Separate latitude and longitude parameters.
    lat_raw = _first(qs, LAT_PARAMS)
    lon_raw = _first(qs, LON_PARAMS)
    if _NUMBER.match(lat_raw or "") and _NUMBER.match(lon_raw or ""):
        try:
            add(float(lat_raw), float(lon_raw), "lat/lon pair",
                lat_raw.strip(), lon_raw.strip())
        except ValueError:
            pass

    return found


#: How to read an accuracy figure -- the bands _assess words per fix,
#: stated once for the Location grid's header tooltip.
ASSESSMENT_GUIDE = (
    "Each fix's own assessment is kept on the record and in every export. "
    "Reading guide: about 30 m or better is typical of a satellite fix; "
    "up to about 200 m is typical of WiFi or cell positioning (a building, "
    "not a room); beyond that it locates the device to a neighbourhood at "
    "best. A fix establishes what the device claimed, not that any "
    "particular person was present.")


def _assess(accuracy_metres, provider):
    """What this fix supports, in words a report can carry."""
    how = f" The application reported the source as {provider}." if provider else ""
    if accuracy_metres is None:
        return ("The device reported this position to the server. No accuracy "
                "was supplied, so how tightly it locates the device is "
                "unknown." + how)
    if accuracy_metres <= 30:
        band = ("an accuracy of about "
                f"{accuracy_metres:.0f} m, which is typical of a satellite fix")
    elif accuracy_metres <= 200:
        band = (f"an accuracy of about {accuracy_metres:.0f} m, typical of "
                "WiFi or cell positioning — a building, not a room")
    else:
        band = (f"an accuracy of about {accuracy_metres:.0f} m, which locates "
                "the device to a neighbourhood at best")
    return ("The device reported this position to the server with " + band +
            ". It establishes what the device claimed, not that any particular "
            "person was present." + how)


def collect(entries):
    """Every position reported by any URL in `entries`, newest first.

    Each row carries the record it came from so a finding can be traced back
    to the request that carried it.
    """
    rows = []
    for entry in entries or []:
        url = entry.get("Url") or entry.get("CleanUrl") or ""
        for fix in extract_from_url(url):
            row = dict(fix)
            row["EntryId"] = entry.get("EntryId")
            row["ContainerId"] = entry.get("ContainerId")
            row["ContainerType"] = entry.get("ContainerType", "")
            # An MSHist visit stored in LOCAL time with no recovered zone
            # has no UTC cache-write time (engine/local_clock.py). Left
            # blank, with the reason on the row; AccessedTime is not
            # substituted.
            note = entry.get("RecordTimeNote") or (
                local_clock.clock_note(entry)
                if local_clock.is_unplaced(entry) else "")
            if note:
                row["RecordTimeUTC"] = ""
                row["RecordTimeNote"] = note
            else:
                # Carved artifacts carry a datetime here where a live
                # record carries a formatted string, so coerce first.
                stamp = (entry.get("ModifiedTime")
                         or entry.get("AccessedTime") or "")
                row["RecordTimeUTC"] = str(stamp).replace(" UTC", "")
            row["Url"] = entry.get("CleanUrl") or url
            row["_entry"] = entry
            rows.append(row)
    rows.sort(key=lambda r: r.get("FixTimestamp") or r.get("RecordTimeUTC") or "",
              reverse=True)
    return rows


def cluster_summary(rows, precision=4):
    """Group fixes that round to the same position.

    A device reporting from one place produces many near-identical fixes; the
    interesting facts are how many distinct places appear and when each was
    reported.
    """
    groups = {}
    for row in rows:
        key = (round(row["Latitude"], precision),
               round(row["Longitude"], precision))
        group = groups.setdefault(key, {
            "Latitude": key[0], "Longitude": key[1], "Fixes": 0,
            "FirstSeen": "", "LastSeen": "", "Providers": set(),
            "MapsUrl": maps_url("%.*f" % (precision, key[0]),
                                "%.*f" % (precision, key[1])),
            "OsmUrl": osm_url("%.*f" % (precision, key[0]),
                              "%.*f" % (precision, key[1])),
        })
        group["Fixes"] += 1
        stamp = row.get("FixTimestamp") or row.get("RecordTimeUTC") or ""
        if stamp:
            if not group["FirstSeen"] or stamp < group["FirstSeen"]:
                group["FirstSeen"] = stamp
            if not group["LastSeen"] or stamp > group["LastSeen"]:
                group["LastSeen"] = stamp
        if row.get("Provider"):
            group["Providers"].add(row["Provider"])
    out = []
    for group in groups.values():
        group["Providers"] = ", ".join(sorted(group["Providers"]))
        out.append(group)
    out.sort(key=lambda g: g["Fixes"], reverse=True)
    return out


# ── Timestamps embedded in URLs ───────────────────────────────────────
# Applications stamp requests with the time: cache-busters, telemetry, the
# fix time on a position. Such a request time survives even when the
# record's own columns do not, and can be compared against them.

import datetime as _dt

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?")
# Epoch values, bounded to a plausible era so that ordinary large integers —
# ids, sizes, build numbers — are not read as times.
_EPOCH_RANGES = (
    ("epoch seconds", 1_000_000_000, 4_102_444_800, 1.0),
    ("epoch milliseconds", 1_000_000_000_000, 4_102_444_800_000, 1e3),
    ("epoch microseconds", 1_000_000_000_000_000, 4_102_444_800_000_000, 1e6),
)
# Windows FILETIME: 100 ns ticks since 1601.
_FILETIME_MIN = 126_000_000_000_000_000     # ~year 2000
_FILETIME_MAX = 145_000_000_000_000_000     # ~year 2060


def decode_url_timestamp(value):
    """Interpret one parameter value as a time, or return (None, "").

    Returns (ISO-8601 UTC string, format name). Only shapes that cannot
    plausibly be something else are decoded, because a number read as a date
    puts a fabricated time in front of an examiner.
    """
    text = str(value or "").strip()
    if not text:
        return None, ""
    if _ISO.match(text):
        return text, "ISO-8601 as written"
    if not text.isdigit():
        return None, ""
    number = int(text)
    if _FILETIME_MIN <= number <= _FILETIME_MAX:
        seconds = number / 1e7 - 11_644_473_600
        try:
            stamp = _dt.datetime.fromtimestamp(seconds, _dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None, ""
        return stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "Windows FILETIME"
    for name, low, high, divisor in _EPOCH_RANGES:
        if low <= number <= high:
            try:
                stamp = _dt.datetime.fromtimestamp(number / divisor,
                                                   _dt.timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None, ""
            return stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), name
    return None, ""


def timestamps_from_url(url):
    """Every decodable time in this URL's query string.

    Each row: Parameter, RawValue, DecodedUTC, Format. The raw value travels
    with the decode so the reading can be checked.
    """
    if not url or "?" not in url:
        return []
    try:
        query = parse_qs(urlparse(url).query, keep_blank_values=False)
    except ValueError:
        return []
    found = []
    for key, values in query.items():
        for value in values[:1]:
            decoded, form = decode_url_timestamp(unquote(str(value)))
            if decoded:
                found.append({
                    "Parameter": key,
                    "RawValue": unquote(str(value)),
                    "DecodedUTC": decoded,
                    "Format": form,
                })
    return found
