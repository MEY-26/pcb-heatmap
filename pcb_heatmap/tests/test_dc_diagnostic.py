"""Thermal rejection preserves only independently valid reference-DC results."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import AnalysisError, ComponentHeat
import solver
from test_solver import strip, scenario


class DCDiagnosticTests(unittest.TestCase):
    def rejected(self, board, config):
        with self.assertRaises(AnalysisError) as caught:
            solver.analyze(board, config)
        return caught.exception

    def test_excessive_load_retains_cold_dc_maps_and_analytical_energy(self):
        board = strip(rows=4, columns=13)
        config = scenario(1040)
        before = copy.deepcopy(config)
        copper = board.copper.copy()
        error = self.rejected(board, config)
        self.assertEqual(error.code, 'electrothermal_outside_validity')
        diagnostic = error.diagnostic
        self.assertEqual(diagnostic['reference_temperature_c'], 25)
        self.assertNotIn('temperature_c', diagnostic)
        self.assertNotIn('max_temperature_c', diagnostic['summaries'])
        resistance = 1.724e-8 * 12 / (.00007 * 4)
        net = diagnostic['summaries']['nets']['N']
        self.assertAlmostEqual(net['max_delta_v'], 1040 * resistance, places=7)
        self.assertAlmostEqual(net['source_current_a'], 1040, places=6)
        self.assertAlmostEqual(diagnostic['summaries']['joule_w'], 1040 ** 2 * resistance, places=7)
        self.assertAlmostEqual(net['energy_error_w'], 0, places=6)
        self.assertEqual(config, before)
        np.testing.assert_array_equal(board.copper, copper)

    def test_feedback_rejection_keeps_first_not_hot_iteration(self):
        board = strip(rows=4, columns=13)
        config = scenario(50)
        config.settings.alpha = .00393
        config.settings.max_iterations = 20
        config.settings.tolerance_c = 1e-16
        config.settings.ambient_c = 40
        error = self.rejected(board, config)
        self.assertGreater(error.details['iteration'], 1)
        cold_resistance = 1.724e-8 * (1 + .00393 * 20) * 12 / (.00007 * 4)
        self.assertEqual(error.diagnostic['reference_temperature_c'], 40)
        self.assertAlmostEqual(error.diagnostic['summaries']['joule_w'], 50 ** 2 * cold_resistance, places=7)

    def test_signed_return_current_remains_signed(self):
        config = scenario(-1040)
        config.sources[0].voltage_v = 0
        diagnostic = self.rejected(strip(), config).diagnostic
        self.assertAlmostEqual(diagnostic['summaries']['nets']['N']['source_current_a'], -1040, places=6)
        self.assertGreater(diagnostic['summaries']['joule_w'], 0)
        self.assertGreater(np.nanmax(diagnostic['voltage_v']['N']), 0)

    def test_heater_only_failure_cannot_create_an_electrical_diagnostic(self):
        config = scenario()
        config.sources = []; config.loads = []
        config.heaters = [ComponentHeat(['D'], 100000)]
        self.assertIsNone(self.rejected(strip(), config).diagnostic)

    def test_cancel_and_electrical_failures_are_not_turned_into_partial_success(self):
        config = scenario()
        with self.assertRaises(AnalysisError) as caught:
            solver.analyze(strip(), config, cancel=lambda: True)
        self.assertIsNone(caught.exception.diagnostic)
        self.assertIsNone(caught.exception.code)
        config.loads[0].pad_ids = ['missing']
        with self.assertRaises(AnalysisError) as caught:
            solver.analyze(strip(), config)
        self.assertIsNone(caught.exception.diagnostic)

    def test_thermal_iterative_failure_preserves_dc_but_cancellation_does_not(self):
        board, config = strip(), scenario()
        original = solver._pcg
        calls = []

        def thermal_failure(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise AnalysisError('Conduction solver did not converge after 300 iterations (relative residual 0.1).')
            return original(*args, **kwargs)

        with patch.object(solver, '_pcg', side_effect=thermal_failure):
            error = self.rejected(board, config)
        self.assertEqual(error.code, 'electrothermal_nonconvergence')
        self.assertIsNotNone(error.diagnostic)
        self.assertIsNone(error.details['computed_peak_c'])
        self.assertNotIn('hotspot', error.details)
        calls.clear()

        def thermal_cancel(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise AnalysisError('Analysis cancelled.')
            return original(*args, **kwargs)

        with patch.object(solver, '_pcg', side_effect=thermal_cancel):
            error = self.rejected(board, config)
        self.assertIsNone(error.code)
        self.assertIsNone(error.diagnostic)


if __name__ == '__main__':
    unittest.main()
