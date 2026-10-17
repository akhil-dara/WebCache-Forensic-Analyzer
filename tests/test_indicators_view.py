"""IndicatorsView: one RecordSet, built on RecordsView the same way
ContainersView/DomainsView are -- against rows shaped the way
indicator_loader.indicator_rows() actually produces them (see
test_indicator_loader.py for that shape's own tests).

No column here drills anywhere -- like cookies.py's own three segments,
no existing view is "records carrying this indicator" (see cookies.py's
own docstring for the same reasoning).
"""
from webcache.views.indicators import IndicatorsView


def _row(**overrides):
    base = {
        "Kind": "Windows SID", "Value": "S-1-5-21-1-2-3-500",
        "Decoded": "the built-in Administrator", "Conf": "High",
        "Records": 3, "Why": "the S-1-<authority>-<sub> form is unambiguous",
    }
    base.update(overrides)
    return base


def make_rows(n):
    return [_row(Value="S-1-5-21-1-2-3-%d" % i, Records=i + 1) for i in range(n)]


# --- columns -------------------------------------------------------------

def test_columns_match_the_spec(qtbot):
    v = IndicatorsView()
    qtbot.addWidget(v)
    keys = [c.key for c in v.COLUMNS]
    assert keys == ["Kind", "Value", "Decoded", "Conf", "Records",
                    "Fields", "Why"]


def test_kind_and_confidence_columns_use_the_flag_kind(qtbot):
    v = IndicatorsView()
    qtbot.addWidget(v)
    for key in ("Kind", "Conf"):
        col = next(c for c in v.COLUMNS if c.key == key)
        assert col.kind == "flag"


def test_records_column_is_numeric(qtbot):
    v = IndicatorsView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "Records")
    assert col.kind == "num"
    assert col.numeric is True


def test_no_column_drills_anywhere(qtbot):
    v = IndicatorsView()
    qtbot.addWidget(v)
    assert all(not c.is_link for c in v.COLUMNS)


# --- the table itself ----------------------------------------------------

def test_the_table_shows_every_record(qtbot):
    v = IndicatorsView()
    v.set_records(make_rows(22))
    qtbot.addWidget(v)
    assert v.table.model().rowCount() == 22
    assert "22" in v.count_label.text()


def test_typing_in_the_filter_box_narrows_the_table(qtbot):
    from PySide6.QtTest import QTest

    v = IndicatorsView()
    v.set_records(make_rows(50))
    qtbot.addWidget(v)
    QTest.keyClicks(v.filter_box, "S-1-5-21-1-2-3-1")
    qtbot.waitUntil(lambda: v.table.model().rowCount() < 50, timeout=3000)


def test_no_quick_filters_means_no_chip_row(qtbot):
    v = IndicatorsView()
    qtbot.addWidget(v)
    assert v._quick_filters == []


def test_it_has_no_switcher_being_a_single_record_set(qtbot):
    v = IndicatorsView()
    qtbot.addWidget(v)
    assert v._switcher_buttons == {}


def test_header_and_caveat_are_reachable(qtbot):
    v = IndicatorsView()
    qtbot.addWidget(v)
    assert v.header is not None
    v.set_caveat("Values carried inside URLs; presence is not intent.")
    assert v.caveat is not None


def test_zero_records_because_none_exist_reads_as_a_genuine_empty_state(qtbot):
    v = IndicatorsView()
    v.set_records([])
    qtbot.addWidget(v)
    assert v.table.showing_genuine_empty_state() is True


def test_a_not_determinable_confidence_does_not_crash_display(qtbot):
    v = IndicatorsView()
    qtbot.addWidget(v)
    v.set_records([_row(Conf="Not determinable")])
    assert v.table.model().rowCount() == 1
    assert v.table.model().row_at(0)["Conf"] == "Not determinable"
