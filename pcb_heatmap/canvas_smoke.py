"""Synthetic geometry, direct-picking and wx render regression checks.

No user PCB is loaded or saved. This is a programmatic drawing smoke test,
not a screenshot or native UI automation helper.
"""
from __future__ import annotations

import importlib.util
import copy
import os
from pathlib import Path
import sys

os.environ['PCB_HEATMAP_HEADLESS'] = '1'
HERE = Path(__file__).resolve().parent
if 'pcb_heatmap' not in sys.modules:
    spec = importlib.util.spec_from_file_location('pcb_heatmap', HERE / '__init__.py', submodule_search_locations=[str(HERE)])
    package = importlib.util.module_from_spec(spec)
    sys.modules['pcb_heatmap'] = package
    spec.loader.exec_module(package)

import numpy as np
import wx
from pcb_heatmap.board_view import BoardCanvas, point_in_polygons


def rectangle(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def layout_fixture():
    return {
        'bounds_mm': [0, 0, 20, 12],
        'outline': [[rectangle(0, 0, 20, 12), rectangle(18, 9, 19, 10)]],
        'holes': [[rectangle(16, 9, 17, 10)]],
        'layers': [{'name': 'F.Cu'}, {'name': 'B.Cu'}],
        'pads': [{'identifier': 'pad-a', 'label': 'J1.1', 'reference': 'J1', 'number': '1',
                  'net': 'POWER', 'x_mm': 2, 'y_mm': 2, 'layers': [0],
                  'polygons_by_layer': {'0': [[rectangle(1, 1, 3, 3), rectangle(1.75, 1.75, 2.25, 2.25)]]},
                  'hole_polygons': [[rectangle(1.75, 1.75, 2.25, 2.25)]]},
                 {'identifier': 'pad-b', 'label': 'J2.1', 'reference': 'J2', 'number': '1',
                  'net': 'POWER', 'x_mm': 16, 'y_mm': 2, 'layers': [1],
                  'polygons_by_layer': {'1': [[rectangle(15, 1, 17, 3)]]}}],
        'copper_by_layer': [[{'net': 'POWER', 'kind': 'zone', 'identifier': 'zone-1',
                              'polygons': [[rectangle(.5, .5, 17.5, 8.5), rectangle(8, 4, 12, 8)]]},
                             {'net': 'POWER', 'kind': 'track', 'identifier': 'trace-1',
                              'polygons': [[rectangle(3, 1.8, 8, 2.2)]]}],
                            [{'net': 'POWER', 'kind': 'track', 'identifier': 'trace-2',
                              'polygons': [[rectangle(3, 1.8, 16, 2.2)]]}]],
        'vias': [{'identifier': 'via-1', 'net': 'POWER', 'x_mm': 5, 'y_mm': 5,
                  'diameter_mm': 1, 'drill_mm': .5, 'layers': [0, 1]}],
        'footprints': [{'reference': 'J1', 'value': 'IN', 'x_mm': 2, 'y_mm': 2,
                        'layer_index': 0, 'box_mm': [1, 1, 3, 3]},
                       {'reference': 'J2', 'value': 'OUT', 'x_mm': 16, 'y_mm': 2,
                        'layer_index': 1, 'box_mm': [15, 1, 17, 3]}],
        'drawings_by_layer': {'0': [{'kind': 'drawing', 'polygons': [[rectangle(1, 1, 4, 4)]]}]}}


class Click:
    def __init__(self, point, ctrl=False):
        self.point, self.ctrl = point, ctrl
    def GetPosition(self):
        return self.point
    def ControlDown(self):
        return self.ctrl


def main():
    app = wx.App(False)
    frame = wx.Frame(None, size=(900, 650))
    events, marker_events = [], []
    canvas = BoardCanvas(frame, on_pick=events.append, on_marker=marker_events.append)
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(canvas, 1, wx.EXPAND)
    frame.SetSizer(sizer)
    frame.Layout()
    canvas.set_layout(layout_fixture())
    assert point_in_polygons(1, 1, canvas.layout['outline'])
    assert not point_in_polygons(18.5, 9.5, canvas.layout['outline'])
    assert canvas.hit_test(2, 2)['pad_ids'] == ['pad-a']
    assert canvas.hit_test(4, 4)['net'] == 'POWER'
    assert canvas.hit_test(10, 6) is None, 'Zone void must not be selected by bounding box.'
    assert canvas.hit_test(10, 6, heat=True)['net'] == ''
    assert canvas.hit_test(18.5, 9.5, heat=True) is None, 'Board cutout is not a thermal contact.'
    assert canvas.hit_test(16.5, 9.5, heat=True) is None, 'A drill hole is not a board heat contact.'
    via_hit = canvas.hit_test(5, 5)
    distance = math_hypot(via_hit['x_mm'] - 5, via_hit['y_mm'] - 5)
    assert .25 < distance < .5, 'Via drill click must anchor to actual copper annulus.'
    canvas.set_layer(1)
    assert canvas.hit_test(2, 2) is None
    assert canvas.hit_test(16, 2)['pad_ids'] == ['pad-b']
    canvas.set_layer(-1)
    original = canvas.screen_to_world(123, 234)
    canvas.zoom_at(123, 234, 1.8)
    assert np.allclose(original, canvas.screen_to_world(123, 234))
    canvas.set_mode('source')
    canvas._click(Click(canvas.world_to_screen(2, 2)))
    assert events[-1]['pad_ids'] == ['pad-a'] and events[-1]['kind'] == 'source'
    canvas.set_mode('select')
    canvas._click(Click(canvas.world_to_screen(16, 2), True))
    assert events[-1]['pad_ids'] == ['pad-a', 'pad-b']
    previous = len(events)
    for point in ((4, 4), (5, 5), (10, 6), (25, 15), (16.5, 9.5)):
        canvas._click(Click(canvas.world_to_screen(*point), True))
        assert canvas.get_selection() == ['pad-a', 'pad-b'], 'Ctrl non-pad click must retain the group.'
        assert len(events) == previous, 'Ctrl non-pad click must not create a point contact.'
    previous = len(events)
    canvas.set_selection(['pad-a'])
    canvas.set_mode('load')
    assert len(events) == previous, 'Host setters must not cause selection callback loops.'
    canvas._click(Click(canvas.world_to_screen(4, 4)))
    point = events[-1]['points'][0]
    assert point['net'] == 'POWER' and point['layer'] == 0 and point['identifier'].startswith('point:')
    # Component bodies copy only their own source-net pads. A direct pad click
    # stays precise, including a different-net pad inside that same body.
    fixture = layout_fixture()
    for identifier, x, y, net, layer, reference in (
            ('q1-a', 9, 1, 'POWER', 0, 'Q1'), ('q1-b', 11, 1, 'POWER', 0, 'Q1'),
            ('q1-g', 9, 3, 'GND', 0, 'Q1'), ('q2-a', 10, 1, 'POWER', 1, 'Q2')):
        fixture['pads'].append({'identifier': identifier, 'reference': reference,
                                'label': identifier, 'number': identifier[-1], 'net': net,
                                'x_mm': x, 'y_mm': y, 'layers': [layer],
                                'polygons_by_layer': {str(layer): [[rectangle(x-.3, y-.3, x+.3, y+.3)]]}})
    fixture['footprints'].extend([
        {'reference': 'Q1', 'x_mm': 10, 'y_mm': 2, 'layer_index': 0, 'box_mm': [8.5, .5, 11.5, 3.5]},
        {'reference': 'Q2', 'x_mm': 10, 'y_mm': 2, 'layer_index': 1, 'box_mm': [8.5, .5, 11.5, 3.5]}])
    unchanged = copy.deepcopy(fixture)
    canvas.set_layout(fixture)
    canvas.set_preferred_net('POWER')
    canvas.set_layer(0)
    hit = canvas.hit_test(10, 2)
    assert hit['reference'] == 'Q1' and hit['pad_ids'] == ['q1-a', 'q1-b']
    canvas._click(Click(canvas.world_to_screen(10, 2)))
    assert events[-1]['pad_ids'] == ['q1-a', 'q1-b'] and events[-1]['auto_matched']
    assert events[-1]['kind'] == 'load'
    canvas._click(Click(canvas.world_to_screen(10, 2), True))
    assert canvas.get_selection() == [], 'Ctrl component click toggles the matching group.'
    canvas._click(Click(canvas.world_to_screen(10, 2), True))
    assert canvas.get_selection() == ['q1-a', 'q1-b']
    canvas._click(Click(canvas.world_to_screen(9, 3)))
    assert events[-1]['pad_ids'] == ['q1-g'] and not events[-1]['auto_matched']
    canvas.set_layer(1)
    assert canvas.hit_test(10, 2)['pad_ids'] == ['q2-a'], 'Body picking respects the board side.'
    canvas.set_layer(0)
    assert canvas.hit_test(10, 2, heat=True)['type'] == 'point', 'Heaters do not use source-net grouping.'
    canvas.set_preferred_net('OTHER')
    assert canvas.hit_test(10, 2)['pad_ids'] == [], 'No-match body must not select a copper plane below it.'
    canvas.set_preferred_net('')
    assert canvas.hit_test(10, 2)['type'] == 'point', 'Grouping can be disabled.'
    assert fixture == unchanged, 'Canvas selection and settings never alter exported PCB data.'
    canvas.set_layout(layout_fixture())
    canvas.set_layer(-1)
    values = np.array([[20., 30.], [40., 50.]])
    canvas.set_overlay(values, np.array([[1, 1], [1, 0]], bool), '°C', (2., 3.), .5, scale=(0., 100.))
    assert canvas.overlay_value(2.1, 3.1) == (20., '°C')
    assert canvas.overlay_value(2.6, 3.1) == (30., '°C')
    assert canvas.overlay_value(2.6, 3.6) is None
    assert canvas.overlay_value(1.99, 3.1) is None
    canvas.set_markers([{'id': 'source-1', 'kind': 'source', 'pad_ids': ['pad-a'], 'label': '5 V'},
                        {'id': 'load-1', 'kind': 'load', 'points': [point], 'label': '2 A'}])
    # Exercise the same native wx graphics routines used by EVT_PAINT, without
    # capturing a desktop screenshot or accessing another app's surface.
    bitmap = wx.Bitmap(900, 650)
    dc = wx.MemoryDC(bitmap)
    gc = wx.GraphicsContext.Create(dc)
    canvas._draw_base(gc)
    canvas._draw_top(gc)
    canvas._draw_legend(gc, 900)
    assert len(canvas._marker_hits) == 2
    mx, my, _ = canvas._marker_hits[0]
    canvas._click(Click((mx, my)))
    assert marker_events[-1] == 'source-1'
    canvas._click(Click((mx, my), True))
    assert marker_events == ['source-1'], 'Ctrl-clicking a marked pad selects it instead of editing its value.'
    assert canvas.get_selection() == ['pad-a']
    canvas.set_visibility(references=False, pad_numbers=False, drawings=False,
                          zones=False, tracks=False, vias=False)
    assert not any(canvas.get_visibility().values())
    assert canvas.hit_test(4, 4) is None, 'Hidden copper is not selectable as a point.'
    assert canvas.hit_test(2, 2)['type'] == 'pad', 'Pads remain selectable when drawing aids are hidden.'
    canvas._draw_base(gc)
    canvas._draw_top(gc)
    assert len(canvas._marker_hits) == 2, 'Numerical source/load markers stay visible.'
    canvas.set_show_references(True)
    assert canvas.get_visibility()['references']
    assert not canvas.get_visibility()['drawings'], 'Visibility controls operate independently.'
    del gc
    dc.SelectObject(wx.NullBitmap)
    canvas.language = lambda: 'tr'
    canvas.fit_board()
    assert canvas.focus_reference('J1')
    assert not canvas.focus_reference('UNKNOWN')
    canvas.clear()
    assert canvas.layout is None and canvas.get_selection() == [] and canvas._overlay is None
    frame.Destroy()
    app.ProcessPendingEvents()
    print('Board canvas: geometry, Ctrl selection, component grouping, visibility, overlay and native drawing checks passed.')


def math_hypot(x, y):
    return (x*x + y*y) ** .5


if __name__ == '__main__':
    main()
