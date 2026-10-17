"""The export worker: off the GUI thread, snapshotted, and honest about
what a cancelled bundle left behind.

run() is called directly here rather than through start(). A QThread's
run() is an ordinary method; calling it on the test's own thread runs the
identical code with signals delivered synchronously, which is what lets
these assertions be about the WORK rather than about Qt's scheduler. The
one property that genuinely needs the real thread -- registration in
consent._RUNNING_WORKERS so the single shutdown sweep bounds this worker
kind too -- is checked through the runner.
"""
import inspect
import json
import os
import types

import pytest

from webcache.engine import forensic_engine
from webcache.shell import export_formats as F
from webcache.shell import consent
from webcache.shell.export_runner import ExportJob, ExportRunner, ExportWorker


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _entries():
    return [{"Url": "http://example.test/a", "ContainerType": "History",
             "AccessedTime": "2026-02-17T16:50:09Z", "AccessCount": 2,
             "EntryId": 1, "ContainerId": 3}]


def _job(key, path, **over):
    kwargs = dict(key=key, path=path, entries=_entries(), stats=None,
                  case_meta={"examiner": "E"}, db_info={"path": "x"})
    kwargs.update(over)
    return ExportJob(**kwargs)


def _run(job):
    worker = ExportWorker(job)
    out = {"written": [], "failed": [], "progress": []}
    worker.written.connect(lambda paths: out["written"].extend(paths))
    worker.failed.connect(out["failed"].append)
    worker.progress.connect(out["progress"].append)
    worker.run()
    return out


# --- the job is a snapshot ----------------------------------------------

def test_the_job_takes_its_own_copy_of_every_row_list():
    """A recovery merge landing mid-write must not change the set being
    written."""
    entries = _entries()
    job = _job("csv", "x.csv", entries=entries)
    entries.append({"Url": "http://added.later/"})
    assert len(job.entries) == 1


def test_nothing_in_the_job_is_a_widget():
    from PySide6.QtWidgets import QWidget
    job = _job("csv", "x.csv")
    for name in ExportJob.__slots__:
        assert not isinstance(getattr(job, name), QWidget), name


def test_the_job_uses_slots_so_a_typo_cannot_invent_a_field():
    job = _job("csv", "x.csv")
    with pytest.raises(AttributeError):
        job.entires = []


# --- the worker is tracked by the one shutdown sweep --------------------

def test_the_worker_registers_in_the_shared_running_set(app, tmp_path):
    runner = ExportRunner()
    job = _job("csv", str(tmp_path / "a.csv"))
    runner.start(job)
    assert runner._worker in consent._RUNNING_WORKERS, (
        "one shutdown sweep for every worker kind, not a second set")
    runner._worker.wait(20000)
    app.processEvents()


def test_the_worker_is_unparented_like_every_other_worker_here(tmp_path):
    worker = ExportWorker(_job("csv", str(tmp_path / "a.csv")))
    assert worker.parent() is None


# --- a single format ----------------------------------------------------

def test_a_flat_csv_is_written_and_reported(tmp_path):
    path = str(tmp_path / "all.csv")
    out = _run(_job("csv", path))
    assert out["failed"] == []
    assert os.path.exists(path)
    assert path in out["written"]


def test_a_format_that_does_not_write_its_own_sidecar_gets_one(tmp_path):
    """"A provenance sidecar on every export" has to be true, not nearly
    true."""
    path = str(tmp_path / "all.csv")
    out = _run(_job("csv", path))
    side = path + ".metadata.json"
    assert os.path.exists(side)
    assert side in out["written"]
    header = json.load(open(side, encoding="utf-8"))
    assert header["examiner"] == "E"
    assert header["rows_written"] == 1


def test_a_format_that_writes_its_own_sidecar_is_not_given_a_second(tmp_path):
    path = str(tmp_path / "fixes.csv")
    fix = {"Latitude": 51.5, "Longitude": -0.12, "LatitudeRaw": "51.5",
           "LongitudeRaw": "-0.12"}
    _run(_job("loc_csv", path, location_fixes=[fix]))
    side = json.load(open(path + ".metadata.json", encoding="utf-8"))
    # The engine's own sidecar carries rows_written; a second pass over the
    # top would replace it with one built the same way from the same inputs,
    # and two paths to one file is how they drift.
    assert side["rows_written"] == 1
    assert F.BY_KEY["loc_csv"].sidecar is False


# --- the sidecar states what the FILE holds, not just len(job.entries) --
#
# _run_single wrote every sidecar with
# rows_written=len(job.entries), regardless of what the writer it just
# called actually put in the file. Verified against the real exhibit with
# 217 carved records supplied: the case SQLite's own "records" table (live
# and carved, one table -- see export_sqlite's own docstring) held 827
# rows while metadata.json said "rows_written": 610.

def test_the_sqlite_sidecar_counts_the_records_table_not_only_live_entries(
        tmp_path):
    recovered = [{"Url": "http://carved.test/%d" % i, "RecoverySource": "log",
                  "Confidence": "medium"} for i in range(3)]
    path = str(tmp_path / "case.sqlite")
    out = _run(_job("sqlite", path, recovered=recovered))
    assert out["failed"] == []
    import sqlite3
    con = sqlite3.connect(path)
    actual_rows = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    con.close()
    assert actual_rows == len(_entries()) + len(recovered)
    side = json.load(open(path + ".metadata.json", encoding="utf-8"))
    assert side["rows_written"] == actual_rows, (
        "the sidecar must state what the file's own table holds, not "
        "only the live entry count")


# --- [8] sqlite_raw copies whole ESE TABLES, not job.entries --------------
#
# _rows_written's default branch (len(job.entries)) is wrong for sqlite_
# raw exactly the way it was wrong for "sqlite" above: this writer copies
# every ESE table byte for byte (export_sqlite_raw's own docstring -- "the
# database converted to SQLite AS IT IS STORED") and never reads
# job.entries at all. The count the FILE holds is the sum of every
# COPIED table's own row count.

def _live_node():
    """A `_node` shaped like dissect's real one: long enough to pass
    ese_records.is_record_node, which is what every fake row here needs
    to be enumerated by live_records() instead of silently dropped as a
    1-byte stub."""
    return types.SimpleNamespace(data=b"\x00" * 16, key=b"")


class _FakeRawRecord(dict):
    """A fake ESE record: dict-like .get(column_name), plus dissect's
    own `_node` attribute."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._node = _live_node()


class _FakeRawColumn:
    def __init__(self, name):
        self.name = name


class _FakeRawTable:
    def __init__(self, columns, rows):
        self.columns = [_FakeRawColumn(c) for c in columns]
        self._rows = [_FakeRawRecord(row) for row in rows]

    def records(self):
        return iter(self._rows)


class _FakeRawDb:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return self._tables[name]


class _FakeRawParser:
    """Just enough of WebCacheParser's surface for export_sqlite_raw:
    table_names plus a db.table(name) that answers .columns/.records()."""

    def __init__(self, tables):
        # tables: {table_name: (column_names, [row_dict, ...])}
        self.table_names = list(tables)
        self.db = _FakeRawDb(
            {name: _FakeRawTable(cols, rows)
             for name, (cols, rows) in tables.items()})
        self.db_path = "C:/case/exhibit.dat"
        self.source_hashes = {}


def test_the_sqlite_raw_sidecar_counts_rows_across_every_copied_table(
        tmp_path):
    """The job's own entries (see _entries() above -- exactly ONE) are
    unrelated to this format entirely: export_sqlite_raw never reads
    job.entries, it reads job.parser's own ESE tables. A parser with
    three tables holding 3 + 1 + 0 rows must report 4, not 1.
    """
    parser = _FakeRawParser({
        "TableA": (["Col1"], [{"Col1": 1}, {"Col1": 2}, {"Col1": 3}]),
        "TableB": (["Col1"], [{"Col1": 9}]),
        "TableC": (["Col1"], []),
    })
    path = str(tmp_path / "raw.sqlite")
    out = _run(_job("sqlite_raw", path, parser=parser))
    assert out["failed"] == []
    import sqlite3
    con = sqlite3.connect(path)
    actual_rows = sum(
        con.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
        for t in ("TableA", "TableB", "TableC"))
    con.close()
    assert actual_rows == 4
    side = json.load(open(path + ".metadata.json", encoding="utf-8"))
    assert side["rows_written"] == actual_rows, (
        "the sidecar must state the real total across every copied "
        "table, not len(job.entries) -- a number this format does not "
        "even read")


def test_a_kml_sidecar_counts_location_fixes_not_the_unrelated_entries(
        tmp_path):
    """loc_kml writes job.location_fixes, never job.entries -- the old
    code reported len(job.entries), which on a position-only job can be
    any number at all, including zero, unrelated to what the KML holds."""
    fixes = [{"Latitude": 1.0, "Longitude": 2.0},
             {"Latitude": 3.0, "Longitude": 4.0},
             {"Latitude": 5.0, "Longitude": 6.0}]
    path = str(tmp_path / "fixes.kml")
    out = _run(_job("loc_kml", path, entries=[], location_fixes=fixes))
    assert out["failed"] == []
    side = json.load(open(path + ".metadata.json", encoding="utf-8"))
    assert side["rows_written"] == len(fixes)


def test_a_csv_position_sidecar_is_not_overwritten_with_the_wrong_count(
        tmp_path):
    """export_location_csv already writes its own accurate sidecar
    (mirroring kape_csv/timesketch); the catalogue mis-declared loc_csv's
    sidecar as runner-owned, so _run_single wrote a SECOND, wrong one
    (len(job.entries)) straight over the correct one export_location_csv
    had just written."""
    fixes = [{"Latitude": 1.0, "Longitude": 2.0},
             {"Latitude": 3.0, "Longitude": 4.0}]
    path = str(tmp_path / "fixes.csv")
    out = _run(_job("loc_csv", path, entries=[], location_fixes=fixes))
    assert out["failed"] == []
    side = json.load(open(path + ".metadata.json", encoding="utf-8"))
    assert side["rows_written"] == len(fixes)


def test_a_failure_is_reported_and_never_raised_out_of_the_thread(tmp_path):
    out = _run(_job("csv", str(tmp_path / "nowhere" / "deep" / "a.csv")))
    assert out["failed"], "a failing write must reach the GUI, not the void"
    assert out["written"] == []


def test_an_unknown_key_fails_rather_than_writing_something_arbitrary(
        tmp_path):
    out = _run(_job("not_a_format", str(tmp_path / "a.csv")))
    assert out["failed"]


# --- the view CSV goes through the same one chokepoint ------------------

def test_a_view_csv_writes_its_own_provenance_sidecar(tmp_path):
    from webcache.widgets.column_spec import Column
    path = str(tmp_path / "history.csv")
    job = _job("view_csv", path,
               rows=[{"CleanUrl": "a", "_kind": "history"}],
               columns=[Column("CleanUrl", "Address", 100, kind="url")],
               scope={"view": "history", "view_label": "History",
                      "columns": ["Address"], "hidden_columns": [],
                      "rows_in_file": 1, "rows_in_view": 1,
                      "rows_in_record_set": 3, "is_subset": True,
                      "text_filter": "a", "conditions": {}, "values": {},
                      "chip_text": 'search "a"', "live_rows": 1,
                      "carved_rows": 0, "recovery_scan_run": False},
               stamp={"exported_utc": "2026-09-01T00:00:00Z", "evidence": {}})
    out = _run(job)
    assert out["failed"] == []
    assert os.path.exists(path + ".provenance.txt")
    assert path + ".provenance.txt" in out["written"]
    text = open(path + ".provenance.txt", encoding="utf-8").read()
    assert "THIS IS A FILTERED SUBSET" in text


# --- the bundle ---------------------------------------------------------

def test_the_bundle_member_list_matches_the_engines_own(tmp_path):
    """BUNDLE_MEMBERS exists so the worker can report honest arithmetic
    and stop between members. It must not drift from the filenames the
    engine's own bundle writer uses."""
    src = inspect.getsource(forensic_engine.ForensicEngine.export_full_bundle)
    for key, _label, filename in F.BUNDLE_MEMBERS:
        if key in F.SHELL_WRITTEN_BUNDLE_KEYS:
            continue        # built from the app's views; the engine has none
        assert filename in src, filename
    assert F.MANIFEST_NAME in src


def test_the_bundle_progress_line_counts_real_members(tmp_path):
    out = _run(_job("bundle", str(tmp_path / "bundle")))
    joined = " ".join(out["progress"])
    assert "of %d" % len(F.BUNDLE_MEMBERS) in joined, (
        "indeterminate bar, but the count in the TEXT is real arithmetic")


def test_a_completed_bundle_writes_a_manifest_that_says_so(tmp_path):
    out_dir = str(tmp_path / "bundle")
    out = _run(_job("bundle", out_dir))
    manifest = json.load(
        open(os.path.join(out_dir, F.MANIFEST_NAME), encoding="utf-8"))
    assert manifest["cancelled"] is False
    assert manifest["tool_version"]
    assert manifest["formats"], "a manifest with no formats explains nothing"
    assert os.path.join(out_dir, F.MANIFEST_NAME) in out["written"]


def test_a_cancelled_bundle_keeps_whole_files_and_names_its_own_gap(tmp_path):
    """Cancel semantics differ from the recovery scan, deliberately: a
    partial carve reported as a scan is a misrepresentation, but a folder
    that names its own incompleteness cannot be mistaken for a complete
    one."""
    out_dir = str(tmp_path / "bundle")
    job = _job("bundle", out_dir)
    worker = ExportWorker(job)
    written = []
    worker.written.connect(written.extend)
    # Cancel after the first member -- the identical thing the Cancel
    # button does, reached without needing a running event loop (see this
    # module's docstring).
    worker.progress.connect(lambda _m: worker.cancel())
    worker.run()
    manifest = json.load(
        open(os.path.join(out_dir, F.MANIFEST_NAME), encoding="utf-8"))
    assert manifest["cancelled"] is True
    statuses = {item["status"] for item in manifest["formats"]}
    assert "not attempted (cancelled)" in statuses
    for item in manifest["formats"]:
        if item["status"] == "written":
            full = os.path.join(out_dir, item["file"])
            assert os.path.exists(full)
            assert not os.path.exists(full + ".partial"), (
                "atomic_write guarantees each kept file is whole")


def test_a_skipped_format_appears_in_the_manifest_with_its_reason(tmp_path):
    """A PDF absent because reportlab is missing must appear WITH the
    reason; a manifest that silently omits it lets a reader believe the
    bundle was complete."""
    out_dir = str(tmp_path / "bundle")
    job = _job("bundle", out_dir, caps={"reportlab": False, "entries": True,
                                        "openpyxl": True, "parser": False,
                                        "stats": True})
    _run(job)
    manifest = json.load(
        open(os.path.join(out_dir, F.MANIFEST_NAME), encoding="utf-8"))
    pdf = [i for i in manifest["formats"] if i["file"].endswith(".pdf")]
    assert pdf, "the PDF must still be listed"
    assert pdf[0]["status"] == "skipped"
    assert "reportlab" in pdf[0]["reason"]


# --- "a scan ran and found nothing" vs "no scan ran" ----------

def test_recovered_csv_skip_reason_says_the_scan_ran_and_found_nothing(
        tmp_path):
    """The skip reason for recovered_csv was
    a hardcoded literal ("No recovery scan has run for this exhibit...")
    gated only on bool(job.recovered) -- so it appeared even when a scan
    HAD run and genuinely found nothing. Verified with
    scope["recovery_scan_run"]=True and zero carved records: the
    manifest claimed no scan had run when one had."""
    out_dir = str(tmp_path / "bundle")
    _run(_job("bundle", out_dir, recovered=[],
              scope={"recovery_scan_run": True}))
    manifest = json.load(
        open(os.path.join(out_dir, F.MANIFEST_NAME), encoding="utf-8"))
    item = [i for i in manifest["formats"]
            if i["file"] == "06_recovered_artifacts.csv"][0]
    assert item["status"] == "skipped"
    assert "no recovery scan has run" not in item["reason"].lower(), (
        "a scan DID run for this exhibit -- the reason must not claim "
        "otherwise")
    assert "ran" in item["reason"].lower()
    assert "found" in item["reason"].lower()


def test_recovered_csv_skip_reason_says_no_scan_ran_at_all(tmp_path):
    out_dir = str(tmp_path / "bundle")
    _run(_job("bundle", out_dir, recovered=[],
              scope={"recovery_scan_run": False}))
    manifest = json.load(
        open(os.path.join(out_dir, F.MANIFEST_NAME), encoding="utf-8"))
    item = [i for i in manifest["formats"]
            if i["file"] == "06_recovered_artifacts.csv"][0]
    assert item["status"] == "skipped"
    assert "no recovery scan has run" in item["reason"].lower()


def test_the_manifest_records_whether_a_recovery_scan_had_run(tmp_path):
    out_dir = str(tmp_path / "bundle")
    _run(_job("bundle", out_dir, scope={"recovery_scan_run": False}))
    manifest = json.load(
        open(os.path.join(out_dir, F.MANIFEST_NAME), encoding="utf-8"))
    assert manifest["scope"]["recovery_scan_run"] is False


# --- the runner ---------------------------------------------------------

def test_the_runner_relays_and_owns_no_widget(app, tmp_path):
    from PySide6.QtWidgets import QWidget
    runner = ExportRunner()
    assert not isinstance(runner, QWidget)
    seen = []
    runner.written.connect(seen.append)
    runner.start(_job("csv", str(tmp_path / "a.csv")))
    runner._worker.wait(20000)
    app.processEvents()
    assert seen, "the runner must relay the worker's own written signal"


def test_bundle_members_that_exclude_recovered_records_say_so(tmp_path):
    """_writer_for maps "csv" and "html" to
    engine functions that take no recovered argument at all, so those two
    bundle members silently exclude carved records while every other
    member includes them. Verified on the real exhibit with 217 carved
    records: 01_all_records_full.csv (csv) held 610 data rows and
    02_timeline_explorer.csv (kape_csv) held 827 -- two files in the same
    bundle both claiming to be the record set. Merging them would mean
    changing export_csv and the old HTML writer themselves (engine,
    carried over); instead each member now states its own scope
    explicitly in the manifest so the disagreement is legible rather
    than silent. (The CSV and the offline report both carry carved
    rows.)
    """
    out_dir = str(tmp_path / "bundle")
    recovered = [{"Url": "http://carved.test/%d" % i, "RecoverySource": "log",
                  "Confidence": "medium"} for i in range(3)]
    _run(_job("bundle", out_dir, recovered=recovered))
    manifest = json.load(
        open(os.path.join(out_dir, F.MANIFEST_NAME), encoding="utf-8"))
    by_file = {item["file"]: item for item in manifest["formats"]}

    # export_csv writes carved rows too, so file 01 INCLUDES them and
    # the manifest must say so.
    csv_item = by_file["01_all_records_full.csv"]
    assert csv_item["includes_recovered_records"] is True
    assert "carved_records_excluded" not in csv_item

    # The offline report carries every view's rows, carved ones included.
    # This engine-built job holds no snapshot, so the member is skipped
    # WITH its reason -- and still states its scope.
    html_item = by_file["04_offline_report.html"]
    assert html_item["includes_recovered_records"] is True
    assert "carved_records_excluded" not in html_item
    assert html_item["status"] == "skipped"

    # Every other member DOES include recovered records -- and must say
    # so too, or "explicit scope" is only implemented for the two that
    # exclude it.
    json_item = by_file["03_complete_data.json"]
    assert json_item["includes_recovered_records"] is True
    assert "carved_records_excluded" not in json_item
    sqlite_item = by_file["07_case.sqlite"]
    assert sqlite_item["includes_recovered_records"] is True


def _csv_data_rows(path):
    import csv as _csv
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(_csv.reader(fh))
    return len(rows) - 1          # minus the header


def test_manifest_and_sidecar_agree_with_the_csv_files_own_row_count(tmp_path):
    """The chain-of-custody documents must describe the
    file they sit beside. The count is taken from the CSV itself, never
    from a constant: 1 live entry + 3 carved rows is 4 data rows, so the
    manifest must not call carved rows excluded and the single-format
    sidecar must not say rows_written 1."""
    recovered = [{"Url": "http://carved.test/%d" % i, "RecoverySource": "log",
                  "Confidence": "medium"} for i in range(3)]

    out_dir = str(tmp_path / "bundle")
    _run(_job("bundle", out_dir, recovered=recovered))
    in_file = _csv_data_rows(os.path.join(out_dir, "01_all_records_full.csv"))
    manifest = json.load(
        open(os.path.join(out_dir, F.MANIFEST_NAME), encoding="utf-8"))
    item = [i for i in manifest["formats"]
            if i["file"] == "01_all_records_full.csv"][0]
    claimed = manifest["scope"]["live_entries"] + (
        manifest["scope"]["carved_records"]
        if item["includes_recovered_records"] else 0)
    assert claimed == in_file, (claimed, in_file)
    assert "carved_records_excluded" not in item

    single = str(tmp_path / "one.csv")
    _run(_job("csv", single, recovered=recovered))
    side = json.load(open(single + ".metadata.json", encoding="utf-8"))
    rows = side.get("rows_written", side.get("report", {}).get("rows_written"))
    assert rows == _csv_data_rows(single), (rows, _csv_data_rows(single))


def test_engine_full_bundle_csv_holds_the_carved_rows_too(tmp_path):
    """The engine's own export_full_bundle and the GUI
    bundle must agree about what file 01 is."""
    engine = forensic_engine.ForensicEngine()
    engine.load_entries(_entries())
    recovered = [{"Url": "http://carved.test/%d" % i, "RecoverySource": "log",
                  "Confidence": "medium"} for i in range(3)]
    out_dir = str(tmp_path / "eng")
    engine.export_full_bundle(_entries(), out_dir, {"examiner": "E"},
                              {"path": "x"}, recovered=recovered)
    assert _csv_data_rows(
        os.path.join(out_dir, "01_all_records_full.csv")) == 1 + len(recovered)


def test_the_bundle_reports_every_file_on_disk_including_companions(tmp_path):
    """`written` promises "every path on disk, sidecars included".

    Two members write a .metadata.json of their own through the engine
    (kape_csv, timesketch). Returning only the members this loop wrote
    made the status line say "10 file(s)" over a folder holding 12 --
    verified on a real exhibit. A count on screen that disagrees with the
    folder is the same defect as a row count that disagrees with a file.
    """
    out_dir = str(tmp_path / "bundle")
    out = _run(_job("bundle", out_dir))
    on_disk = {os.path.join(out_dir, n) for n in os.listdir(out_dir)}
    assert set(out["written"]) == on_disk, (
        "reported %d, on disk %d" % (len(out["written"]), len(on_disk)))


# --- the places a location export writes ---------------------------------

def test_a_job_takes_cluster_shaped_places_as_a_list_of_dicts():
    """export_location_pdf iterates `places` and calls p.get("Latitude") on
    each one. ExportJob stored them with dict(places), which raises
    ValueError on a list of dicts before a single byte is written -- so
    the PDF card could never have run even once the fixes existed."""
    places = [{"Latitude": 51.5074, "Longitude": -0.1278, "Fixes": 2,
               "Accuracy": "±12–140 m", "FirstSeen": None,
               "LastSeen": None},
              {"Latitude": 48.8566, "Longitude": 2.3522, "Fixes": 1,
               "Accuracy": "(not supplied)", "FirstSeen": None,
               "LastSeen": None}]
    job = ExportJob(key="loc_csv", path="x.csv", places=places)
    assert isinstance(job.places, list)
    assert [p["Latitude"] for p in job.places] == [51.5074, 48.8566]


def test_a_job_with_no_places_holds_an_empty_list_not_an_empty_dict():
    """The engine writes the Distinct places table only `if places:`, and
    both are falsy -- but iterating a dict yields its KEYS, so a later
    truthy dict would silently feed strings where dicts belong."""
    job = ExportJob(key="loc_csv", path="x.csv")
    assert job.places == []


# --- the manifest is read by machines, too --------------------------------

def test_case_fields_stored_as_json_reach_the_manifest_as_structure(tmp_path):
    """The case file keeps its evidence-opened log as JSON TEXT. Copied
    straight into the manifest it became a string holding escaped JSON --
    a chain-of-custody record every reader had to parse twice. The
    examiner's own free text is never reinterpreted, even when it
    happens to look like JSON."""
    log = [{"opened_utc": "2026-01-01T00:00:00Z",
            "files": [{"path": "C:/x/WebCacheV01.dat", "sha256": "ab",
                       "bytes": 1}]}]
    out_dir = str(tmp_path / "bundle")
    _run(_job("bundle", out_dir,
              case_meta={"examiner": "E", "notes": "[1, 2]",
                         "evidence_opened": json.dumps(log)}))
    manifest = json.load(
        open(os.path.join(out_dir, F.MANIFEST_NAME), encoding="utf-8"))
    assert manifest["case"]["evidence_opened"] == log
    assert manifest["case"]["notes"] == "[1, 2]"


def test_each_csv_states_how_many_values_excel_would_run_as_formulas(
        tmp_path):
    """Stored URLs that begin with = or @ exist in real exhibits (seen in
    a certificate-revocation container). They are written unaltered --
    changing evidence to suit a spreadsheet is tampering -- so the
    manifest must say how many there are, as the view CSV's sidecar
    already does. Silence let a reader open the file in Excel unwarned."""
    entries = _entries() + [dict(_entries()[0], Url="=http://a.test/x",
                                 CleanUrl="=http://a.test/x", EntryId=99)]
    out_dir = str(tmp_path / "bundle")
    _run(_job("bundle", out_dir, entries=entries))
    manifest = json.load(
        open(os.path.join(out_dir, F.MANIFEST_NAME), encoding="utf-8"))
    full = [i for i in manifest["formats"]
            if i["file"] == "01_all_records_full.csv"][0]
    assert full["values_starting_with_formula_character"] >= 1
    assert "formula" in manifest["caution"].lower()
    assert "not altered" in manifest["caution"].lower()


# --- a sectioned file states its recovered records too --------------------
#
# xlsx and json keep live entries in their main table and recovered records
# in a section of their own. The sidecar counted only the live entries, so
# a reader of the provenance concluded the recovered records were absent.

@pytest.mark.parametrize("key,ext,section", [
    ("xlsx", "xlsx", "Recovered sheet"),
    ("json", "json", "recovered_artifacts"),
])
def test_a_sectioned_export_states_the_recovered_records_it_holds(
        tmp_path, key, ext, section):
    recovered = [{"Url": "http://carved.test/%d" % i, "RecoverySource": "log",
                  "Confidence": "medium"} for i in range(3)]
    path = str(tmp_path / ("all." + ext))
    out = _run(_job(key, path, recovered=recovered))
    assert out["failed"] == []
    side = json.load(open(path + ".metadata.json", encoding="utf-8"))
    assert side["rows_written"] == len(_entries())
    assert side["recovered_rows_written"] == 3
    assert side["recovered_rows_section"] == section
