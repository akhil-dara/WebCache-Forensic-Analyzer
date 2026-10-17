"""The record dialog fits, reveals what it names, and
states provenance in words for every carved kind."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from webcache.shell import detail_fields
from webcache.shell.record_kinds import K_CARVED_STRUCT, K_TABLE_ROW
from tests.test_detail_fields import carved_struct_row
from tests._native_screen import skip_unless_measurable


def test_revealing_the_carve_bytes_never_pushes_close_off_the_screen():
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": "."}
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests._record_dialog_fit_probe"],
        capture_output=True, text=True, timeout=300, cwd=root, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout.strip()
    skip_unless_measurable(out)
    values = dict(part.split("=", 1) for part in out.split(" ", 4))
    assert int(values["frame"]) <= int(values["avail"]), out
    assert int(values["close_bottom"]) <= int(values["dialog_h"]), out
    assert values["tab"] == "Bytes at the carve offset", out


def test_a_carved_file_access_record_gets_the_same_provenance_strip():
    row = {"CleanUrl": "file:///C:/Users/alice/x.txt", "Origin":
           "Carved (deleted/unflushed)", "Source": "WebCacheV01.dat",
           "_kind": K_CARVED_STRUCT,
           "_record": {"Offset": 8192, "Page": 2, "Confidence": "high",
                       "RecoverySource": "Structured record reconstruction"}}
    facts = dict(detail_fields.provenance_facts(row))
    assert facts == {"Carved from": "WebCacheV01.dat", "Offset": "0x00002000",
                     "Page": "2", "Method": "Structured record reconstruction",
                     "Confidence": "high"}


def test_engine_tokens_read_as_words_with_the_token_beside_them():
    row = carved_struct_row()
    row["_record"] = dict(row["_record"], RecordEndMode="sps-212",
                          Region="deleted-record")
    # The shell row wins over its record on a collision, so the fixture's
    # own Region has to say it too.
    row["Region"] = "deleted-record"
    fields = {f.key: f for f in detail_fields.flatten(
        detail_fields.fields_for(row))}
    assert "property store" in fields["RecordEndMode"].display_value
    assert "(sps-212)" in fields["RecordEndMode"].display_value
    assert "deleted record" in fields["Region"].display_value
    assert "(deleted-record)" in fields["Region"].display_value


def test_recovery_method_is_not_repeated_as_engine_method():
    row = carved_struct_row(Method="unallocated page")
    keys = [f.key for f in detail_fields.flatten(detail_fields.fields_for(row))]
    assert "Method" in keys and "RecoverySource" not in keys


def test_every_field_of_a_search_hit_is_labelled_in_words():
    hit = {"Table": "Container_2", "Container": "Content",
           "TableType": "Content", "Row": 3, "MatchedColumns": "Url",
           "FoundIn": "value", "Context": "x", "BlobOffset": None,
           "MatchedValue": "x", "RawType": "text", "RawValue": "x",
           "Url": "(empty)", "_kind": K_TABLE_ROW, "_result": {}}
    fields = detail_fields.flatten(detail_fields.fields_for(hit))
    labels = {f.key: f.label for f in fields}
    assert all(label.strip() for label in labels.values())
    assert labels["FoundIn"] == "Found in"
    assert labels["MatchedColumns"] == "Matched columns"
    assert labels["Row"] == "Row # in its table"


def test_history_and_file_access_offer_offset_page_method_columns(qtbot):
    from webcache.views.file_access import FileAccessView
    from webcache.views.history import HistoryView
    for view in (HistoryView(), FileAccessView()):
        qtbot.addWidget(view)
        optional = {c.key for c in view.COLUMNS if c.optional}
        assert {"Offset", "Page", "Method"} <= optional


def test_carved_file_access_rows_carry_their_offset_page_and_method():
    import types
    from webcache.shell.recovery_loader import carved_file_access_rows
    entry = {"Url": "file:///C:/Users/alice/x.txt",
             "CleanUrl": "file:///C:/Users/alice/x.txt", "IsLocalFile": True,
             "ContainerType": "History", "RecoverySource": "page slack",
             "Source": "WebCacheV01.dat", "Offset": 8192, "Page": 2,
             "Confidence": "low"}
    engine = types.SimpleNamespace(structured_records=[entry],
                                   all_artifacts=lambda: [])
    row = carved_file_access_rows(engine)[0]
    assert (row["Offset"], row["Page"], row["Method"]) == (8192, 2, "page slack")
    assert len(row) <= 24          # Copies, Drive, FileType: see test_row_is_a_record


def test_bytes_are_never_squeezed_inline_and_open_the_carve_tab():
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": "."}
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests._record_dialog_reveal_probe"],
        capture_output=True, text=True, timeout=300, cwd=root, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout.strip()
    skip_unless_measurable(out)
    for line in out.splitlines():
        path, rest = line.split(" ", 1)
        v = dict(part.split("=", 1) for part in rest.split(" ", 4))
        if v["inline"] == "1":
            assert int(v["region_h"]) >= int(v["region_min"]), line
        else:
            assert v["windows"] == "1", line
        assert v["tab"] == "Bytes at the carve offset", line
