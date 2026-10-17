"""The same record reads the same way in every view and every export.

One structural test walks every destination the main window's own nav list
declares -- never a list someone keeps up to date -- and every record set
each one can show, and asserts the three things the validation spec makes
promises about:

  1. no evidence column is elided (wrap ON, the default; wrap OFF elides
     by design, and that is the examiner's own toggle);
  2. every view's export carries the full field set for ITS records, and a
     view that cannot carry one says why;
  3. the origin label renders on every row, and no two headings in one
     grid are alike, the vertical header's "Origin" included.

The rows come from the app's own loaders, run over one synthetic exhibit
(a live set, a carved set, a cookie/HSTS/certificate/container set). Hand
built rows would pass for a view whose loader had quietly stopped
attaching `_record`, and that is exactly the failure the export check
exists to see: the file still writes, every column is there, and all of
it is derived.

Related, and not repeated here:
  tests/test_heading_fit_native.py  no heading is clipped (native probe)
  tests/test_no_elision.py          elision survives only on chrome (source)
"""
import csv
import datetime

import pytest
from PySide6.QtCore import Qt

from webcache.provenance import aggregate_members, aggregate_origin_of
from webcache.engine.forensic_engine import ENTRY_FIELDS
from webcache.shell import (evidence_loader, headers_loader, iocs_loader,
                            location_loader, recovery_loader, record_kinds,
                            search_loader, timeline_loader)
from webcache.shell import export_formats as F
from webcache.shell.domain_loader import domain_rows
from webcache.shell.indicator_loader import indicator_rows
from webcache.shell.main_window import NAV_SECTIONS, MainWindow
from webcache.widgets.bar_delegate import ShareBarDelegate
from webcache.widgets.record_model import (ORIGIN_HEADING, ORIGIN_LABEL_CARVED,
                                           ORIGIN_LABEL_LIVE)
from webcache.widgets.records_table import RecordsTable, WrappingDelegate

#: The main window's destinations. Asserted, not derived from what the test
#: happens to walk: a seventeenth view fails here until someone decides
#: which of the sets below its tables belong to.
NAV_COUNT = 17

#: Destinations with no RecordsTable at all, each with the reason.
NO_GRID = {
    "dashboard": "headline figures only",
    "browser": "raw ESE tables in a QTableWidget; walked on its own below",
    "integrity": "hashes and the parse log, not a record set",
    "export": "the Export & Report page is not a record set",
}

# How each record set's export is expected to be filled. "entry": the full
# ENTRY_FIELDS set. "own": the record kind's own complete key set (cookies,
# HSTS pins, certificates, containers are not URL-cache entries). "none":
# no per-record fields, with the sidecar saying why -- "aggregates" for a
# population summary, "not single parsed records" for a row that is
# neither.
ENTRY, OWN, AGGREGATE, NOT_A_RECORD = "entry", "own", "aggregate", "not_a_record"

EXPECTED = {
    ("history", "history"): ENTRY,
    ("downloads", "file_access"): ENTRY,
    ("downloads", "downloads"): ENTRY,
    ("search", "hits"): NOT_A_RECORD,
    ("search", "hit_fields"): NOT_A_RECORD,
    ("timeline", "minute"): AGGREGATE,
    ("timeline", "hour"): AGGREGATE,
    ("timeline", "day"): AGGREGATE,
    ("timeline", "month"): AGGREGATE,
    ("timeline", "period_records"): ENTRY,
    ("domains", "domains"): AGGREGATE,
    ("domains", "member_records"): ENTRY,
    ("location", "fixes"): ENTRY,
    ("location", "places"): AGGREGATE,
    ("location", "records"): ENTRY,
    ("indicators", "indicators"): AGGREGATE,
    ("iocs", "ioc_hits"): ENTRY,
    ("iocs", "entryid_gaps"): AGGREGATE,
    ("iocs", "time_voids"): NOT_A_RECORD,
    ("iocs", "beaconing"): AGGREGATE,
    ("iocs", "deceptive_hostnames"): AGGREGATE,
    ("iocs", "redirect_chains"): NOT_A_RECORD,
    ("cookies", "cookies"): OWN,
    ("cookies", "hsts"): OWN,
    ("cookies", "certs"): OWN,
    ("headers", "headers"): ENTRY,
    ("containers", "containers"): OWN,
    ("recovery", "deleted"): ENTRY,
    ("tagged", "tagged"): ENTRY,
}

#: The canonical fields whose exact stored value must reach the file for an
#: ENTRY record -- raw FILETIMEs (above 2**53, where a float rounds them),
#: the ids, and the carve provenance.
PROBES = ("AccessedTime_raw", "ModifiedTime_raw", "EntryId", "UrlHash",
          "Offset", "Page", "Confidence")

RAW = 133544180420000001
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


def _ft(*args):
    dt = datetime.datetime(*args, tzinfo=datetime.timezone.utc)
    return int((dt - _EPOCH).total_seconds() * 10_000_000)


# --- one synthetic exhibit, pushed through the app's own loaders ----------

def _live(entry_id, url, **extra):
    row = {"EntryId": entry_id, "ContainerId": 4, "ContainerName": "Container_4",
           "ContainerType": "History", "Url": url, "CleanUrl": url,
           "UrlHash": RAW + entry_id, "AccessedTime_raw": RAW + entry_id,
           "ModifiedTime_raw": _ft(2024, 3, 11, 9, 14, 2) + entry_id,
           "Flags": 0}
    row.update(extra)
    return row


def _live_entries():
    entries = [
        _live(1, "https://example.test/geo?lat=48.8566&lon=2.3522"
                 "&mac=00:1A:2B:3C:4D:5E&id=123e4567-e89b-12d3-a456-426614174000"),
        _live(2, "http://abcdefghij.onion/x"),
        _live(3, "http://xn--pple-43d.example/login"),
        # EntryIds 4-8 are absent from container 4: an EntryId gap.
        _live(9, "file:///C:/synthetic/report.txt", IsLocalFile=True),
        _live(10, "https://example.test/redirect-a",
              RedirectUrl="https://example.test/redirect-b"),
        _live(11, "https://example.test/redirect-b"),
        _live(12, "https://example.test/answer",
              ResponseHeaders={"_status_line": "HTTP/1.1 200 OK",
                               "content-type": "text/html"}),
        _live(20, "https://downloads.example.test/tool.zip",
              ContainerId=9, ContainerType="Downloads"),
    ]
    # Regular visits to one host, a minute apart: beaconing. Together with
    # one visit months later they also make a silence for the time voids.
    for i in range(12):
        entries.append(_live(
            100 + i, "https://beacon.example.test/poll", ContainerId=7,
            ContainerName="Container_7",
            ModifiedTime_raw=_ft(2024, 1, 5, 8, i, 0)))
    entries.append(_live(200, "https://example.test/late", ContainerId=7,
                         ContainerName="Container_7",
                         ModifiedTime_raw=_ft(2024, 6, 20, 8, 0, 0)))
    return entries


def _carved_struct(**extra):
    row = {"Url": "https://example.test/geo?lat=51.5074&lon=-0.1278",
           "CleanUrl": "https://example.test/geo?lat=51.5074&lon=-0.1278",
           "ContainerId": 4, "ContainerType": "History", "Flags": 0,
           "ModifiedTime_raw": _ft(2024, 3, 12, 9, 0, 0), "Source": "V01.log",
           "Offset": 4096, "Page": 3,
           "RecoverySource": "Structured record reconstruction",
           "Confidence": "high",
           "ResponseHeaders": {"_status_line": "HTTP/1.1 200 OK",
                               "server": "synthetic"}}
    row.update(extra)
    return row


def _carved_string():
    return {"Url": "http://carved.example.test/only", "CleanUrl":
            "http://carved.example.test/only", "Source": "V01.log",
            "Offset": 777, "Page": None,
            "RecoverySource": "Transaction log", "Confidence": "medium",
            "NearbyFiletime": datetime.datetime(
                2024, 3, 12, tzinfo=datetime.timezone.utc)}


class _Parser:
    def __init__(self):
        self.all_entries = _live_entries()
        self.cookie_entries = [{
            "Domain": "example.test", "RDomain": "test.example",
            "Name": "sid", "Value": "abc", "Path": "/",
            "Expires_raw": RAW + 1, "LastModified_raw": RAW + 2}]
        self.hsts_entries = [{
            "Domain": "example.test", "IncludeSubdomains": False,
            "Expires": "2026-01-01 00:00:00 UTC", "LastTimeUsed": "",
            "LastTimeUsed_raw": RAW + 3}]
        self.cert_entries = [{
            "HostPort": "example.test:443", "IsCertificate": True,
            "Thumbprint": "AB" * 20, "BlobSize": 4, "Blob_raw": b"\x30\x82\x01\x00",
            "ModifiedTime_raw": RAW + 4}]
        self.containers_meta = [{
            "ContainerId": 4, "Name": "History", "HasTable": True,
            "RecordCount": 12, "Size": 2048, "PartitionId": "p0",
            "Directory": "C:/synthetic/History", "LastAccessTime_raw": RAW + 5,
            "LastScavengeTime_raw": RAW + 6,
            "LastAccessTime": "2024-03-11 09:14:02 UTC",
            "LastScavengeTime": "2024-03-11 09:14:02 UTC"}]

    def get_container_type(self, cid):
        return "History"


class _Engine:
    def __init__(self):
        self.structured_records = [
            _carved_struct(),
            _carved_struct(Url="file:///C:/synthetic/carved.txt",
                           CleanUrl="file:///C:/synthetic/carved.txt",
                           IsLocalFile=True, Offset=5120),
            _carved_struct(Url="http://carvedhost.onion/y",
                           CleanUrl="http://carvedhost.onion/y", Offset=7168),
            _carved_struct(Url="https://downloads.example.test/carved.zip",
                           CleanUrl="https://downloads.example.test/carved.zip",
                           ContainerType="Downloads", ContainerId=9,
                           Offset=6144)]
        self._artifacts = [_carved_string()]
        self.tombstones = [{"Table": "Container_4", "ContainerId": 4,
                            "ContainerType": "History", "Source": "V01.log",
                            "Offset": 8192, "Page": 5,
                            "KeyColumns": ("EntryId",), "KeyValues": (77,)}]

    def all_artifacts(self):
        return self._artifacts


def _exhibit():
    """{(nav key, set key): (rows, table attribute path)} from the loaders."""
    parser, engine = _Parser(), _Engine()
    live = parser.all_entries
    carved = list(engine.structured_records) + engine.all_artifacts()
    out = {}

    def put(nav, key, rows, pane=False):
        out[(nav, key)] = (rows, pane)

    put("history", "history", evidence_loader.history_rows_from_parser(parser)
        + recovery_loader.carved_history_rows(engine))
    put("downloads", "file_access",
        evidence_loader.file_access_rows_from_parser(parser)
        + recovery_loader.carved_file_access_rows(engine))
    put("downloads", "downloads",
        evidence_loader.downloads_rows_from_parser(parser)
        + recovery_loader.carved_downloads_rows(engine))
    result = {"table": "Container_4", "container_name": "History",
              "table_type": "History", "row_index": 1,
              "matched_columns": ["Url"], "match_value": "example",
              "row": {"Url": "https://example.test/a", "EntryId": 1}}
    put("search", "hits", search_loader.search_rows([result]))
    put("search", "hit_fields", search_loader.hit_field_rows(None, result),
        pane=True)

    inputs = timeline_loader.timeline_inputs(live, carved)
    for grain, *_rest in timeline_loader.GRAINS:
        put("timeline", grain, timeline_loader.period_rows(inputs, grain))
    day = timeline_loader.period_rows(inputs, "day")
    put("timeline", "period_records",
        timeline_loader.record_rows(day[0], inputs), pane=True)

    domains = domain_rows(live, carved)
    put("domains", "domains", domains)
    put("domains", "member_records",
        timeline_loader.member_record_rows(domains[0]["_members"]), pane=True)
    fixes = location_loader.position_fixes(live, carved)
    put("location", "fixes", fixes)
    put("location", "places", location_loader.places(fixes))
    put("location", "records", location_loader.source_records(fixes))
    put("indicators", "indicators", indicator_rows(live, carved))
    put("iocs", "ioc_hits", iocs_loader.ioc_hit_rows(live, carved))
    put("iocs", "entryid_gaps", iocs_loader.entryid_gap_rows(live, carved))
    put("iocs", "time_voids", iocs_loader.time_void_rows(live, carved))
    put("iocs", "beaconing", iocs_loader.beaconing_rows(live))
    put("iocs", "deceptive_hostnames",
        iocs_loader.deceptive_hostname_rows(live, carved))
    put("iocs", "redirect_chains", iocs_loader.redirect_hop_rows(live, carved))
    put("cookies", "cookies", evidence_loader.cookie_rows_from_parser(parser))
    put("cookies", "hsts", evidence_loader.hsts_rows_from_parser(parser))
    put("cookies", "certs", evidence_loader.cert_rows_from_parser(parser))
    put("headers", "headers", headers_loader.header_rows_from_parser(parser)
        + headers_loader.carved_header_rows(engine))
    put("containers", "containers",
        evidence_loader.container_rows_from_parser(parser))
    put("recovery", "deleted", recovery_loader.deleted_records_rows(engine))
    from webcache.engine.case_db import CaseDb
    from webcache.shell import case_notes, tagged_loader
    case = CaseDb().open(":memory:")
    case_notes.set_tag(case, [{"_record": live[0]}, {"_record": carved[0]}],
                       "Relevant", True)
    put("tagged", "tagged", tagged_loader.tagged_rows(case, live, carved))
    return out


# --- walking the real window ----------------------------------------------

@pytest.fixture
def window(qtbot):
    """Function-scoped on purpose: a module-scoped window would be built
    before conftest's per-test settings redirect, and its closeEvent would
    write the developer's real settings.json."""
    w = MainWindow()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def views(window):
    return {key: window._ensure_view_built(key) for key in window.nav_keys}


def _filled(views):
    """Yields (nav, set key, view, table, columns, rows), each set filled
    through the view's OWN path just before it is yielded, so the table
    under test is the table an examiner sees. A generator on purpose: a
    view's sets share one grid, and the next fill replaces this one."""
    exhibit = _exhibit()
    for (nav, key), (rows, pane) in exhibit.items():
        view = views[nav]
        if pane:
            columns = (getattr(view, "HIT_FIELD_COLUMNS", None)
                       if nav == "search" else
                       view.MEMBER_COLUMNS if nav == "domains"
                       else view.PERIOD_RECORD_COLUMNS)
            view.pane.set_rows(columns, rows, "heading", "note", "empty")
            table = view.pane.table
        elif hasattr(view, "_record_sets"):
            view.set_records_for(key, rows)
            view._switch_segment(key)
            columns = view._segments_by_key[key].columns
            table = view.table
        else:
            columns = view.COLUMNS
            view.set_records(rows)
            table = view.table
        yield nav, key, view, table, columns, rows


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def _export(view, nav, table, tmp_path, label):
    """The file _export_view writes, from the model's own rows and
    columns, and its sidecar's text."""
    model = table.model()
    rows = list(model.filter.visible())
    scope = F.scope_from_view(view, nav, label, model)
    path = str(tmp_path / ("%s.csv" % label))
    F.write_view_csv(rows, list(model.columns), path, scope)
    side = F.write_view_provenance(path, {}, scope, 0)
    with open(side, encoding="utf-8-sig") as fh:
        return _read(path), fh.read(), rows, list(model.columns)


# --- the structure itself -------------------------------------------------

def test_the_nav_list_is_the_one_being_walked(window, views):
    """Views come from NAV_SECTIONS through the window; the count is
    asserted so a new destination cannot slip past this file."""
    declared = [k for _s, items in NAV_SECTIONS for k, _l, _c in items]
    assert len(declared) == NAV_COUNT
    assert window.nav_keys == declared
    assert len(views) == NAV_COUNT
    for key, view in views.items():
        grids = view.findChildren(RecordsTable)
        if key in NO_GRID:
            assert not grids, "%s now holds a grid; classify its sets" % key
        else:
            assert grids, "%s holds no grid and is not in NO_GRID" % key


def test_every_grid_and_every_set_is_accounted_for(views):
    """A record set nobody classified, or a classification with no set
    behind it, both fail -- and so does a grid no set fills."""
    filled, fed = set(), {}
    for nav, key, _v, table, _c, _r in _filled(views):
        filled.add((nav, key))
        fed.setdefault(nav, []).append(table)
    assert filled == set(EXPECTED)
    declared_sets = {(nav, rs.key) for nav, v in views.items()
                     for rs in getattr(v, "_record_sets", [])}
    assert declared_sets <= set(EXPECTED), sorted(declared_sets - set(EXPECTED))
    for nav, view in views.items():
        for grid in view.findChildren(RecordsTable):
            assert any(t is grid for t in fed.get(nav, [])), (
                nav, "a grid no record set fills")


def test_every_set_is_filled_by_real_rows(views):
    """An empty set would make every later check vacuous."""
    for nav, key, _view, table, _columns, rows in _filled(views):
        assert rows, (nav, key, "the synthetic exhibit gave this set no rows")
        assert table.model().rowCount() == len(rows), (nav, key)


# --- 1. no evidence column elides -----------------------------------------

def test_no_evidence_column_elides_while_the_grid_wraps(views):
    for nav, key, _v, table, _c, _r in _filled(views):
        where = (nav, key)
        assert table.is_wrapping(), where
        assert table.wordWrap(), where
        assert table.textElideMode() == Qt.ElideNone, where
        model = table.model()
        for c in range(model.columnCount()):
            delegate = table.itemDelegateForColumn(c) or table.itemDelegate()
            # WrappingDelegate, not its non-wrapping base class: the base
            # passed this check while it cut unbroken runs.
            assert isinstance(delegate, (WrappingDelegate,
                                         ShareBarDelegate)), (where, c)


def test_no_row_of_any_grid_can_be_taller_than_the_viewport(views):
    """A row taller than the viewport has a bottom
    part per-item scrolling can never show. Every grid is given one
    5,000-character value in a text column; its row stops at the cap,
    and the cap is below the smallest viewport measured on a maximised
    window (Location Raw records, 371 px)."""
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QStyleOptionViewItem
    huge = "https://example.test/" + "/".join("seg%04d" % i for i in range(700))
    checked = 0
    for nav, key, _v, table, _c, _r in _filled(views):
        model = table.model()
        text_cols = [c for c in range(model.columnCount())
                     if model.column_at(c).kind in ("text", "url")]
        if not text_cols:
            continue
        model.row_at(0)[model.column_at(text_cols[0]).key] = huge
        table.resize(1328, 371)
        base = QStyleOptionViewItem()
        table.initViewItemOption(base)
        # The fit adds the grid line to a hint, as sizeHintForRow does.
        cap = table.itemDelegate().cap_height(base) + 1
        assert cap < 371, (nav, key, cap)
        for r in range(min(model.rowCount(), 20)):
            hint = table._row_height_hint(r, base, QFontMetrics(base.font))
            assert hint <= cap, (nav, key, r, hint, cap)
        checked += 1
    assert checked >= 20, checked


def test_the_whole_value_surfaces_wrap_and_never_elide(views, qtbot,
                                                       monkeypatch, tmp_path):
    """The record dialog's field table and the Table
    Browser's whole-row view are where every grid sends an examiner for
    the whole value. Walked here with the grids: the one evidence
    delegate, word wrap on, nothing elided -- a QTableWidget left at Qt's
    default elide mode (ElideRight) fails."""
    from webcache.shell.record_detail import RecordDetailDialog
    from webcache.shell.table_row_detail import TableRowDialog
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    rows, _pane = _exhibit()[("history", "history")]
    dialog = RecordDetailDialog(rows[0])
    whole_row = TableRowDialog(["EntryId", "Url"],
                               [{"type": "Long", "text": "7"},
                                {"type": "Text",
                                 "text": "https://example.test/a"}],
                               table="Container_4")
    qtbot.addWidget(whole_row)
    try:
        for name, table, chrome in (("record dialog", dialog.table, {2}),
                                    ("whole row", whole_row.table, set())):
            assert table.wordWrap(), name
            assert table.textElideMode() == Qt.ElideNone, name
            for c in range(table.columnCount()):
                if c in chrome:
                    continue          # the Basis badge column: chrome
                delegate = (table.itemDelegateForColumn(c)
                            or table.itemDelegate())
                assert isinstance(delegate, WrappingDelegate), (name, c)
    finally:
        dialog.close()


def test_a_grid_elides_only_when_the_examiner_turns_wrap_off(views):
    """The one route to elision is the user's own toggle, and it comes
    back: nothing else in a grid may set ElideRight."""
    table = views["history"].table
    table.set_wrap(False)
    assert table.textElideMode() == Qt.ElideRight
    table.set_wrap(True)
    assert table.textElideMode() == Qt.ElideNone and table.wordWrap()


def test_the_default_setting_is_wrap_on(window):
    assert window._grid_wrap is True


def test_the_raw_grid_wraps_and_never_elides(views, qtbot):
    """The Table Browser is no longer an exception: its
    raw grid holds each value whole, wraps with the one evidence delegate
    under the row cap, and elides only when the examiner turns Wrap off --
    walked under the same assertions as every record grid."""
    from tests.test_raw_values_whole import LONG, _Rows
    view = views["browser"]
    view.set_parser(_Rows([[1, LONG], [2, b"\x00\x01" * 200]]))
    view.select_table("Container_2")
    grid = view.grid
    assert grid.wordWrap()
    assert grid.textElideMode() == Qt.ElideNone
    assert isinstance(grid.itemDelegate(), WrappingDelegate)
    for c in range(grid.columnCount()):
        assert grid.itemDelegateForColumn(c) is None, c
    assert grid.item(0, 1).text() == LONG
    assert "View these bytes" in grid.item(1, 1).text()
    assert "whole" in view.view_row_button.toolTip().lower()


# --- 2. the export carries the full field set for its records -------------

def test_every_views_export_carries_the_full_set_for_its_records(
        views, tmp_path):
    heads = {k: h for k, h, _g in ENTRY_FIELDS}
    for nav, key, view, table, _columns, _rows in _filled(views):
        where = (nav, key)
        expected = EXPECTED[where]
        header, sidecar, rows, columns = _export(
            view, nav, table, tmp_path, "%s_%s" % (nav, key))
        canon = F.canonical_columns_for(rows, columns)
        by_key = {c.key: c for c in columns if c.field == c.key}
        if expected == ENTRY:
            assert any(isinstance(k, str) for k, _h in canon) or by_key, where
            for row in rows:
                assert isinstance(row.get("_record"), dict), (
                    where, "a record view whose rows carry no _record "
                    "exports derived values only")
                assert row.get("_kind") not in record_kinds.AGGREGATES, where
            # Every ENTRY_FIELDS key is either written after the view's own
            # columns or is one the view declares as that same field.
            written = {k for k, _h in canon}
            for k, h, _g in ENTRY_FIELDS:
                assert k in written or k in by_key, (where, k)
            # The exact stored values reach the file, not their derivations.
            hdr, *body = header
            for probe in PROBES:
                name = heads[probe]
                if name in hdr:
                    col = hdr.index(name)
                elif ("%s (record)" % name) in hdr:
                    col = hdr.index("%s (record)" % name)
                elif probe in by_key:
                    col = [c.key for c in columns].index(probe)
                else:
                    pytest.fail("%s: %s is nowhere in the export" % (where, probe))
                for row, cells in zip(rows, body):
                    value = row["_record"].get(probe)
                    if value in (None, ""):
                        continue
                    if (probe == "Confidence"
                            and row.get("_kind") == record_kinds.K_TOMBSTONE):
                        # the screen's Confidence is the one word
                        # "exact" and the key is its own Key column; the
                        # stored long form ("exact key: ...") still names
                        # both for writers with no Key column.
                        assert cells[col] == row["Confidence"], (where, probe)
                        assert row["Key"] in str(value), (where, probe)
                        continue
                    assert cells[col] == str(value), (where, probe)
            assert "Canonical fields :" in sidecar or "Record fields" in sidecar
        elif expected == OWN:
            own = [k for k, _h in canon if isinstance(k, tuple)]
            assert own, (where, "an own-kind record set exports only its "
                         "derived columns")
            assert not any(isinstance(k, str) for k, _h in canon), (
                where, "a non-entry record must not get the URL-cache schema")
            hdr, *body = header
            for row, cells in zip(rows, body):
                record = row["_record"]
                assert isinstance(record, dict), where
                for k in record:
                    assert (k in by_key
                            or any(t == ("_record", k) for t, _h in canon)), (
                        where, k)
                    if str(k).endswith("_raw") and record[k]:
                        name = next(h for t, h in canon if t == ("_record", k))
                        cell = cells[hdr.index(name)]
                        shown = (record[k].hex() if isinstance(record[k], bytes)
                                 else str(record[k]))
                        assert cell.lower() == shown.lower(), (where, k)
            assert "Record fields" in sidecar, where
        else:
            assert canon == [], (where, "an aggregate or non-record view "
                                 "must not fabricate per-record columns")
            reason = ("aggregates, not single records" if expected == AGGREGATE
                      else "not single parsed records")
            assert reason in sidecar, (where, "the sidecar must say why "
                                       "there are no per-record fields")


# --- 3. origin label and headings -----------------------------------------

def test_the_origin_label_renders_on_every_row_of_every_grid(views):
    for nav, key, _v, table, _c, rows in _filled(views):
        where = (nav, key)
        model = table.model()
        visible = list(model.filter.visible())
        assert visible, where
        header = table.verticalHeader()
        assert not header.isHidden(), where
        assert header.width() >= header.floor_width(), where
        for r, row in enumerate(visible):
            shown = model.headerData(r, Qt.Vertical, Qt.DisplayRole)
            if aggregate_members(row) is not None:
                # an aggregate's label comes from its members.
                assert shown == (aggregate_origin_of(row) or "—"), (
                    where, r)
                continue
            if "_record" in row and row["_record"] is None:
                # neither a record nor a population never reads Live.
                assert shown == "—", (where, r)
                continue
            carved = str(row.get("Origin", "")).startswith("Carved")
            assert shown == (
                ORIGIN_LABEL_CARVED if carved else ORIGIN_LABEL_LIVE), (where, r)


def test_the_exhibit_puts_both_origins_in_the_record_views(views):
    """The label check above is only as good as its rows: the record sets
    that can hold carved rows must hold one here."""
    for nav, key, _v, table, _c, _r in _filled(views):
        if EXPECTED[(nav, key)] != ENTRY:
            continue
        origins = {str(r.get("Origin", "")).startswith("Carved")
                   for r in table.model().filter.visible()}
        if (nav, key) in {("history", "history"), ("downloads", "file_access"),
                          ("iocs", "ioc_hits"), ("location", "fixes"),
                          ("headers", "headers")}:
            assert origins == {True, False}, (nav, key)


def test_no_two_headings_in_one_grid_are_alike(views):
    for nav, key, _v, _t, columns, _r in _filled(views):
        labels = [c.label for c in columns]
        assert len(labels) == len(set(labels)), (nav, key, sorted(
            l for l in labels if labels.count(l) > 1))
        assert ORIGIN_HEADING not in labels, (
            nav, key, "duplicates the vertical header's own heading")
