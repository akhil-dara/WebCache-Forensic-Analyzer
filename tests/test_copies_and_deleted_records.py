"""Duplicate carved copies, deleted-record stubs and the Deleted Records
view's method chips."""
import datetime
import types

import pytest

from webcache.shell import recovery_loader
from webcache.shell.record_kinds import K_TOMBSTONE
from webcache.views.history import HistoryView
from webcache.views.recovery import RecoveryView

UTC = datetime.timezone.utc
_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=UTC)
FT = int((datetime.datetime(2024, 6, 29, 10, tzinfo=UTC) - _EPOCH)
         .total_seconds()) * 10_000_000


def carved(url, offset, when=FT):
    return {"Url": url, "CleanUrl": url, "ContainerType": "History",
            "RecoverySource": "Structured record reconstruction",
            "Source": "WebCacheV01.dat", "Offset": offset, "Page": 1,
            "Confidence": "high", "ModifiedTime_raw": when}


def _engine(records, stubs=()):
    return types.SimpleNamespace(structured_records=list(records),
                                 all_artifacts=lambda: [],
                                 tombstones=list(stubs))


COPIES = [carved("https://dup.example.test/", 4096 * i) for i in (1, 2, 3)]
UNIQUE = carved("https://one.example.test/", 4096 * 9)


def test_identical_carved_copies_are_counted_on_every_member():
    rows = recovery_loader.carved_history_rows(_engine(COPIES + [UNIQUE]))
    copies = [r["Copies"] for r in rows if "dup" in r["CleanUrl"]]
    assert copies == ["3 copies (same URL, time and container)",
                      "copy 2 of 3", "copy 3 of 3"]
    assert next(r for r in rows if "one" in r["CleanUrl"])["Copies"] == ""


def test_hide_duplicate_copies_keeps_one_of_each(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(recovery_loader.carved_history_rows(
        _engine(COPIES + [UNIQUE])))
    assert not view.chip_hide_copies.isChecked()
    view.chip_hide_copies.click()
    assert view.table.model().rowCount() == 2


STUB = {"Table": "Container_11", "KeyColumns": ("UrlHash", "EntryId"),
        "KeyValues": (111, 7), "Source": "WebCacheV01.dat",
        "Offset": 8192, "Page": 2, "ContainerType": "History"}


def test_a_stub_states_its_key_in_its_own_column():
    rows = recovery_loader.deleted_records_rows(_engine([], [STUB]))
    stub = next(r for r in rows if r["_kind"] == K_TOMBSTONE)
    assert stub["Key"] == "UrlHash 111, EntryId 7"
    assert stub["Confidence"] == "exact"


@pytest.fixture
def recovery(qtbot):
    v = RecoveryView()
    qtbot.addWidget(v)
    # 1450, not 1300: the substitute font the offscreen platform measures
    # with is wider than Segoe UI, and the URL may take a hidden column's
    # width only from what File..Confidence leave spare. The real-font fit
    # at 1328 is tests/_recovery_fit_probe.py's job.
    v.resize(1450, 800)
    v.set_records(recovery_loader.deleted_records_rows(
        _engine(COPIES + [UNIQUE], [STUB])))
    v.show()
    qtbot.waitExposed(v)
    return v


def test_a_constant_column_is_hidden_and_named_and_the_url_widens(recovery):
    keys = [c.key for c in recovery.table.model().columns]
    assert recovery.table.isColumnHidden(keys.index("Source"))
    assert "File" in recovery.identical_chip.text()
    assert recovery.table.columnWidth(keys.index("CleanUrl")) >= 174 + 130


def test_the_method_chips_filter_by_kind(recovery):
    recovery.method_buttons["stubs"].click()
    model = recovery.table.model()
    assert model.rowCount() == 1
    assert model.row_at(0)["_kind"] == K_TOMBSTONE
    recovery.method_buttons["all"].click()
    assert model.rowCount() == 5


def test_timestamp_says_which_clock(recovery):
    labels = [c.label for c in recovery.table.model().columns]
    assert "Timestamp (UTC)" in labels


def test_after_a_scan_the_button_offers_to_run_again_quietly(recovery):
    assert recovery.recover_button.text() == "Run recovery again…"
    assert not recovery.recover_button.property("accent")


def test_a_stubs_dialog_is_titled_as_a_stub(qtbot):
    from webcache.shell.record_detail import RecordDetailDialog
    row = next(r for r in recovery_loader.deleted_records_rows(
        _engine([], [STUB])) if r["_kind"] == K_TOMBSTONE)
    dlg = RecordDetailDialog(row)
    qtbot.addWidget(dlg)
    assert dlg.carved_chip.text() == "DELETED-RECORD STUB"
    assert "UrlHash 111, EntryId 7" in dlg.identity_label.text()


def test_the_sidecar_names_the_columns_hidden_as_identical(recovery):
    from webcache.shell import export_formats
    scope = export_formats.scope_from_view(
        recovery, "recovery", "Deleted Records", recovery.table.model())
    assert "File" in scope["hidden_columns"]
    # A view preference only: the file still lists every declared column.
    assert "File" in scope["columns"]
    # Hiding identical columns is not a column's own hidden flag; only an
    # optional column ("Timestamp basis") starts hidden, by declaration.
    assert not any(c.hidden for c in recovery.table.model().columns
                   if not c.optional)


def test_a_live_row_without_copies_survives_the_chip(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    live = {"CleanUrl": "https://live.example.test/", "Origin": "Live record"}
    view.set_records([live] + recovery_loader.carved_history_rows(
        _engine(COPIES)))
    view.chip_hide_copies.click()
    assert view.table.model().rowCount() == 2


def test_a_narrow_view_does_not_push_confidence_off_for_the_widened_url(
        qtbot):
    v = RecoveryView()
    qtbot.addWidget(v)
    v.resize(900, 800)
    v.set_records(recovery_loader.deleted_records_rows(
        _engine(COPIES + [UNIQUE], [STUB])))
    v.show()
    qtbot.waitExposed(v)
    header = v.table.horizontalHeader()
    keys = [c.key for c in v.table.model().columns]
    url = keys.index("CleanUrl")
    assert header.sectionSize(url) < 174 + 130, (
        "no spare room, so the URL did not take the hidden File width")


def test_hiding_copies_says_which_exports_keep_them(qtbot):
    """It said "still counted and exported", but Export view writes the
    rows on screen (a real History export: 589 of 790, the copies left
    out); only the full case exports keep every row."""
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(recovery_loader.carved_history_rows(
        _engine(COPIES + [UNIQUE])))
    view.chip_hide_copies.click()
    text = view.count_label.text()
    assert "2 duplicate copies hidden" in text
    assert "left out of Export view; kept in the full case exports" in text
    view.chip_hide_copies.click()
    assert "hidden" not in view.count_label.text()


LONG_CAVEAT = ("A long caveat sentence that must fold behind the note "
               "expander and never take the count line with it. " * 6)


def test_the_count_line_never_folds_when_a_long_caveat_does(qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.resize(760, 700)
    view.set_records(recovery_loader.carved_history_rows(
        _engine(COPIES + [UNIQUE])), note=LONG_CAVEAT)
    view.show()
    qtbot.waitExposed(view)
    view.chip_hide_copies.click()
    count = view.count_label
    assert "duplicate copies hidden" in count.text()
    assert LONG_CAVEAT.strip()[:40] not in count.text()
    assert count.maximumHeight() >= count.heightForWidth(count.width()), (
        "the count line is clipped")
    # the caveat is what folds, and it is still whole and reachable
    assert LONG_CAVEAT.strip() in view.note_label.text()
    assert view.note_line.toggle.isVisible()


def test_copies_sits_right_after_the_address_with_room_for_its_heading(
        qtbot):
    view = HistoryView()
    qtbot.addWidget(view)
    view.set_records(recovery_loader.carved_history_rows(
        _engine(COPIES + [UNIQUE])))
    columns = view.table.model().columns
    keys = [c.key for c in columns]
    # Right after the Address and its "Same visit as" link.
    assert keys.index("Copies") == keys.index("SameVisit") + 1
    assert keys.index("SameVisit") == keys.index("CleanUrl") + 1
    copies = columns[keys.index("Copies")]
    heading = view.table.fontMetrics().horizontalAdvance("Copies")
    assert copies.width >= heading + 24
