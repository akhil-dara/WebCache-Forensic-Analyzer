"""The flat CSV must carry carved records (including deleted-record stubs)
alongside live ones, and its timestamp cells must be a shape Excel parses
as a date-time -- not text carrying a clock-name suffix ("... UTC",
"... LOCAL").

Found by opening what export_csv actually writes: it took no `recovered`
argument at all, so every carved record (582 / 885 / 148 on three real
samples) was silently absent from the flat CSV while the export catalogue
promised every canonical field; and its timestamp cells kept the clock
word, a shape Excel will not parse.
"""
import csv

from webcache.engine.forensic_engine import (
    ForensicEngine, ENTRY_FIELD_HEADERS, provenance,
)


def _rows(tmp_path, **kw):
    out = tmp_path / "a.csv"
    # "AccessedTime" carries the clock-word string the real parser puts
    # there (ese_parser.filetime_to_str -> stamp_str(dt, "UTC")), e.g.
    # "2024-01-17 21:20:00 UTC" -- not just the raw FILETIME int, which by
    # itself never carries a clock word and would make the clock-word
    # assertion pass vacuously regardless of whether export_csv fixes
    # anything.
    ForensicEngine.__new__(ForensicEngine).export_csv(
        [{"Url": "u1", "AccessedTime_raw": 133500000000000000,
          "AccessedTime": "2024-01-17 21:20:00 UTC"}], str(out), **kw)
    with open(out, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_carved_records_are_in_the_csv(tmp_path):
    rows = _rows(tmp_path, recovered=[{"Url": "u2", "Source": "WebCacheV01.dat",
                                       "Offset": 4096, "Confidence": "low"}])
    assert len(rows) == 2


def test_timestamps_carry_no_clock_word(tmp_path):
    rows = _rows(tmp_path)
    # Confirm the real headers before trusting the "Accessed" substring
    # filter below -- if ENTRY_FIELD_HEADERS ever drops every "Accessed"
    # header, `stamped` goes empty and `stamped and ...` correctly fails,
    # rather than the assertion vacuously passing.
    assert any("Accessed" in h for h in ENTRY_FIELD_HEADERS)
    stamped = [v for k, v in rows[0].items() if v and "Accessed" in k]
    assert stamped and all(not v.endswith((" UTC", " LOCAL")) for v in stamped)


def test_carved_row_provenance_matches_case_sqlite(tmp_path):
    """A carved row's provenance columns (Origin/Method/...) in the CSV must
    equal what export_sqlite writes for the SAME artifact -- both writers
    must derive them through the one shared helper, never two independent
    copies of the fill-in logic that could silently drift apart."""
    artifact = {"Url": "u3", "Source": "WebCacheV01.dat", "Offset": 8192,
                "RecoverySource": "Transaction log", "Confidence": "medium"}

    csv_rows = _rows(tmp_path, recovered=[artifact])
    carved_csv_row = csv_rows[-1]
    assert carved_csv_row["Url (raw)"] == "u3"

    import sqlite3
    db_out = tmp_path / "a.sqlite"
    ForensicEngine.__new__(ForensicEngine).export_sqlite(
        [{"Url": "u1", "AccessedTime_raw": 133500000000000000}],
        str(db_out), recovered=[artifact])
    con = sqlite3.connect(str(db_out))
    con.row_factory = sqlite3.Row
    sqlite_row = con.execute(
        "SELECT * FROM records WHERE Url = ?", ("u3",)).fetchone()
    con.close()

    # (internal key, CSV header) -- the CSV is keyed by ENTRY_FIELD_HEADERS
    # display strings, not the internal ENTRY_FIELD_KEYS names.
    for key, header in (("Origin", "Origin"), ("Method", "Carve method"),
                        ("Source", "Carved from file"),
                        ("Offset", "Carved at offset"),
                        ("Confidence", "Carve confidence")):
        expected = sqlite_row[key]
        assert carved_csv_row[header] == str(expected if expected is not None else "")
    assert carved_csv_row["Origin"] == provenance.CARVED_ORIGIN
    assert carved_csv_row["Origin"] != ""


def test_stub_row_has_no_invented_url_or_timestamp(tmp_path):
    """A deleted-record stub (main_window._recovered_artifacts()) has no
    URL and no timestamp of its own -- only a b-tree
    key. The CSV must not invent either for it."""
    stub = {
        "TableName": "Container_11",
        "Source": "Container_11",
        "RecoverySource": "Deleted-record stub (b-tree key only)",
        "Confidence": "exact key",
        "Url": "",
    }
    rows = _rows(tmp_path, recovered=[stub])
    stub_row = rows[-1]
    assert stub_row["Url (raw)"] == ""
    stamped = [v for k, v in stub_row.items() if "Accessed" in k or "Timestamp" in k]
    assert all(v == "" for v in stamped)
    assert stub_row["Origin"] == provenance.CARVED_ORIGIN
