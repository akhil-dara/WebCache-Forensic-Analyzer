"""--self-test: what the release workflow runs against every built
program before it is published."""
import json

from webcache import __main__ as entry


def test_the_self_test_reports_a_working_program(tmp_path, qtbot):
    out = tmp_path / "self-test.json"
    assert entry.self_test(str(out)) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["views"] >= 16
    assert report["page_bytes"] > 10_000
    assert report["installed"] is False
    assert report["version"]


def test_a_broken_program_fails_the_self_test_and_says_why(tmp_path, qtbot,
                                                           monkeypatch):
    from webcache.shell import html_package
    monkeypatch.setattr(html_package, "page_script",
                        lambda: (_ for _ in ()).throw(FileNotFoundError("util.js")))
    out = tmp_path / "self-test.json"
    assert entry.self_test(str(out)) == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["ok"] is False and "util.js" in report["error"]
