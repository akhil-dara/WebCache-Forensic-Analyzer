"""A cell with its keyword highlighted where it occurs.

Search's context column shows about forty characters either side of a
match; each case-insensitive occurrence of the keyword is painted on the
accent colour. The value is drawn through a QTextDocument, so every
character is HTML-escaped before the highlight span is added, and spaces
are preserved (white-space: pre, or pre-wrap while the grid wraps).

A WrappingDelegate, so the grid's Wrap switch and row fit apply as in any
other column. The keyword is matched against the displayed text, not the
break characters the delegate inserts.
"""
import html
import re

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QAbstractTextDocumentLayout, QBrush, QPalette,
                           QTextDocument, QTextOption)
from PySide6.QtWidgets import (QApplication, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem)

from ..shell import theme
from .records_table import ROW_LINE_CAP, WrappingDelegate

_PAD_X = 9
_ELLIPSIS = "\u2026"
_WORD_JOINER = "\u2060"


def highlight_html(text, keyword, fg, bg):
    """`text` escaped, with every case-insensitive occurrence of `keyword`
    wrapped in one colour span. The span is the only markup in the
    result; the evidence around and inside it is escaped first."""
    text = "" if text is None else str(text)
    if not keyword:
        return html.escape(text)
    out, pos = [], 0
    for m in re.finditer(re.escape(keyword), text, re.IGNORECASE):
        out.append(html.escape(text[pos:m.start()]))
        out.append('<span style="color:%s;background:%s">%s</span>'
                   % (fg, bg, html.escape(m.group(0))))
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


class KeywordDelegate(WrappingDelegate):
    """Paints a cell's text with `keyword` highlighted. Set `.keyword` to
    the search that produced the rows; "" paints plain escaped text."""

    def __init__(self, parent=None):
        super().__init__(parent, line_cap=ROW_LINE_CAP)
        self.keyword = ""

    def _plain_option(self, option, index):
        """The style option WITHOUT WrappingDelegate's break points, so
        the keyword is found in the text as displayed."""
        opt = QStyleOptionViewItem(option)
        QStyledItemDelegate.initStyleOption(self, opt, index)
        return opt

    def _document(self, option, text):
        text = "" if text is None else str(text)
        if text.startswith(_ELLIPSIS):
            # A word joiner keeps a leading cut mark on the line it
            # belongs to.
            text = _ELLIPSIS + _WORD_JOINER + text[1:]
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDocumentMargin(0)
        wraps = bool(option.features & QStyleOptionViewItem.WrapText)
        text_option = QTextOption()
        text_option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere
                                if wraps else QTextOption.NoWrap)
        doc.setDefaultTextOption(text_option)
        doc.setTextWidth(max(1, option.rect.width() - 2 * _PAD_X))
        doc.setHtml('<div style="white-space:%s">%s</div>'
                    % ("pre-wrap" if wraps else "pre", highlight_html(text, self.keyword,
                                     theme.color("on_primary").name(),
                                     theme.color("primary").name())))
        return doc

    def paint(self, painter, option, index):
        opt = self._plain_option(option, index)
        text = opt.text
        opt.text = ""
        bg = opt.backgroundBrush
        if bg.style() != Qt.NoBrush:
            painter.save()
            painter.fillRect(option.rect, bg)
            painter.restore()
        opt.backgroundBrush = QBrush(Qt.NoBrush)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        # Padding, border and selection from the style; the text is ours.
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        doc = self._document(opt, text)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        # The model's ForegroundRole (the carved/live colour) reaches the
        # text exactly as it would through the style.
        role = (QPalette.HighlightedText if opt.state & QStyle.State_Selected
                else QPalette.Text)
        ctx.palette.setColor(QPalette.Text, opt.palette.color(role))
        rect = opt.rect
        top = rect.top() + max(0, (rect.height() - doc.size().height()) / 2)
        painter.save()
        painter.setClipRect(rect)
        painter.translate(rect.left() + _PAD_X, top)
        ctx.clip = QRectF(0, 0, rect.width() - _PAD_X, rect.bottom() - top)
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        opt = self._plain_option(option, index)
        doc = self._document(opt, opt.text)
        size.setHeight(max(size.height(), int(doc.size().height()) + 8))
        return size
