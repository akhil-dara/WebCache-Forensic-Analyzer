"""History opens on what an examiner reads first: when, how often, where.
Sparse columns (Copies, Same visit as) come after and stay narrow, and
spare width goes to the grid, not the details pane."""
from webcache.views.history import HistoryView


def test_the_first_columns_are_when_visits_and_address(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    keys = [c.key for c in v.COLUMNS]
    assert keys[:4] == ["AccessedUtc", "AccessedLocal", "VisitCount", "CleanUrl"]


def test_sparse_columns_are_narrow(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    width = {c.key: c.width for c in v.COLUMNS}
    assert width["Copies"] <= 110 and width["SameVisit"] <= 220


def test_spare_width_goes_to_the_grid_not_the_pane(qtbot):
    v = HistoryView()
    qtbot.addWidget(v)
    split = v._details_split
    assert split.widget(1) is not None
    v.resize(1300, 800); v.show(); qtbot.waitExposed(v)
    pane_before = split.sizes()[1]
    v.resize(1800, 800); qtbot.wait(50)
    assert split.sizes()[1] == pane_before
