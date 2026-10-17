"""No evidence value is elided anywhere.

Elision survives only on chrome, named below with the reason and where
its full text lives.
"""
import pathlib

from PySide6.QtCore import Qt

from webcache.shell.record_detail import RecordDetailDialog
from webcache.widgets.column_spec import Column
from webcache.widgets.filter_popup import FilterPopup
from webcache.widgets.record_model import RecordTableModel
from webcache.widgets.wrapping_text import WrappingText
from tests.test_detail_fields import history_row

ROOT = pathlib.Path(__file__).resolve().parent.parent / "webcache"

ALLOWED_ELIDERS = {
    "main_window.py": "the status bar line; its full text is its tooltip",
    "record_detail.py": "ElidingButton captions; the full caption is the tooltip",
    "sidebar.py": "nav names; the full name and count are the row tooltip",
}

LONG_TOKEN = ("https://example.test/reports/quarterly/2026/full-detail-view"
              "?case=alpha&examiner=none&token=" + "a" * 120)


def _sources():
    return [p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_eliding_label_exists_anywhere():
    offenders = [p.name for p in _sources()
                 if "ElidingLabel" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_elision_survives_only_on_chrome():
    offenders = [p.name for p in _sources()
                 if "elidedText(" in p.read_text(encoding="utf-8")
                 and p.name not in ALLOWED_ELIDERS]
    assert offenders == []


#: The only places a view may be switched to ElideRight: the examiner's own
#: Wrap toggle turned off (a visible ellipsis; tooltip, copy and dialog
#: still carry the whole value). Anything else is an elider.
ELIDE_ON_WRAP_OFF = {"records_table.py", "browser.py"}


def test_a_view_elides_only_through_the_wrap_toggle():
    """setTextElideMode(Qt.ElideRight) outside a
    set_wrap is an elider this file did not see; every other call must
    say ElideNone."""
    offenders = []
    for path in _sources():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "setTextElideMode(" not in line:
                continue
            if "ElideRight" in line:
                if not (path.name in ELIDE_ON_WRAP_OFF and "_wrap" in line):
                    offenders.append("%s:%d" % (path.name, n))
            elif "ElideNone" not in line:
                offenders.append("%s:%d" % (path.name, n))
    assert offenders == []


def test_wrapping_text_wraps_a_single_token_and_copies_it_exactly(qtbot):
    w = WrappingText(LONG_TOKEN)
    qtbot.addWidget(w)
    w.resize(300, 10)
    w.show()
    qtbot.waitExposed(w)
    assert w.full_text() == w.toPlainText() == LONG_TOKEN
    assert w.height() >= 2 * w.fontMetrics().lineSpacing(), "did not wrap"
    assert w.minimumSizeHint().width() < 100, "puts a floor under its parent"


def test_wrapping_text_is_selectable_and_never_markup(qtbot):
    markup = "<b>bold</b><img src='x'>"
    w = WrappingText(markup)
    qtbot.addWidget(w)
    assert w.toPlainText() == markup
    assert w.textInteractionFlags() & Qt.TextSelectableByMouse
    assert w.isReadOnly()


def test_the_record_dialog_identity_line_wraps_and_stays_whole(qtbot):
    dlg = RecordDetailDialog(history_row(CleanUrl=LONG_TOKEN))
    try:
        dlg.resize(1100, 700)
        dlg.show()
        qtbot.waitExposed(dlg)
        assert isinstance(dlg.identity_label, WrappingText)
        assert LONG_TOKEN in dlg.identity_label.full_text()
        assert dlg.identity_label.height() >= \
            2 * dlg.identity_label.fontMetrics().lineSpacing()
    finally:
        dlg.close()


def test_the_filter_popup_value_list_never_elides(qtbot):
    col = Column("CleanUrl", "Address", 400, kind="url")
    model = RecordTableModel([col], [{"CleanUrl": LONG_TOKEN}])
    popup = FilterPopup(model, col)
    qtbot.addWidget(popup)
    assert popup.values_list.wordWrap()
    assert popup.values_list.textElideMode() == Qt.ElideNone


def test_the_filter_description_line_wraps(qtbot):
    from webcache.views.history import HistoryView
    view = HistoryView()
    qtbot.addWidget(view)
    assert view._filter_desc_label.wordWrap()


def test_a_long_value_list_lays_out_without_stalling(qtbot):
    from webcache.widgets.stall_detector import StallDetector
    col = Column("CleanUrl", "Address", 400, kind="url")
    rows = [{"CleanUrl": "https://example.test/%d/%s" % (i, "x" * 60)}
            for i in range(20_000)]
    popup = FilterPopup(RecordTableModel([col], rows), col)
    qtbot.addWidget(popup)
    popup.show()
    qtbot.waitExposed(popup)
    with StallDetector(threshold_ms=150) as det:
        qtbot.wait(1500)
    assert not det.stalls, "worst gap %.0f ms" % det.worst_gap_ms
