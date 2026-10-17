"""The licence is stated the same way everywhere a person meets it: the
LICENSE file, the README, the About box and the package metadata."""
import pathlib
import tomllib

from webcache.shell import help_texts

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_licence_file_is_the_agpl_v3():
    head = (ROOT / "LICENSE").read_text(encoding="utf-8")[:200]
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in head
    assert "Version 3, 19 November 2007" in head


def test_the_about_box_names_it():
    assert "GNU Affero General Public License v3.0" in help_texts.ABOUT_TEXT
    assert "Akhil Dara" in help_texts.ABOUT_TEXT


def test_the_package_metadata_declares_it():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(
        encoding="utf-8"))["project"]
    assert project["license"] == "AGPL-3.0-only"
    assert project["license-files"] == ["LICENSE"]
