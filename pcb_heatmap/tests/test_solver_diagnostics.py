"""Rejected electrothermal candidates remain invalid but explain their inputs."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import AnalysisError, Load
import solver
from test_solver import strip, scenario


class SolverDiagnosticsTests(unittest.TestCase):
    def test_excessive_group_loads_report_actual_totals_without_changing_them(self):
        board = strip()
        config = scenario()
        config.loads = [Load(['D'], 80) for _ in range(13)]
        before = copy.deepcopy(config)
        copper = board.copper.copy()
        with self.assertRaises(AnalysisError) as caught:
            solver.analyze(board, config)
        error = caught.exception
        self.assertEqual(error.code, 'electrothermal_outside_validity')
        self.assertEqual(error.details['total_draw_a'], 1040)
        self.assertEqual(error.details['total_injection_a'], 0)
        self.assertEqual(error.details['net_loads'], [dict(net='N', draw_a=1040,
                         injection_a=0, signed_a=1040, group_count=13)])
        self.assertGreater(error.details['computed_peak_c'], 1500)
        self.assertEqual(error.details['model_limit_c'], 1500)
        self.assertEqual(error.details['iteration'], 1)
        self.assertEqual(error.details['previous_iteration'], 0)
        self.assertEqual(error.details['previous_peak_c'], 25)
        hot = error.details['hotspot']
        self.assertTrue(0 <= hot['row'] < board.board_mask.shape[0])
        self.assertTrue(0 <= hot['column'] < board.board_mask.shape[1])
        self.assertEqual(config, before)
        np.testing.assert_array_equal(board.copper, copper)

    def test_return_current_is_injection_and_does_not_cancel_positive_totals(self):
        config = scenario(-1040)
        config.sources[0].voltage_v = 0
        with self.assertRaises(AnalysisError) as caught:
            solver.analyze(strip(), config)
        error = caught.exception
        self.assertEqual(error.code, 'electrothermal_outside_validity')
        self.assertEqual(error.details['total_draw_a'], 0)
        self.assertEqual(error.details['total_injection_a'], 1040)
        self.assertEqual(error.details['net_loads'][0]['signed_a'], -1040)

    def test_nonconvergence_reports_iteration_and_unconverged_candidate(self):
        config = scenario(10)
        config.settings.alpha = .00393
        config.settings.max_iterations = 1
        with self.assertRaisesRegex(AnalysisError, 'did not converge') as caught:
            solver.analyze(strip(), config)
        error = caught.exception
        self.assertEqual(error.code, 'electrothermal_nonconvergence')
        self.assertEqual(error.details['iteration'], 1)
        self.assertEqual(error.details['previous_peak_c'], 25)
        self.assertGreater(error.details['computed_peak_c'], 25)
        self.assertLess(error.details['computed_peak_c'], 1500)
        self.assertGreater(error.details['max_change_c'], config.settings.tolerance_c)

    def test_nonfinite_candidate_is_distinguished_and_never_given_a_peak(self):
        board = strip()
        config = scenario(1)
        pcg = solver._pcg
        calls = []

        def fail_only_thermal(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                return np.full(len(args[4]), np.nan), 1, np.nan
            return pcg(*args, **kwargs)

        with patch.object(solver, '_pcg', side_effect=fail_only_thermal), \
                patch.object(solver._RecycledGuesses, 'add') as recycle, \
                self.assertRaises(AnalysisError) as caught:
            solver.analyze(board, config)
        self.assertEqual(caught.exception.code, 'electrothermal_nonfinite')
        self.assertIsNone(caught.exception.details['computed_peak_c'])
        self.assertNotIn('hotspot', caught.exception.details)
        self.assertEqual(caught.exception.details['total_draw_a'], 1)
        recycle.assert_not_called()

    def test_ordinary_result_and_warning_marker_are_unchanged(self):
        config = scenario(1)
        config.settings.max_temperature_c = 25.0001
        result = solver.analyze(strip(), config)
        self.assertTrue(result.diagnostics['converged'])
        self.assertGreater(result.summaries['max_temperature_c'], config.settings.max_temperature_c)
        self.assertLess(result.summaries['max_temperature_c'], 1500)
        self.assertTrue(any('Peak temperature exceeds' in warning for warning in result.diagnostics['warnings']))
        self.assertAlmostEqual(result.summaries['nets']['N']['source_current_a'], 1, places=8)


if __name__ == '__main__':
    unittest.main()
