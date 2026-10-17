"""IntegrityView: three cards -- Source Integrity, SHA-256 Source Hashes,
Parsing Decision Log -- built on Card (widgets/card.py) the same way DashboardView already builds its own
three cards. This file proves only what IntegrityView itself renders from
a WebCacheParser.get_database_info()-shaped dict (integrity_loader.py's
own tests already prove the shaping is correct in isolation); no real
WebCacheParser is needed here, the same discipline test_dashboard_view.py
already follows for DashboardView.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics

from webcache.views.integrity import IntegrityView


def _info(**overrides):
    base = {
        "path": r"C:\case\WebCacheV01.dat",
        "db_state_text": "Dirty shutdown",
        "derived_tz": "UTC+05:30",
        "parse_stats": {"parsed": 610, "skipped": 0, "errors": 0},
        "source_hashes": {"WebCacheV01.dat": "a" * 64},
        "decision_log": [
            "Opened read-only: WebCacheV01.dat (DIRTY shutdown)",
            "SomeTable: SKIPPED — permission denied",
        ],
    }
    base.update(overrides)
    return base


def test_header_and_caveat_are_reachable(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    assert v.header is not None
    v.set_caveat("Hashes and the parse log; a clean parse is not a complete database.")
    assert v.caveat is not None


def test_before_any_data_the_view_reads_as_no_evidence_loaded(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    assert "no evidence" in v.header._subtitle.text().lower()
    assert v._source_rows == []
    assert v._hash_rows == []
    assert v._log_list.count() == 0


# --- Source Integrity card --------------------------------------------

def test_source_integrity_card_shows_all_six_fields_after_set_data(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info())
    labels = [label_widget.text() for label_widget, _value in v._source_rows]
    assert labels == ["Database state", "Read-only guarantee",
                      "Derived machine TZ", "Records (URL-cache entries)",
                      "Rows parsed, all tables",
                      "Tables skipped", "Record errors"]


def test_database_state_value_is_shown(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info(db_state_text="Clean shutdown"))
    values = dict((l.text(), val.text()) for l, val in v._source_rows)
    assert values["Database state"] == "Clean shutdown"


def test_source_integrity_values_are_selectable_and_copyable(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info())
    for _label, value_widget in v._source_rows:
        assert value_widget.textInteractionFlags() & Qt.TextSelectableByMouse


def test_source_integrity_labels_are_wide_enough_not_to_clip(qtbot):
    """Screenshot defect: "Read-only guarantee" and "Derived machine TZ"
    were clipped to "Read-only guarant"/"Derived machine T" against a
    fixed label width chosen for the shortest label ("Database state"),
    not the longest -- the same "never squeeze a column below its
    heading" lesson column-fit-rules.md already states for RecordsTable,
    applying here to a plain QLabel column instead."""
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info())
    for label_widget, _value in v._source_rows:
        fm = QFontMetrics(label_widget.font())
        needed = fm.horizontalAdvance(label_widget.text())
        assert label_widget.minimumWidth() >= needed, (
            "%r needs %dpx but only has %dpx"
            % (label_widget.text(), needed, label_widget.minimumWidth()))


def test_read_only_guarantee_value_names_rb_and_carries_the_full_statement_as_tooltip(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info())
    values = dict((l.text(), val) for l, val in v._source_rows)
    guarantee = values["Read-only guarantee"]
    assert "'rb'" in guarantee.text() or '"rb"' in guarantee.text()
    assert "esentutl" in guarantee.toolTip().lower()
    assert len(guarantee.toolTip()) > len(guarantee.text())


# --- SHA-256 Source Hashes card ----------------------------------------

def test_hash_card_shows_one_row_per_source_file(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info(source_hashes={
        "WebCacheV01.dat": "a" * 64, "V01.log": "b" * 64}))
    assert len(v._hash_rows) == 2


def test_hash_row_shows_the_file_its_role_and_its_full_hash(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info(source_hashes={"WebCacheV01.dat": "f" * 64}))
    row = v._hash_rows[0]
    assert row["file"].text() == "WebCacheV01.dat"
    assert "exhibit itself" in row["role"].text().lower()
    assert row["hash"].text() == "f" * 64


def test_hash_value_is_monospaced_and_selectable(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info())
    hash_label = v._hash_rows[0]["hash"]
    assert hash_label.textInteractionFlags() & Qt.TextSelectableByMouse
    assert "mono" in hash_label.font().family().lower() or \
        "consolas" in hash_label.font().family().lower() or \
        "cascadia" in hash_label.styleSheet().lower()


# --- Parsing Decision Log card ------------------------------------------

def test_decision_log_card_shows_every_line_in_order(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    log = ["first line", "second line", "third line"]
    v.set_data(_info(decision_log=log))
    items = [v._log_list.item(i).text() for i in range(v._log_list.count())]
    assert items == log


def test_flagged_decision_log_lines_are_coloured_differently(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info(decision_log=[
        "Opened read-only: WebCacheV01.dat (DIRTY shutdown)",
        "SomeTable: SKIPPED — permission denied",
    ]))
    clean_colour = v._log_list.item(0).foreground().color()
    flagged_colour = v._log_list.item(1).foreground().color()
    assert clean_colour != flagged_colour


# --- empty state / theme ------------------------------------------------

def test_set_data_none_returns_to_the_empty_state(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info())
    assert v._source_rows != []
    v.set_data(None)
    assert v._source_rows == []
    assert v._hash_rows == []
    assert v._log_list.count() == 0
    assert "no evidence" in v.header._subtitle.text().lower()


def test_refresh_theme_preserves_the_last_data_shown(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.set_data(_info(source_hashes={"WebCacheV01.dat": "c" * 64}))
    v.refresh_theme()
    assert len(v._hash_rows) == 1
    assert v._hash_rows[0]["hash"].text() == "c" * 64


def test_refresh_theme_before_any_data_stays_in_the_empty_state(qtbot):
    v = IntegrityView()
    qtbot.addWidget(v)
    v.refresh_theme()
    assert v._source_rows == []
