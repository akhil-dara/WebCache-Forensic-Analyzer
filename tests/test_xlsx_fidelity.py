"""The workbook must keep the evidence's values exactly and execute nothing.

Three defects in ForensicEngine.export_xlsx / write_table, found by opening
what it writes:

  1. A string from the evidence beginning with "=" (or "+", "-", "@") is
     written with no type guard, so openpyxl infers it as a live FORMULA.
     A saved string starting with "=HYPERLINK(...)" becomes an executing
     cell the moment the workbook is opened. The project's _FORMULA_LEAD
     guard exists on two CSV writers already; the xlsx writer has none.

  2. openpyxl converts every Python int to float. Below 2**53 that is
     exact; above it, UrlHash values and raw FILETIMEs are silently
     changed (scientific notation, lost low bits).

  3. Every cell is run through the Excel date converter regardless of
     which column it is in, so a date-SHAPED string sitting in a text
     column (e.g. a page title that happens to read like a timestamp)
     becomes a real date. A value must become a date because its COLUMN
     says so, never because it happens to parse as one.

The fix must never rewrite a stored string to make Excel behave -- only
the cell's TYPE may be forced (data_type = "s"). Rewriting the value
would itself be evidence tampering.
"""
import openpyxl
import pytest

from webcache.engine import forensic_engine


def _book(tmp_path, entry):
    engine = forensic_engine.ForensicEngine()
    entries = [entry]
    engine.load_entries(entries)
    path = str(tmp_path / "b.xlsx")
    engine.export_xlsx(entries, path, True, {"examiner": "E"}, {}, {},
                       None, None, None, engine.get_statistics())
    return openpyxl.load_workbook(path)


def _all_records_cell(wb, header):
    ws = wb["All Records"]
    heads = [c.value for c in ws[1]]
    return ws.cell(row=2, column=heads.index(header) + 1)


def _history_cell(wb, header):
    ws = wb["History"]
    heads = [c.value for c in ws[1]]
    return ws.cell(row=2, column=heads.index(header) + 1)


_BASE_ENTRY = {"ContainerType": "History", "ContainerName": "History",
              "EntryId": 1, "ContainerId": 1}


def test_a_string_beginning_with_equals_is_text_not_a_formula(tmp_path):
    entry = dict(_BASE_ENTRY, Url='=HYPERLINK("x")')
    c = _all_records_cell(_book(tmp_path, entry), "Url (raw)")
    assert c.data_type == "s"
    assert c.value == '=HYPERLINK("x")'


@pytest.mark.parametrize("lead", ["=", "+", "-", "@"])
def test_every_formula_lead_character_is_kept_as_text(tmp_path, lead):
    value = lead + "cmd|'/c calc'!A1"
    entry = dict(_BASE_ENTRY, Url=value)
    c = _all_records_cell(_book(tmp_path, entry), "Url (raw)")
    assert c.data_type == "s"
    assert c.value == value


def test_an_integer_above_2_to_53_is_kept_exactly(tmp_path):
    big = 2 ** 60 + 7
    entry = dict(_BASE_ENTRY, UrlHash=big)
    c = _all_records_cell(_book(tmp_path, entry), "UrlHash")
    assert str(c.value) == str(big)


def test_an_integer_at_or_below_2_to_53_stays_numeric(tmp_path):
    small = 2 ** 53
    entry = dict(_BASE_ENTRY, UrlHash=small)
    c = _all_records_cell(_book(tmp_path, entry), "UrlHash")
    assert c.data_type == "n"
    assert c.value == small


def test_a_negative_integer_stays_numeric_not_text(tmp_path):
    """A negative number is not a formula-lead character. Only a leading
    '-' on a STRING must be neutralised; a real negative int/float must
    stay a live number cell."""
    entry = dict(_BASE_ENTRY, FileSize=-42)
    c = _all_records_cell(_book(tmp_path, entry), "FileSize")
    assert c.data_type == "n"
    assert c.value == -42


def test_a_date_shaped_string_in_a_text_column_stays_text(tmp_path):
    entry = dict(_BASE_ENTRY, SPS_PageTitle="2024-06-15 08:30:00")
    c = _history_cell(_book(tmp_path, entry), "Page title")
    assert isinstance(c.value, str)
    assert c.value == "2024-06-15 08:30:00"


def test_a_real_timestamp_column_still_becomes_a_date(tmp_path):
    """Must-not-regress: the fix that gates the date conversion on the
    column must not also blind it -- AccessedTime is a real Timestamps
    column and its value must still land as a real datetime cell."""
    import datetime
    entry = dict(_BASE_ENTRY, AccessedTime="2024-06-15 08:30:00")
    c = _all_records_cell(_book(tmp_path, entry), "AccessedTime (UTC)")
    assert isinstance(c.value, datetime.datetime)


# --- the Case Info sheet takes the same guards ----------

def _case_info(tmp_path, case_meta):
    engine = forensic_engine.ForensicEngine()
    entries = [dict(_BASE_ENTRY, Url="http://example.test/")]
    engine.load_entries(entries)
    path = str(tmp_path / "ci.xlsx")
    engine.export_xlsx(entries, path, True, case_meta, {}, {},
                       None, None, None, engine.get_statistics())
    ws = openpyxl.load_workbook(path)["Case Info"]
    return {ws.cell(row=r, column=1).value: ws.cell(row=r, column=2)
            for r in range(3, ws.max_row + 1)}


def test_a_case_info_note_beginning_with_equals_is_text_not_a_formula(tmp_path):
    cells = _case_info(tmp_path, {"examiner": "E",
                                  "notes": '=HYPERLINK("x")'})
    cell = cells["Notes"]
    assert cell.data_type == "s", "a free-text note became a formula"
    assert cell.value == '=HYPERLINK("x")'


@pytest.mark.parametrize("lead", ["+", "-", "@"])
def test_every_formula_lead_in_case_info_is_kept_as_text(tmp_path, lead):
    cells = _case_info(tmp_path, {"examiner": lead + "SUM(1)",
                                  "case_number": lead + "42"})
    for key, expected in (("Examiner", lead + "SUM(1)"),
                          ("Case number", lead + "42")):
        assert cells[key].data_type == "s", key
        assert cells[key].value == expected, key


def test_a_timestamp_shaped_case_note_stays_text(tmp_path):
    cells = _case_info(tmp_path, {"examiner": "E",
                                  "notes": "2026-02-17 16:50:09"})
    assert cells["Notes"].value == "2026-02-17 16:50:09", (
        "a note shaped like a timestamp became a date cell")


def test_case_info_generated_utc_is_still_a_real_date(tmp_path):
    import datetime as _dt
    cells = _case_info(tmp_path, {"examiner": "E"})
    assert isinstance(cells["Generated (UTC)"].value, _dt.datetime)
