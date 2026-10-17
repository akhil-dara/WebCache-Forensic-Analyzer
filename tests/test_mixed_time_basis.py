"""A "(UTC)" time column that holds MSHist rows
says so. The header badge is not OBS when some rows' UTC is derived from
a LOCAL value, and each such cell's tooltip names its own basis."""
import datetime

from PySide6.QtCore import Qt

from webcache.views.file_access import FileAccessView
from webcache.views.location import LocationView

UTC = datetime.timezone.utc
WHEN = datetime.datetime(2024, 6, 29, 20, 0, tzinfo=UTC)
NOTE = ("ModifiedTime (visit written) \u2014 stored as LOCAL wall-clock by "
        "an MSHist container; UTC derived with UTC+05:30, the recovered "
        "zone (INF)")


def _fa_row(mshist):
    record = {"MSHistFrom": "2024-06-30", "TzOffsetSeconds": 19800} if mshist \
        else {}
    return {"ModifiedTime": WHEN, "CleanUrl": "file:///C:/x/a.txt",
            "LocalPath": "C:/x/a.txt", "Origin": "Live record",
            "ModifiedTimeBasis": NOTE if mshist else
            "ModifiedTime (visit written)",
            "_record": record, "_kind": "file_access"}


def _column(view, key):
    return next(c for c in view.table.model().columns if c.key == key)


def _tooltip(view, row, key):
    model = view.table.model()
    col = [c.key for c in model.columns].index(key)
    return model.data(model.index(row, col), Qt.ToolTipRole) or ""


def test_a_column_holding_derived_mshist_rows_is_not_badged_observed(qtbot):
    view = FileAccessView()
    qtbot.addWidget(view)
    view.set_records_for("file_access", [_fa_row(False), _fa_row(True)])
    col = _column(view, "ModifiedTime")
    assert col.badge != "OBS"
    assert "INF" in col.badge
    assert "mixed" in (col.badge_tooltip or "").lower()


def test_an_all_utc_column_keeps_its_observed_badge(qtbot):
    view = FileAccessView()
    qtbot.addWidget(view)
    view.set_records_for("file_access", [_fa_row(False)])
    assert _column(view, "ModifiedTime").badge == "OBS"


def test_each_derived_cell_names_its_own_basis(qtbot):
    view = FileAccessView()
    qtbot.addWidget(view)
    view.set_records_for("file_access", [_fa_row(True)])
    assert "stored as LOCAL wall-clock" in _tooltip(view, 0, "ModifiedTime")


def test_the_local_column_says_where_its_value_comes_from(qtbot):
    view = FileAccessView()
    qtbot.addWidget(view)
    view.set_records_for("file_access", [_fa_row(False)])
    note = _column(view, "AccessedLocal").note or ""
    assert "SPS id 24" in note and "MSHist" in note


def test_location_cache_wrote_is_graded_per_row(qtbot):
    view = LocationView()
    qtbot.addWidget(view)
    key = next(k for k, rs in view._segments_by_key.items()
               if any(c.key == "RecordTimeShown" for c in rs.columns))
    view._switch_segment(key)
    row = {"RecordTimeUtc": WHEN, "RecordTimeShown": WHEN, "RecordTimeNote": NOTE,
           "_record": {"MSHistFrom": "2024-06-30", "TzOffsetSeconds": 19800}}
    view.set_records_for(key, [row])
    assert "INF" in _column(view, "RecordTimeShown").badge
