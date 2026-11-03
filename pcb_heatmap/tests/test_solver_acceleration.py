"""Fine-grid accuracy, isolation and cancellation checks for solver acceleration."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import (AnalysisError, AnalysisSettings, ComponentHeat, Layer, Load,
                   Pad, RasterBoard, Scenario, Source, Via)
import solver


def separated_board():
    """Two outlined islands, a through-cutout and multilayer via-fed copper."""
    mask = np.ones((24, 40), dtype=bool)
    mask[:, 19:21] = False
    mask[9:12, 8:11] = False
    copper = np.broadcast_to(mask, (4, *mask.shape)).astype(float).copy()
    board = RasterBoard(0, 0, .5, mask, copper, {'N': copper.copy()},
                        [Layer(str(i), .07, float(z)) for i, z in enumerate(np.linspace(.035, 1.565, 4))],
                        [], {}, {}, metadata={'board_thickness_mm': 1.6})
    for row in range(2, 24, 5):
        for col in range(2, 19, 5):
            if mask[row, col]:
                board.vias.append(Via((col + .5) * .5, (row + .5) * .5,
                                       .2, .45, 0, 3, 'N', 25., f'V{row}_{col}'))
    groups = {'S': [(0, row, 1) for row in range(24)],
              'D': [(3, row, 17) for row in range(24)],
              'H': [(0, 12, 30)]}
    for name, cells in groups.items():
        layer, row, col = cells[0]
        board.pads[name] = Pad(name, name, 'N', (col + .5) * .5, (row + .5) * .5,
                               tuple(sorted({cell[0] for cell in cells})))
        board.pad_cells[name] = cells
    settings = AnalysisSettings(tolerance_c=1e-6, solver_tolerance=1e-10,
                                convection_top=30, convection_bottom=20)
    return board, Scenario([Source(['S'], 33.6)], [Load(['D'], 2)],
                           [ComponentHeat(['H'], .2)], settings)


class SolverAccelerationTests(unittest.TestCase):
    def test_recycled_projection_preserves_new_rhs_and_does_not_mutate_solutions(self):
        matrix = np.array([[3., -1., 0.], [-1., 4., -1.], [0., -1., 2.]])
        first_rhs, second_rhs = np.array([1., 0., 0.]), np.array([0., 1., .2])
        first = np.linalg.solve(matrix, first_rhs)
        second = np.linalg.solve(matrix, second_rhs)
        old_first, old_second = first.copy(), second.copy()
        recycle = solver._RecycledGuesses(3)
        recycle.add(first, lambda x: matrix @ x)
        recycle.add(second, lambda x: matrix @ x)
        rhs = 2.3 * first_rhs - .4 * second_rhs
        guess = recycle.guess(rhs, np.zeros(3))
        np.testing.assert_allclose(matrix @ guess, rhs, atol=1e-14)
        np.testing.assert_array_equal(first, old_first)
        np.testing.assert_array_equal(second, old_second)

    def test_batched_via_products_equal_explicit_edges_with_unequal_resistivity(self):
        rng = np.random.default_rng(42)
        n = 12
        left, right, g = [0, 1, 4], [1, 2, 7], [1., 2., 3.]
        blocks = [(np.array([0, 2, 3]), np.array([6, 8]), rng.uniform(.1, 2., (3, 2))),
                  (np.array([1, 3]), np.array([7, 9, 10]), .7),
                  (np.array([4, 5, 2]), np.array([9, 11]), rng.uniform(.2, 1., (3, 2)))]
        all_left, all_right, all_g = list(left), list(right), list(g)
        for a, b, conductance in blocks:
            full = np.broadcast_to(conductance, (len(a), len(b)))
            all_left.extend(np.repeat(a, len(b)))
            all_right.extend(np.tile(b, len(a)))
            all_g.extend(full.ravel())
        all_left, all_right, all_g = np.array(all_left), np.array(all_right), np.array(all_g)
        diagonal = .01 + np.bincount(all_left, weights=all_g, minlength=n)
        diagonal += np.bincount(all_right, weights=all_g, minlength=n)
        multiply = solver._BlockMultiply(diagonal, np.array(left), np.array(right), np.array(g), blocks)
        for _ in range(4):
            x = rng.normal(size=n)
            explicit = diagonal * x - np.bincount(all_left, weights=all_g * x[all_right], minlength=n)
            explicit -= np.bincount(all_right, weights=all_g * x[all_left], minlength=n)
            np.testing.assert_allclose(multiply(x), explicit, rtol=2e-14, atol=2e-14)

    def test_multilevel_matches_fine_grid_jacobi_on_cutouts_islands_and_vias(self):
        board, scenario = separated_board()
        accelerated = solver.analyze(board, scenario)
        self.assertEqual(accelerated.diagnostics['preconditioner'], 'multilevel')
        with patch.object(solver, '_preconditioner', return_value=None):
            reference = solver.analyze(board, scenario)
        np.testing.assert_allclose(accelerated.temperature_c, reference.temperature_c,
                                   rtol=2e-9, atol=1e-6, equal_nan=True)
        np.testing.assert_allclose(accelerated.voltage_v['N'], reference.voltage_v['N'],
                                   rtol=1e-11, atol=1e-9, equal_nan=True)
        np.testing.assert_allclose(accelerated.current_density_a_mm2['N'],
                                   reference.current_density_a_mm2['N'],
                                   rtol=1e-6, atol=1e-7, equal_nan=True)
        self.assertAlmostEqual(accelerated.summaries['total_heat_w'],
                               reference.summaries['total_heat_w'], places=8)
        self.assertAlmostEqual(accelerated.summaries['convection_w'],
                               accelerated.summaries['total_heat_w'], places=7)
        self.assertTrue(np.isnan(accelerated.voltage_v['N'][:, :, 25:]).all())
        self.assertTrue(np.isnan(accelerated.temperature_c[:, :, 19:21]).all())
        self.assertGreater(accelerated.temperature_c[0, 12, 30], 25.)
        # Acceleration must reduce actual iterations, not relax the tolerance.
        self.assertLess(accelerated.diagnostics['iterations'][0]['thermal_pcg_iterations'],
                        reference.diagnostics['iterations'][0]['thermal_pcg_iterations'])
        self.assertLess(accelerated.diagnostics['iterations'][-1]['thermal_relative_residual'], 5e-10)

    def test_components_exact_on_random_sparse_graph_and_isolated_nodes(self):
        rng = np.random.default_rng(12345)
        n = 400
        # Keep the two halves disconnected, with isolated nodes at their ends.
        left = np.r_[rng.integers(0, 180, 500), rng.integers(200, 380, 500)]
        right = np.r_[rng.integers(0, 180, 500), rng.integers(200, 380, 500)]
        labels = solver._components(n, left, right)
        adjacency = [set() for _ in range(n)]
        for a, b in zip(left, right):
            adjacency[a].add(int(b)); adjacency[b].add(int(a))
        expected = np.full(n, -1)
        for start in range(n):
            if expected[start] >= 0:
                continue
            stack = [start]
            expected[start] = start
            while stack:
                for neighbor in adjacency[stack.pop()]:
                    if expected[neighbor] < 0:
                        expected[neighbor] = start
                        stack.append(neighbor)
        np.testing.assert_array_equal(labels[:, None] == labels,
                                      expected[:, None] == expected)

    def test_graph_preparation_cancellation(self):
        with self.assertRaisesRegex(AnalysisError, 'cancelled'):
            solver._components(3, np.array([0, 1]), np.array([1, 2]), lambda: True)
        with self.assertRaisesRegex(AnalysisError, 'cancelled'):
            solver._preconditioner(np.ones(1024), np.array([], dtype=int),
                                   np.array([], dtype=int), np.array([]),
                                   np.arange(1024), (1, 32, 32), lambda: True)


if __name__ == '__main__':
    unittest.main()
