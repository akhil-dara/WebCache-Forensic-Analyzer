import datetime

import pytest
from PySide6.QtCore import QModelIndex, Qt

from webcache.provenance import CONTAINER_NOT_DETERMINABLE
from webcache.widgets.column_spec import Column
from webcache.widgets.record_model import (ROLE_IS_CARVED, ROLE_RAW,
                                            ROLE_ROW, RecordTableModel)
from tests.fixtures import FIXTURE_COLUMNS, make_rows
from tests.test_literal_tooltips import shown


def _find_row(model, predicate):
    return next(r for r in range(model.rowCount())
                if predicate(model.row_at(r)))


@pytest.fixture
def model(qtbot):
    return RecordTableModel(list(FIXTURE_COLUMNS), make_rows(2_000))


@pytest.fixture
def model_with_link_column(qtbot):
    """A model whose first column carries a real on_click, so the link
    styling path in RecordTableModel.data() is genuinely exercised rather
    than just declared. FIXTURE_COLUMNS' own CleanUrl column has no
    on_click, which is exactly why the earlier version of this test suite
    never noticed the link path could hide the carved/live distinction."""
    cols = list(FIXTURE_COLUMNS)
    cols[0] = Column("CleanUrl", "Address", 420, kind="url",
                      field="CleanUrl", on_click=lambda row: None)
    return RecordTableModel(cols, make_rows(2_000))


def test_dimensions_match_the_data(model):
    assert model.rowCount() == 2_000
    assert model.columnCount() == len(FIXTURE_COLUMNS)
    assert model.rowCount(model.index(0, 0)) == 0, "a table model has no children"


def test_display_role_is_text_and_raw_role_is_the_value(model):
    col = [c.key for c in FIXTURE_COLUMNS].index("AccessedUtc")
    ix = model.index(0, col)
    assert isinstance(model.data(ix, Qt.DisplayRole), str)
    raw = model.data(ix, ROLE_RAW)
    assert raw is None or isinstance(raw, datetime.datetime)


def test_row_role_returns_the_whole_record(model):
    row = model.data(model.index(0, 0), ROLE_ROW)
    assert isinstance(row, dict)
    assert "CleanUrl" in row


def test_header_shows_the_column_label(model):
    assert model.headerData(0, Qt.Horizontal, Qt.DisplayRole) == "Address"


def test_tooltip_is_the_untruncated_value(model):
    ix = model.index(0, 0)
    assert shown(model.data(ix, Qt.ToolTipRole)) == str(model.row_at(0)["CleanUrl"])


def test_filtering_changes_the_row_count(model, qtbot):
    """Filters are driven through the model, never through model.filter --
    the model wraps them so no caller can change the filter and forget to
    tell the view."""
    with qtbot.waitSignal(model.modelReset):
        model.set_text("nimbus")
    assert model.rowCount() < 2_000
    with qtbot.waitSignal(model.modelReset):
        model.set_text("")
    assert model.rowCount() == 2_000


def test_sorting_reorders_what_the_model_reports(model, qtbot):
    with qtbot.waitSignal(model.modelReset):
        model.sort_by("VisitCount", descending=False)
    col = [c.key for c in FIXTURE_COLUMNS].index("VisitCount")
    vals = [model.data(model.index(r, col), ROLE_RAW) for r in range(model.rowCount())]
    assert vals == sorted(vals)


def test_blank_cells_render_as_empty_string_not_None(model):
    col = [c.key for c in FIXTURE_COLUMNS].index("Title")
    texts = [model.data(model.index(r, col), Qt.DisplayRole)
             for r in range(200)]
    assert all(isinstance(t, str) for t in texts)
    assert "" in texts


def test_invalid_index_returns_None(model):
    assert model.data(QModelIndex(), Qt.DisplayRole) is None


# --- carved/live: never hideable, in any column, in any styling mode -----

@pytest.mark.parametrize("col_key", [c.key for c in FIXTURE_COLUMNS])
def test_carved_rows_are_visually_distinguishable(model, col_key):
    """Never hideable, in any mode, in any column -- now carried by the row
    tint and the origin label, not by amber text. Parametrized over
    every fixture column: the previous version of this test only ever
    checked column 0 (CleanUrl), which happened to be neither a link nor
    ever blank -- exactly the two cases where the unfixed model let the
    distinction disappear."""
    col_index = [c.key for c in FIXTURE_COLUMNS].index(col_key)
    carved = _find_row(model, lambda r: r["Origin"].startswith("Carved"))
    live = _find_row(model, lambda r: r["Origin"] == "Live record")
    assert (model.data(model.index(carved, col_index), Qt.BackgroundRole)
            != model.data(model.index(live, col_index), Qt.BackgroundRole))


def test_carved_is_distinguishable_in_a_link_column(model_with_link_column):
    """A carved cell in a link column must still read as a link -- and the
    row tint, not the text colour, still carries the carved fact."""
    m = model_with_link_column
    col_index = 0  # CleanUrl, now carrying on_click
    assert m.columns[col_index].is_link
    carved = _find_row(m, lambda r: r["Origin"].startswith("Carved"))
    live = _find_row(m, lambda r: r["Origin"] == "Live record")
    carved_fg = m.data(m.index(carved, col_index), Qt.ForegroundRole)
    live_fg = m.data(m.index(live, col_index), Qt.ForegroundRole)
    assert carved_fg == live_fg
    assert (m.data(m.index(carved, col_index), Qt.BackgroundRole)
            != m.data(m.index(live, col_index), Qt.BackgroundRole))


def test_carved_is_distinguishable_when_the_cell_is_blank(model):
    """A carved cell that happens to be blank still reads with the normal
    blank/muted text colour; the row tint carries the carved fact."""
    col_index = [c.key for c in FIXTURE_COLUMNS].index("Title")
    carved_blank = _find_row(
        model, lambda r: r["Origin"].startswith("Carved") and not r["Title"])
    live_blank = _find_row(
        model, lambda r: r["Origin"] == "Live record" and not r["Title"])
    carved_fg = model.data(model.index(carved_blank, col_index), Qt.ForegroundRole)
    live_fg = model.data(model.index(live_blank, col_index), Qt.ForegroundRole)
    assert carved_fg == live_fg
    assert (model.data(model.index(carved_blank, col_index), Qt.BackgroundRole)
            != model.data(model.index(live_blank, col_index), Qt.BackgroundRole))


def test_container_not_determinable_renders_as_real_text_not_a_blank_cell(qtbot):
    """The confirmed defect: a carved record with no resolvable container
    used to render as a blank cell -- indistinguishable from "the tool
    failed to read this field". recovery_loader.py now normalises that
    case to CONTAINER_NOT_DETERMINABLE, and that text must actually reach
    Qt.DisplayRole, not just live in the row dict."""
    row = dict(make_rows(1)[0], Origin="Carved (deleted/unflushed)",
              ContainerType=CONTAINER_NOT_DETERMINABLE)
    m = RecordTableModel(list(FIXTURE_COLUMNS), [row])
    col = [c.key for c in FIXTURE_COLUMNS].index("ContainerType")
    assert m.data(m.index(0, col), Qt.DisplayRole) == CONTAINER_NOT_DETERMINABLE


def test_container_not_determinable_is_styled_distinctly_from_a_real_container(qtbot):
    """Must never be confusable with a real container name -- a genuine
    ContainerType like "History" keeps the normal full carved colour;
    the sentinel gets the muted treatment instead."""
    real = dict(make_rows(1)[0], Origin="Carved (deleted/unflushed)",
               ContainerType="History")
    sentinel = dict(make_rows(1)[0], Origin="Carved (deleted/unflushed)",
                    ContainerType=CONTAINER_NOT_DETERMINABLE)
    m = RecordTableModel(list(FIXTURE_COLUMNS), [real, sentinel])
    col = [c.key for c in FIXTURE_COLUMNS].index("ContainerType")
    real_fg = m.data(m.index(0, col), Qt.ForegroundRole)
    sentinel_fg = m.data(m.index(1, col), Qt.ForegroundRole)
    assert sentinel_fg != real_fg


def test_container_not_determinable_gets_the_same_muted_treatment_as_a_blank_carved_cell(qtbot):
    """Not a new colour of its own -- the SAME muted "carved_blank" a
    genuinely blank carved cell already gets, so an examiner learns one
    visual rule ("muted amber means this cell carries less certainty")
    rather than a second one just for this column."""
    blank = dict(make_rows(1)[0], Origin="Carved (deleted/unflushed)",
                ContainerType="")
    sentinel = dict(make_rows(1)[0], Origin="Carved (deleted/unflushed)",
                    ContainerType=CONTAINER_NOT_DETERMINABLE)
    m = RecordTableModel(list(FIXTURE_COLUMNS), [blank, sentinel])
    col = [c.key for c in FIXTURE_COLUMNS].index("ContainerType")
    assert (m.data(m.index(0, col), Qt.ForegroundRole)
           == m.data(m.index(1, col), Qt.ForegroundRole))


def test_role_is_carved_is_a_non_colour_carrier_of_the_same_fact(model):
    """A view/delegate that wants a glyph or row decoration instead of (or
    in addition to) colour can read this role -- colour alone is not a
    guaranteed carrier: colour-vision deficiency, a greyscale screenshot,
    or a high-contrast theme can all erase a colour-only distinction."""
    carved = _find_row(model, lambda r: r["Origin"].startswith("Carved"))
    live = _find_row(model, lambda r: r["Origin"] == "Live record")
    assert model.data(model.index(carved, 0), ROLE_IS_CARVED) is True
    assert model.data(model.index(live, 0), ROLE_IS_CARVED) is False


# --- set_rows / refresh: the load-bearing recovery-scan path -------------

def test_set_rows_swaps_data_changes_count_and_emits_reset(model, qtbot):
    """set_rows is the documented path for merging carved records into an
    already-open view after a recovery scan -- a forensic path, not a
    convenience one. It must actually replace the rows, report the new
    count, and tell any attached view to repaint."""
    assert model.rowCount() == 2_000
    replacement = make_rows(50, seed=99)
    with qtbot.waitSignal(model.modelReset):
        model.set_rows(replacement)
    assert model.rowCount() == 50
    assert model.row_at(0)["CleanUrl"] == replacement[0]["CleanUrl"]


def test_refresh_republishes(model, qtbot):
    """refresh() is the escape hatch for a caller that mutated model.filter
    directly (against the warning in __init__) or otherwise needs a
    republish without changing the filter itself."""
    with qtbot.waitSignal(model.modelReset):
        model.refresh()
    assert model.rowCount() == 2_000


def test_sort_by_recovers_from_a_raising_filter(model, qtbot, monkeypatch):
    """Pins the fix for a real bug: sort_by used to bracket
    beginResetModel()/endResetModel() with no try/finally, so a raising
    RecordFilter.sort() left the model permanently stuck mid-reset -- a
    blank table with no visible error. Confirms the model survives a
    raising mutation and a subsequent normal one still works."""
    original_count = model.rowCount()

    def boom(key, descending=False):
        raise RuntimeError("simulated failure mid-sort")

    monkeypatch.setattr(model.filter, "sort", boom)
    with pytest.raises(RuntimeError):
        model.sort_by("VisitCount")
    # Not stuck in a permanent reset: the model still reports a sane count.
    assert model.rowCount() == original_count

    monkeypatch.undo()
    with qtbot.waitSignal(model.modelReset):
        model.sort_by("VisitCount", descending=True)
    assert model.rowCount() == original_count


def test_set_rows_recovers_from_a_raising_filter(model, qtbot, monkeypatch):
    """Same fix, same pin, for set_rows -- the method the review flagged as
    the more realistic trigger, since it is the one a recovery scan calls
    mid-session with data that can legitimately be malformed."""
    original_count = model.rowCount()

    def boom(rows):
        raise ValueError("simulated malformed recovery-scan rows")

    monkeypatch.setattr(model.filter, "set_rows", boom)
    with pytest.raises(ValueError):
        model.set_rows(make_rows(10))
    assert model.rowCount() == original_count

    monkeypatch.undo()
    with qtbot.waitSignal(model.modelReset):
        model.set_rows(make_rows(75, seed=5))
    assert model.rowCount() == 75
