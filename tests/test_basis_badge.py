"""The basis chip, and the carved/live colour cache, shared rather than
copied.

The record detail dialog paints the SAME OBS/DER/INF/CARV chip on a field
row that _ProvenanceHeaderView already paints on a column heading, and it
paints carved values in the SAME amber family record_model already uses in
the grid. Both of those are one fact rendered on two surfaces, so both
have exactly one failure mode worth guarding: the two surfaces drifting.

Two extractions, each with a stated reason:

  widgets/basis_badge.py -- the chip's geometry and font. A second copy of
  "5px padding, 16px tall, bold at pointSizeF() - 2.5" in the dialog would
  look identical on the day it was written and then diverge the first time
  either is tuned, leaving an examiner with two differently-sized chips
  claiming the same thing.

  record_model.foreground() -- the theme-name-keyed QColor cache, promoted
  from the private _fg(). Its docstring already records why it exists: a
  QColor baked in at import time never updates when the theme pill
  switches palettes, and a hardcoded near-white was verified unreadable on
  the light palette. A dialog calling theme.color() directly would
  reintroduce exactly that, on a surface with no test watching it.
"""
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

from webcache.shell import theme
from webcache.widgets import basis_badge, record_model
from webcache.widgets.records_table import RecordsTable, _ProvenanceHeaderView


# --- geometry, shared not copied ----------------------------------------

def test_the_header_reads_its_chip_geometry_from_the_shared_module():
    """Not "the numbers happen to be equal" -- the SAME objects. Equal
    numbers is what two copies look like right up until one is tuned."""
    assert _ProvenanceHeaderView.BADGE_PAD_PX is basis_badge.BADGE_PAD_PX
    assert _ProvenanceHeaderView.BADGE_HEIGHT_PX is basis_badge.BADGE_HEIGHT_PX
    assert _ProvenanceHeaderView.BADGE_GAP_PX is basis_badge.BADGE_GAP_PX


def test_the_badge_font_is_bold_and_smaller_than_the_font_it_is_given(qtbot):
    base = QFont()
    base.setPointSizeF(11.0)
    font = basis_badge.badge_font(base)
    assert font.bold() is True
    assert font.pointSizeF() == pytest.approx(11.0 - basis_badge.BADGE_FONT_DELTA_PT)
    # and never shrinks into illegibility on a tiny base font.
    tiny = QFont()
    tiny.setPointSizeF(4.0)
    assert basis_badge.badge_font(tiny).pointSizeF() >= basis_badge.BADGE_FONT_MIN_PT


def test_the_badge_font_does_not_mutate_the_font_it_was_given(qtbot):
    """A QFont is a value type but Qt hands them around by reference all
    over; mutating the header's own font in place would bold every column
    heading."""
    base = QFont()
    base.setPointSizeF(11.0)
    base.setBold(False)
    basis_badge.badge_font(base)
    assert base.bold() is False
    assert base.pointSizeF() == pytest.approx(11.0)


def test_badge_width_reserves_padding_on_both_sides(qtbot):
    font = basis_badge.badge_font(QFont())
    narrow = basis_badge.badge_width(font, "OBS")
    wide = basis_badge.badge_width(font, "CARV")
    assert wide > narrow > 2 * basis_badge.BADGE_PAD_PX


def test_the_header_and_the_shared_module_agree_on_a_chip_width(qtbot):
    """The header's own badge_width() is what _enforce_heading_floor sizes
    a column against. If it and the dialog disagree, one of the two paints
    a chip that does not fit."""
    table = RecordsTable()
    qtbot.addWidget(table)
    header = table.horizontalHeader()
    for text in ("OBS", "DER", "INF", "CARV"):
        assert header.badge_width(text) == pytest.approx(
            basis_badge.badge_width(header.badge_font_object(), text))


# --- painting -----------------------------------------------------------

def test_paint_badge_actually_paints_something(qtbot):
    """A chip that draws nothing is the failure mode a geometry-only test
    cannot see."""
    pixmap = QPixmap(80, 24)
    pixmap.fill(QColor("#101418"))
    painter = QPainter(pixmap)
    basis_badge.paint_badge(painter, QRectF(4, 4, 46, 16), "CARV",
                            basis_badge.badge_font(QFont()),
                            QColor("#D29922"))
    painter.end()
    image = pixmap.toImage()
    colors = {image.pixel(x, y) for x in range(80) for y in range(24)}
    assert len(colors) > 1, "paint_badge drew nothing at all"


def test_paint_badge_stays_inside_the_rect_it_is_given(qtbot):
    """The header's whole "never overlap the label" guarantee rests on the
    chip honouring its reserved slot."""
    pixmap = QPixmap(120, 40)
    pixmap.fill(QColor("#101418"))
    background = pixmap.toImage().pixel(2, 2)
    painter = QPainter(pixmap)
    basis_badge.paint_badge(painter, QRectF(40, 12, 40, 16), "DER",
                            basis_badge.badge_font(QFont()),
                            QColor("#58A6FF"))
    painter.end()
    image = pixmap.toImage()
    for x, y in ((2, 2), (2, 38), (118, 2), (118, 38), (20, 20), (100, 20)):
        assert image.pixel(x, y) == background, (x, y)


def test_paint_badge_leaves_the_painter_as_it_found_it(qtbot):
    """It is called mid-paintSection, between other drawing. A leaked pen,
    brush or font would silently restyle whatever paints next."""
    pixmap = QPixmap(40, 20)
    painter = QPainter(pixmap)
    painter.setFont(QFont("Segoe UI", 14))
    before = painter.font().pointSizeF()
    basis_badge.paint_badge(painter, QRectF(2, 2, 30, 16), "INF",
                            basis_badge.badge_font(QFont()), QColor("red"))
    assert painter.font().pointSizeF() == pytest.approx(before)
    painter.end()


# --- the foreground cache ----------------------------------------------

def test_foreground_is_public_and_returns_a_colour():
    color = record_model.foreground("carved")
    assert isinstance(color, QColor)
    assert color.isValid()


def test_foreground_caches_within_a_theme_and_drops_it_on_a_switch(qapp):
    """The cache exists for a measured reason -- data() runs once per
    visible cell on every repaint and theme.color() parses a hex string
    each call -- and it is keyed by theme NAME so a palette switch cannot
    leave a stale colour behind."""
    original = theme.current_name()
    try:
        theme.apply(qapp, "dark")
        first = record_model.foreground("carved")
        assert record_model.foreground("carved") is first, "not cached"
        theme.apply(qapp, "light")
        after = record_model.foreground("carved")
        assert after is not first, "cache survived a theme switch"
        assert after == theme.color("carved")
    finally:
        theme.apply(qapp, original)


def test_the_model_paints_through_the_same_function_the_dialog_will_use(
        qtbot, columns):
    """Carved and live paint through the same live palette, in the grid
    and the dialog alike."""
    from tests.fixtures import make_rows
    rows = make_rows(4)
    rows[0]["Origin"] = "Carved (unallocated page)"
    model = record_model.RecordTableModel(columns, rows)
    painted = model.data(model.index(0, 1), Qt.ForegroundRole)
    assert painted not in (record_model.foreground("carved"),
                           record_model.foreground("carved_link"),
                           record_model.foreground("carved_blank"))
