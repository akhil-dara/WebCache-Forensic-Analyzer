"""A drill pane (a Timeline period's records, a
domain's records) opens newest first, and its sort arrow states that
order -- an arrow over an unsorted list asserts an order that is not
there."""
import datetime

from PySide6.QtCore import Qt

from webcache.shell import domain_loader, timeline_loader
from webcache.views.domains import DomainsView
from webcache.views.timeline import TimelineView

UTC = datetime.timezone.utc
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=UTC)
#: Minutes of one day, deliberately out of order.
MINUTES = [7, 3, 19, 1, 22, 11, 5, 17, 2, 13, 29, 23, 8, 4, 27, 6, 14, 21,
           9, 25, 12]


def ft(dt):
    return int((dt - _EPOCH).total_seconds()) * 10_000_000


def _when(minute):
    return datetime.datetime(2024, 3, 1, 10, minute, tzinfo=UTC)


def _entry(i, minute):
    url = "https://order.example.test/%d" % i
    return {"Url": url, "CleanUrl": url, "ContainerType": "History",
            "ContainerId": 1, "EntryId": i, "ModifiedTime_raw": ft(_when(minute)),
            "AccessCount": 1, "FileSize": 0}


ENTRIES = [_entry(i, m) for i, m in enumerate(MINUTES)]


def _newest_first(pane):
    model = pane.table.model()
    times = [model.row_at(i)["KeyTimeUtc"] for i in range(min(20, model.rowCount()))]
    assert len(times) == 20
    assert times == sorted(times, reverse=True), times
    header = pane.table.horizontalHeader()
    keys = [c.key for c in model.columns]
    assert header.sortIndicatorSection() == keys.index("KeyTimeUtc")
    assert header.sortIndicatorOrder() == Qt.DescendingOrder


def test_a_timeline_period_pane_is_newest_first(qtbot):
    view = TimelineView()
    qtbot.addWidget(view)
    inputs = timeline_loader.timeline_inputs(ENTRIES)
    view.set_inputs(inputs)
    for grain, _l, _p in timeline_loader.GRAINS:
        view.set_records_for(grain, timeline_loader.period_rows(inputs, grain))
    assert view.go_to_date("2024-03-01")
    _newest_first(view.pane)


def test_a_domain_pane_is_newest_first(qtbot):
    view = DomainsView()
    qtbot.addWidget(view)
    view.set_records(domain_loader.domain_rows(ENTRIES, []))
    assert view.show_domain("order.example.test")
    _newest_first(view.pane)
