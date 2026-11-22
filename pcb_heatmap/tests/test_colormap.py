"""Shared colour ramps: legacy parity, endpoints, masks and legends."""
from __future__ import annotations

import numpy as np
import unittest

from pcb_heatmap import colormap


def legacy_colorize(values, valid, low, high):
    """The 0.3.4 implementation, kept here as the parity oracle."""
    stops = np.array([[22, 42, 88], [30, 104, 207], [26, 190, 205],
                      [86, 209, 116], [246, 224, 66], [245, 128, 32],
                      [198, 34, 36]], dtype=float)
    normalized = np.clip((np.nan_to_num(values, nan=low) - low) / max(high - low, 1e-12), 0, 1)
    positions = normalized * (len(stops) - 1)
    a = np.minimum(positions.astype(int), len(stops) - 2)
    weight = (positions - a)[..., None]
    rgb = np.asarray(stops[a] * (1 - weight) + stops[a + 1] * weight, dtype=np.uint8)
    rgb[~valid] = [237, 242, 246]
    return np.ascontiguousarray(rgb)


class ColorMapTests(unittest.TestCase):
    def test_default_ramp_is_bit_identical_to_release_0_3_4(self):
        generator = np.random.default_rng(20260101)
        values = generator.normal(50, 30, size=(7, 11))
        values[2, 3] = np.nan
        valid = generator.random((7, 11)) > 0.2
        expected = legacy_colorize(values, valid, 0.0, 90.0)
        actual = colormap.colorize(values, valid, 0.0, 90.0)
        self.assertTrue(np.array_equal(expected, actual))

    def test_endpoints_land_on_the_first_and_last_stop(self):
        low, high = -5.0, 15.0
        sample = colormap.colorize(np.array([[low, high]]), np.ones((1, 2), bool), low, high)
        self.assertEqual(tuple(sample[0, 0]), colormap.RAMPS['rainbow'][0])
        self.assertEqual(tuple(sample[0, 1]), colormap.RAMPS['rainbow'][-1])

    def test_invalid_cells_use_the_sentinel_colour(self):
        values = np.array([[1.0, 2.0, 3.0]])
        valid = np.array([[True, False, True]])
        rgb = colormap.colorize(values, valid, 1.0, 3.0)
        self.assertEqual(tuple(rgb[0, 1]), tuple(colormap.INVALID_RGB))
        custom = colormap.colorize(values, valid, 1.0, 3.0, invalid=(1, 2, 3))
        self.assertEqual(tuple(custom[0, 1]), (1, 2, 3))

    def test_flat_field_and_empty_span_do_not_divide_by_zero(self):
        values = np.full((2, 3), 42.0)
        rgb = colormap.colorize(values, np.ones((2, 3), bool), 42.0, 42.0)
        self.assertEqual(rgb.shape, (2, 3, 3))
        self.assertTrue(np.all(rgb == rgb[0, 0]))
        self.assertEqual(colormap.legend_ticks(42.0, 42.0), [42.0])

    def test_every_declared_ramp_renders_and_is_ordered(self):
        for name in colormap.ramp_names():
            colors = colormap.ramp_colors(name, 16)
            self.assertEqual(colors.shape, (16, 3))
            self.assertEqual(colors.dtype, np.uint8)
            self.assertFalse(np.array_equal(colors[0], colors[-1]))
        self.assertEqual(colormap.ramp_names(), list(colormap.RAMP_ORDER))
        self.assertEqual(colormap.valid_ramp('nope'), colormap.DEFAULT_RAMP)

    def test_unknown_ramp_falls_back_instead_of_raising(self):
        rgb = colormap.colorize(np.array([[0.0, 1.0]]), np.ones((1, 2), bool), 0.0, 1.0,
                                ramp='not-a-ramp')
        expected = colormap.colorize(np.array([[0.0, 1.0]]), np.ones((1, 2), bool), 0.0, 1.0)
        self.assertTrue(np.array_equal(rgb, expected))

    def test_legend_ticks_are_monotonic_and_bounded(self):
        ticks = colormap.legend_ticks(2.0, 62.0, 5)
        self.assertEqual(len(ticks), 5)
        self.assertAlmostEqual(ticks[0], 2.0)
        self.assertAlmostEqual(ticks[-1], 62.0)
        self.assertEqual(ticks, sorted(ticks))

    def test_number_formatting_is_compact_and_finite_aware(self):
        self.assertEqual(colormap.format_number(61.34999), '61.35')
        self.assertEqual(colormap.format_number(0.00042), '4.200e-04')
        self.assertEqual(colormap.format_number(float('nan')), '—')
        self.assertEqual(colormap.format_number('nonsense'), '—')
