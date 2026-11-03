"""Visual contact validation and solver regressions without native PCB writes."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contacts import attach_contacts, validate_contacts
from model import (AnalysisError, AnalysisSettings, ComponentHeat, Layer, Load,
                   Pad, RasterBoard, Scenario, Source)
from solver import analyze


def mesh(layers=2, columns=13):
    copper = np.ones((layers, 1, columns))
    return RasterBoard(10, 20, 1.0, np.ones((1, columns), dtype=bool), copper,
                       {'N': copper.copy()},
                       [Layer(f'L{i}', .07, .035 + .4 * i) for i in range(layers)],
                       [], {}, {}, metadata={'board_thickness_mm': 1.6})


def point(identifier='point:source', net='N', layer=0, x_mm=10.5, y_mm=20.5):
    return dict(identifier=identifier, net=net, layer=layer, x_mm=x_mm, y_mm=y_mm)


def info(board):
    return dict(layers=board.layers, pads=board.pads, nets=list(board.net_copper))


class ContactTests(unittest.TestCase):
    def test_validate_normalizes_without_mutating_caller_records(self):
        board = mesh()
        records = [point(x_mm=11)]
        before = copy.deepcopy(records)
        result = validate_contacts(records, info(board))
        self.assertEqual(records, before)
        self.assertIsNot(result['point:source'], records[0])
        self.assertIsInstance(result['point:source']['x_mm'], float)
        result['point:source']['net'] = 'changed'
        self.assertEqual(records[0]['net'], 'N')

    def test_pad_net_fallback_and_native_pad_identity_preserved(self):
        board = mesh()
        native = Pad('native-uuid', 'J1.1', 'N', 10.5, 20.5, (0,))
        board.pads[native.identifier] = native
        board.pad_cells[native.identifier] = [(0, 0, 0)]
        records = [point()]
        validated = validate_contacts(records, {'layers': board.layers, 'pads': [vars(native)]})
        before_copper = board.copper.copy()
        before_net = board.net_copper['N'].copy()
        attached = attach_contacts(board, validated)
        self.assertIs(board.pads[native.identifier], native)
        self.assertEqual(vars(native), dict(identifier='native-uuid', label='J1.1', net='N',
                                           x_mm=10.5, y_mm=20.5, layers=(0,)))
        self.assertEqual(board.pad_cells[native.identifier], [(0, 0, 0)])
        np.testing.assert_array_equal(board.copper, before_copper)
        np.testing.assert_array_equal(board.net_copper['N'], before_net)
        self.assertEqual(attached, validated)
        self.assertEqual(board.pad_cells['point:source'], [(0, 0, 0)])
        self.assertIn('X 10.500 mm, Y 20.500 mm', board.pads['point:source'].label)
        self.assertTrue(any('ideal terminals' in warning for warning in board.warnings))

    def test_invalid_ids_nets_layers_and_coordinates_rejected(self):
        board = mesh()
        invalid = [point(identifier='native'), point(identifier='point:'), point(net='MISSING'),
                   point(net=None), point(layer=-1), point(layer=2), point(layer=True),
                   point(layer=0.0), point(x_mm=float('nan')), point(y_mm=float('inf')),
                   point(x_mm='10.5'), point(y_mm=True)]
        for record in invalid:
            with self.subTest(record=record), self.assertRaises(AnalysisError):
                validate_contacts([record], info(board))
        with self.assertRaisesRegex(AnalysisError, 'Duplicate'):
            validate_contacts([point(), point()], info(board))
        board.pads['point:source'] = Pad('point:source', 'existing', 'N', 10.5, 20.5, (0,))
        with self.assertRaisesRegex(AnalysisError, 'Duplicate'):
            validate_contacts([point()], info(board))

    def test_outside_board_and_cutout_rejected_without_partial_attachment(self):
        board = mesh()
        board.board_mask[0, 5] = False
        for x, y in [(9.9, 20.5), (23, 20.5), (10.5, 21), (15.5, 20.5)]:
            records = [point(), point(identifier='point:bad', x_mm=x, y_mm=y)]
            with self.subTest(x=x, y=y), self.assertRaisesRegex(AnalysisError, 'outside'):
                attach_contacts(board, records)
            self.assertEqual(board.pads, {})
            self.assertEqual(board.pad_cells, {})
            self.assertEqual(board.warnings, [])

    def test_clearance_and_cross_layer_contact_never_snap(self):
        board = mesh()
        board.net_copper['N'][0, 0, 0] = 0
        # The same cell has copper on layer 1; this must not rescue layer 0.
        self.assertGreater(board.net_copper['N'][1, 0, 0], 0)
        with self.assertRaisesRegex(AnalysisError, 'no resolved copper.*Refine the grid'):
            attach_contacts(board, [point()])
        self.assertEqual(board.pads, {})
        attach_contacts(board, [point(layer=1)])
        self.assertEqual(board.pad_cells['point:source'], [(1, 0, 0)])

    def test_point_terminals_analytic_strip_and_total_current(self):
        board = mesh(layers=1)
        records = [point(), point(identifier='point:load', x_mm=22.5)]
        before = copy.deepcopy(records)
        attach_contacts(board, records)
        settings = AnalysisSettings(alpha=0, convection_top=50, convection_bottom=50,
                                    solver_tolerance=1e-10, tolerance_c=1e-8)
        config = Scenario([Source(['point:source'], 33.6)],
                          [Load(['point:load'], 2.0)], settings=settings)
        result = analyze(board, config)
        expected_resistance = 1.724e-8 * .012 / (.001 * .00007)
        self.assertAlmostEqual(result.summaries['nets']['N']['source_current_a'], 2, places=8)
        self.assertAlmostEqual(result.summaries['nets']['N']['max_delta_v'],
                               2 * expected_resistance, places=9)
        self.assertAlmostEqual(result.summaries['joule_w'], 4 * expected_resistance, places=9)
        self.assertEqual(records, before)

    def test_points_on_separate_layers_do_not_create_vias(self):
        board = mesh()
        attach_contacts(board, [point(), point(identifier='point:load', layer=1, x_mm=22.5)])
        config = Scenario([Source(['point:source'], 33.6)], [Load(['point:load'], 2)])
        with self.assertRaisesRegex(AnalysisError, 'no physical connection'):
            analyze(board, config)

    def test_empty_net_heat_point_on_fr4_solves_and_conserves_power(self):
        board = mesh()
        board.copper[:] = 0
        board.net_copper['N'][:] = 0
        attach_contacts(board, [point(identifier='point:heat', net='', layer=1)])
        self.assertEqual(board.pads['point:heat'].net, '')
        self.assertEqual(board.pad_cells['point:heat'], [(1, 0, 0)])
        settings = AnalysisSettings(alpha=0, convection_top=50, convection_bottom=50,
                                    solver_tolerance=1e-10, tolerance_c=1e-8)
        result = analyze(board, Scenario([], [], [ComponentHeat(['point:heat'], .01)], settings))
        self.assertAlmostEqual(result.summaries['component_heat_w'], .01)
        self.assertAlmostEqual(result.summaries['convection_w'], .01, places=8)
        self.assertGreater(result.summaries['max_temperature_c'], 25)
        self.assertEqual(result.voltage_v, {})


if __name__ == '__main__':
    unittest.main()
