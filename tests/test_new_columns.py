"""Three values the loaders now decide, and the columns that show them.

A row key nothing declares as a column is reachable by a detail surface
and by nothing else. These three earn a column outright, because each is
a fact an examiner has to weigh while READING THE TABLE, not after
opening one row:

  Confidence (Downloads). Every other carved or derived surface in this
  application grades itself -- a carved record's Confidence, an
  indicator's Conf, a URL's health. A decoded download blob already
  carries a grade, decided by how many of the four fields were actually
  recovered, and Downloads was the one surface that showed a decode
  without saying how much of it was real.

  Secure (Cookies). Bit 0x1, decoded by ese_parser for every cookie and
  shown nowhere. Whether a session cookie was restricted to HTTPS is a
  property of the row worth scanning a column for.

  Found in (Indicators). url_intel.SCANNED_FIELDS covers five fields. A
  MAC address read out of a URL and one read out of a cached filename are
  different claims about the same string, and the view could not say
  which was which.

Column kinds are asserted, not just presence: kind decides which filter
operators the header funnel offers (record_filter.OPERATORS_BY_KIND) and
how the value is aligned and coloured, so a column with the right key and
the wrong kind is a column that filters wrongly.
"""
from webcache.views.cookies import CookiesView
from webcache.views.file_access import FileAccessView
from webcache.views.indicators import IndicatorsView


def _columns(view, key):
    """The named RecordSet's columns -- these views are segmented, and
    view.COLUMNS is only ever the ACTIVE segment's list (see
    records_view.py, which reassigns it on every segment switch)."""
    return view._segments_by_key[key].columns


def test_downloads_shows_how_much_of_the_decode_was_real(qtbot):
    v = FileAccessView()
    qtbot.addWidget(v)
    col = next(c for c in _columns(v, "downloads")
               if c.key == "DownloadConfidence")
    assert col.label == "Confidence"
    assert col.kind == "flag"
    # No provenance citation on purpose -- see
    # test_a_live_downloads_confidence_never_wears_the_carved_badge below
    # for why pointing this at the catalogue's "Confidence" entry was a
    # claim about where these rows came from.
    assert col.field is None


def test_cookies_shows_the_secure_bit(qtbot):
    v = CookiesView()
    qtbot.addWidget(v)
    col = next(c for c in _columns(v, "cookies") if c.key == "IsSecure")
    assert col.label == "Secure"
    assert col.kind == "flag"


def test_indicators_says_which_field_the_value_was_found_in(qtbot):
    v = IndicatorsView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "Fields")
    assert col.label == "Found in"
    assert col.kind == "text"


def test_the_new_columns_render_the_rows_the_loaders_actually_build(qtbot):
    """The teeth. A column whose key no loader writes shows an empty
    cell forever and looks exactly like a column whose data is genuinely
    absent -- this port's signature defect, one layer over."""
    from webcache.shell import evidence_loader, indicator_loader

    class _P:
        all_entries = []
        cookie_entries = [{"Domain": "example.test", "Name": "sid",
                           "Value": "v", "Path": "/", "IsSecure": True,
                           "Expires_raw": 0, "LastModified_raw": 0}]

    cookie_row = evidence_loader.cookie_rows_from_parser(_P())[0]
    col = next(c for c in _columns(CookiesView(), "cookies")
               if c.key == "IsSecure")
    assert col.key in cookie_row

    class _D:
        all_entries = [{"ContainerType": "Downloads",
                        "ResponseHeaders_raw": b"\x00" * 64}]

    dl_row = evidence_loader.downloads_rows_from_parser(_D())[0]
    col = next(c for c in _columns(FileAccessView(), "downloads")
               if c.key == "DownloadConfidence")
    assert col.key in dl_row

    ind_row = indicator_loader.indicator_rows(
        [{"Url": "https://example.test/00-1A-2B-3C-4D-5E/a"}])[0]
    assert "Fields" in ind_row


def test_a_live_downloads_confidence_never_wears_the_carved_badge(qtbot):
    """CAUGHT ON SCREEN, not by the suite.

    evidence_model catalogues "Confidence" as "Confidence grade for a
    CARVED artifact", basis CARVED -- which is exactly right for the
    Deleted Records view, whose rows are carved. Pointing the Downloads
    column's field= at the same catalogue entry painted a CARV chip on
    the heading of a column full of LIVE records, asserting a provenance
    the rows do not have.

    A download blob's decode confidence is a different quantity that
    happens to share a word. Until it has its own FIELD_PROVENANCE entry,
    the honest rendering is NO badge -- basis_of() defaults to DERIVED for
    an unknown key, so a wrong citation is worse than none: it is
    indistinguishable from a real one.
    """
    from webcache.engine import evidence_model

    assert evidence_model.basis_of("Confidence") == evidence_model.CARVED, (
        "if this stops being true the reasoning below needs revisiting")

    v = FileAccessView()
    qtbot.addWidget(v)
    col = next(c for c in _columns(v, "downloads")
               if c.key == "DownloadConfidence")
    assert col.field is None, (
        "a live Downloads row is not carved; field='Confidence' cites the "
        "carved-artifact catalogue entry and paints CARV on the heading")


def test_the_deleted_records_confidence_keeps_its_carved_citation(qtbot):
    """The other half: that catalogue entry is correct where the rows
    really are carved, and must not be removed as collateral."""
    from webcache.views.recovery import RecoveryView

    v = RecoveryView()
    qtbot.addWidget(v)
    col = next(c for c in v.COLUMNS if c.key == "Confidence")
    assert col.field == "Confidence"
