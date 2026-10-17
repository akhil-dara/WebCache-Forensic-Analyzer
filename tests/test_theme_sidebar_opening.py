"""The theme switch says it is busy, the sidebar fits the examiner's 816 px work area with a theme button
worded as an action, and the centre card says what is being opened."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from webcache.shell import theme
from webcache.shell.main_window import MainWindow
from tests._native_screen import skip_unless_measurable


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_the_toggle_is_quick_enough_to_need_no_wait_cursor(win, monkeypatch):
    """Hidden views are parked during a switch (_park_hidden_views), so
    the switch costs only what is on screen and shows no busy cursor."""
    seen = []
    real_apply = theme.apply

    def spy(app, name="dark"):
        seen.append(QApplication.overrideCursor())
        return real_apply(app, name)

    monkeypatch.setattr(theme, "apply", spy)
    win._toggle_theme()
    assert seen == [None]
    win._toggle_theme()


def test_the_theme_button_says_what_it_does(win):
    text = win.sidebar.theme_pill.text()
    other = "light" if theme.current_name() == "dark" else "dark"
    assert "Switch to %s theme" % other in text


def _fit_probe():
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": "."}
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests._sidebar_fit_probe"],
        capture_output=True, text=True, timeout=300, cwd=root, env=env)
    assert result.returncode == 0, result.stderr[-4000:]
    out = result.stdout.strip()
    skip_unless_measurable(out)
    return out, {k: int(v) for k, v in (p.split("=") for p in out.split())}


def test_every_nav_row_fits_at_816_px_without_scrolling():
    out, values = _fit_probe()
    assert values["scroll_max"] == 0, out
    assert values["last_bottom"] <= values["viewport"], out


def test_the_foot_buttons_show_their_words_inside_the_sidebar_at_816_px():
    """An on-screen grab showed Collapse's text clipped; and the
    theme button's new, longer action wording must not be cut either."""
    out, values = _fit_probe()
    assert values["pill_room"] >= values["pill_need"], out
    assert values["collapse_room"] >= values["collapse_need"], out
    assert values["collapse_bottom"] <= values["sidebar_h"], out
    # nor cut at the top and bottom.
    assert values["collapse_room_h"] >= values["collapse_need_h"], out


def test_the_centre_card_says_what_is_opening_and_for_how_long(win):
    win.first_run.set_opening("WebCacheV01.dat")
    assert win.first_run.heading.text() == "Opening WebCacheV01.dat…"
    assert not win.first_run.open_button.isVisibleTo(win.first_run)
    win._busy_for = "load"
    win._load_last_message = "Parsing WebCacheV01.dat…"
    win._load_elapsed.start()
    win._refresh_load_elapsed()
    assert "elapsed" in win.first_run.elapsed_label.text()
    win._end_load_busy_ui()
    assert win.first_run.heading.text() == "No evidence open"
    assert win.first_run.open_button.isVisibleTo(win.first_run)


def test_opening_a_file_puts_its_name_on_the_card_as_plain_text(
        win, monkeypatch, tmp_path):
    """The name comes from the examiner's chosen path; it is shown as
    plain text, never as a link."""
    from webcache.shell import main_window as mw

    class _Accepting:
        recover_deleted = False

        def __init__(self, path, parent=None):
            self.evidence_set = type("E", (), {"hashes": {}})()

        def exec(self):
            return mw.QDialog.Accepted

        def deleteLater(self):
            pass

    class _Signal:
        def connect(self, *args):
            pass

    class _IdleLoader:
        def __init__(self, parent=None):
            self.progress = _Signal()
            self.loaded = _Signal()
            self.failed = _Signal()

        def load(self, *args):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(mw, "OpenEvidenceDialog", _Accepting)
    monkeypatch.setattr(mw, "EvidenceLoader", _IdleLoader)
    win._open_evidence_at(str(tmp_path / "alice-exhibit.dat"))
    heading = win.first_run.heading
    assert heading.text() == "Opening alice-exhibit.dat…"
    assert heading.textFormat() == Qt.PlainText
    assert not heading.openExternalLinks()
    win._end_load_busy_ui()


def test_the_origin_header_answers_unasked_roles_without_a_row_lookup(qtbot):
    """F23's profile: re-polishing the whole application on a theme switch
    asks every grid's vertical header for many roles per section; each one
    looked the row up and derived its origin label before discovering the
    role was not one it answers (61,200 calls, 0.66 s of a 2.5 s toggle on
    the 136.5 MB sample)."""
    from webcache.widgets.record_model import RecordTableModel
    from tests.fixtures import FIXTURE_COLUMNS, make_rows
    model = RecordTableModel(list(FIXTURE_COLUMNS), make_rows(10))
    looked_up = []
    real = model.origin_label
    model.origin_label = lambda row: looked_up.append(1) or real(row)
    for role in (Qt.FontRole, Qt.TextAlignmentRole, Qt.DecorationRole,
                 Qt.SizeHintRole, Qt.ForegroundRole, Qt.BackgroundRole):
        assert model.headerData(3, Qt.Vertical, role) is None
    assert looked_up == []
    assert model.headerData(3, Qt.Vertical, Qt.DisplayRole)
    assert looked_up == [1]
