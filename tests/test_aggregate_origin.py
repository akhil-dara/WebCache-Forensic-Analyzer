"""An aggregate row says where its members came from."""
import datetime

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetricsF

from webcache.shell import domain_loader, export_formats, timeline_loader
from webcache.shell.record_kinds import K_TIME_VOID
from webcache.views.domains import DomainsView
from webcache.widgets.column_spec import Column
from webcache.widgets.record_model import RecordTableModel
from webcache.widgets.records_table import RecordsTable

UTC = datetime.timezone.utc
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=UTC)


def ft(dt):
    return int((dt - _EPOCH).total_seconds()) * 10_000_000


DAY = datetime.datetime(2024, 3, 1, 10, 0, tzinfo=UTC)


def live(url, when=DAY):
    return {"Url": url, "CleanUrl": url, "ContainerType": "History",
            "ModifiedTime_raw": ft(when), "AccessCount": 1, "FileSize": 0}


def carved(url, when=DAY):
    e = live(url, when)
    e.update(RecoverySource="unallocated page", Source="WebCacheV01.dat",
             Offset=4096, Page=1, Confidence="high")
    return e


def _labels(rows):
    model = RecordTableModel([Column("Records", "Records", 80, kind="num")], rows)
    return [model.headerData(i, Qt.Vertical, Qt.DisplayRole)
            for i in range(model.rowCount())]


def test_a_domain_whose_every_record_is_carved_reads_recovered_only():
    rows = domain_loader.domain_rows(
        [live("https://kept.example.test/a")],
        [carved("https://gone.example.test/a"),
         carved("https://gone.example.test/b"),
         carved("https://kept.example.test/b")])
    by_domain = dict(zip([r["Domain"] for r in rows], _labels(rows)))
    assert by_domain["gone.example.test"] == "Recovered only"
    assert by_domain["kept.example.test"] == "Mixed"


def test_a_domain_with_only_live_records_reads_live():
    rows = domain_loader.domain_rows([live("https://a.example.test/1")], [])
    assert _labels(rows) == ["Live"]


def test_a_period_of_carved_records_reads_recovered_only():
    later = DAY + datetime.timedelta(days=3)
    inputs = timeline_loader.timeline_inputs(
        [live("https://a.example.test/1")],
        [carved("https://b.example.test/1", later),
         carved("https://b.example.test/2", later)])
    rows = timeline_loader.period_rows(inputs, "day")
    assert dict(zip([r["Period"] for r in rows], _labels(rows))) == {
        "2024-03-01": "Live", "2024-03-04": "Recovered only"}


def test_a_row_that_is_neither_a_record_nor_a_population_never_reads_live():
    rows = [{"From": DAY, "To": DAY, "GapHours": 5, "_record": None,
             "_kind": K_TIME_VOID}]
    assert _labels(rows) == ["—"]


def test_a_recovered_only_aggregate_is_tinted_like_a_carved_record(qtbot):
    rows = domain_loader.domain_rows([], [carved("https://gone.example.test/a")])
    model = RecordTableModel([Column("Records", "Records", 80, kind="num")], rows)
    assert model.data(model.index(0, 0), Qt.BackgroundRole) is not None


def test_the_origin_column_is_wide_enough_for_the_aggregate_words(qtbot):
    view = DomainsView()
    qtbot.addWidget(view)
    view.set_records(domain_loader.domain_rows(
        [], [carved("https://gone.example.test/a")]))
    header = view.table.verticalHeader()
    need = QFontMetricsF(header.painted_font()).horizontalAdvance("Recovered only")
    assert header.width() >= need


def test_the_export_origin_cell_names_the_derived_origin():
    rows = domain_loader.domain_rows([], [carved("https://gone.example.test/a")])
    assert export_formats.origin_cell(rows[0]) == (
        "Aggregate (not a record) — Recovered only")


# --- -----------------------------------------------------------

def _every_row_kind():
    from webcache.shell import iocs_loader
    domains = domain_loader.domain_rows(
        [live("https://kept.example.test/a")],
        [carved("https://gone.example.test/a")])
    period_inputs = timeline_loader.timeline_inputs(
        [live("https://a.example.test/1")],
        [carved("https://b.example.test/1", DAY + datetime.timedelta(days=3))])
    periods = timeline_loader.period_rows(period_inputs, "day")
    voids = [{"From": DAY, "To": DAY, "GapHours": 5, "_record": None,
              "_kind": K_TIME_VOID}]
    hops = [{"Hop": 1, "_record": None, "_kind": "redirect_hop"}]
    empty_aggregate = [{"Records": 0, "_record": None, "_members": [],
                        "_kind": domains[0]["_kind"]}]
    records = [live("https://a.example.test/1"),
               carved("https://b.example.test/1")]
    for r in records:
        r["Origin"] = "Carved (deleted/unflushed)" if r.get(
            "RecoverySource") else "Live record"
    return domains + periods + voids + hops + empty_aggregate + records


def test_the_export_origin_cell_agrees_with_the_header_for_every_row_kind():
    rows = _every_row_kind()
    for row, label in zip(rows, _labels(rows)):
        cell = export_formats.origin_cell(row)
        if label == "\u2014":
            assert cell == "\u2014", (row.get("_kind"), cell)
        elif label == "Live":
            assert cell in ("Live record",) or cell.endswith("Live"), cell
        elif label == "Carved":
            assert cell.startswith("Carved"), cell
        else:
            assert cell.endswith(label), (label, cell)
        # A memberless, non-record row never exports as a live record.
        if row.get("_record", 1) is None and not row.get("_members"):
            assert cell != "Live record"


def test_an_entryid_gap_with_recovered_members_reads_mixed_not_live():
    from webcache.shell import iocs_loader
    def entry(eid, extra=None):
        e = live("https://a.example.test/%d" % eid)
        e.update(ContainerId=7, ContainerName="History", ContainerType="History",
                 EntryId=eid)
        e.update(extra or {})
        return e
    live_entries = [entry(1), entry(4)]
    carved_entries = [entry(2, {"RecoverySource": "unallocated page"})]
    rows = iocs_loader.entryid_gap_rows(live_entries, carved_entries)
    assert rows and rows[0]["Recovered"] == 1
    assert _labels(rows) == ["Mixed"]


def test_the_origin_column_is_sized_for_aggregates_whatever_the_first_row(qtbot):
    from webcache.widgets.records_table import RecordsTable
    table = RecordsTable()
    qtbot.addWidget(table)
    columns = [Column("Records", "Records", 80, kind="num")]
    plain = {"Records": 1, "_record": None}
    aggregate = domain_loader.domain_rows(
        [], [carved("https://gone.example.test/a")])[0]
    table.set_records(columns, [plain, aggregate])
    header = table.verticalHeader()
    need = QFontMetricsF(header.painted_font()).horizontalAdvance("Recovered only")
    assert header.width() >= need


def test_the_origin_legend_explains_the_dash_and_the_aggregate_words(qtbot):
    view = DomainsView()
    qtbot.addWidget(view)
    view.set_records(domain_loader.domain_rows(
        [], [carved("https://gone.example.test/a")]))
    tip = view.table.corner_button.toolTip()
    for word in ("Mixed", "Recovered only", "\u2014:"):
        assert word in tip, word
