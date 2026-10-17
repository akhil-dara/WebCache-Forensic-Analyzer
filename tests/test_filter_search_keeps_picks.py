"""Searching a column's value list.

Measured on a real exhibit's Address column: a search for one site
showed 11 of 523 values and OK applied no filter at all, because the 512
values the search hid were still ticked; and "None" during a search
cleared only the values on show, so two values picked under two searches
became a filter keeping 513.

Untouched, a search selects exactly its matches. Once the examiner ticks,
unticks, or presses All or None, those picks are kept across every later
search, and the status line says how many ticked values a search hides.
"""
from PySide6.QtCore import Qt

from tests.test_filter_popup import popup  # noqa: F401 (fixture)


def _search(p, text):
    p.search_box.setText(text)
    p._apply_value_search()


def _tick_shown(p, label_part, on=True):
    """Tick a shown value as a click does: through the model's setData."""
    vm = p.values_list.value_model
    for row, i in enumerate(vm.rows):
        if label_part in vm.labels[i]:
            vm.setData(vm.index(row), Qt.Checked if on else Qt.Unchecked,
                       Qt.CheckStateRole)
            return
    raise AssertionError(label_part)


def test_ok_after_a_search_keeps_only_what_the_search_shows(popup):
    _search(popup, "live")
    assert popup.chosen_values() == {"login.live.com"}


def test_refining_the_search_narrows_again(popup):
    _search(popup, "o")
    _search(popup, "outlook")
    assert popup.chosen_values() == {"outlook.office.com"}


def test_clearing_an_untouched_search_restores_everything(popup):
    _search(popup, "live")
    _search(popup, "")
    assert popup.chosen_values() is None


def test_picks_made_under_two_searches_are_both_kept(popup):
    _search(popup, "o")
    popup.select_none()
    _tick_shown(popup, "outlook")
    _search(popup, "bing")
    _tick_shown(popup, "bing")
    assert popup.chosen_values() == {"outlook.office.com", "bing.com"}
    _search(popup, "")
    vm = popup.values_list.value_model
    ticked = {vm.values[i] for i in range(len(vm.values)) if vm.checked[i]}
    assert ticked == {"outlook.office.com", "bing.com"}


def test_the_status_counts_ticked_values_a_search_hides(popup):
    _search(popup, "o")
    popup.select_none()
    _tick_shown(popup, "outlook")
    _search(popup, "bing")
    assert popup.selection_text() == (
        "1 of 8 values ticked — 1 hidden by the search")
    _tick_shown(popup, "bing")
    _search(popup, "")
    assert popup.selection_text() == "2 of 8 values ticked"
