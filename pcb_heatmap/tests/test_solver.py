"""Analytical and physical regression checks, using only stdlib unittest/NumPy."""
from __future__ import annotations
import copy
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import (AnalysisError, AnalysisSettings, ComponentHeat, Layer, Load,
                   Pad, RasterBoard, Scenario, Source, Via)
from solver import analyze


def strip(layers=1, rows=3, columns=12, cell_mm=1.0):
    thickness = .07
    centers = np.linspace(.035, 1.565, layers) if layers > 1 else [.035]
    copper = np.ones((layers, rows, columns), dtype=float)
    board = RasterBoard(0, 0, cell_mm, np.ones((rows, columns), dtype=bool), copper,
                        {'N': copper.copy()}, [Layer(f'L{i+1}', thickness, float(z)) for i, z in enumerate(centers)],
                        [], {}, {}, metadata={'board_thickness_mm': 1.6})
    add_pad(board, 'S', 'N', [(l, r, 0) for l in range(layers) for r in range(rows)])
    add_pad(board, 'D', 'N', [(l, r, columns - 1) for l in range(layers) for r in range(rows)])
    return board


def add_pad(board, identifier, net, cells):
    l, r, c = cells[0]
    board.pads[identifier] = Pad(identifier, identifier, net, (c + .5) * board.cell_mm,
                                 (r + .5) * board.cell_mm, tuple(sorted({x[0] for x in cells})))
    board.pad_cells[identifier] = list(cells)


def scenario(current=1, **kwargs):
    settings = AnalysisSettings(alpha=0, convection_top=30, convection_bottom=30,
                                tolerance_c=1e-8, solver_tolerance=1e-10, **kwargs)
    return Scenario([Source(['S'], 33.6)], [Load(['D'], current)], settings=settings)


class SolverTests(unittest.TestCase):
    def test_uniform_resistor_and_density(self):
        board = strip(rows=4, columns=13)
        result = analyze(board, scenario(12))
        expected_r = 1.724e-8 * 12 / (.00007 * 4)
        net = result.summaries['nets']['N']
        self.assertAlmostEqual(net['max_delta_v'], 12 * expected_r, places=9)
        self.assertAlmostEqual(result.summaries['joule_w'], 12 ** 2 * expected_r, places=9)
        self.assertAlmostEqual(net['source_current_a'], 12, places=7)
        np.testing.assert_allclose(result.current_density_a_mm2['N'], 12 / (4 * .07), rtol=1e-7)

    def test_four_parallel_layers(self):
        a = analyze(strip(1), scenario(8))
        b = analyze(strip(4), scenario(8))
        self.assertAlmostEqual(b.summaries['joule_w'], a.summaries['joule_w'] / 4, places=8)
        self.assertAlmostEqual(b.summaries['nets']['N']['max_delta_v'], a.summaries['nets']['N']['max_delta_v'] / 4, places=9)
        self.assertAlmostEqual(b.summaries['nets']['N']['source_current_a'], 8, places=7)

    def test_load_group_total_not_per_pad(self):
        board = strip(rows=4)
        add_pad(board, 'D1', 'N', [(0, 0, 11), (0, 1, 11)])
        add_pad(board, 'D2', 'N', [(0, 2, 11), (0, 3, 11)])
        config = scenario(7)
        config.loads[0].pad_ids = ['D1', 'D2']
        result = analyze(board, config)
        self.assertAlmostEqual(result.summaries['nets']['N']['source_current_a'], 7, places=7)

    def test_signed_ground_return_current(self):
        config = scenario(-8)
        config.sources[0].voltage_v = 0
        result = analyze(strip(), config)
        self.assertGreater(result.summaries['nets']['N']['voltage_max_v'], 0)
        self.assertAlmostEqual(result.summaries['nets']['N']['source_current_a'], -8, places=7)
        self.assertGreater(result.summaries['joule_w'], 0)

    def test_electrical_energy_and_convection_balance(self):
        result = analyze(strip(), scenario(15))
        summary = result.summaries
        self.assertAlmostEqual(summary['joule_w'], float(result.joule_w.sum()), places=12)
        self.assertAlmostEqual(summary['convection_w'], summary['total_heat_w'], places=7)
        self.assertAlmostEqual(summary['nets']['N']['energy_error_w'], 0, places=7)

    def test_actual_via_span_and_wall_plating(self):
        board = strip(layers=3, rows=1, columns=1)
        board.copper[1] = 0
        board.net_copper['N'][1] = 0
        board.vias = [Via(.5, .5, .2, .45, 0, 2, 'N', 25, 'V1')]
        add_pad(board, 'S', 'N', [(0, 0, 0)])
        add_pad(board, 'D', 'N', [(2, 0, 0)])
        result = analyze(board, scenario(2))
        area_m2 = math.pi * ((.0002 + 2 * .000025) ** 2 - .0002 ** 2) / 4
        resistance = 1.724e-8 * .00153 / area_m2
        self.assertAlmostEqual(result.summaries['joule_w'], 4 * resistance, places=10)
        via = result.via_current_a[0]
        self.assertAlmostEqual(via['max_current_a'], 2, places=8)
        self.assertAlmostEqual(via['loss_w'], 4 * resistance, places=10)
        self.assertEqual(via['segments'][0]['to_layer'], 2)
        # Halving the actual span halves the barrel resistance.
        board.layers[1].z_mm = .4
        board.layers[2].z_mm = .8
        result2 = analyze(board, scenario(2))
        self.assertAlmostEqual(result2.summaries['joule_w'] / result.summaries['joule_w'], (.8 - .035) / 1.53, places=8)

    def test_via_annulus_contacts_without_fake_center_copper(self):
        board = strip(layers=2, rows=1, columns=3)
        board.copper[:, :, 1] = 0
        board.net_copper['N'][:, :, 1] = 0
        board.vias = [Via(1.5, .5, .2, .45, 0, 1, 'N', 25, 'V')]
        board.metadata['via_cells'] = [{0: [(0, 0), (0, 2)], 1: [(0, 0), (0, 2)]}]
        add_pad(board, 'S', 'N', [(0, 0, 0), (0, 0, 2)])
        add_pad(board, 'D', 'N', [(1, 0, 0), (1, 0, 2)])
        result = analyze(board, scenario(3))
        self.assertAlmostEqual(result.via_current_a[0]['max_current_a'], 3, places=7)
        self.assertEqual(result.via_current_a[0]['segments'][0]['from_layer'], 0)

    def test_other_net_receives_heat_without_electrical_short(self):
        board = strip(rows=5, columns=8)
        a = np.zeros_like(board.copper); a[:, 0, :] = 1
        b = np.zeros_like(board.copper); b[:, 4, :] = 1
        board.net_copper = {'A': a, 'B': b}
        board.copper = a + b
        add_pad(board, 'S', 'A', [(0, 0, 0)])
        add_pad(board, 'D', 'A', [(0, 0, 7)])
        result = analyze(board, scenario(20))
        self.assertGreater(result.temperature_c[0, 4, 4], 25)
        self.assertEqual(set(result.voltage_v), {'A'})
        self.assertTrue(np.isnan(result.voltage_v['A'][0, 4, 4]))

    def test_disconnected_sink_is_rejected(self):
        board = strip(rows=1, columns=6)
        board.copper[:, :, 2:4] = 0
        board.net_copper['N'][:, :, 2:4] = 0
        with self.assertRaisesRegex(AnalysisError, 'no physical connection'):
            analyze(board, scenario())

    def test_unpowered_island_is_not_singular(self):
        board = strip(rows=1, columns=6)
        board.copper[:, :, 2:4] = 0
        board.net_copper['N'][:, :, 2:4] = 0
        add_pad(board, 'D', 'N', [(0, 0, 1)])
        result = analyze(board, scenario())
        self.assertTrue(np.isnan(result.voltage_v['N'][0, 0, 4]))
        self.assertTrue(np.isfinite(result.temperature_c[0, 0, 4]))
        self.assertEqual(result.summaries['nets']['N']['floating_copper_cells'], 2)

    def test_exact_zero_face_prevents_raster_clearance_bridge(self):
        board = strip(rows=1, columns=6)
        faces = np.ones((1, 1, 5)); faces[0, 0, 2] = 0
        board.metadata['net_edges'] = {'N': {'x': faces, 'y': np.ones((1, 0, 6))}}
        with self.assertRaisesRegex(AnalysisError, 'no physical connection'):
            analyze(board, scenario())

    def test_source_load_overlap_and_conflicting_sources_rejected(self):
        board = strip()
        bad = scenario()
        bad.loads[0].pad_ids = ['S']
        with self.assertRaisesRegex(AnalysisError, 'overlap'):
            analyze(board, bad)
        bad = scenario()
        bad.sources.append(Source(['S'], 12))
        with self.assertRaisesRegex(AnalysisError, 'incompatible voltages'):
            analyze(board, bad)

    def test_no_source_and_invalid_boundary(self):
        bad = scenario()
        bad.sources = []
        with self.assertRaisesRegex(AnalysisError, 'require at least one source'):
            analyze(strip(), bad)
        bad = scenario()
        bad.settings.convection_top = bad.settings.convection_bottom = 0
        with self.assertRaisesRegex(AnalysisError, 'convection'):
            analyze(strip(), bad)

    def test_manual_heater_energy(self):
        board = strip()
        config = Scenario([], [], [ComponentHeat(['S', 'D'], .8)], scenario().settings)
        result = analyze(board, config)
        self.assertAlmostEqual(result.summaries['component_heat_w'], .8)
        self.assertAlmostEqual(result.summaries['convection_w'], .8, places=7)

    def test_positive_temperature_feedback_and_explicit_nonconvergence(self):
        board = strip()
        fixed = analyze(board, scenario(10))
        config = scenario(10)
        config.settings.alpha = .00393
        config.settings.max_iterations = 60
        result = analyze(board, config)
        self.assertGreater(result.summaries['max_temperature_c'], fixed.summaries['max_temperature_c'])
        self.assertGreater(result.summaries['joule_w'], fixed.summaries['joule_w'])
        config.settings.max_iterations = 1
        with self.assertRaisesRegex(AnalysisError, 'did not converge'):
            analyze(board, config)

    def test_does_not_mutate_input(self):
        board = strip(2)
        config = scenario(7)
        snapshot = copy.deepcopy(board)
        old_settings = copy.deepcopy(vars(config.settings))
        analyze(board, config)
        np.testing.assert_array_equal(board.copper, snapshot.copper)
        np.testing.assert_array_equal(board.net_copper['N'], snapshot.net_copper['N'])
        self.assertEqual(board.pad_cells, snapshot.pad_cells)
        self.assertEqual(board.layers, snapshot.layers)
        self.assertEqual(vars(config.settings), old_settings)

    def test_cancellation_is_explicit(self):
        with self.assertRaisesRegex(AnalysisError, 'cancelled'):
            analyze(strip(), scenario(), cancel=lambda: True)


if __name__ == '__main__':
    unittest.main()
