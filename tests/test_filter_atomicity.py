"""A column's filter is applied whole or not at all.

set_values and set_condition each roll back on failure, but:
  * FilterPopup.apply committed the values, THEN the condition -- a raise
    in the second left the first applied: half a filter;
  * a quick-filter chip whose filter raised stayed checked while the model
    rolled back -- the chip claimed a filter the grid was not applying;
  * either exception escaped a Qt slot, where PySide prints it and the
    examiner sees nothing.
"""
from webcache.views.history import HistoryView
from webcache.widgets.filter_popup import FilterPopup
from webcache.widgets.record_filter import Condition, RecordFilter
from webcache.widgets.record_model import RecordTableModel
from tests.fixtures import FIXTURE_COLUMNS, make_rows


class _Boom(Condition):
    """Validates cleanly, raises while MATCHING -- the case rollback is
    for."""

    def matches(self, value):
        raise RuntimeError("matcher exploded")


def _boom():
    return _Boom("contains", "x")


def test_set_column_filter_sets_both_in_one_step():
    f = RecordFilter(make_rows(200), FIXTURE_COLUMNS)
    assert hasattr(f, "set_column_filter"), "RecordFilter.set_column_filter is missing"
    domains = {r["Domain"] for r in f.rows[:3]}
    cond = Condition("contains", "a")
    f.set_column_filter("Domain", domains, cond)
    assert f.allowed_values("Domain") == domains
    assert f.condition_for("Domain") is cond
    assert all(r["Domain"] in domains and "a" in r["Domain"].lower()
               for r in f.visible())


def test_set_column_filter_rolls_both_back_when_the_condition_raises():
    f = RecordFilter(make_rows(200), FIXTURE_COLUMNS)
    assert hasattr(f, "set_column_filter"), "RecordFilter.set_column_filter is missing"
    before_values = {r["Domain"] for r in f.rows[:5]}
    f.set_values("Domain", before_values)
    visible_before = list(f.visible())
    raised = False
    try:
        f.set_column_filter("Domain", {f.rows[0]["Domain"]}, _boom())
    except RuntimeError:
        raised = True
    assert raised
    assert f.allowed_values("Domain") == before_values
    assert f.condition_for("Domain") is None
    assert f.visible() == visible_before


def test_popup_apply_is_never_half_applied(qtbot):
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(300))
    col = next(c for c in FIXTURE_COLUMNS if c.key == "Domain")
    popup = FilterPopup(model, col)
    qtbot.addWidget(popup)
    popup.show()
    qtbot.waitExposed(popup)
    one = model.filter.rows[0]["Domain"]
    popup.chosen_values = lambda: {one}
    popup.chosen_condition = _boom
    raised = None
    result = None
    with qtbot.capture_exceptions() as leaked:
        try:
            result = popup.apply()
        except RuntimeError as exc:
            raised = exc
    assert model.filter.allowed_values("Domain") is None, (
        "the values half of a failed apply stayed applied")
    assert model.filter.condition_for("Domain") is None
    assert raised is None, "apply let %r escape into its Qt slot" % raised
    assert result is False
    assert "matcher exploded" in popup.status_text()
    assert not leaked


def test_a_chip_whose_filter_fails_unchecks_and_says_why(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(make_rows(300))
    model = view.table.model()

    def explode(*_a, **_k):
        raise RuntimeError("chip filter exploded")

    model.set_values = explode
    model.set_condition = explode
    with qtbot.capture_exceptions() as leaked:
        view.chip_inprivate.setChecked(True)
    assert not view.chip_inprivate.isChecked(), (
        "the chip stayed checked while the grid applies no filter")
    assert "chip filter exploded" in view.count_label.text()
    assert not leaked, "the exception escaped the Qt slot"
