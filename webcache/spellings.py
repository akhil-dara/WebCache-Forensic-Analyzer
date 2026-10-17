r"""Other spellings a value is found by.

A value is shown and exported exactly as stored. Searching is different:
an examiner types what a path says, not how a URL encodes it. Every matcher
-- the filter box, a column condition and Search -- also tries the
spellings given here:

- "Tax%20docs" is also "Tax docs";
- a search term "how+to+wipe" in a query string is also "how to wipe";
- "file:///C:/Users/x" is also the Windows path "C:\Users\x", as it is
  pasted from Explorer.
"""
import re
from urllib.parse import unquote, unquote_plus

_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")


def decoded_spelling(text):
    """`text` with its percent-escapes decoded, or None when it has none
    (or decoding changes nothing). Only %XX escapes are decoded: a '+'
    stays a '+'."""
    if not isinstance(text, str) or "%" not in text or not _ESCAPE.search(text):
        return None
    decoded = unquote(text)
    return decoded if decoded != text else None


def might_have_other_spellings(text):
    """A cheap test before other_spellings: most cells have none."""
    return "%" in text or "+" in text or text[:5].lower() == "file:"


def other_spellings(text):
    """Every other spelling `text` is found by, never `text` itself:
    decoded (a '+' read as a space only in the query, where it means one),
    and, for a file: URL, the Windows path."""
    if not isinstance(text, str) or not text or not might_have_other_spellings(text):
        return []
    out = []
    head, sep, query = text.partition("?")
    if _ESCAPE.search(text) or "+" in query:
        decoded = unquote(head) + (sep + unquote_plus(query) if sep else "")
        if decoded != text:
            out.append(decoded)
    if text[:5].lower() == "file:":
        path = _windows_path(text)
        if path and path != text and path not in out:
            out.append(path)
    return out


def _windows_path(url):
    r"""file:///C:/a/b -> C:\a\b ; file://host/share/a -> \\host\share\a."""
    rest = url[5:].split("?", 1)[0].split("#", 1)[0]
    if rest.startswith("///"):
        path = rest[3:]
    elif rest.startswith("//"):
        path = "//" + rest[2:]
    else:
        return None
    return unquote(path).replace("/", "\\")
