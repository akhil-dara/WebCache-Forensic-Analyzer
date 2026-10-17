"""Any text an investigator can see, they can select and copy.

Grids (RecordsTable) and the record dialog already give this; every other
label in the shell and the views did not, and there was nothing enforcing
it beyond remembering to set the flag on every new QLabel. This file
walks the REAL widget tree of every top-level surface -- the main window
across every nav destination, and every standalone dialog -- and fails
loudly, by parent class and text, for any visible non-empty QLabel that
is not selectable.

Mouse-only is the bar (see webcache/widgets/copyable.py): keyboard
selectability would pull every caption into the Tab chain, which is a
regression this file's own Tab-chain tests below guard against.
"""
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QLabel, QWidget

from webcache.provenance import EvidenceSet
from webcache.shell import theme
from webcache.shell.open_evidence import OpenEvidenceDialog
from webcache.shell.main_window import ExplainDialog, MainWindow
from webcache.shell.record_detail import RecordDetailDialog
from webcache.shell.table_row_detail import TableRowDialog
from webcache.widgets import copyable, hex_view

from tests.fixtures import make_rows
from tests.test_detail_fields import history_row
from tests.test_table_row_view import _page as table_row_page

_EVIDENCE_PATH = r"C:\case\WebCacheV01.dat"


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                        {_EVIDENCE_PATH: "a" * 64})


def _uncopyable(root):
    bad = []
    for label in root.findChildren(QLabel):
        if not label.text().strip() or label.property(copyable.DECORATIVE):
            continue
        if not label.isVisibleTo(root):
            continue
        if not label.textInteractionFlags() & Qt.TextSelectableByMouse:
            bad.append("%s: %r" % (type(label.parent()).__name__, label.text()[:40]))
    return bad


@pytest.fixture(autouse=True)
def _settings_go_somewhere_disposable(tmp_path, monkeypatch):
    """No test in this file may touch the real settings.json -- same
    reason every dialog-building test file in this suite gives one of
    these: a persisted geometry or preference from a throwaway window
    must never land in the checkout's own settings.json."""
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")


# --- the main window, across every nav destination ----------------------

def test_every_view_label_is_copyable(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    for key in w.nav_keys:
        w.go_to(key)
    assert _uncopyable(w) == []


def test_every_view_label_is_copyable_with_evidence_loaded(qtbot):
    """The empty-state walk above only reaches labels visible with no
    evidence open. Dashboard figures, count lines and the provenance
    strip only exist once a case is loaded, so this repeats the walk with
    a real (fixture) evidence set applied through the same
    `_on_evidence_loaded` path the application itself uses."""
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    w._on_evidence_loaded({"rows": make_rows(20), "parser": None},
                          _fake_evidence_set())
    for key in w.nav_keys:
        w.go_to(key)
    assert _uncopyable(w) == []


def test_a_header_offers_its_column_name(qtbot):
    """The examiner chose to keep right-click a direct, one-click
    open of FilterPopup (no intermediate header menu) and put "Copy
    column name" INSIDE the popup instead -- see
    FilterPopup.copy_name_button."""
    from webcache.views.history import HistoryView
    v = HistoryView()
    qtbot.addWidget(v)
    v.set_records([{"CleanUrl": "https://example.test/a"}])
    header = v.table.horizontalHeader()
    header.customContextMenuRequested.emit(QPoint(header.sectionPosition(0) + 5, 5))
    popup = v.table._filter_popup
    assert popup is not None
    assert popup.copy_name_button.toolTip() == "Copy column name"


# --- standalone dialogs, built the way their own test files build them ---

def test_explain_dialog_labels_are_copyable(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    dlg = ExplainDialog(w, "Some explanatory text an investigator reads.")
    qtbot.addWidget(dlg)
    assert _uncopyable(dlg) == []


def test_consent_dialog_labels_are_copyable(qtbot, tmp_path):
    evidence = tmp_path / "WebCacheV01.dat"
    evidence.write_bytes(b"not a real ese db")
    d = OpenEvidenceDialog(str(evidence))
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    assert _uncopyable(d) == []


@pytest.fixture
def _record_dialog_build(qtbot):
    """A RecordDetailDialog torn down by hand: WA_DeleteOnClose destroys
    the C++ object on close and pytest-qt's own teardown would then call
    close() on a dead pointer -- see tests/test_record_detail_room.py's
    own `build` fixture, which this copies rather than diverges from."""
    made = []

    def _build(row, w=1279, h=724):
        parent = QWidget()
        made.append(parent)
        parent.resize(w + 260, h + 120)
        parent.show()
        dlg = RecordDetailDialog(row, parent)
        made.append(dlg)
        dlg.resize(w, h)
        dlg.show()
        qtbot.waitExposed(dlg)
        dlg.resize(w, h)
        qtbot.wait(20)
        return dlg

    yield _build
    for widget in reversed(made):
        try:
            widget.close()
        except RuntimeError:
            pass


def test_record_detail_dialog_labels_are_copyable(_record_dialog_build):
    dlg = _record_dialog_build(history_row())
    assert _uncopyable(dlg) == []


@pytest.fixture
def _table_row_dialog_build(qtbot):
    """Same hand-teardown reason as the record dialog -- see
    tests/test_table_row_view.py's own `build` fixture."""
    made = []

    def _build(columns, rows, row=0, w=1279, h=724, **kw):
        page = table_row_page(columns, rows)
        parent = QWidget()
        made.append(parent)
        parent.resize(w + 260, h + 120)
        parent.show()
        dialog = TableRowDialog(page["columns"], page["rows"][row], parent,
                                table=page["display_name"], **kw)
        made.append(dialog)
        dialog.resize(w, h)
        dialog.show()
        qtbot.waitExposed(dialog)
        dialog.resize(w, h)
        qtbot.wait(20)
        return dialog

    yield _build
    for widget in reversed(made):
        try:
            widget.close()
        except RuntimeError:
            pass


def test_table_row_dialog_labels_are_copyable(_table_row_dialog_build):
    columns = ["Name", "Value"]
    rows = [{"Name": "example.dat", "Value": "hello"}]
    dlg = _table_row_dialog_build(columns, rows)
    assert _uncopyable(dlg) == []


def test_blob_pane_labels_are_copyable(qtbot):
    from webcache.shell import blob_source
    source = blob_source.MemoryBlob("Response headers", b"abc" * 40,
                                    "ResponseHeaders_raw")
    widget = hex_view.BlobPane(source)
    qtbot.addWidget(widget)
    widget.show()
    assert _uncopyable(widget) == []


# --- Tab chain must not grow ---------------------------------------------

def _tab_chain_length(start):
    """Count widgets visited by repeated focusNextChild() from `start`
    until it cycles back, per the task's own correction: keyboard
    selectability was rejected specifically because it would make every
    caption a Tab stop, so this is the regression test for that."""
    seen = []
    w = start
    for _ in range(500):
        seen.append(w)
        nxt = w.nextInFocusChain()
        if nxt is None or nxt is start or nxt in seen:
            break
        w = nxt
    return len(seen)


def test_main_window_tab_chain_does_not_grow(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    w.show()
    qtbot.waitExposed(w)
    focus_widgets = [ch for ch in w.findChildren(QWidget)
                     if ch.focusPolicy() != Qt.NoFocus]
    labels_with_focus = [ch for ch in focus_widgets if isinstance(ch, QLabel)]
    assert labels_with_focus == [], (
        "label(s) unexpectedly accept keyboard focus, which would pull "
        "them into the Tab chain: %s"
        % [(type(l.parent()).__name__, l.text()[:40]) for l in labels_with_focus])


def test_record_detail_dialog_tab_chain_does_not_grow(_record_dialog_build):
    dlg = _record_dialog_build(history_row())
    labels_with_focus = [ch for ch in dlg.findChildren(QLabel)
                         if ch.focusPolicy() != Qt.NoFocus]
    assert labels_with_focus == [], (
        "provenance-strip label(s) unexpectedly accept keyboard focus: %s"
        % [(type(l.parent()).__name__, l.text()[:40]) for l in labels_with_focus])
