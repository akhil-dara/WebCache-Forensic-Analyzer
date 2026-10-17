"""Where a wrapped value may break, shared by the record grid and
WrappingText.

A zero-width space is a break opportunity, not a break: the layout uses
one only when a line would otherwise overflow. Opportunities are placed:

  * after URL and path punctuation -- but never a "." or "," that joins
    two digits;
  * at a CamelCase hump, so "BackgroundTransfer" breaks between the
    words and not at whatever character the column ran out on;
  * in the grid only, inside a run with none of those (a hash, a base64
    blob), every _HARD_BREAK_RUN characters -- the run counter restarts
    at "-" and "/" (a SID breaks at its hyphens, never inside a
    sub-authority) and at every break already placed.

These characters exist only in drawn and measured text; copy, tooltip,
filter, sort and exports read the model, which never holds one.
"""
import re

#: Zero-width space: a line-break opportunity that paints nothing.
ZWSP = "​"
#: Punctuation a wrapped value may break after. Qt's own line breaker
#: (UAX #14) already breaks after "/" and "-" (and never between a sign
#: and its number), but not after "&", "=", "." or "_" -- so a query
#: string reads to it as one word. "?" is listed because UAX #14 keeps
#: it glued to what follows in some contexts.
SOFT_BREAK_AFTER = re.compile(
    r"([&=;:_+#%@|\\]|\?(?!\d)|(?<!\d)[.,]|[.,](?!\d))(?=\S)")
#: A hyphen-joined chain of four or more groups (a SID, a GUID): Qt never
#: breaks between a hyphen and a digit, so without an opportunity here a
#: SID is one unbreakable line, clipped at the cell edge. Three groups (a
#: date) are left alone.
HYPHEN_CHAIN = re.compile(r"\w+(?:-\w+){3,}")
#: A CamelCase hump: lower/digit then Upper ("BackgroundTransfer"), or
#: the end of an acronym before a word ("HTTPServer" -> HTTP|Server).
HUMP = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
#: A run this long with still no break opportunity is broken every
#: this-many characters. Longer than any prose word, so titles still wrap
#: between words.
HARD_BREAK_RUN = 24
LONG_RUN = re.compile(r"[^\s\-/%s]{%d}(?=[^\s\-/%s])"
                      % (ZWSP, HARD_BREAK_RUN, ZWSP))


def with_soft_breaks(text):
    """`text` with break opportunities at separators and humps only."""
    if len(text) <= 1:
        return text
    text = HYPHEN_CHAIN.sub(lambda m: m.group(0).replace("-", "-" + ZWSP), text)
    return HUMP.sub(ZWSP, SOFT_BREAK_AFTER.sub(r"\1" + ZWSP, text))


def breakable(text):
    """with_soft_breaks plus the hard-break run, for a grid cell: Qt's
    item views wrap with WordWrap, which lays a run with no opportunity
    out as one over-long line and clips it."""
    if len(text) <= 16:
        return text
    return LONG_RUN.sub(r"\g<0>" + ZWSP, with_soft_breaks(text))
