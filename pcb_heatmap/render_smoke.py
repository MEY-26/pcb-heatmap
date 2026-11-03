"""Local wx smoke test; synthetic data only, no PCB inspection or mutation."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ['PCB_HEATMAP_HEADLESS'] = '1'
HERE = Path(__file__).resolve().parent
if 'pcb_heatmap' not in sys.modules:
    spec = importlib.util.spec_from_file_location('pcb_heatmap', HERE / '__init__.py', submodule_search_locations=[str(HERE)])
    module = importlib.util.module_from_spec(spec)
    sys.modules['pcb_heatmap'] = module
    spec.loader.exec_module(module)

import numpy as np
import wx
from pcb_heatmap.gui import MainFrame, PadPicker, colorize, worker_python, apply_light_palette


def main():
    app = wx.App(False)
    frame = MainFrame()
    frame.Show(False)
    frame.Layout()
    def descend(window):
        yield window
        for child in window.GetChildren():
            yield from descend(child)
    # Simulate the inherited dark KiCad client palette, then verify that our
    # frame alone owns readable foregrounds/backgrounds.
    for control in descend(frame):
        control.SetOwnForegroundColour('#ffffff')
        control.SetOwnBackgroundColour('#101010')
    apply_light_palette(frame)
    for control in (frame.stats, frame.notes, frame.terminals, frame.view, frame.net,
                    frame.setting_controls['ambient_c']):
        assert control.GetForegroundColour().GetAsString(wx.C2S_HTML_SYNTAX).lower() == '#172e43'
        if not isinstance(control, wx.SpinCtrlDouble):
            assert control.GetBackgroundColour().GetAsString(wx.C2S_HTML_SYNTAX).lower() == '#ffffff'
    for child in frame.setting_controls['ambient_c'].GetChildren():
        if isinstance(child, wx.TextCtrl):
            assert child.GetBackgroundColour().GetAsString(wx.C2S_HTML_SYNTAX).lower() == '#ffffff'
    assert Path(worker_python()).is_file()
    assert not frame.run_button.IsEnabled()
    pads = [dict(identifier=f'pad{i}', label=f'J1.{i}', net='SUPPLY', reference='J1', footprint='Connector', x_mm=i, y_mm=0, layers=[0]) for i in range(1, 5)]
    frame.pad_by_id = {pad['identifier']: pad for pad in pads}
    with PadPicker(frame, pads) as picker:
        assert picker.identifiers() == [], 'Footprint pads must not be selected by default'
        picker.check_visible(None)
        assert len(picker.identifiers()) == 4
        picker.search.SetValue('J1.1')
        assert len(picker.visible) == 1
        assert len(picker.identifiers()) == 4, 'Filtering must retain explicit checked state'
        picker.uncheck(None)
        assert not picker.identifiers()
    frame.rows = [dict(kind='source', pad_ids=['pad1'], value=5), dict(kind='load', pad_ids=['pad2', 'pad3'], value=2)]
    frame.inspection = dict(sha256='synthetic', layers=[dict(name='F.Cu'), dict(name='B.Cu')],
                            stats=dict(copper_zones=12, filled_copper_zones=11))
    frame.refresh_rows()
    errors = []
    original_error, original_verified, original_worker = frame.error, frame.verified, frame.start_worker
    frame.error = errors.append
    frame.verified = lambda **kwargs: True
    frame.start_worker = lambda *args: (_ for _ in ()).throw(AssertionError('Overlap must be rejected before starting a worker'))
    good_rows = frame.rows
    frame.rows = [dict(kind='source', pad_ids=['pad1'], value=5), dict(kind='load', pad_ids=['pad1'], value=2)]
    frame.analyze()
    assert len(errors) == 1 and 'J1.1' in errors[0] and 'DIFFERENT' in errors[0]
    frame.language = 'tr'
    frame.analyze()
    assert len(errors) == 2 and 'FARKLI' in errors[-1] and 'J1.1' in errors[-1]
    assert frame.process is None and frame.result_dir is None
    frame.rows = good_rows
    frame.language = 'en'
    frame.error, frame.verified, frame.start_worker = original_error, original_verified, original_worker
    case = frame.scenario()
    assert case['loads'][0]['current_a'] == 2
    assert len(case['loads'][0]['pad_ids']) == 2
    frame.language_choice.SetSelection(1)
    frame.change_language(None)
    assert 'Padleri' in frame.capture_mode.GetString(1)
    assert '12 bakır zone (11 dolgulu)' in frame.board_label.GetLabel()
    assert frame.usage_button.GetLabel() == 'Kullanım'
    frame.language_choice.SetSelection(0)
    frame.change_language(None)
    assert '12 copper zones (11 filled)' in frame.board_label.GetLabel()
    shape = (2, 30, 50)
    temperature = np.full(shape, 25.0)
    temperature[:, 8:22, 12:35] += 12
    temperature[1, 15, 25] = 53
    volts = np.full(shape, 5.)
    volts[:, 5:25, 10:40] = 4.95
    current = np.zeros(shape)
    current[:, 5:25, 10:40] = 20
    with tempfile.TemporaryDirectory(prefix='pcb-heatmap-gui-smoke-') as directory:
        output = Path(directory)
        np.savez_compressed(output / 'result.npz', temperature_c=temperature, voltage_v__0=volts,
                            current_density_a_mm2__0=current, board_mask=np.ones(shape[1:], bool), copper=np.ones(shape))
        metadata = dict(arrays_file='result.npz', nets=['SUPPLY'], layers=[dict(name='F.Cu'), dict(name='B.Cu')],
                        source_voltages_v=dict(SUPPLY=5), origin_x_mm=0, origin_y_mm=0, cell_mm=.25,
                        summaries=dict(total_heat_w=2, joule_w=1.5, component_heat_w=.5),
                        via_current_a=[dict(max_current_a=3, net='SUPPLY', x_mm=2, y_mm=3)])
        (output / 'result.json').write_text(json.dumps(metadata), encoding='utf-8')
        frame.load_result(output / 'result.json')
        assert frame.canvas.high == 53
        # Native bitmap must own the expected RGB pixels even after allocation
        # churn and garbage collection (embedded KiCad defers paint events).
        import gc
        expected_rgb = frame.canvas.rgb_buffer.copy()
        allocations = [bytearray(expected_rgb.nbytes) for _ in range(40)]
        del allocations
        gc.collect()
        image = frame.canvas.bitmap.ConvertToImage()
        pixels = np.frombuffer(image.GetData(), dtype=np.uint8).reshape(expected_rgb.shape)
        assert np.array_equal(pixels, expected_rgb), 'Native bitmap pixel roundtrip changed the heatmap'
        assert len(np.unique(pixels.reshape(-1, 3), axis=0)) > 1
        assert frame.stats.GetLabel().count('\n') >= 3
        assert frame.stats.GetSize().height >= frame.stats.GetBestSize().height, 'Four-line result statistics must be fully visible'
        frame.language_choice.SetSelection(1)
        frame.change_language(None)
        assert frame.notes.GetValue().startswith('Kararlı DC yaklaşımı.')
        assert frame.terminals.GetColumn(3).GetText() == 'Toplam'
        assert frame.stats.GetSize().height >= frame.stats.GetBestSize().height
        frame.language_choice.SetSelection(0)
        frame.change_language(None)
        frame.layer.SetSelection(1)
        frame.render_result()
        assert frame.canvas.high == 53, 'Layer filters must keep the common scale'
        assert float(np.max(frame.canvas.values)) == 37
        for view in range(3):
            frame.view.SetSelection(view)
            for layer in range(3):
                frame.layer.SetSelection(layer)
                frame.render_result()
                assert frame.canvas.bitmap.IsOk()
        frame.view.SetSelection(2)
        frame.layer.SetSelection(0)
        frame.render_result()
        assert np.isclose(frame.canvas.high, 50)
        frame.rows[0]['value'] = 0
        frame.result['source_voltages_v']['SUPPLY'] = 0
        frame.arrays['voltage_v__0'][:] = .02
        frame.arrays['voltage_v__0'][1] = .05
        frame.render_result()
        assert np.isclose(frame.canvas.high, 50), 'Return-net rise magnitude must be visible'
    rgb = colorize(np.array([[0., 1., np.nan]]), np.array([[True, True, False]]), 0, 1)
    assert rgb.shape == (1, 3, 3) and rgb.dtype == np.uint8
    frame.Destroy()
    app.Yield(True)
    app.Destroy()
    print('GUI_SMOKE_OK: bilingual controls, explicit pad selection, group totals, 3 maps, common layer scale, ground rise magnitude')


if __name__ == '__main__':
    main()
