"""The wiring for HTTP Headers: the nav key "headers" builds a real view
with a real count, opening evidence populates it, a recovery scan merges
carved header records into it, and both of its export buttons reach a
writer rather than a navigation.

Mirrors test_indicators_wiring.py's shape and test_export_wiring.py's
synchronous runner, so the pair export is proved by OPENING THE FILE and
counting its rows -- the button's number is a promise, and the only way to
prove a promise is to check what was delivered.
"""
import csv
import os

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog

from webcache.engine import ese_parser
from webcache.provenance import CARVED_ORIGIN, EvidenceSet
from webcache.shell import headers_loader as H
from webcache.shell.export_runner import ExportWorker
from webcache.shell.main_window import MainWindow, _NO_COUNT_KEYS
from webcache.views.headers import HeadersView

_EVIDENCE_PATH = "C:/case/WebCacheV01.dat"

RESP = (b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/html\r\n"
        b"Set-Cookie: a=1\r\n"
        b"Set-Cookie: b=2\r\n\r\n")
REQ = b"Accept: */*\r\n\r\n"


def _entry(entry_id=1, **overrides):
    base = {"ContainerType": "Content", "ContainerId": 5, "EntryId": entry_id,
            "ContainerName": "Content",
            "CleanUrl": "https://example%d.test/a" % entry_id,
            "ModifiedTime_raw": 133546220420000000,
            "ResponseHeaders_raw": RESP, "RequestHeaders_raw": REQ,
            "ResponseHeaders": ese_parser.decode_content_headers(RESP),
            "RequestHeaders": ese_parser.decode_content_headers(REQ)}
    base.update(overrides)
    return base


def _sps_entry():
    """A History record whose blob is a property store. It must not be in
    this view, and the count must not pretend it is."""
    return {"ContainerType": "History", "ContainerId": 3, "EntryId": 90,
            "CleanUrl": "https://example.test/visited",
            "ModifiedTime_raw": 133546220420000000,
            "ResponseHeaders_raw": b"\x01\x00\x00\x00propstore",
            "BlobClass": "sps", "SPS_VisitCount": 2}


class _FakeParser:
    db_path = _EVIDENCE_PATH
    source_hashes = {"WebCacheV01.dat": "0" * 64}

    def __init__(self, entries=()):
        self.all_entries = list(entries)
        self.db = None
        self.containers_meta = []
        self.container_type_map = {}


class _StubEngine:
    def __init__(self, structured_records=None, artifacts=None):
        self.structured_records = list(structured_records or [])
        self._artifacts = list(artifacts or [])

    def all_artifacts(self):
        return self._artifacts


class _FakeConsentDialog:
    recover_deleted = False
    def __init__(self, path, parent=None):
        import hashlib
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
        self.evidence_set = EvidenceSet([path], {path: 1}, {path: digest})

    def exec(self):
        from PySide6.QtWidgets import QDialog
        return QDialog.Accepted

    def deleteLater(self):
        pass


class _SyncExportRunner(QObject):
    progress = Signal(str)
    written = Signal(list)
    failed = Signal(str)
    jobs = []

    def start(self, job):
        _SyncExportRunner.jobs.append(job)
        worker = ExportWorker(job)
        worker.progress.connect(self.progress)
        worker.written.connect(self.written)
        worker.failed.connect(self.failed)
        worker.run()

    def cancel(self):
        pass


@pytest.fixture(autouse=True)
def _reset_jobs():
    _SyncExportRunner.jobs = []
    yield


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    from webcache import paths
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    monkeypatch.setattr(paths, "cases_dir", lambda: case_dir)
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1600, 900)
    return w


@pytest.fixture
def exhibit(tmp_path):
    """The evidence directory, kept SEPARATE from where exports go.

    Nothing an export writes may land in the evidence folder, and the
    refusal that enforces it is a MODAL dialog -- so a test that writes
    beside its own exhibit does not fail, it hangs. test_export_wiring.py
    's own fixture says the same thing for the same reason.
    """
    d = tmp_path / "exhibit"
    d.mkdir()
    return d


@pytest.fixture
def outbox(tmp_path):
    d = tmp_path / "exports"
    d.mkdir()
    return d


def _nav_count(win):
    """The nav badge as painted -- the same reach every other
    sidebar-count test in this suite makes."""
    text = win.sidebar._rows["headers"].count_label.text()
    return int(text.replace(",", "")) if text.strip("-–") else None


def _headers_view(win):
    return win._ensure_view_built("headers")


def _fake_evidence_set():
    return EvidenceSet([_EVIDENCE_PATH], {_EVIDENCE_PATH: 1},
                       {_EVIDENCE_PATH: "a" * 64})


def _open(win, entries):
    win._on_evidence_loaded({"rows": [], "parser": _FakeParser(entries)},
                            _fake_evidence_set())


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


# --- a real view with a real count ----------------------------------------

def test_headers_is_a_real_view_not_a_placeholder(win):
    assert isinstance(_headers_view(win), HeadersView)


def test_headers_no_longer_claims_it_has_no_number_to_show(win):
    """It is a record-set view now, and a permanent dash on the nav rail
    would say there is nothing here to count."""
    assert "headers" not in _NO_COUNT_KEYS


def test_the_view_is_reachable(win):
    win.go_to("headers")
    assert win.current_key == "headers"


# --- opening evidence -----------------------------------------------------

def test_opening_evidence_populates_headers(win):
    _open(win, [_entry(1), _entry(2)])
    assert _headers_view(win).table.model().rowCount() == 2


def test_the_sps_record_never_reaches_the_table_or_the_count(win):
    _open(win, [_entry(1), _sps_entry()])
    view = _headers_view(win)
    assert view.table.model().rowCount() == 1
    assert _nav_count(win) == 1


def test_the_nav_badge_carries_the_row_count(win):
    _open(win, [_entry(1), _entry(2), _entry(3)])
    assert _nav_count(win) == 3


def test_the_count_line_says_live_records_only_before_a_scan(win):
    """THE CARVED-RECORDS RULE: no carve runs at open time, so this row
    set is live records only and the line an examiner reads must say so."""
    _open(win, [_entry(1)])
    text = _headers_view(win).line_text().lower()
    assert "live records only" in text


def test_a_parser_with_no_entries_leaves_the_view_empty_not_crashed(win):
    win._on_evidence_loaded({"rows": [], "parser": object()},
                            _fake_evidence_set())
    assert _headers_view(win).table.model().rowCount() == 0


# --- the carved merge -----------------------------------------------------

def test_a_recovery_scan_merges_carved_header_records(win):
    _open(win, [_entry(1)])
    carved = _entry(77, Source="transaction log", RecoverySource="log")
    win._on_recovery_loaded(_StubEngine([carved]))
    view = _headers_view(win)
    assert view.table.model().rowCount() == 2


def test_the_merge_note_states_the_live_and_recovered_split(win):
    _open(win, [_entry(1)])
    win._on_recovery_loaded(
        _StubEngine([_entry(77, Source="page slack", RecoverySource="slack")]))
    text = _headers_view(win).line_text()
    assert "1 live, 1 recovered" in text


def test_a_carved_header_row_reaches_the_table_stamped_carved(win):
    _open(win, [_entry(1)])
    win._on_recovery_loaded(
        _StubEngine([_entry(77, Source="page slack", RecoverySource="slack")]))
    model = _headers_view(win).table.model()
    origins = {model.row_at(i)["Origin"] for i in range(model.rowCount())}
    assert CARVED_ORIGIN in origins
    assert "Live record" in origins


def test_the_merge_is_built_from_the_original_live_list(win):
    """Merged from the rows THIS load produced, never from whatever the
    table already shows -- the same discipline History keeps, so a second
    scan cannot double-count the first one's carved rows."""
    _open(win, [_entry(1)])
    engine = _StubEngine([_entry(77, Source="log", RecoverySource="log")])
    win._on_recovery_loaded(engine)
    win._on_recovery_loaded(engine)
    assert _headers_view(win).table.model().rowCount() == 2


def test_the_nav_badge_grows_with_the_merge(win):
    _open(win, [_entry(1)])
    win._on_recovery_loaded(
        _StubEngine([_entry(77, Source="log", RecoverySource="log")]))
    assert _nav_count(win) == 2


# --- the record surfaces every other view already has ---------------------

def test_a_row_opens_the_detail_dialog(win):
    _open(win, [_entry(1)])
    view = _headers_view(win)
    view.table.open_record(0)
    assert win._detail_dialogs, "recordActivated is not wired to the dialog"
    for dialog in list(win._detail_dialogs):
        dialog.close()


def test_the_container_cell_drills_to_the_table_browser(win):
    _open(win, [_entry(1)])
    view = _headers_view(win)
    by_key = {c.key: c for c in view.COLUMNS}
    by_key["ContainerId"].on_click(view.table.model().row_at(0))
    assert win.current_key == "browser"


def test_the_pane_opens_the_record_through_the_tables_own_route(win):
    _open(win, [_entry(1)])
    view = _headers_view(win)
    view.table.selectRow(0)
    view.detail_pane.detail_button.click()
    assert win._detail_dialogs
    for dialog in list(win._detail_dialogs):
        dialog.close()


# --- both exports ---------------------------------------------------------

def _open_through_the_dialog(win, monkeypatch, path, entries):
    from webcache.shell import main_window as mw

    class _SyncLoader(QObject):
        progress = Signal(str)
        loaded = Signal(object)
        failed = Signal(str)

        def load(self, db_path, known_hashes=None):
            self.loaded.emit({"rows": [], "parser": _FakeParser(entries)})

        def cancel(self):
            pass

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (path, "")))
    monkeypatch.setattr(mw, "OpenEvidenceDialog", _FakeConsentDialog)
    monkeypatch.setattr(mw, "EvidenceLoader", _SyncLoader)
    monkeypatch.setattr(mw, "ExportRunner", _SyncExportRunner)
    win.open_evidence_action.trigger()


def test_the_view_export_button_reaches_a_writer_not_a_navigation(
        win, monkeypatch, exhibit, outbox):
    _open_through_the_dialog(win, monkeypatch,
                             str(exhibit / "e.dat"),
                             [_entry(1), _entry(2)])
    out = str(outbox / "headers.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view = _headers_view(win)
    promised = int(view.export_button.text().split("(")[1].rstrip(")"))
    view.export_button.click()
    assert win.current_key != "export"
    body = _read(out)
    assert len(body) - 1 == promised == 2


def test_the_pair_button_writes_one_row_per_pair_and_keeps_its_promise(
        win, monkeypatch, exhibit, outbox):
    _open_through_the_dialog(win, monkeypatch,
                             str(exhibit / "e.dat"),
                             [_entry(1), _entry(2)])
    out = str(outbox / "headers_pairs.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view = _headers_view(win)
    promised = int(view.pairs_export_button.text().split("(")[1].rstrip(")"))
    view.pairs_export_button.click()
    body = _read(out)
    assert promised == H.total_pairs(view.visible_rows())
    assert len(body) - 1 == promised, (
        "the button said %s pairs; the file holds %s" % (promised, len(body) - 1))


def test_the_pair_file_names_the_direction_and_keeps_wire_order(
        win, monkeypatch, exhibit, outbox):
    _open_through_the_dialog(win, monkeypatch,
                             str(exhibit / "e.dat"), [_entry(1)])
    out = str(outbox / "pairs.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    _headers_view(win).pairs_export_button.click()
    header, *body = _read(out)
    assert "Direction" in header and "Ordinal" in header
    assert "Origin" in header and "RecordSource" in header
    direction = header.index("Direction")
    name = header.index("Header")
    responses = [r[name] for r in body if r[direction] == "response"]
    assert responses[0] == H.STATUS_LINE_LABEL
    assert responses.count("Set-Cookie") == 2, (
        "the pair export must carry both values the decoded dict collapsed")


def test_a_filtered_pair_export_writes_only_what_was_on_screen(
        win, monkeypatch, exhibit, outbox):
    """Pair rows captured at view-build time would let a filtered view
    export pairs the examiner had never seen."""
    _open_through_the_dialog(win, monkeypatch,
                             str(exhibit / "e.dat"),
                             [_entry(1), _entry(2), _entry(3)])
    view = _headers_view(win)
    view.filter_box.setText("example1")
    view._apply_text()
    assert view.table.model().rowCount() == 1
    out = str(outbox / "pairs_filtered.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    promised = int(view.pairs_export_button.text().split("(")[1].rstrip(")"))
    view.pairs_export_button.click()
    body = _read(out)
    assert len(body) - 1 == promised
    assert promised == H.total_pairs(view.visible_rows())


def test_a_pair_export_carries_its_own_provenance_sidecar(
        win, monkeypatch, exhibit, outbox):
    _open_through_the_dialog(win, monkeypatch,
                             str(exhibit / "e.dat"), [_entry(1)])
    out = str(outbox / "pairs_side.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    _headers_view(win).pairs_export_button.click()
    # <name>.provenance.txt beside the file it describes -- the
    # extension is kept, so the sidecar and its CSV sort together.
    sidecar = out + ".provenance.txt"
    assert os.path.exists(sidecar)
    text = open(sidecar, encoding="utf-8").read()
    assert "header pairs" in text, (
        "two different numbers on one screen have to be told apart in the "
        "file that leaves the building")


def test_the_pair_export_goes_through_the_one_chokepoint(
        win, monkeypatch, exhibit, outbox):
    """Exactly one place in this application hands a chosen path to a
    writer, and the pair export is not a second one."""
    _open_through_the_dialog(win, monkeypatch,
                             str(exhibit / "e.dat"), [_entry(1)])
    out = str(outbox / "pairs_chokepoint.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    _headers_view(win).pairs_export_button.click()
    assert [j.key for j in _SyncExportRunner.jobs] == ["header_pairs"]


# --- the self-consistency guard must be able to fire -------------

def test_a_stale_pairs_button_label_refuses_the_export(
        win, monkeypatch, exhibit, outbox):
    """main_window._export_header_pairs carries
    the identical dead guard as _export_view -- len(rows) compared
    against model.rowCount(), which cannot disagree with itself. Worse
    here: even a REAL check against model.rowCount() would compare the
    wrong quantity, since pairs_export_button promises a PAIR count
    (headers_loader.total_pairs), not a row count. This forces the
    button's own label stale and checks the export is refused against
    the pair count the button actually promised.
    """
    _open_through_the_dialog(win, monkeypatch,
                             str(exhibit / "e.dat"),
                             [_entry(1), _entry(2)])
    view = _headers_view(win)
    real_pairs = H.total_pairs(view.visible_rows())
    view.pairs_export_button.setText("Export header pairs (%d)"
                                     % (real_pairs + 500))
    out = str(outbox / "pairs_stale.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view.pairs_export_button.click()
    assert not os.path.exists(out), (
        "a stale button label must refuse the write")
    message = win.status_message()
    assert str(real_pairs + 500) in message and str(real_pairs) in message


# --- defects the on-screen run exposed ------------------------------------

def test_the_status_line_after_a_pair_export_counts_pairs_not_rows(
        win, monkeypatch, exhibit, outbox):
    """The on-screen run wrote 7,202 pairs and the status bar said
    "Exported 546 of 546 rows". The scope the summary reads was built
    before the worker knew the pair count, so it reported the record
    count for a file of pairs."""
    _open_through_the_dialog(win, monkeypatch,
                             str(exhibit / "e.dat"), [_entry(1), _entry(2)])
    out = str(outbox / "pairs_status.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    view = _headers_view(win)
    pairs = H.total_pairs(view.visible_rows())
    view.pairs_export_button.click()
    status = win.status_message()
    assert "header pairs" in status, status
    assert format(pairs, ",") in status, status
    assert "%s of 2 rows" % pairs not in status


def test_the_status_line_still_names_the_records_the_pairs_came_from(
        win, monkeypatch, exhibit, outbox):
    """Both numbers, because both are on the screen the examiner just
    left."""
    _open_through_the_dialog(win, monkeypatch,
                             str(exhibit / "e.dat"), [_entry(1), _entry(2)])
    out = str(outbox / "pairs_status2.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    _headers_view(win).pairs_export_button.click()
    status = win.status_message()
    assert "2 of 2 record" in status, status


def test_an_ordinary_view_export_keeps_its_own_wording(
        win, monkeypatch, exhibit, outbox):
    """The rows wording is not collateral damage of the pairs one."""
    _open_through_the_dialog(win, monkeypatch,
                             str(exhibit / "e.dat"), [_entry(1), _entry(2)])
    out = str(outbox / "rows_status.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "")))
    _headers_view(win).export_button.click()
    status = win.status_message()
    assert "Exported 2 of 2 rows" in status, status
