"""How times are written on screen: a pattern the examiner chooses.

Only the spelling changes. The instant, its zone (each time column's
heading says UTC or LOCAL) and every export are unaffected: exports always
write ISO 8601. The grid, the search box, the value picker and the record
views all format through format_dt, so a search finds what is shown.

Patterns are strftime directives plus three for fraction digits:
%3f (milliseconds), %6f (microseconds) and %7f (100-nanosecond ticks, the
FILETIME resolution). Qt-free.
"""
import re

#: The spelling used until the examiner chooses another.
DEFAULT_PATTERN = "%Y-%m-%d %H:%M:%S"

#: (key, label, pattern) offered in the chooser, in order.
PRESETS = (
    ("iso", "ISO 8601 (24-hour)", "%Y-%m-%d %H:%M:%S"),
    ("iso_ms", "ISO 8601 with milliseconds", "%Y-%m-%d %H:%M:%S.%3f"),
    ("iso_12", "12-hour", "%Y-%m-%d %I:%M:%S.%3f %p"),
    ("excel", "Excel style", "%d-%b-%Y %H:%M:%S.%3f"),
    ("us", "US style", "%m/%d/%Y %I:%M:%S.%3f %p"),
    ("dmy_12", "Day-month-year, 12-hour", "%d-%b-%Y %I:%M:%S.%3f %p"),
    ("dmy_slash", "Day/month/year, 24-hour", "%d/%m/%Y %H:%M:%S"),
    ("ticks", "Seven fraction digits (FILETIME resolution)",
     "%Y-%m-%d %H:%M:%S.%7f"),
    ("iso_t", "ISO 8601 with T separator and milliseconds",
     "%Y-%m-%dT%H:%M:%S.%3f"),
    ("weekday", "With the weekday", "%a %d %b %Y %H:%M:%S"),
)

#: Directives a pattern may use, besides %3f/%6f/%7f.
DIRECTIVES = "aAbBdHIjmMpSyYwUW%"

_FRACTION = re.compile(r"%([367])f")
_DIRECTIVE = re.compile(r"%(.)")

_pattern = DEFAULT_PATTERN
_compiled = None


def pattern():
    """The pattern in force."""
    return _pattern


def problem(text):
    """Why `text` cannot be used as a pattern, or "" when it can."""
    if not text or not text.strip():
        return "Write a pattern, for example %Y-%m-%d %H:%M:%S."
    bare = _FRACTION.sub("", text)
    found = _DIRECTIVE.findall(bare)
    unknown = sorted({d for d in found if d not in DIRECTIVES})
    if unknown:
        return "Not a supported code: %s." % ", ".join("%" + d for d in unknown)
    if not found and not _FRACTION.search(text):
        return "The pattern has no date or time codes."
    return ""


def _compile(text):
    """[(is_fraction, piece)]: strftime pieces and fraction widths."""
    parts, pos = [], 0
    for m in _FRACTION.finditer(text):
        if m.start() > pos:
            parts.append((False, text[pos:m.start()]))
        parts.append((True, int(m.group(1))))
        pos = m.end()
    if pos < len(text):
        parts.append((False, text[pos:]))
    return parts


def format_with(text, value):
    """`value` (a datetime) written with pattern `text`."""
    out = []
    for is_fraction, piece in _compile(text):
        if is_fraction:
            out.append(("%06d" % value.microsecond + "0")[:piece])
        else:
            out.append(value.strftime(piece))
    return "".join(out)


def set_pattern(text):
    """Use `text` from now on. A pattern with a problem() is refused and
    the default is used."""
    global _pattern, _compiled
    _pattern = text if not problem(text) else DEFAULT_PATTERN
    _compiled = None if _pattern == DEFAULT_PATTERN else _compile(_pattern)


def format_dt(value):
    """`value` written with the pattern in force. The default spelling is
    built directly, since it runs for every painted cell and every cell of
    the search haystack."""
    if _compiled is None:
        return "%04d-%02d-%02d %02d:%02d:%02d" % (
            value.year, value.month, value.day,
            value.hour, value.minute, value.second)
    out = []
    for is_fraction, piece in _compiled:
        if is_fraction:
            out.append(("%06d" % value.microsecond + "0")[:piece])
        else:
            out.append(value.strftime(piece))
    return "".join(out)


_STAMP = re.compile(r"^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)"
                    r"(?:\.(\d{1,7}))?( UTC| LOCAL)?$")


def respell(text):
    """A time already written as "YYYY-MM-DD HH:MM:SS[.fff][ UTC| LOCAL]"
    (the engine's display strings), rewritten with the pattern in force,
    its zone word kept. Any other text is returned unchanged."""
    if _compiled is None or not isinstance(text, str):
        return text
    m = _STAMP.match(text)
    if m is None:
        return text
    import datetime
    frac = (m.group(7) or "").ljust(6, "0")[:6]
    try:
        value = datetime.datetime(*(int(m.group(i)) for i in range(1, 7)),
                                  microsecond=int(frac))
    except ValueError:
        return text
    return format_dt(value) + (m.group(8) or "")


def stored_text(value):
    """The instant as stored, in full: ISO 8601 with seven fraction digits
    (FILETIME resolution), "Z" for a UTC value. Shown beside the chosen
    spelling so the stored value is always one hover away."""
    text = value.strftime("%Y-%m-%dT%H:%M:%S.") + ("%06d0" % value.microsecond)
    offset = value.utcoffset()
    if offset is None:
        return text
    if not offset:
        return text + "Z"
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return text + "%s%02d:%02d" % (sign, abs(minutes) // 60, abs(minutes) % 60)


def tooltip_text(value):
    """A time cell's tooltip: the stored value, and how it is shown."""
    return "Stored: %s\nShown as: %s (View > Time display format)" % (
        stored_text(value), _pattern)
