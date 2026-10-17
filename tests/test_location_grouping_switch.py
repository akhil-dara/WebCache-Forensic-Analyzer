"""The Location view's grouping switch: the examiner picks the scale
places are grouped at, and the subtitle, the note, the fixes' Place
column and the drill from a place to its fixes all follow it."""
import pytest

pytest.importorskip("PySide6")

from webcache.shell import location_loader
from webcache.views.location import LocationView

from tests.test_location_loader import _live, _url

HOME = [("18.4200100", "-39.6299900"), ("18.4202500", "-39.6298100"),
        ("18.4198000", "-39.6303000")]
AWAY = [("18.4650000", "-39.5900000")]


def _entries():
    return [_live(_url(lat=a, lon=b)) for a, b in HOME + AWAY]


class _Shell:
    """MainWindow's three location lines, so the view is driven the way
    the shell drives it without opening an exhibit."""

    def __init__(self, view):
        self.view = view
        self.grouping = location_loader.DEFAULT_GROUPING
        self.fixes = location_loader.position_fixes(_entries(),
                                                    grouping=self.grouping)
        view.groupingChanged.connect(self.regroup)
        self.push()

    def regroup(self, grouping):
        self.grouping = grouping
        location_loader.label_fixes(self.fixes, grouping)
        self.push()

    def push(self):
        places = location_loader.places(self.fixes, grouping=self.grouping)
        self.view.set_records_for("fixes", self.fixes)
        self.view.set_records_for(
            "places", places,
            note=location_loader.places_note(self.fixes, places,
                                             grouping=self.grouping))


@pytest.fixture
def shell(qtbot):
    view = LocationView()
    qtbot.addWidget(view)
    return _Shell(view)


def test_every_grouping_has_a_button_and_the_default_is_checked(shell):
    buttons = shell.view.grouping_buttons
    assert list(buttons) == [g.key for g in location_loader.GROUPINGS]
    assert buttons[location_loader.DEFAULT_GROUPING].isChecked()


def test_choosing_a_grouping_regroups_and_restates_it(shell):
    view = shell.view
    view._switch_segment("places")
    assert view._switcher_label("places") == "Places (2)"
    view.grouping_buttons["11m"].click()
    assert shell.grouping == "11m"
    assert view._switcher_label("places") == "Places (4)"
    assert "within 11 m" in view.header._subtitle.text()
    assert "within 11 m" in view.grouping_buttons["11m"].toolTip()


def test_the_drill_still_finds_its_fixes_after_a_regroup(shell):
    view = shell.view
    view.grouping_buttons["1km"].click()
    view._switch_segment("places")
    big = max(view._segment_rows["places"], key=lambda r: r["Fixes"])
    view.show_fixes_at(big)
    assert view.table.model().rowCount() == big["Fixes"]


def test_clicking_the_grouping_in_force_announces_nothing(shell, qtbot):
    with qtbot.assertNotEmitted(shell.view.groupingChanged):
        shell.view.grouping_buttons[location_loader.DEFAULT_GROUPING].click()
