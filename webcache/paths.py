"""Where the application keeps its own files.

Nothing the application writes is placed in the evidence folder.

- A portable (frozen) copy keeps its files beside the executable, not in
  PyInstaller's temporary unpack directory, which is deleted on exit.
- An installed copy (marked by INSTALLED_MARKER) keeps them in the
  examiner's profile under %LOCALAPPDATA%, since Program Files is not
  writable without administrator rights. Uninstalling never removes them.
- WEBCACHE_DATA_DIR overrides both, and the case-files folder alone can be
  chosen in the application (File > Case files folder).
"""
import os
import pathlib
import sys

#: Written beside the executable by the installer (packaging/webcache.iss).
INSTALLED_MARKER = "installed"
#: The folder an installed copy uses under %LOCALAPPDATA%.
DATA_FOLDER_NAME = "WebCacheAnalyzer"
#: Moves settings and case files together, for anyone who needs them
#: somewhere else.
ENV_DATA_DIR = "WEBCACHE_DATA_DIR"
#: The setting naming a case-files folder the examiner chose.
CASES_SETTING = "cases_dir"


def app_dir() -> pathlib.Path:
    """The directory the program itself is in."""
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent.parent


def is_installed() -> bool:
    return (app_dir() / INSTALLED_MARKER).is_file()


def data_dir() -> pathlib.Path:
    """Where settings (and, by default, case files) live: WEBCACHE_DATA_DIR
    when set, the examiner's profile for an installed copy, else beside the
    program."""
    override = os.environ.get(ENV_DATA_DIR, "").strip()
    if override:
        d = pathlib.Path(override)
    elif is_installed():
        base = os.environ.get("LOCALAPPDATA") or str(
            pathlib.Path.home() / "AppData" / "Local")
        d = pathlib.Path(base) / DATA_FOLDER_NAME
    else:
        return app_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_cases_dir() -> pathlib.Path:
    return data_dir() / "cases"


def chosen_cases_dir():
    """The folder the examiner chose for case files, or None."""
    from .shell import settings
    chosen = str(settings.get(CASES_SETTING, "") or "").strip()
    return pathlib.Path(chosen) if chosen else None


def cases_dir() -> pathlib.Path:
    """Case files, keyed by evidence SHA-256. Never beside the exhibit.

    The chosen folder when there is one and it can be created, otherwise
    the default, so a detached drive does not stop an exhibit opening.
    """
    chosen = chosen_cases_dir()
    if chosen is not None:
        try:
            chosen.mkdir(parents=True, exist_ok=True)
            return chosen
        except OSError:
            pass
    d = default_cases_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_path() -> pathlib.Path:
    return data_dir() / "settings.json"
