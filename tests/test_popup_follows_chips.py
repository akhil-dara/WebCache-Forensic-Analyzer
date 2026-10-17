"""A chip toggled (or filters cleared) while a filter popup is
open on that column must never leave the chip and the grid disagreeing
once the popup's OK is pressed."""
import pytest

from webcache.views.history import HistoryView
from tests.fixtures import make_rows


@pytest.fixture
def view(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records(make_rows(300))
    v.resize(1500, 800)
    v.show()
    qtbot.waitExposed(v)
    return v


def _open_popup(view):
    section = [c.key for c in view.table.model().columns].index("IsInPrivate")
    view.table._open_filter_popup(section)
    return view.table._filter_popup


def _press_ok_if_still_open(popup):
    """Whichever design: closed (nothing to press) or re-synced (OK is safe)."""
    try:
        if popup.isVisible():
            popup._ok()
    except RuntimeError:            # the C++ popup was deleted
        pass


def _agree(view):
    model = view.table.model()
    in_force = "IsInPrivate" in model.filter._values
    assert view.chip_inprivate.isChecked() == in_force
    assert view.chip_inprivate.looks_checked() == in_force
    assert (model.rowCount() < 300) == in_force


def test_chip_switched_off_under_an_open_popup(view):
    view.chip_inprivate.click()
    popup = _open_popup(view)
    view.chip_inprivate.click()
    _press_ok_if_still_open(popup)
    _agree(view)


def test_chip_switched_on_under_an_open_popup(view):
    popup = _open_popup(view)
    view.chip_inprivate.click()
    _press_ok_if_still_open(popup)
    _agree(view)


def test_grid_clear_button_under_an_open_popup(view):
    view.chip_inprivate.click()
    popup = _open_popup(view)
    view.clear_all_filters()
    _press_ok_if_still_open(popup)
    _agree(view)
