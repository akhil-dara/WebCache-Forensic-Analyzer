"""Every image the README shows exists, and none is real evidence: they
come from docs/make_screenshots.py's made-up exhibit."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_every_readme_image_exists():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    assert len(images) >= 5
    for rel in images:
        assert (ROOT / rel).is_file(), rel


def test_the_screenshots_say_they_are_not_real_evidence():
    """A reader must never take a screenshot for someone's real evidence."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "fictional demonstration exhibit, not real evidence" in text


def test_how_to_remake_them_is_with_the_script_not_in_the_readme():
    """Maintainer instructions live beside the script; the README is for
    the people who use the tool."""
    script = ROOT / "docs" / "make_screenshots.py"
    assert script.is_file()
    assert "python -m docs.make_screenshots" in script.read_text(encoding="utf-8")
