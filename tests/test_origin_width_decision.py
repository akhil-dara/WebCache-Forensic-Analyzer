"""Whether the origin column is sized for the
aggregate words is decided from the row set's kind -- one look at the
first row, since a view's row set is homogeneous -- never by sampling
rows."""
from webcache.widgets import records_table
from tests.fixtures import FIXTURE_COLUMNS, make_rows


def test_the_origin_width_is_decided_from_one_row(qtbot, monkeypatch):
    calls = []
    real = records_table.aggregate_members

    def counting(row):
        calls.append(1)
        return real(row)

    monkeypatch.setattr(records_table, "aggregate_members", counting)
    table = records_table.RecordsTable()
    qtbot.addWidget(table)
    table.set_records(FIXTURE_COLUMNS, make_rows(500))
    assert len(calls) <= 1, len(calls)
    assert not table.verticalHeader()._aggregate
