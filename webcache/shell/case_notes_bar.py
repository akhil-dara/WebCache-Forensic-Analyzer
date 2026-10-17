"""Tags and comments on the record (or records) in front of the examiner:
one click per tag, Enter to add a comment, saved to the case file as each
is made. Used by the record dialog and the details pane, so the two can
never tag differently. The rules are case_notes'; this is only their
controls."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
                               QWidget)

from ..widgets import copyable
from ..widgets.flow_layout import FlowLayout
from ..widgets.quick_filter_chip import QuickFilterChip
from . import case_notes, theme

NO_CASE_TEXT = ("Notes are kept in this exhibit's case file, which could "
                "not be opened, so tags and comments cannot be saved.")
NOT_A_RECORD_TEXT = ("This row is not a record (a summary or a raw table "
                     "row), so it cannot carry a tag or a comment.")


class CaseNotesBar(QWidget):
    #: A tag or comment was saved.
    changed = Signal()

    def __init__(self, case, rows, author="", parent=None, compact=False):
        """`compact` (the details pane): tags on one line, the new-tag
        and comment boxes on the next, so a narrow pane shows every tag
        whole."""
        super().__init__(parent)
        self._case = case
        self._rows = [r for r in (rows or ()) if case_notes.is_taggable(r)]
        self._author = author or ""
        self._buttons = {}

        self._status = copyable.selectable(QLabel(""))
        self._status.setTextFormat(Qt.PlainText)
        self._status.setWordWrap(True)

        self._tags_row = QHBoxLayout()
        self._tags_row.setSpacing(6)
        # The title and the chips flow onto further lines when the space
        # is narrow, so every chip keeps its whole label.
        self._chips = QWidget()
        self._chip_flow = FlowLayout(self._chips)
        title = copyable.selectable(QLabel("Tags"))
        title.setTextFormat(Qt.PlainText)
        title.setStyleSheet("font-weight: 600;")
        self._chip_flow.addWidget(title)
        self._chips_at = self._chip_flow.count()
        self._tags_row.addWidget(self._chips, 1)
        self.new_tag_box = QLineEdit(placeholderText="New tag…")
        self.new_tag_box.setMaximumWidth(160)
        self.new_tag_box.setToolTip("Type a tag and press Enter")
        self.new_tag_box.returnPressed.connect(self._add_new_tag)
        self._entry_row = QHBoxLayout()
        self._entry_row.setSpacing(6)
        (self._entry_row if compact else self._tags_row).addWidget(
            self.new_tag_box)

        self._comments = copyable.selectable(QLabel(""))
        self._comments.setWordWrap(True)
        self._comments.setTextFormat(Qt.PlainText)
        self.comment_box = QLineEdit(
            placeholderText="Add a comment, then press Enter")
        self.comment_box.setMinimumWidth(220)
        self.comment_box.returnPressed.connect(self._add_comment)
        # One line, not two: the record's fields are what this dialog is
        # for, and a second row of notes cost two of them.
        (self._entry_row if compact else self._tags_row).addWidget(
            self.comment_box, 2)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addWidget(self._status)
        root.addLayout(self._tags_row)
        root.addLayout(self._entry_row)
        root.addWidget(self._comments)
        self._refresh()

    # --- reading ------------------------------------------------------

    def tag_button(self, tag):
        return self._buttons.get(tag)

    def status_text(self):
        return self._status.text()

    def comments_text(self):
        return self._comments.text()

    def _usable(self):
        return self._case is not None and bool(self._rows)

    # --- the controls ---------------------------------------------------

    def _refresh(self):
        usable = self._usable()
        if self._case is None:
            self._status.setText(NO_CASE_TEXT)
        elif not self._rows:
            self._status.setText(NOT_A_RECORD_TEXT)
        else:
            self._status.setText("")
        self._status.setVisible(not usable)
        self._status.setStyleSheet("color: %s;" % theme.color("muted").name())
        counts = case_notes.tag_counts(self._case, self._rows) if usable else {}
        total = len(self._rows)
        for tag in case_notes.known_tags(self._case):
            button = self._buttons.get(tag)
            if button is None:
                button = QuickFilterChip(tag, accent="primary")
                button.clicked.connect(
                    lambda _c=False, t=tag: self._toggle(t))
                self._chip_flow.insertWidget(
                    self._chips_at + len(self._buttons), button)
                self._buttons[tag] = button
            n = counts.get(tag, 0)
            button.blockSignals(True)
            button.setChecked(usable and n == total and total > 0)
            button.blockSignals(False)
            if total > 1:
                button.setToolTip("%s of %s selected records carry “%s”. "
                                  "Click to put it on all of them, or take "
                                  "it off when every one has it."
                                  % (format(n, ","), format(total, ","), tag))
            else:
                button.setToolTip("Click to %s “%s”." % (
                    "remove" if n else "add", tag))
            button.setVisible(usable)
        self.new_tag_box.setVisible(usable)
        self.comment_box.setVisible(usable)
        lines = []
        if usable and total == 1:
            for c in case_notes.comments_of(self._case, self._rows[0]):
                who = (" · %s" % c["author"]) if c.get("author") else ""
                lines.append("%s%s — %s" % (c["created"], who, c["comment"]))
        self._comments.setText("\n".join(lines))
        self._comments.setVisible(bool(lines))
        # Nothing to do here, nothing on screen: a dialog's fields are
        # worth more than a sentence about notes that cannot be kept.
        # The reason stays readable (status_text) for whoever asks.
        self.setHidden(not usable)

    def _toggle(self, tag):
        counts = case_notes.tag_counts(self._case, self._rows)
        on = counts.get(tag, 0) < len(self._rows)
        case_notes.set_tag(self._case, self._rows, tag, on)
        self._refresh()
        self.changed.emit()

    def _add_new_tag(self):
        tag = self.new_tag_box.text().strip()
        if not tag or not self._usable():
            return
        case_notes.set_tag(self._case, self._rows, tag, True)
        self.new_tag_box.clear()
        self._refresh()
        self.changed.emit()

    def _add_comment(self):
        text = self.comment_box.text().strip()
        if not text or not self._usable():
            return
        case_notes.add_comment(self._case, self._rows, text, self._author)
        self.comment_box.clear()
        self._refresh()
        self.changed.emit()
