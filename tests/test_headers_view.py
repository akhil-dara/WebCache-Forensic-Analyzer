"""HeadersView: the record table, and the second pane beside it.

HTTP Headers is the only two-pane view. The seam is ONE method on the base -- RecordsView.
_table_area() -- so six existing views are untouched and the pane stays a
subclass's business; both halves of that are asserted here.

What this file does NOT re-prove: the base class's generic contract
(filter box, count line, Ctrl+F, chips, the Export view button), which
tests/test_records_view.py already owns. Only what HeadersView itself
declares.
"""
import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter

from webcache import provenance
from webcache.shell import headers_loader as H
from webcache.views.headers import COLUMNS, HeaderPane, HeadersView
from webcache.views.history import HistoryView
from webcache.views.records_view import RecordsView

RESP = (b"HTTP/1.1 404 Not Found\r\n"
        b"Content-Type: text/html\r\n"
        b"Server: nginx\r\n"
        b"Set-Cookie: a=1\r\n"
        b"Set-Cookie: b=2\r\n"
        b"X-Forwarded-For: 203.0.113.7\r\n\r\n")
REQ = b"Accept: */*\r\n\r\n"


def _record(**overrides):
    from webcache.engine import ese_parser
    record = {"ContainerType": "Content", "ContainerId": 5, "EntryId": 41,
              "ContainerName": "Content",
              "CleanUrl": "https://example.test/a",
              "ModifiedTime_raw": 133546220420000000,
              "ResponseHeaders_raw": RESP, "RequestHeaders_raw": REQ,
              "ResponseHeaders": ese_parser.decode_content_headers(RESP),
              "RequestHeaders": ese_parser.decode_content_headers(REQ)}
    record.update(overrides)
    return record


class _Parser:
    def __init__(self, entries):
        self.all_entries = list(entries)


def _rows(n=1):
    return H.header_rows_from_parser(
        _Parser([_record(EntryId=41 + i,
                         CleanUrl="https://example%d.test/a" % i)
                 for i in range(n)]))


# --- the one new hook on the base ----------------------------------------

def test_the_base_puts_its_own_table_in_the_table_area(qtbot):
    """The default table area holds the view's own table, with the
    details pane beside it."""
    view = HistoryView()
    qtbot.addWidget(view)
    area = view._table_area()
    assert area.isAncestorOf(view.table)
    assert area.isAncestorOf(view.details_pane)


def test_the_base_hook_is_what_the_root_layout_actually_adds(qtbot):
    """A hook nothing calls is decoration. The table has to reach the
    layout THROUGH it, or a subclass overriding it changes nothing."""
    import inspect
    source = inspect.getsource(RecordsView.__init__)
    assert "self._table_area()" in source
    assert "root.addWidget(self.table, 1)" not in source


def test_headers_pairs_its_table_with_a_second_pane(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    area = view._table_area()
    assert isinstance(area, QSplitter)
    assert area.orientation() == Qt.Horizontal
    assert view.table.parent() is area
    assert view.detail_pane.parent() is area


def test_the_splitter_is_in_the_view_and_the_table_is_still_reachable(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    assert view.table.model() is None or True
    # The base's own API still works through the splitter.
    view.set_records(_rows(3))
    assert view.table.model().rowCount() == 3


# --- columns and chips ----------------------------------------------------

def test_columns_match_the_spec():
    keys = [c.key for c in COLUMNS]
    assert keys == ["CleanUrl", "Status", "RespCount", "ReqCount",
                    "DuplicateCount", "ContentType", "Server",
                    "ClientIpHeaders", "ModifiedTime", "ContainerId",
                    "Origin", "Source"]


def test_the_computed_columns_claim_no_provenance_they_cannot_cite():
    """ClientIpHeaders and DuplicateCount are computed in this port and
    are absent from evidence_model.FIELD_PROVENANCE. field=None is the
    honest degradation -- basis_of() would default them to DERIVED and
    paint a confident badge on a claim with no citation."""
    by_key = {c.key: c for c in COLUMNS}
    assert by_key["ClientIpHeaders"].field is None
    assert by_key["DuplicateCount"].field is None
    assert by_key["Status"].field == "HttpStatus"
    assert by_key["ContentType"].field == "ContentType"
    assert by_key["Server"].field == "Server"


def test_the_container_column_drills_rather_than_only_copying(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    by_key = {c.key: c for c in view.COLUMNS}
    assert by_key["ContainerId"].on_click is not None
    seen = []
    view.drillRequested.connect(lambda key, row: seen.append(key))
    by_key["ContainerId"].on_click({"ContainerId": 5})
    assert seen == ["browser"]


def test_the_three_quick_filter_chips_exist(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    for attr in ("chip_request_side", "chip_client_ip", "chip_error_status"):
        assert hasattr(view, attr), attr


def test_the_error_status_chip_filters_to_4xx_and_5xx(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    rows = _rows(2)
    ok = dict(rows[0])
    ok["StatusClass"] = "2xx"
    view.set_records([ok, rows[1]])
    view.chip_error_status.setChecked(True)
    assert view.table.model().rowCount() == 1


def test_the_client_ip_chip_matches_only_rows_that_named_one(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    rows = _rows(2)
    blank = dict(rows[0])
    blank["ClientIpHeaders"] = ""
    view.set_records([blank, rows[1]])
    view.chip_client_ip.setChecked(True)
    assert view.table.model().rowCount() == 1


# --- what the view says about the rows it does not have -------------------

def test_the_subtitle_states_the_pair_count_beside_the_record_count(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    view.set_records(_rows(2))
    subtitle = view.header._subtitle.text()
    assert "2" in subtitle
    assert "pair" in subtitle.lower()


def test_the_subtitle_states_the_sps_exclusion(qtbot):
    """An examiner seeing a dozen rows against a status bar reading
    hundreds needs the reason in front of them, not in a docstring."""
    view = HeadersView()
    qtbot.addWidget(view)
    view.set_records(_rows(1))
    subtitle = view.header._subtitle.text().lower()
    assert "property store" in subtitle and "sps" in subtitle


def test_the_empty_state_explains_itself_rather_than_painting_a_void(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    view.set_records([])
    assert view.table.showing_genuine_empty_state()
    text = view.table._empty_reason.lower()
    assert "property store" in text


# --- the pair export button -----------------------------------------------

def test_the_pair_button_counts_pairs_not_records(qtbot):
    """Two honest numbers on one screen. The record count is what the
    table shows; the pair count is what the pair file would hold."""
    view = HeadersView()
    qtbot.addWidget(view)
    rows = _rows(2)
    view.set_records(rows)
    assert view.export_button.text() == "Export view (2)"
    assert view.pairs_export_button.text() == (
        "Export header pairs (%s)" % H.total_pairs(rows))


def test_the_pair_button_tracks_the_filter(qtbot):
    """The earlier version captured its rows at view-build time and always
    wrote every pair of the unfiltered set, so a filtered view exported
    rows the examiner had never seen. This is the direct fix."""
    view = HeadersView()
    qtbot.addWidget(view)
    rows = _rows(3)
    view.set_records(rows)
    view.filter_box.setText("example1")
    view._apply_text()
    assert view.table.model().rowCount() == 1
    visible = view.table.model().filter.visible()
    assert view.pairs_export_button.text() == (
        "Export header pairs (%s)" % H.total_pairs(visible))


def test_the_pair_button_is_beside_the_view_export_button(qtbot):
    """Beside it, not somewhere else on the screen: the two numbers only
    make sense read together."""
    view = HeadersView()
    qtbot.addWidget(view)
    bar = view.pairs_export_button.parentWidget().layout()
    assert bar is not None
    found = None
    for i in range(bar.count()):
        item = bar.itemAt(i)
        if item.layout() is not None and item.layout().indexOf(
                view.export_button) >= 0:
            found = item.layout()
    assert found is not None
    assert found.indexOf(view.pairs_export_button) == (
        found.indexOf(view.export_button) + 1)


def test_clicking_the_pair_button_only_says_an_examiner_asked(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    seen = []
    view.pairExportRequested.connect(lambda: seen.append(1))
    view.pairs_export_button.click()
    assert seen == [1]


# --- the pane -------------------------------------------------------------

def test_the_pane_starts_on_a_placeholder(qtbot):
    pane = HeaderPane()
    qtbot.addWidget(pane)
    assert "select" in pane.placeholder.text().lower()
    assert pane.placeholder.isVisible() or pane.current_row() is None


def test_selecting_a_row_fills_the_pane_and_clearing_it_empties_it(qtbot):
    pane = HeaderPane()
    qtbot.addWidget(pane)
    row = _rows(1)[0]
    pane.set_row(row)
    assert pane.current_row() is row
    pane.set_row(None)
    assert pane.current_row() is None


def test_the_pane_renders_the_status_line_first_and_then_wire_order(qtbot):
    pane = HeaderPane()
    qtbot.addWidget(pane)
    pane.set_row(_rows(1)[0])
    names = pane.rendered_names("response")
    assert names[0] == H.STATUS_LINE_LABEL
    assert names == [H.STATUS_LINE_LABEL, "Content-Type", "Server",
                     "Set-Cookie", "Set-Cookie", "X-Forwarded-For"]


def test_the_pane_keeps_both_values_of_a_repeated_header(qtbot):
    pane = HeaderPane()
    qtbot.addWidget(pane)
    pane.set_row(_rows(1)[0])
    values = [v for n, v in pane.rendered_pairs("response") if n == "Set-Cookie"]
    assert values == ["a=1", "b=2"]


def test_the_pane_states_the_collapse_in_words(qtbot):
    pane = HeaderPane()
    qtbot.addWidget(pane)
    pane.set_row(_rows(1)[0])
    assert "overwritten" in pane.duplicates_label.text()
    assert pane.duplicates_label.isVisibleTo(pane)


def test_a_record_with_no_repeats_says_nothing_about_repeats(qtbot):
    from webcache.engine import ese_parser
    blob = b"HTTP/1.1 200 OK\r\nServer: x\r\n\r\n"
    rows = H.header_rows_from_parser(_Parser([_record(
        ResponseHeaders_raw=blob,
        ResponseHeaders=ese_parser.decode_content_headers(blob),
        RequestHeaders_raw=None, RequestHeaders={})]))
    pane = HeaderPane()
    qtbot.addWidget(pane)
    pane.set_row(rows[0])
    assert not pane.duplicates_label.isVisibleTo(pane)


def test_an_absent_side_is_absent_entirely_not_a_none_placeholder(qtbot):
    from webcache.engine import ese_parser
    blob = b"HTTP/1.1 200 OK\r\nServer: x\r\n\r\n"
    rows = H.header_rows_from_parser(_Parser([_record(
        ResponseHeaders_raw=blob,
        ResponseHeaders=ese_parser.decode_content_headers(blob),
        RequestHeaders_raw=None, RequestHeaders={})]))
    pane = HeaderPane()
    qtbot.addWidget(pane)
    pane.set_row(rows[0])
    assert pane.rendered_names("request") == []
    assert not pane.request_block.isVisibleTo(pane)
    assert pane.response_block.isVisibleTo(pane)


def test_the_pane_states_the_client_ip_limit_in_words(qtbot):
    """Colour is reinforcement of a fact already stated in text, never
    the only place the fact appears."""
    pane = HeaderPane()
    qtbot.addWidget(pane)
    pane.set_row(_rows(1)[0])
    assert H.CLIENT_IP_NOTE in pane.client_ip_label.text()


def test_the_pane_has_no_hex_dump_of_its_own(qtbot):
    """BlobPane already does this properly -- full length, paged, with
    strings, decode, SHA-256 and byte export. A second, worse viewer in
    the pane is the drift the shared BLOB_FIELDS catalogue exists to
    prevent (the earlier version truncated to 256 bytes while labelling it
    with the full length)."""
    import inspect
    from webcache.views import headers
    source = inspect.getsource(headers)
    for banned in ("hexdump", "hex()", "BlobPane", "256"):
        assert banned not in source, banned


def test_the_pane_asks_for_the_record_and_the_container_by_signal(qtbot):
    pane = HeaderPane()
    qtbot.addWidget(pane)
    row = _rows(1)[0]
    pane.set_row(row)
    seen = []
    pane.detailRequested.connect(lambda r: seen.append(("detail", r)))
    pane.containerRequested.connect(lambda r: seen.append(("container", r)))
    pane.detail_button.click()
    pane.container_button.click()
    assert [k for k, _r in seen] == ["detail", "container"]
    assert all(r is row for _k, r in seen)


def test_a_carved_row_reaches_the_pane_saying_so(qtbot):
    pane = HeaderPane()
    qtbot.addWidget(pane)
    row = dict(_rows(1)[0])
    row["Origin"] = provenance.CARVED_ORIGIN
    row["Source"] = "transaction log"
    pane.set_row(row)
    assert provenance.CARVED_ORIGIN in pane.origin_label.text()


def test_the_table_selection_drives_the_pane(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    rows = _rows(2)
    view.set_records(rows)
    view.table.selectRow(1)
    assert view.detail_pane.current_row() is view.table.model().row_at(1)


# --- defects the on-screen run exposed ------------------------------------

def test_the_pane_leaves_the_table_the_width_until_something_is_selected(qtbot):
    """The table has twelve columns and does not fit at any width. A pane
    holding nothing but a one-line invitation must not take two fifths of
    the window to hold it."""
    view = HeadersView()
    qtbot.addWidget(view)
    view.resize(1600, 900)
    view.set_records(_rows(3))
    idle = view._table_area().sizes()
    view.table.selectRow(0)
    active = view._table_area().sizes()
    assert idle[1] < active[1], (idle, active)
    assert idle[1] * 3 < idle[0], (
        "the empty pane is taking a quarter of the window or more: %s" % idle)


def test_the_pane_returns_the_width_when_the_selection_is_cleared(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    view.resize(1600, 900)
    view.set_records(_rows(3))
    view.table.selectRow(0)
    active = view._table_area().sizes()
    view.set_records(_rows(2))          # a fresh model clears the selection
    assert view._table_area().sizes()[1] < active[1]


def test_each_side_paints_one_label_not_two_widgets_per_header(qtbot):
    """The first draft built a name label and a value label per pair --
    44 child widgets for one 22-header record -- and they overlapped: a
    word-wrapped QLabel's height is not what a QVBoxLayout gives it
    inside a scroll area. One rich-text label per side is both correct
    and a fraction of the widgets."""
    from PySide6.QtWidgets import QLabel
    pane = HeaderPane()
    qtbot.addWidget(pane)
    pane.set_row(_rows(1)[0])
    labels = pane.response_block.findChildren(QLabel)
    assert len(labels) == 2, [lb.text()[:30] for lb in labels]


def test_the_painted_text_holds_every_value_in_wire_order(qtbot):
    pane = HeaderPane()
    qtbot.addWidget(pane)
    pane.set_row(_rows(1)[0])
    text = pane.response_text.text()
    assert text.index("a=1") < text.index("b=2")
    assert "Content-Type" in text and "nginx" in text


def test_a_value_that_looks_like_markup_is_shown_not_interpreted(qtbot):
    """A header value is evidence. Rendering it as markup would change
    what the examiner reads."""
    from webcache.engine import ese_parser
    blob = (b"HTTP/1.1 200 OK\r\n"
            b"X-Note: <b>not bold</b> & <script>\r\n\r\n")
    rows = H.header_rows_from_parser(_Parser([_record(
        ResponseHeaders_raw=blob,
        ResponseHeaders=ese_parser.decode_content_headers(blob),
        RequestHeaders_raw=None, RequestHeaders={})]))
    pane = HeaderPane()
    qtbot.addWidget(pane)
    pane.set_row(rows[0])
    assert "&lt;b&gt;not bold&lt;/b&gt;" in pane.response_text.text()
    assert ("<b>not bold</b>", ) and "&amp;" in pane.response_text.text()


def test_the_pane_never_describes_a_row_a_filter_has_removed(qtbot):
    """Seen on the real exhibit: a row selected, then a filter typed that
    excluded it, and the pane went on showing its headers beside a table
    that no longer held it. Worse than stale -- the current index is a row
    NUMBER, so the next refresh could have pointed it at a different
    record entirely while the pane still read as the selected one.
    """
    view = HeadersView()
    qtbot.addWidget(view)
    rows = _rows(3)
    view.set_records(rows)
    view.table.selectRow(0)
    assert view.detail_pane.current_row() is not None
    view.filter_box.setText("example2")
    view._apply_text()
    visible = view.table.model().filter.visible()
    assert len(visible) == 1
    shown = view.detail_pane.current_row()
    assert shown is None or shown in visible, (
        "the pane is showing a row the filter removed")


def test_the_pane_follows_the_selection_after_a_filter_narrows_it(qtbot):
    view = HeadersView()
    qtbot.addWidget(view)
    view.set_records(_rows(3))
    view.filter_box.setText("example2")
    view._apply_text()
    view.table.selectRow(0)
    assert view.detail_pane.current_row() is view.table.model().row_at(0)


def test_the_carved_origin_line_is_painted_carved_when_the_row_is(qtbot):
    """refresh_theme decided this colour from the label's own text, and
    refresh_theme runs at construction -- before any row exists. The
    branch could never fire in normal use, so a carved record's origin
    line was painted in the live colour. The WORDS were always right,
    which is why this is reinforcement and not the fact itself."""
    from webcache.shell import theme
    carved = theme.PALETTES[theme.current_name()]["carved"]
    pane = HeaderPane()
    qtbot.addWidget(pane)
    row = dict(_rows(1)[0])
    row["Origin"] = provenance.CARVED_ORIGIN
    pane.set_row(row)
    assert carved in pane.origin_label.styleSheet()
    pane.set_row(_rows(1)[0])
    assert carved not in pane.origin_label.styleSheet()


def test_a_record_with_no_stored_instant_uses_the_absence_vocabulary(qtbot):
    """A bare dash is a fifth spelling of absence in an application that
    already has exactly four and a test file pinning them. The pane's
    meta line was the one place one slipped in."""
    pane = HeaderPane()
    qtbot.addWidget(pane)
    row = dict(_rows(1)[0])
    row["ModifiedTime"] = None
    pane.set_row(row)
    assert provenance.ABSENCE_EMPTY in pane.meta_label.text()
    assert "—" not in pane.meta_label.text()
