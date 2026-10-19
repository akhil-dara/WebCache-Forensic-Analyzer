"""DomainsView: one RecordSet, built on RecordsView the same way
ContainersView is (test_containers_view.py already proves the shape this
mirrors) -- against rows shaped the way domain_loader.domain_rows()
actually produces them (see test_domain_loader.py for that shape's own
tests).
"""
from webcache.views.domains import DomainsView


def _row(**overrides):
    base = {
        "Domain": "example.com", "Records": 10, "Carved": 2,
        "OnlyCarved": False, "FileSize": 4096,
        "FirstSeen": None, "LastSeen": None,
        "ContainerType": "History", "AccessCount": 3.5,
        "IsInPrivate": False,
    }
    base.update(overrides)
    return base


def make_rows(n):
    return [_row(Domain="host%d.example" % i, Records=i + 1) for i in range(n)]


# --- columns -----------------------------------------------------------

def test_columns_match_the_spec(qtbot):
    v = DomainsView()
    qtbot.addWidget(v)
    keys = [c.key for c in v.COLUMNS]
    assert keys == ["Domain", "Records", "Visits", "Carved", "OnlyCarved",
                    "FileSize",
                    "FirstSeen", "LastSeen", "ContainerType", "AccessCount",
                    "IsInPrivate"]


def test_carved_column_uses_the_carved_kind(qtbot):
    v = DomainsView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "Carved")
    assert col.kind == "carved"


def test_only_carved_column_uses_the_only_carved_kind(qtbot):
    v = DomainsView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "OnlyCarved")
    assert col.kind == "only_carved"


def test_container_type_column_uses_the_types_kind(qtbot):
    v = DomainsView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "ContainerType")
    assert col.kind == "types"


def test_file_size_column_uses_the_size_kind(qtbot):
    v = DomainsView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "FileSize")
    assert col.kind == "size"


def test_first_seen_and_last_seen_use_the_time_kind(qtbot):
    v = DomainsView()
    qtbot.addWidget(v)
    for key in ("FirstSeen", "LastSeen"):
        col = next(c for c in v.COLUMNS if c.key == key)
        assert col.kind == "time"


# --- a domain row selects itself and fills the records pane --------

def test_the_domain_column_selects_the_domain_in_place(qtbot):
    v = DomainsView()
    qtbot.addWidget(v)
    v.set_records(make_rows(3))
    col = next(c for c in v.COLUMNS if c.key == "Domain")
    assert col.is_link
    target = v.table.model().row_at(0)["Domain"]
    col.on_click({"Domain": target})
    assert v.selected_domain() == target


# --- the table itself ----------------------------------------------------

def test_the_table_shows_every_record(qtbot):
    v = DomainsView()
    v.set_records(make_rows(22))
    qtbot.addWidget(v)
    assert v.table.model().rowCount() == 22
    assert "22" in v.count_label.text()


def test_typing_in_the_filter_box_narrows_the_table(qtbot):
    from PySide6.QtTest import QTest

    v = DomainsView()
    v.set_records(make_rows(50))
    qtbot.addWidget(v)
    QTest.keyClicks(v.filter_box, "host1.")
    qtbot.waitUntil(lambda: v.table.model().rowCount() < 50, timeout=3000)


def test_no_quick_filters_means_no_chip_row(qtbot):
    v = DomainsView()
    qtbot.addWidget(v)
    assert v._quick_filters == []


def test_it_has_no_switcher_being_a_single_record_set(qtbot):
    v = DomainsView()
    qtbot.addWidget(v)
    assert v._switcher_buttons == {}


def test_header_and_caveat_are_reachable(qtbot):
    v = DomainsView()
    qtbot.addWidget(v)
    assert v.header is not None
    v.set_caveat("Grouped by host; one host can serve many unrelated services.")
    assert v.caveat is not None


# --- the "before a recovery scan" caveat: the note line, not a fake zero --

def test_a_note_before_any_scan_explains_the_carved_columns_are_not_yet_meaningful(qtbot):
    """Before Evidence > Recover deleted records has ever run, every row's
    Carved/OnlyCarved reads 0/False honestly -- but with EVERY row reading
    that way, the honest per-row zero risks being read as "no deleted
    records exist for any domain". The note line (RecordsView's own `note`
    mechanism, exactly like HistoryView's LIVE_ONLY_NOTE) is what says
    that plainly instead of leaving the table to imply it."""
    v = DomainsView()
    qtbot.addWidget(v)
    v.set_records(make_rows(5), note="From deleted/Deleted only cannot be "
                                     "populated yet -- no recovery scan has "
                                     "run for this exhibit.")
    text = v.line_text().lower()
    assert "no recovery scan" in text


def test_zero_records_because_none_exist_reads_as_a_genuine_empty_state(qtbot):
    v = DomainsView()
    v.set_records([])
    qtbot.addWidget(v)
    assert v.table.showing_genuine_empty_state() is True
