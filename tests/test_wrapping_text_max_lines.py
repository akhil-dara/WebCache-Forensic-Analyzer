"""A WrappingText given a line ceiling stops growing there and scrolls
the rest, whole; without one it grows to its content as before."""
from webcache.widgets.wrapping_text import WrappingText


def test_a_line_ceiling_caps_the_height_and_scrolls_the_rest(qtbot):
    text = "https://example.test/" + "x" * 2000
    w = WrappingText(text, max_lines=4)
    qtbot.addWidget(w)
    w.resize(200, 100)
    w.show()
    line = w.fontMetrics().lineSpacing()
    qtbot.waitUntil(lambda: w.verticalScrollBar().maximum() > 0, timeout=1000)
    assert w.height() <= 4 * line + 2 * w.frameWidth() + 4
    assert w.full_text() == text


def test_without_a_ceiling_it_grows_to_its_content(qtbot):
    w = WrappingText("https://example.test/" + "x" * 600)
    qtbot.addWidget(w)
    w.resize(200, 100)
    w.show()
    line = w.fontMetrics().lineSpacing()
    qtbot.waitUntil(lambda: w.height() > 4 * line, timeout=1000)
