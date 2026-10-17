"""The application's mark, as geometry only.

The mark is drawn by Qt at runtime (webcache/shell/icon.py) and by Pillow
at build time (packaging/build_icon.py); both read their shapes from here.
This module imports nothing, so the build script stays free of Qt.

The mark is a globe cut into horizontal cache-record layers, one layer
shifted out of line in teal: a record recovered from where it no longer
sits. Below 32 px it uses three wider bands and no meridian, so it stays
legible at taskbar size.
"""

#: The globe, in a 0..1 box.
CENTRE = (0.5, 0.5)
RADIUS = 0.342

#: The layers, as (top, bottom, shift, recovered) in 0..1 units. `shift`
#: moves that layer's slice of the globe to the right; `recovered`
#: paints it in RECOVERED rather than the mark colour.
_BANDS_LARGE = (
    (0.1583, 0.3271, 0.0, False),
    (0.3729, 0.4771, 0.0, False),
    (0.5229, 0.6271, 0.0667, True),
    (0.6729, 0.8417, 0.0, False),
)
_BANDS_SMALL = (
    (0.1583, 0.3250, 0.0, False),
    (0.4167, 0.5833, 0.0, False),
    (0.6750, 0.8417, 0.0, False),
)
_SMALL_BELOW = 32

#: The meridian: an outline in the backing colour, drawn from 32 px up.
_MERIDIAN_RX = 0.1417
_MERIDIAN_STROKE = 0.0458

#: The recovered layer's colour (teal), as RGB. The mark colour and the
#: backing are the theme's primary and window colours, passed in.
RECOVERED = (11, 181, 166)


def bands(size):
    """The layers for an icon `size` px square, as
    (top, bottom, shift, recovered) in pixels."""
    spec = _BANDS_SMALL if size < _SMALL_BELOW else _BANDS_LARGE
    return [(top * size, bottom * size, shift * size, recovered)
            for top, bottom, shift, recovered in spec]


def disc_bbox(size, shift=0.0):
    """The globe's bounding box in pixels, moved right by `shift` px."""
    cx, cy = CENTRE
    return (cx * size - RADIUS * size + shift, cy * size - RADIUS * size,
            cx * size + RADIUS * size + shift, cy * size + RADIUS * size)


def meridian(size):
    """((x0, y0, x1, y1), stroke) in pixels, or None below 32 px."""
    if size < _SMALL_BELOW:
        return None
    cx, cy = CENTRE
    return ((cx * size - _MERIDIAN_RX * size, cy * size - RADIUS * size,
             cx * size + _MERIDIAN_RX * size, cy * size + RADIUS * size),
            _MERIDIAN_STROKE * size)


def backing_radius(size):
    """The corner radius of the rounded square the mark sits on."""
    return size * 0.22
