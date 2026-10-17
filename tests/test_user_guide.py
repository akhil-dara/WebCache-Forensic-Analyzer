"""The user guide, inside the application.

There was no documentation in the tool at all: Help held About, the
shortcuts and the badge legend, and nothing said what any screen is for
or how it works. The guide covers every screen, and each screen opens it
at its own section from a button in its header.
"""
from PySide6.QtCore import Qt

from webcache.shell import user_guide
from webcache.shell.main_window import NAV_SECTIONS


def _nav_keys():
    return [key for _s, items in NAV_SECTIONS for key, *_rest in items]


def test_every_screen_has_its_own_section():
    keys = {t.key for t in user_guide.TOPICS}
    missing = [k for k in _nav_keys() if k not in keys]
    assert missing == []


def test_the_guide_also_covers_the_work_that_spans_screens():
    titles = [t.title for t in user_guide.TOPICS]
    for needed in ("Getting started", "Filtering, sorting and columns",
                   "A record in full", "Tags and comments",
                   "Exports and file formats", "Evidence handling",
                   "Basis badges and Origin", "Keyboard shortcuts"):
        assert needed in titles, needed


def test_every_section_says_something():
    for topic in user_guide.TOPICS:
        assert len(topic.html) > 200, topic.key


def test_the_guide_names_no_other_product():
    """Checked by hash, so this file does not name them either: every
    word and word pair of the guide is hashed and compared."""
    import hashlib
    import re
    banned = {"d5a18304ad8cdc2b", "e6643136d0b0e9e3", "f177f01a816a6a24", "ff99650b45c074f1", "3b8e886d1720d0ab", "38f177320fdf6daf", "c83be91a8df8f339", "ff5fa623d6d9b88f"}
    words = re.findall(r"[a-z0-9-]+", " ".join(
        t.html for t in user_guide.TOPICS).lower())
    grams = set(words) | {" ".join(p) for p in zip(words, words[1:])}
    found = [g for g in grams
             if hashlib.sha256(g.encode()).hexdigest()[:16] in banned]
    assert found == []


def test_the_window_opens_at_a_screens_section(qtbot):
    window = user_guide.UserGuideWindow()
    qtbot.addWidget(window)
    window.show_topic("location")
    assert window.current_key() == "location"
    assert "Location" in window.page_text()


def test_help_menu_and_each_header_open_the_guide(qtbot):
    from webcache.shell import main_window as mw
    win = mw.MainWindow()
    qtbot.addWidget(win)
    assert win.help_guide_action.text().startswith("User guide")
    win.help_guide_action.trigger()
    assert win._guide_window.isVisible()
    win.go_to("history")
    view = win._built_widget("history")
    view.header.help_button.click()
    assert win._guide_window.current_key() == "history"


def test_topics_are_grouped_like_the_sidebar(qtbot):
    window = user_guide.UserGuideWindow()
    qtbot.addWidget(window)
    groups = window.group_titles()
    assert groups[:2] == ["START HERE", "USER ACTIVITY"]
    assert "HOW TO" in groups
    # Every topic is reachable, and a heading cannot be selected.
    assert window.show_topic("tagged")
    heading = window.topic_list.item(0)
    assert not heading.flags() & Qt.ItemIsSelectable


def test_search_hides_groups_with_no_match(qtbot):
    window = user_guide.UserGuideWindow()
    qtbot.addWidget(window)
    window.search_box.setText("beacon")
    shown = [window.topic_list.item(i).text()
             for i in range(window.topic_list.count())
             if not window.topic_list.item(i).isHidden()]
    assert "Findings" in shown and "Cookies & HSTS" not in shown
    assert "ARTIFACTS" not in shown


def test_a_screen_topic_opens_its_screen(qtbot):
    window = user_guide.UserGuideWindow()
    qtbot.addWidget(window)
    window.show_topic("timeline")
    with qtbot.waitSignal(window.openScreenRequested) as blocker:
        window.open_screen_button.click()
    assert blocker.args == ["timeline"]
    window.show_topic("filtering")
    assert window.open_screen_button.isHidden()


def test_previous_and_next_walk_the_topics(qtbot):
    window = user_guide.UserGuideWindow()
    qtbot.addWidget(window)
    window.show_topic("history")
    window.next_button.click()
    assert window.current_key() == "downloads"
    window.previous_button.click()
    assert window.current_key() == "history"


def test_open_this_screen_navigates_the_window(qtbot):
    from webcache.shell import main_window as mw
    win = mw.MainWindow()
    qtbot.addWidget(win)
    guide = win.show_user_guide("domains")
    guide.openScreenRequested.emit("domains")
    assert win._current == "domains" or not win._ever_loaded
