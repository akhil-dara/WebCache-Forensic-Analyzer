"""The Keyboard shortcuts page is a real two-column table: every
description starts at one x, both columns are selectable, and Copy still
yields "keys<TAB>description" lines."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel

from webcache.shell import help_texts
from webcache.shell.main_window import MainWindow
from tests.test_literal_tooltips import shown


@pytest.fixture
def dialog(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    d = w._show_help("Keyboard shortcuts", w.help_shortcuts_action.data())
    qtbot.addWidget(d)
    return d


def _label_for(dialog, text):
    hits = [l for l in dialog.findChildren(QLabel) if l.text() == text]
    return hits[0] if hits else None


def test_every_description_starts_at_the_same_x(dialog):
    xs = set()
    for _keys, desc in help_texts.SHORTCUTS:
        label = _label_for(dialog, desc)
        assert label is not None, desc
        xs.add(label.mapTo(dialog, label.rect().topLeft()).x())
    assert len(xs) == 1


def test_both_columns_are_selectable(dialog):
    for keys, desc in help_texts.SHORTCUTS:
        for text in (keys, desc):
            label = _label_for(dialog, text)
            assert label is not None, text
            assert label.textInteractionFlags() & Qt.TextSelectableByMouse


def test_copy_yields_tab_separated_lines(dialog):
    dialog.copy_button.click()
    text = QGuiApplication.clipboard().text()
    assert text.splitlines() == ["%s\t%s" % kv for kv in help_texts.SHORTCUTS]


# --- the view keys are shown where the views are -----------------------------

def test_each_of_the_first_nine_views_names_its_key_in_its_tooltip(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    for i, key in enumerate(w.nav_keys, start=1):
        tip = shown(w.sidebar._rows[key].toolTip())
        if i <= 9:
            assert tip.endswith("Ctrl+%d" % i), (key, tip)
        else:
            assert "Ctrl+" not in tip, (key, tip)
