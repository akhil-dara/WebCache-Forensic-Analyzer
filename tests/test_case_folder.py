"""Where settings and case files live -- portable, installed, overridden,
or a folder the examiner chose -- and File > Case files folder."""
import pathlib
import sys

import pytest

from webcache import paths
from webcache.shell import case_folder, settings
from webcache.shell.case_store import SUFFIX


@pytest.fixture
def program(tmp_path, monkeypatch):
    """A frozen program in tmp_path/prog, a profile in tmp_path/local, and
    settings in a scratch file (conftest's isolation, kept)."""
    prog = tmp_path / "prog"
    prog.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(prog / "WebCacheAnalyzer.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    return prog


def test_a_portable_copy_keeps_everything_beside_the_program(program):
    assert not paths.is_installed()
    assert paths.data_dir() == program.resolve()
    assert paths.default_cases_dir() == program.resolve() / "cases"


def test_an_installed_copy_keeps_everything_in_the_profile(program, tmp_path):
    (program / paths.INSTALLED_MARKER).write_text("")
    assert paths.is_installed()
    expected = tmp_path / "local" / paths.DATA_FOLDER_NAME
    assert paths.data_dir() == expected and expected.is_dir()
    assert paths.cases_dir() == expected / "cases"


def test_the_environment_moves_everything(program, tmp_path, monkeypatch):
    (program / paths.INSTALLED_MARKER).write_text("")
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "elsewhere"))
    assert paths.data_dir() == tmp_path / "elsewhere"


def test_a_chosen_folder_holds_the_case_files(program, tmp_path):
    chosen = tmp_path / "case volume"
    settings.save(**{paths.CASES_SETTING: str(chosen)})
    try:
        assert paths.cases_dir() == chosen and chosen.is_dir()
    finally:
        settings.save(**{paths.CASES_SETTING: ""})


def test_a_chosen_folder_that_cannot_be_made_falls_back_to_the_default(
        program, tmp_path):
    blocker = tmp_path / "a file"
    blocker.write_text("")
    settings.save(**{paths.CASES_SETTING: str(blocker / "cases")})
    try:
        assert paths.cases_dir() == paths.default_cases_dir()
    finally:
        settings.save(**{paths.CASES_SETTING: ""})


def test_changing_the_folder_copies_case_files_and_keeps_the_originals(
        program, tmp_path):
    old = paths.cases_dir()
    (old / ("a" * 16 + SUFFIX)).write_bytes(b"one")
    (old / ("b" * 16 + SUFFIX)).write_bytes(b"two")
    (old / "not a case file.txt").write_bytes(b"x")
    new = tmp_path / "chosen"
    new.mkdir()
    (new / ("b" * 16 + SUFFIX)).write_bytes(b"newer")
    try:
        ok, said = case_folder.change_cases_dir(str(new))
        assert ok, said
        assert paths.cases_dir() == new
        assert (new / ("a" * 16 + SUFFIX)).read_bytes() == b"one"
        assert (new / ("b" * 16 + SUFFIX)).read_bytes() == b"newer"
        assert not (new / "not a case file.txt").exists()
        assert (old / ("a" * 16 + SUFFIX)).exists()
        assert "1 case file copied" in said and "1 already there" in said
        ok, said = case_folder.change_cases_dir(None)
        assert ok and paths.cases_dir() == paths.default_cases_dir()
    finally:
        settings.save(**{paths.CASES_SETTING: ""})


def test_a_folder_inside_the_evidence_folder_is_refused(program, tmp_path):
    evidence = tmp_path / "exhibit"
    evidence.mkdir()
    ok, said = case_folder.change_cases_dir(str(evidence / "cases"),
                                            evidence_dirs=[evidence])
    assert not ok and "evidence folder" in said
    assert not (evidence / "cases").exists()
    assert paths.chosen_cases_dir() is None


def test_the_dialog_says_where_and_why_and_changes_it(program, tmp_path,
                                                      qtbot, monkeypatch):
    calls = []
    dialog = case_folder.CaseFolderDialog(
        before_change=lambda: calls.append("close"),
        on_changed=lambda: calls.append("reopen"))
    qtbot.addWidget(dialog)
    assert dialog.path_label.text() == str(paths.cases_dir())
    assert "portable" in dialog.where_label.text()
    assert not dialog.default_button.isEnabled()
    target = tmp_path / "picked"
    monkeypatch.setattr(case_folder.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(target)))
    try:
        dialog.change_button.click()
        assert calls == ["close", "reopen"]
        assert dialog.path_label.text() == str(target)
        assert "A folder you chose." == dialog.where_label.text()
        assert dialog.default_button.isEnabled()
        dialog.default_button.click()
        assert dialog.path_label.text() == str(paths.default_cases_dir())
    finally:
        settings.save(**{paths.CASES_SETTING: ""})


def test_file_menu_opens_it_with_the_evidence_folder_fenced_off(
        program, tmp_path, qtbot, monkeypatch):
    from types import SimpleNamespace
    from webcache.shell.main_window import MainWindow
    window = MainWindow()
    qtbot.addWidget(window)
    exhibit = tmp_path / "exhibit"
    window._evidence_set = SimpleNamespace(
        files=[str(exhibit / "WebCacheV01.dat"), str(exhibit / "V01.log")])
    seen = []
    monkeypatch.setattr(case_folder.CaseFolderDialog, "exec",
                        lambda self: seen.append(self._evidence_dirs))
    assert window.case_folder_action in window._file_menu.actions()
    window.case_folder_action.trigger()
    assert seen == [[str(exhibit)]]
