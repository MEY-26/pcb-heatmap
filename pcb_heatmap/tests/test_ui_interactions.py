"""List keyboard actions, undo/redo, inline values and the adaptive card."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import wx

os.environ['PCB_HEATMAP_HEADLESS'] = '1'
from pcb_heatmap.visual_gui import VisualFrame


def terminal(identifier, kind, *pad_ids, value=1):
    return dict(identifier=identifier, kind=kind, pad_ids=list(pad_ids), value=value)


class EditEvent:
    def __init__(self, text='', cancelled=False, column=2, index=0):
        self.text, self.cancelled, self.column, self.index = text, cancelled, column, index
        self.vetoed = False

    def GetColumn(self):
        return self.column

    def GetText(self):
        return self.text

    def IsEditCancelled(self):
        return self.cancelled

    def GetIndex(self):
        return self.index

    def Veto(self):
        self.vetoed = True


class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.frame = VisualFrame(preferences_path=str(Path(self.directory.name) / 'prefs.json'))
        self.frame.error = Mock()
        self.frame.start_worker = Mock()
        self.frame.pad_by_id = {
            name: dict(identifier=name, label=name, net='VBUS', layers=[0],
                       reference=name.split('.')[0], x_mm=index, y_mm=0)
            for index, name in enumerate(('J1.1', 'J1.2', 'U1.1', 'U1.2'))
        }
        self.frame.canvas._pad_by_id = dict(self.frame.pad_by_id)

    def tearDown(self):
        self.frame.process = None
        self.frame._settings_timer.Stop()
        self.frame.Destroy()
        wx.Yield()
        self.directory.cleanup()

    def rows(self, *records):
        self.frame.rows = list(records)
        self.frame.refresh_rows()

    def select(self, *indices):
        for index in range(self.frame.terminals.GetItemCount()):
            self.frame.terminals.Select(index, False)
        for index in indices:
            self.frame.terminals.Select(index)

    def test_delete_key_removes_selected_rows(self):
        self.rows(terminal('a', 'heat', 'J1.1'), terminal('b', 'heat', 'J1.2'),
                  terminal('c', 'heat', 'U1.1'))
        self.select(0, 2)
        event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
        event.SetKeyCode(wx.WXK_DELETE)
        self.frame._list_key(event)
        self.assertEqual([row['identifier'] for row in self.frame.rows], ['b'])

    def test_many_rows_ask_before_removing(self):
        self.rows(*(terminal(name, 'heat', pad) for name, pad in
                    (('a', 'J1.1'), ('b', 'J1.2'), ('c', 'U1.1'), ('d', 'U1.2'))))
        self.select(0, 1, 2, 3)
        with patch('pcb_heatmap.visual_gui.wx.MessageBox', return_value=wx.NO):
            self.frame.remove_group()
        self.assertEqual(len(self.frame.rows), 4)
        with patch('pcb_heatmap.visual_gui.wx.MessageBox', return_value=wx.YES):
            self.frame.remove_group()
        self.assertEqual(self.frame.rows, [])

    def test_undo_and_redo_restore_rows(self):
        self.rows(terminal('a', 'heat', 'J1.1'), terminal('b', 'heat', 'J1.2'))
        self.select(1)
        self.frame.remove_group()
        self.assertEqual(len(self.frame.rows), 1)
        self.frame.undo()
        self.assertEqual([row['identifier'] for row in self.frame.rows], ['a', 'b'])
        self.frame.redo()
        self.assertEqual([row['identifier'] for row in self.frame.rows], ['a'])

    def test_inline_value_edit_updates_the_row(self):
        self.rows(terminal('a', 'load', 'J1.1', value=1.0))
        event = EditEvent('2,5')
        with patch('pcb_heatmap.visual_gui.wx.CallAfter', lambda fn, *a: fn(*a)):
            self.frame._end_label_edit(event)
        self.assertFalse(event.vetoed)
        self.assertAlmostEqual(self.frame.rows[0]['value'], 2.5)

    def test_inline_edit_rejects_zero_load_and_text(self):
        self.rows(terminal('a', 'load', 'J1.1', value=1.0))
        for text in ('0', 'nonsense'):
            event = EditEvent(text)
            with patch('pcb_heatmap.visual_gui.wx.CallAfter', lambda fn, *a: fn(*a)):
                self.frame._end_label_edit(event)
            self.assertTrue(event.vetoed, text)
            self.assertEqual(self.frame.rows[0]['value'], 1.0)

    def test_selection_card_is_group_only_for_several_pads(self):
        self.frame.canvas.selected = ['J1.1']
        self.frame.update_selection_info()
        self.assertEqual(self.frame.selection_info.GetLabel(), 'J1.1')
        self.assertFalse(self.frame.group_note.IsShown())
        self.frame.canvas.selected = ['J1.1', 'J1.2']
        self.frame.update_selection_info()
        self.assertIn('2', self.frame.selection_info.GetLabel())
        self.assertTrue(self.frame.group_note.IsShown())
        self.frame.canvas.selected = []
        self.frame.update_selection_info()
        self.assertEqual(self.frame.selection_info.GetLabel(), 'No pads selected')
        self.assertFalse(self.frame.group_note.IsShown())

    def test_preset_sets_cell_and_tolerance(self):
        self.frame.preset_choice.SetSelection(0)   # Fast
        self.frame.apply_preset()
        self.assertAlmostEqual(self.frame.setting_controls['cell_mm'].GetValue(), 0.5)
        self.assertAlmostEqual(
            self.frame.setting_controls['solver_tolerance'].GetValue(), 1e-6)
        self.frame.preset_choice.SetSelection(2)   # Fine
        self.frame.apply_preset()
        self.assertAlmostEqual(self.frame.setting_controls['cell_mm'].GetValue(), 0.25)

    def test_copper_override_shows_up_in_the_scenario(self):
        self.frame.inspection = dict(sha256='abc', nets=['VBUS'], pads=[], stats={},
                                     layers=[dict(name='F.Cu', thickness_mm=0.035),
                                             dict(name='B.Cu', thickness_mm=0.035)])
        self.frame.rebuild_copper_rows()
        self.assertIsNone(self.frame.copper_thickness())
        self.frame.copper_spins[0].SetValue(70)
        self.assertEqual(self.frame.copper_thickness(), [70, 35])
        data = self.frame.scenario()
        self.assertEqual(data['settings']['copper_um'], [70, 35])

    def test_assign_ids_and_add_to_selection(self):
        self.frame.verified = lambda **kwargs: True
        self.frame.ask_value = Mock(return_value=3.0)
        self.frame.canvas.selected = ['J1.1']
        self.frame.add_to_selection(['J1.2', 'J1.1'])
        self.assertEqual(self.frame.canvas.get_selection(), ['J1.1', 'J1.2'])
        self.frame.assign_ids('heat', ['U1.1'])
        self.assertEqual(self.frame.rows[0]['pad_ids'], ['U1.1'])
        self.assertEqual(self.frame.rows[0]['kind'], 'heat')

    def test_marker_toggle_hides_markers_and_is_remembered(self):
        self.assertTrue(self.frame.canvas.get_visibility()['markers'])
        self.frame.canvas.set_markers([dict(id='a', kind='source', pad_ids=['J1.1'],
                                            value=5, label='5 V')])
        self.frame.toggle_markers()
        self.assertFalse(self.frame.canvas.show_markers)
        self.assertFalse(self.frame.markers_button.active)
        self.assertFalse(self.frame.ui_state['markers'])
        self.frame.canvas.set_visibility(markers=True)
        self.assertEqual(set(self.frame.canvas.get_visibility()),
                         {'references', 'pad_numbers', 'drawings', 'tracks', 'zones',
                          'vias', 'markers'})
        self.frame.toggle_markers()
        self.assertFalse(self.frame.canvas.show_markers)
        self.frame.toggle_markers()
        self.assertTrue(self.frame.canvas.show_markers)
        self.assertTrue(self.frame.markers_button.active)

    def test_zoom_out_uses_the_whole_board_bitmap(self):
        from pcb_heatmap.board_view import BoardCanvas
        canvas = BoardCanvas(self.frame)
        canvas.set_layout(dict(bounds_mm=(0, 0, 100, 80),
                               outline=[[[0, 0], [100, 0], [100, 80], [0, 80]]],
                               pads=[], layers=[{'name': 'F.Cu'}], copper_by_layer=[],
                               vias=[], footprints=[], holes=[], drawings_by_layer={},
                               nets=[]))
        canvas.SetSize((600, 400))
        world = canvas._ensure_world_bitmap()
        self.assertIsNotNone(world)
        from pcb_heatmap.board_view import WORLD_BITMAP_LIMIT
        self.assertLessEqual(max(world.GetSize()), WORLD_BITMAP_LIMIT)
        xmin, ymin, xmax, ymax = canvas._world_view
        self.assertLessEqual(xmin, 0)
        self.assertGreaterEqual(xmax, 100)
        canvas.fit_board()
        before = canvas.scale
        canvas.zoom_at(300, 200, 0.4)
        self.assertLess(canvas.scale, before)
        bitmap = wx.Bitmap(600, 400)
        memory = wx.MemoryDC(bitmap)
        try:
            self.assertTrue(canvas._paint_fast(memory, 600, 400),
                            'A zoomed-out gesture must paint from the board bitmap.')
        finally:
            memory.SelectObject(wx.NullBitmap)
        canvas.Destroy()

    def test_history_lists_completed_runs(self):
        self.frame.result = dict(summaries=dict(
            max_temperature_c=41.5, nets={'VBUS': dict(max_delta_v=0.02,
                                                       copper_area_mm2=12.5)}))
        self.frame.record_history()
        self.assertEqual(len(self.frame.run_history), 1)
        self.assertIn('41.50', self.frame.history_label.GetLabel())
        self.assertIn('12.5', self.frame.history_label.GetLabel())
