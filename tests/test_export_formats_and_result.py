"""Export formats (RFC 3339 times, flags, the sidecar) and the result bar
shown after an export."""
import csv
import datetime
import os

import pytest

from webcache.engine import forensic_engine
from webcache.shell import export_formats
from webcache.views.history import HistoryView
from tests.fixtures import make_rows
from tests._native_screen import skip_unless_measurable

UTC = datetime.timezone.utc


def test_rfc3339_columns_are_written_as_rfc3339():
    for key in ("KeyTimestampUTC", "ModifiedTime_rfc", "AccessedTime_rfc"):
        assert key not in forensic_engine.TIMESTAMP_EXPORT_KEYS
    assert "ModifiedTime" in forensic_engine.TIMESTAMP_EXPORT_KEYS


def test_a_view_csv_carries_real_rfc3339_and_a_no_flag(tmp_path):
    """In the FILE: the RFC3339 cell keeps its T and Z (it is not the
    "(UTC)" column again), and a false IsInPrivate reads No, not blank."""
    from webcache.shell.record_kinds import K_HISTORY
    from webcache.widgets.column_spec import Column
    record = {"EntryId": 7, "ContainerId": 4, "ContainerType": "History",
              "Url": "https://example.test/a",
              "CleanUrl": "https://example.test/a",
              "AccessedTime_raw": 133544180420000001, "IsInPrivate": False}
    rows = [{"CleanUrl": record["CleanUrl"], "Origin": "Live record",
             "_record": record, "_kind": K_HISTORY}]
    path = str(tmp_path / "v.csv")
    export_formats.write_view_csv(
        rows, [Column("CleanUrl", "Address", 400, kind="url")], path, {})
    with open(path, encoding="utf-8-sig", newline="") as fh:
        header, row = list(csv.reader(fh))
    cell = dict(zip(header, row))
    rfc = cell["AccessedTime (RFC3339)"]
    assert "T" in rfc and rfc.endswith("Z")
    parsed = datetime.datetime.fromisoformat(rfc.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert cell["IsInPrivate"] == "No"


def test_a_false_flag_is_written_no_not_blank():
    assert forensic_engine._cell(False) == "No"
    assert forensic_engine._cell(True) == "Yes"


def test_a_view_that_declares_origin_gets_no_second_origin(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    assert export_formats.appended_columns_for(view.COLUMNS) == []


def test_the_sidecar_states_the_column_arithmetic():
    line = export_formats.column_arithmetic({
        "columns": ["c"] * 87, "view_column_count": 11,
        "canonical_entry_count": 76, "canonical_shown_count": 3})
    assert line == ("87 = 11 view columns + 76 canonical fields "
                    "(of %d in the schema; 3 already shown as view columns)"
                    % len(forensic_engine.ENTRY_FIELDS))


def test_show_in_folder_refuses_the_evidence_folder(monkeypatch, tmp_path):
    from webcache.shell import export_folder
    opened = []
    monkeypatch.setattr(export_folder, "_open_folder", opened.append)
    evidence = tmp_path / "case"
    evidence.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    from webcache.shell import export_target
    dirs = {export_target._norm(str(evidence))}
    assert export_folder.show_in_folder(str(evidence / "x.csv"), dirs) != ""
    assert opened == []
    assert export_folder.show_in_folder(str(out / "x.csv"), dirs) == ""
    assert opened == [str(out)]


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    from webcache.provenance import EvidenceSet
    from webcache.shell.main_window import MainWindow

    class _Parser:
        all_entries = []
        db = None
        db_path = "C:/case/WebCacheV01.dat"
        containers_meta = []
        container_type_map = {}

    w = MainWindow()
    qtbot.addWidget(w)
    w._on_evidence_loaded({"rows": make_rows(5), "parser": _Parser()},
                          EvidenceSet([_Parser.db_path], {_Parser.db_path: 1},
                                      {_Parser.db_path: "a" * 64}))
    return w


def test_the_full_path_is_shown_with_copy_and_show_in_folder(win, tmp_path):
    target = str(tmp_path / "history.csv")
    win._export_key = None
    win._last_view_scope = {"rows_in_file": 5, "rows_in_record_set": 5}
    win._on_export_written([target, target + ".provenance.txt"])
    bar = win.export_result_bar
    assert bar.isVisibleTo(win)
    assert target in bar.path_label.text()
    assert bar.copy_button.isEnabled() and bar.show_button.isEnabled()


def test_a_zero_row_export_asks_first(win, monkeypatch):
    history = win._ensure_view_built("history")
    history.table.model().set_text("no-such-text-anywhere")
    asked = []
    # raising=False: before F18 the method does not exist, and the red
    # must fail on the behaviour (the chooser opens), not on the patch.
    monkeypatch.setattr(win, "_confirm_empty_export",
                        lambda label: asked.append(label) or False,
                        raising=False)
    chooser = []
    monkeypatch.setattr(win, "_choose_export_path",
                        lambda *a: chooser.append(a) or "")
    win._export_view(history, "history")
    assert asked == ["History"]
    assert chooser == []


def test_a_carved_history_records_isinprivate_matches_the_views_inprivate():
    """F32 on carved rows: the History view derives InPrivate from the
    carved record's Flags (bit 0x08, History only -- the live rule), so the
    canonical IsInPrivate beside it must say the same, not blank."""
    from webcache.shell import recovery_loader
    carved = {"Url": "https://example.test/c",
              "CleanUrl": "https://example.test/c", "Flags": 0x01,
              "ContainerType": "History",
              "RecoverySource": "Structured record reconstruction",
              "Source": "V01.log", "Offset": 1, "Page": 1}

    class _Engine:
        structured_records = [carved]

    view_row = recovery_loader.carved_history_rows(_Engine())[0]
    canon = forensic_engine.canonical_record_row(carved, carved=True)
    assert forensic_engine._cell(canon.get("IsInPrivate")) == \
        forensic_engine._cell(view_row["IsInPrivate"]) == "No"
    # Bit 0x08 on a non-History record is not InPrivate (EDITED_CACHE_ENTRY
    # on Content) and a record with no Flags carries no answer: both say
    # the app's absence wording, exactly as the view does.
    from webcache.provenance import ABSENCE_NOT_DETERMINABLE
    content = dict(carved, Flags=0x08, ContainerType="Content")
    assert forensic_engine.canonical_record_row(
        content, carved=True).get("IsInPrivate") == ABSENCE_NOT_DETERMINABLE
    bare = {k: v for k, v in carved.items() if k != "Flags"}
    assert forensic_engine.canonical_record_row(
        bare, carved=True).get("IsInPrivate") == ABSENCE_NOT_DETERMINABLE



def test_the_dismiss_button_is_not_a_light_box_on_the_dark_bar():
    """Seen on screen: the native style drew the bar's dismiss button as a
    light grey box with a white cross -- the glyph unreadable, the box the
    brightest thing on the bar. Measured natively (see the probe)."""
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": "."}
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests._result_bar_probe"],
        capture_output=True, text=True, timeout=60, cwd=root, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout.strip()
    skip_unless_measurable(out)
    light = float(out.split("=")[1])
    assert light < 0.25, "%.0f%% of the dismiss button is light" % (light * 100)


# --- a carved record with no Flags makes no InPrivate claim --

def _flagless_carved_history(flags_key=False):
    record = {"Url": "https://example.test/f",
              "CleanUrl": "https://example.test/f",
              "ContainerType": "History", "ContainerId": 4,
              "RecoverySource": "Structured record reconstruction",
              "Source": "V01.log", "Offset": 64, "Page": 2,
              "Confidence": "high"}
    if flags_key:
        record["Flags"] = None
    return record


class _FlaglessEngine:
    def __init__(self, record):
        self.structured_records = [record]
        self.tombstones = []

    def all_artifacts(self):
        return []


@pytest.mark.parametrize("flags_key", [False, True],
                         ids=["no-Flags-key", "Flags-None"])
def test_a_carved_record_without_flags_reads_the_same_absence_everywhere(
        qtbot, tmp_path, flags_key):
    """"No" is an assertion the evidence does not make when the record
    carries no Flags. Grid, value picker, dialog, view CSV (view column
    AND canonical IsInPrivate) and the engine's recovered row all say the
    app's one absence wording for it."""
    from PySide6.QtCore import Qt
    from webcache.provenance import ABSENCE_NOT_DETERMINABLE as ABSENT
    from webcache.shell import detail_fields, domain_loader, recovery_loader
    from webcache.widgets.column_spec import display_text
    record = _flagless_carved_history(flags_key)
    engine = _FlaglessEngine(record)

    history_row = recovery_loader.carved_history_rows(engine)[0]
    deleted_row = [r for r in recovery_loader.deleted_records_rows(engine)
                   if r.get("_record") is record][0]
    assert history_row["IsInPrivate"] == ABSENT
    assert deleted_row["IsInPrivate"] == ABSENT

    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records([history_row])
    model = view.table.model()
    col = [c.key for c in model.columns].index("IsInPrivate")
    assert model.data(model.index(0, col), Qt.DisplayRole) == ABSENT
    labels = [display_text(v, model.columns[col]) or "(blank)"
              for v, _n in model.value_counts("IsInPrivate")]
    assert "No" not in labels and labels == [ABSENT]

    shown = [f for g in detail_fields.fields_for(history_row)
             for f in g.fields if f.key == "IsInPrivate"]
    assert shown and all(f.display_value != "No" for f in shown)

    path = str(tmp_path / "h.csv")
    export_formats.write_view_csv([history_row], list(model.columns), path, {})
    with open(path, encoding="utf-8-sig", newline="") as fh:
        header, line = list(csv.reader(fh))
    cell = dict(zip(header, line))
    assert cell["InPrivate"] == cell["IsInPrivate"] == ABSENT

    engine_row = forensic_engine.build_recovered_row(record)
    assert forensic_engine._cell(engine_row["IsInPrivate"]) == ABSENT
    assert domain_loader._inprivate(record) is None


# --- the constant-column chips speak the grid's words -------

def test_the_identical_chip_uses_the_columns_display_text(qtbot):
    rows = make_rows(12)
    for row in rows:
        row["IsInPrivate"] = False
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(rows)
    text = view._constant_chip.text()
    assert "InPrivate: No" in text, text
    assert "False" not in text and "True" not in text


def test_the_recovery_hidden_identical_chip_uses_display_text(qtbot,
                                                              monkeypatch):
    from webcache.views.recovery import RecoveryView
    from webcache.widgets.column_spec import Column
    view = RecoveryView()
    qtbot.addWidget(view)
    flag = Column("IsInPrivate", "InPrivate", 80, kind="flag")
    monkeypatch.setattr(view.table, "identical_columns",
                        lambda: [(flag, False)])
    monkeypatch.setattr(view.table, "auto_hidden_keys",
                        lambda: {"IsInPrivate"})
    view._identical_changed()
    text = view.identical_chip.text()
    assert "InPrivate: No" in text, text
    assert "False" not in text
