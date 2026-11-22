"""Grouped-terminal current split: per-pad and per-cell rules, conservation."""
from __future__ import annotations

import numpy as np
import unittest

from pcb_heatmap.model import (AnalysisError, Layer, Load, Pad, RasterBoard, Scenario,
                               Source, Via, split_preview)
from pcb_heatmap import solver


def board(rows=5, columns=20, pads=None, vias=()):
    shape = (1, rows, columns)
    copper = np.zeros(shape)
    copper[0, 2, :] = 1.0
    net = {'N': copper.copy()}
    pad_records, pad_cells = {}, {}
    for identifier, (label, positions) in (pads or {}).items():
        pad_records[identifier] = Pad(identifier=identifier, label=label, net='N',
                                      x_mm=0.0, y_mm=0.0, layers=(0,))
        pad_cells[identifier] = list(positions)
    return RasterBoard(origin_x_mm=0.0, origin_y_mm=0.0, cell_mm=1.0,
                       board_mask=np.ones((rows, columns), bool), copper=copper,
                       net_copper=net,
                       layers=[Layer('F.Cu', 0.035, 0.0175)],
                       vias=list(vias), pads=pad_records, pad_cells=pad_cells,
                       warnings=[], metadata={})


class SplitTests(unittest.TestCase):
    def electrical(self, load_pads, distribution, current=3.0):
        pad_cells = {'S': [(0, 2, 0)]}
        for index, positions in enumerate(load_pads):
            pad_cells[f'P{index}'] = list(positions)
        raster = board(pads={key: (key + '.1', value) for key, value in pad_cells.items()})
        load = Load(pad_ids=[f'P{index}' for index in range(len(load_pads))],
                    current_a=current, distribution=distribution)
        return solver._make_electrical(raster, Scenario(sources=[Source(['S'], 5.0)], loads=[load]),
                                       'N', np.array([0.0175]), None), raster

    def test_equal_per_pad_gives_every_pad_the_same_total(self):
        graph, raster = self.electrical([[(0, 2, 10)], [(0, 2, 16), (0, 2, 17)]], 'per_pad')
        weights = {cell: graph.sinks[node] for cell, node in
                   [((0, 2, 10), graph.index[(0, 2, 10)]),
                    ((0, 2, 16), graph.index[(0, 2, 16)]),
                    ((0, 2, 17), graph.index[(0, 2, 17)])]}
        self.assertAlmostEqual(weights[(0, 2, 10)], 1.5)
        self.assertAlmostEqual(weights[(0, 2, 16)], 0.75)
        self.assertAlmostEqual(weights[(0, 2, 17)], 0.75)
        self.assertAlmostEqual(float(graph.sinks.sum()), 3.0, places=12)
        split = graph.load_splits[0]
        self.assertEqual(split['distribution'], 'per_pad')
        self.assertAlmostEqual(split['pads'][0]['current_a'], 1.5)
        self.assertAlmostEqual(split['pads'][1]['current_a'], 1.5)
        self.assertAlmostEqual(sum(pad['current_a'] for pad in split['pads']), 3.0, places=12)

    def test_area_rule_keeps_the_release_0_3_4_behaviour(self):
        graph, _ = self.electrical([[(0, 2, 10)], [(0, 2, 16), (0, 2, 17)]], 'area')
        self.assertAlmostEqual(graph.sinks[graph.index[(0, 2, 10)]], 1.0)
        self.assertAlmostEqual(graph.sinks[graph.index[(0, 2, 16)]], 1.0)
        self.assertAlmostEqual(graph.sinks[graph.index[(0, 2, 17)]], 1.0)
        split = graph.load_splits[0]
        self.assertAlmostEqual(split['pads'][0]['current_a'], 1.0)
        self.assertAlmostEqual(split['pads'][1]['current_a'], 2.0)
        self.assertEqual(split['pads'][0]['cells'], 1)
        self.assertEqual(split['pads'][1]['cells'], 2)

    def test_default_distribution_is_the_legacy_area_rule(self):
        pad_cells = {'S': [(0, 2, 0)], 'P': [(0, 2, 10), (0, 2, 11)]}
        raster = board(pads={key: (key + '.1', value) for key, value in pad_cells.items()})
        load = Load(pad_ids=['P'], current_a=2.0)
        self.assertEqual(load.distribution, 'area')
        graph = solver._make_electrical(raster, Scenario(sources=[Source(['S'], 5.0)], loads=[load]),
                                        'N', np.array([0.0175]), None)
        self.assertAlmostEqual(graph.sinks[graph.index[(0, 2, 10)]], 1.0)
        self.assertAlmostEqual(float(graph.sinks.sum()), 2.0, places=12)

    def test_pads_sharing_a_cell_keep_the_group_total(self):
        graph, _ = self.electrical([[(0, 2, 10)], [(0, 2, 10), (0, 2, 11)]], 'per_pad')
        self.assertAlmostEqual(float(graph.sinks.sum()), 3.0, places=12)
        split = graph.load_splits[0]
        self.assertEqual(split['shared_cells'], 1)
        self.assertAlmostEqual(split['pads'][0]['current_a'], 1.125)
        self.assertAlmostEqual(split['pads'][1]['current_a'], 1.875)
        self.assertAlmostEqual(sum(pad['current_a'] for pad in split['pads']), 3.0, places=12)

    def test_negative_current_is_divided_without_changing_sign(self):
        graph, _ = self.electrical([[(0, 2, 10)], [(0, 2, 16)]], 'per_pad', current=-4.0)
        self.assertAlmostEqual(float(graph.sinks.sum()), -4.0, places=12)
        self.assertAlmostEqual(graph.load_splits[0]['pads'][0]['current_a'], -2.0)

    def test_unknown_rule_is_rejected_before_the_solve(self):
        pad_cells = {'S': [(0, 2, 0)], 'P': [(0, 2, 10)]}
        raster = board(pads={key: (key + '.1', value) for key, value in pad_cells.items()})
        load = Load(pad_ids=['P'], current_a=1.0, distribution='equalish')
        with self.assertRaisesRegex(AnalysisError, 'Unknown load distribution'):
            solver._make_electrical(raster, Scenario(sources=[Source(['S'], 1.0)], loads=[load]),
                                    'N', np.array([0.0175]), None)


class GeometrySummaryTests(unittest.TestCase):
    def test_copper_area_and_via_statistics_are_attached_per_net(self):
        via = Via(x_mm=5.0, y_mm=2.0, drill_mm=0.3, diameter_mm=0.6,
                  start_layer=0, end_layer=0, net='N', plating_um=25.0, identifier='V1')
        raster = board(vias=[via])
        summaries = {'N': {}}
        solver._attach_geometry_summaries(raster, summaries,
                                          [dict(via_index=0, current_a=1.0, loss_w=0.002),
                                           dict(via_index=0, current_a=0.5, loss_w=0.001)])
        summary = summaries['N']
        self.assertAlmostEqual(summary['copper_area_mm2'], 20.0)
        self.assertEqual(summary['copper_area_by_layer_mm2'], [20.0])
        self.assertEqual(summary['via_count'], 1)
        self.assertAlmostEqual(summary['via_loss_w'], 0.003)
        self.assertAlmostEqual(summary['max_via_current_a'], 1.0)
        self.assertAlmostEqual(summary['max_via_density_a_mm2'],
                               1.0 / (solver._via_area(via) * 1e6))

    def test_vias_and_area_from_other_nets_are_excluded(self):
        other = Via(x_mm=0.0, y_mm=0.0, drill_mm=0.3, diameter_mm=0.6,
                    start_layer=0, end_layer=0, net='OTHER', plating_um=25.0, identifier='V2')
        raster = board(vias=[other])
        summaries = {'N': {}, 'OTHER': {}}
        solver._attach_geometry_summaries(raster, summaries,
                                          [dict(via_index=0, current_a=2.0, loss_w=0.01)])
        self.assertEqual(summaries['N']['via_count'], 0)
        self.assertEqual(summaries['OTHER']['via_count'], 1)
        self.assertAlmostEqual(summaries['OTHER']['max_via_current_a'], 2.0)


class PreviewTests(unittest.TestCase):
    pads = {
        'A': dict(identifier='A', label='J1.1',
                  polygons_by_layer={'0': [[[[0, 0], [2, 0], [2, 1], [0, 1]]]]}),
        'B': dict(identifier='B', label='J1.2',
                  polygons_by_layer={'0': [[[[0, 0], [1, 0], [1, 1], [0, 1]]]]}),
        'C': dict(identifier='C', label='J1.3'),
    }

    def test_per_pad_preview_is_exact(self):
        preview = split_preview(self.pads, ['A', 'B', 'C'], 'per_pad', 3.0)
        self.assertEqual([record['value'] for record in preview], [1.0, 1.0, 1.0])
        self.assertAlmostEqual(sum(record['share'] for record in preview), 1.0)

    def test_area_preview_uses_pad_polygon_area(self):
        preview = split_preview(self.pads, ['A', 'B'], 'area', 3.0)
        self.assertAlmostEqual(preview[0]['area_mm2'], 2.0)
        self.assertAlmostEqual(preview[1]['area_mm2'], 1.0)
        self.assertAlmostEqual(preview[0]['value'], 2.0)
        self.assertAlmostEqual(preview[1]['value'], 1.0)

    def test_area_preview_without_geometry_falls_back_to_equal_shares(self):
        preview = split_preview(self.pads, ['C'], 'area', 2.0)
        self.assertAlmostEqual(preview[0]['share'], 1.0)
        self.assertAlmostEqual(preview[0]['value'], 2.0)
        preview = split_preview(self.pads, ['A', 'C'], 'area', 2.0)
        self.assertAlmostEqual(sum(record['share'] for record in preview), 1.0)

    def test_unknown_rule_and_empty_selection_are_safe(self):
        preview = split_preview(self.pads, ['A', 'B'], 'nonsense', 4.0)
        self.assertAlmostEqual(sum(record['value'] for record in preview), 4.0)
        self.assertEqual(split_preview(self.pads, [], 'per_pad', 4.0), [])

    def test_contour_area_ignores_degenerate_rings(self):
        from pcb_heatmap.model import contour_area, polygon_area
        self.assertEqual(contour_area([[0, 0], [1, 1]]), 0.0)
        self.assertEqual(polygon_area([]), 0.0)
        self.assertAlmostEqual(contour_area([[0, 0], [2, 0], [2, 2], [0, 2]]), 4.0)
