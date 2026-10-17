"""The prompt shown while something is dragged over the window.

It covers the content area and states whether the drop will be taken: the
exhibit drop_target resolved, or drop_target's refusal in its own words, in
the accepting or the refusing colour.

It never accepts drops itself (setAcceptDrops(False) and
WA_TransparentForMouseEvents), since Qt hands a drop to the first widget
under the cursor that accepts drops. MainWindow hides it on drag-leave and
at the start of dropEvent. Colours are read each time it is shown, so a
theme change applies.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from . import glyphs, theme
from ..widgets import copyable

#: The two states a drag can be in, and the palette role each is painted
#: in: the primary colour when the drop will be taken, the warning colour
#: (not error red) when it will not.
_TONES = {"ready": ("primary", "database"), "refused": ("warn", "warning")}

#: Shown on every accepting drag, under the file's name.
OPEN_PROMISE = "Nothing is read until you press Open."

#: A fixed width, shared with the labels inside (_TEXT_WIDTH), so wrapped
#: refusal text is measured at the width it is painted at.
_CARD_WIDTH = 560
_CARD_MARGIN = 44
_TEXT_WIDTH = _CARD_WIDTH - 2 * _CARD_MARGIN


class DropOverlay(QWidget):
    """The prompt itself. Created once with the window, shown per drag."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Invisible to the drag manager and the mouse (see the module
        # docstring).
        self.setObjectName("dropOverlay")
        # A plain QWidget paints a stylesheet background only with this
        # attribute.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(False)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._tone = "ready"
        self._accent = theme.color("primary")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(60, 60, 60, 60)
        outer.addStretch(1)

        self._card = QFrame()
        self._card.setObjectName("dropOverlayCard")
        self._card.setFixedWidth(_CARD_WIDTH)  # see _CARD_WIDTH
        card_lay = QVBoxLayout(self._card)
        card_lay.setContentsMargins(_CARD_MARGIN, 40, _CARD_MARGIN, 40)
        card_lay.setSpacing(14)
        card_lay.setAlignment(Qt.AlignHCenter)

        self._mark = QLabel()
        self._mark.setProperty(copyable.DECORATIVE, True)  # icon-only mark
        self._mark.setAlignment(Qt.AlignCenter)
        card_lay.addWidget(self._mark, 0, Qt.AlignHCenter)

        self._message = copyable.selectable(copyable.FixedWidthWrapLabel(""))
        self._message.setWordWrap(True)
        self._message.setAlignment(Qt.AlignCenter)
        self._message.setFixedWidth(_TEXT_WIDTH)
        card_lay.addWidget(self._message, 0, Qt.AlignHCenter)

        self._detail = copyable.selectable(copyable.FixedWidthWrapLabel(""))
        self._detail.setWordWrap(True)
        self._detail.setAlignment(Qt.AlignCenter)
        self._detail.setFixedWidth(_TEXT_WIDTH)
        card_lay.addWidget(self._detail, 0, Qt.AlignHCenter)

        outer.addWidget(self._card, 0, Qt.AlignHCenter)
        outer.addStretch(1)
        self.hide()

    # --- what it is saying, for the window and for tests ------------------

    def message(self):
        """The headline: the exhibit's name, or the refusal."""
        return self._message.text()

    def detail(self):
        return self._detail.text()

    def tone(self):
        return self._tone

    def accent(self):
        """The colour the current tone is painted in, as read at the last
        show()."""
        return self._accent

    # --- showing it -------------------------------------------------------

    def show_for(self, tone, message, detail=""):
        """Show and raise the prompt for one drag, styled from the palette
        in force."""
        role, glyph = _TONES[tone]
        self._tone = tone
        self._accent = theme.color(role)
        palette = theme.PALETTES[theme.current_name()]
        accent = self._accent.name()

        self._mark.setPixmap(glyphs.pixmap(glyph, self._accent, 40))
        self._message.setText(message)
        self._message.setStyleSheet(
            "font-size: 17px; font-weight: 600; background: transparent; "
            "color: %s;" % palette["text"])
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))
        self._detail.setStyleSheet(
            "font-size: 12.5px; background: transparent; color: %s;"
            % palette["muted"])
        self.setStyleSheet("""
            QWidget#dropOverlay {
                background: %(wash)s;
            }
            QFrame#dropOverlayCard {
                background: %(base)s;
                border: 2px dashed %(accent)s;
                border-radius: 14px;
            }
        """ % {"wash": _wash(palette["window"]), "base": palette["base"],
               "accent": accent})
        # The card is sized to its contents' height for this width; the
        # layout's cached hint describes the previous drag's text.
        self._card.layout().invalidate()
        self._card.setFixedHeight(self._card.sizeHint().height())
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()


def _wash(hex_colour):
    """The window's background at 85%, so the view behind stays
    recognisable."""
    return "rgba(%d, %d, %d, 217)" % (
        int(hex_colour[1:3], 16), int(hex_colour[3:5], 16),
        int(hex_colour[5:7], 16))
