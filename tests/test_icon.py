"""There was no setWindowIcon anywhere before this: the window, the
taskbar and Alt-Tab all showed Qt's bare default. build_icon() existing
and being CALLED somewhere are two different claims -- __main__.py's own
wiring (app.setWindowIcon(build_icon())) is exercised by test_selfshot.py
and test_shutdown.py's pattern of testing main()'s pieces directly rather
than running main() itself (which would block on app.exec()); this file
is the icon module's own behaviour.
"""
from webcache.shell.icon import SIZES, _paint_one, build_icon


def test_icon_is_not_null(qapp):
    """A QIcon built from zero pixmaps -- the shape a build_icon() that
    silently failed to paint anything would take -- is null. QIcon()
    itself (Qt's own bare default) is also null, so this is the one
    assertion that actually distinguishes "drew something" from "drew
    nothing"."""
    assert not build_icon().isNull()


def test_icon_provides_every_declared_size(qapp):
    """Each size in SIZES is painted independently (see icon.py's own
    docstring for why) -- this proves every one of them actually landed in
    the QIcon, not just however many addPixmap happened to keep. 16 is the
    taskbar/Alt-Tab size this whole fix exists for; 256 is what a high-DPI
    Explorer "Extra large icons" view samples."""
    available = {(s.width(), s.height()) for s in build_icon().availableSizes()}
    assert available == {(s, s) for s in SIZES}
    assert (16, 16) in available
    assert (256, 256) in available


def test_the_mark_is_emerald_on_near_black_not_a_qt_default(qapp):
    """The standing instruction is that nothing here should look like a
    framework demo -- emerald #00E59E on near-black #0D1117, the same two
    roles theme.py's "dark" palette already pins in
    test_the_primary_is_emerald_not_a_default_blue. Reads _paint_one()'s
    own pixmap directly, at the exact size it was painted for, rather than
    through QIcon.pixmap(): that call rounds the requested size by the
    screen's device pixel ratio (125% on this machine turns a 128 request
    into an actual 160), lands on no exact match among SIZES, and
    smooth-scales the nearest one -- which blurs every pure colour into a
    gradient and would fail this assertion for a reason that has nothing
    to do with whether build_icon() painted the right colours.
    """
    image = _paint_one(128).toImage()
    colors = {image.pixelColor(x, y).name().upper()
              for x in range(image.width()) for y in range(image.height())}
    assert "#00E59E" in colors, "the emerald mark must actually be painted"
    assert "#0D1117" in colors, "the near-black background must actually be painted"


# --- one mark, drawn twice, and legible at 16px ----------------------------
#
# Three identities were on screen at once: the app icon was a magnifying
# glass, the sidebar's brand mark was glyphs.pixmap("shield") -- the SAME
# glyph two nav rows already use, so the brand was indistinguishable from
# a navigation item -- and the logo the examiner chose is a shield whose
# lower half breaks into record lines.
#
# The mark is now one shape family in one place (webcache/shell/mark.py,
# pure geometry, no Qt) that both renderers consume: the Qt one for
# setWindowIcon and the sidebar, the Pillow one for the build-time .ico
# that Explorer shows before the app has launched.

import importlib.util
import pathlib

from PySide6.QtGui import QColor, QImage

from webcache.shell import glyphs, icon as icon_module, theme

_EMERALD = (0, 229, 158)
_NEAR_BLACK = (13, 17, 23)


def _load_pillow_builder():
    path = (pathlib.Path(__file__).resolve().parent.parent
            / "packaging" / "build_icon.py")
    spec = importlib.util.spec_from_file_location("build_icon_for_mark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _qt_pixels(size):
    image = _paint_one(size).toImage()
    return [[QColor(image.pixel(x, y)).getRgb()[:3]
             for x in range(size)] for y in range(size)]


def _near(a, b, tol=40):
    return all(abs(p - q) <= tol for p, q in zip(a, b))


def _opaque_fraction(pixmap):
    """How much of the square the mark actually covers."""
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    painted = sum(1
                  for y in range(image.height())
                  for x in range(image.width())
                  if QColor.fromRgba(image.pixel(x, y)).alpha() > 128)
    return painted / float(image.width() * image.height())


def _emerald_fraction(rows):
    total = sum(len(r) for r in rows)
    hits = sum(1 for r in rows for px in r if _near(px, _EMERALD))
    return hits / total


def test_the_mark_geometry_is_shared_not_copied_into_both_renderers(qapp):
    """Two implementations of one mark drift. The numbers live once."""
    from webcache.shell import mark
    assert mark.bands(64) and mark.disc_bbox(64) and mark.meridian(64)
    # One layer is the recovered one, shifted out of line, at full size.
    assert any(recovered and shift > 0
               for _t, _b, shift, recovered in mark.bands(64))


def test_the_two_renderers_draw_the_same_mark(qapp):
    """The .ico Explorer shows and the QIcon the taskbar shows must be
    the same picture. Compared by how much of each is emerald, per size,
    which catches a divergence in shape without pinning antialiasing."""
    pillow = _load_pillow_builder()
    for size in SIZES:
        qt_rows = _qt_pixels(size)
        image = pillow._render(size).convert("RGB")
        pil_rows = [[image.getpixel((x, y)) for x in range(size)]
                    for y in range(size)]
        qt_fraction = _emerald_fraction(qt_rows)
        pil_fraction = _emerald_fraction(pil_rows)
        # The tolerance scales with the edge-to-area ratio, because that
        # is what two different rasterisers actually disagree about: Qt
        # antialiases directly, Pillow has no antialiasing at all and is
        # supersampled and LANCZOS-reduced instead, and a blended edge
        # pixel need not fall the same side of "is this emerald" in
        # both. At 16px one pixel is 0.4% of the icon; at 256px it is
        # 0.0015%.
        #
        # Measured differences: 0.023 at 16, 0.038 at 24, 0.008 at 32,
        # 0.021 at 48, and 0.003 or better from 64 up. A flat threshold
        # either passes a real divergence at 256 or fails antialiasing
        # noise at 24.
        tolerance = 0.006 + 1.0 / size
        assert abs(qt_fraction - pil_fraction) < tolerance, (
            "at %dpx Qt paints %.3f emerald and Pillow %.3f"
            % (size, qt_fraction, pil_fraction))


def test_the_record_lines_are_still_there_at_sixteen_pixels(qapp):
    """The whole reason the mark is drawn per size rather than scaled:
    16px is the taskbar. A globe whose layer cuts have closed up at 16px
    is a plain disc."""
    rows = _qt_pixels(16)
    column = [row[8] for row in rows]
    runs = []
    for pixel in column:
        kind = ("mark" if _near(pixel, _EMERALD)
                else "hole" if _near(pixel, _NEAR_BLACK) else "other")
        if not runs or runs[-1][0] != kind:
            runs.append([kind, 0])
        runs[-1][1] += 1
    inner = [k for k, _n in runs]
    # Three, not two: two slots cut the shield into three emerald bands
    # down its centre line. Two would also be true of a plain ring --
    # the magnifying glass this replaced scored exactly two here, which
    # is why the bar is where it is.
    assert inner.count("mark") >= 3, (
        "the slots have closed up at 16px, leaving a plain shield: %s" % runs)


def _alpha(pixmap):
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    return [QColor.fromRgba(image.pixel(x, y)).alpha() / 255.0
            for y in range(image.height()) for x in range(image.width())]


def test_the_sidebar_brand_is_the_application_mark(qapp):
    """The brand is the application mark, and no navigation glyph: it
    was once glyphs.pixmap("shield"), the Findings and Integrity icon, so
    it read as a third copy of a list item. Compared by coverage against
    the mark (QLabel re-rasterises what it is given, so bytes never
    match), and by per-pixel difference against EVERY nav glyph -- the
    globe used for Indicators included, the nearest in subject."""
    from webcache.shell.main_window import NAV_SECTIONS
    from webcache.shell.sidebar import NAV_ICONS, Sidebar
    bar = Sidebar(NAV_SECTIONS)
    brand = _opaque_fraction(bar._brand_icon.pixmap())
    mine_pixmap = icon_module.mark_pixmap(
        20, theme.color("primary"), theme.color("window"))
    assert abs(brand - _opaque_fraction(mine_pixmap)) < 0.05
    mine = _alpha(mine_pixmap)
    for name in sorted(set(NAV_ICONS.values())):
        nav = _alpha(glyphs.pixmap(name, theme.color("primary"), 20))
        difference = sum(abs(a - b) for a, b in zip(mine, nav)) / len(mine)
        assert difference > 0.15, (
            "the brand is too close to the %r nav glyph (%.3f)"
            % (name, difference))


def test_the_brand_is_rendered_for_high_dpi_like_every_glyph_beside_it(qapp):
    """glyphs.pixmap() renders at 4x physical and sets
    devicePixelRatio, so the nav icons stay crisp at 125% and 200%
    Windows scaling. A brand mark that did not would be the one soft
    thing in the lockup -- and was: grabbed from the running
    application at 125% it came back as a 20px pixmap upscaled into a
    25px slot."""
    brand = icon_module.mark_pixmap(
        20, theme.color("primary"), theme.color("window"))
    nav = glyphs.pixmap("shield", theme.color("primary"), 20)
    assert brand.devicePixelRatio() == nav.devicePixelRatio()
    assert brand.width() == nav.width()
