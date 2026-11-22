"""Copper foil override: resolution, validation and its physical effect."""
from __future__ import annotations

import numpy as np
import unittest

from pcb_heatmap.model import (AnalysisError, AnalysisSettings, Layer, Load, Pad,
                               RasterBoard, Scenario, Source)
from pcb_heatmap import solver


def track_board(columns=24):
    shape = (1, 5, columns)
    copper = np.zeros(shape, dtype=np.float32)
    copper[0, 2, 2:columns - 2] = 1.0
    pads = {'S': Pad('S', 'J1.1', 'N', 0.0, 0.0, (0,)),
            'L': Pad('L', 'J2.1', 'N', 0.0, 0.0, (0,))}
    return RasterBoard(origin_x_mm=0.0, origin_y_mm=0.0, cell_mm=1.0,
                       board_mask=np.ones((5, columns), bool), copper=copper,
                       net_copper={'N': copper.copy()},
                       layers=[Layer('F.Cu', 0.035, 0.0175)],
                       vias=[], pads=pads,
                       pad_cells={'S': [(0, 2, 2)], 'L': [(0, 2, columns - 3)]},
                       warnings=[], metadata={'board_thickness_mm': 1.6})


def settings(**extra):
    base = dict(ambient_c=25.0, convection_top=10.0, convection_bottom=10.0,
                fr4_k=0.3, substrate_k_z=0.3, substrate_material='fr4')
    base.update(extra)
    return AnalysisSettings(**base)


class CopperThicknessTests(unittest.TestCase):
    def test_default_uses_the_stackup(self):
        board = track_board()
        thickness = solver._copper_thickness(board, settings())
        self.assertAlmostEqual(float(thickness[0]), 0.035e-3)

    def test_single_value_applies_to_every_layer(self):
        board = track_board()
        board.layers.append(Layer('B.Cu', 0.035, 1.5))
        board.copper = np.concatenate([board.copper, board.copper])
        board.net_copper = {'N': board.copper.copy()}
        thickness = solver._copper_thickness(board, settings(copper_um=[70.0]))
        self.assertEqual(len(thickness), 2)
        self.assertAlmostEqual(float(thickness[1]), 70e-6)

    def test_per_layer_values_are_honoured(self):
        board = track_board()
        thickness = solver._copper_thickness(board, settings(copper_um=[105.0]))
        self.assertAlmostEqual(float(thickness[0]), 105e-6)

    def test_wrong_count_and_out_of_range_are_rejected(self):
        board = track_board()
        with self.assertRaisesRegex(AnalysisError, 'one value per copper layer'):
            solver._copper_thickness(board, settings(copper_um=[35.0, 35.0]))
        for value in (0.0, 501.0, float('nan')):
            with self.subTest(value=value), self.assertRaisesRegex(AnalysisError, '1 and 500'):
                solver._copper_thickness(board, settings(copper_um=[value]))

    def test_thicker_copper_reduces_copper_loss(self):
        board = track_board()
        model = Scenario(sources=[Source(['S'], 5.0)], loads=[Load(['L'], 1.0, 'per_pad')],
                         settings=settings())
        thin = solver.analyze(board, model)
        model.settings = settings(copper_um=[100.0])
        thick = solver.analyze(board, model)
        self.assertLess(thick.summaries['joule_w'], thin.summaries['joule_w'] * 0.6)
        self.assertAlmostEqual(thick.summaries['nets']['N']['load_current_a'], 1.0)
