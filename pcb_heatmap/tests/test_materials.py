"""Substrate directionality and legacy-scenario physical regression checks."""
from __future__ import annotations

import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
from materials import substrate_conductivities
from model import (AnalysisError, AnalysisSettings, ComponentHeat, Layer, Load,
                   Pad, RasterBoard, Scenario, Source, Via)
from solver import _thermal_system, analyze


def board_fixture():
    copper = np.ones((2, 3, 6), dtype=float)
    board = RasterBoard(0, 0, 1., np.ones((3, 6), dtype=bool), copper,
                        {'N': copper.copy()}, [Layer('F.Cu', .07, .035), Layer('B.Cu', .07, 1.565)],
                        [], {}, {}, metadata={'board_thickness_mm': 1.6})
    for identifier, col in [('S', 0), ('D', 5)]:
        board.pads[identifier] = Pad(identifier, identifier, 'N', col + .5, .5, (0, 1))
        board.pad_cells[identifier] = [(l, r, col) for l in range(2) for r in range(3)]
    return board


def run_case(settings):
    return analyze(board_fixture(), Scenario([Source(['S'], 5.)], [Load(['D'], 2.)], settings=settings))


class MaterialTests(unittest.TestCase):
    def test_legacy_k_remains_isotropic(self):
        settings = AnalysisSettings(fr4_k=.679)
        self.assertEqual(substrate_conductivities(settings), (.679, .679))
        self.assertIsNone(settings.substrate_k_z)
        self.assertEqual(settings.substrate_material, 'custom')

    def test_material_category_does_not_change_user_conductivity(self):
        for material in ['custom', 'fr4', 'ceramic']:
            settings = AnalysisSettings(fr4_k=23.4, substrate_k_z=17.2, substrate_material=material)
            self.assertEqual(substrate_conductivities(settings), (23.4, 17.2))

    def test_explicit_isotropic_matches_legacy_solution(self):
        settings = AnalysisSettings(fr4_k=.51, alpha=0, tolerance_c=1e-7)
        explicit = copy.deepcopy(settings)
        explicit.substrate_k_z = .51
        explicit.substrate_material = 'fr4'
        legacy_result, explicit_result = run_case(settings), run_case(explicit)
        np.testing.assert_array_equal(legacy_result.temperature_c, explicit_result.temperature_c)
        np.testing.assert_array_equal(legacy_result.joule_w, explicit_result.joule_w)

    def test_xy_and_z_enter_distinct_physical_conductances(self):
        board = board_fixture()
        board.copper[:] = 0
        settings = AnalysisSettings(fr4_k=.8, substrate_k_z=.2)
        z = np.asarray([l.z_mm * .001 for l in board.layers])
        _, left, right, conductance, _, _, _ = _thermal_system(board, settings, z, .0016)
        layer_size = board.board_mask.size
        lateral = (left // layer_size) == (right // layer_size)
        # Each thermal slice is .8mm thick; square XY faces cancel cell width.
        np.testing.assert_allclose(conductance[lateral], .8 * .0008, rtol=1e-12)
        # No copper coverage: only through-plane k enters each Z resistance.
        np.testing.assert_allclose(conductance[~lateral], .001 ** 2 * .2 / .00153, rtol=1e-12)
        changed = copy.deepcopy(settings)
        changed.substrate_k_z = .6
        more_z = _thermal_system(board, changed, z, .0016)[3]
        np.testing.assert_allclose(more_z[lateral], conductance[lateral], rtol=1e-12)
        np.testing.assert_allclose(more_z[~lateral], 3 * conductance[~lateral], rtol=1e-12)

    def test_ceramic_conductivity_above_old_gui_limit_solves_and_preserves_electrics(self):
        regular = AnalysisSettings(alpha=0, fr4_k=.3, tolerance_c=1e-7)
        ceramic = AnalysisSettings(alpha=0, fr4_k=170., substrate_k_z=150.,
                                   substrate_material='ceramic', tolerance_c=1e-7)
        first, second = run_case(regular), run_case(ceramic)
        np.testing.assert_allclose(second.joule_w, first.joule_w, rtol=1e-12)
        self.assertAlmostEqual(second.summaries['convection_w'], second.summaries['total_heat_w'], places=8)
        self.assertTrue(np.isfinite(second.temperature_c).all())
        self.assertEqual(second.diagnostics['substrate'], {
            'material': 'ceramic', 'k_xy_w_mk': 170., 'k_z_w_mk': 150.,
            'construction': 'homogeneous_insulating_substrate'})

    def test_nonpositive_nonfinite_and_nonnumeric_values_rejected(self):
        for value in [0., -1., float('nan'), float('inf'), True, '170']:
            for field in ['fr4_k', 'substrate_k_z']:
                settings = AnalysisSettings()
                setattr(settings, field, value)
                with self.subTest(field=field, value=value), self.assertRaises(AnalysisError) as caught:
                    substrate_conductivities(settings)
                self.assertEqual(caught.exception.code, 'invalid_substrate_conductivity')

    def test_metal_core_cannot_silently_become_a_homogeneous_aluminium_board(self):
        settings = AnalysisSettings(fr4_k=200., substrate_material='metal_core')
        with self.assertRaises(AnalysisError) as caught:
            run_case(settings)
        self.assertEqual(caught.exception.code, 'unsupported_metal_core')
        self.assertIn('separate insulating dielectric and metal-base', str(caught.exception))
        diagnostic = caught.exception.diagnostic
        self.assertIsNotNone(diagnostic)
        self.assertNotIn('temperature_c', diagnostic)
        self.assertNotIn('max_temperature_c', diagnostic['summaries'])
        self.assertEqual(diagnostic['reference_temperature_c'], 25.)
        self.assertAlmostEqual(diagnostic['summaries']['nets']['N']['source_current_a'], 2., places=7)
        self.assertGreater(diagnostic['summaries']['joule_w'], 0.)

    def test_metal_core_invalid_electrical_contact_does_not_produce_dc_maps(self):
        settings = AnalysisSettings(substrate_material='metal_core')
        with self.assertRaises(AnalysisError) as caught:
            analyze(board_fixture(), Scenario([Source(['missing'], 5.)], [Load(['D'], 2.)], settings=settings))
        self.assertIsNone(caught.exception.diagnostic)

    def test_metal_core_heater_only_does_not_fabricate_dc_maps(self):
        settings = AnalysisSettings(substrate_material='metal_core')
        with self.assertRaises(AnalysisError) as caught:
            analyze(board_fixture(), Scenario([], [], [ComponentHeat(['S'], .1)], settings))
        self.assertEqual(caught.exception.code, 'unsupported_metal_core')
        self.assertIsNone(caught.exception.diagnostic)

    def test_worker_preserves_new_fields_and_reads_legacy_scenarios(self):
        from pcb_heatmap.worker import read_scenario
        with tempfile.TemporaryDirectory(prefix='heatmap-material-test-') as folder:
            path = Path(folder) / 'scenario.json'
            path.write_text(json.dumps({'settings': {'fr4_k': .512}}), encoding='utf8')
            old, _ = read_scenario(path)
            self.assertEqual(old.settings.fr4_k, .512)
            self.assertIsNone(old.settings.substrate_k_z)
            new_data = {'settings': {'fr4_k': 170., 'substrate_k_z': 150., 'substrate_material': 'ceramic'}}
            path.write_text(json.dumps(new_data), encoding='utf8')
            new, _ = read_scenario(path)
            self.assertEqual(new.settings.fr4_k, 170.)
            self.assertEqual(new.settings.substrate_k_z, 150.)
            self.assertEqual(new.settings.substrate_material, 'ceramic')
            new_data['settings']['substrate_material'] = 'metal_core'
            path.write_text(json.dumps(new_data), encoding='utf8')
            dc_only, _ = read_scenario(path)
            self.assertEqual(dc_only.settings.substrate_material, 'metal_core')

    def test_settings_and_board_not_mutated_by_directional_solution(self):
        settings = AnalysisSettings(fr4_k=.679, substrate_k_z=.512)
        board = board_fixture()
        before_settings = asdict(settings)
        before_copper = board.copper.copy()
        analyze(board, Scenario([], [], [ComponentHeat(['S'], .01)], settings))
        self.assertEqual(asdict(settings), before_settings)
        np.testing.assert_array_equal(board.copper, before_copper)

    def test_via_approximation_does_not_create_negative_thermal_edges(self):
        board = board_fixture()
        board.vias = [Via(.5, .5, .2, .45, 0, 1, 'N')]
        settings = AnalysisSettings(fr4_k=450., substrate_k_z=450.)
        with self.assertRaises(AnalysisError) as caught:
            analyze(board, Scenario([], [], [ComponentHeat(['S'], .01)], settings))
        self.assertEqual(caught.exception.code, 'unsupported_via_substrate_conductivity')

    def test_native_worker_metal_core_writes_dc_only_never_temperature(self):
        from pcb_heatmap.test_extractor_native import make_fixture
        from pcb_heatmap.extractor import inspect_board
        with tempfile.TemporaryDirectory(prefix='heatmap-metal-core-worker-') as folder:
            folder = Path(folder)
            board_path = folder / 'generated.kicad_pcb'
            make_fixture(board_path, layers=4, via=True, cutout=True)
            info = inspect_board(str(board_path))
            pads = {pad['label']: pad['identifier'] for pad in info['pads']}
            scenario_path = folder / 'scenario.json'
            scenario_path.write_text(json.dumps({
                'sources': [{'pad_ids': [pads['J1.1']], 'voltage_v': 5.}],
                'loads': [{'pad_ids': [pads['J2.1']], 'current_a': 2.}],
                'settings': {'substrate_material': 'metal_core', 'fr4_k': 200., 'substrate_k_z': 2.}}), encoding='utf8')
            output = folder / 'results'
            child_env = dict(os.environ, PCB_HEATMAP_HEADLESS='1')
            process = subprocess.run([
                sys.executable, str(PACKAGE / 'worker.py'), 'analyze', '--board', str(board_path),
                '--scenario', str(scenario_path), '--output-dir', str(output), '--cell-mm', '.25', '--max-cells', '50000'],
                capture_output=True, text=True, encoding='utf8', errors='replace', timeout=90, env=child_env)
            self.assertNotEqual(process.returncode, 0)
            messages = []
            for line in process.stdout.splitlines():
                try:
                    messages.append(json.loads(line))
                except ValueError:
                    pass
            self.assertTrue(any(row.get('type') == 'diagnostic_result' for row in messages), process.stdout + process.stderr)
            self.assertTrue(any(row.get('code') == 'unsupported_metal_core' for row in messages), process.stdout)
            self.assertFalse((output / 'result.json').exists())
            self.assertFalse((output / 'result.npz').exists())
            result = json.loads((output / 'dc-diagnostic.json').read_text(encoding='utf8'))
            self.assertEqual(result['analysis_kind'], 'dc_diagnostic')
            self.assertEqual(result['thermal_status'], 'unavailable')
            self.assertEqual(result['thermal_error']['code'], 'unsupported_metal_core')
            self.assertEqual(result['scenario']['settings']['substrate_material'], 'metal_core')
            self.assertAlmostEqual(result['summaries']['nets']['POWER']['source_current_a'], 2., places=6)
            with np.load(output / 'dc-diagnostic.npz', allow_pickle=False) as arrays:
                self.assertNotIn('temperature_c', arrays.files)
                self.assertIn('voltage_v__0', arrays.files)
                self.assertIn('current_density_a_mm2__0', arrays.files)
                self.assertIn('joule_w', arrays.files)


if __name__ == '__main__':
    unittest.main()
