"""The case at a glance."""
import datetime
from collections import Counter

from webcache.provenance import CONTAINER_NOT_DETERMINABLE
from webcache.shell import dashboard_data
from webcache.views.dashboard import DashboardView

UTC = datetime.timezone.utc
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=UTC)


def ft(dt):
    return int((dt - _EPOCH).total_seconds()) * 10_000_000


FIRST = datetime.datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
LAST = datetime.datetime(2024, 6, 29, 20, 0, 0, tzinfo=UTC)


class _Parser:
    derived_tz_offset_seconds = 19800
    all_entries = [{"ModifiedTime_raw": ft(FIRST)},
                   {"ModifiedTime_raw": ft(LAST)}, {}]

    def get_database_info(self):
        return {"path": "C:/case/WebCacheV01.dat", "file_size": 4096,
                "db_state_text": "Dirty shutdown", "derived_tz": "UTC+05:30",
                "sha256": "ab" * 32}


def test_the_case_summary_states_range_zone_state_hash_and_recovery():
    rows = dict(dashboard_data.case_summary(_Parser()))
    assert rows["Activity (UTC)"] == "2024-01-02 03:04:05 – 2024-06-29 20:00:00"
    assert rows["Activity (local, UTC+05:30)"] == \
        "2024-01-02 08:34:05 – 2024-06-30 01:30:00"
    assert rows["Recovered time zone"] == "UTC+05:30"
    assert rows["Database state"] == "Dirty shutdown"
    assert rows["SHA-256"] == "ab" * 32
    assert rows["Recovery"] == "Not run"
    ran = dict(dashboard_data.case_summary(_Parser(), [{"_record": {}}] * 4))
    assert ran["Recovery"] == "Ran — 4 recovered records"


def _stats(recovered=0, inprivate=0):
    return {"total_records": 10 + recovered, "table_count": 5,
            "container_count": 3, "inprivate_count": inprivate,
            "total_file_size": 0,
            "container_types": Counter({CONTAINER_NOT_DETERMINABLE: 50,
                                        "History": 7, "Content": 3}),
            "top_domains": Counter(), "db_path": "C:/case/WebCacheV01.dat",
            "db_file_size": 4096, "recovered_count": recovered}


def test_the_headline_splits_live_and_recovered(qtbot):
    view = DashboardView()
    qtbot.addWidget(view)
    view.set_data(_stats(recovered=0), summary=dashboard_data.case_summary(_Parser()))
    assert view.chip_records.value() == "10"
    assert view.chip_recovered.value() == "—"
    view.set_data(_stats(recovered=40), summary=dashboard_data.case_summary(
        _Parser(), [{"_record": {}}] * 40))
    assert view.chip_recovered.value() == "40"


def test_not_determinable_is_listed_last_and_zero_is_neutral(qtbot):
    view = DashboardView()
    qtbot.addWidget(view)
    view.set_data(_stats(), summary=dashboard_data.case_summary(_Parser()))
    assert view._container_type_names[-1] == CONTAINER_NOT_DETERMINABLE
    assert view.chip_inprivate.accent() == "muted"
    view.set_data(_stats(inprivate=2), summary=dashboard_data.case_summary(_Parser()))
    assert view.chip_inprivate.accent() == "error"


def test_the_case_card_shows_every_fact(qtbot):
    view = DashboardView()
    qtbot.addWidget(view)
    view.set_data(_stats(), summary=dashboard_data.case_summary(_Parser()))
    labels = [label.text() for label, _value in view._db_info_rows]
    for expected in ("Activity (UTC)", "Recovered time zone",
                     "Database state", "SHA-256", "Recovery"):
        assert expected in labels
    assert "Tables" not in labels and "Containers" not in labels


def _mshist(local_dt, offset):
    return {"MSHistFrom": "20240101", "TzOffsetSeconds": offset,
            "ModifiedTime_raw": ft(local_dt)}


class _DstParser(_Parser):
    derived_tz_offset_seconds = -18000
    all_entries = [
        _mshist(datetime.datetime(2024, 7, 1, 12, 0, 0, tzinfo=UTC), -14400),
        _mshist(datetime.datetime(2024, 1, 10, 9, 0, 0, tzinfo=UTC), -18000)]

    def get_database_info(self):
        return dict(_Parser().get_database_info(), derived_tz="UTC-05:00")


def test_the_local_range_uses_each_records_own_offset_across_dst():
    rows = dict(dashboard_data.case_summary(_DstParser()))
    assert rows["Activity (UTC)"] == "2024-01-10 14:00:00 – 2024-07-01 16:00:00"
    # each end names the offset it was actually shifted by
    assert rows.get("Activity (local)") == (
        "2024-01-10 09:00:00 (UTC-05:00) – 2024-07-01 12:00:00 (UTC-04:00)")
    assert not any(k.startswith("Activity (local, ") for k in rows)


def test_no_recovered_zone_is_stated_not_hidden():
    class _NoZone(_Parser):
        derived_tz_offset_seconds = None

        def get_database_info(self):
            return dict(_Parser().get_database_info(), derived_tz="")
    rows = dict(dashboard_data.case_summary(_NoZone()))
    assert rows.get("Activity (local)") == "No time zone was recovered"
    assert rows["Recovered time zone"].startswith("Could not be derived")


def test_the_card_says_what_the_range_covers():
    rows = dict(dashboard_data.case_summary(_Parser()))
    assert rows.get("Activity covers") == "Live records only (recovery not run)"
    assert "Activity (live only, UTC)" not in rows
    later = datetime.datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)
    ran = dict(dashboard_data.case_summary(
        _Parser(), [{"_record": {"ModifiedTime_raw": ft(later)}}]))
    assert ran.get("Activity covers") == "Live and recovered records"
    assert ran["Activity (UTC)"].endswith("2025-03-04 05:06:07")
    assert ran.get("Activity (live only, UTC)") ==         "2024-01-02 03:04:05 – 2024-06-29 20:00:00"


def test_no_live_only_row_when_recovery_does_not_widen_the_range():
    inside = datetime.datetime(2024, 3, 4, 5, 6, 7, tzinfo=UTC)
    ran = dict(dashboard_data.case_summary(
        _Parser(), [{"_record": {"ModifiedTime_raw": ft(inside)}}]))
    assert ran.get("Activity covers") == "Live and recovered records"
    assert "Activity (live only, UTC)" not in ran


def test_set_data_has_no_dead_note_parameter(qtbot):
    import pytest
    view = DashboardView()
    qtbot.addWidget(view)
    with pytest.raises(TypeError):
        view.set_data(_stats(), note="anything")
