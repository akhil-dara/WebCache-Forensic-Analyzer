"""FileAccessView: local files opened through the browser, and downloads
the iedownload container recorded -- two structurally different record
sets sharing one table via RecordsView's segmented switcher.

Built entirely on RecordsView (test_records_view.py already proves the
base class's own generic contract); this file proves only what
FileAccessView itself declares -- its two RecordSets' columns, that no
quick filters means no chip row, and its header/caveat text -- against
rows shaped the way evidence_loader.file_access_rows_from_parser() /
downloads_rows_from_parser() actually produce them (see
test_evidence_loader.py for that shape's own tests).
"""
import datetime

from webcache.views.file_access import (DOWNLOAD_COLUMNS,
                                        FILE_ACCESS_COLUMNS, FileAccessView)


def _fa_row(**overrides):
    base = {
        "ModifiedTime": datetime.datetime(2024, 6, 1, 12, 0, 0,
                                          tzinfo=datetime.timezone.utc),
        "AccessedLocal": datetime.datetime(2024, 6, 1, 17, 30, 0),
        "VisitCountBest": 3,
        "CleanUrl": r"file:///C:/Users/alice/Desktop/notes.txt",
        "Origin": "Live record",
        "Source": "",
        "FileSize": 1024,
        "ContainerId": 3,
        "ContainerName": "Content",
        "EntryId": 7,
        "AccessedTime": datetime.datetime(2024, 6, 1, 12, 0, 0,
                                          tzinfo=datetime.timezone.utc),
        "CreationTime": datetime.datetime(2024, 5, 1, 9, 0, 0,
                                          tzinfo=datetime.timezone.utc),
    }
    base.update(overrides)
    return base


def _dl_row(**overrides):
    base = {
        "DownloadTime": datetime.datetime(2024, 3, 2, 9, 0, 0,
                                          tzinfo=datetime.timezone.utc),
        "DownloadPath": r"D:\evidence\case9\bill.pdf",
        "DownloadSize": 9001,
        "DownloadSourceUrl": "https://portal.example/bill.pdf",
        "Origin": "Live record",
        "Source": "",
    }
    base.update(overrides)
    return base


# --- columns -----------------------------------------------------------

def test_file_access_columns_match_the_spec():
    keys = [c.key for c in FILE_ACCESS_COLUMNS]
    assert keys == ["ModifiedTime", "AccessedLocal", "VisitCountBest",
                    "CleanUrl", "LocalPath", "Drive", "FileType",
                    "SameVisit", "Copies", "Origin",
                    "FileSize",
                    "ContainerId",
                    "ContainerName", "EntryId", "AccessedTime", "CreationTime",
                    "Offset", "Page", "Method"]


def test_download_columns_match_the_spec():
    keys = [c.key for c in DOWNLOAD_COLUMNS]
    assert keys == ["DownloadTime", "DownloadPath", "DownloadSize",
                    "DownloadSourceUrl", "DownloadConfidence"]


def test_local_file_path_column_uses_the_path_kind_not_url():
    col = next(c for c in FILE_ACCESS_COLUMNS if c.key == "CleanUrl")
    assert col.kind == "path"
    assert col.is_link is False


def test_saved_to_column_uses_the_path_kind_not_url():
    col = next(c for c in DOWNLOAD_COLUMNS if c.key == "DownloadPath")
    assert col.kind == "path"
    assert col.is_link is False


def test_size_columns_use_the_size_kind():
    fa_size = next(c for c in FILE_ACCESS_COLUMNS if c.key == "FileSize")
    dl_size = next(c for c in DOWNLOAD_COLUMNS if c.key == "DownloadSize")
    assert fa_size.kind == "size"
    assert dl_size.kind == "size"


def test_source_url_column_uses_the_url_kind():
    col = next(c for c in DOWNLOAD_COLUMNS if c.key == "DownloadSourceUrl")
    assert col.kind == "url"


# --- the view itself -----------------------------------------------------

def test_it_opens_on_the_file_access_segment_by_default(qtbot):
    v = FileAccessView()
    v.set_records_for("file_access", [_fa_row()])
    v.set_records_for("downloads", [_dl_row()])
    qtbot.addWidget(v)
    assert [c.key for c in v.table.model().columns] == \
        [c.key for c in FILE_ACCESS_COLUMNS]
    assert v.table.model().rowCount() == 1


def test_declares_two_named_segments(qtbot):
    v = FileAccessView()
    qtbot.addWidget(v)
    assert set(v._switcher_buttons.keys()) == {"file_access", "downloads"}


def test_switching_to_downloads_shows_the_download_columns_and_rows(qtbot):
    v = FileAccessView()
    v.set_records_for("file_access", [_fa_row(), _fa_row()])
    v.set_records_for("downloads", [_dl_row()])
    qtbot.addWidget(v)

    v._switch_segment("downloads")

    assert [c.key for c in v.table.model().columns] == \
        [c.key for c in DOWNLOAD_COLUMNS]
    assert v.table.model().rowCount() == 1


def test_the_chips_are_history_s_two_visit_chips(qtbot):
    """Repeated carves and MSHist twins doubled most rows on a real
    machine; the chips are History's own, off by default."""
    v = FileAccessView()
    qtbot.addWidget(v)
    assert [q.attr for q in v._quick_filters] == [
        "chip_hide_copies", "chip_one_row_per_visit"]
    assert not v.chip_hide_copies.isChecked()
    assert not v.chip_one_row_per_visit.isChecked()


def test_header_and_caveat_are_reachable(qtbot):
    v = FileAccessView()
    qtbot.addWidget(v)
    assert v.header is not None
    v.set_caveat("Shows files opened through the browser.")
    assert v.caveat is not None


def test_export_button_is_present(qtbot):
    v = FileAccessView()
    v.set_records_for("file_access", [_fa_row()])
    qtbot.addWidget(v)
    with qtbot.waitSignal(v.exportRequested, timeout=1000):
        v.export_button.click()


def test_row_values_render_for_the_file_access_segment(qtbot):
    v = FileAccessView()
    v.set_records_for("file_access", [_fa_row(CleanUrl="file:///D:/case/x.jpg")])
    qtbot.addWidget(v)
    row = v.table.model().row_at(0)
    assert row["CleanUrl"] == "file:///D:/case/x.jpg"


def test_row_values_render_for_the_downloads_segment(qtbot):
    v = FileAccessView()
    v.set_records_for("downloads", [_dl_row(DownloadPath=r"E:\out\file.zip")])
    qtbot.addWidget(v)
    v._switch_segment("downloads")
    row = v.table.model().row_at(0)
    assert row["DownloadPath"] == r"E:\out\file.zip"


# --- the genuine empty state: DEFECT 2's own repro, "Downloads (0)" -------

def test_an_exhibit_with_no_downloads_shows_a_real_empty_state_not_a_blank_void(qtbot):
    """DEFECT 2 itself: switching to "Downloads (0)" used to paint column
    headers over roughly 600px of nothing, with no statement of what
    happened. An examiner must be able to tell "this exhibit has none of
    these" from "the decode failed" or "a filter is hiding everything"."""
    v = FileAccessView()
    v.set_records_for("file_access", [_fa_row()])
    v.set_records_for("downloads", [])
    qtbot.addWidget(v)

    v._switch_segment("downloads")

    assert v.table.showing_genuine_empty_state() is True
    assert "Downloads" in v.table.empty_state_text()


def test_an_exhibit_with_no_file_access_records_shows_its_own_wording(qtbot):
    v = FileAccessView()
    v.set_records_for("file_access", [])
    v.set_records_for("downloads", [_dl_row()])
    qtbot.addWidget(v)

    assert v.table.showing_genuine_empty_state() is True
    assert "file-access" in v.table.empty_state_text().lower()


def test_downloads_empty_state_wording_differs_from_file_access(qtbot):
    """Each segment names ITSELF, not the other -- a shared, generic
    sentence would not tell an examiner which container is actually
    empty."""
    v = FileAccessView()
    v.set_records_for("file_access", [])
    v.set_records_for("downloads", [])
    qtbot.addWidget(v)

    fa_text = v.table.empty_state_text()
    v._switch_segment("downloads")
    dl_text = v.table.empty_state_text()

    assert fa_text != dl_text
    assert "file-access" in fa_text.lower()
    assert "downloads" in dl_text.lower()
