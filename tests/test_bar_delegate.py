"""ShareBarDelegate: a 0..1 share, drawn, without costing virtualisation.

WHY A DELEGATE AND NOT A WIDGET. The Dashboard draws its own bars with a
QProgressBar per row (views/dashboard.py), which is fine there -- that
card holds ten rows in a QVBoxLayout. The equivalent inside a QTableView
is setIndexWidget per row, which builds one widget for every row in the
model and destroys the one property this port has explicitly refused to
trade away. A QStyledItemDelegate paints only the cells actually on
screen.

WHY SQUARE ROOT. dashboard.py already measured it: on real evidence a
linear scale turned nine of ten bars into identical four-pixel stubs. The
bar's job is to make periods COMPARABLE; the exact count is in the
adjacent Records column, and the tooltip states the linear percentage in
words so the drawing never has to be read as the number.
"""
import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QHelpEvent, QImage, QPainter
from PySide6.QtWidgets import QStyleOptionViewItem

from webcache.shell import theme
from webcache.widgets.bar_delegate import ShareBarDelegate
from webcache.widgets.column_spec import Column
from webcache.widgets.record_model import RecordTableModel

_COLUMNS = [Column("Period", "Period", 120, kind="text"),
            Column("Share", "Relative volume", 190, kind="bar"),
            Column("Origin", "Origin", 120, kind="text")]

_W, _H = 200, 24


def _model(share, origin="Live record"):
    return RecordTableModel(
        _COLUMNS, [{"Period": "p", "Share": share, "Origin": origin}])


def _paint(delegate, model, width=_W, height=_H):
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.black)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, width, height)
    delegate.paint(painter, option, model.index(0, 1))
    painter.end()
    return image


def _bar_pixel(image, delegate, share):
    """The centre of the bar this share should have drawn."""
    track = _W - 2 * delegate.TRACK_INSET_PX
    x = delegate.TRACK_INSET_PX + delegate.bar_width(track, share) // 2
    return image.pixelColor(x, _H // 2)


# --- the maths ------------------------------------------------------------

def test_the_scale_is_square_root_not_linear():
    """A quarter of the peak draws HALF the track, not a quarter of it --
    the whole reason this scale was chosen over the obvious one."""
    track = 100
    assert ShareBarDelegate.bar_width(track, 0.25) == 50
    assert ShareBarDelegate.bar_width(track, 1.0) == 100


def test_a_nonzero_share_never_vanishes():
    """A period that holds records must never draw as nothing at all: an
    empty cell in this column would read as an empty period, which is the
    one thing this grid never fabricates."""
    width = ShareBarDelegate.bar_width(400, 0.000001)
    assert width >= ShareBarDelegate.MIN_VISIBLE_PX
    assert width > 0


def test_a_zero_share_draws_nothing():
    assert ShareBarDelegate.bar_width(400, 0) == 0


def test_share_of_reads_the_raw_role_never_the_display_text():
    """DisplayRole is a formatted string; the delegate needs the number.
    Reading the text back and re-parsing it is how a thousands separator
    or a locale decimal point silently becomes a zero-width bar."""
    model = _model(0.5)
    assert ShareBarDelegate.share_of(model.index(0, 1)) == 0.5


@pytest.mark.parametrize("value", [None, "", "not a number"])
def test_a_value_that_is_not_a_share_draws_nothing_rather_than_guessing(value):
    model = _model(value)
    assert ShareBarDelegate.share_of(model.index(0, 1)) is None


@pytest.mark.parametrize("value,expected", [(-0.5, 0.0), (1.7, 1.0)])
def test_a_share_outside_zero_to_one_is_clamped(value, expected):
    model = _model(value)
    assert ShareBarDelegate.share_of(model.index(0, 1)) == expected


# --- what actually lands on screen ---------------------------------------

def test_a_live_row_is_drawn_in_the_secondary_colour(qtbot):
    delegate = ShareBarDelegate()
    model = _model(1.0)
    image = _paint(delegate, model)
    assert _bar_pixel(image, delegate, 1.0) == theme.color("secondary")


def test_a_carved_row_is_drawn_in_the_carved_colour(qtbot):
    """The live/carved distinction is never hideable (record_model.py's
    own rule), and a NEW column kind must not be the one place it stops
    applying."""
    delegate = ShareBarDelegate()
    model = _model(1.0, origin="Carved (deleted/unflushed)")
    image = _paint(delegate, model)
    assert _bar_pixel(image, delegate, 1.0) == theme.color("carved")


def test_an_empty_share_paints_no_bar_at_all(qtbot):
    delegate = ShareBarDelegate()
    image = _paint(delegate, _model(None))
    for x in range(_W):
        assert image.pixelColor(x, _H // 2) not in (
            theme.color("secondary"), theme.color("carved")), x


def test_the_cell_carries_no_text(qtbot):
    """opt.text is cleared before the style draws: a bar with the raw
    float printed across it is two encodings of one value fighting for
    the same pixels, and the exact number lives in the Records column."""
    delegate = ShareBarDelegate()
    model = _model(0.5)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, _W, _H)
    prepared = delegate.prepared_option(option, model.index(0, 1))
    assert prepared.text == ""


# --- the tooltip, which carries the honesty the width cannot -------------

def test_the_tooltip_states_the_linear_percentage_and_names_the_scale():
    delegate = ShareBarDelegate()
    delegate.set_unit("day")
    text = delegate.tooltip_for(0.25)
    assert "25.0%" in text, (
        "the LINEAR share, which is what the width deliberately is not")
    assert "day" in text
    assert "square-root" in text
    assert "Records column" in text


def test_the_tooltip_names_a_generic_unit_until_a_view_sets_one():
    assert "period" in ShareBarDelegate().tooltip_for(1.0)


def test_help_event_shows_a_tooltip_for_a_real_share(qtbot):
    from webcache.widgets.records_table import RecordsTable

    table = RecordsTable()
    table.set_records(_COLUMNS, [{"Period": "p", "Share": 0.25,
                                  "Origin": "Live record"}])
    qtbot.addWidget(table)
    delegate = ShareBarDelegate()
    index = table.model().index(0, 1)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, _W, _H)
    event = QHelpEvent(QEvent.ToolTip, QPoint(5, 5), QPoint(5, 5))
    assert delegate.helpEvent(event, table, option, index) is True
