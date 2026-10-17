"""The offline report's one cell encoding.

Every cell is stored as exactly what the app's own view CSV writes for it,
plus a tag for each fact that text alone loses. These tests hold the
encoding to the app's writers themselves -- never to a re-typed copy of
their rules -- so a change to export_formats moves both together."""
import csv
import datetime
import os
import re

import pytest

from webcache.engine import forensic_engine
from webcache.engine.case_db import CaseDb
from webcache.shell import export_formats, record_kinds
from webcache.widgets import column_spec
from webcache.widgets.column_spec import Column

UTC = datetime.timezone.utc

VALUES = [
    None, "", "plain", "=1+1", "+cmd", "-3", "@SUM(A1)", "a,b", 'q"uote',
    "line1\nline2", "  padded  ", 0, -7, 2 ** 53, 2 ** 53 + 1, -(2 ** 60),
    1.0, 0.25, -1.5e-07, 1e16, True, False,
    datetime.datetime(2026, 2, 17, 16, 50, 9, 123456, tzinfo=UTC),
    datetime.datetime(2026, 2, 17, 16, 50, 9),
    datetime.datetime(1601, 1, 1),
    "2026-02-17T16:50:09Z", "2026-02-17 16:50:09 UTC", b"\x00\x01",
    b"\xff\x10", "nul\x00inside", "lone\ud800surrogate", "ctl\x07\x7f",
    "\x01tagged", float("nan"), float("inf"), float("-inf"),
]

#: Every kind the app's column specs can declare. The parametrised test
#: below runs each one; the structural test fails if a spec uses a kind
#: this list lacks (or KINDS grows without a case here).
KINDS_TESTED = list(column_spec.KINDS)

TAG_CHARS = ("\x01", "\x02", "\x03", "\x04")


def _strip(value):
    """The CSV text a stored cell stands for (what the page writes)."""
    if value is None:
        return ""
    if isinstance(value, str) and value[:1] in TAG_CHARS:
        return value[1:]
    return str(value)


def _csv_cell(tmp_path, value, kind):
    """What the app's own view CSV writes for one value in a one-column view."""
    col = Column("V", "V", kind=kind)
    path = tmp_path / "one.csv"
    export_formats.write_view_csv(
        [{"V": value, "_kind": "history", "_record": None}], [col], str(path), {})
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[1][0]


@pytest.mark.parametrize("kind", KINDS_TESTED)
@pytest.mark.parametrize("value", VALUES, ids=repr)
def test_the_stored_cell_is_what_the_view_csv_writes(tmp_path, value, kind):
    from webcache.shell.html_package import encode_cell
    flag = kind in ("time", "time_local")
    raw = export_formats._view_cells(
        {"V": value}, [Column("V", "V", kind=kind)], [], [], None, None)[0]
    assert _strip(encode_cell(raw, flag)) == _csv_cell(tmp_path, value, kind)


def test_every_kind_a_spec_declares_has_a_case():
    """A kind added to KINDS, or used by a Column(...) anywhere in the app,
    must be in KINDS_TESTED -- the parametrised parity test then runs it.
    Found by reading the sources, so a new view cannot slip one in."""
    root = os.path.dirname(os.path.dirname(column_spec.__file__))
    used = set()
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    used.update(re.findall(
                        r"""kind\s*=\s*["']([a-z_]+)["']""", fh.read()))
    assert set(KINDS_TESTED) == set(column_spec.KINDS)
    assert (used & set(column_spec.KINDS)) <= set(KINDS_TESTED)
    assert {"time_local", "bar", "path", "types"} <= set(KINDS_TESTED)


def test_tags_mark_exactly_the_facts_the_csv_text_loses():
    from webcache.shell.html_package import (TAG_BIGINT, TAG_DATETIME,
                                             TAG_FLOAT, encode_cell)
    assert (encode_cell(datetime.datetime(2026, 1, 2, 3, 4, 5), True)
            == TAG_DATETIME + "2026-01-02 03:04:05")
    assert encode_cell(2 ** 53) == 2 ** 53
    assert encode_cell(2 ** 53 + 1) == TAG_BIGINT + str(2 ** 53 + 1)
    assert encode_cell(-(2 ** 53) - 1) == TAG_BIGINT + str(-(2 ** 53) - 1)
    assert encode_cell(1.0) == TAG_FLOAT + "1.0"
    assert encode_cell(7) == 7
    assert encode_cell("") is None and encode_cell(None) is None
    assert encode_cell(True) == "Yes" and encode_cell(False) == "No"
    assert encode_cell(float("nan")) == TAG_FLOAT + "nan"
    assert encode_cell(float("-inf")) == TAG_FLOAT + "-inf"


def test_no_stored_string_can_begin_with_a_tag():
    """_safe_text escapes every control character a tag uses, so stored
    text can never be read back as a tag."""
    from webcache.shell.html_package import encode_cell
    for tag in TAG_CHARS:
        assert encode_cell(tag + "2026-01-02 03:04:05")[:1] == "\\"


def test_canonical_cells_are_what_the_view_csv_writes_for_the_record():
    from webcache.shell.html_package import canonical_cells
    record = {"EntryId": 7, "ContainerId": 3, "ContainerType": "History",
              "ContainerName": "History", "Url": "https://example.test/a",
              "CleanUrl": "https://example.test/a", "UrlHash": 2 ** 60,
              "AccessedTime_raw": 133500000000000000, "Flags": 8}
    row = {"V": "x", "_kind": "history", "_record": record}
    cols = [Column("V", "V")]
    _headers, flags, appended, canon = export_formats.view_layout([row], cols)
    start = len(cols) + len(appended)
    raw = export_formats._view_cells(row, cols, appended, canon, None, None)
    expected = [export_formats._clean(v, f)
                for v, f in zip(raw[start:], flags[start:])]
    by_key = dict(zip(forensic_engine.ENTRY_FIELD_KEYS,
                      canonical_cells(record, carved=False)))
    assert len(by_key) == len(forensic_engine.ENTRY_FIELDS) == 80
    assert ([_strip(by_key[k]) for k, _h in canon]
            == ["" if v is None else str(v) for v in expected])


def test_a_carved_record_reads_as_the_carved_writer_reads_it():
    from webcache.shell.html_package import canonical_cells
    record = {"Url": "https://example.test/c", "RecoverySource": "slack",
              "Confidence": "high", "ContainerType": "History"}
    by_key = dict(zip(forensic_engine.ENTRY_FIELD_KEYS,
                      canonical_cells(record, carved=True)))
    full = forensic_engine.build_recovered_row(record)
    assert by_key["Origin"] == full["Origin"]
    assert by_key["Method"] == "slack"
    assert by_key["IsInPrivate"] == full["IsInPrivate"]


def test_own_cells_keep_every_key_the_record_carries():
    from webcache.shell.html_package import own_cells
    cookie = {"Name": "sid", "Domain": "example.test", "Expires_raw": 2 ** 60,
              "IsSecure": True, "Value": None}
    cells = own_cells(cookie)
    assert list(cells) == ["Name", "Domain", "Expires_raw", "IsSecure", "Value"]
    assert cells["Expires_raw"] == "\x02" + str(2 ** 60)
    assert cells["IsSecure"] == "Yes" and cells["Value"] is None


def test_view_cells_carry_the_appended_origin():
    from webcache.shell.html_package import view_cells
    row = {"V": True, "Origin": "Live record", "_kind": "history",
           "_record": {"EntryId": 1}}
    cols = [Column("V", "V", kind="flag")]
    headers, flags, appended, _canon = export_formats.view_layout([row], cols)
    cells = view_cells(row, cols, appended, flags)
    assert cells[0] == "Yes"
    assert headers[1:3] == ["Origin", "RecordSource"]
    assert cells[1] == "Live record" and cells[2] is None


# --- whole rows against the app's own CSV --------------------------------

def _csv_rows(tmp_path, rows, cols, tags_map=None, comments_map=None):
    path = tmp_path / "rows.csv"
    export_formats.write_view_csv(rows, cols, str(path), {}, tags_map,
                                  comments_map)
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def _page_row(row, cols, rows, tags_map=None, comments_map=None):
    """One row exactly as the page will store it: view cells, then the
    canonical or own block in the layout's own order."""
    from webcache.shell.html_package import (canonical_cells, own_cells,
                                             view_cells)
    headers, flags, appended, canon = export_formats.view_layout(rows, cols)
    cells = view_cells(row, cols, appended, flags)
    block = export_formats._block_of(row)
    record = export_formats._record_of(row)
    entry = None
    if block == "entry":
        carved = (export_formats.origin_cell(row)
                  == export_formats.provenance.CARVED_ORIGIN)
        entry = dict(zip(forensic_engine.ENTRY_FIELD_KEYS,
                         canonical_cells(record, carved, tags_map,
                                         comments_map)))
    own = own_cells(record) if block == "own" else {}
    for key, _h in canon:
        if isinstance(key, tuple):
            cells.append(own.get(key[1]))
        else:
            cells.append(None if entry is None else entry.get(key))
    return headers, cells


def _assert_rows_match_csv(tmp_path, rows, cols, tags_map=None,
                           comments_map=None):
    written = _csv_rows(tmp_path, rows, cols, tags_map, comments_map)
    assert len(written) == len(rows) + 1
    for row, csv_row in zip(rows, written[1:]):
        headers, cells = _page_row(row, cols, rows, tags_map, comments_map)
        assert headers == written[0]
        assert [_strip(c) for c in cells] == csv_row


def test_rows_with_datetimes_tags_and_comments_match_the_csv_byte_for_byte(
        tmp_path):
    record = {"EntryId": 7, "ContainerId": 3, "ContainerType": "History",
              "ContainerName": "History", "Url": "https://example.test/a",
              "CleanUrl": "https://example.test/a", "UrlHash": 2 ** 60,
              "AccessedTime_raw": 133500000000000000, "Flags": 8,
              "Title": "=alice"}
    key = CaseDb.record_keys(record)[0]
    tags_map = {key: ["Reviewed", "alice"]}
    comments_map = {key: [{"comment": "seen on example.test"}, "second"]}
    cols = [Column("When", "When", kind="time"),
            Column("Local", "Local", kind="time_local"),
            Column("Plain", "Plain", kind="text"),
            Column("Hash", "Hash", kind="offset"),
            Column("Ratio", "Ratio", kind="num")]
    when = datetime.datetime(2026, 2, 17, 16, 50, 9, 5, tzinfo=UTC)
    rows = [{"When": when, "Local": datetime.datetime(2026, 2, 17, 16, 50, 9),
             "Plain": when, "Hash": 2 ** 60, "Ratio": 0.5,
             "_kind": "history", "_record": record}]
    _assert_rows_match_csv(tmp_path, rows, cols, tags_map, comments_map)
    _headers, cells = _page_row(rows[0], cols, rows, tags_map, comments_map)
    texts = [_strip(c) for c in cells]
    assert "Reviewed, alice" in texts
    assert "seen on example.test || second" in texts


def test_a_carved_row_matches_the_csv_byte_for_byte(tmp_path):
    record = {"Url": "https://example.test/c", "RecoverySource": "slack",
              "Confidence": "high", "ContainerType": "History",
              "Title": "carved\x00title\ud800"}
    cols = [Column("Url", "Url", kind="url")]
    rows = [{"Url": record["Url"], "Source": "carved", "Origin": "Carved",
             "_kind": "history", "_record": record, "_carved": True}]
    written = _csv_rows(tmp_path, rows, cols)
    _headers, cells = _page_row(rows[0], cols, rows)
    assert [_strip(c) for c in cells] == written[1]
    assert export_formats.origin_cell(rows[0]) \
        == export_formats.provenance.CARVED_ORIGIN, \
        "the fixture must really be a carved row"


def test_an_own_record_row_matches_the_csv_byte_for_byte(tmp_path):
    cookie = {"Name": "sid", "Domain": "example.test", "Expires_raw": 2 ** 60,
              "IsSecure": True, "Value": None, "Blob": b"\xde\xad",
              "Weight": 1.0, "Seen": datetime.datetime(2026, 1, 2, 3, 4, 5)}
    cols = [Column("Name", "Name")]
    rows = [{"Name": "sid", "_kind": record_kinds.K_COOKIE,
             "_record": cookie}]
    assert export_formats._block_of(rows[0]) == "own"
    _assert_rows_match_csv(tmp_path, rows, cols)


# --- the timestamp rule -------------------------------------------------

def test_a_datetime_is_a_date_cell_only_in_a_timestamp_column():
    """xlsx_cell_parts makes a date cell only for a timestamp column; the
    page must carry exactly that rule."""
    from webcache.shell.html_package import TAG_DATETIME, encode_cell
    when = datetime.datetime(2026, 2, 17, 16, 50, 9, tzinfo=UTC)
    inside = encode_cell(when, True)
    outside = encode_cell(when, False)
    assert inside.startswith(TAG_DATETIME)
    assert not outside.startswith(TAG_DATETIME)
    in_value = forensic_engine.xlsx_cell_parts(when, True)[0]
    out_value = forensic_engine.xlsx_cell_parts(when, False)[0]
    assert isinstance(in_value, datetime.datetime)
    assert out_value == outside


# --- raw values survive --------------------------------------------------

def test_bytes_are_uppercase_hex_with_a_bytes_tag():
    from webcache.shell.html_package import TAG_BYTES, TAGS, encode_cell
    assert TAG_BYTES in TAGS
    assert encode_cell(b"\x00\xff\x10") == TAG_BYTES + "00FF10"
    assert forensic_engine.xlsx_cell_parts(b"\x00\xff\x10", False)[0] == "00FF10"


def _unescape(text):
    text = re.sub(r"\\u([0-9A-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    return re.sub(r"\\x([0-9A-F]{2})", lambda m: chr(int(m.group(1), 16)), text)


@pytest.mark.parametrize("original", [
    "a\x00b", "lone\ud800x\udfff", "bell\x07del\x7f", "\x01\x02\x03\x04",
    "plain text", "tab\tnewline\n"])
def test_nul_controls_and_lone_surrogates_are_escaped_and_reversible(original):
    from webcache.shell.html_package import encode_cell
    stored = encode_cell(original)
    assert "\x00" not in stored
    assert not re.search("[\ud800-\udfff]", stored)
    assert _unescape(stored) == original
    assert forensic_engine.xlsx_cell_parts(original, False)[0] == stored


def test_nan_and_infinity_are_text_tokens_in_every_writer(tmp_path):
    from webcache.shell.html_package import TAG_FLOAT, encode_cell
    for number, token in ((float("nan"), "nan"), (float("inf"), "inf"),
                          (float("-inf"), "-inf")):
        assert encode_cell(number) == TAG_FLOAT + token
        assert forensic_engine.xlsx_cell_parts(number, False)[0] == token
        assert _csv_cell(tmp_path, number, "num") == token


def test_the_export_sidecar_states_the_escaping(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("a\n", encoding="utf-8")
    side = export_formats.write_view_provenance(str(path), {}, {}, 0)
    with open(side, encoding="utf-8-sig") as fh:
        text = fh.read()
    assert "uppercase hex" in text
    assert "\\uD800" in text and "\\x00" in text
    assert "nan" in text
