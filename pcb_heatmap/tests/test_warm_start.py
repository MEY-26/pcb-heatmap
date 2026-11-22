"""Warm solver state: identical results and no wasted work on a rerun."""
from __future__ import annotations

import numpy as np
import unittest

from pcb_heatmap.model import AnalysisSettings, Layer, Load, Pad, RasterBoard, Scenario, Source
from pcb_heatmap import solver


def board(columns=40):
    shape = (1, 5, columns)
    copper = np.zeros(shape, dtype=np.float32)
    copper[0, 2, 2:columns - 2] = 1.0
    pads = {'S': Pad('S', 'J1.1', 'N', 0.0, 0.0, (0,)),
            'L': Pad('L', 'J2.1', 'N', 0.0, 0.0, (0,))}
    return RasterBoard(0.0, 0.0, 0.5, np.ones((5, columns), bool), copper,
                       {'N': copper.copy()}, [Layer('F.Cu', 0.035, 0.0175)],
                       [], pads, {'S': [(0, 2, 2)], 'L': [(0, 2, columns - 3)]},
                       [], {'board_thickness_mm': 1.6})


def settings(**extra):
    base = dict(ambient_c=25.0, convection_top=10.0, convection_bottom=10.0,
                fr4_k=0.3, substrate_k_z=0.3, substrate_material='fr4')
    base.update(extra)
    return AnalysisSettings(**base)


class WarmStartTests(unittest.TestCase):
    def test_rerun_matches_and_carries_state(self):
        mesh = board()
        model = Scenario(sources=[Source(['S'], 5.0)], loads=[Load(['L'], 1.5, 'per_pad')],
                         settings=settings())
        warm = {}
        first = solver.analyze(mesh, model, warm=warm)
        self.assertIn('temperature', warm)
        self.assertIn('voltages', warm)
        self.assertIn('thermal', warm)
        self.assertIn('thermal_signature', warm)
        model.loads[0].current_a = 2.0
        second = solver.analyze(mesh, model, warm=warm)
        fresh = solver.analyze(mesh, model, warm={})
        # A warm start reaches the same converged answer within the solver's
        # own thermal tolerance, not bit-for-bit (the residual path differs).
        self.assertLess(abs(second.summaries['max_temperature_c']
                            - fresh.summaries['max_temperature_c']), 0.05)
        self.assertGreaterEqual(second.summaries['max_temperature_c'],
                                first.summaries['max_temperature_c'])

    def test_changed_physics_invalidates_the_cached_system(self):
        mesh = board()
        warm = {}
        first = solver.analyze(mesh, Scenario([Source(['S'], 5.0)],
                                             [Load(['L'], 1.0, 'per_pad')],
                                             settings=settings()), warm=warm)
        signature = warm['thermal_signature']
        warm['thermal'] = 'stale'
        second = solver.analyze(mesh, Scenario([Source(['S'], 5.0)],
                                              [Load(['L'], 1.0, 'per_pad')],
                                              settings=settings(ambient_c=40.0)), warm=warm)
        self.assertNotEqual(warm['thermal_signature'], signature)
        self.assertNotEqual(warm['thermal'], 'stale')
        self.assertGreater(second.summaries['max_temperature_c'],
                           first.summaries['max_temperature_c'])
