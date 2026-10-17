"""Deleted-record stubs reached the screen but not a single export: every
writer is handed `recovered=main_window._recovered_artifacts()`, which
built its set from `engine.all_artifacts() + engine.structured_records`
only. A stub carries no URL and no timestamp -- only a b-tree key -- so it
must reach `build_entry_row` shaped as a real (if sparse) artifact, never
inventing either.
"""
import sqlite3

from webcache.engine.forensic_engine import ForensicEngine
from webcache.shell.main_window import MainWindow


class _StubEngine:
    """Mirrors the recovery engine's exported surface for this test:
    no carved page/log artifacts, no structured records, one tombstone
    -- the shape `_on_recovery_loaded` leaves `engine.tombstones` in."""

    def __init__(self, tombstones):
        self.structured_records = []
        self.tombstones = tombstones

    def all_artifacts(self):
        return []


def _stub_engine():
    return _StubEngine([
        {"Table": "Container_11", "KeyColumns": ("UrlHash", "EntryId"),
         "KeyValues": (123456789, 42)},
    ])


def test_recovered_artifacts_includes_a_stub_shaped_for_build_entry_row(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w._recovery_engine = _stub_engine()

    recovered = w._recovered_artifacts()

    stubs = [a for a in recovered
             if "Deleted-record stub" in str(a.get("RecoverySource", ""))]
    assert len(stubs) == 1
    stub = stubs[0]
    assert stub["EntryId"] == 42
    assert stub["UrlHash"] == 123456789
    assert stub["TableName"] == "Container_11"
    assert stub["Url"] == ""


def test_case_sqlite_carries_one_row_for_the_stub(tmp_path, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w._recovery_engine = _stub_engine()

    out = tmp_path / "c.sqlite"
    engine = ForensicEngine()
    engine.load_entries([])
    engine.export_sqlite([], str(out), recovered=w._recovered_artifacts())

    con = sqlite3.connect(out)
    rows = con.execute(
        "select EntryId, RecordSource from records "
        "where RecordSource like 'RECOVERED — Deleted-record stub%'"
    ).fetchall()
    assert rows == [(42, "RECOVERED — Deleted-record stub (b-tree key only) "
                          "(exact key: UrlHash 123456789, EntryId 42 "
                          "confidence)")]


# --- one builder, so screen and files cannot drift -------

_PLACED_STUB = {"Table": "Container_11", "KeyColumns": ("UrlHash", "EntryId"),
                "KeyValues": (123456789, 42), "Page": 5, "Offset": 0x3B0523,
                "Source": "WebCacheV01.dat", "ContainerId": 11,
                "ContainerType": "History"}


def _stub_artifact():
    from webcache.shell import recovery_loader
    build = getattr(recovery_loader, "stub_artifact", None)
    assert build is not None, "recovery_loader.stub_artifact is missing"
    return build


def test_stub_artifact_states_the_key_the_file_and_where_it_lies():
    from webcache.shell.recovery_loader import TOMBSTONE_METHOD
    art = _stub_artifact()(_PLACED_STUB)
    assert art["Confidence"] == "exact key: UrlHash 123456789, EntryId 42"
    assert art["RecoverySource"] == TOMBSTONE_METHOD
    assert art["TableName"] == "Container_11"
    assert art["ContainerName"] == "Container_11"
    assert art["Source"] == "WebCacheV01.dat"
    assert art["Page"] == 5 and art["Offset"] == 0x3B0523
    assert art["ContainerType"] == "History"
    assert art["UrlHash"] == 123456789 and art["EntryId"] == 42
    assert art["Url"] == ""


def test_a_stub_with_no_decodable_key_says_so():
    art = _stub_artifact()({"Table": "LeakFiles", "KeyColumns": (),
                            "KeyValues": ()})
    assert art["Confidence"] == "key not decoded"


def test_the_screen_row_and_the_export_artifact_agree(qtbot):
    from webcache.shell.recovery_loader import deleted_records_rows
    w = MainWindow()
    qtbot.addWidget(w)
    engine = _StubEngine([_PLACED_STUB])
    w._recovery_engine = engine

    screen = deleted_records_rows(engine)[0]
    exported = [a for a in w._recovered_artifacts()
                if a.get("EntryId") == 42][0]
    for key in ("Source", "Offset", "Page", "ContainerType"):
        assert screen.get(key) == exported.get(key), (
            key, screen.get(key), exported.get(key))
    # the screen says "exact" and keeps the key in its own column; the
    # export artifact keeps the combined sentence for writers with no Key
    # column. Both name the same two facts.
    assert exported["Confidence"] == "%s key: %s" % (
        screen["Confidence"], screen["Key"])
    assert exported["Source"] == "WebCacheV01.dat"


def test_the_recovered_csv_keeps_the_key_a_stub_proves(tmp_path):
    """recovered_csv (and the xlsx Recovered sheet, kape_csv, pdf) never
    run build_entry_row, so the key reaches them only through Confidence."""
    import csv
    art = _stub_artifact()(_PLACED_STUB)
    path = str(tmp_path / "r.csv")
    ForensicEngine._write_recovered_csv([art], path)
    with open(path, encoding="utf-8-sig", newline="") as fh:
        text = fh.read()
    assert "UrlHash 123456789" in text and "EntryId 42" in text
