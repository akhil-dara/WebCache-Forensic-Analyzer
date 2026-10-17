"""The header every record view opens with (icon badge, title, subtitle,
Guide button), and the one-line caveat shown under its filter row.

A widget, so any view can use it without importing another view.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from . import copyable
from .note_line import NoteLine
from ..shell import glyphs, theme


class ViewHeader(QWidget):
    """Circular badge, title and subtitle. set_subtitle is called whenever
    the view's row count changes."""

    def __init__(self, icon_name, title, subtitle="", parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(12)

        self._badge = QFrame()
        self._badge.setFixedSize(34, 34)
        self._badge_icon = QLabel(self._badge)
        self._badge_icon.setGeometry(9, 9, 17, 17)
        self._badge_icon.setProperty(copyable.DECORATIVE, True)  # icon-only
        row.addWidget(self._badge, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(3)
        title_label = copyable.selectable(QLabel(title))
        title_label.setStyleSheet(
            "font-size: 19px; font-weight: 600; letter-spacing: -0.2px; "
            "background: transparent;")
        self._subtitle = copyable.selectable(QLabel(subtitle))
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(
            "font-size: 12px; background: transparent; color: %s;"
            % theme.color("muted").name())
        col.addWidget(title_label)
        col.addWidget(self._subtitle)
        row.addLayout(col, 1)
        # Opens the user guide at this screen's section. Hidden until the
        # shell connects it (show_help_button).
        self.help_button = QPushButton("Guide")
        self.help_button.setObjectName("headerHelp")
        self.help_button.setFixedHeight(28)
        self.help_button.setToolTip("How this screen works (user guide)")
        self.help_button.setAccessibleName("How this screen works")
        self.help_button.setCursor(Qt.PointingHandCursor)
        # Takes no focus, so it never holds keys meant for the view;
        # Ctrl+F1 opens the guide from the keyboard.
        self.help_button.setFocusPolicy(Qt.NoFocus)
        self.help_button.setVisible(False)
        row.addWidget(self.help_button, 0, Qt.AlignTop)

        self.refresh_theme()

    def show_help_button(self, on_click):
        self.help_button.clicked.connect(on_click)
        self.help_button.setVisible(True)

    def set_subtitle(self, text):
        self._subtitle.setText(text)

    def subtitle_text(self):
        return self._subtitle.text()

    def refresh_theme(self):
        self._badge_icon.setPixmap(
            glyphs.pixmap(self._icon_name, theme.color("primary"), 17))
        p = theme.PALETTES[theme.current_name()]
        self._badge.setStyleSheet(
            "background: %(alt_base)s; border: 1px solid %(border)s; "
            "border-radius: 17px;" % p)
        self._subtitle.setStyleSheet(
            "font-size: 12px; background: transparent; color: %s;"
            % theme.color("muted").name())


class CaveatLine(QWidget):
    """The view's one-line caveat (what it does not prove), with its
    warning glyph."""

    def __init__(self, text="", parent=None, key=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 8)
        row.setSpacing(7)
        self._icon = QLabel()
        self._icon.setFixedSize(13, 13)
        self._icon.setProperty(copyable.DECORATIVE, True)  # icon-only
        row.addWidget(self._icon, 0, Qt.AlignTop)
        self._text = copyable.selectable(QLabel(text))
        self._text.setWordWrap(True)
        self.note_line = NoteLine(self._text, self,
                                  key=("caveat:" + key) if key else None)
        row.addWidget(self._text, 1)
        row.addWidget(self.note_line.toggle, 0, Qt.AlignTop)
        self.refresh_theme()

    def set_text(self, text):
        self._text.setText(text)
        self.note_line._sync()

    def refresh_theme(self):
        self._icon.setPixmap(glyphs.pixmap("warning", theme.color("carved"), 13))
        self._text.setStyleSheet(
            "font-size: 11.5px; background: transparent; color: %s;"
            % theme.color("muted2").name())


def constant_columns(columns, rows):
    """Every column holding one identical, non-blank value in every row,
    as [(Column, value)] in declared order; [] for fewer than two rows.
    Every row is checked."""
    if len(rows) < 2:
        return []
    candidates = {c.key: (c, rows[0].get(c.key)) for c in columns
                  if rows[0].get(c.key) not in (None, "")}
    for row in rows[1:]:
        if not candidates:
            break
        for key in list(candidates):
            if row.get(key) != candidates[key][1]:
                del candidates[key]
    return [candidates[c.key] for c in columns if c.key in candidates]


def blank_columns(columns, rows):
    """Every column empty (None or "") in every row, as [Column] in
    declared order; [] for fewer than two rows."""
    if len(rows) < 2:
        return []
    candidates = [c for c in columns if rows[0].get(c.key) in (None, "")]
    for row in rows[1:]:
        if not candidates:
            break
        candidates = [c for c in candidates
                      if row.get(c.key) in (None, "")]
    return candidates


def constant_text(column, value):
    """"InPrivate: No": one constant column as the grid displays it
    (column_spec.display_text)."""
    from .column_spec import blank_label, display_text
    return "%s: %s" % (column.label,
                       display_text(value, column) or blank_label(column))


def constant_column_summary(columns, rows):
    """(Column, value, row_count) for one column holding the same
    non-blank value in every row, or None.

    Every row is checked; a column stops being checked at the first row
    that differs. Empty `rows` returns None.
    """
    if not rows:
        return None
    candidates = {c.key: (c, rows[0].get(c.key)) for c in columns}
    for row in rows[1:]:
        if not candidates:
            break
        for key in list(candidates):
            col, value = candidates[key]
            if row.get(key) != value:
                del candidates[key]
    if not candidates:
        return None
    # Origin is preferred when it is constant.
    if "Origin" in candidates and candidates["Origin"][1] not in (None, ""):
        col, value = candidates["Origin"]
        return (col, value, len(rows))
    for col, value in candidates.values():
        if value not in (None, ""):
            return (col, value, len(rows))
    return None
