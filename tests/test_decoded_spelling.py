"""An examiner types what a path says, not how a URL encodes it.

Addresses are stored percent-encoded ("Tax%20docs"). A search for "tax
docs" found nothing in History's filter box, in a column condition and in
Search, while the encoded spelling found every one: a false negative an
examiner would never notice. Each matcher now also matches the decoded
spelling. What is shown and exported stays the stored text."""
import types

from webcache.engine.ese_parser import WebCacheParser
from webcache.shell import search_loader
from webcache.spellings import decoded_spelling
from webcache.widgets.column_spec import Column
from webcache.widgets.record_filter import Condition, RecordFilter

URL = "file:///F:/Case%20files/Tax%20docs/Form%2016.pdf"
OTHER = "file:///F:/Case%20files/Photos/beach.jpg"
COLUMNS = [Column("CleanUrl", "Address", 300, kind="url")]


def test_a_decoded_spelling_exists_only_for_percent_encoded_text():
    assert decoded_spelling(URL) == "file:///F:/Case files/Tax docs/Form 16.pdf"
    assert decoded_spelling("plain text") is None
    assert decoded_spelling("100% sure") is None      # not a %XX escape


def test_the_filter_box_finds_the_words_an_examiner_types():
    f = RecordFilter([{"CleanUrl": URL}, {"CleanUrl": OTHER}], COLUMNS)
    f.set_text("tax docs")
    assert [r["CleanUrl"] for r in f.visible()] == [URL]
    f.set_text("Tax%20docs")                          # the stored spelling still works
    assert [r["CleanUrl"] for r in f.visible()] == [URL]


def test_a_contains_condition_finds_them_too():
    f = RecordFilter([{"CleanUrl": URL}, {"CleanUrl": OTHER}], COLUMNS)
    f.set_condition("CleanUrl", Condition("contains", "tax docs"))
    assert [r["CleanUrl"] for r in f.visible()] == [URL]


class _Rec(dict):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._node = types.SimpleNamespace(data=b"\x00" * 16, key=b"")


class _Table:
    def __init__(self, rows):
        self.columns = [types.SimpleNamespace(name="Url")]
        self._rows = rows

    def records(self):
        for row in self._rows:
            yield _Rec(Url=row)


def test_search_across_tables_finds_them():
    parser = WebCacheParser()
    parser.db = types.SimpleNamespace(table=lambda name: _Table([URL, OTHER]))
    parser.table_names = ["Container_1"]
    hits = parser.search_all_tables("tax docs")
    assert len(hits) == 1, hits


def test_search_in_recovered_records_finds_them():
    from webcache.shell.record_kinds import K_CARVED_STRUCT
    rows = [{"_kind": K_CARVED_STRUCT, "_record": {"Url": u}, "CleanUrl": u}
            for u in (URL, OTHER)]
    hits = search_loader.recovered_hits("tax docs", rows)
    assert len(hits) == 1, hits


def test_does_not_contain_excludes_the_encoded_spelling_too():
    """A negated condition must hold for BOTH spellings, or the hidden one
    slips through."""
    f = RecordFilter([{"CleanUrl": URL}, {"CleanUrl": OTHER}], COLUMNS)
    f.set_condition("CleanUrl", Condition("does not contain", "tax docs"))
    assert [r["CleanUrl"] for r in f.visible()] == [OTHER]


def test_what_is_shown_stays_the_stored_text():
    from webcache.widgets.column_spec import display_text
    assert display_text(URL, COLUMNS[0]) == URL


# --- the other spellings an examiner types --------------------------------

from webcache.spellings import other_spellings  # noqa: E402

FILE_URL = "file:///C:/Users/jdoe/Downloads/Tax%20docs/x.pdf"
SEARCH_URL = "https://search.example.test/results?q=how+to+wipe&form=QBRE"


def test_a_file_url_is_also_spelled_as_the_windows_path():
    assert r"C:\Users\jdoe\Downloads\Tax docs\x.pdf" in other_spellings(FILE_URL)
    assert "\\\\server\\share\\a b.txt" in other_spellings(
        "file://server/share/a%20b.txt")


def test_a_plus_in_a_query_is_a_space_but_in_a_path_is_a_plus():
    assert any("q=how to wipe" in s for s in other_spellings(SEARCH_URL))
    assert all("a b" not in s for s in other_spellings("file:///C:/a+b/c.txt"))


def test_the_filter_box_finds_a_pasted_windows_path():
    f = RecordFilter([{"CleanUrl": FILE_URL}, {"CleanUrl": OTHER}], COLUMNS)
    f.set_text(r"Users\jdoe\Downloads")
    assert [r["CleanUrl"] for r in f.visible()] == [FILE_URL]


def test_the_filter_box_finds_search_terms_typed_with_spaces():
    f = RecordFilter([{"CleanUrl": SEARCH_URL}, {"CleanUrl": OTHER}], COLUMNS)
    f.set_text("how to wipe")
    assert [r["CleanUrl"] for r in f.visible()] == [SEARCH_URL]


def test_search_across_tables_finds_a_pasted_windows_path():
    parser = WebCacheParser()
    parser.db = types.SimpleNamespace(table=lambda name: _Table([FILE_URL, OTHER]))
    parser.table_names = ["Container_1"]
    assert len(parser.search_all_tables(r"downloads\tax docs")) == 1
