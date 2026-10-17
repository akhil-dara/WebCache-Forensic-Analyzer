""""IOC Matches (0)" before any watchlist was scanned is not "scanned and
found nothing": it says no watchlist has been scanned, and how to run one.
After a scan, the usual sentence returns."""
from webcache.views.iocs import FindingsView


def _view(qtbot):
    view = FindingsView()
    qtbot.addWidget(view)
    view.set_records_for("ioc_hits", [])
    return view


def test_no_watchlist_scanned_yet_says_so_and_how(qtbot):
    view = _view(qtbot)
    text = view.table.empty_state_text()
    assert "no watchlist has been scanned" in text.lower(), text
    assert "Scan" in text


def test_after_a_scan_the_usual_sentence_returns(qtbot):
    view = _view(qtbot)
    view.watchlist_box.setText("example.test")
    view._emit_scan()
    view.set_records_for("ioc_hits", [])
    text = view.table.empty_state_text()
    assert "no watchlist has been scanned" not in text.lower(), text
    assert "watchlist term matched" in text


def test_the_offline_report_says_the_same(qtbot):
    from webcache.shell import package_snapshot
    view = _view(qtbot)
    segs = package_snapshot.segments_of(view, "")
    ioc = next(s for s in segs if s.key == "ioc_hits")
    assert "no watchlist has been scanned" in ioc.empty_text.lower()
