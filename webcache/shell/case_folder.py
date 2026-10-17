"""File > Case files folder: where tags, comments and case metadata are
kept, and choosing another folder.

The default is the program's folder for a portable copy and the examiner's
profile for an installed one (paths.py). Choosing a folder copies the
existing case files into it; nothing is moved or deleted. A folder inside
an evidence folder is refused.
"""
import pathlib
import shutil

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

from .. import paths
from ..widgets import copyable
from . import settings
from .case_store import SUFFIX


def _inside(child, parent):
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def check_folder(folder, evidence_dirs=()):
    """'' when FOLDER can hold case files, else the reason it cannot."""
    folder = pathlib.Path(folder)
    for evidence in evidence_dirs:
        if _inside(folder, pathlib.Path(evidence)):
            return ("That folder is inside the evidence folder. Nothing this "
                    "tool writes is ever kept beside the exhibit.")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".webcache-write-check"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        return "That folder cannot be written to: %s" % (exc.strerror or exc)
    return ""


def copy_case_files(source, target):
    """Copy every case file in SOURCE that TARGET lacks. Returns
    (copied, already there). Originals are left where they were."""
    source, target = pathlib.Path(source), pathlib.Path(target)
    copied = skipped = 0
    if not source.is_dir() or _inside(source, target) and _inside(target, source):
        return 0, 0
    for path in sorted(source.glob("*" + SUFFIX)):
        dest = target / path.name
        if dest.exists():
            skipped += 1
            continue
        shutil.copy2(path, dest)
        copied += 1
    return copied, skipped


def change_cases_dir(folder, evidence_dirs=()):
    """Make FOLDER (None: the default) the case-files folder, copying the
    case files from the folder in use. Returns (ok, message)."""
    current = paths.cases_dir()
    target = paths.default_cases_dir() if folder is None else pathlib.Path(folder)
    reason = check_folder(target, evidence_dirs)
    if reason:
        return False, reason
    try:
        copied, skipped = copy_case_files(current, target)
    except OSError as exc:
        return False, "Copying the case files failed: %s" % (exc.strerror or exc)
    settings.save(**{paths.CASES_SETTING: "" if folder is None else str(target)})
    said = "Case files are now kept in %s." % target
    if copied:
        said += " %d case file%s copied from %s (the originals are still there)." % (
            copied, "" if copied == 1 else "s", current)
    if skipped:
        said += " %d already there %s left as they were." % (
            skipped, "was" if skipped == 1 else "were")
    return True, said


class CaseFolderDialog(QDialog):

    def __init__(self, evidence_dirs=(), before_change=None, on_changed=None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Case files folder")
        self.setMinimumWidth(560)
        self._evidence_dirs = list(evidence_dirs)
        #: The window closes the open case file before a copy (a copy of
        #: an open database can be torn) and reopens it after.
        self._before_change = before_change
        self._on_changed = on_changed
        intro = QLabel(
            "Tags, comments and case details are kept in one case file per "
            "exhibit, in this folder. Never beside the evidence.")
        intro.setWordWrap(True)
        self.path_label = copyable.selectable(QLabel(""))
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet("font-weight: 600;")
        self.where_label = QLabel("")
        self.where_label.setWordWrap(True)
        self.status_label = copyable.selectable(QLabel(""))
        self.status_label.setWordWrap(True)
        self.copy_button = QPushButton("Copy path")
        self.change_button = QPushButton("Change…")
        self.default_button = QPushButton("Use default")
        close = QPushButton("Close")
        self.copy_button.clicked.connect(self._copy)
        self.change_button.clicked.connect(self._choose)
        self.default_button.clicked.connect(lambda: self._apply(None))
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        for b in (self.copy_button, self.change_button, self.default_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(close)
        root = QVBoxLayout(self)
        for w in (intro, self.path_label, self.where_label, self.status_label):
            root.addWidget(w)
        root.addLayout(buttons)
        self.refresh()

    def refresh(self):
        in_use = paths.cases_dir()
        chosen = paths.chosen_cases_dir()
        self.path_label.setText(str(in_use))
        if chosen is None:
            where = ("The default for this %s copy."
                     % ("installed" if paths.is_installed() else "portable"))
        elif chosen.resolve() == in_use.resolve():
            where = "A folder you chose."
        else:
            where = ("The folder you chose (%s) is not available, so the "
                     "default is in use." % chosen)
        self.where_label.setText(where)
        self.default_button.setEnabled(chosen is not None)

    def _copy(self):
        QGuiApplication.clipboard().setText(self.path_label.text())

    def _choose(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the case files folder", self.path_label.text())
        if folder:
            self._apply(folder)

    def _apply(self, folder):
        if self._before_change is not None:
            self._before_change()
        try:
            ok, message = change_cases_dir(folder, self._evidence_dirs)
        finally:
            if self._on_changed is not None:
                self._on_changed()
        self.status_label.setText(message)
        self.refresh()
