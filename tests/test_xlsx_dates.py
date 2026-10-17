"""The named regression, checked in the written file rather than in the
code that claims to have fixed it.

Two defects have shipped in this project's lineage, both in the workbook,
both invisible to a green suite because nothing ever opened the file:

  1. 13,481 of 13,513 timestamp cells were TEXT, not dates. A text cell
     that looks like a date sorts alphabetically and offers nothing to a
     date filter. excel_datetime() was added to fix it -- and it fixes the
     SHAPE of the string, which is only half the job: openpyxl writes a
     Python str as a string cell, and Excel does not re-parse string cells
     when it opens an .xlsx. The cell has to carry a real datetime with a
     number format, or the timestamp is still text.

  2. 175 columns were narrower than the values in them and had to be
     widened by hand before they could be read.

So these assertions read data_type and number_format off the cells, and
column_dimensions off the sheet. Nothing here trusts a comment.
"""
import datetime
import os

import pytest

from webcache.engine import forensic_engine
from webcache.shell import export_formats as F
from webcache.widgets.column_spec import Column

openpyxl = pytest.importorskip("openpyxl")


def _entries():
    return [{"Url": "http://example.test/page", "CleanUrl": "http://example.test/page",
             "ContainerType": "History", "ContainerName": "History",
             "AccessedTime": "2026-02-17T16:50:09Z",
             "AccessedTime_raw": 133843382090000000,
             "AccessCount": 2, "EntryId": 1, "ContainerId": 3}]


@pytest.fixture
def workbook(tmp_path):
    engine = forensic_engine.ForensicEngine()
    entries = _entries()
    engine.load_entries(entries)
    path = str(tmp_path / "workbook.xlsx")
    engine.export_xlsx(entries, path, True, {"examiner": "E"}, {},
                       {}, None, None, None, engine.get_statistics())
    return openpyxl.load_workbook(path)


def _looks_like_a_timestamp(value):
    return (isinstance(value, str) and len(value) >= 19
            and value[4] == "-" and value[7] == "-" and value[10] == " ")


def test_no_timestamp_cell_is_left_as_text(workbook):
    """The half of the fix that was missing: excel_datetime normalises the
    string, and then openpyxl writes it as a string cell anyway."""
    offenders = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if _looks_like_a_timestamp(cell.value):
                    offenders.append(
                        "%s!%s = %r" % (sheet.title, cell.coordinate,
                                        cell.value))
    assert not offenders, (
        "%d timestamp cell(s) are text, not dates: %s"
        % (len(offenders), offenders[:5]))


def test_a_timestamp_cell_is_a_real_datetime_with_a_number_format(workbook):
    sheet = workbook["All Records"]
    headers = [c.value for c in sheet[1]]
    found = []
    for index, header in enumerate(headers, 1):
        cell = sheet.cell(row=2, column=index)
        if isinstance(cell.value, datetime.datetime):
            found.append((header, cell))
    assert found, "no datetime cell at all in All Records"
    for header, cell in found:
        assert cell.number_format != "General", header
        assert "yy" in cell.number_format.lower(), (
            "%s carries a datetime with no date format, so Excel shows it "
            "as a serial number" % header)


def test_the_precision_of_the_evidence_survives(workbook):
    """Milliseconds are kept. Two records a few ms apart are a sequence;
    rounded to the second they are a tie, and the order they happened in
    is gone."""
    sheet = workbook["All Records"]
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, datetime.datetime):
                assert "ss" in cell.number_format, cell.coordinate


def test_no_column_is_narrower_than_its_own_heading(workbook):
    """175 columns shipped narrower than the values in them."""
    for sheet in workbook.worksheets:
        for index, cell in enumerate(sheet[1], 1):
            if cell.value in (None, ""):
                continue
            letter = cell.column_letter
            width = sheet.column_dimensions[letter].width
            assert width, "%s!%s has no width set at all" % (sheet.title, letter)
            assert width >= len(str(cell.value)), (
                "%s!%s is %.1f wide for a %d-character heading %r"
                % (sheet.title, letter, width, len(str(cell.value)),
                   cell.value))


def test_no_column_is_narrower_than_the_values_in_it(workbook):
    """The defect as it was actually reported: a nine-character heading
    over 765-character values came out 13 wide, and 175 columns had to be
    widened by hand before they could be read. Capped at
    XLSX_MAX_COL_WIDTH, because a 2,096-character blob cannot be a
    2,096-wide column either -- the value is never truncated, only the
    view of it."""
    cap = forensic_engine.XLSX_MAX_COL_WIDTH
    for sheet in workbook.worksheets:
        longest = {}
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, str):
                    longest[cell.column_letter] = max(
                        longest.get(cell.column_letter, 0), len(cell.value))
        for letter, length in longest.items():
            width = sheet.column_dimensions[letter].width
            assert width >= min(length, cap), (
                "%s!%s is %.1f wide for values up to %d characters"
                % (sheet.title, letter, width or 0, length))


# --- the other caller of the same rule -----------------------------------

def test_the_view_csv_uses_the_same_normaliser(tmp_path):
    """The two writers that must not drift: export_xlsx and
    export_formats.write_view_csv. Pinning only one of them is how they
    came apart the first time."""
    import csv
    rows = [{"When": datetime.datetime(2026, 2, 17, 16, 50, 9),
             "_kind": "history"}]
    path = str(tmp_path / "view.csv")
    F.write_view_csv(rows, [Column("When", "Last visit (UTC)", 160,
                                   kind="time")], path, {})
    with open(path, encoding="utf-8-sig", newline="") as fh:
        body = list(csv.reader(fh))
    assert body[1][0] == forensic_engine.excel_datetime(
        "2026-02-17 16:50:09")
    assert "T" not in body[1][0]


# --- the sidecar cannot be half-written beside a whole export ------------

def test_the_metadata_sidecar_is_written_atomically(tmp_path):
    """A sidecar that dies mid-write leaves a truncated JSON file beside a
    complete export -- and a truncated provenance document is worse than
    none, because it looks like one."""
    import inspect
    src = inspect.getsource(
        forensic_engine.ForensicEngine._write_metadata_sidecar)
    assert "atomic_write" in src or "atomic_path" in src, (
        "every other writer in this module publishes only completed files; "
        "this one used a plain open()")


def test_a_failing_sidecar_leaves_no_partial_file(tmp_path):
    engine = forensic_engine.ForensicEngine()
    path = str(tmp_path / "export.csv")
    open(path, "w").close()

    # A dict with a tuple key: json.dump raises on it even with
    # default=str, which only covers unserialisable VALUES.
    with pytest.raises(TypeError):
        engine._write_metadata_sidecar(
            path, {"examiner": {(1, 2): "x"}}, {}, rows_written=1)
    leftovers = [n for n in os.listdir(str(tmp_path))
                 if n.endswith(".partial")]
    assert leftovers == [], leftovers
    assert not os.path.exists(path + ".metadata.json"), (
        "a sidecar that failed must not exist at all")


def test_every_column_headed_utc_or_local_holds_dates_on_every_sheet(workbook):
    """A heading that names a clock promises a date. The focused History
    sheet's own sort column, "Visit (UTC)", was RFC 3339 TEXT
    ("2026-02-17T16:50:09Z") -- found by exporting a real exhibit and
    reading the cell types back: the check above only recognised the
    space-separated shape, so the T...Z shape walked past it. An RFC3339
    column says so in its heading and stays verbatim; this test does not
    touch those."""
    offenders = []
    for ws in workbook.worksheets:
        header = [c.value for c in ws[1]]
        for ci, title in enumerate(header, 1):
            if not isinstance(title, str) or "RFC3339" in title:
                continue
            if not (title.endswith("(UTC)") or title.endswith("(LOCAL)")):
                continue
            for row in ws.iter_rows(min_row=2, min_col=ci, max_col=ci):
                value = row[0].value
                if isinstance(value, str) and value.strip():
                    offenders.append((ws.title, title, value))
    assert offenders == []
