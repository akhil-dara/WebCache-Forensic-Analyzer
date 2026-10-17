import pytest
from PySide6.QtGui import QColor, QPalette

from webcache.shell import settings, theme


def test_every_palette_defines_every_role():
    roles = set(theme.PALETTES["dark"])
    for name, palette in theme.PALETTES.items():
        assert set(palette) == roles, "%s is missing %s" % (
            name, roles - set(palette))


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_apply_sets_tooltip_link_and_disabled_roles_on_the_qpalette(
        qapp, theme_name):
    """The dict having the keys proves nothing about the actual QPalette --
    this project has repeatedly found tests that assert a thing exists
    rather than that it works. apply() must carry ToolTipBase/ToolTipText,
    Link/LinkVisited and the Disabled group of WindowText/Text/ButtonText/
    Highlight through onto qapp.palette() itself, not just leave them
    sitting in PALETTES unused. Reading the roles back off qapp.palette()
    (rather than off the local QPalette apply() built) is what catches a
    regression where apply() constructs the right QPalette and then, say,
    forgets to call app.setPalette(pal) -- the exact "half applied" defect
    class this fix exists to close.
    """
    theme.apply(qapp, theme_name)
    p = theme.PALETTES[theme_name]
    pal = qapp.palette()

    assert pal.color(QPalette.ToolTipBase) == QColor(p["tooltip_base"])
    assert pal.color(QPalette.ToolTipText) == QColor(p["tooltip_text"])
    assert pal.color(QPalette.Link) == QColor(p["link"])
    assert pal.color(QPalette.LinkVisited) == QColor(p["link_visited"])

    disabled_text = QColor(p["disabled_text"])
    assert pal.color(QPalette.Disabled, QPalette.WindowText) == disabled_text
    assert pal.color(QPalette.Disabled, QPalette.Text) == disabled_text
    assert pal.color(QPalette.Disabled, QPalette.ButtonText) == disabled_text
    assert pal.color(QPalette.Disabled, QPalette.Highlight) == QColor(
        p["disabled_highlight"])

    # And the Disabled group must actually differ from the Active/Normal
    # group -- a palette that sets Disabled.Text to the same colour as the
    # ordinary Text role would pass the assertions above while still
    # leaving a disabled control looking indistinguishable from an enabled
    # one on screen.
    assert (pal.color(QPalette.Disabled, QPalette.Text)
            != pal.color(QPalette.Active, QPalette.Text))


def test_the_primary_is_emerald_not_a_default_blue():
    """The tool must not look like a framework demo."""
    assert theme.PALETTES["dark"]["primary"].upper() == "#00E59E"


def test_apply_actually_changes_the_application_palette(qapp):
    theme.apply(qapp, "dark")
    bg = qapp.palette().window().color()
    theme.apply(qapp, "light")
    assert qapp.palette().window().color() != bg


def test_apply_actually_changes_the_application_stylesheet(qapp):
    """Applying a theme is two halves -- QPalette and stylesheet -- and the
    palette half already has a test above. This is the stylesheet half's.

    Deleting `app.setStyleSheet(...)` from apply() left every other test in
    this file green, because nothing anywhere read qapp.styleSheet(). That
    is the regression to guard against: one half of
    apply() gets removed (or never written) and the suite stays green while
    the window goes half-painted. Checking for each theme's own primary
    color, rather than just "is non-empty", means this can't pass on a
    stylesheet left over from the previous apply() call.
    """
    theme.apply(qapp, "dark")
    assert theme.PALETTES["dark"]["primary"] in qapp.styleSheet()
    theme.apply(qapp, "light")
    assert theme.PALETTES["light"]["primary"] in qapp.styleSheet()


def test_theme_label_matches_what_is_applied(qapp):
    """A label reading 'Teal - light' over a dark window was a real bug.

    theme._current defaults to "dark" at import time, so a test that only
    ever calls apply(qapp, "dark") would still pass even if apply() were a
    no-op that never touched _current at all -- the assertion could not
    fail. Applying "light" first, and checking the label both ways, forces
    current_label() to actually track what apply() last set rather than
    coasting on the module's initial default.
    """
    theme.apply(qapp, "light")
    assert theme.current_label().endswith("light")
    theme.apply(qapp, "dark")
    assert theme.current_label().endswith("dark")


def test_a_failed_apply_leaves_the_label_naming_the_theme_still_on_screen(qapp):
    """_current is written only after setPalette AND setStyleSheet have
    both returned. If apply() blows up partway through -- here, forced by
    an app stand-in whose setStyleSheet always raises -- current_label()
    must keep naming the theme that was applied before, because that is
    what is actually still on screen. Reading _current first and hoping
    nothing in between fails is exactly the gap hazard 2 is about.

    A lightweight stand-in is used instead of monkeypatching the real
    QApplication's setStyleSheet: apply() only ever calls .setPalette and
    .setStyleSheet on its `app` argument, so anything providing those two
    methods exercises the same code path without depending on how a
    shiboken-wrapped C++ method reacts to being overridden per instance.
    """
    class _RaisesOnStyleSheet:
        def setPalette(self, pal):
            pass

        def setStyleSheet(self, sheet):
            raise RuntimeError("boom")

    theme.apply(qapp, "dark")
    with pytest.raises(RuntimeError):
        theme.apply(_RaisesOnStyleSheet(), "light")
    assert theme.current_label().endswith("dark")


def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    settings.save(theme="light", last_evidence_dir=r"D:\case\exhibit")
    assert settings.get("theme") == "light"
    assert settings.get("last_evidence_dir") == r"D:\case\exhibit"


def test_missing_settings_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "nope.json")
    assert settings.get("theme", "dark") == "dark"


def test_corrupt_settings_file_does_not_stop_the_app(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr("webcache.paths.settings_path", lambda: p)
    assert settings.get("theme", "dark") == "dark"


def test_save_does_not_raise_when_the_destination_is_unwritable(tmp_path, monkeypatch):
    """The write-side half of test_corrupt_settings_file_does_not_stop_the_app
    above. load() already tolerates a bad file on disk; save() -- called
    unconditionally from MainWindow.closeEvent on every window close -- had
    no equivalent guard, so on read-only app-local media (a locked-down
    forensic workstation, write-protected portable media -- the exact VM/
    RDP deployment the packaging spec justifies opengl32sw.dll for)
    closing the window raised an uncaught OSError.

    Pointed at a path whose PARENT directory does not exist, so open()
    itself fails with a genuine OSError -- cross-platform, unlike relying
    on chmod-style permission bits that behave differently on Windows.
    """
    monkeypatch.setattr(
        "webcache.paths.settings_path",
        lambda: tmp_path / "no-such-directory" / "settings.json")
    result = settings.save(theme="light")
    assert result["theme"] == "light", (
        "the in-memory merge must still succeed even though persisting it "
        "did not")


def test_load_does_not_alias_column_state_to_the_module_default(tmp_path, monkeypatch):
    """dict(DEFAULTS) is a shallow copy: when a stored file omits
    "column_state", the naive merge makes the returned dict's
    "column_state" the very same object as DEFAULTS["column_state"].
    Mutating it in place -- the obvious way to record a view's column
    widths -- would then leak into every other view and survive across
    process-wide load() calls forever, silently.
    """
    monkeypatch.setattr("webcache.paths.settings_path",
                        lambda: tmp_path / "settings.json")
    first = settings.load()
    first["column_state"]["history"] = 240
    second = settings.load()
    assert second["column_state"] == {}
    assert settings.DEFAULTS["column_state"] == {}
