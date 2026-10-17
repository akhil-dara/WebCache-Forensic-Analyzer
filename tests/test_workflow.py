"""The release workflow, checked as text.

A workflow that cannot be verified without pushing a tag is a workflow that
gets debugged in production.
"""
import pathlib

WF = (pathlib.Path(__file__).resolve().parents[1]
      / ".github" / "workflows" / "release.yml")


def test_the_workflow_exists():
    assert WF.is_file()


def test_it_triggers_on_a_version_tag():
    text = WF.read_text(encoding="utf-8")
    assert "tags:" in text and "v*" in text


def test_it_installs_essentials_not_the_metapackage():
    text = WF.read_text(encoding="utf-8")
    assert "PySide6-Essentials" in text
    assert "pip install PySide6\n" not in text


def test_tests_run_before_the_build_and_can_fail_the_release():
    text = WF.read_text(encoding="utf-8")
    assert text.index("pytest") < text.index("PyInstaller")


def test_it_carries_the_no_op_guard():
    """A suite that degraded to running nothing looks identical to a passing
    one. The existing tests.yml fails under 300 checks; keep that here."""
    text = WF.read_text(encoding="utf-8")
    assert "degraded" in text or "no-op" in text


def test_it_needs_permission_to_create_a_release():
    text = WF.read_text(encoding="utf-8")
    assert "contents: write" in text


def test_it_publishes_checksums():
    assert "SHA256SUMS" in WF.read_text(encoding="utf-8")


def test_it_runs_the_build_checker():
    assert "check_build.py" in WF.read_text(encoding="utf-8")


# --- installer and portable downloads ------------------------------------

ISS = WF.parents[2] / "packaging" / "webcache.iss"


def test_it_ships_an_installer_and_both_portable_builds():
    text = WF.read_text(encoding="utf-8")
    for name in ("-setup.exe", "-portable.zip", "-portable.exe"):
        assert name in text


def test_every_built_program_is_self_tested_before_publishing():
    text = WF.read_text(encoding="utf-8")
    assert text.count("--self-test") >= 2
    assert text.index("--self-test") < text.index("gh release create")


def test_the_installer_is_installed_run_and_uninstalled_on_the_runner():
    text = WF.read_text(encoding="utf-8")
    assert "/CURRENTUSER" in text and "unins000.exe" in text


def test_the_tag_must_match_the_version():
    assert "does not match version" in WF.read_text(encoding="utf-8")


def test_the_installer_needs_no_admin_and_offers_all_users():
    text = ISS.read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text
    assert "PrivilegesRequiredOverridesAllowed=dialog commandline" in text
    assert "{autopf}" in text and "{autoprograms}" in text
    assert "desktopicon" in text and "unchecked" in text


def test_the_installer_marks_the_copy_installed():
    from webcache import paths
    text = ISS.read_text(encoding="utf-8")
    assert 'Source: "%s"' % paths.INSTALLED_MARKER in text
    assert (ISS.parent / paths.INSTALLED_MARKER).is_file()
    assert "LicenseFile=..\\LICENSE" in text
    assert (WF.parents[2] / "LICENSE").is_file()


def test_a_failing_suite_still_builds_but_never_publishes():
    """One run shows every problem: the suites do not stop the build, the
    self-tests or the installer -- and the job still fails at the end, so
    the publish job (which needs it) never runs. Read as text: PyYAML is
    not a dependency of this project."""
    text = WF.read_text(encoding="utf-8")
    suites = text.index("- name: Run the suites")
    block = text[suites:text.index("- ", suites + 10)]
    assert "id: suites" in block and "continue-on-error: true" in block
    fail = text.index("- name: Fail the release if any test failed")
    assert "if: steps.suites.outcome == 'failure'" in text[fail:fail + 200]
    assert suites < text.index("- name: Build the installer") < fail
    assert fail < text.index("  publish:")
