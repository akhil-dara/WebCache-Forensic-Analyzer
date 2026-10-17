"""The provenance note must describe the timestamp cells
as they are written -- YYYY-MM-DD HH:MM:SS[.ffffff], a date cell in XLSX --
not claim RFC 3339, whose form sits in each *_rfc column. The app's note
and the page's note say it word for word."""
import inspect

from webcache.shell import export_formats, html_package

SENTENCE = ("UTC timestamps are written as YYYY-MM-DD HH:MM:SS[.ffffff] "
            "(a date cell in XLSX); the RFC 3339 form of each is in its "
            "*_rfc column.")


def test_the_app_note_states_the_written_shape_not_rfc_3339():
    source = inspect.getsource(export_formats)
    assert "UTC in RFC 3339" not in source
    assert "YYYY-MM-DD HH:MM:SS[.ffffff]" in source
    assert "*_rfc column" in source


def test_the_page_note_says_the_same_words():
    page = (html_package._ASSET_DIR / "export_csv.js").read_text("utf-8")
    assert "UTC in RFC 3339" not in page
    assert "YYYY-MM-DD HH:MM:SS[.ffffff]" in page
    assert "*_rfc column" in page
