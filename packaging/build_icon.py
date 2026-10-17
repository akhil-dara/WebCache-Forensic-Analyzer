"""Render packaging/webcache.ico at build time.

The application draws its mark with Qt at runtime (webcache/shell/icon.py).
The executable's file icon is needed before any Qt application exists, so
this module draws the same mark with Pillow from the shared geometry in
webcache/shell/mark.py. The .ico is generated on every build rather than
stored in the repository.
"""
import pathlib
import sys

from PIL import Image, ImageChops, ImageDraw

# Run as a plain script from packaging/; mark.py has no Qt dependency.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from webcache.shell import mark  # noqa: E402

#: Each size is drawn at its own resolution rather than scaled from one
#: large bitmap, so small sizes stay sharp.
SIZES = (16, 24, 32, 48, 64, 128, 256)

#: The dark theme's window and primary colours (webcache/shell/theme.py),
#: as literals so this script does not import Qt.
_BG = (13, 17, 23, 255)      # #0D1117
_MARK = (0, 229, 158, 255)   # #00E59E
_RECOVERED = mark.RECOVERED + (255,)


def _render(size):
    """The mark at one size, matching paint_mark() in webcache/shell/icon.py."""
    # Pillow does not antialias fills, so each size is drawn at 4x and
    # reduced.
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle((0, 0, big - 1, big - 1),
                           radius=mark.backing_radius(big), fill=_BG)
    # The layers for `size`: small icons use fewer, wider bands.
    for top, bottom, shift, recovered in mark.bands(size):
        disc = Image.new("L", (big, big), 0)
        ImageDraw.Draw(disc).ellipse(
            [v * scale for v in mark.disc_bbox(size, shift)], fill=255)
        band = Image.new("L", (big, big), 0)
        ImageDraw.Draw(band).rectangle(
            (0, top * scale, big, bottom * scale), fill=255)
        layer = ImageChops.multiply(disc, band)
        img.paste(_RECOVERED if recovered else _MARK, (0, 0), layer)
    meridian = mark.meridian(size)
    if meridian is not None:
        box, stroke = meridian
        draw.ellipse([v * scale for v in box], outline=_BG,
                     width=max(1, round(stroke * scale)))

    img = img.resize((size, size), Image.LANCZOS)
    return img


def build_ico(dest):
    """Write every size in SIZES into one multi-resolution .ico at `dest`.

    One image is passed per size so the ICO writer stores each as drawn
    instead of resizing a single source."""
    frames = [_render(size) for size in SIZES]
    dest = pathlib.Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(dest, format="ICO",
                     sizes=[(s, s) for s in SIZES],
                     append_images=frames[:-1])
    return dest


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else (
        pathlib.Path(__file__).resolve().parent / "webcache.ico")
    print("wrote", build_ico(target))
