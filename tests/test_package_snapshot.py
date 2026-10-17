"""Reading the application into a PackageSnapshot."""
import ast
import pathlib
import types

import pytest

from webcache import provenance
from webcache.shell.html_package import PackageColumn
from webcache.widgets.column_spec import Column
from webcache.widgets.record_filter import Condition

from tests.fixtures import make_rows
from tests.test_export_wiring import (_FakeParser, _open_exhibit,  # noqa: F401
                                      exhibit, win)

SHELL = pathlib.Path(__file__).resolve().parent.parent / "webcache" / "shell"


@pytest.mark.parametrize("name", ["html_package.py", "package_snapshot.py"])
def test_the_package_modules_never_import_qt(name):
    path = SHELL / name
    assert path.is_file(), "%s does not exist yet" % name
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    assert not [n for n in names if "PySide6" in n], names


class _RecordSet:
    def __init__(self, key, label, columns, default_sort=None):
        self.key, self.label, self.columns = key, label, columns
        self.caveat, self.count_noun = None, None
        self.default_sort = default_sort
        self.empty_text = "No %s records in this exhibit." % label
        self.subtitle = lambda n: "%d rows" % n


def _spec(label, key, values=None, condition=None, post=None):
    return types.SimpleNamespace(label=label, key=key, values=values,
                                 condition=condition, post=post,
                                 sentence=None)


def test_segments_of_copies_columns_and_keeps_rows_by_reference():
    from webcache.shell.package_snapshot import POST_CHIP_REASON, segments_of
    col = Column("CleanUrl", "Address", 300, kind="url", field="CleanUrl")
    col.badge, col.badge_tooltip = "OBS", "OBS (Observed) - read directly"
    rows = [{"CleanUrl": "https://example.test/a"}]
    view = types.SimpleNamespace(
        _record_sets=[_RecordSet("history", "History", [col],
                                 default_sort=("CleanUrl", True))],
        _segment_rows={"history": rows},
        _segment_notes={"history": "1 live, 0 recovered"},
        _quick_filters=[
            _spec("InPrivate only", "IsInPrivate", values={True}),
            _spec("Has search terms", "SearchTerms",
                  condition=Condition("is not blank")),
            _spec("One row per visit", "SameVisit", post=lambda v: v)],
        _view_caveat="the view's own caveat", COUNT_NOUN="records")
    seg = segments_of(view, "nav caption")[0]
    assert seg.rows[0] is rows[0]
    assert isinstance(seg.columns[0], PackageColumn)
    assert seg.columns[0].badge == "OBS"
    assert seg.note == "1 live, 0 recovered"
    assert seg.caveat == "the view's own caveat"
    assert seg.default_sort == ("CleanUrl", True) and seg.subtitle == "1 rows"
    assert seg.quick[0] == {"label": "InPrivate only", "key": "IsInPrivate",
                            "values": ["Yes"], "cond": None, "sentence": None,
                            "counted": False, "none_note": None}
    assert seg.quick[1]["cond"] == ["is not blank", None, None]
    assert seg.quick[2] == {"label": "One row per visit",
                            "skipped": POST_CHIP_REASON}


def test_a_view_without_record_sets_is_read_from_its_table():
    from webcache.shell.package_snapshot import segments_of
    rows = [{"CleanUrl": "https://example.test/c"}]
    model = types.SimpleNamespace(filter=types.SimpleNamespace(rows=rows))
    view = types.SimpleNamespace(
        COLUMNS=[Column("CleanUrl", "URL")],
        table=types.SimpleNamespace(model=lambda: model),
        _note="2 recovered")
    seg = segments_of(view, "Carved from unallocated pages")[0]
    assert seg.rows == rows and seg.default_sort == ("Timestamp", True)
    assert seg.caveat == "Carved from unallocated pages"
    assert seg.note == "2 recovered"


class _RawParser:
    db = object()
    containers_meta = []

    def get_tables_grouped(self):
        return {"Containers": [{"name": "Container_1"}]}

    def get_table_display_name(self, name):
        return "Container 1"

    def get_table_row_count(self, name):
        return 2

    def get_table_rows_raw(self, name, limit=500, offset=0):
        rows = [[1, 133500000000000000, b"\x01\xab"], [2, None, b""]]
        return ["EntryId", "AccessedTime", "ResponseHeaders"], rows[:limit]

    @staticmethod
    def raw_type_name(value):
        if value is None:
            return "null"
        return "binary" if isinstance(value, bytes) else type(value).__name__

    @classmethod
    def raw_rendering(cls, value):
        return "" if value is None else str(value)


def test_raw_tables_are_one_segment_each_with_full_hex_and_decoded_columns(
        monkeypatch):
    from webcache.shell import package_snapshot, table_browser_loader
    monkeypatch.setattr(
        table_browser_loader, "decode_filetime_cell",
        lambda parser, table, column, value, entry_id=None:
        "2024-01-01 00:00:00 UTC" if column == "AccessedTime" and value else "")
    view = package_snapshot.raw_view(_RawParser(), "Raw ESE tables")
    assert view.key == "raw" and view.picker == "list"
    seg = view.segments[0]
    assert (seg.key, seg.group, seg.label) == (
        "t:Container_1", "Containers", "Container 1")
    columns, rows, note = seg.resolve()
    assert [c.label for c in columns] == [
        "Row #", "EntryId", "AccessedTime", "AccessedTime (decoded)",
        "ResponseHeaders"]
    assert rows[0]["c:ResponseHeaders"] == "01AB"
    assert rows[0]["d:AccessedTime"].startswith("2024")
    assert rows[1]["c:ResponseHeaders"] == "" and note == ""
    assert "binary" in columns[4].note
    assert rows[0]["_kind"] == "table_row" and rows[0]["_record"] is None


def test_the_window_snapshot_reads_every_record_view_in_nav_order(
        win, monkeypatch, exhibit):
    from webcache.shell.package_snapshot import PACKAGE_VIEW_KEYS
    _open_exhibit(win, monkeypatch, str(exhibit / "e.dat"),
                  rows=make_rows(3), parser=_FakeParser([]))
    snap = win._package_snapshot()
    assert [v.key for v in snap.views] == list(PACKAGE_VIEW_KEYS)
    history = snap.views[0]
    assert history.label == win._labels["history"]
    shown = win.stack.widget(win._index["history"])._segment_rows["history"]
    assert len(shown) == len(history.segments[0].rows) > 0
    assert all(a is b for a, b in zip(history.segments[0].rows, shown))
    # "One row per visit" is reproduced in the page, not listed as skipped.
    assert any(q.get("twins") for q in history.segments[0].quick)
    timeline = [v for v in snap.views if v.key == "timeline"][0]
    assert {s.clock for s in timeline.segments} == {"utc"}
    assert timeline.initial == "day_utc"
    # every grain opens newest first, on either clock, as the app does.
    assert {s.default_sort for s in timeline.segments} == {
        ("PeriodStart", True)}
    assert snap.meta["tool_version"] == provenance.TOOL_VERSION
    assert snap.member_columns[0].label == "When (UTC)"
    assert snap.member_columns[0].badge


def test_each_location_segment_and_deleted_records_carry_the_apps_noun(qtbot):
    """The page's count line names each segment's own unit.
    LocationView's COUNT_NOUN follows whichever segment was active when the
    snapshot read it, so every Location segment used to be "position fixes";
    Deleted Records said "records" where the app says "recovered records"."""
    from webcache.shell.package_snapshot import segments_of
    from webcache.views.location import COUNT_NOUNS, LocationView
    from webcache.views.recovery import RecoveryView

    location = LocationView()
    qtbot.addWidget(location)
    nouns = {seg.key: seg.noun for seg in segments_of(location)}
    assert nouns == COUNT_NOUNS

    recovery = RecoveryView()
    qtbot.addWidget(recovery)
    assert [seg.noun for seg in segments_of(recovery)] == ["recovered records"]


def test_deleted_records_carries_the_apps_method_and_confidence_chips(qtbot):
    """The page reproduces Deleted Records' chips."""
    from webcache.shell import html_package, record_kinds
    from webcache.shell.package_snapshot import segments_of
    from webcache.views.recovery import RecoveryView

    recovery = RecoveryView()
    qtbot.addWidget(recovery)
    quick = segments_of(recovery)[0].quick
    assert [(q["label"], q["key"], q["values"], q.get("group")) for q in quick] == [
        ("Structured", "_kind",
         [html_package.encode_cell(record_kinds.K_CARVED_STRUCT)], "method"),
        ("String carves", "_kind",
         [html_package.encode_cell(record_kinds.K_CARVED_STRING)], "method"),
        ("Deleted-record stubs", "_kind",
         [html_package.encode_cell(record_kinds.K_TOMBSTONE)], "method"),
        ("High confidence only", "Confidence",
         [html_package.encode_cell("high")], None),
    ]


def test_the_page_summary_states_size_as_the_app_does_and_in_bytes():
    """The Dashboard shows "136.5 MB"; the page showed
    only raw digits. It now shows both."""
    from webcache.shell.package_snapshot import page_summary
    rows = page_summary([("File", "WebCacheV01.dat"), ("Size", 143130624)])
    assert rows == [("File", "WebCacheV01.dat"),
                    ("Size", "136.5 MB (143,130,624 bytes)")]


def test_a_raw_table_segment_states_its_rows_once(monkeypatch):
    """The count line already says "N rows"; the factory's
    note repeated it."""
    from webcache.shell import package_snapshot

    class _P:
        def get_table_row_count(self, name):
            return 2

        def get_table_rows_raw(self, name, limit, offset):
            return ["EntryId", "Url"], [[1, "a"], [2, "b"]]

        def raw_type_name(self, value):
            return type(value).__name__

        def raw_rendering(self, value):
            return str(value)

    monkeypatch.setattr(package_snapshot.table_browser_loader,
                        "decode_filetime_cell", lambda *a, **k: None)
    _cols, rows, note = package_snapshot._raw_factory(_P(), "T")()
    assert len(rows) == 2 and note == ""


def test_each_segment_carries_its_views_line_cap(qtbot):
    """The app caps a Location row at 3 lines and every
    other grid at 6; the page reproduces each view's own cap."""
    from webcache.shell.package_snapshot import segments_of
    from webcache.views.location import LocationView
    from webcache.views.history import HistoryView
    location, history = LocationView(), HistoryView()
    qtbot.addWidget(location)
    qtbot.addWidget(history)
    assert {s.cap for s in segments_of(location)} == {3}
    assert {s.cap for s in segments_of(history)} == {6}


def test_the_open_log_leaves_the_case_table_as_its_own_rows():
    """The case file's evidence-opened log reached the
    page's Case table as one JSON string. It becomes its own table."""
    import json
    from webcache.shell import case_store
    from webcache.shell.package_snapshot import split_open_log
    log = [{"opened_utc": "2026-10-05T10:00:00Z",
            "files": [{"path": "C:/case/e.dat", "sha256": "ab" * 32,
                       "bytes": 1024}]}]
    case, rows = split_open_log({"examiner": "alice",
                                 case_store.OPEN_LOG_META_KEY: json.dumps(log)})
    assert case == {"examiner": "alice"}
    assert rows == [["2026-10-05T10:00:00Z", "C:/case/e.dat", "ab" * 32, 1024]]
    assert split_open_log({"examiner": "alice"}) == ({"examiner": "alice"}, [])
