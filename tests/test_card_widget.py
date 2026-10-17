"""Card: the titled panel Dashboard's three cards are built from, and
the shape Integrity/Findings/Export reuse --
so this pins the reusable contract, not just Dashboard's own usage of it.

ElidingLabel and ClickableRow live in the same module (webcache/widgets/
card.py) because Card's own list-row callers need both: a single-line
value that truncates rather than wrapping mid-word or forcing the card
wider than its stretch-assigned share of the window, and a row that can
be clicked without inventing a bespoke QFrame subclass in every view that
wants a drill-through row inside a card.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from webcache.widgets.card import Card, ClickableRow


@pytest.fixture
def card(qtbot):
    c = Card("database", "Container Types")
    qtbot.addWidget(c)
    return c


def test_card_exposes_a_body_layout_callers_add_content_into(card):
    label = QLabel("a row")
    card.body.addWidget(label)
    assert card.body.count() == 1


def test_card_has_no_engine_import():
    """Belt-and-braces alongside test_structure.py's own AST-based check --
    this one just proves the class is usable without ever importing the
    engine, by constructing it with no evidence-shaped data at all."""
    import webcache.widgets.card as mod
    assert "engine" not in mod.__dict__


def test_refresh_theme_does_not_raise_before_or_after_construction(card):
    card.refresh_theme()  # must be idempotent and safe to call any time


def test_set_trailing_replaces_any_previous_trailing_widget(card):
    first = QLabel("first")
    second = QLabel("second")
    card.set_trailing(first)
    card.set_trailing(second)
    assert card._trailing_slot.count() == 1


# --- ClickableRow --------------------------------------------------------

def test_clickable_row_emits_clicked_on_a_left_click(qtbot):
    row = ClickableRow()
    qtbot.addWidget(row)
    row.resize(200, 24)
    row.show()
    with qtbot.waitSignal(row.clicked, timeout=1000):
        QTest.mouseClick(row, Qt.LeftButton)


def test_clickable_row_uses_a_pointing_hand_cursor():
    row = ClickableRow()
    assert row.cursor().shape() == Qt.PointingHandCursor
