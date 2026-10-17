"""A LIVE record's Origin must not carry the CARVED basis badge.

evidence_model grades the field KEY "Origin" CARVED, because for a
carved row the value IS the recovery act. The record dialog asked for
the badge by key alone, so every live record showed "Live record" under
a CARV chip whose tooltip says "Recovered heuristically from unallocated
space or transaction logs" -- false for a row read from a live table.
"""
from webcache.shell.record_detail import RecordDetailDialog
from tests.test_detail_fields import carved_struct_row, history_row


def _origin_badge(dlg):
    for r, field in enumerate(dlg._rows):
        if field is not None and field.field == "Origin":
            item = dlg.table.item(r, 2)
            return item.text(), item.toolTip()
    raise AssertionError("no Origin row")


def test_a_live_records_origin_is_not_badged_carved(qtbot):
    dlg = RecordDetailDialog(history_row())
    try:
        short, tip = _origin_badge(dlg)
        assert short == "OBS"
        assert "Recovered heuristically" not in tip
        assert "live table" in tip
        origin_line = next(line for line in dlg.copy_tsv_text().splitlines()
                           if line.startswith("Origin\t"))
        assert origin_line.endswith("\tOBS")
    finally:
        dlg.close()


def test_a_carved_records_origin_keeps_the_carved_badge(qtbot):
    dlg = RecordDetailDialog(carved_struct_row())
    try:
        short, _tip = _origin_badge(dlg)
        assert short == "CARV"
    finally:
        dlg.close()
