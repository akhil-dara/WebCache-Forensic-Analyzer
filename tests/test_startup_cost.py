"""What the application must NOT pay for before it can show a window.

MEASURED, not assumed. `python -X importtime -c "import
webcache.shell.main_window"` on this machine: 18.5 s cumulative, of which
forensic_engine was 15.5 s -- openpyxl 9.6 s (which pulls numpy) and
reportlab 1.9 s. Both were imported by a module-level try/except whose only
purpose was to set HAS_OPENPYXL / HAS_REPORTLAB, so an examiner waited ten
seconds for two libraries before seeing anything, and paid it again on
every launch whether or not they ever exported.

Availability is a question about the ENVIRONMENT, and importlib answers it
without executing the package. The writers import what they need when they
are actually called.

These tests pin the property, not a timing: a wall-clock budget on a shared
VM is exactly the flaky-perf-test shape this project already has trouble
with (see test_perf.py). "Is this module in sys.modules" is deterministic.
"""
import subprocess
import sys


def _modules_after(statement):
    """The set of top-level modules a fresh interpreter ends up holding."""
    code = ("import sys; %s; "
            "print(' '.join(sorted({m.split('.')[0] for m in sys.modules})))"
            % statement)
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    return set(out.stdout.split())


def test_showing_a_window_does_not_import_the_export_libraries():
    mods = _modules_after("import webcache.shell.main_window")
    heavy = {"openpyxl", "reportlab", "numpy"} & mods
    assert not heavy, (
        "importing the shell pulls in %s -- measured at ~11.5 s of the "
        "~18.5 s it takes to import main_window at all, paid on every "
        "launch by every examiner, including those who never export"
        % sorted(heavy))


def test_the_engine_still_reports_what_is_installed():
    """The capability flags export_formats reads must survive the change."""
    from webcache.engine import forensic_engine
    assert isinstance(forensic_engine.HAS_OPENPYXL, bool)
    assert isinstance(forensic_engine.HAS_REPORTLAB, bool)


def test_the_flags_agree_with_whether_the_package_can_be_imported():
    """A flag that says False while the package imports fine would silently
    disable a format the examiner actually has."""
    import importlib
    from webcache.engine import forensic_engine
    for name, flag in (("openpyxl", forensic_engine.HAS_OPENPYXL),
                       ("reportlab", forensic_engine.HAS_REPORTLAB)):
        try:
            importlib.import_module(name)
            really = True
        except ImportError:
            really = False
        assert flag == really, "%s: flag %r, import %r" % (name, flag, really)
