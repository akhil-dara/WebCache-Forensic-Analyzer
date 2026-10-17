"""CookiesView: Cookies, HSTS pins, and cached TLS certificates -- three
structurally different record sets sharing one segmented switcher, built
entirely on RecordsView (test_records_view.py already proves the base
class's own generic contract; this file proves only what CookiesView
itself declares: its three RecordSets' columns, that no quick filters
means no chip row, and its header/empty-state text), against rows shaped
the way evidence_loader.cookie_rows_from_parser()/hsts_rows_from_parser()/
cert_rows_from_parser() actually produce them (see
test_evidence_loader_cookies.py for that shape's own tests).
"""
import datetime

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from webcache.views.cookies import (CERT_COLUMNS, COOKIE_COLUMNS,
                                    HSTS_COLUMNS, CookiesView)


def _cookie_row(i):
    return {"Domain": "example%d.com" % i, "Name": "c%d" % i, "Value": "v",
           "Path": "/",
           "Expires": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
           "LastModified": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)}


def _hsts_row(i, **overrides):
    base = {"Domain": "example%d.com" % i, "Corroborated": "yes",
           "Significance": "x", "HostAttribution": "y",
           "LastTimeUsed": None, "Expires": "never",
           "IncludeSubdomains": "no"}
    base.update(overrides)
    return base


def _cert_row(i):
    return {"HostPort": "example%d.com:443" % i, "IsCertificate": True,
           "Thumbprint": "aa", "BlobSize": 10, "ModifiedTime": None}


# --- columns -------------------------------------------------------------

def test_cookie_columns_match_the_spec():
    keys = [c.key for c in COOKIE_COLUMNS]
    assert keys == ["Domain", "Name", "Value", "Path", "Expires",
                    "LastModified", "IsSecure"]


def test_hsts_columns_match_the_spec():
    keys = [c.key for c in HSTS_COLUMNS]
    assert keys == ["Domain", "Corroborated", "Significance", "HostAttribution",
                    "LastTimeUsed", "Expires", "IncludeSubdomains"]


def test_cert_columns_match_the_spec():
    keys = [c.key for c in CERT_COLUMNS]
    assert keys == ["HostPort", "IsCertificate", "Thumbprint", "BlobSize",
                    "ModifiedTime"]


def test_cookie_domain_badges_the_raw_reversed_column_not_the_cell_value():
    """The cell shows cookie_entries' unreversed, human-readable Domain;
    the field= badge names RDomain, the raw column as actually stored --
    see evidence_loader.cookie_rows_from_parser's own docstring."""
    col = next(c for c in COOKIE_COLUMNS if c.key == "Domain")
    assert col.field == "RDomain"


def test_hsts_domain_has_no_badge_unlike_cookies_domain():
    col = next(c for c in HSTS_COLUMNS if c.key == "Domain")
    assert col.field is None


def test_the_secure_column_has_no_badge_with_no_provenance_entry():
    """Secure declared field="IsSecure", absent from evidence_
    model.FIELD_PROVENANCE, so records_view.py's badge wiring defaulted it
    through basis_of() to DERIVED -- a hover told an examiner it was
    "computed by this tool using documented, reproducible arithmetic",
    with no citation, for a value this codebase has no verified research
    citation to attach. field=None is the established, honest degradation
    (see the HSTS Domain case just above): no badge guessed."""
    from webcache.engine import evidence_model
    assert "IsSecure" not in evidence_model.FIELD_PROVENANCE
    col = next(c for c in COOKIE_COLUMNS if c.key == "IsSecure")
    assert col.field is None


def test_no_column_is_ever_a_drill_through_link():
    """Unlike Containers' Name column, none of these three segments points
    at a more detailed view elsewhere in this port -- see cookies.py's own
    module docstring."""
    for cols in (COOKIE_COLUMNS, HSTS_COLUMNS, CERT_COLUMNS):
        assert all(not c.is_link for c in cols)


# --- the view itself -----------------------------------------------------

def test_starts_on_the_cookies_segment(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    v.set_records_for("cookies", [_cookie_row(1)])
    keys = [c.key for c in v.table.model().columns]
    assert "Value" in keys  # a cookies-only column
    assert "Significance" not in keys


def test_declares_three_named_segments(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    assert set(v._switcher_buttons.keys()) == {"cookies", "hsts", "certs"}


def test_set_records_for_populates_the_named_segment_only(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    v.set_records_for("cookies", [_cookie_row(1), _cookie_row(2)])
    assert v.table.model().rowCount() == 2
    v.set_records_for("hsts", [_hsts_row(1)])
    # Still showing cookies -- the hsts rows landed but are not active yet.
    assert v.table.model().rowCount() == 2


def test_switching_segments_swaps_columns_and_rows(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    v.set_records_for("cookies", [_cookie_row(1)])
    v.set_records_for("hsts", [_hsts_row(1), _hsts_row(2)])
    v._switch_segment("hsts")
    assert v.table.model().rowCount() == 2
    assert any(c.key == "Significance" for c in v.table.model().columns)


def test_switching_segments_clears_the_filter_box(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    v.set_records_for("cookies", [_cookie_row(i) for i in range(5)])
    QTest.keyClicks(v.filter_box, "example1")
    v._switch_segment("certs")
    assert v.filter_box.text() == ""


def test_segment_button_label_carries_the_count(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    v.set_records_for("certs", [_cert_row(i) for i in range(7)])
    assert "7" in v._switcher_buttons["certs"].text()


def test_an_hsts_pin_never_used_is_not_a_crash_and_reads_as_blank(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    v.set_records_for("hsts", [_hsts_row(1, LastTimeUsed=None)])
    v._switch_segment("hsts")
    assert v.table.model().row_at(0)["LastTimeUsed"] is None


def test_ctrl_f_focuses_the_filter_box(qtbot):
    v = CookiesView()
    v.set_records_for("cookies", [_cookie_row(1)])
    qtbot.addWidget(v)
    v.resize(900, 600)
    v.show()
    qtbot.waitExposed(v)
    v.activateWindow()
    qtbot.wait(50)
    v.table.setFocus()
    QTest.keyClick(v, Qt.Key_F, Qt.ControlModifier)
    assert v.filter_box.hasFocus()


def test_typing_in_the_filter_box_narrows_the_active_segment(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    v.set_records_for("cookies", [_cookie_row(i) for i in range(50)])
    QTest.keyClicks(v.filter_box, "example1")
    qtbot.waitUntil(lambda: v.table.model().rowCount() < 50, timeout=3000)


def test_zero_records_in_a_segment_reads_as_a_genuine_empty_state(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    v.set_records_for("certs", [])
    v._switch_segment("certs")
    assert v.table.showing_genuine_empty_state() is True
    assert "Clear filters" not in v.count_label.text()


def test_each_segments_empty_text_names_itself(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    v.set_records_for("cookies", [])
    cookies_text = v.table.empty_state_text()
    v._switch_segment("hsts")
    v.set_records_for("hsts", [])
    hsts_text = v.table.empty_state_text()
    assert cookies_text != hsts_text
    assert "cookie" in cookies_text.lower()
    assert "hsts" in hsts_text.lower()


def test_an_emptied_filter_offers_a_way_back(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    v.set_records_for("cookies", [_cookie_row(i) for i in range(20)])
    QTest.keyClicks(v.filter_box, "zzzz-nothing-matches")
    qtbot.waitUntil(lambda: v.table.model().rowCount() == 0, timeout=3000)
    assert "Clear filters" in v.table.empty_state_text()
    v.clear_all_filters()
    assert v.table.model().rowCount() == 20


def test_header_and_caveat_are_reachable(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    assert v.header is not None
    v.set_caveat("An HSTS pin proves a TLS connection, not that a page was viewed.")
    assert v.caveat is not None
