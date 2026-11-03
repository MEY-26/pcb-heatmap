"""Snapshot provenance and edits to the source PCB during an actual solve."""
from argparse import Namespace
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['PCB_HEATMAP_HEADLESS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pcb_heatmap.snapshot import create_snapshot, digest
from pcb_heatmap.test_extractor_native import make_fixture


class SnapshotTests(unittest.TestCase):
    def test_copy_is_independent_and_existing_files_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / 'live.kicad_pcb'
            source.write_bytes(b'(kicad_pcb (version 20241229))')
            run = folder / 'run'; run.mkdir()
            before = source.read_bytes()
            record = create_snapshot(source, run)
            self.assertEqual(source.read_bytes(), before)
            copy = Path(record['path'])
            self.assertEqual(copy.read_bytes(), before)
            self.assertEqual(record['sha256'], digest(source))
            self.assertEqual(record['original_path'], str(source.resolve()))
            source.write_bytes(before + b'\n; newer user edits')
            self.assertEqual(copy.read_bytes(), before)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                create_snapshot(source, run)
            self.assertEqual(copy.read_bytes(), before)

    def test_copy_for_solver_must_match_the_displayed_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / 'source.kicad_pcb'; source.write_bytes(b'initial')
            view = folder / 'view'; view.mkdir()
            frozen = create_snapshot(source, view)
            source.write_bytes(b'new board contents')
            run = folder / 'solve'; run.mkdir()
            copied = create_snapshot(frozen['path'], run, expected_sha256=frozen['sha256'], original_path=source)
            self.assertEqual(copied['sha256'], frozen['sha256'])
            self.assertEqual(copied['original_path'], str(source.resolve()))
            bad = folder / 'bad'; bad.mkdir()
            with self.assertRaisesRegex(ValueError, 'changed'):
                create_snapshot(source, bad, expected_sha256=frozen['sha256'])
            self.assertFalse((bad / 'board-snapshot.kicad_pcb').exists())

    def test_editing_original_during_worker_solve_keeps_snapshot_result_valid(self):
        from pcb_heatmap import worker, solver
        from pcb_heatmap.extractor import inspect_board
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            original = make_fixture(folder / 'live.kicad_pcb', layers=4)
            before = original.read_bytes()
            run = folder / 'solve'; run.mkdir()
            frozen = create_snapshot(original, run)
            info = inspect_board(frozen['path'])
            pads = {pad['label']: pad['identifier'] for pad in info['pads']}
            scenario = dict(expected_sha256=frozen['sha256'], original_board_path=str(original), snapshot=frozen,
                            sources=[dict(pad_ids=[pads['J1.1']], voltage_v=33.6)],
                            loads=[dict(pad_ids=[pads['J2.1']], current_a=2)], heaters=[],
                            settings=dict(alpha=0, convection_top=50, convection_bottom=50))
            config = folder / 'case.json'; config.write_text(json.dumps(scenario), encoding='utf8')
            solve = solver.analyze

            def edit_while_solving(*args, **kwargs):
                # Simulate the user's independent save, not a plugin write.
                original.write_bytes(before + b'\n')
                return solve(*args, **kwargs)

            args = Namespace(command='analyze', board=frozen['path'], scenario=str(config),
                             output_dir=str(run), cell_mm=.5, max_cells=50000)
            with patch.object(solver, 'analyze', side_effect=edit_while_solving), redirect_stdout(io.StringIO()):
                worker.run(args)
            result = json.loads((run / 'result.json').read_text(encoding='utf8'))
            self.assertEqual(original.read_bytes(), before + b'\n')
            self.assertEqual(Path(frozen['path']).read_bytes(), before)
            self.assertEqual(result['sha256'], frozen['sha256'])
            self.assertEqual(result['original_board_path'], str(original))
            self.assertEqual(result['snapshot'], frozen)
            self.assertAlmostEqual(result['summaries']['nets']['POWER']['source_current_a'], 2, places=6)
            self.assertGreaterEqual(result['timings_s']['solver'], 0)


if __name__ == '__main__':
    unittest.main()
