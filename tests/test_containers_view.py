"""ContainersView: every container the Containers table registers, and
its metadata -- one RecordSet, built on RecordsView the same way
HistoryView is (test_records_view.py already proves the base class's own
generic contract; this file proves only what ContainersView itself
declares: its columns, that the Name column drills through, and its
header/empty-state text), against rows shaped the way evidence_loader.
container_rows_from_parser() actually produces them (see
test_evidence_loader_containers.py for that shape's own tests).
"""
from webcache.provenance import CONTAINER_NOT_DETERMINABLE
from webcache.views.containers import ContainersView


def _row(**overrides):
    base = {
        "Id": 1, "Name": "Container_1", "Type": "Content",
        "Records": 10, "Size": 1024, "Partition": "p0",
        "Directory": "C:\\cache",
        "LastAccess": "2026-01-01 00:00:00 UTC",
        "LastScavenge": "2026-01-02 00:00:00 UTC",
    }
    base.update(overrides)
    return base


def make_rows(n):
    return [_row(Id=i, Name="Container_%d" % i, Records=i * 10) for i in range(n)]


# --- columns -------------------------------------------------------------

def test_columns_match_the_spec(qtbot):
    v = ContainersView()
    qtbot.addWidget(v)
    keys = [c.key for c in v.COLUMNS]
    assert keys == ["Id", "Name", "Type", "Records", "Size", "Partition",
                    "Directory", "LastAccess", "LastScavenge"]


def test_the_name_column_drills_through(qtbot):
    v = ContainersView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "Name")
    assert col.is_link
    with qtbot.waitSignal(v.drillRequested, timeout=1000) as sig:
        col.on_click({"Id": 1, "Name": "Container_1"})
    assert sig.args[0] == "browser"


def test_directory_column_uses_the_path_kind_not_url(qtbot):
    v = ContainersView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "Directory")
    assert col.kind == "path"
    assert col.is_link is False


def test_size_column_uses_the_size_kind(qtbot):
    v = ContainersView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "Size")
    assert col.kind == "size"


# --- the table itself -----------------------------------------------------

def test_the_table_shows_every_record(qtbot):
    v = ContainersView()
    v.set_records(make_rows(22))
    qtbot.addWidget(v)
    assert v.table.model().rowCount() == 22
    assert "22" in v.count_label.text()


def test_typing_in_the_filter_box_narrows_the_table(qtbot):
    from PySide6.QtTest import QTest

    v = ContainersView()
    v.set_records(make_rows(50))
    qtbot.addWidget(v)
    QTest.keyClicks(v.filter_box, "Container_1")
    qtbot.waitUntil(lambda: v.table.model().rowCount() < 50, timeout=3000)


def test_a_not_determinable_records_value_does_not_crash_sorting(qtbot):
    """A container whose Container_<id> table is gone reports Records as
    provenance.CONTAINER_NOT_DETERMINABLE -- a string in a numeric
    column -- alongside rows with real integer counts. Sorting must not
    raise on the mixed types."""
    v = ContainersView()
    rows = make_rows(5)
    rows[0]["Records"] = CONTAINER_NOT_DETERMINABLE
    v.set_records(rows)
    qtbot.addWidget(v)
    v.table.model().sort_by("Records", False)
    v.table.model().sort_by("Records", True)
    assert v.table.model().rowCount() == 5


def test_no_quick_filters_means_no_chip_row(qtbot):
    v = ContainersView()
    qtbot.addWidget(v)
    assert v._quick_filters == []


def test_it_has_no_switcher_being_a_single_record_set(qtbot):
    v = ContainersView()
    qtbot.addWidget(v)
    assert v._switcher_buttons == {}


# --- the genuine empty state ------------------------------------------------

def test_zero_records_because_none_exist_reads_as_a_genuine_empty_state(qtbot):
    v = ContainersView()
    v.set_records([])
    qtbot.addWidget(v)
    assert v.table.showing_genuine_empty_state() is True
    assert "Clear filters" not in v.count_label.text()


def test_an_emptied_filter_offers_a_way_back(qtbot):
    from PySide6.QtTest import QTest

    v = ContainersView()
    v.set_records(make_rows(20))
    qtbot.addWidget(v)
    QTest.keyClicks(v.filter_box, "zzzz-nothing-matches")
    qtbot.waitUntil(lambda: v.table.model().rowCount() == 0, timeout=3000)
    assert "Clear filters" in v.table.empty_state_text()
    v.clear_all_filters()
    assert v.table.model().rowCount() == 20


def test_header_and_caveat_are_reachable(qtbot):
    v = ContainersView()
    qtbot.addWidget(v)
    assert v.header is not None
    v.set_caveat("Container metadata as the database records it.")
    assert v.caveat is not None
