"""A carved row reads like text, and still cannot be mistaken for live."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from webcache.shell import theme
from webcache.widgets.record_model import RecordTableModel, foreground
from tests.fixtures import FIXTURE_COLUMNS, make_rows
from tests.test_detail_fields import carved_struct_row, history_row


def _srgb_channel(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hexcolor):
    color = QColor(hexcolor)
    return (0.2126 * _srgb_channel(color.red())
            + 0.7152 * _srgb_channel(color.green())
            + 0.0722 * _srgb_channel(color.blue()))


def _contrast_ratio(hex_a, hex_b):
    """WCAG 2.x contrast ratio: (L1 + 0.05) / (L2 + 0.05), lighter over
    darker."""
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _model():
    return RecordTableModel(list(FIXTURE_COLUMNS), make_rows(60))


def _first(model, carved):
    for r in range(model.rowCount()):
        if model.row_at(r)["Origin"].startswith("Carved") == carved \
                and model.row_at(r)["Title"]:
            return r
    raise AssertionError("fixture lacks the row")


@pytest.mark.parametrize("name", ["dark", "light"])
def test_both_themes_define_a_carved_row_tint(name):
    assert "carved_row" in theme.PALETTES[name]
    assert theme.PALETTES[name]["carved_row"] != theme.PALETTES[name]["base"]


def test_carved_text_uses_the_normal_text_colour(qtbot):
    m = _model()
    col = [c.key for c in FIXTURE_COLUMNS].index("Title")
    carved, live = _first(m, True), _first(m, False)
    assert (m.data(m.index(carved, col), Qt.ForegroundRole)
            == m.data(m.index(live, col), Qt.ForegroundRole)
            == foreground("text"))


def test_no_carved_cell_is_painted_amber(qtbot):
    m = _model()
    amber = [foreground("carved"), foreground("carved_link"),
             foreground("carved_blank")]
    for r in range(m.rowCount()):
        for c in range(m.columnCount()):
            assert m.data(m.index(r, c), Qt.ForegroundRole) not in amber


def test_a_carved_row_carries_the_tint_and_a_live_row_does_not(qtbot):
    m = _model()
    carved, live = _first(m, True), _first(m, False)
    for c in range(m.columnCount()):
        assert m.data(m.index(carved, c), Qt.BackgroundRole) == foreground("carved_row")
        assert m.data(m.index(live, c), Qt.BackgroundRole) is None


def test_the_dialog_paints_carved_values_as_text_on_the_tint(qtbot):
    from webcache.shell.record_detail import RecordDetailDialog
    dlg = RecordDetailDialog(carved_struct_row())
    try:
        amber = [foreground("carved"), foreground("carved_link"),
                 foreground("carved_blank")]
        for r in range(dlg.table.rowCount()):
            if dlg.field_at(r) is None:
                continue
            item = dlg.table.item(r, 1)
            assert item.foreground().color() not in amber, item.text()
            assert item.background().color() == foreground("carved_row")
    finally:
        dlg.close()


@pytest.mark.parametrize("name", ["dark", "light"])
def test_carved_tint_keeps_text_contrast_at_or_above_wcag_aa(name):
    """The tint must not merely be non-amber -- it must still be READABLE.
    WCAG 2.x's 4.5:1 threshold for normal-size text, checked against the
    text colours record_model.data() and the dialog actually paint on a
    carved row's tint (text, muted/blank, url/link). "primary" (the
    time-column colour) is excluded: it already sits below 4.5:1 against
    the plain light "base" surface today (3.20:1) -- a pre-existing gap
    in the light theme's own accent choice, not one this tint introduces
    or is responsible for fixing."""
    palette = theme.PALETTES[name]
    bg = palette["carved_row"]
    for role in ("text", "muted", "url"):
        ratio = _contrast_ratio(palette[role], bg)
        assert ratio >= 4.5, "%s on carved_row (%s) is only %.2f:1" % (
            role, name, ratio)


def test_the_grid_actually_paints_the_tint_pixel(qtbot, qapp):
    """Qt.BackgroundRole reaching data() is not
    enough: the app's own QSS rule for QTableView::item (theme.py's
    padding/border-bottom, applied here via theme.apply() exactly as
    MainWindow does at startup) makes QStyleSheetStyle own the item paint
    path and silently drop the role -- verified directly, offscreen
    platform DPI is 1.0 so widget and image pixels line up 1:1. Without
    theme.apply() this bug does not reproduce at all (Qt honours
    Qt.BackgroundRole fine with no application stylesheet), which is why
    this test applies the theme explicitly rather than relying on
    whatever an unrelated earlier test happened to leave behind. This
    grabs the real rendered pixmap and samples it, so a regression that
    brings the drop back (e.g. a new delegate that forgets
    record_model.BackgroundRoleDelegate) fails HERE, not only at the data
    layer where the earlier version of this bug was invisible."""
    original = theme.current_name()
    try:
        theme.apply(qapp, "dark")
        from webcache.widgets.records_table import RecordsTable
        table = RecordsTable()
        m = _model()
        table.setModel(m)
        table.resize(900, 600)
        table.show()
        qtbot.addWidget(table)
        carved, live = _first(m, True), _first(m, False)
        col = [c.key for c in FIXTURE_COLUMNS].index("Domain")
        pix = table.grab()
        img = pix.toImage()
        hh = table.horizontalHeader().height()

        def _sample(row):
            rect = table.visualRect(m.index(row, col))
            return img.pixelColor(rect.left() + 4, hh + rect.center().y())

        assert _sample(carved) == foreground("carved_row")
        assert _sample(live) != foreground("carved_row")
    finally:
        theme.apply(qapp, original)


def test_the_dialog_actually_paints_the_tint_pixel(qtbot, qapp):
    """The dialog counterpart of the grid check above -- the same QSS
    rule applies to this QTableWidget too, and (see the grid test's own
    docstring) only actually reproduces once theme.apply() has run.

    Renders the viewport directly (QWidget.render(), not .grab()) and
    clears the selection first: the row _populate() auto-selects on open
    paints its native selection highlight over anything a delegate fills
    underneath -- true of the tint exactly as it is true of an ordinary
    row's zebra colour -- and that is a real, separate visual state, not
    this test's target."""
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    from webcache.shell.record_detail import RecordDetailDialog
    original = theme.current_name()
    try:
        theme.apply(qapp, "dark")
        dlg = RecordDetailDialog(carved_struct_row())
        try:
            dlg.resize(1000, 800)
            dlg.show()
            QApplication.processEvents()
            dlg.table.clearSelection()
            dlg.table.setCurrentCell(-1, -1)
            QApplication.processEvents()
            row = next(r for r in range(dlg.table.rowCount())
                       if dlg.field_at(r) is not None)
            rect = dlg.table.visualItemRect(dlg.table.item(row, 1))
            pm = QPixmap(dlg.table.viewport().size())
            dlg.table.viewport().render(pm)
            colour = pm.toImage().pixelColor(rect.left() + 4, rect.center().y())
            assert colour == foreground("carved_row")
        finally:
            dlg.close()
    finally:
        theme.apply(qapp, original)


def test_a_live_dialog_carries_no_tint(qtbot):
    from webcache.shell.record_detail import RecordDetailDialog
    dlg = RecordDetailDialog(history_row())
    try:
        for r in range(dlg.table.rowCount()):
            if dlg.field_at(r) is not None:
                assert dlg.table.item(r, 1).background().color() != \
                    foreground("carved_row")
    finally:
        dlg.close()
