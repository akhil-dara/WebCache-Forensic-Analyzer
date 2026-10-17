"""Which drive, and what kind of file -- the two questions an examiner
asks of File Access first ("was anything opened from removable media?",
"which documents?"), answerable until now only by reading every path.

Both are DERIVED from the decoded path beside them, never stored, and
both get the column funnel's value list for free once they are columns.
"""
from webcache.engine import url_intel
from webcache.shell import evidence_loader
from webcache.views.file_access import FILE_ACCESS_COLUMNS


def test_the_drive_is_the_volume_letter_or_the_share():
    assert url_intel.path_volume(r"C:\Users\x\a.pdf") == "C:"
    assert url_intel.path_volume(r"e:\transfer\b.zip") == "E:"
    assert url_intel.path_volume(r"\\server\share\dir\c.docx") == r"\\server\share"
    assert url_intel.path_volume("") == ""
    assert url_intel.path_volume("relative\d.txt") == ""


def test_the_file_type_is_the_last_segments_extension():
    assert url_intel.path_file_type(r"C:\Users\x\Report.PDF") == "pdf"
    assert url_intel.path_file_type(r"C:\Users\x\archive.tar.gz") == "gz"
    assert url_intel.path_file_type(r"C:\Users\x\Downloads") == ""
    assert url_intel.path_file_type(r"C:\Users\x.y\Downloads") == "", (
        "a dot in a FOLDER name is not the file's type")
    assert url_intel.path_file_type(r"C:\x\name.") == ""
    assert url_intel.path_file_type(r"C:\x\a.this-is-not-an-ext") == ""


class _Parser:
    def __init__(self, entries):
        self.all_entries = entries


def _entry(url):
    return {"Url": url, "CleanUrl": url, "IsLocalFile": True,
            "ContainerType": "History", "ContainerName": "History",
            "ContainerId": 1, "EntryId": 7}


def test_each_file_access_row_carries_drive_and_type():
    row = evidence_loader.file_access_rows_from_parser(
        _Parser([_entry("file:///E:/transfer/plan%20v2.xlsx")]))[0]
    assert row["Drive"] == "E:"
    assert row["FileType"] == "xlsx"


def test_both_are_columns_beside_the_decoded_path():
    keys = [c.key for c in FILE_ACCESS_COLUMNS]
    at = keys.index("LocalPath")
    assert keys[at + 1:at + 3] == ["Drive", "FileType"]


def test_a_version_number_in_a_folder_name_is_not_a_file_type():
    """Seen on a real exhibit: "File type" listed 11 and 12 -- folders
    named for a version ("Python 3.12"). Digits alone are read as a type
    only in the split-archive shape (.001), which is a file."""
    assert url_intel.path_file_type(r"C:\Tools\Python 3.12") == ""
    assert url_intel.path_file_type(r"C:\Tools\lib-2.0") == ""
    assert url_intel.path_file_type(r"C:\case\image.001") == "001"
    assert url_intel.path_file_type(r"C:\case\image.E01") == "e01"
