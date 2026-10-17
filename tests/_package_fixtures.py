"""Synthetic offline-report snapshots. No evidence: every value is made up
here (example.test, alice). Not a test module -- imported by them."""
import datetime

from webcache import provenance
from webcache.shell.record_kinds import K_CARVED_STRUCT, K_HISTORY
from webcache.widgets.column_spec import Column

UTC = datetime.timezone.utc
GENERATED = "2026-10-01T09:00:00Z"


def entry(i, **extra):
    record = {
        "EntryId": i, "ContainerId": 3, "ContainerName": "History",
        "ContainerType": "History",
        "Url": "Visited: alice@https://example.test/page/%d" % i,
        "CleanUrl": "https://example.test/page/%d" % i,
        "Domain": "example.test",
        "AccessedTime_raw": 133500000000000000 + i * 10_000_000,
        "AccessCount": i, "Flags": 0,
    }
    record.update(extra)
    return record


def history_columns():
    from webcache.shell.html_package import PackageColumn
    return [PackageColumn.from_column(c) for c in (
        Column("CleanUrl", "Address", 460, kind="url", field="CleanUrl"),
        Column("AccessedUtc", "Last visit (UTC)", 165, kind="time",
               field="AccessedUtc"),
        Column("VisitCount", "Visits", 70, kind="num", field="VisitCount"),
        Column("IsInPrivate", "InPrivate", 85, kind="flag"),
        Column("Origin", "Origin detail", 170, kind="text", field="Origin"),
        Column("Offset", "Offset", 100, kind="offset", field="Offset",
               optional=True),
    )]


def history_row(i, carved=False, **extra):
    more = ({"RecoverySource": "unallocated", "Source": "WebCacheV01.dat",
             "Offset": 0x3B0523 + i, "Page": 12, "Confidence": "high"}
            if carved else {})
    record = entry(i, **more)
    row = {
        "CleanUrl": record["CleanUrl"],
        "AccessedUtc": datetime.datetime(2026, 2, 17, 16, 50, i % 60,
                                         tzinfo=UTC),
        "VisitCount": i, "IsInPrivate": i % 2 == 0,
        "Origin": provenance.CARVED_ORIGIN if carved else provenance.LIVE_ORIGIN,
        "Offset": record.get("Offset"),
        "Source": record.get("Source"),
        "_kind": K_CARVED_STRUCT if carved else K_HISTORY,
        "_record": record,
    }
    row.update(extra)
    return row


def segment(key="history", label="History", rows=None, columns=None, **kw):
    from webcache.shell.html_package import PackageSegment
    return PackageSegment(
        key, label, columns or history_columns(),
        rows if rows is not None else [history_row(i) for i in range(1, 6)],
        **kw)


def history_view(segments=None):
    from webcache.shell.html_package import PackageView
    return PackageView(
        "history", "History", "USER ACTIVITY",
        "A record of a page being loaded, not proof a person read it.",
        segments or [segment()])


def snapshot(views=None, **kw):
    from webcache.shell.html_package import PackageSnapshot
    meta = {
        "tool": "WebCache Forensic Analyzer",
        "tool_version": provenance.TOOL_VERSION,
        "evidence": [{"path": "C:/case/WebCacheV01.dat",
                      "sha256": "ab" * 32, "bytes": 1024}],
        "case": {"examiner": "alice"},
        "recovery_scan_run": True,
        "zone": {"offset_seconds": 19800, "label": "UTC+05:30"},
    }
    args = dict(
        views=views or [history_view()], meta=meta,
        summary=[("File", "WebCacheV01.dat"), ("Size", 1024)],
        integrity={"hashes": [["WebCacheV01.dat", "Database", "ab" * 32]],
                   "source": [["Database state", "Dirty shutdown", ""]],
                   "log": [["Parsed 5 records", False]]},
        scope=[("Scope", "What the cache stored.")],
        basis=[("OBS", "OBSERVED", "Read directly.")],
        member_columns=[])
    args.update(kw)
    return PackageSnapshot(**args)


def write(tmp_path, snap=None, name="report.html"):
    from webcache.shell.html_package import write_package
    path = str(tmp_path / name)
    write_package(snap or snapshot(), path, generated_utc=GENERATED)
    return path
