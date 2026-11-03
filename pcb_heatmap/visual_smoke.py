"""Synthetic PCB-first workflow checks; no user design files are used."""
from pathlib import Path
import copy
import json
import os
import sys
import tempfile

os.environ['PCB_HEATMAP_HEADLESS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import wx
from pcb_heatmap.visual_gui import VisualFrame
from pcb_heatmap.layout_export import export_layout
from pcb_heatmap.test_extractor_native import make_fixture
from pcb_heatmap.snapshot import create_snapshot


def main():
    app = wx.App(False)
    frames = []
    with tempfile.TemporaryDirectory(prefix='pcb-heatmap-visual-smoke-') as temp:
        folder = Path(temp)
        board = make_fixture(folder / 'synthetic.kicad_pcb', layers=4)
        original = board.read_bytes()
        layout = export_layout(board)
        f = VisualFrame()
        frames.append(f)
        f.board_path = str(board)
        view_folder = folder / 'view'; view_folder.mkdir()
        f.snapshot = create_snapshot(board, view_folder)
        f.accept_layout(layout)
        f.Layout()
        errors = []
        f.error = errors.append
        values = dict(source=5, load=2, heat=.1)
        f.ask_value = lambda kind, label, current=None: values[kind]
        ids = {pad['label']: pad['identifier'] for pad in layout['pads']}
        f.choose_mode('source')
        f.board_pick(dict(kind='source', pad_ids=[ids['J1.1']], points=[]))
        assert len(f.rows) == 1 and f.rows[0]['value'] == 5
        assert f.canvas.preferred_net == 'POWER'
        f.source_net.SetSelection(0); f.change_source_net(); f.refresh_rows()
        assert f.canvas.preferred_net == '', 'Exact pad mode must stay disabled after a row refresh'
        f.source_net.SetSelection(1); f.change_source_net()
        assert f.canvas.preferred_net == 'POWER'
        board.write_bytes(original + b'\n')
        assert f.verified(), 'Editing the original must not invalidate the displayed copy'
        started = []
        f.start_worker = lambda mode, args: started.append((mode, args))
        f.choose_mode('load')
        f.board_pick(dict(kind='load', pad_ids=[ids['J1.1']], points=[]))
        assert len(errors) == 1 and len(f.rows) == 1, 'Opposite terminal on same pad must be refused'
        f.board_pick(dict(kind='load', pad_ids=[ids['J2.1']], points=[]))
        assert len(f.rows) == 2 and f.rows[-1]['value'] == 2
        f.analyze()
        assert started and started[-1][0] == 'analyze'
        worker_args = started[-1][1]
        worker_board = Path(worker_args[worker_args.index('--board') + 1])
        assert worker_board != board and worker_board != Path(f.snapshot['path'])
        assert worker_board.read_bytes() == original, 'Each solve must use a fresh copy of the displayed snapshot'
        assert json.loads((f.result_dir / 'scenario.json').read_text(encoding='utf8'))['snapshot']['path'] == str(worker_board)
        board.write_bytes(original)
        f.board_pick(dict(kind='heat', pad_ids=[], points=[dict(identifier='point:heat', net='', layer=0, x_mm=4, y_mm=6)]))
        assert len(f.rows) == 3 and f.point_contacts['point:heat']['net'] == ''
        f.canvas.set_selection([ids['J2.1']])
        f.choose_mode('load')
        assert len(f.rows) == 3, 'Repeated identical group must edit the existing row, not double the load'
        assert f.rows[1]['value'] == 2 and '2 A' in f.current_summary.GetLabel()
        f.board_pick(dict(kind='select', cancel_tool=True, pad_ids=[], points=[]))
        assert f.mode == 'select' and f.mode_buttons['select'].GetValue()
        f.busy(True)
        assert not f.node_budget.IsEnabled() and all(not c.IsEnabled() for c in f.setting_controls.values())
        f.busy(False)
        assert f.node_budget.IsEnabled()
        case = f.scenario()
        assert len(case['contacts']) == 1 and case['loads'][0]['current_a'] == 2
        scenario_path = folder / 'case.json'
        f.write_case(scenario_path)
        saved = json.loads(scenario_path.read_text(encoding='utf8'))
        assert saved['contacts'][0]['identifier'] == 'point:heat'
        try:
            f.write_case(board)
            raise AssertionError('Saving a scenario over a native PCB must be refused')
        except ValueError:
            pass
        f2 = VisualFrame()
        frames.append(f2)
        f2.board_path = str(board)
        f2.accept_layout(layout)
        f2.apply_case(saved)
        assert len(f2.rows) == 3 and 'point:heat' in f2.point_contacts
        duplicate_case = copy.deepcopy(saved)
        duplicate_case['loads'].append(copy.deepcopy(duplicate_case['loads'][0]))
        f2.apply_case(duplicate_case)
        duplicate_errors = []
        f2.error = duplicate_errors.append
        assert not f2.check_terminal_rows(f2.rows) and duplicate_errors
        assert '4 A' in f2.current_summary.GetLabel(), 'Imported duplicated loads must stay visible and be counted until user removes them'
        f2.apply_case(saved)
        before_rows = copy.deepcopy(f2.rows)
        invalid = copy.deepcopy(saved)
        invalid['settings']['ambient_c'] = 'not-a-number'
        invalid['loads'] = []
        try:
            f2.apply_case(invalid)
            raise AssertionError('Invalid settings must be refused before scenario state changes')
        except ValueError:
            pass
        assert f2.rows == before_rows
        shape = (4, 32, 48)
        temp = np.full(shape, 25.)
        temp[0, 8, 8] = 35
        temp[3, 8, 8] = 53
        volts = np.full(shape, 5.)
        volts[3] = 4.9
        density = np.ones(shape)
        density[3] *= 10
        np.savez_compressed(folder / 'result.npz', temperature_c=temp, voltage_v__0=volts,
                            current_density_a_mm2__0=density, board_mask=np.ones(shape[-2:], bool))
        metadata = dict(sha256=layout['sha256'], arrays_file='result.npz', nets=['POWER'],
                        origin_x_mm=0, origin_y_mm=0, cell_mm=.25, source_voltages={'POWER': 5},
                        summaries=dict(max_temperature_c=53, total_heat_w=.4,
                                       hotspot=dict(layer='B.Cu', x_mm=2.125, y_mm=2.125)), diagnostics={})
        (folder / 'result.json').write_text(json.dumps(metadata), encoding='utf8')
        f.load_result(folder / 'result.json')
        assert not f.result_dirty and f.canvas.overlay_value(2.125, 2.125)[0] == 35
        missing_sha = dict(metadata); missing_sha.pop('sha256')
        (folder / 'bad-result.json').write_text(json.dumps(missing_sha), encoding='utf8')
        try:
            f.load_result(folder / 'bad-result.json')
            raise AssertionError('A result without snapshot identity must not be shown over the PCB')
        except ValueError:
            pass
        previous_path, previous_snapshot, previous_layout = f.board_path, f.snapshot, f.layout_data
        other_board = folder / 'another-board.kicad_pcb'; other_board.write_bytes(original)
        from unittest.mock import patch
        with patch('pcb_heatmap.visual_gui.create_snapshot', side_effect=OSError('simulated copy failure')):
            f.reload(use_active=False, board_path=other_board)
        assert f.board_path == previous_path and f.snapshot == previous_snapshot and f.layout_data is previous_layout
        f.layer.SetSelection(4)
        f.render_result()
        assert f.canvas.overlay_value(2.125, 2.125)[0] == 53
        for view in (1, 2, 3):
            f.view.SetSelection(view)
            for layer in (0, 1, 4):
                f.layer.SetSelection(layer)
                f.render_result()
                assert f.canvas._overlay is not None
        f.language_choice.SetSelection(1)
        f.change_language()
        assert f.mode_buttons['load'].GetLabel() == 'Yük · A'
        assert f.sidebar_notebook.GetPageText(0) == 'Girişler ve yükler'
        assert 'çekilen 2 A' in f.current_summary.GetLabel()
        token = f.process_token = object()
        f.worker_event(token, dict(type='error', code='electrothermal_outside_validity', message='English fallback',
                                   details=dict(iteration=1, model_limit_c=1500,
                                                net_loads=[dict(net='POWER', group_count=13, draw_a=1040, injection_a=0)])))
        assert '1040 A' in f.last_log[-1] and 'Atanan akımlar' in f.last_log[-1]
        assert 'English fallback' not in f.last_log[-1]
        f.process_token = None
        f.update_selection_info()
        assert f.selection_info.GetSize().height >= f.selection_info.GetBestSize().height
        f.mode = 'heat'
        f.canvas.set_mode('heat')
        f.marker_pick(f.rows[0]['identifier'])
        assert f.result_dirty and f.canvas._overlay is None
        f.canvas.set_selection([ids['J1.1']])
        f.update_selection_info()
        assert 'J1.1' in f.selection_info.GetLabel()
        assert f.canvas.focus_reference('J1')
        # A rejected thermal solve still exposes first-reference DC maps,
        # never a temperature array or a completed-thermal message.
        joule = np.zeros(shape); joule[0, 8, 8] = .01; joule[3, 8, 8] = .02
        np.savez_compressed(folder / 'dc-diagnostic.npz', joule_w=joule, voltage_v__0=volts,
                            current_density_a_mm2__0=density, board_mask=np.ones(shape[-2:], bool),
                            copper=np.ones(shape))
        diagnostic = dict(metadata, arrays_file='dc-diagnostic.npz', analysis_kind='dc_diagnostic',
                          thermal_status='unavailable', reference_temperature_c=25,
                          summaries=dict(nets={}, joule_w=.03),
                          thermal_error=dict(code='electrothermal_outside_validity', details={}))
        (folder / 'dc-diagnostic.json').write_text(json.dumps(diagnostic), encoding='utf8')
        f.layer.SetSelection(1)
        f.result_dir = folder
        token = f.process_token = object()
        f.last_log = ['Thermal result unavailable']
        f.worker_event(token, dict(type='diagnostic_result', path=str(folder / 'outside' / 'dc-diagnostic.json')))
        assert f._diagnostic_path is None, 'Reject output paths outside this worker run'
        f.worker_event(token, dict(type='diagnostic_result', path=str(folder / 'dc-diagnostic.json')))
        f.worker_finished(token, 'analyze', 1, [])
        assert f.is_dc_diagnostic() and not f.result_dirty and f.analysis_notice.IsShown()
        assert 'temperature' not in f.view_keys and 'temperature_c' not in f.arrays
        assert f.view_keys[f.view.GetSelection()] == 'power'
        assert abs(f.canvas.overlay_value(2.125, 2.125)[0] - .16) < 1e-12
        assert f.canvas.overlay_value(2.125, 2.125)[1] == 'W/mm²'
        assert 'sıcaklık tahmini değildir' in f.analysis_notice.GetLabel()
        assert '0.03 W' in f.stats.GetLabel()
        for key in ('density', 'drop', 'power'):
            f.view.SetSelection(f.view_keys.index(key))
            f.render_result()
            assert f.canvas._overlay is not None
        f.language_choice.SetSelection(0); f.change_language()
        assert 'not a temperature prediction' in f.analysis_notice.GetLabel()
        assert f.view_keys[f.view.GetSelection()] == 'power'
        assert f.folder_button.IsEnabled() and f.run_button.IsEnabled() and f.progress.GetValue() == 0
        # A fake diagnostic containing temperatures is refused before any UI
        # state is changed; the trusted DC maps remain on screen.
        corrupt = dict(diagnostic, arrays_file='result.npz')
        (folder / 'invalid-diagnostic.json').write_text(json.dumps(corrupt), encoding='utf8')
        try:
            f.load_result(folder / 'invalid-diagnostic.json')
            raise AssertionError('A DC diagnostic with temperature data must not be accepted')
        except ValueError:
            pass
        assert f.is_dc_diagnostic()
        f.load_result(folder / 'result.json')
        assert 'temperature' in f.view_keys and not f.analysis_notice.IsShown()
        assert board.read_bytes() == original
        for frame in frames:
            frame.Destroy()
        app.Yield(True)
    app.Destroy()
    print('VISUAL_SMOKE_OK: PCB direct contacts, marker editing, multi-pad group, atomic case loading, no PCB overwrite, settings lock, bilingual UI and aligned multilayer overlays')


if __name__ == '__main__':
    main()
