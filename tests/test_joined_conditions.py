"""Excel's Custom AutoFilter: two conditions on one column, joined by And or
Or. Each half reads the cell exactly as it would alone (a text operator the
shown text, a number or date operator the stored value), and the chip
states both halves and the join."""
import datetime

import pytest

from webcache.widgets.column_spec import Column
from webcache.widgets.filter_popup import FilterPopup
from webcache.widgets.record_filter import (Condition, JoinedCondition,
                                            RecordFilter)
from webcache.widgets.record_model import RecordTableModel

UTC = datetime.timezone.utc
COLUMNS = [
    Column("Id", "Id", 60, kind="num"),
    Column("Name", "Name", 120, kind="text"),
    Column("Visits", "Visits", 70, kind="num"),
    Column("Seen", "Seen", 160, kind="time"),
    Column("Private", "Private", 70, kind="flag"),
]


def _rows():
    names = ["alpha", "beta", "gamma", "alphabet", "delta", "", None]
    return [{"Id": i, "Name": names[i % len(names)], "Visits": i,
             "Seen": datetime.datetime(2026, 1, 1 + i, tzinfo=UTC),
             "Private": i % 2 == 0} for i in range(14)]


def _ids(flt):
    return [r["Id"] for r in flt.visible()]


def test_or_keeps_a_row_either_half_keeps():
    flt = RecordFilter(_rows(), COLUMNS)
    flt.set_condition("Visits", JoinedCondition(
        Condition("<", "2"), "or", Condition(">", "11")))
    assert _ids(flt) == [0, 1, 12, 13]


def test_and_keeps_only_a_row_both_halves_keep():
    flt = RecordFilter(_rows(), COLUMNS)
    flt.set_condition("Name", JoinedCondition(
        Condition("begins with", "alpha"), "and",
        Condition("does not contain", "bet")))
    assert _ids(flt) == [0, 7]


def test_a_text_half_reads_the_shown_text_and_a_number_half_the_value():
    flt = RecordFilter(_rows(), COLUMNS)
    flt.set_condition("Private", JoinedCondition(
        Condition("equals", "Yes"), "and", Condition("is not blank")))
    assert _ids(flt) == list(range(0, 14, 2))
    flt.set_condition("Visits", JoinedCondition(
        Condition("ends with", "3"), "or", Condition("between", "6", "7")))
    assert _ids(flt) == [6]


def test_the_chip_states_both_halves_and_the_join():
    flt = RecordFilter(_rows(), COLUMNS)
    flt.set_condition("Visits", JoinedCondition(
        Condition("<", "2"), "or", Condition(">", "11")))
    assert flt.chip_text() == 'Visits: < "2" or > "11"'


def test_an_invalid_half_is_the_conditions_error():
    joined = JoinedCondition(Condition("equals", "a"), "and",
                             Condition("matches regex", "("))
    assert joined.error
    assert not joined.matches("a")


def test_in_the_last_n_days_is_anchored_inside_a_join():
    flt = RecordFilter(_rows(), COLUMNS)
    flt.set_condition("Seen", JoinedCondition(
        Condition("in the last N days", "2"), "or",
        Condition("before", "2026-01-02")))
    assert _ids(flt) == [0, 11, 12, 13]


def test_a_join_must_be_and_or_or():
    with pytest.raises(ValueError):
        JoinedCondition(Condition("<", "2"), "xor", Condition(">", "3"))


# --- the popup ------------------------------------------------------------

@pytest.fixture
def popup(qtbot):
    model = RecordTableModel(list(COLUMNS), _rows())

    def make():
        p = FilterPopup(model, COLUMNS[2])
        qtbot.addWidget(p)
        p.show()
        qtbot.waitExposed(p)
        return p
    return model, make


def test_the_popup_applies_two_conditions_joined_by_or(popup):
    model, make = popup
    p = make()
    p.operator_box.setCurrentText("<")
    p.operand_a.setText("2")
    p.join_box.setCurrentText("Or")
    p.operator_box_2.setCurrentText(">")
    p.operand_a_2.setText("11")
    p._ok()
    assert [model.row_at(r)["Id"] for r in range(model.rowCount())] == [0, 1, 12, 13]
    cond = model.filter.condition_for("Visits")
    assert isinstance(cond, JoinedCondition) and cond.join == "or"


def test_a_reopened_popup_shows_both_halves_and_the_join(popup):
    model, make = popup
    model.set_column_filter("Visits", None, JoinedCondition(
        Condition("between", "3", "5"), "and", Condition("!=", "4")))
    p = make()
    assert (p.operator_box.currentText(), p.operand_a.text(),
            p.operand_b.text()) == ("between", "3", "5")
    assert p.join_box.currentText() == "And"
    assert (p.operator_box_2.currentText(), p.operand_a_2.text()) == (
        "!=", "4")
    p._ok()
    assert [model.row_at(r)["Id"] for r in range(model.rowCount())] == [3, 5]


def test_only_the_second_row_filled_is_a_single_condition(popup):
    model, make = popup
    p = make()
    p.operator_box_2.setCurrentText(">")
    p.operand_a_2.setText("11")
    p._ok()
    cond = model.filter.condition_for("Visits")
    assert isinstance(cond, Condition) and cond.op == ">"


def test_a_one_sided_between_in_the_second_row_is_refused(popup):
    model, make = popup
    p = make()
    p.operator_box.setCurrentText("<")
    p.operand_a.setText("2")
    p.operator_box_2.setCurrentText("between")
    p.operand_a_2.setText("6")
    assert p.apply() is False
    assert "between" in p.status_text()
    assert model.filter.condition_for("Visits") is None


def test_the_condition_rows_carry_excels_heading(popup):
    _model, make = popup
    assert make().condition_caption.text() == "Show rows where:"
