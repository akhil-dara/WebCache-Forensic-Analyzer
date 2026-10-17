"""The Search header subtitle is the count and
the live/recovered split only; what Row # means folds behind the note
line with the scope note, whole and one click away."""
from webcache.views.search import SearchView, _search_subtitle


def test_the_subtitle_is_the_count_and_the_split_only():
    text = _search_subtitle(3, recovered=1)
    assert text == ("3 hits: 2 in the database's own tables and columns, "
                    "1 in recovered records (the fields read from the "
                    "carved bytes).")


def test_what_row_means_is_in_the_folded_note(qtbot):
    view = SearchView()
    qtbot.addWidget(view)
    note = view.scope_note.text()
    assert "WITHIN its table" in note
    assert "Deleted Records" in note
