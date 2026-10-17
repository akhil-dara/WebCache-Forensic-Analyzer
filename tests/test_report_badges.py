"""The offline report's Timeline badge counts the same inputs its Timeline
pages are built from -- never a sidebar figure still waiting on a
background rebuild (an export taken then said 467 dated records beside
pages holding 2,053)."""
import types

from webcache.shell import package_snapshot, timeline_loader


class _Sidebar:
    def __init__(self, counts):
        self.counts = counts

    def count_of(self, key):
        return self.counts.get(key)


def test_the_timeline_badge_is_counted_from_the_report_inputs(monkeypatch):
    monkeypatch.setattr(timeline_loader, "dated_record_count",
                        lambda inputs: 2053)
    window = types.SimpleNamespace(
        sidebar=_Sidebar({"timeline": ("467", "dated records"),
                          "history": ("392", "History records")}),
        _timeline_inputs=object())
    assert package_snapshot.badge_for(window, "timeline") == (
        "2,053", "dated records")
    # Every other view keeps the sidebar's own words.
    assert package_snapshot.badge_for(window, "history") == (
        "392", "History records")


def test_no_inputs_falls_back_to_the_sidebar():
    window = types.SimpleNamespace(
        sidebar=_Sidebar({"timeline": ("467", "dated records")}),
        _timeline_inputs=None)
    assert package_snapshot.badge_for(window, "timeline") == (
        "467", "dated records")
