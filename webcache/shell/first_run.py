"""The empty state shown before any evidence is open.

Shown in place of the view stack until the first Open Evidence succeeds;
MainWindow replaces it in _on_evidence_loaded and does not show it again
for the life of the window (a later Open Evidence replaces rows in place).
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import glyphs, theme
from ..widgets import copyable

#: (glyph, heading, body) -- what opening an exhibit does and never does.
_PROMISES = (
    ("lock", "Nothing is read until you press Open",
     "Every file that will be read is listed before anything is opened or "
     "hashed."),
    ("shield", "The exhibit is never written to",
     "Case notes and settings live beside the application, never beside "
     "the evidence."),
    ("trash", "Deleted records, recovered at open",
     "Carving starts as soon as the database is parsed unless you untick "
     "it, and recovered rows always say where they came from."),
)

#: promises_wrap is capped at 700px (see FirstRunView): three equal
#: columns with 14px gaps, (700 - 2*14) / 3. _CARD_WIDTH is one column;
#: each card fixes its own width to it (see _PromiseCard).
#: _CARD_TEXT_WIDTH is the column minus the card's 14+14 margins.
_CARD_WIDTH = (700 - 2 * 14) // 3
_CARD_TEXT_WIDTH = _CARD_WIDTH - 28


class _PromiseCard(QFrame):
    def __init__(self, glyph, heading, body, parent=None):
        super().__init__(parent)
        self.setObjectName("promiseCard")
        # A fixed width on the card itself. A card sized by a layout's
        # stretch factor is laid out at its minimum height, not the height
        # its wrapped text needs, because Qt does not run heightForWidth
        # for an item whose width the same pass is still deciding. With
        # the width fixed, heightForWidth is unambiguous.
        self.setFixedWidth(_CARD_WIDTH)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        icon = QLabel()
        icon.setProperty(copyable.DECORATIVE, True)  # icon-only
        icon.setPixmap(glyphs.pixmap(glyph, theme.color("primary"), 16))
        head = copyable.selectable(copyable.FixedWidthWrapLabel(heading))
        # Word-wrapped, so the heading's single-line width does not set
        # the card's (and the window's) minimum width.
        head.setWordWrap(True)
        head.setFixedWidth(_CARD_TEXT_WIDTH)
        head.setStyleSheet("font-size: 12px; font-weight: 600; background: transparent;")
        text = copyable.selectable(copyable.FixedWidthWrapLabel(body))
        text.setWordWrap(True)
        # A fixed width, not a maximum: a wrapped label with only a
        # maximum reserves its height from a sizeHint taken before its
        # final width is applied, and lines beyond that height are
        # clipped. A fixed width is known from the first layout pass.
        text.setFixedWidth(_CARD_TEXT_WIDTH)
        text.setStyleSheet("font-size: 11.5px; background: transparent; color: %s;"
                           % theme.color("muted").name())
        lay.addWidget(icon)
        lay.addWidget(head)
        lay.addWidget(text)
        self._icon_label = icon
        self._glyph = glyph

    def refresh_theme(self):
        self._icon_label.setPixmap(
            glyphs.pixmap(self._glyph, theme.color("primary"), 16))


class FirstRunView(QWidget):
    """Centred drop-target card, the three promise cards and a status line.

    openRequested triggers MainWindow.open_evidence_action, the same
    action as the sidebar's Open button, so enabled state and wording are
    defined once.

    While the first load runs, this card is on screen and says so:
    set_opening names the file and hides Open, set_elapsed shows the
    elapsed time, set_idle restores the empty state.
    """

    IDLE_HEADING = "No evidence open"

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 0, 40, 0)
        outer.addStretch(1)

        card = QFrame()
        card.setObjectName("dropCard")
        # A maximum, not a fixed width: QStackedWidget takes its minimum
        # size from every page, so a fixed width here would raise the
        # window's minimum width. The card shrinks on a small window.
        card.setMaximumWidth(560)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(40, 44, 40, 44)
        card_lay.setSpacing(20)
        card_lay.setAlignment(Qt.AlignHCenter)

        self._mark = QLabel()
        self._mark.setProperty(copyable.DECORATIVE, True)  # icon-only mark
        self._mark.setAlignment(Qt.AlignCenter)
        card_lay.addWidget(self._mark, 0, Qt.AlignHCenter)

        heading = copyable.selectable(QLabel(self.IDLE_HEADING))
        # Wrapped: an exhibit's file name can be long, and it must never
        # force the window wider.
        heading.setWordWrap(True)
        self.heading = heading
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet("font-size: 20px; font-weight: 600; background: transparent;")
        card_lay.addWidget(heading)

        self._idle_body = (
            "Open a WebCacheV01.dat to begin. Drag it here, or use the "
            "button below — choose whether to also recover deleted "
            "records, and the exhibit is never written to.")
        body = copyable.selectable(copyable.FixedWidthWrapLabel(
            self._idle_body))
        self.body = body
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignCenter)
        # A fixed width (see _PromiseCard), and a FixedWidthWrapLabel:
        # the layout asks this label's height at the column's width, and a
        # plain QLabel would answer for that wider width and be clipped.
        body.setFixedWidth(430)
        body.setStyleSheet("font-size: 13px; background: transparent; color: %s;"
                           % theme.color("muted").name())
        card_lay.addWidget(body, 0, Qt.AlignHCenter)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.open_button = QPushButton("Open Database")
        theme.mark_accent(self.open_button)
        self.open_button.setFixedHeight(38)
        self.open_button.setCursor(QCursor(Qt.PointingHandCursor))
        hint = copyable.selectable(QLabel("Ctrl+O"))
        hint.setStyleSheet(
            "font-size: 11px; font-family: 'Cascadia Mono', Consolas, monospace; "
            "background: transparent; color: %s;" % theme.color("muted2").name())
        action_row.addStretch(1)
        action_row.addWidget(self.open_button)
        action_row.addWidget(hint)
        action_row.addStretch(1)
        card_lay.addLayout(action_row)
        self._hint = hint

        self.elapsed_label = copyable.selectable(QLabel(""))
        self.elapsed_label.setAlignment(Qt.AlignCenter)
        self.elapsed_label.setVisible(False)
        card_lay.addWidget(self.elapsed_label)

        outer.addWidget(card, 0, Qt.AlignHCenter)

        # -- what opening an exhibit does and never does ----------------
        # A plain QHBoxLayout without stretch: each card has a fixed
        # _CARD_WIDTH (see _PromiseCard).
        promises = QHBoxLayout()
        promises.setSpacing(14)
        promises.setContentsMargins(0, 26, 0, 0)
        self._promise_cards = []
        for glyph, head, text in _PROMISES:
            card_w = _PromiseCard(glyph, head, text)
            promises.addWidget(card_w)
            self._promise_cards.append(card_w)
        promises_wrap = QWidget()
        promises_wrap.setLayout(promises)
        promises_wrap.setMaximumWidth(700)  # see _CARD_WIDTH's own comment
        outer.addWidget(promises_wrap, 0, Qt.AlignHCenter)

        outer.addStretch(1)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.refresh_theme()

    def set_opening(self, name):
        """Say what is being opened, on the card that is on screen.
        `name` is the chosen file's name, shown as plain text."""
        self.heading.setText("Opening %s…" % name)
        # Hashing has finished by the time this card is shown (the Open
        # dialog reports it), so it names the step that is running.
        self.body.setText("Reading the database. The exhibit is never "
                          "written to; the status bar has Cancel.")
        self.open_button.setVisible(False)
        self._hint.setVisible(False)
        self.elapsed_label.setText("")
        self.elapsed_label.setVisible(True)

    def set_elapsed(self, text):
        self.elapsed_label.setText(text)

    def set_idle(self):
        self.heading.setText(self.IDLE_HEADING)
        self.body.setText(self._idle_body)
        self.open_button.setVisible(True)
        self._hint.setVisible(True)
        self.elapsed_label.setVisible(False)

    def refresh_theme(self):
        self.elapsed_label.setStyleSheet(
            "font-size: 12px; font-family: 'Cascadia Mono', Consolas, "
            "monospace; background: transparent; color: %s;"
            % theme.color("muted").name())
        self._mark.setPixmap(glyphs.pixmap("folder", theme.color("primary"), 44))
        p = theme.PALETTES[theme.current_name()]
        self.setStyleSheet("""
            QFrame#dropCard {
                background: %(base)s;
                border: 1.5px dashed %(border)s;
                border-radius: 12px;
            }
            QFrame#promiseCard {
                background: %(base)s;
                border: 1px solid %(border)s;
                border-radius: 8px;
            }
        """ % p)
        for card in self._promise_cards:
            card.refresh_theme()
