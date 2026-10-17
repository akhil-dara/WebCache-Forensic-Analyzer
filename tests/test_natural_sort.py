"""Excel-grade filtering (sub-project C): text sorts naturally -- "file2"
before "file10", "EntryId 9" before "EntryId 10" -- ignoring case, with a
fixed tie-break so the order is total and the offline report can match it."""
from webcache.widgets.column_spec import Column
from webcache.widgets.record_filter import RecordFilter

COLS = [Column("Name", "Name")]


def _sorted(names, desc=False):
    f = RecordFilter([{"Name": n} for n in names], COLS)
    f.sort("Name", desc)
    return [r["Name"] for r in f.visible()]


def test_numbers_inside_text_sort_by_value():
    assert _sorted(["file10", "file2", "File1"]) == ["File1", "file2", "file10"]
    assert _sorted(["v1.10", "v1.9", "v1.2"]) == ["v1.2", "v1.9", "v1.10"]


def test_descending_is_the_exact_reverse_and_blanks_stay_last():
    names = ["b3", "b20", "", "a7"]
    assert _sorted(names) == ["a7", "b3", "b20", ""]
    assert _sorted(names, True) == ["b20", "b3", "a7", ""]


def test_the_value_list_is_in_the_same_natural_order():
    f = RecordFilter([{"Name": n} for n in ("x10", "x9", "x9", "x100")], COLS)
    assert [v for v, _n in f.value_counts("Name")] == ["x9", "x10", "x100"]
