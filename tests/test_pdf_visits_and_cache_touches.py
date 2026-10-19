"""The PDF report's History table keeps visits and cache touches apart.

Its "Visits" column fell back to AccessCount (cache touches, not visits)
with an asterisk explained above the table: the same merged figure the
grids no longer show, and an easy mark to miss in a printed report."""
from webcache.engine import forensic_engine as fe


def test_the_history_table_has_a_column_for_each_counter():
    rows = fe.pdf_history_rows([
        {"ContainerType": "History", "CleanUrl": "https://site.test/a",
         "ModifiedTime": "2026-02-15 10:00:00", "SPS_VisitCount": 3,
         "AccessCount": 9},
        {"ContainerType": "History", "CleanUrl": "https://site.test/b",
         "ModifiedTime": "2026-02-14 10:00:00", "AccessCount": 7},
    ])
    header, a, b = rows
    assert header == ["Visit (UTC)", "Visits", "Cache touches", "URL"]
    assert (a[1], a[2]) == ("3", "9")
    assert (b[1], b[2]) == ("", "7")
    assert not any("*" in str(cell) for row in rows for cell in row[1:3])
