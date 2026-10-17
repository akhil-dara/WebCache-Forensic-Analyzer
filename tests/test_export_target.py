"""Where an export is allowed to land -- the refusal matrix.

Qt-free on purpose: none of this needs a QApplication, and the rule it
encodes ("nothing is written into the evidence folder for the life of the
case") is a property of paths, not of widgets. A test that needed a window
to prove it would be a test nobody runs while changing the rule.

The junction case is the one that matters most and is the one a naive
implementation gets wrong: an examiner can create a directory junction
anywhere on the machine that points straight into the evidence folder, and
os.path.commonpath() on the UNRESOLVED path says the two have nothing in
common. Writing through it still lands in the exhibit's directory.
"""
import os

import pytest

from webcache.shell import export_target


def _mk(tmp_path, name, content=b"x"):
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


@pytest.fixture
def evidence(tmp_path):
    """An exhibit directory shaped like a real one: the .dat, a log the
    parse read, and the .chk file."""
    d = tmp_path / "exhibit"
    d.mkdir()
    dat = _mk(d, "WebCacheV01.dat")
    log = _mk(d, "V01.log")
    _mk(d, "V01.chk")
    files = {os.path.normcase(os.path.realpath(p))
             for p in (dat, log, str(d / "V01.chk"))}
    dirs = {os.path.normcase(os.path.realpath(str(d)))}
    return {"dir": str(d), "dat": dat, "log": log,
            "files": files, "dirs": dirs}


class _FakeEvidenceSet:
    def __init__(self, files):
        self.files = list(files)
        self.hashes = {p: "0" * 64 for p in files}
        self.sizes = {p: 1 for p in files}


class _FakeParser:
    def __init__(self, db_path, source_hashes):
        self.db_path = db_path
        self.source_hashes = dict(source_hashes)


# --- the refusal matrix -------------------------------------------------

def test_the_exhibit_itself_is_refused_in_its_own_words(evidence):
    reason = export_target.refuse_reason(
        evidence["dat"], evidence["files"], evidence["dirs"])
    assert reason
    assert "exhibit itself" in reason
    assert "destroy" in reason


def test_a_sibling_the_parse_read_is_refused_and_named(evidence):
    reason = export_target.refuse_reason(
        evidence["log"], evidence["files"], evidence["dirs"])
    assert reason
    assert "V01.log" in reason, "the refusal must name the file"
    assert "part of the exhibit" in reason
    assert "exhibit itself" not in reason, (
        "a companion log is not the database; two different facts must not "
        "share one sentence")


def test_any_new_file_inside_the_evidence_directory_is_refused(evidence):
    target = os.path.join(evidence["dir"], "my_export.csv")
    reason = export_target.refuse_reason(
        target, evidence["files"], evidence["dirs"])
    assert reason
    assert "for the life of the case" in reason


def test_a_subdirectory_of_the_evidence_directory_is_refused(evidence):
    target = os.path.join(evidence["dir"], "reports", "out.csv")
    reason = export_target.refuse_reason(
        target, evidence["files"], evidence["dirs"])
    assert reason


def test_a_safe_folder_passes(tmp_path, evidence):
    safe = tmp_path / "reports"
    safe.mkdir()
    assert export_target.refuse_reason(
        str(safe / "out.csv"), evidence["files"], evidence["dirs"]) == ""


def test_a_junction_pointing_into_the_evidence_folder_is_refused(
        tmp_path, evidence):
    """The case a naive commonpath() walks straight past."""
    link = tmp_path / "shortcut"
    try:
        os.symlink(evidence["dir"], str(link), target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip("cannot create a directory link here: %s" % exc)
    reason = export_target.refuse_reason(
        str(link / "out.csv"), evidence["files"], evidence["dirs"])
    assert reason, ("a link into the evidence folder must be resolved "
                    "before the comparison, not compared as written")


def test_evidence_paths_covers_the_set_and_every_file_the_parse_read(
        evidence):
    ev = _FakeEvidenceSet([evidence["dat"]])
    parser = _FakeParser(evidence["dat"], {"V01.log": "a" * 64})
    files, dirs = export_target.evidence_paths(ev, parser)
    assert os.path.normcase(os.path.realpath(evidence["dat"])) in files
    assert os.path.normcase(os.path.realpath(evidence["log"])) in files, (
        "parser.source_hashes names files the evidence set may not list; "
        "each is still part of the exhibit")
    assert os.path.normcase(os.path.realpath(evidence["dir"])) in dirs


def test_evidence_paths_survives_no_evidence_at_all():
    files, dirs = export_target.evidence_paths(None, None)
    assert files == set() and dirs == set()


# --- where the chooser opens, and what it suggests ----------------------

def test_default_export_dir_never_reads_last_evidence_dir(monkeypatch,
                                                          tmp_path):
    """The two settings keys exist precisely so a save dialog cannot open
    pointed at the exhibit."""
    evidence_dir = tmp_path / "exhibit"
    evidence_dir.mkdir()
    docs = tmp_path / "Documents"
    docs.mkdir()
    monkeypatch.setattr(
        export_target.settings, "get",
        lambda key, default=None: {"last_evidence_dir": str(evidence_dir),
                                   "last_export_dir": ""}.get(key, default))
    monkeypatch.setattr(export_target, "_documents_dir", lambda: str(docs))
    assert export_target.default_export_dir() == str(docs)


def test_default_export_dir_uses_last_export_dir_when_it_still_exists(
        monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(
        export_target.settings, "get",
        lambda key, default=None: {"last_export_dir": str(out)}.get(key, default))
    assert export_target.default_export_dir() == str(out)


def test_default_export_dir_falls_back_when_the_saved_dir_is_gone(
        monkeypatch, tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    monkeypatch.setattr(
        export_target.settings, "get",
        lambda key, default=None: {
            "last_export_dir": str(tmp_path / "deleted")}.get(key, default))
    monkeypatch.setattr(export_target, "_documents_dir", lambda: str(docs))
    assert export_target.default_export_dir() == str(docs)


def test_the_settings_key_is_a_named_constant_not_a_literal():
    assert export_target.LAST_EXPORT_DIR_KEY == "last_export_dir"


WHEN = __import__("datetime").datetime(
    2026, 10, 17, 10, 15, 22, tzinfo=__import__("datetime").timezone.utc)


def test_a_filtered_export_says_so_in_its_own_filename():
    whole = export_target.suggest_name("webcache_history", ".csv", False,
                                       when=WHEN)
    part = export_target.suggest_name("webcache_history", ".csv", True,
                                      when=WHEN)
    assert whole == "WebCache_history_20261017-101522Z.csv"
    assert part == "WebCache_history_FILTERED_20261017-101522Z.csv"
    assert part.endswith(".csv"), "the marker goes BEFORE the extension"


def test_the_filename_leads_with_the_case_number_when_there_is_one():
    """A folder of exports from several cases, or the same view exported
    twice, must not collide or be told apart only by memory: the case
    number and the UTC time of the export are in the name."""
    name = export_target.suggest_name("webcache_history", ".csv", False,
                                      case_number="CASE 2026/117",
                                      when=WHEN)
    assert name == "CASE-2026-117_history_20261017-101522Z.csv"


def test_a_case_number_cannot_put_a_path_in_the_name():
    backslash = chr(92)
    name = export_target.suggest_name("webcache_report", ".pdf", False,
                                      case_number=".." + backslash + "x:/y*?",
                                      when=WHEN)
    assert backslash not in name and "/" not in name and ":" not in name
    assert name.endswith("_report_20261017-101522Z.pdf")


def test_safe_alternative_leaves_the_evidence_directory(evidence,
                                                        monkeypatch, tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    monkeypatch.setattr(export_target, "default_export_dir", lambda: str(docs))
    chosen = os.path.join(evidence["dir"], "webcache_history.csv")
    alt = export_target.safe_alternative(chosen, evidence["dirs"])
    assert os.path.basename(alt) == "webcache_history.csv"
    assert export_target.refuse_reason(
        alt, evidence["files"], evidence["dirs"]) == "", (
        "the alternative offered must itself pass the refusal check")
