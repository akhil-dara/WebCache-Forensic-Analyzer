"""The grid's main text column takes the width nothing else is using.

Seen on a real exhibit's Findings at 1,536 px: the URL column was 475 px
and the 760 px to its right were empty, so every URL wrapped to six lines,
was cut with a "+10 more lines" marker, and three rows filled the screen.
A column's declared width is its FLOOR; the first URL or path column (or,
failing one, a wide text column) grows into the rest of the viewport,
and shrinks back to its floor -- never below it -- when the window does.
"""
from webcache.widgets.column_spec import Column
from webcache.widgets.records_table import RecordsTable


def _columns():
    return [Column("When", "When", 150, kind="time"),
            Column("Url", "URL", 300, kind="url"),
            Column("Count", "Count", 80, kind="num")]


def _rows():
    return [{"When": None, "Url": "https://example.test/%d" % i, "Count": i}
            for i in range(20)]


def _table(qtbot, width):
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records(_columns(), _rows())
    t.resize(width, 400)
    t.show()
    qtbot.waitExposed(t)
    qtbot.wait(20)
    return t


def _used(t):
    header = t.horizontalHeader()
    return sum(header.sectionSize(i) for i in range(header.count())
               if not header.isSectionHidden(i))


def test_the_url_column_takes_the_spare_width(qtbot):
    t = _table(qtbot, 1200)
    header = t.horizontalHeader()
    assert header.sectionSize(1) > 600
    spare = t.viewport().width() - _used(t)
    assert 0 <= spare <= 4, "the grid fills its width, without overflowing"
    assert t.horizontalScrollBar().maximum() == 0


def test_it_shrinks_back_to_its_floor_and_never_below(qtbot):
    t = _table(qtbot, 1200)
    t.resize(500, 400)
    qtbot.wait(20)
    assert t.horizontalHeader().sectionSize(1) == 300
    t.resize(1400, 400)
    qtbot.wait(20)
    assert t.horizontalHeader().sectionSize(1) > 800


def test_other_columns_keep_their_declared_widths(qtbot):
    t = _table(qtbot, 1200)
    header = t.horizontalHeader()
    # Their declared width, or their heading's if that is wider (the
    # heading floor, column-fit rule) -- never the spare.
    assert header.sectionSize(0) < 200
    assert header.sectionSize(2) < 120


def test_a_grid_with_no_url_or_wide_text_column_is_left_alone(qtbot):
    t = RecordsTable()
    qtbot.addWidget(t)
    t.set_records([Column("A", "A", 120, kind="num"),
                   Column("B", "B", 120, kind="num")],
                  [{"A": 1, "B": 2}])
    t.resize(1000, 300)
    t.show()
    qtbot.waitExposed(t)
    assert t.horizontalHeader().sectionSize(0) == 120
    assert t.horizontalHeader().sectionSize(1) == 120
