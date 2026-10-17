"""The examiner chooses how times are written on screen. Only the spelling
changes: the instant, its zone and every export stay as they are."""
import datetime

import pytest

from webcache.widgets import time_format as tf
from webcache.widgets.column_spec import Column, display_text, searchable_text

VALUE = datetime.datetime(2025, 1, 13, 16, 38, 51, 504000,
                          tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def _restore():
    old = tf.pattern()
    yield
    tf.set_pattern(old)


def test_the_default_is_the_spelling_the_grid_always_used():
    tf.set_pattern(tf.DEFAULT_PATTERN)
    assert tf.format_dt(VALUE) == "2025-01-13 16:38:51"


@pytest.mark.parametrize("pattern, text", [
    ("%Y-%m-%d %H:%M:%S.%3f", "2025-01-13 16:38:51.504"),
    ("%Y-%m-%d %I:%M:%S.%3f %p", "2025-01-13 04:38:51.504 PM"),
    ("%d-%b-%Y %H:%M:%S.%3f", "13-Jan-2025 16:38:51.504"),
    ("%m/%d/%Y %I:%M:%S.%3f %p", "01/13/2025 04:38:51.504 PM"),
    ("%d-%b-%Y %I:%M:%S.%7f %p", "13-Jan-2025 04:38:51.5040000 PM"),
    ("%Y-%m-%dT%H:%M:%S.%3fZ", "2025-01-13T16:38:51.504Z"),
    ("%a %d %b %Y %H:%M:%S.%3f", "Mon 13 Jan 2025 16:38:51.504"),
    ("%H:%M:%S.%6f", "16:38:51.504000"),
])
def test_patterns_write_the_same_instant(pattern, text):
    tf.set_pattern(pattern)
    assert tf.format_dt(VALUE) == text


def test_every_preset_formats():
    for key, label, pattern in tf.PRESETS:
        assert tf.format_with(pattern, VALUE), key


def test_a_pattern_that_writes_nothing_useful_is_refused():
    for bad in ("", "   ", "plain words", "%Q"):
        assert tf.problem(bad), bad
    assert tf.problem("%Y-%m-%d") == ""


def test_the_grid_and_the_search_box_follow_the_choice():
    tf.set_pattern("%d-%b-%Y %H:%M:%S.%3f")
    col = Column("When", kind="time")
    assert display_text(VALUE, col) == "13-Jan-2025 16:38:51.504"
    assert "13-Jan-2025" in searchable_text(VALUE, col)


def test_the_search_haystack_matches_what_is_shown():
    from webcache.widgets.record_filter import RecordFilter
    tf.set_pattern("%d-%b-%Y %H:%M:%S")
    col = Column("When", kind="time")
    rf = RecordFilter([{"When": VALUE}], [col])
    rf.set_text("13-jan-2025")
    assert len(rf.visible()) == 1


def test_the_engines_written_times_are_respelled_with_their_zone():
    tf.set_pattern("%d-%b-%Y %H:%M:%S.%3f")
    assert tf.respell("2025-01-13 16:38:51.504 UTC") == "13-Jan-2025 16:38:51.504 UTC"
    assert tf.respell("2025-01-13 16:38:51 LOCAL") == "13-Jan-2025 16:38:51.000 LOCAL"
    assert tf.respell("not a time") == "not a time"
    tf.set_pattern(tf.DEFAULT_PATTERN)
    assert tf.respell("2025-01-13 16:38:51.504 UTC") == "2025-01-13 16:38:51.504 UTC"


def test_the_record_dialog_follows_the_choice():
    from webcache.shell.detail_fields import _render
    tf.set_pattern("%d-%b-%Y %H:%M:%S")
    assert _render(VALUE, "time") == "13-Jan-2025 16:38:51"
    assert _render("2025-01-13 16:38:51.504 UTC", "text") == "13-Jan-2025 16:38:51 UTC"


def test_choosing_a_format_repaints_open_grids_and_is_remembered(qtbot, tmp_path,
                                                                 monkeypatch):
    import webcache.paths as paths
    from webcache.shell import settings
    from webcache.shell.main_window import MainWindow
    monkeypatch.setattr(paths, "settings_path", lambda: tmp_path / "s.json")
    win = MainWindow()
    qtbot.addWidget(win)
    view = win._ensure_view_built("recovery")
    view.set_records([{"CleanUrl": "a", "Timestamp": VALUE}])
    model = view.table.model()
    col = [c.key for c in model.columns].index("Timestamp")
    win.set_time_format("%d-%b-%Y %H:%M:%S.%3f")
    model = view.table.model()
    assert model.index(0, col).data() == "13-Jan-2025 16:38:51.504"
    assert settings.get("time_format") == "%d-%b-%Y %H:%M:%S.%3f"


def test_the_dialog_returns_a_preset_or_the_examiners_own(qtbot):
    from webcache.shell.time_format_dialog import TimeFormatDialog
    d = TimeFormatDialog(tf.DEFAULT_PATTERN)
    qtbot.addWidget(d)
    assert d.chosen_pattern() == tf.DEFAULT_PATTERN
    d.own_edit.setText("")
    d._insert("%H:%M")
    assert d.chosen_pattern() == "%H:%M"
    d.own_edit.setText("nonsense"); d._own_edited()
    from PySide6.QtWidgets import QDialogButtonBox
    assert not d.box.button(QDialogButtonBox.Apply).isEnabled()


def test_a_time_cell_tooltip_gives_the_stored_value_and_the_format():
    tf.set_pattern("%d-%b-%Y %H:%M:%S")
    tip = tf.tooltip_text(VALUE)
    assert "Stored: 2025-01-13T16:38:51.5040000Z" in tip
    assert "%d-%b-%Y %H:%M:%S" in tip
