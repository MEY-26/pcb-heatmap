"""Vectorised polygon rasterisation against a brute-force reference."""
from __future__ import annotations

import numpy as np
import unittest

from pcb_heatmap.geometry import SAMPLES, sample_polygons
from pcb_heatmap.model import AnalysisError


def inside(polygons, x, y):
    """Even-odd point-in-polygon over all islands."""
    for contours in polygons:
        count = 0
        for contour in contours:
            for index in range(len(contour)):
                ax, ay = contour[index - 1][:2]
                bx, by = contour[index][:2]
                if (ay > y) != (by > y):
                    if x < (bx - ax) * (y - ay) / (by - ay) + ax:
                        count += 1
        if count % 2:
            return True
    return False


def brute(polygons, origin, cell, h, w, axis='area'):
    s = SAMPLES
    if axis == 'area':
        out = np.zeros((h, w), dtype=float)
        for row in range(h):
            for column in range(w):
                hits = 0
                for sy in range(s):
                    for sx in range(s):
                        x = origin[0] + column * cell + (sx + .5) * cell / s
                        y = origin[1] + row * cell + (sy + .5) * cell / s
                        hits += inside(polygons, x, y)
                out[row, column] = hits / (s * s)
        return out
    out = np.zeros((h, w - 1), dtype=float)
    for row in range(h):
        for column in range(w - 1):
            hits = 0
            for sy in range(s):
                x = origin[0] + (column + 1) * cell
                y = origin[1] + row * cell + (sy + .5) * cell / s
                hits += inside(polygons, x, y)
            out[row, column] = hits / s
    return out


class GeometryTests(unittest.TestCase):
    def square(self, x0, y0, x1, y1):
        return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float)

    def test_area_coverage_matches_brute_force(self):
        polygons = [[self.square(.1, .1, .9, .7)]]
        got = sample_polygons(polygons, (0., 0.), 1., 3, 3)
        expected = brute(polygons, (0., 0.), 1., 3, 3)
        np.testing.assert_allclose(got, expected.astype(np.float32), atol=1e-6)

    def test_hole_is_subtracted(self):
        outer = self.square(.1, .1, .9, .9)
        hole = self.square(.3, .3, .7, .7)[::-1]
        polygons = [[outer, hole]]
        got = sample_polygons(polygons, (0., 0.), 1., 2, 2)
        expected = brute(polygons, (0., 0.), 1., 2, 2)
        np.testing.assert_allclose(got, expected.astype(np.float32), atol=1e-6)
        self.assertLess(got.mean(), sample_polygons([[outer]], (0., 0.), 1., 2, 2).mean())

    def test_face_coverage_and_transpose(self):
        polygons = [[self.square(.1, .1, .9, .9)]]
        got = sample_polygons(polygons, (0., 0.), 1., 2, 3, axis='x')
        expected = brute(polygons, (0., 0.), 1., 2, 3, axis='x')
        np.testing.assert_allclose(got, expected.astype(np.float32), atol=1e-6)
        transposed = sample_polygons(polygons, (0., 0.), 1., 3, 2, axis='y')
        np.testing.assert_allclose(transposed, got.T, atol=1e-6)

    def test_disconnected_islands_in_one_cell_are_refused(self):
        first = self.square(0., 0., .4, 1.)
        second = self.square(.6, 0., 1., 1.)
        with self.assertRaisesRegex(AnalysisError, 'disconnected'):
            sample_polygons([[first], [second]], (0., 0.), 1., 1, 1, collision_check=True)

    def test_degenerate_polygons_are_ignored(self):
        got = sample_polygons([[[0., 0.], [1., 0.]]], (0., 0.), 1., 2, 2)
        self.assertTrue(np.array_equal(got, np.zeros((2, 2), dtype=np.float32)))
