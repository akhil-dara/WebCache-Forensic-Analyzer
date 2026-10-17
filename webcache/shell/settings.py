"""Window geometry, theme, last evidence directory, column widths.

Stored with the application, never in the evidence folder. A missing or
corrupt file falls back to the defaults.
"""
import copy
import json

from .. import paths

DEFAULTS = {
    "theme": "dark",
    "last_evidence_dir": "",
    # Where exports last went. Separate from "last_evidence_dir" so a save
    # dialog never opens in the evidence folder.
    "last_export_dir": "",
    "window_geometry": "",
    "column_state": {},
    # The first launch opens maximised; closeEvent stores the real state.
    "window_maximized": True,
    # The nav rail collapsed to an icon strip.
    "sidebar_collapsed": False,
    # Grids wrap long values by default.
    "grid_wrap": True,
    "details_pane": True,
    # How times are written on screen (widgets/time_format.py).
    "time_format": "%Y-%m-%d %H:%M:%S",
}


def load():
    try:
        with open(paths.settings_path(), encoding="utf-8") as fh:
            stored = json.load(fh)
    except (OSError, ValueError):
        stored = {}
    # A deep copy, so nested values such as "column_state" never alias
    # DEFAULTS.
    merged = copy.deepcopy(DEFAULTS)
    if isinstance(stored, dict):
        merged.update(stored)
    return merged


def get(key, default=None):
    return load().get(key, DEFAULTS.get(key, default))


def save(**changes):
    data = load()
    data.update(changes)
    try:
        tmp = paths.settings_path().with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        tmp.replace(paths.settings_path())
    except (OSError, ValueError):
        # An unwritable settings path (read-only media) must not stop the
        # application closing; the setting is simply not kept.
        pass
    return data
