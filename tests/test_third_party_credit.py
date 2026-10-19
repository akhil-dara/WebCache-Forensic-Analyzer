"""The libraries the tool is built on are named wherever a person meets
the tool, and the statement about reading a dirty database says only
what is measured: no repair is run, so the file is not written to."""
import pathlib

from webcache.engine import evidence_model
from webcache.shell import help_texts, user_guide

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIBRARIES = ("dissect.esedb", "dissect.cstruct", "dissect.util", "PySide6",
             "openpyxl", "reportlab", "Pillow")


def test_the_notices_file_names_each_library_and_its_licence():
    notices = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    for name in LIBRARIES:
        assert name in notices, name
    for licence in ("Apache-2.0", "LGPL-3.0", "MIT", "BSD"):
        assert licence in notices, licence


def test_the_readme_and_about_box_credit_the_ese_reader():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Built on" in readme
    assert "dissect.esedb" in readme
    assert "dissect.esedb" in help_texts.ABOUT_TEXT
    assert "THIRD-PARTY-NOTICES" in help_texts.ABOUT_TEXT


def test_the_build_ships_the_notices_and_each_librarys_licence_files():
    spec = (ROOT / "packaging" / "webcache.spec").read_text(encoding="utf-8")
    assert "THIRD-PARTY-NOTICES.md" in spec
    assert "copy_metadata" in spec
    # PySide6's wheel carries no LGPL text, so the project ships it.
    assert '"../licenses"' in spec
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        text = (ROOT / "licenses" / name).read_text(encoding="utf-8")
        assert "Version 3, 29 June 2007" in text[:200], name


def test_no_text_claims_a_repair_destroys_records():
    """The esentutl /r comparison found the records identical; what a
    repair does is write to the file."""
    from webcache.engine import ese_parser
    import inspect
    texts = [dict(evidence_model.SCOPE_STATEMENTS)["Source handling"],
             inspect.getsource(ese_parser.WebCacheParser),
             " ".join(str(x) for x in vars(user_guide).values()
                      if isinstance(x, (str, list, tuple))),
             (ROOT / "README.md").read_text(encoding="utf-8")]
    for text in texts:
        assert "destroy" not in text.replace("\n", " ").lower() or \
            "records" not in text.lower().split("destroy", 1)[1][:80]
    assert "writes to the database file" in dict(
        evidence_model.SCOPE_STATEMENTS)["Source handling"]
