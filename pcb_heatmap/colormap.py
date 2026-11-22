"""Named colour ramps shared by the PCB canvas and the result viewer.

``rainbow`` is the palette released in 0.3.4 and stays byte-identical; the
other ramps are additions offered by the appearance settings.  Keeping the
ramp here removes the copy that used to live in both ``gui.py`` and
``board_view.py``.
"""
from __future__ import annotations

import numpy as np

DEFAULT_RAMP = 'rainbow'

# Seven-stop ramps keep the interpolation identical to 0.3.4 for the default.
RAMPS = {
    'rainbow': ((22, 42, 88), (30, 104, 207), (26, 190, 205), (86, 209, 116),
                (246, 224, 66), (245, 128, 32), (198, 34, 36)),
    'turbo': ((48, 18, 59), (70, 107, 227), (38, 190, 214), (92, 226, 150),
              (196, 233, 74), (252, 175, 46), (238, 96, 24), (180, 24, 10),
              (122, 4, 3)),
    'viridis': ((68, 1, 84), (72, 40, 120), (62, 74, 137), (49, 104, 142),
                (38, 130, 142), (31, 158, 137), (53, 183, 121), (109, 205, 89),
                (180, 222, 44), (253, 231, 37)),
    'inferno': ((0, 0, 4), (27, 12, 65), (74, 12, 107), (120, 28, 109),
                (165, 44, 96), (207, 68, 70), (237, 105, 37), (251, 155, 6),
                (247, 209, 61), (252, 255, 164)),
    'magma': ((0, 0, 4), (24, 15, 61), (68, 15, 118), (114, 31, 129),
              (158, 47, 127), (205, 64, 113), (241, 96, 93), (253, 150, 104),
              (254, 202, 141), (252, 253, 191)),
    'gray': ((12, 12, 14), (247, 247, 247)),
}

RAMP_ORDER = ('rainbow', 'turbo', 'viridis', 'inferno', 'magma', 'gray')

#: Painted where the mesh has no finite value (only used by panels that do not
#: composite the map over the board, so it never hides copper).
INVALID_RGB = np.array([237, 242, 246], dtype=np.uint8)


def ramp_names():
    return list(RAMP_ORDER)


def valid_ramp(name):
    return name if name in RAMPS else DEFAULT_RAMP


def stops(name=DEFAULT_RAMP):
    return np.asarray(RAMPS[valid_ramp(name)], dtype=float)


def colorize(values, valid, low, high, ramp=DEFAULT_RAMP, invalid=INVALID_RGB):
    """Interpolate a ramp over ``values`` and return an ``(h, w, 3)`` uint8 map.

    The arithmetic is deliberately unchanged from 0.3.4: a single linear scale
    with no smoothing of numerical cells.  Invalid cells receive ``invalid``.
    """
    table = stops(ramp)
    values = np.asarray(values, dtype=float)
    valid = np.asarray(valid, dtype=bool)
    span = max(float(high) - float(low), 1e-12)
    normalized = np.clip((np.nan_to_num(values, nan=low) - low) / span, 0, 1)
    positions = normalized * (len(table) - 1)
    index = np.minimum(positions.astype(int), len(table) - 2)
    weight = (positions - index)[..., None]
    rgb = np.asarray(table[index] * (1 - weight) + table[index + 1] * weight,
                     dtype=np.uint8)
    if valid.shape == rgb.shape[:2]:
        rgb = np.where(valid[..., None], rgb,
                       np.asarray(invalid, dtype=np.uint8)[None, None, :])
    return np.ascontiguousarray(rgb)


def ramp_colors(ramp=DEFAULT_RAMP, count=64):
    """Return ``count`` evenly spaced ramp colours as a uint8 array."""
    count = max(2, int(count))
    samples = np.linspace(0., 1., count)
    return colorize(samples[None, :], np.ones((1, count), bool), 0., 1., ramp)[0]


def legend_ticks(low, high, count=5):
    """Tick values for a linear legend, collapsed when the span is empty."""
    low, high = float(low), float(high)
    count = max(2, int(count))
    if not np.isfinite(low) or not np.isfinite(high) or abs(high - low) <= 1e-12 * max(1., abs(low), abs(high)):
        return [low]
    return [float(value) for value in np.linspace(low, high, count)]


def format_number(value, digits=4):
    """Compact engineering notation for legends and result labels."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return '—'
    if not np.isfinite(value):
        return '—'
    magnitude = abs(value)
    if magnitude != 0 and (magnitude < 1e-3 or magnitude >= 1e5):
        return f'{value:.{max(1, digits - 1)}e}'
    text = f'{value:.{digits}g}'
    return text.replace('e+', 'e')
