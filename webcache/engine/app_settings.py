"""Application preferences that outlive a single evidence file.

Preferences about the tool, not findings about the evidence, so they are
kept with the application and never in a case file or the evidence folder.
A missing, empty, truncated or newer-version file never stops the tool
opening; the defaults apply.
"""

import io
import json
import os

FILENAME = "settings.json"

# Only these are read back. An unknown key in the file is ignored rather than
# trusted, so a hand-edited or newer file cannot inject arbitrary state.
DEFAULTS = {
    "theme": None,              # None = whatever the theme module defaults to
    "sidebar_collapsed": False,
    "timezone": "UTC",          # how UTC timestamps are shown
    "last_evidence_dir": "",    # where the file picker opens next time
    "browser_list_collapsed": False,   # Table Browser's list of tables
}


#: Overrides the location, for tests and for anyone who wants preferences
#: somewhere else. Set WEBCACHE_SETTINGS to a full file path.
ENV_OVERRIDE = "WEBCACHE_SETTINGS"


def settings_path():
    """Kept with the application. WEBCACHE_SETTINGS overrides the path,
    so a test run never writes to the real file."""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return override
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), FILENAME)


def load():
    """Current preferences, defaults filled in for anything absent."""
    values = dict(DEFAULTS)
    try:
        with io.open(settings_path(), encoding="utf-8") as handle:
            stored = json.load(handle)
    except Exception:
        return values           # missing, unreadable, or not JSON: use defaults
    if not isinstance(stored, dict):
        return values
    for key in DEFAULTS:
        if key in stored and isinstance(stored[key], type(DEFAULTS[key])) \
                or (DEFAULTS[key] is None and key in stored):
            values[key] = stored[key]
    return values


def save(**changes):
    """Merge `changes` into the stored preferences.

    Returns True when they reached disk. A read-only install, a locked file
    or a full disk means the preference is not kept; this is reported, not
    raised.
    """
    values = load()
    for key, value in changes.items():
        if key not in DEFAULTS:
            # An unknown key from a caller is an error, so a new
            # preference is never dropped silently.
            raise KeyError(
                "unknown setting %r -- add it to app_settings.DEFAULTS" % key)
        values[key] = value
    try:
        path = settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Write beside and replace, so an interrupted write cannot leave a
        # half-written file that the next launch refuses to parse.
        temp = path + ".tmp"
        with io.open(temp, "w", encoding="utf-8", newline="") as handle:
            json.dump(values, handle, indent=2, sort_keys=True)
        os.replace(temp, path)
        return True
    except Exception:
        return False
