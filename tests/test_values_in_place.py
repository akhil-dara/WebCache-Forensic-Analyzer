"""And the word-boundary wrapping rule."""
import re

import pytest
from PySide6.QtCore import Qt

from webcache.views.containers import ContainersView
from webcache.views.cookies import CookiesView
from webcache.views.file_access import FileAccessView
from webcache.views.location import LocationView
from webcache.widgets.column_spec import Column
from webcache.widgets.record_model import RecordTableModel
from webcache.widgets.records_table import _breakable

ZWSP = "\u200b"


def test_a_file_url_decodes_to_a_windows_path():
    from webcache.engine import url_intel
    assert url_intel.windows_path_from_file_url(
        "file:///C:/Users/alice/My%20Documents/a%23b.txt") == \
        "C:\\Users\\alice\\My Documents\\a#b.txt"
    assert url_intel.windows_path_from_file_url(
        "file://server/share/x%20y.docx") == "\\\\server\\share\\x y.docx"
    assert url_intel.windows_path_from_file_url("https://example.test/") == ""


def test_file_access_shows_the_decoded_path_beside_the_stored_one(qtbot):
    view = FileAccessView()
    qtbot.addWidget(view)
    keys = [c.key for c in view.COLUMNS]
    assert "LocalPath" in keys
    assert keys.index("LocalPath") == keys.index("CleanUrl") + 1


def test_a_coordinate_never_breaks_inside_its_number():
    out = _breakable("-33.8688197123456, 151.2092955987654")
    assert re.search(r"\d[.,]\u200b\d|\d\u200b[.,]\d", out) is None


def test_a_sid_breaks_only_at_its_hyphens():
    out = _breakable("S-1-5-21-1234567890-1234567890-1234567890-1001")
    assert re.search(r"\d\u200b\d", out) is None


def test_the_partition_column_is_wide_enough_for_a_sid(qtbot):
    view = ContainersView()
    qtbot.addWidget(view)
    width = next(c.width for c in view.COLUMNS if c.key == "Partition")
    assert width >= 300


def test_location_rows_stop_at_three_lines(qtbot):
    view = LocationView()
    qtbot.addWidget(view)
    assert view.table.itemDelegate().line_cap == 3


def test_a_copy_only_link_reads_as_text_with_a_copy_glyph():
    col = Column("MapsUrl", "Google Maps", 135, kind="url",
                 on_click=lambda row: None, on_click_copies=True)
    model = RecordTableModel([col], [{"MapsUrl": "https://maps.example.test/"}])
    index = model.index(0, 0)
    from webcache.widgets.record_model import foreground
    assert model.data(index, Qt.ForegroundRole) == foreground("text")
    assert model.data(index, Qt.DecorationRole) is not None


def test_identical_columns_are_hidden_and_named(qtbot):
    view = FileAccessView()
    qtbot.addWidget(view)
    rows = [{"CleanUrl": "file:///C:/a%d.txt" % i, "FileSize": 0,
             "Origin": "Live record" if i else "Carved (deleted/unflushed)"}
            for i in range(4)]
    view.set_records(rows)
    keys = [c.key for c in view.table.model().columns]
    assert view.identical_button.isChecked()
    assert view.table.isColumnHidden(keys.index("FileSize"))
    assert "Size" in view._constant_chip.text()
    view.identical_button.click()
    assert not view.table.isColumnHidden(keys.index("FileSize"))


def test_a_long_identical_value_is_named_not_repeated(qtbot):
    from webcache.views.iocs import FindingsView
    view = FindingsView()
    qtbot.addWidget(view)
    paragraph = "One interpretation paragraph, the same on every row. " * 4
    view.set_records_for("entryid_gaps", [
        {"ContainerId": i, "ContainerName": "C%d" % i, "Live": i,
         "Missing": 1, "Recovered": 0, "GapRuns": 1,
         "Interpretation": paragraph, "_record": None, "_kind": "entryid_gap",
         "_records": []} for i in range(3)])
    view._switch_segment("entryid_gaps")
    assert paragraph not in view._constant_chip.text()
    assert "Interpretation" in view._constant_chip.text()
    assert paragraph.strip() in view._constant_chip.toolTip()


def test_each_cookies_segment_states_its_own_caveat(qtbot):
    view = CookiesView()
    qtbot.addWidget(view)
    view.set_caveat("An HSTS pin proves a TLS connection, not that a page was viewed.")
    view._switch_segment("certs")
    assert "HSTS" not in view.caveat._text.text()
    view._switch_segment("hsts")
    assert "HSTS" in view.caveat._text.text()


# --- wrapping prefers word and separator boundaries ---------------------

def _only_at_boundaries(out, source):
    """Every break point in `out` sits after a separator or at a
    CamelCase hump -- never inside a run of letters."""
    assert out.replace(ZWSP, "") == source
    for m in re.finditer(ZWSP, out):
        before, after = out[m.start() - 1], out[m.end()]
        ok = (before in "/\\-_.?&=,;:+#%@|" or
              (before.islower() and after.isupper()) or
              (before.isupper() and after.isupper()))
        assert ok, "break inside a token at %r|%r" % (before, after)


def test_the_grid_breaks_an_identifier_at_its_humps_not_mid_word():
    source = "BackgroundTransferServiceProviderConfigurationStore"
    out = _breakable(source)
    assert ZWSP in out
    _only_at_boundaries(out, source)
    # no 24-character hard cut through the middle of a word
    assert re.search(r"[a-z]{3}\u200b[a-z]{3}", out) is None


def test_the_grid_still_hard_breaks_a_token_with_no_boundary():
    source = "0123456789abcdef" * 6
    out = _breakable(source)
    assert ZWSP in out and out.replace(ZWSP, "") == source


def test_the_grid_breaks_a_path_and_a_query_at_separators():
    source = "Folder_Name.sub/deep\\leaf?a=1&b=2,c=3"
    _only_at_boundaries(_breakable(source), source)


def _wrapped_lines(widget):
    layout = widget.document().firstBlock().layout()
    text = widget.document().toPlainText()
    return [text[layout.lineAt(i).textStart():
                 layout.lineAt(i).textStart() + layout.lineAt(i).textLength()]
            .replace(ZWSP, "") for i in range(layout.lineCount())]


def test_wrapping_text_breaks_an_identifier_at_a_hump_not_mid_word(qtbot):
    from webcache.widgets.wrapping_text import WrappingText
    widget = WrappingText("BackgroundTransfer")
    qtbot.addWidget(widget)
    fm = widget.fontMetrics()
    whole = fm.horizontalAdvance("BackgroundTransfer")
    first = fm.horizontalAdvance("Background")
    if not (0 < first < whole):
        pytest.skip("no usable font metrics")
    width = (first + whole) // 2 if whole - first > 8 else first + 2
    widget.resize(width + 10, 40)
    widget.document().setTextWidth(width)
    assert _wrapped_lines(widget) == ["Background", "Transfer"]


def test_wrapping_text_keeps_the_stored_text_and_the_copy_exact(qtbot):
    from webcache.widgets.wrapping_text import WrappingText
    widget = WrappingText("BackgroundTransfer/alpha_beta.gamma?x=1&y=2")
    qtbot.addWidget(widget)
    assert widget.text() == "BackgroundTransfer/alpha_beta.gamma?x=1&y=2"
    widget.selectAll()
    mime = widget.createMimeDataFromSelection()
    assert mime.text() == "BackgroundTransfer/alpha_beta.gamma?x=1&y=2"
    assert ZWSP not in mime.text()


def test_a_sid_offers_a_break_after_every_hyphen():
    """Qt never breaks between a hyphen and a digit, so a SID with no
    opportunity of its own stays one line and is clipped (seen on screen:
    the Partition column). Every hyphen of a SID is an opportunity; a
    three-part date is left whole, and a coordinate's sign stays on it."""
    sid = "S-1-5-21-1234567890-1234567890-1234567890-1001"
    out = _breakable(sid)
    assert out.count("-" + ZWSP) == sid.count("-")
    assert "-" + ZWSP not in _breakable("2026-08-03 15:58:20")
    assert "-" + ZWSP not in _breakable("-33.8688197123456, 151.2092955987654")
