"""Read-only native KiCad -> worker -> solver integration on generated boards."""
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

os.environ['PCB_HEATMAP_HEADLESS'] = '1'
PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE.parent))
from pcb_heatmap.test_extractor_native import make_fixture


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class WorkerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pcb-heatmap-worker-test-')
        self.directory = Path(self.temp.name)
        self.board = self.directory / 'generated-only.kicad_pcb'
        make_fixture(self.board, layers=4, via=True, cutout=True)
        self.original_hash = digest(self.board)

    def tearDown(self):
        self.assertEqual(self.original_hash, digest(self.board), 'The analysed native PCB must never be saved or mutated.')
        self.temp.cleanup()

    def run_worker(self, *args, worker=None):
        result = subprocess.run([sys.executable, str(worker or PACKAGE / 'worker.py'), *map(str, args)],
                                cwd=self.directory, capture_output=True, text=True, encoding='utf8',
                                errors='replace', timeout=90)
        messages = []
        # Native builds can write diagnostic chatter; only valid protocol lines count.
        for line in result.stdout.splitlines():
            try:
                value = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and 'type' in value:
                messages.append(value)
        return result, messages

    def inspect(self, worker=None):
        output = self.directory / ('inspect-' + str(len(list(self.directory.iterdir()))) + '.json')
        process, messages = self.run_worker('inspect', '--board', self.board, '--output', output, worker=worker)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertTrue(any(item['type'] == 'result' for item in messages), process.stdout)
        return json.loads(output.read_text(encoding='utf8'))

    def make_scenario(self, info, **changes):
        labels = {item['label']: item['identifier'] for item in info['pads']}
        data = {'expected_sha256': self.original_hash,
                'sources': [{'pad_ids': [labels['J1.1']], 'voltage_v': 33.6}],
                'loads': [{'pad_ids': [labels['J2.1']], 'current_a': 2}],
                'settings': {'alpha': 0, 'convection_top': 50, 'convection_bottom': 50,
                             'solver_tolerance': 1e-9, 'tolerance_c': 1e-5}}
        data.update(changes)
        output = self.directory / 'scenario.json'
        output.write_text(json.dumps(data), encoding='utf8')
        return output

    def test_inspect_emits_json_without_source_changes(self):
        info = self.inspect()
        self.assertEqual(info['sha256'], self.original_hash)
        self.assertEqual(len(info['layers']), 4)
        self.assertEqual({item['label'] for item in info['pads']}, {'J1.1', 'J2.1'})
        self.assertEqual(digest(self.board), self.original_hash)

    def test_inspect_cannot_overwrite_native_input(self):
        process, messages = self.run_worker('inspect', '--board', self.board, '--output', self.board)
        self.assertNotEqual(process.returncode, 0)
        self.assertTrue(any(item['type'] == 'error' for item in messages), process.stdout)
        self.assertFalse(any(item['type'] == 'result' for item in messages))
        self.assertEqual(digest(self.board), self.original_hash)

    def test_analysis_four_layers_conserves_current_and_heat_and_safe_npz(self):
        info = self.inspect()
        config = self.make_scenario(info)
        output = self.directory / 'analysis'
        process, messages = self.run_worker('analyze', '--board', self.board, '--scenario', config,
                                            '--output-dir', output, '--cell-mm', '.25', '--max-cells', '50000')
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        progress = [item['progress'] for item in messages if item['type'] == 'progress']
        self.assertTrue(progress)
        self.assertTrue(all(0 <= value <= 1 for value in progress))
        self.assertEqual(progress[-1], 1)
        self.assertTrue(any(item['type'] == 'result' for item in messages))
        result = json.loads((output / 'result.json').read_text(encoding='utf8'))
        self.assertEqual(result['sha256'], self.original_hash)
        self.assertEqual(result['nets'], ['POWER'])
        net = result['summaries']['nets']['POWER']
        self.assertAlmostEqual(net['source_current_a'], 2, places=6)
        self.assertAlmostEqual(net['load_current_a'], 2, places=12)
        self.assertGreater(net['joule_w'], 0)
        self.assertAlmostEqual(net['energy_error_w'], 0, places=6)
        self.assertAlmostEqual(result['summaries']['total_heat_w'], result['summaries']['convection_w'], places=7)
        self.assertEqual(len(result['via_current_a']), 2)
        self.assertTrue(all(len(via['segments']) == 3 for via in result['via_current_a']))
        self.assertTrue(any(via['max_current_a'] > 0 for via in result['via_current_a']))
        self.assertTrue(result['diagnostics']['converged'])
        with np.load(output / 'result.npz', allow_pickle=False) as arrays:
            self.assertEqual(arrays['temperature_c'].shape, (4, 32, 48))
            self.assertEqual(arrays['board_mask'].dtype, np.dtype('bool'))
            for name in arrays.files:
                self.assertNotEqual(arrays[name].dtype.kind, 'O', f'{name} cannot contain pickled arbitrary objects.')
            mask = arrays['board_mask']
            self.assertTrue(np.isfinite(arrays['temperature_c'][:, mask]).all())
            self.assertTrue(np.isfinite(arrays['voltage_v__0']).any())
            self.assertTrue(np.isfinite(arrays['current_density_a_mm2__0']).any())
            self.assertGreater(arrays['joule_w'].sum(), 0)
            self.assertAlmostEqual(float(arrays['joule_w'].sum()), result['summaries']['joule_w'], places=12)

    def test_stale_source_hash_rejects_without_results(self):
        config = self.make_scenario(self.inspect(), expected_sha256='0' * 64)
        output = self.directory / 'rejected-stale'
        process, messages = self.run_worker('analyze', '--board', self.board, '--scenario', config,
                                            '--output-dir', output, '--cell-mm', '.25')
        self.assertNotEqual(process.returncode, 0)
        errors = [item for item in messages if item['type'] == 'error']
        self.assertTrue(errors)
        self.assertIn('changed', errors[-1]['message'])
        self.assertFalse((output / 'result.json').exists())
        self.assertFalse((output / 'result.npz').exists())
        self.assertFalse(any(item['type'] == 'result' for item in messages))

    def test_invalid_terminal_has_error_but_no_result(self):
        info = self.inspect()
        source_id = next(item['identifier'] for item in info['pads'] if item['label'] == 'J1.1')
        config = self.make_scenario(info, loads=[{'pad_ids': [source_id], 'current_a': 2}])
        output = self.directory / 'rejected-overlap'
        process, messages = self.run_worker('analyze', '--board', self.board, '--scenario', config,
                                            '--output-dir', output, '--cell-mm', '.25')
        self.assertNotEqual(process.returncode, 0)
        self.assertTrue(any(item['type'] == 'error' and 'overlap' in item['message'] for item in messages), process.stdout)
        self.assertFalse((output / 'result.json').exists())
        self.assertFalse((output / 'result.npz').exists())
        self.assertFalse(any(item['type'] == 'result' for item in messages))

    def test_pcm_identifier_directory_bootstraps_without_repository_imports(self):
        installed = self.directory / 'plugins' / 'com_github_mey-26_pcb-heatmap'
        installed.mkdir(parents=True)
        # Explicit source allowlist: no user projects, caches, generated outputs or tests.
        for filename in ['__init__.py', 'worker.py', 'model.py', 'extractor.py', 'solver.py', 'materials.py']:
            shutil.copy2(PACKAGE / filename, installed / filename)
        info = self.inspect(worker=installed / 'worker.py')
        self.assertEqual(info['sha256'], self.original_hash)
        self.assertEqual(len(info['layers']), 4)
        self.assertEqual(info['board_path'], str(self.board.resolve()))


if __name__ == '__main__':
    unittest.main()
