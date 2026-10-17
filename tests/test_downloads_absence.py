"""An empty Downloads list says what it can and cannot mean. This database
records only downloads made through Internet Explorer's or legacy Edge's
own download manager; "No Downloads in this exhibit" read as "the user
downloaded nothing" while History showed freshly downloaded files opened."""
from webcache.views import file_access


def _downloads_set():
    view = file_access.FileAccessView()
    return view, view._segments_by_key["downloads"]


def test_the_empty_text_limits_the_claim_to_this_database(qtbot):
    view, rs = _downloads_set()
    qtbot.addWidget(view)
    text = rs.empty_text.lower()
    assert "in this exhibit" not in text
    assert "other browsers" in text
    assert "file access" in text            # where opened downloads do appear


def test_a_zero_count_subtitle_says_the_same(qtbot):
    view, rs = _downloads_set()
    qtbot.addWidget(view)
    assert "other browsers" in rs.subtitle(0).lower()
    assert rs.subtitle(3).startswith("3 downloads")
