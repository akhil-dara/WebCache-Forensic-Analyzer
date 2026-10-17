"""History's "Has search terms" chip at zero says what that zero covers.

On a real exhibit the chip read "· 0" and nothing else, which reads as
"this person never searched". The database holds no Chromium-based Edge
activity at all, so a zero here says nothing about searches made there;
the chip states that scope fact (never advice)."""
from webcache.views.history import HistoryView
from tests.fixtures import make_rows


def test_the_zero_chip_states_the_scope_of_the_zero(qtbot):
    rows = make_rows(5)
    for r in rows:
        r["SearchTerms"] = ""
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records(rows)
    tip = v.chip_search_terms.toolTip()
    assert "Chromium-based Edge (v79+)" in tip
    assert "0 of 5" in tip or "show nothing" in tip


def test_a_chip_with_matches_carries_no_scope_note(qtbot):
    rows = make_rows(5)
    rows[0]["SearchTerms"] = "weather"
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records(rows)
    assert "Chromium" not in v.chip_search_terms.toolTip()
