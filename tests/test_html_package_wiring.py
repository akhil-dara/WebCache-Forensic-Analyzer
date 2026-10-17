"""The application writes the offline report: the card, the worker, the bundle, the build."""
import hashlib
import json
import os
import re

from PySide6.QtWidgets import QFileDialog

from webcache.engine import forensic_engine
from webcache.shell import export_formats as F
from webcache.shell.export_runner import ExportJob, ExportWorker

from tests.fixtures import make_rows
from tests.test_export_wiring import (_FakeParser, _open_exhibit,  # noqa: F401
                                      _SyncExportRunner, exhibit, outbox, win)

ENTRIES = [{"Url": "http://example.test/a", "ContainerType": "History",
            "EntryId": 1, "ContainerId": 3}]


def _island(path):
    from webcache.shell.html_package import unpack_island
    text = open(path, encoding="utf-8").read()
    return unpack_island(json.loads(re.search(
        r'id="wc-data">(.*?)</script>', text, re.S).group(1)))


def test_the_html_card_is_the_offline_report():
    fmt = F.BY_KEY["html"]
    assert fmt.title == "Offline HTML report"
    assert fmt.requires == ("entries",)
    assert fmt.default_basename == "webcache_offline_report"
    assert ("html", "Offline HTML report",
            "04_offline_report.html") in F.BUNDLE_MEMBERS
    assert F.BUNDLE_KEYS_WITHOUT_RECOVERED == frozenset()
    assert F.SHELL_WRITTEN_BUNDLE_KEYS == frozenset({"html"})


def test_the_old_capped_writer_is_gone():
    assert not hasattr(forensic_engine.ForensicEngine, "export_html_report")
    assert not hasattr(forensic_engine, "HTML_REPORT_ROW_CAP")
    assert not hasattr(forensic_engine.ForensicEngine, "_td")
    # The location PDF still escapes with it.
    assert hasattr(forensic_engine.ForensicEngine, "_html_escape")


def test_a_job_without_a_snapshot_fails_and_says_why(tmp_path):
    worker = ExportWorker(ExportJob(key="html", path=str(tmp_path / "r.html"),
                                    entries=ENTRIES))
    failed = []
    worker.failed.connect(failed.append)
    worker.run()
    assert failed and "snapshot" in failed[0]


def test_the_card_writes_the_report_its_sidecars_and_every_view(
        win, monkeypatch, exhibit, outbox):
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"), rows=make_rows(4),
                  parser=_FakeParser(ENTRIES))
    out = str(outbox / "report.html")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._ensure_view_built("export").cards["html"].button.click()
    job = _SyncExportRunner.jobs[-1]
    assert job.key == "html" and job.package is not None
    for path in (out, out + ".sha256", out + ".metadata.json"):
        assert os.path.exists(path), path
    digest = hashlib.sha256(open(out, "rb").read()).hexdigest()
    assert open(out + ".sha256", encoding="utf-8").read().split()[0] == digest
    island = _island(out)
    keys = [v["key"] for v in island["views"]]
    assert keys[:2] == ["history", "downloads"] and "recovery" in keys
    assert len(island["views"][0]["segments"][0]["rows"]) == 4


def test_the_bundle_writes_it_with_recovered_records_in_scope(
        win, monkeypatch, exhibit, outbox):
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"), rows=make_rows(4),
                  parser=_FakeParser(ENTRIES))
    target = str(outbox / "bundle")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: target))
    win._ensure_view_built("export").bundle_button.click()
    manifest = json.load(open(os.path.join(target, F.MANIFEST_NAME),
                              encoding="utf-8"))
    item = [i for i in manifest["formats"]
            if i["file"] == "04_offline_report.html"][0]
    assert item["status"] == "written"
    assert item["includes_recovered_records"] is True
    assert "carved_records_excluded" not in item
    assert "04_offline_report.html.sha256" in {
        c["name"] for c in manifest["companion_files"]}


# --- ------------------------------------------------------------

def _counted_snapshot():
    """Every unit the page's "Records in this report" table counts: live
    and carved rows, a deleted-record stub, an aggregate whose members are
    records of their own, and a raw table."""
    import types

    from tests import _package_fixtures as fx
    from webcache.shell import recovery_loader
    from webcache.shell.html_package import PackageColumn, PackageView
    from webcache.shell.record_kinds import K_PERIOD, K_TABLE_ROW

    stub = {"Table": "Container_3", "KeyColumns": ("UrlHash", "EntryId"),
            "KeyValues": (111, 7), "Source": "WebCacheV01.dat",
            "Offset": 8192, "Page": 2, "ContainerType": "History"}
    stub_rows = [r for r in recovery_loader.deleted_records_rows(
        types.SimpleNamespace(structured_records=[], tombstones=[stub],
                              all_artifacts=lambda: []))
        if r["_kind"] == "tombstone"]
    history = [fx.history_row(i) for i in (1, 2, 3)] + [
        fx.history_row(i, carved=True) for i in (4, 5)]
    period = {"Period": "2026-02-17", "Records": 2, "_kind": K_PERIOD,
              "_members": [fx.entry(21), fx.entry(22)]}
    # The shape package_snapshot's raw-table factory gives a row.
    raw = [{"Id": i, "_kind": K_TABLE_ROW, "_record": None, "_row": i}
           for i in range(3)]
    views = [
        fx.history_view([fx.segment(rows=history)]),
        PackageView("recovery", "Recovery", "RECOVERY", "", [fx.segment(
            "deleted", "Deleted records", rows=stub_rows)]),
        PackageView("timeline", "Timeline", "ANALYSIS", "", [fx.segment(
            "day_utc", "By day", rows=[period],
            columns=[PackageColumn("Period", "Period"),
                     PackageColumn("Records", "Records", kind="num")])]),
        PackageView("raw", "Raw tables", "DATABASE", "", [fx.segment(
            "Containers", "Containers", rows=raw,
            columns=[PackageColumn("Id", "Id", kind="num")])],
            picker="list"),
    ]
    return fx.snapshot(views=views, member_columns=[
        PackageColumn("CleanUrl", "Address", kind="url")])


def test_the_reports_sidecar_counts_what_the_page_holds(tmp_path):
    """A sidecar must never understate what its file contains. The page
    holds every view's rows -- not len(entries) -- so the sidecar states
    each count the page's own "Records in this report" table states, by
    its unit, read from the island the page was written from."""
    from webcache.shell.html_package import build_island
    snap = _counted_snapshot()
    out = str(tmp_path / "r.html")
    worker = ExportWorker(ExportJob(key="html", path=out, entries=ENTRIES,
                                    package=snap))
    written = []
    worker.written.connect(written.append)
    worker.run()
    assert written
    side = json.load(open(out + ".metadata.json", encoding="utf-8"))
    # 3 live + 2 carved history rows, 1 stub, 1 period, 3 raw table rows.
    assert side["rows_written"] == 3 + 2 + 1 + 1 + 3
    contents = side.get("page_contents") or {}

    island = build_island(snap, "2026-10-01T09:00:00Z")
    segments = [(v["label"], s) for v in island["views"]
                for s in v["segments"]]
    assert contents["rows_per_segment"] == [
        {"view": view, "segment": s["label"], "rows": len(s["rows"]),
         "live records": 3 if s["key"] == "history" else 0,
         # A stub's Origin cell is the carved one: the page's table
         # counts it as a carved record, and so does the sidecar.
         "recovered records (carves and stubs)": {"history": 2, "deleted": 1}.get(s["key"], 0),
         "not single records (aggregates, raw rows)":
             {"history": 0, "deleted": 0, "day_utc": 1,
              "Containers": 3}[s["key"]]}
        for view, s in segments]
    assert contents["rows_total"] == 3 + 2 + 1 + 1 + 3
    assert side["rows_written"] == contents["rows_total"]
    assert side["rows_written_unit"] == "rows across every view's segments"
    assert contents["distinct_records"] == {
        "live records": 3 + 2,          # 3 history rows, 2 members
        "carved records": 2,
        "deleted-record stubs": 1,
        "other records (cookies, HSTS pins, certificates, containers)": 0,
        "total": 3 + 2 + 2 + 1}
    assert contents["raw_table_rows"] == 3
    assert contents["aggregate_members"] == 2
    assert len(island["records"]) == contents["distinct_records"]["total"]


def test_the_done_bar_names_both_files_written_beside_the_report(
        win, monkeypatch, exhibit, outbox):
    """Two companions are written beside the report: the provenance
    sidecar and the SHA-256 file. The line names each, never "sidecar"
    in the singular."""
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"), rows=make_rows(2),
                  parser=_FakeParser(ENTRIES))
    out = str(outbox / "report.html")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    win._ensure_view_built("export").cards["html"].button.click()
    status = win.status_message()
    assert "report.html.metadata.json" in status, status
    assert "report.html.sha256" in status, status
    assert "sidecar beside it" not in status, status


def test_a_failed_snapshot_is_reported_on_the_card_not_lost(
        win, monkeypatch, exhibit, outbox):
    """An exception while preparing the report's snapshot
    used to escape the click slot -- printed to stderr, nothing on screen.
    The card must say the report could not be prepared, and nothing is
    written."""
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"), rows=make_rows(4),
                  parser=_FakeParser(ENTRIES))
    out = str(outbox / "report.html")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))

    def boom():
        raise RuntimeError("synthetic view failure")
    monkeypatch.setattr(win, "_package_snapshot", boom)
    failures = []
    view = win._ensure_view_built("export")
    monkeypatch.setattr(view, "report_failed",
                        lambda key, message: failures.append((key, message)))
    before = len(_SyncExportRunner.jobs)
    view.cards["html"].button.click()
    assert failures and failures[-1][0] == "html"
    assert "could not be prepared" in failures[-1][1]
    assert "synthetic view failure" in failures[-1][1]
    assert len(_SyncExportRunner.jobs) == before
    assert not os.path.exists(out)
