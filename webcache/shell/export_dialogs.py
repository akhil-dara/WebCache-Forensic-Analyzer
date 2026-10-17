"""The dialog shown when an export destination is refused.

A refused destination opens a modal dialog that stays until answered, so a
refusal is never mistaken for a button that did nothing. It offers:

  Save it there          -- the same filename, in a folder that is not the
                            evidence folder (export_target.safe_alternative).
  Choose another folder… -- reopens the chooser at the safe path, keeping
                            the pending job.
  Cancel the export      -- nothing is written, and the status bar says so.

There is no option to write into the evidence folder.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QVBoxLayout)

from . import theme
from ..widgets import copyable

#: The reason for the refusal, stated every time.
STANDING_RULE = ("The evidence folder is read-only for the whole life of "
                 "the case. Nothing this tool writes is ever placed inside "
                 "it — not an export, not a case file, not a log.")


class SafeFolderDialog(QDialog):
    CHOSE_SAFE, CHOSE_ELSEWHERE, CANCELLED = 1, 2, 3

    def __init__(self, parent, reason, safe_path):
        super().__init__(parent)
        self.setWindowTitle("That folder holds the evidence")
        self._outcome = self.CANCELLED
        self._path = safe_path

        reason_label = copyable.selectable(QLabel(reason))
        reason_label.setWordWrap(True)
        rule_label = copyable.selectable(QLabel(STANDING_RULE))
        rule_label.setWordWrap(True)
        offer_label = QLabel("Offered instead:\n%s" % safe_path)
        offer_label.setWordWrap(True)
        # Selectable text, never a link: the path is on the examiner's
        # machine and is copied, never opened.
        copyable.selectable(offer_label)

        p = theme.PALETTES[theme.current_name()]
        reason_label.setStyleSheet(
            "font-size: 12.5px; font-weight: 600; color: %s;" % p["warn"])
        rule_label.setStyleSheet("font-size: 12px; color: %s;" % p["muted"])
        offer_label.setStyleSheet(
            "font-family: 'Cascadia Mono', Consolas, monospace; "
            "font-size: 11.5px; color: %s;" % p["text"])

        buttons = QDialogButtonBox()
        save_here = buttons.addButton("Save it there",
                                      QDialogButtonBox.AcceptRole)
        save_here.setDefault(True)
        elsewhere = buttons.addButton("Choose another folder…",
                                      QDialogButtonBox.ActionRole)
        cancel = buttons.addButton("Cancel the export",
                                   QDialogButtonBox.RejectRole)
        save_here.clicked.connect(lambda: self._finish(self.CHOSE_SAFE))
        elsewhere.clicked.connect(lambda: self._finish(self.CHOSE_ELSEWHERE))
        cancel.clicked.connect(lambda: self._finish(self.CANCELLED))

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(reason_label)
        root.addWidget(rule_label)
        root.addWidget(offer_label)
        root.addWidget(buttons)

    def _finish(self, outcome):
        self._outcome = outcome
        # accept() for both forward paths and reject() for cancel, so
        # exec() keeps its usual meaning; outcome() tells the forward paths
        # apart.
        if outcome == self.CANCELLED:
            self.reject()
        else:
            self.accept()

    def outcome(self):
        return self._outcome

    def path(self):
        return self._path
