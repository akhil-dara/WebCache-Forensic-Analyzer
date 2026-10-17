"""Recovered records are searched and said to be; hits read
in context; the scope is grouped."""
import pytest
from PySide6.QtCore import Qt

from webcache.provenance import CARVED_ORIGIN, EvidenceSet
from webcache.shell import search_loader
from webcache.shell.main_window import MainWindow
from webcache.shell.recovery_loader import deleted_records_rows

_PATH = "C:/case/WebCacheV01.dat"
TOKEN = "zqxjtoken"


class _Parser:
    def __init__(self):
        self.all_entries = []
        self.db = None
        self.db_path = _PATH
        self.containers_meta = []
        self.container_type_map = {}
        self.table_names = ["Container_1", "Container_2", "HstsEntryEx_1",
                            "MSysObjects"]

    def get_table_display_name(self, name):
        return name

    def get_table_type(self, name):
        return {"Container_1": "History", "Container_2": "Content",
                "HstsEntryEx_1": "HSTS"}.get(name, "System Catalog")


class _Engine:
    def __init__(self, records):
        self.structured_records = records
        self.tombstones = []

    def all_artifacts(self):
        return []


def _carved(url):
    return {"Url": url, "CleanUrl": url, "ContainerType": "History",
            "RecoverySource": "unallocated page", "Source": "WebCacheV01.dat",
            "Offset": 8192, "Page": 2, "Confidence": "high",
            "ModifiedTime_raw": 133544180420000000}


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    w._on_evidence_loaded({"rows": [], "parser": _Parser()},
                          EvidenceSet([_PATH], {_PATH: 1}, {_PATH: "a" * 64}))
    return w


def _empty_db_result():
    return {"rows": [], "tables": 4, "rows_scanned": 40, "skipped": []}


# --- --------------------------------------------------------------------

def test_recovered_records_are_searched_by_default(win):
    win._on_recovery_loaded(_Engine([_carved("https://gone.example.test/%s" % TOKEN),
                                     _carved("https://gone.example.test/other")]))
    query = win._search_query_for(TOKEN, "")
    win._on_search_found(query, _empty_db_result())
    view = win._ensure_view_built("search")
    rows = [view.table.model().row_at(i)
            for i in range(view.table.model().rowCount())]
    assert len(rows) == 1
    assert rows[0]["Origin"] == CARVED_ORIGIN
    assert rows[0]["Table"] == search_loader.RECOVERED_TABLE
    assert "2 recovered records searched" in view.line_text()


def test_a_single_table_scope_says_the_recovered_records_were_not_searched(win):
    win._on_recovery_loaded(_Engine([_carved("https://gone.example.test/a")]))
    query = win._search_query_for(TOKEN, "Container_1")
    win._on_search_found(query, _empty_db_result())
    text = win._ensure_view_built("search").line_text()
    assert "1 recovered record NOT searched" in text


def test_before_recovery_the_line_says_recovered_records_do_not_exist_yet(win):
    query = win._search_query_for(TOKEN, "")
    win._on_search_found(query, _empty_db_result())
    view = win._ensure_view_built("search")
    assert "recovery has not run" in view.line_text()
    assert "recovery has not run" in view.table.empty_state_text()


def test_the_scope_offers_recovered_records_and_groups_tables(win):
    win._on_recovery_loaded(_Engine([_carved("https://gone.example.test/a")]))
    combo = win._ensure_view_built("search").scope_combo
    data = [combo.itemData(i) for i in range(combo.count())]
    assert data[1] == search_loader.RECOVERED_SCOPE
    assert "Recovered records (1)" == combo.itemText(1)
    headers = [i for i, d in enumerate(data)
               if str(d).startswith(search_loader.GROUP_PREFIX)]
    assert headers
    for i in headers:
        assert not combo.model().item(i).isEnabled()


def test_recovered_hits_are_found_in_their_own_fields():
    rows = deleted_records_rows(_Engine([_carved("https://x.example.test/%s" % TOKEN)]))
    hits = search_loader.recovered_hits(TOKEN.upper(), rows)
    assert len(hits) == 1
    assert hits[0]["MatchedColumns"] == "Url"
    assert hits[0]["_record"] is rows[0]["_record"]


# --- --------------------------------------------------------------------

def test_a_blob_hit_reads_as_the_keyword_in_context_with_its_offset():
    blob = (b"\x00\x01garbage" * 40 + b"Server: synthetic-" + TOKEN.encode()
            + b"-host\r\n" + b"\xff" * 300)
    offset = blob.index(TOKEN.encode())
    result = {"table": "Container_2", "container_name": "Content",
              "table_type": "Content", "row_index": 3,
              "matched_columns": ["ResponseHeaders"], "match_in_blob": True,
              "match_value": "mojibake " * 50, "match_raw_type": "binary",
              "match_raw": " ".join("%02X" % b for b in blob),
              "row": {"ResponseHeaders": "[Binary]"}}
    row = search_loader.search_rows([result], keyword=TOKEN)[0]
    assert row["BlobOffset"] == offset
    assert TOKEN in row["Context"]
    assert len(row["Context"]) <= 2 * search_loader.KWIC_RADIUS + len(TOKEN) + 2


def test_a_text_hit_is_cut_to_its_context_too():
    text = "a" * 200 + TOKEN + "b" * 200
    snippet, start = search_loader.keyword_context(text, TOKEN)
    assert snippet == "…" + "a" * 40 + TOKEN + "b" * 40 + "…"
    assert start == 200


def test_the_keyword_is_highlighted_and_the_rest_escaped():
    from webcache.widgets.keyword_delegate import highlight_html
    html = highlight_html("<b>x</b> ZQXJTOKEN y", TOKEN, "#000", "#ff0")
    assert "&lt;b&gt;" in html
    assert "<span style=\"color:#000;background:#ff0\">ZQXJTOKEN</span>" in html


def test_the_whole_values_are_one_click_away_not_on_every_row(win):
    view = win._ensure_view_built("search")
    win.go_to("search")
    keys = [c.key for c in view.table.model().columns]
    for key in ("MatchedValue", "RawValue"):
        assert view.table.isColumnHidden(keys.index(key))
    assert view.columns_button.isVisible()
    actions = {a.text(): a for a in view.columns_button.menu().actions()}
    actions["Matched value — decoded"].trigger()
    assert not view.table.isColumnHidden(keys.index("MatchedValue"))


# --- a search that races a recovery scan ------------------------------------

def test_a_scan_landing_mid_search_leaves_the_search_running_and_is_named(win):
    view = win._ensure_view_built("search")
    query = win._search_query_for(TOKEN, "")
    view.show_searching(query)
    win._on_recovery_loaded(_Engine([_carved("https://gone.example.test/%s" % TOKEN)]))
    # The scope gains the recovered records; the running search is not
    # painted idle under the scan.
    assert view.scope_combo.findData(search_loader.RECOVERED_SCOPE) == 1
    assert not view.search_button.isEnabled()
    win._on_search_found(query, _empty_db_result())
    text = view.line_text()
    assert "1 recovered record NOT searched" in text
    assert "recovery finished after this search began" in text


def test_a_new_scan_keeps_the_examiners_scope(win):
    view = win._ensure_view_built("search")
    view.scope_combo.setCurrentIndex(view.scope_combo.findData("Container_2"))
    win._on_recovery_loaded(_Engine([_carved("https://gone.example.test/a")]))
    assert view.scope() == "Container_2"


def test_a_recovered_only_search_reads_no_table(win, monkeypatch):
    from webcache.shell import main_window as mw
    started = []
    monkeypatch.setattr(mw.SearchRunner, "start",
                        lambda self, q: started.append(q))
    win._on_recovery_loaded(_Engine([_carved("https://gone.example.test/%s" % TOKEN)]))
    win._start_search(TOKEN, search_loader.RECOVERED_SCOPE)
    view = win._ensure_view_built("search")
    assert started == []
    assert view.table.model().rowCount() == 1
    assert "1 recovered record searched" in view.line_text()


def test_a_hidden_column_takes_no_room_and_comes_back_whole(win):
    """Found on screen: a hidden section resized by the heading floor
    left a blank gap where it would have been."""
    view = win._ensure_view_built("search")
    win.go_to("search")
    header = view.table.horizontalHeader()
    keys = [c.key for c in view.table.model().columns]
    hidden = keys.index("MatchedValue")
    before, after = hidden - 1, hidden + 1
    assert header.sectionPosition(after) == (header.sectionPosition(before)
                                             + header.sectionSize(before))
    view.table.set_column_hidden("MatchedValue", False)
    assert header.sectionSize(hidden) >= 380
    assert header.sectionPosition(after) == (header.sectionPosition(hidden)
                                             + header.sectionSize(hidden))


# --- a recovered hit means the term IS IN THE EVIDENCE ---------

class _FullEngine:
    """One structured record, one string carve, one stub -- each carrying
    the tool's own labels beside the fields read from the carved bytes."""

    def __init__(self):
        self.structured_records = [{
            "Url": "https://site.example.test/page", "EntryId": 5,
            "ContainerId": 1, "CacheId": 0, "UrlHash": 12345, "Flags": 1,
            "Type": 0, "AccessCount": 2, "FileSize": 10, "SyncCount": 0,
            "ExemptionDelta": 0, "SecureDirectory": 3,
            "AccessedTime_raw": 133544180420000000,
            "AccessedTime": "2024-03-09 00:34:02 UTC",
            "ResponseHeaders_raw": b"HTTP/1.1 200 OK\r\nServer: synth\r\n",
            "SPS_PageTitle": "A synthetic page",
            "CleanUrl": "https://site.example.test/page",
            "ContainerType": "History", "ContainerName": "History",
            "Confidence": "high", "Region": "deleted-record",
            "RecoverySource": "Structured record reconstruction",
            "Source": "WebCacheV01.dat", "Offset": 8192, "Page": 2,
            "RecordEndMode": "exact", "InLiveDb": False,
            "HasResponseHeaders": True, "UrlHealth": "clean",
        }]
        self.tombstones = [{
            "Table": "Container_1", "KeyColumns": ("UrlHash", "EntryId"),
            "KeyValues": (777, 42), "Page": 3, "Offset": 100,
            "Source": "WebCacheV01.dat",
        }]

    def all_artifacts(self):
        return [{"Url": "http://frag.example.test/x",
                 "FragmentTexts": ["http://frag.example.test/x"],
                 "RecoverySource": "unallocated page", "Confidence": "medium",
                 "Region": "page-slack", "Source": "WebCacheV01.dat",
                 "Offset": 8192, "Page": 4, "Encoding": "ascii",
                 "UrlHealth": "repairable"}]


@pytest.mark.parametrize("term", [
    "carved", "deleted", "high", "medium", "webcache", "structured",
    "recovered", "determinable", "8192", "page-slack", "clean", "stub",
    "history", "exact"])
def test_the_tools_own_labels_are_never_a_hit(term):
    rows = deleted_records_rows(_FullEngine())
    assert search_loader.recovered_hits(term, rows) == []


@pytest.mark.parametrize("term,kind_index,column", [
    ("site.example", 0, "Url"),
    ("12345", 0, "UrlHash"),
    ("Server: synth", 0, "ResponseHeaders_raw"),
    ("synthetic page", 0, "SPS_PageTitle"),
    ("2024-03-09 00:34:02", 0, "AccessedTime"),
    ("frag.example", 1, "Url, FragmentTexts"),
    ("777", 2, "KeyValues"),
])
def test_the_fields_read_from_the_carved_bytes_are_searched(
        term, kind_index, column):
    rows = deleted_records_rows(_FullEngine())
    hits = search_loader.recovered_hits(term, rows)
    assert [h["Row"] for h in hits] == [kind_index + 1]
    assert hits[0]["MatchedColumns"] == column


def test_a_stub_key_matches_as_a_whole_number_only():
    rows = deleted_records_rows(_FullEngine())
    assert search_loader.recovered_hits("77", rows) == []


# --- blob matches are real, in the encoding the blob holds -----

def test_a_keyword_with_no_latin1_characters_never_matches_an_unrelated_blob():
    assert search_loader.blob_context(
        b"\x01\x02Server: nothing here\x00", "日本")[1] is None
    rows = deleted_records_rows(_FullEngine())
    assert search_loader.recovered_hits("日本", rows) == []


def test_utf16_bytes_are_never_lower_cased_into_a_different_character():
    # U+0141 (L with stroke) is 41 01; lower-casing the 0x41 byte made it
    # read as U+0161 (s with caron), 61 01.
    assert search_loader.blob_context(
        "Ł".encode("utf-16-le"), "š")[1] is None


def test_a_utf16_match_at_an_odd_offset_is_not_a_match():
    data = b"\x00" + "ab".encode("utf-16-le")
    assert search_loader.blob_context(data, "ab")[1] is None


def test_a_utf8_multibyte_hit_reads_in_utf8_not_latin1():
    data = b"\x00\x01 caf\xc3\xa9 au lait \x02"
    snippet, at = search_loader.blob_context(data, "CAFÉ")[:2]
    assert at == 3
    assert "café" in snippet and "Ã" not in snippet


def test_an_exact_case_non_ascii_keyword_hits():
    data = b"xx \xc3\x89t\xc3\xa9 yy"
    assert search_loader.blob_context(data, "Été")[1] == 3


def test_a_utf16_hit_is_decoded_in_utf16_around_the_match():
    data = b"\x00\x00" + "Ωmega window".encode("utf-16-le")
    snippet, at = search_loader.blob_context(data, "WINDOW")[:2]
    assert at == 2 + 2 * len("Ωmega ")
    assert "Ωmega window" in snippet


def test_undecodable_bytes_read_as_dots_not_accented_letters():
    snippet = search_loader.blob_context(b"\xe9abc keyword", "keyword")[0]
    assert "é" not in snippet
    assert snippet.startswith("·abc keyword")


def test_a_hit_at_the_start_and_at_the_end_of_a_blob():
    snippet, at = search_loader.blob_context(b"keyword then more", "keyword")[:2]
    assert at == 0 and not snippet.startswith("…")
    data = b"x" * 100 + b"keyword"
    snippet, at = search_loader.blob_context(data, "keyword")[:2]
    assert at == 100 and snippet.endswith("keyword")


def test_a_term_longer_than_the_window_is_shown_whole():
    term = "t" * 100
    data = b"\x01" * 60 + term.encode() + b"\x02" * 60
    snippet, at = search_loader.blob_context(data, term)[:2]
    assert at == 60 and term in snippet


def test_a_blob_hit_names_its_encoding():
    blob = b"\x00\x00" + "header window".encode("utf-16-le")
    result = {"table": "Container_2", "row_index": 1,
              "matched_columns": ["ResponseHeaders"], "match_in_blob": True,
              "match_value": "x", "match_raw_type": "binary",
              "match_raw": " ".join("%02X" % b for b in blob),
              "row": {"ResponseHeaders": "[Binary]"}}
    row = search_loader.search_rows([result], keyword="window")[0]
    assert row.get("BlobEncoding") == "UTF-16LE"
    ascii_blob = dict(result, match_raw=" ".join(
        "%02X" % b for b in b"\x00plain window\x00"))
    row = search_loader.search_rows([ascii_blob], keyword="window")[0]
    assert row.get("BlobEncoding") == "ASCII"


def test_the_offset_column_heading_names_its_unit(win):
    view = win._ensure_view_built("search")
    labels = {c.key: c.label for c in view.COLUMNS}
    assert "byte" in labels["BlobOffset"].lower()
    assert "BlobEncoding" in labels


def test_a_context_that_falls_back_is_one_clean_capped_line():
    result = {"table": "T", "row_index": 1, "matched_columns": ["X"],
              "match_in_blob": True,
              "match_value": "line one\nline two ‮ reversed\n" * 40,
              "match_raw_type": "text", "match_raw": "zz",
              "row": {"X": "y"}}
    row = search_loader.search_rows([result], keyword="4d5a")[0]
    assert "\n" not in row["Context"] and "‮" not in row["Context"]
    assert len(row["Context"]) <= 2 * search_loader.KWIC_RADIUS + 2


# --- a restored column state agrees with menu and sidecar ------

def test_a_shown_column_restored_on_relaunch_is_checked_and_not_called_hidden(qtbot):
    from webcache.shell import export_formats
    from webcache.views.search import SearchView
    label = "Matched value \u2014 decoded"
    first = SearchView()
    qtbot.addWidget(first)
    first.show()
    {a.text(): a for a in first.columns_button.menu().actions()}[label].trigger()
    state = first.table.save_column_state()
    signature = first.table.column_signature()

    second = SearchView()           # the next launch: fresh Column objects
    qtbot.addWidget(second)
    second.show()
    second.table.restore_column_state(state, signature=signature)
    model = second.table.model()
    keys = [c.key for c in model.columns]
    at = keys.index("MatchedValue")
    assert not second.table.isColumnHidden(at)
    assert {a.text(): a for a in second.columns_button.menu().actions()}[
        label].isChecked()
    scope = export_formats.scope_from_view(second, "search", "Search", model)
    assert label not in scope["hidden_columns"]
    # and the next search does not hide it again.
    second.show_results(search_loader.SearchQuery("x"), _empty_db_result())
    assert not second.table.isColumnHidden(at)


# --- the subtitle and scope note describe BOTH kinds of hit ----

def test_the_subtitle_splits_live_and_recovered_hits_and_says_what_row_means(win):
    win._on_recovery_loaded(_Engine([_carved("https://gone.example.test/%s" % TOKEN)]))
    live = {"table": "Container_1", "container_name": "History",
            "table_type": "History", "row_index": 4,
            "matched_columns": ["Url"], "match_in_blob": False,
            "match_value": "https://kept.example.test/%s" % TOKEN,
            "match_raw_type": "text", "match_raw": "x", "row": {"Url": "u"}}
    query = win._search_query_for(TOKEN, "")
    win._on_search_found(query, dict(_empty_db_result(), rows=search_loader.search_rows(
        [live], keyword=TOKEN)))
    view = win._ensure_view_built("search")
    text = view.header._subtitle.text()
    assert "2 hits" in text
    assert "1 in the database's own tables" in text
    assert "1 in recovered records" in text
    # What Row # means folds behind the note line.
    note = view.scope_note.text()
    assert "Deleted Records" in note          # what Row # means for those
    assert "WITHIN its table" in note         # and for a table hit


def test_the_scope_note_and_placeholder_name_the_recovered_records(win):
    view = win._ensure_view_built("search")
    assert "recovered records" in view.scope_note.text()
    assert "recovered records" in view.keyword_box.placeholderText()
