"""The filter popup's date tree, flag operators and look."""
import datetime
import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QListView

from webcache.shell import theme
from webcache.widgets.column_spec import Column
from webcache.widgets.filter_popup import FilterPopup
from webcache.widgets.record_filter import Condition
from webcache.widgets.record_model import RecordTableModel

UTC = datetime.timezone.utc


def _model(rows, columns):
    return RecordTableModel(columns, rows)


TIME = Column("When", "When (UTC)", 160, kind="time")
FLAG = Column("IsInPrivate", "InPrivate", 80, kind="flag")
ROWS = ([{"When": datetime.datetime(2024, 3, d, h, tzinfo=UTC),
          "IsInPrivate": False} for d in (1, 2) for h in range(10)]
        + [{"When": datetime.datetime(2025, 1, 5, 9, tzinfo=UTC),
            "IsInPrivate": True}])


def test_a_time_column_is_picked_by_year_month_and_day(qtbot):
    model = _model(ROWS, [TIME, FLAG])
    popup = FilterPopup(model, TIME)
    qtbot.addWidget(popup)
    tree = popup.date_tree
    years = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert years == ["2024  (20)", "2025  (1)"]
    march = tree.topLevelItem(0).child(0)
    assert march.text(0) == "2024-03  (20)"
    assert [march.child(i).text(0) for i in range(march.childCount())] == \
        ["2024-03-01  (10)", "2024-03-02  (10)"]
    for i in range(tree.topLevelItemCount()):
        tree.topLevelItem(i).setCheckState(0, Qt.Unchecked)
    march.child(1).setCheckState(0, Qt.Checked)
    assert popup.apply()
    assert model.rowCount() == 10


def test_operands_say_what_to_type(qtbot):
    model = _model(ROWS, [TIME, FLAG])
    popup = FilterPopup(model, TIME)
    qtbot.addWidget(popup)
    assert "YYYY-MM-DD" in popup.operand_a.placeholderText()


def test_a_boolean_flag_offers_yes_and_no_not_text_operators(qtbot):
    model = _model(ROWS, [TIME, FLAG])
    popup = FilterPopup(model, FLAG)
    qtbot.addWidget(popup)
    ops = [popup.operator_box.itemText(i) for i in range(popup.operator_box.count())]
    assert "is yes" in ops and "is no" in ops and "contains" not in ops
    popup.operator_box.setCurrentText("is yes")
    assert popup.apply()
    assert model.rowCount() == 1
    assert Condition("is yes").describe(FLAG) == "Is Yes"


def test_a_short_value_list_is_filled_before_the_first_paint(qtbot):
    model = _model(ROWS, [TIME, FLAG, Column("Name", "Name", 80)])
    popup = FilterPopup(model, model.columns[2])
    qtbot.addWidget(popup)
    assert popup.values_list.layoutMode() == QListView.SinglePass


@pytest.mark.parametrize("name", ["dark", "light"])
def test_a_checked_box_carries_a_tick_image(qtbot, name):
    app = QApplication.instance()
    previous = theme.current_name()
    theme.apply(app, name)
    try:
        _check_tick(app, name)
    finally:
        theme.apply(app, previous)


def _check_tick(app, name):
    sheet = app.styleSheet()
    assert "QCheckBox::indicator:checked" in sheet
    for selector in ("QCheckBox::indicator:checked",
                     "QListWidget::indicator:checked"):
        block = sheet.split(selector, 1)[1].split("}", 1)[0]
        assert "image: url(" in block
    path = theme.PALETTES[name].get("check_mark", "")
    assert os.path.exists(path)


def _lum(hex_colour):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    c = QColor(hex_colour)
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


@pytest.mark.parametrize("name", ["dark", "light"])
@pytest.mark.parametrize("background", ["base", "row_alt", "carved_row"])
def test_timestamps_meet_wcag_aa_on_every_row(name, background):
    p = theme.PALETTES[name]
    a, b = sorted((_lum(p.get("time_text", p["primary"])), _lum(p[background])), reverse=True)
    assert (a + 0.05) / (b + 0.05) >= 4.5


def test_a_time_cell_is_painted_in_the_time_text_role(qtbot):
    model = _model(ROWS, [TIME, FLAG])
    got = model.data(model.index(0, 0), Qt.ForegroundRole)
    assert got == QColor(theme.PALETTES[theme.current_name()].get(
        "time_text", "#000000"))


def test_ticking_a_month_ticks_its_days_and_a_partial_shows_tristate(qtbot):
    rows = ROWS + [{"When": None, "IsInPrivate": None}]
    model = _model(rows, [TIME, FLAG])
    popup = FilterPopup(model, TIME)
    qtbot.addWidget(popup)
    tree = popup.date_tree
    y2024 = tree.topLevelItem(0)
    march = y2024.child(0)
    assert tree.topLevelItem(tree.topLevelItemCount() - 1).text(0) == "(blank)  (1)"
    popup.select_none()
    assert march.checkState(0) == Qt.Unchecked
    march.child(0).setCheckState(0, Qt.Checked)
    assert march.checkState(0) == Qt.PartiallyChecked
    assert y2024.checkState(0) == Qt.PartiallyChecked
    march.setCheckState(0, Qt.Checked)
    assert [march.child(i).checkState(0) for i in range(2)] == [Qt.Checked] * 2
    assert popup.apply()
    assert model.rowCount() == 20


def test_a_local_column_groups_by_its_own_displayed_day(qtbot):
    local = Column("L", "Last visit (LOCAL)", 160, kind="time_local")
    plus5 = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    rows = [{"L": datetime.datetime(2024, 3, 1, 23, 50, tzinfo=plus5)},
            {"L": datetime.datetime(2024, 3, 2, 0, 10, tzinfo=plus5)}]
    popup = FilterPopup(_model(rows, [local]), local)
    qtbot.addWidget(popup)
    march = popup.date_tree.topLevelItem(0).child(0)
    assert [march.child(i).text(0) for i in range(march.childCount())] == \
        ["2024-03-01  (1)", "2024-03-02  (1)"]
    assert "(local)" in popup.operand_a.placeholderText()


def test_searching_a_time_tree_hides_empty_months(qtbot):
    popup = FilterPopup(_model(ROWS, [TIME, FLAG]), TIME)
    qtbot.addWidget(popup)
    popup.search_box.setText("2025-01")
    popup._apply_value_search()
    assert popup.visible_value_count() == 1
    assert popup.date_tree.topLevelItem(0).isHidden()
    assert not popup.date_tree.topLevelItem(1).isHidden()


def test_ticking_values_on_a_yes_no_column_adds_no_condition(qtbot):
    """OK after only ticking values must filter by those
    values alone. The operator box once opened on "is yes", so the same OK
    silently hid every "No" row as well."""
    model = _model(ROWS, [TIME, FLAG])
    popup = FilterPopup(model, FLAG)
    qtbot.addWidget(popup)
    for i in range(popup.values_list.count()):
        item = popup.values_list.item(i)
        item.setCheckState(Qt.Unchecked if item.data(Qt.UserRole) is True
                           else Qt.Checked)
    assert popup.apply()
    assert model.rowCount() == 20
    assert model.filter.condition_for("IsInPrivate") is None
    assert popup.operator_box.currentText() == "(no condition)"
