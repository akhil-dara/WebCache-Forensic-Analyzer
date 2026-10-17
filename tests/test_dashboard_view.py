"""DashboardView: the five stat chips, three cards, and the promise its
own caveat makes -- "every number here is reproduced in the view it came
from" (main_window.NAV_SECTIONS). Every test that checks a figure also
checks where clicking it goes, because a summary number with nowhere to
click is exactly the failure this project has already been bitten by
once (see records_view.py's own module docstring).

DashboardView takes fully-shaped data (dashboard_data.compute_dashboard_
stats()'s own dict shape) via set_data() -- it never imports the engine
itself (test_structure.py's test_no_view_imports_another_view covers the
cross-view rule; this view simply never needs webcache.engine at all,
the same discipline widgets/ is held to even though a view technically
may import it).
"""
from collections import Counter

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from webcache.views.dashboard import DashboardView


def _stats(**overrides):
    base = {
        "total_records": 3000,
        "table_count": 42,
        "container_count": 7,
        "inprivate_count": 12,
        "total_file_size": 3 * 1024 * 1024,  # 3.0 MB
        "container_types": Counter({"History": 2000, "Cookies": 1000}),
        "top_domains": Counter({"example.com": 40, "other.example": 10}),
        "db_path": "C:/case/WebCacheV01.dat",
        "db_file_size": 5 * 1024 * 1024,
        "recovered_count": 0,
    }
    base.update(overrides)
    return base


@pytest.fixture
def view(qtbot):
    v = DashboardView()
    qtbot.addWidget(v)
    v.resize(1280, 800)
    v.show()
    return v


# --- construction / no-evidence state -----------------------------------

def test_header_uses_the_dashboard_nav_icon(view):
    """"grid" is NAV_ICONS["dashboard"] (sidebar.py), so the sidebar
    row and the view header agree on which glyph means "Dashboard"."""
    assert view.header._icon_name == "grid"


def test_starts_with_no_fabricated_zero_figures(view):
    """Before set_data() is ever called (mirrors MainWindow construction,
    before any exhibit is open) every chip must read '—', never '0' --
    see StatChip's own docstring for the identical discipline one layer
    down."""
    for chip in (view.chip_records, view.chip_tables, view.chip_containers,
                view.chip_inprivate, view.chip_cache_size):
        assert chip.value() == "—"


def test_starts_with_a_no_evidence_subtitle_not_a_records_loaded_claim(view):
    text = view.header._subtitle.text().lower()
    assert "no evidence" in text


def test_all_five_chips_exist_with_their_own_attribute_names(view):
    for chip in (view.chip_records, view.chip_tables, view.chip_containers,
                view.chip_inprivate, view.chip_cache_size):
        assert chip is not None


def test_all_three_cards_exist(view):
    assert view.card_container_types is not None
    assert view.card_top_domains is not None
    assert view.card_database_info is not None


def test_caveat_is_set_via_set_caveat(view):
    view.set_caveat("Headline figures only.")
    assert view.caveat._text.text() == "Headline figures only."


def test_refresh_theme_does_not_raise_before_any_data(view):
    view.refresh_theme()


# --- set_data(None): back to the honest empty state ----------------------

def test_set_data_none_shows_dashes_again(view):
    view.set_data(_stats())
    view.set_data(None)
    assert view.chip_records.value() == "—"


# --- set_data(stats): the five chips --------------------------------------

def test_chip_values_reflect_the_given_stats(view):
    view.set_data(_stats())
    assert view.chip_records.value() == "3,000"
    assert view.chip_tables.value() == "42"
    assert view.chip_containers.value() == "7"
    assert view.chip_inprivate.value() == "12"
    assert view.chip_cache_size.value() == "3.0 MB"


# --- drill-through: every figure goes somewhere real ----------------------

@pytest.mark.parametrize("chip_attr,target", [
    ("chip_records", "browser"),
    ("chip_tables", "browser"),
    ("chip_containers", "containers"),
    ("chip_inprivate", "history"),
    ("chip_cache_size", "downloads"),
])
def test_each_chip_drills_to_its_reproducing_view(view, qtbot, chip_attr, target):
    view.set_data(_stats())
    chip = getattr(view, chip_attr)
    with qtbot.waitSignal(view.drillRequested, timeout=1000) as sig:
        QTest.mouseClick(chip, Qt.LeftButton)
    assert sig.args[0] == target


# --- Container Types card --------------------------------------------------

def test_container_types_card_has_one_row_per_type_sorted_by_count(view):
    view.set_data(_stats())
    assert [r.container_type for r in view._container_type_rows] == \
        ["History", "Cookies"]


def test_container_types_row_click_drills_to_containers(view, qtbot):
    view.set_data(_stats())
    row = view._container_type_rows[0]
    with qtbot.waitSignal(view.drillRequested, timeout=1000) as sig:
        QTest.mouseClick(row, Qt.LeftButton)
    assert sig.args[0] == "containers"


def test_container_types_percentages_sum_close_to_a_hundred(view):
    view.set_data(_stats())
    total_pct = sum(r.pct for r in view._container_type_rows)
    assert 99.0 <= total_pct <= 100.01


def test_container_types_percentages_sum_to_exactly_a_hundred(view):
    """546/46/10/8 of 610 independently
    rounds to 90/8/2/1 -- 101, not 100. Largest-remainder apportionment
    gives 89/8/2/1, which sums to exactly 100."""
    view.set_data(_stats(container_types=Counter(
        {"History": 546, "Cookies": 46, "Content": 10, "Downloads": 8})))
    pcts = [r.pct for r in view._container_type_rows]
    assert pcts == [89, 8, 2, 1]
    assert sum(pcts) == 100


# --- Top 10 Domains card ---------------------------------------------------

def test_top_domains_card_is_sorted_by_count_and_capped_at_ten(view):
    many = Counter({"d%d.example" % i: (100 - i) for i in range(15)})
    view.set_data(_stats(top_domains=many))
    assert len(view._domain_rows) == 10
    assert view._domain_rows[0].domain == "d0.example"


def test_more_than_ten_domains_offers_all_of_them(view, qtbot):
    """A top ten never reads as the whole list: the card says how many
    domains there are and opens every one of them."""
    many = Counter({"d%d.example" % i: (100 - i) for i in range(15)})
    view.set_data(_stats(top_domains=many))
    more = view.all_domains_row
    assert more is not None
    # Added to a shown window: Qt shows it on the next event-loop turn.
    qtbot.waitUntil(lambda: more.isVisibleTo(view), timeout=1000)
    assert more.copy_row_text == "View all 15 domains"
    with qtbot.waitSignal(view.drillRequested, timeout=1000) as sig:
        QTest.mouseClick(more, Qt.LeftButton)
    assert sig.args[0] == "domains"


def test_ten_or_fewer_domains_need_no_more_row(view):
    view.set_data(_stats())
    assert view.all_domains_row is None


def test_domain_row_click_drills_to_domains(view, qtbot):
    view.set_data(_stats())
    row = view._domain_rows[0]
    with qtbot.waitSignal(view.drillRequested, timeout=1000) as sig:
        QTest.mouseClick(row, Qt.LeftButton)
    assert sig.args[0] == "domains"


# --- right-click Copy on a summary row --------------------

def test_container_type_row_right_click_offers_copy_of_the_count(view, qtbot):
    """The row's name/count/pct labels stay DECORATIVE (a mouse-selectable
    child would swallow the drill-through click), so the figure is
    reached through a right-click menu instead."""
    view.set_data(_stats())
    row = view._container_type_rows[0]
    menu = row.build_context_menu()
    copy_action = next(a for a in menu.actions()
                       if a.text().lower() == "copy")
    copy_action.trigger()
    assert QGuiApplication.clipboard().text() == format(row.count, ",")


def test_container_type_row_right_click_offers_copy_row(view, qtbot):
    view.set_data(_stats())
    row = view._container_type_rows[0]
    menu = row.build_context_menu()
    copy_row_action = next(a for a in menu.actions()
                          if a.text().lower() == "copy row")
    copy_row_action.trigger()
    clip = QGuiApplication.clipboard().text()
    assert row.container_type in clip
    assert format(row.count, ",") in clip


def test_container_type_row_left_click_still_drills_through(view, qtbot):
    view.set_data(_stats())
    row = view._container_type_rows[0]
    with qtbot.waitSignal(view.drillRequested, timeout=1000) as sig:
        QTest.mouseClick(row, Qt.LeftButton)
    assert sig.args[0] == "containers"


def test_domain_row_right_click_offers_copy_and_copy_row(view, qtbot):
    view.set_data(_stats())
    row = view._domain_rows[0]
    menu = row.build_context_menu()
    copy_action = next(a for a in menu.actions()
                       if a.text().lower() == "copy")
    copy_action.trigger()
    assert QGuiApplication.clipboard().text() == format(row.count, ",")

    copy_row_action = next(a for a in menu.actions()
                          if a.text().lower() == "copy row")
    copy_row_action.trigger()
    clip = QGuiApplication.clipboard().text()
    assert row.domain in clip
    assert format(row.count, ",") in clip


def test_domain_row_left_click_still_drills_through(view, qtbot):
    view.set_data(_stats())
    row = view._domain_rows[0]
    with qtbot.waitSignal(view.drillRequested, timeout=1000) as sig:
        QTest.mouseClick(row, Qt.LeftButton)
    assert sig.args[0] == "domains"


# --- Database Info card ----------------------------------------------------

def test_database_info_shows_file_size_tables_containers(view):
    view.set_data(_stats())
    values = [v.text() for _l, v in view._db_info_rows]
    assert "WebCacheV01.dat" in values
    assert "5.0 MB" in values
    assert "42" in values
    assert "7" in values


def test_database_info_values_are_selectable(view):
    view.set_data(_stats())
    for _label, value_widget in view._db_info_rows:
        assert value_widget.textInteractionFlags() & Qt.TextSelectableByMouse


# --- the carved-records note -----------------------------------------------

def test_the_split_is_not_repeated_on_a_third_line(view):
    # the headline chips and the subtitle state the split; a note
    # line beneath them said it a third time, so there is none.
    view.set_data(_stats())
    assert not hasattr(view, "_note_label")
    assert not hasattr(view, "_note")


# --- theme repaint keeps whatever data was already on screen --------------

def test_refresh_theme_preserves_current_chip_values(view):
    view.set_data(_stats())
    view.refresh_theme()
    assert view.chip_records.value() == "3,000"


# --- Cache Size vs. Database Info's Size: an explicit distinction --------
#
# The chips show Cache Size 100.5 MB while Database Info shows Size 30.0 MB.
# Both are correct -- cached response bodies live in files on disk outside
# the .dat -- but side by side with no explanation it reads as an error.
# Neither number changes; only the UI has to say, explicitly, why they
# disagree.

def test_cache_size_chip_tooltip_names_it_as_separate_from_the_database_file(view):
    view.set_data(_stats())
    tip = view.chip_cache_size.toolTip().lower()
    assert "cached" in tip or "response bod" in tip
    assert ".dat" in tip or "database file" in tip


def test_database_info_size_row_tooltip_names_it_as_the_dat_file_itself(view):
    view.set_data(_stats())
    label_widget, value_widget = next(
        (l, v) for l, v in view._db_info_rows if l.text() == "Size")
    tip = (label_widget.toolTip() + " " + value_widget.toolTip()).lower()
    assert "cache size" in tip
    assert ".dat" in tip or "database file" in tip


def test_no_view_peer_imports():
    """Belt-and-braces alongside test_structure.py's own cross-view check:
    dashboard.py must never import another view module directly."""
    import pathlib
    text = pathlib.Path("webcache/views/dashboard.py").read_text(encoding="utf-8")
    for other in ("history", "file_access", "containers", "cookies", "recovery"):
        assert ("import %s" % other) not in text
        assert (".%s import" % other) not in text


# --- a zero InPrivate count says what it cannot show ----------------------

def test_a_zero_inprivate_count_does_not_read_as_no_private_browsing(view):
    """InPrivate entries are normally removed when the private session ends,
    and only Internet Explorer and legacy Edge write them here: 0 cannot
    show that no private browsing happened."""
    view.set_data(_stats(inprivate_count=0))
    tip = view.chip_inprivate.toolTip().lower()
    assert "session ends" in tip
    assert "does not show" in tip


def test_a_nonzero_count_keeps_the_recovered_caveat(view):
    view.set_data(_stats(inprivate_count=3))
    assert "recovered" in view.chip_inprivate.toolTip().lower()
