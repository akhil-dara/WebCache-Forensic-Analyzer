"""A grid's visit column holds the browser's visit counter only.

Found working "how many times was this page visited": History headed a
column "Visits" that, on 1,385 of the exhibit's 2,015 rows (every
dated-history record, which stores no visit counter), showed AccessCount
-- cache touches, which this tool states are not visits -- and File
Access did the same under "Opens". Both counters are now shown, each
under its own name, and never merged."""
from types import SimpleNamespace

from webcache.shell import evidence_loader as ev
from webcache.shell import recovery_loader as rec

FT = 134150000000000000


def _entries():
    with_counter = {"ContainerType": "History", "IsLocalFile": True,
                    "Url": "Visited: u@file:///C:/a.txt",
                    "CleanUrl": "file:///C:/a.txt",
                    "ModifiedTime_raw": FT, "SPS_VisitCount": 3,
                    "AccessCount": 9}
    without = {"ContainerType": "History", "IsLocalFile": True,
               "Url": "Visited: u@file:///C:/b.txt",
               "CleanUrl": "file:///C:/b.txt",
               "ModifiedTime_raw": FT, "AccessCount": 7}
    return [with_counter, without]


def _check(rows, visits_key):
    by_url = {r["CleanUrl"]: r for r in rows}
    a, b = by_url["file:///C:/a.txt"], by_url["file:///C:/b.txt"]
    assert (a[visits_key], a["CacheTouches"]) == (3, 9)
    assert (b[visits_key], b["CacheTouches"]) == (None, 7)


def test_live_history_rows():
    _check(ev.history_rows_from_parser(SimpleNamespace(all_entries=_entries())),
           "VisitCount")


def test_live_file_access_rows():
    _check(ev.file_access_rows_from_parser(
        SimpleNamespace(all_entries=_entries())), "VisitCount")


def test_recovered_history_rows():
    _check(rec.carved_history_rows(SimpleNamespace(structured_records=_entries())),
           "VisitCount")


def test_recovered_file_access_rows():
    _check(rec.carved_file_access_rows(
        SimpleNamespace(structured_records=_entries())), "VisitCount")


def test_the_grids_name_each_counter(qtbot):
    from webcache.views.file_access import FILE_ACCESS_COLUMNS
    from webcache.views.history import HistoryView
    v = HistoryView()
    qtbot.addWidget(v)
    labels = {c.key: c.label for c in v.table.model().columns} \
        if v.table.model() else None
    if labels is None:
        v.set_records([])
        labels = {c.key: c.label for c in v.table.model().columns}
    assert labels["VisitCount"] == "Visits (property store)"
    assert labels["CacheTouches"] == "Cache touches"
    fa = {c.key: c.label for c in FILE_ACCESS_COLUMNS}
    assert fa["VisitCount"] == "Opens (property store)"
    assert fa["CacheTouches"] == "Cache touches"
    assert "VisitCountBest" not in fa


def _labels_of(row):
    from webcache.shell import detail_fields as df
    out = {}
    for g in df.fields_for(row):
        for f in g.fields:
            out.setdefault(f.label, []).append(f.display_value)
    return out


def test_the_record_view_shows_each_counter_once_under_its_own_name():
    rows = ev.history_rows_from_parser(SimpleNamespace(all_entries=_entries()))
    by_url = {r["CleanUrl"]: r for r in rows}
    with_counter = _labels_of(by_url["file:///C:/a.txt"])
    assert with_counter["Visits (property store)"] == ["3"]
    assert with_counter["Cache touches (AccessCount)"] == ["9"]
    assert "Visits" not in with_counter
    assert "Visit count (SPS id 6)" not in with_counter     # not twice
    without = _labels_of(by_url["file:///C:/b.txt"])
    assert without["Cache touches (AccessCount)"] == ["7"]
    # Never shown as a visit count, under any name.
    assert all("7" not in v for k, v in without.items() if "Visit" in k)
