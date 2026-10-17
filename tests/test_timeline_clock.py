"""The Timeline's clock: UTC or the recovered local time, and the prose
that says which."""
import datetime

import pytest

from webcache.engine import forensic_engine
from webcache.shell import timeline_loader
from webcache.views.history import HistoryView
from webcache.views.timeline import TimelineView
from tests.fixtures import make_rows

UTC = datetime.timezone.utc
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=UTC)
ZONE = 19800


def ft(dt):
    return int((dt - _EPOCH).total_seconds()) * 10_000_000


def rec(dt):
    return {"Url": "https://a.example.test/", "ContainerType": "History",
            "ModifiedTime_raw": ft(dt)}


def mshist(utc_dt, offset):
    """An MSHist record: stored LOCAL time, stamped with its own offset."""
    local = utc_dt + datetime.timedelta(seconds=offset)
    return {"Url": ":2024010120240101: alice@https://a.example.test/",
            "MSHistFrom": "2024-01-01", "ContainerType": "History",
            "ModifiedTime_raw": ft(local), "TzOffsetSeconds": offset}


LATE = datetime.datetime(2024, 6, 29, 20, 0, tzinfo=UTC)   # 01:30 local, 30 June
EARLY = datetime.datetime(2024, 6, 29, 10, 0, tzinfo=UTC)  # 15:30 local, 29 June


def test_the_engine_buckets_on_the_local_clock_when_asked():
    e = forensic_engine.ForensicEngine()
    utc = [b["period"] for b in e.get_timeline("day", [rec(EARLY), rec(LATE)])]
    local = [b["period"] for b in e.get_timeline("day", [rec(EARLY), rec(LATE)],
                                                 offset_seconds=ZONE)]
    assert utc == ["2024-06-29"]
    assert local == ["2024-06-29", "2024-06-30"]


def test_a_local_period_starts_at_its_true_instant():
    inputs = timeline_loader.timeline_inputs([rec(LATE)])
    row = timeline_loader.period_rows(inputs, "day", offset_seconds=ZONE)[0]
    assert row["Period"] == "2024-06-30"
    start = row["PeriodStart"]
    assert (start.year, start.month, start.day, start.hour) == (2024, 6, 30, 0)
    assert start.utcoffset() == datetime.timedelta(seconds=ZONE)


def test_local_days_use_each_records_own_offset_not_one_global_offset():
    winter = mshist(datetime.datetime(2024, 1, 1, 20, 0, tzinfo=UTC), -18000)
    summer = mshist(datetime.datetime(2024, 7, 1, 4, 30, tzinfo=UTC), -14400)
    inputs = timeline_loader.timeline_inputs([winter, summer])
    rows = timeline_loader.period_rows(inputs, "day", offset_seconds=-18000)
    # 04:30 UTC in July is 00:30 on 1 July under DST; one global -05:00
    # would wrongly file it on 30 June.
    assert [r["Period"] for r in rows] == ["2024-01-01", "2024-07-01"]


def test_both_clocks_account_for_every_record():
    recs = [rec(EARLY), rec(LATE),
            mshist(datetime.datetime(2024, 1, 1, 20, 0, tzinfo=UTC), ZONE),
            {"Url": "https://nothing.example.test/"}]
    inputs = timeline_loader.timeline_inputs(recs)
    utc = timeline_loader.period_rows(inputs, "day")
    local = timeline_loader.period_rows(inputs, "day", offset_seconds=ZONE)
    assert (sum(r["Records"] for r in utc)
            == sum(r["Records"] for r in local)
            == len(inputs.records) == 3)
    assert inputs.undated_live == 1


def test_the_note_names_the_clock_the_periods_are_on():
    inputs = timeline_loader.timeline_inputs([rec(LATE)])
    rows = timeline_loader.period_rows(inputs, "day", offset_seconds=ZONE)
    note = timeline_loader.grain_note(inputs, rows, "day", False,
                                      clock_label="UTC+05:30")
    assert "Periods are UTC+05:30 days." in note
    assert "Periods are UTC days." in timeline_loader.grain_note(
        inputs, rows, "day", False)


@pytest.fixture
def view(qtbot):
    v = TimelineView()
    qtbot.addWidget(v)
    v.resize(1400, 800)
    v.show()
    qtbot.waitExposed(v)
    inputs = timeline_loader.timeline_inputs([rec(EARLY), rec(LATE),
                                              rec(EARLY - datetime.timedelta(days=40))])
    v.set_inputs(inputs)
    for grain, _l, _p in timeline_loader.GRAINS:
        v.set_records_for(grain, timeline_loader.period_rows(inputs, grain))
    return v


def test_the_header_states_the_zone_and_offers_local(view):
    view.set_zone(ZONE, "UTC+05:30")
    assert "UTC+05:30" in view.zone_label.text()
    assert view.clock_buttons["local"].isEnabled()
    fired = []
    view.clockChanged.connect(fired.append)
    view.clock_buttons["local"].click()
    assert fired == ["local"] and view.clock() == "local"


def test_without_a_zone_local_is_disabled_and_says_why(view):
    view.set_zone(None, "")
    assert not view.clock_buttons["local"].isEnabled()
    assert "no time zone" in view.zone_label.text().lower()


def test_newest_first_by_default(view):
    model = view.table.model()
    periods = [model.row_at(i)["Period"] for i in range(model.rowCount())]
    assert periods == sorted(periods, reverse=True)


def test_go_to_date_selects_that_period(view):
    assert view.go_to_date("2024-05-20")
    assert view.selected_period() == "2024-05-20"
    assert not view.go_to_date("1999-01-01")


def test_a_day_with_nothing_names_its_nearest_neighbours(view):
    """"No period starts with that date" left the PREVIOUS selection
    highlighted, which reads as the answer; and an empty day's next
    question is where the nearest activity is."""
    days = sorted(view.table.model().row_at(i)["Period"]
                  for i in range(view.table.model().rowCount()))
    assert view.go_to_date(days[-1])
    view.date_box.setText("2024-06-01")
    view._go_from_box()
    assert not view.selected_period()
    status = view.go_status.text()
    assert "No records on 2024-06-01" in status, status
    before = max(d for d in days if d < "2024-06-01")
    after = min(d for d in days if d > "2024-06-01")
    assert before in status and after in status, status


def test_a_date_past_every_period_says_there_is_nothing_after(view):
    view.date_box.setText("2099-01-01")
    view._go_from_box()
    assert "nothing after" in view.go_status.text(), view.go_status.text()


def test_a_long_note_folds_to_one_line_and_keeps_every_word(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    v.resize(900, 700)
    long_note = " ".join(["This sentence is part of a long note."] * 12)
    v.set_records(make_rows(10), note=long_note)
    v.show()
    qtbot.waitExposed(v)
    assert long_note in v.note_label.text()
    assert long_note not in v.count_label.text()
    line = v.note_label.fontMetrics().lineSpacing()
    assert v.note_label.maximumHeight() <= 2 * line
    assert v.note_line.toggle.isVisible()
    v.note_line.toggle.click()
    assert v.note_label.maximumHeight() > 10 * line


def test_the_fold_says_a_note_exists_and_is_remembered_per_view(qtbot):
    from PySide6.QtWidgets import QLabel
    from webcache.widgets.note_line import NoteLine
    text = " ".join(["Caveat about coordinates."] * 40)

    def make(key):
        label = QLabel(text)
        label.setWordWrap(True)
        qtbot.addWidget(label)
        label.resize(400, 200)
        label.show()
        qtbot.waitExposed(label)
        return NoteLine(label, key=key)

    first = make("alpha-test-view")
    assert "note" in first.toggle.text().lower()
    first.toggle.click()
    assert not first.is_collapsed()
    # the same view built again (a rebuild, a re-open) comes back open;
    # another view is unaffected
    assert not make("alpha-test-view").is_collapsed()
    assert make("beta-test-view").is_collapsed()
