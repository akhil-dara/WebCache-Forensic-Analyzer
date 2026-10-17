"""A format export's status line says how many of what it wrote.

Seen exporting a real exhibit's positions: "Exported to fixes.csv" -- the
94 the file held was in its sidecar and nowhere on screen, while a view
export says "Exported 26 of 112 rows". The number is read back from the
sidecar the writer just produced, in the unit that format counts.
"""
import json

from webcache.shell import main_window


def _written(tmp_path, rows, name="x.csv"):
    data = tmp_path / name
    data.write_text("x", encoding="utf-8")
    side = tmp_path / (name + ".metadata.json")
    side.write_text(json.dumps({"rows_written": rows}), encoding="utf-8")
    return [str(data), str(side)]


def test_positions_are_counted_as_position_fixes(tmp_path):
    assert main_window._written_count("loc_csv", _written(tmp_path, 94)) == (
        "94 position fixes")
    assert main_window._written_count("loc_kml", _written(tmp_path, 1)) == (
        "1 position fix")


def test_a_merged_file_says_it_holds_both_origins(tmp_path):
    assert main_window._written_count("csv", _written(tmp_path, 2861)) == (
        "2,861 records, live and recovered")


def test_a_format_whose_count_is_not_its_contents_says_nothing(tmp_path):
    """The PDF lists selected records; its sidecar's number is not what
    the reader will find in it."""
    assert main_window._written_count("pdf", _written(tmp_path, 982)) == ""


def test_no_sidecar_no_number(tmp_path):
    data = tmp_path / "x.csv"
    data.write_text("x", encoding="utf-8")
    assert main_window._written_count("loc_csv", [str(data)]) == ""


def _sectioned(tmp_path, live, recovered, section, name="x.xlsx"):
    data = tmp_path / name
    data.write_text("x", encoding="utf-8")
    side = tmp_path / (name + ".metadata.json")
    side.write_text(json.dumps({
        "rows_written": live, "recovered_rows_written": recovered,
        "recovered_rows_section": section}), encoding="utf-8")
    return [str(data), str(side)]


def test_a_sectioned_file_names_its_recovered_records_and_where(tmp_path):
    """The workbook holds the recovered records on a sheet of their own;
    "982 live records" alone read as "recovered left out"."""
    paths = _sectioned(tmp_path, 982, 1879, "Recovered sheet")
    assert main_window._written_count("xlsx", paths) == (
        "982 live records and 1,879 recovered records (Recovered sheet)")


def test_a_sectioned_file_with_nothing_recovered_says_live_only(tmp_path):
    paths = _sectioned(tmp_path, 982, 0, "recovered_artifacts", "x.json")
    assert main_window._written_count("json", paths) == "982 live records"
