"""When the period list is short -- typically after typing a date into the
filter -- the grid shrinks to its rows and the selected period's records
get the rest. A one-row grid kept 60% of the height, mostly empty, while
the day's 50 records showed two at a time."""
import datetime

from webcache.shell import timeline_loader
from webcache.views.timeline import TimelineView

UTC = datetime.timezone.utc
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=UTC)


def _ft(dt):
    return int((dt - _EPOCH).total_seconds()) * 10_000_000


def _entries(days):
    out = []
    for i in range(days * 3):
        when = datetime.datetime(2024, 3, 1, 10, 0, tzinfo=UTC) + datetime.timedelta(days=i // 3, minutes=i)
        url = "https://short.example.test/%d" % i
        out.append({"Url": url, "CleanUrl": url, "ContainerType": "History",
                    "ContainerId": 1, "EntryId": i, "ModifiedTime_raw": _ft(when),
                    "AccessCount": 1, "FileSize": 0})
    return out


def _view(qtbot, days):
    # Under the app's own stylesheet, as the examiner sees it: unstyled, Qt
    # lays the split out differently and a re-layout bug hid (passed alone,
    # failed after any test that applied the theme).
    from PySide6.QtWidgets import QApplication
    from webcache.shell import theme
    theme.apply(QApplication.instance(), "dark")
    view = TimelineView()
    qtbot.addWidget(view)
    view.resize(1300, 800)
    inputs = timeline_loader.timeline_inputs(_entries(days))
    view.set_inputs(inputs)
    for grain, _l, _p in timeline_loader.GRAINS:
        view.set_records_for(grain, timeline_loader.period_rows(inputs, grain))
    view.show()
    qtbot.waitExposed(view)
    return view


def _pane_share(view):
    top, pane = view._splitter.sizes()
    return pane / float(top + pane)


def test_a_one_day_list_gives_its_records_most_of_the_height(qtbot):
    view = _view(qtbot, days=30)
    view.filter_box.setText("2024-03-05")
    qtbot.waitUntil(lambda: view.table.model().rowCount() == 1, timeout=3000)
    assert view.go_to_date("2024-03-05")
    qtbot.waitUntil(lambda: view._splitter.sizes()[1] > 0, timeout=2000)
    # The grid keeps room for the one period listed, not four empty rows.
    assert _pane_share(view) > 0.8, view._splitter.sizes()


def test_a_long_list_keeps_the_usual_split(qtbot):
    view = _view(qtbot, days=30)
    assert view.go_to_date("2024-03-05")
    assert abs(_pane_share(view) - 0.40) < 0.05, view._splitter.sizes()


def test_clearing_the_filter_gives_the_list_its_usual_room_back(qtbot):
    view = _view(qtbot, days=30)
    view.filter_box.setText("2024-03-05")
    qtbot.waitUntil(lambda: view.table.model().rowCount() == 1, timeout=3000)
    assert view.go_to_date("2024-03-05")
    assert _pane_share(view) > 0.7
    view.filter_box.setText("")
    qtbot.waitUntil(lambda: view.table.model().rowCount() == 30, timeout=3000)
    assert view.go_to_date("2024-03-06")
    assert abs(_pane_share(view) - 0.40) < 0.05, view._splitter.sizes()
