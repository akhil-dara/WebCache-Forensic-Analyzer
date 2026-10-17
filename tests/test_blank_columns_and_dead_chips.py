"""Empty columns and chips that cannot change anything.

A column empty in every row folds away with the identical ones, and the
chip names it -- "N columns hidden: M identical, K empty in every row".

A quick-filter chip whose column holds one value in every row can only
empty the grid (or change nothing), so it is disabled after the fill, with
the reason in its tooltip -- and enabled again when a fill brings rows that
differ.
"""
from webcache.views.history import HistoryView
from tests.fixtures import make_rows


def _rows(inprivate=False):
    rows = make_rows(12)
    for row in rows:
        row["Title"] = ""
        row["IsInPrivate"] = False
    if inprivate:
        rows[3]["IsInPrivate"] = True
    return rows


def _hidden(view, key):
    keys = [c.key for c in view.table.model().columns]
    return view.table.isColumnHidden(keys.index(key))


def test_a_column_empty_in_every_row_is_hidden_and_named(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(_rows())
    assert _hidden(view, "Title")
    text = view._constant_chip.text()
    assert "empty in every row" in text, text
    assert "Title" in text


def test_the_chip_counts_identical_and_empty_columns(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(_rows())
    text = view._constant_chip.text()
    identical = len(view.table.identical_columns())
    rows = _rows()
    empty = sum(1 for c in view.table.model().columns
                if not c.optional
                and all(r.get(c.key) in (None, "") for r in rows))
    assert empty >= 1
    assert ("%d columns hidden: %d identical, %d empty in every row"
            % (identical + empty, identical, empty)) in text, text


def test_a_chip_that_can_only_empty_the_grid_is_disabled_with_a_reason(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(_rows())
    chip = view.chip_inprivate
    assert not chip.isEnabled()
    assert "Every row is No" in chip.toolTip()
    view.set_records(_rows(inprivate=True))
    assert chip.isEnabled()


def test_a_column_with_a_filter_on_it_is_never_folded_away(qtbot):
    """Filtering InPrivate to Yes makes it identical in every row shown; it
    must stay visible, or its filter could be neither seen nor cleared."""
    view = HistoryView()
    qtbot.addWidget(view)
    rows = _rows(inprivate=True)
    rows[5]["IsInPrivate"] = True     # two rows survive the filter
    view.set_records(rows)
    assert not _hidden(view, "IsInPrivate")
    view.table.model().set_values("IsInPrivate", {True})
    view._update_constant_chip_now()
    assert not _hidden(view, "IsInPrivate")


def test_a_filtered_identical_column_is_named_as_shown_not_counted_hidden(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(_rows())
    before = view._constant_chip.text()
    hidden_before = len(view.table.auto_hidden_keys())
    assert "InPrivate" in before and _hidden(view, "IsInPrivate")
    view.table.model().set_values("IsInPrivate", {False})
    view._update_constant_chip_now()
    text = view._constant_chip.text()
    assert not _hidden(view, "IsInPrivate")
    hidden = len(view.table.auto_hidden_keys())
    assert hidden == hidden_before - 1
    assert text.startswith("%d columns hidden:" % hidden), text
    assert "InPrivate: No (filtered, shown)" in text, text
    # Nothing identical is hidden now: no "0 identical" in the count.
    assert "0 identical" not in text, text
