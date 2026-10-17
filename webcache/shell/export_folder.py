"""Show an export's folder: the only place the application opens anything.

Opens the folder the examiner exported into, never a file, and refuses any
folder inside an evidence directory (the examined machine's paths are
copied, never opened)."""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from . import export_target

REFUSE_EVIDENCE = ("Not opened: that folder holds the evidence. Only your "
                   "own export folder is opened; evidence folders are "
                   "copied, never opened.")
REFUSE_MISSING = "Not opened: that export folder no longer exists."


def _open_folder(folder):
    """The single launch. Tests and screen grabs replace this."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def folder_for(path):
    """The folder Show in folder means for `path`: a folder is itself
    (a bundle), a file is the folder holding it."""
    full = os.path.abspath(path)
    return full if os.path.isdir(full) else os.path.dirname(full)


def show_in_folder(path, evidence_dirs):
    """Open the folder holding `path`. Returns "" on success, or the
    sentence saying why it was refused. The refusal is checked on the
    resolved folder (export_target._norm resolves links), so a junction
    into the evidence folder is refused too."""
    if not path:
        return REFUSE_MISSING
    folder = folder_for(path)
    if not os.path.isdir(folder):
        return REFUSE_MISSING
    if export_target.refuse_reason(folder, (), evidence_dirs):
        return REFUSE_EVIDENCE
    _open_folder(folder)
    return ""
