"""View > Time display format: choose how times are written on screen.

A preset, or the examiner's own pattern built from strftime codes plus
%3f/%6f/%7f for fraction digits, with a live preview. Only the on-screen
spelling changes; exports always write ISO 8601 (see widgets/time_format).
"""
import datetime

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox,
                               QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton,
                               QVBoxLayout)

from ..widgets import time_format as tf

#: The instant every example is written from.
EXAMPLE = datetime.datetime(2025, 1, 13, 16, 38, 51, 504000)

#: The codes offered as buttons under "Your own pattern", with what each
#: writes, for the tooltip.
CODES = (
    ("%d", "day of the month, 01-31"), ("%b", "month name, short"),
    ("%B", "month name, full"), ("%m", "month, 01-12"),
    ("%Y", "year, four digits"), ("%y", "year, two digits"),
    ("%H", "hour, 00-23"), ("%I", "hour, 01-12"),
    ("%M", "minute"), ("%S", "second"),
    ("%3f", "milliseconds"), ("%6f", "microseconds"),
    ("%7f", "100-nanosecond ticks (FILETIME resolution)"),
    ("%p", "AM or PM"), ("%a", "weekday, short"), ("%j", "day of the year"),
)

OWN_KEY = "own"

NOTE = ("Only how times are written on screen changes. The instant and its "
        "zone stay as stored (each time column names UTC or LOCAL), and "
        "every export writes ISO 8601.")


def _mono():
    font = QFont("Cascadia Mono")
    font.setStyleHint(QFont.Monospace)
    return font


class TimeFormatDialog(QDialog):
    """Returns the chosen pattern from chosen_pattern() when accepted."""

    def __init__(self, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Time display format")
        root = QVBoxLayout(self)
        heading = QLabel("Choose how times are written")
        heading.setObjectName("dialogHeading")
        font = heading.font(); font.setPointSizeF(font.pointSizeF() * 1.25)
        font.setBold(True); heading.setFont(font)
        root.addWidget(heading)
        root.addWidget(QLabel("The examples show one value: 13 January 2025, "
                              "16:38:51.504."))

        grid = QGridLayout()
        self.group = QButtonGroup(self)
        self.buttons = {}
        presets = list(tf.PRESETS) + [(OWN_KEY, "Write your own (below)", "")]
        for row, (key, label, pattern) in enumerate(presets):
            button = QRadioButton(label)
            self.group.addButton(button)
            self.buttons[key] = button
            grid.addWidget(button, row, 0)
            if pattern:
                example = QLabel(tf.format_with(pattern, EXAMPLE))
                example.setFont(_mono())
                example.setToolTip(pattern)
                grid.addWidget(example, row, 1)
        root.addLayout(grid)

        own = QFrame()
        own.setFrameShape(QFrame.StyledPanel)
        own_box = QVBoxLayout(own)
        own_box.addWidget(QLabel("<b>Your own pattern</b>"))
        self.own_edit = QLineEdit()
        self.own_edit.setFont(_mono())
        own_box.addWidget(self.own_edit)
        codes = QGridLayout()
        for i, (code, meaning) in enumerate(CODES):
            b = QPushButton(code)
            b.setToolTip(meaning)
            b.setFont(_mono())
            b.clicked.connect(lambda _c=False, c=code: self._insert(c))
            codes.addWidget(b, i // 8, i % 8)
        own_box.addLayout(codes)
        self.preview = QLabel()
        self.preview.setFont(_mono())
        own_box.addWidget(self.preview)
        self.problem_label = QLabel()
        self.problem_label.setWordWrap(True)
        own_box.addWidget(self.problem_label)
        root.addWidget(own)

        note = QLabel(NOTE)
        note.setWordWrap(True)
        root.addWidget(note)

        self.box = QDialogButtonBox(QDialogButtonBox.Apply
                                    | QDialogButtonBox.Cancel)
        self.box.button(QDialogButtonBox.Apply).clicked.connect(self.accept)
        self.box.rejected.connect(self.reject)
        root.addWidget(self.box)

        match = next((k for k, _l, p in tf.PRESETS if p == current), OWN_KEY)
        self.buttons[match].setChecked(True)
        self.own_edit.setText(current)
        self.own_edit.textEdited.connect(self._own_edited)
        self.group.buttonToggled.connect(lambda *_: self._update())
        self._update()

    def _insert(self, code):
        self.own_edit.insert(code)
        self._own_edited()

    def _own_edited(self, *_):
        self.buttons[OWN_KEY].setChecked(True)
        self._update()

    def chosen_pattern(self):
        for key, _label, pattern in tf.PRESETS:
            if self.buttons[key].isChecked():
                return pattern
        return self.own_edit.text()

    def _update(self):
        pattern = self.chosen_pattern()
        problem = tf.problem(pattern)
        self.problem_label.setText(problem)
        self.preview.setText("Preview:  " + (
            tf.format_with(pattern, EXAMPLE) if not problem else "—"))
        self.box.button(QDialogButtonBox.Apply).setEnabled(not problem)
