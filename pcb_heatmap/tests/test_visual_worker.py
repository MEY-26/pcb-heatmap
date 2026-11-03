"""Visual PCB/point-terminal worker integration on generated native boards only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pcbnew as p

os.environ['PCB_HEATMAP_HEADLESS'] = '1'
PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE.parent))
from pcb_heatmap.test_extractor_native import make_fixture
from pcb_heatmap.extractor import _sample_polygons


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contact(identifier, x, y, net='POWER', layer=0):
    return dict(identifier='point:' + identifier, net=net, layer=layer, x_mm=x, y_mm=y)


class VisualWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='heatmap-visual-worker-')
        self.directory = Path(self.temp.name)
        self.board = self.directory / 'generated-four-layer.kicad_pcb'
        make_fixture(self.board, layers=4, via=True, cutout=True)
        self.original_hash = digest(self.board)

    def tearDown(self):
        self.assertEqual(digest(self.board), self.original_hash,
                         'Reading/analyzing the PCB must not save or modify its native contents.')
        self.temp.cleanup()

    def worker(self, *args, worker=None):
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        environment['PYTHONNOUSERSITE'] = '1'
        process = subprocess.run([sys.executable, str(worker or PACKAGE / 'worker.py'), *map(str, args)],
                                 cwd=self.directory, capture_output=True, text=True, encoding='utf8',
                                 errors='replace', timeout=90, env=environment)
        messages = []
        for line in process.stdout.splitlines():
            try:
                item = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            if isinstance(item, dict) and 'type' in item:
                messages.append(item)
        return process, messages

    def scenario(self, **changes):
        data = dict(expected_sha256=self.original_hash,
                    contacts=[contact('source', 2.2, 3), contact('load', 9.8, 3)],
                    sources=[dict(pad_ids=['point:source'], voltage_v=33.6)],
                    loads=[dict(pad_ids=['point:load'], current_a=2)],
                    heaters=[], settings=dict(alpha=0, convection_top=50, convection_bottom=50,
                                              solver_tolerance=1e-9, tolerance_c=1e-5))
        data.update(changes)
        path = self.directory / 'visual-scenario.json'
        path.write_text(json.dumps(data), encoding='utf8')
        return path

    def analyze(self, config, worker=None):
        output = self.directory / 'result'
        process, messages = self.worker('analyze', '--board', self.board, '--scenario', config,
                                        '--output-dir', output, '--cell-mm', '.25',
                                        '--max-cells', '50000', worker=worker)
        return process, messages, output

    def assert_failed_without_results(self, process, messages, output, error_fragment):
        self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(any(item['type'] == 'error' and error_fragment in item['message']
                            for item in messages), process.stdout + process.stderr)
        self.assertFalse(any(item['type'] == 'result' for item in messages), process.stdout)
        self.assertFalse((output / 'result.json').exists())
        self.assertFalse((output / 'result.npz').exists())
        self.assertFalse((output / 'dc-diagnostic.json').exists())
        self.assertFalse((output / 'dc-diagnostic.npz').exists())

    def test_component_pad_heat_without_any_electrical_net_solve(self):
        board = p.LoadBoard(str(self.board))
        footprint = next(fp for fp in board.GetFootprints() if fp.GetReference() == 'J1')
        identifier = str(next(iter(footprint.Pads())).m_Uuid.AsString())
        config = self.scenario(contacts=[], sources=[], loads=[],
                               heaters=[dict(pad_ids=[identifier], power_w=1.)])
        process, messages, output = self.analyze(config)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads((output / 'result.json').read_text(encoding='utf8'))
        self.assertEqual(result['nets'], [])
        self.assertEqual(result['summaries']['component_heat_w'], 1.)
        self.assertEqual(result['summaries']['joule_w'], 0.)
        self.assertGreater(result['summaries']['max_temperature_c'], 25.)

    def test_layout_exports_native_vector_geometry_without_source_changes(self):
        output = self.directory / 'layout.json'
        process, messages = self.worker('layout', '--board', self.board, '--output', output)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(any(item['type'] == 'result' for item in messages), process.stdout)
        layout = json.loads(output.read_text(encoding='utf8'))
        self.assertEqual(layout['sha256'], self.original_hash)
        self.assertEqual(layout['bounds_mm'], [0, 0, 12, 8])
        self.assertEqual(len(layout['layers']), 4)
        self.assertEqual(len(layout['copper_by_layer']), 4)
        self.assertTrue(all(any(item['kind'] == 'track' and item['polygons'] for item in layer)
                            for layer in layout['copper_by_layer']))
        self.assertEqual({pad['label'] for pad in layout['pads']}, {'J1.1', 'J2.1'})
        self.assertTrue(all(pad['polygons_by_layer']['0'] for pad in layout['pads']))
        self.assertEqual(len(layout['vias']), 2)
        self.assertTrue(all(via['layers'] == [0, 1, 2, 3] for via in layout['vias']))
        self.assertEqual(layout['nets'], ['POWER'])
        self.assertTrue(layout['outline'])

    def test_layout_exports_filled_zone_with_holes(self):
        # Editing here is restricted to our generated disposable fixture.
        make_fixture(self.board, layers=4, via=True, cutout=True, zone=True)
        native = p.LoadBoard(str(self.board))
        p.ZONE_FILLER(native).Fill(native.Zones())
        p.SaveBoard(str(self.board), native)
        self.original_hash = digest(self.board)
        output = self.directory / 'layout-zone.json'
        process, _ = self.worker('layout', '--board', self.board, '--output', output)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        layout = json.loads(output.read_text(encoding='utf8'))
        self.assertEqual(layout['stats']['copper_zones'], 1)
        self.assertEqual(layout['stats']['filled_copper_zones'], 1)
        zones = [item for layer in layout['copper_by_layer'] for item in layer if item['kind'] == 'zone']
        self.assertTrue(zones)
        self.assertTrue(all(item['net'] == 'GND' and item['polygons'] for item in zones))
        # KiCad may fracture holes into slit-connected outlines rather than
        # separate hole contours. Test physical coverage, not representation.
        polygons = [[np.asarray(contour, dtype=float) for contour in polygon]
                    for item in zones for polygon in item['polygons']]
        coverage = _sample_polygons(polygons, (0, 0), .25, 32, 48)
        self.assertGreater(coverage[18, 8], .9)
        self.assertEqual(coverage[24, 24], 0,
                         'The native board cutout must remain empty in exported filled-zone geometry.')

    def test_visual_point_source_and_load_conserve_current_and_energy(self):
        records = [contact('source', 2.2, 3), contact('load', 9.8, 3), contact('heater', 1, 6, net='')]
        config = self.scenario(contacts=records, heaters=[dict(pad_ids=['point:heater'], power_w=.01)])
        before_config = config.read_bytes()
        process, messages, output = self.analyze(config)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(any(item['type'] == 'result' for item in messages), process.stdout)
        result = json.loads((output / 'result.json').read_text(encoding='utf8'))
        self.assertEqual(result['sha256'], self.original_hash)
        self.assertEqual(result['nets'], ['POWER'])
        net = result['summaries']['nets']['POWER']
        self.assertAlmostEqual(net['source_current_a'], 2, places=6)
        self.assertAlmostEqual(net['load_current_a'], 2, places=10)
        self.assertGreater(net['joule_w'], 0)
        self.assertAlmostEqual(net['energy_error_w'], 0, places=6)
        self.assertAlmostEqual(result['summaries']['component_heat_w'], .01, places=10)
        self.assertAlmostEqual(result['summaries']['total_heat_w'], result['summaries']['convection_w'], places=7)
        self.assertTrue(any('ideal terminals' in warning for warning in result['warnings']))
        saved_scenario = json.loads((output / 'scenario.json').read_text(encoding='utf8'))
        self.assertEqual(saved_scenario['contacts'], records)
        self.assertEqual(config.read_bytes(), before_config)
        with np.load(output / 'result.npz', allow_pickle=False) as arrays:
            mask = arrays['board_mask']
            self.assertEqual(arrays['temperature_c'].shape, (4, 32, 48))
            self.assertTrue(np.isfinite(arrays['temperature_c'][:, mask]).all())
            self.assertTrue(np.isfinite(arrays['voltage_v__0']).any())
            self.assertTrue(np.isfinite(arrays['current_density_a_mm2__0']).any())
            self.assertTrue(all(arrays[key].dtype.kind != 'O' for key in arrays.files))

    def test_visual_heat_only_point_on_fr4_without_electrical_net(self):
        config = self.scenario(contacts=[contact('heater', 1, 6, net='')], sources=[], loads=[],
                               heaters=[dict(pad_ids=['point:heater'], power_w=.01)])
        process, messages, output = self.analyze(config)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads((output / 'result.json').read_text(encoding='utf8'))
        self.assertEqual(result['nets'], [])
        self.assertEqual(result['summaries']['nets'], {})
        self.assertEqual(result['summaries']['joule_w'], 0)
        self.assertAlmostEqual(result['summaries']['component_heat_w'], .01, places=10)
        self.assertAlmostEqual(result['summaries']['convection_w'], .01, places=7)
        self.assertGreater(result['summaries']['max_temperature_c'], 25)
        self.assertTrue(any(item['type'] == 'result' for item in messages), process.stdout)

    def test_visual_contacts_stale_sha_rejected_without_result(self):
        process, messages, output = self.analyze(self.scenario(expected_sha256='0' * 64))
        self.assert_failed_without_results(process, messages, output, 'changed')

    def test_unstable_analysis_emits_structured_load_diagnostics_without_result(self):
        config = self.scenario(loads=[dict(pad_ids=['point:load'], current_a=1000000)])
        process, messages, output = self.analyze(config)
        self.assertNotEqual(process.returncode, 0)
        errors = [event for event in messages if event['type'] == 'error']
        self.assertTrue(errors, process.stdout + process.stderr)
        self.assertEqual(errors[-1]['code'], 'electrothermal_outside_validity')
        self.assertEqual(errors[-1]['details']['net_loads'][0]['draw_a'], 1000000)
        self.assertGreater(errors[-1]['details']['computed_peak_c'], 1500)
        self.assertFalse((output / 'result.json').exists())
        self.assertFalse((output / 'result.npz').exists())
        partial_events = [event for event in messages if event['type'] == 'diagnostic_result']
        self.assertEqual(len(partial_events), 1)
        self.assertEqual(Path(partial_events[0]['path']), output / 'dc-diagnostic.json')
        self.assertFalse(any(event['type'] == 'result' for event in messages))
        metadata = json.loads((output / 'dc-diagnostic.json').read_text(encoding='utf8'))
        self.assertEqual(metadata['analysis_kind'], 'dc_diagnostic')
        self.assertEqual(metadata['thermal_status'], 'unavailable')
        self.assertEqual(metadata['reference_temperature_c'], 25)
        self.assertEqual(metadata['sha256'], self.original_hash)
        self.assertEqual(metadata['thermal_error']['code'], 'electrothermal_outside_validity')
        self.assertNotIn('max_temperature_c', metadata['summaries'])
        self.assertAlmostEqual(metadata['summaries']['nets']['POWER']['source_current_a'], 1000000, places=2)
        self.assertGreater(metadata['summaries']['joule_w'], 0)
        with np.load(output / 'dc-diagnostic.npz', allow_pickle=False) as arrays:
            self.assertNotIn('temperature_c', arrays.files)
            self.assertTrue(np.isfinite(arrays['voltage_v__0']).any())
            self.assertGreater(float(arrays['joule_w'].sum()), 0)
            self.assertTrue(all(arrays[key].dtype.kind != 'O' for key in arrays.files))
        original_diagnostic = (output / 'dc-diagnostic.npz').read_bytes()
        process2, events2 = self.worker('analyze', '--board', self.board, '--scenario', config,
                                        '--output-dir', output, '--cell-mm', '.25', '--max-cells', '50000')
        self.assertNotEqual(process2.returncode, 0)
        self.assertTrue(any(e['type'] == 'error' and 'already contains' in e['message'] for e in events2))
        self.assertEqual((output / 'dc-diagnostic.npz').read_bytes(), original_diagnostic)

    def test_visual_point_inside_clearance_rejected_without_snapping_or_result(self):
        records = [contact('source', 2.2, 3), contact('load', 6, 4)]
        process, messages, output = self.analyze(self.scenario(contacts=records))
        self.assert_failed_without_results(process, messages, output, 'no resolved copper')

    def test_visual_points_and_layout_in_renamed_pcm_directory(self):
        installed = self.directory / 'plugins' / 'com_github_mey-26_pcb-heatmap'
        installed.mkdir(parents=True)
        for filename in ['__init__.py', 'worker.py', 'model.py', 'extractor.py', 'solver.py', 'materials.py',
                         'layout_export.py', 'contacts.py']:
            shutil.copy2(PACKAGE / filename, installed / filename)
        output = self.directory / 'installed-layout.json'
        process, _ = self.worker('layout', '--board', self.board, '--output', output,
                                 worker=installed / 'worker.py')
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        layout = json.loads(output.read_text(encoding='utf8'))
        self.assertEqual(layout['sha256'], self.original_hash)
        self.assertEqual(len(layout['copper_by_layer']), 4)
        process, messages, result_dir = self.analyze(self.scenario(), worker=installed / 'worker.py')
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(any(item['type'] == 'result' for item in messages), process.stdout)
        result = json.loads((result_dir / 'result.json').read_text(encoding='utf8'))
        self.assertAlmostEqual(result['summaries']['nets']['POWER']['source_current_a'], 2, places=6)


if __name__ == '__main__':
    unittest.main()
