"""Calculation controls restore and flush user preferences across GUI sessions."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import wx

os.environ['PCB_HEATMAP_HEADLESS'] = '1'
from pcb_heatmap.preferences import load_calculation_settings, save_calculation_settings
from pcb_heatmap.visual_gui import VisualFrame


class CalculationSettingsGUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'preferences.json'
        self.frames = []

    def tearDown(self):
        for frame in self.frames:
            if frame:
                frame.process = None
                frame._settings_timer.Stop()
                frame.Destroy()
        wx.Yield()
        self.temp.cleanup()

    def frame(self):
        frame = VisualFrame(preferences_path=self.path)
        frame.error = Mock()
        frame.start_worker = Mock()
        self.frames.append(frame)
        return frame

    @staticmethod
    def edit(control, value):
        # Exercise the bound editing event, without a worker or native PCB.
        control.SetValue(value)
        event = wx.CommandEvent(wx.EVT_TEXT.typeId, control.GetId())
        event.SetEventObject(control)
        control.GetEventHandler().ProcessEvent(event)

    @staticmethod
    def board_metadata(frame):
        frame.inspection = dict(sha256='synthetic-board', layers=[dict(name='F.Cu')],
                                pads=[], nets=['N'])

    def case(self, settings, **extra):
        return dict(expected_sha256='synthetic-board', settings=settings,
                    sources=[], loads=[], heaters=[], contacts=[], **extra)

    def test_changed_controls_material_and_budget_restore_in_fresh_window(self):
        first = self.frame()
        values = dict(ambient_c=32.5, convection_top=30., convection_bottom=0.,
                      via_plating_um=35., cell_mm=.075, fr4_k=170.,
                      substrate_k_z=140., copper_k=390.,
                      max_temperature_c=115., max_delta_v=.125)
        self.assertEqual(set(values), set(first.setting_controls),
                         'Include each editable calculation setting in the roundtrip.')
        for key, value in values.items():
            self.edit(first.setting_controls[key], value)
            self.assertTrue(first._settings_timer.IsRunning(), key)
            first._settings_timer.Stop()
        self.edit(first.node_budget, 750000)
        first.material_choice._choose(first.material_ids.index('ceramic'))
        self.assertTrue(first._settings_timer.IsRunning())
        self.assertTrue(first.persist_calculation_settings())
        second = self.frame()
        for key, value in values.items():
            self.assertAlmostEqual(second.setting_controls[key].GetValue(), value,
                                   places=6, msg=key)
        self.assertEqual(second.node_budget.GetValue(), 750000)
        self.assertEqual(second.selected_material(), 'ceramic')
        self.assertFalse(second._settings_timer.IsRunning(),
                         'Restoring a saved setting must not act like a user edit.')
        self.assertEqual(load_calculation_settings(self.path),
                         dict(values, node_budget=750000, substrate_material='ceramic'))
        first.start_worker.assert_not_called()
        second.start_worker.assert_not_called()

    def test_legacy_preference_without_z_retains_isotropic_conductivity(self):
        self.assertTrue(save_calculation_settings({'fr4_k': .679}, self.path))
        frame = self.frame()
        self.assertAlmostEqual(frame.setting_controls['fr4_k'].GetValue(), .679)
        self.assertAlmostEqual(frame.setting_controls['substrate_k_z'].GetValue(), .679)
        self.assertEqual(frame.selected_material(), 'custom')

    def test_explicit_isotropic_none_restores_same_xy_and_z(self):
        self.assertTrue(save_calculation_settings(dict(fr4_k=.512, substrate_k_z=None,
                                                       substrate_material='fr4'), self.path))
        frame = self.frame()
        self.assertAlmostEqual(frame.setting_controls['fr4_k'].GetValue(), .512)
        self.assertAlmostEqual(frame.setting_controls['substrate_k_z'].GetValue(), .512)
        self.assertEqual(frame.selected_material(), 'fr4')

    def test_legacy_case_mirrors_conductivity_in_z_despite_previous_anisotropy(self):
        frame = self.frame()
        self.board_metadata(frame)
        frame.setting_controls['fr4_k'].SetValue(20)
        frame.setting_controls['substrate_k_z'].SetValue(10)
        frame.material_choice.SetSelection(frame.material_ids.index('ceramic'))
        frame.apply_case(self.case({'fr4_k': .679}))
        self.assertAlmostEqual(frame.setting_controls['fr4_k'].GetValue(), .679)
        self.assertAlmostEqual(frame.setting_controls['substrate_k_z'].GetValue(), .679)
        self.assertEqual(frame.selected_material(), 'custom',
                         'Legacy cases predate the material label; do not inherit another case.')

    def test_new_case_retains_material_anisotropy_and_mesh_preferences(self):
        frame = self.frame()
        self.board_metadata(frame)
        frame.apply_case(self.case(dict(fr4_k=24., substrate_k_z=20.,
                                        substrate_material='ceramic'),
                                   cell_mm=.1, max_cells=650000))
        self.assertEqual(frame.selected_material(), 'ceramic')
        self.assertEqual(frame.setting_controls['fr4_k'].GetValue(), 24.)
        self.assertEqual(frame.setting_controls['substrate_k_z'].GetValue(), 20.)
        self.assertAlmostEqual(frame.setting_controls['cell_mm'].GetValue(), .1)
        self.assertEqual(frame.node_budget.GetValue(), 650000)
        self.assertEqual(frame.scenario()['settings']['substrate_material'], 'ceramic')

    def test_material_edit_invalidates_existing_result_and_schedules_save(self):
        frame = self.frame()
        frame.result = {'analysis_kind': 'thermal'}
        frame.canvas.clear_overlay = Mock()
        frame.material_choice._choose(frame.material_ids.index('ceramic'))
        self.assertTrue(frame.result_dirty)
        frame.canvas.clear_overlay.assert_called()
        self.assertTrue(frame._settings_timer.IsRunning())
        self.assertFalse(self.path.exists(), 'Autosaving is debounced rather than blocking each edit.')

    def test_close_flushes_pending_changes_without_waiting_for_debounce(self):
        frame = self.frame()
        self.edit(frame.setting_controls['ambient_c'], 37.)
        self.assertTrue(frame._settings_timer.IsRunning())
        self.assertFalse(self.path.exists())
        self.assertTrue(frame.Close())
        self.assertEqual(load_calculation_settings(self.path)['ambient_c'], 37.)
        frame.start_worker.assert_not_called()

    def test_analysis_attempt_flushes_settings_before_board_validation(self):
        frame = self.frame()
        self.edit(frame.setting_controls['ambient_c'], 28.)
        frame.verified = Mock(return_value=False)
        frame.analyze()
        frame.verified.assert_called_once()
        self.assertEqual(load_calculation_settings(self.path)['ambient_c'], 28.)
        frame.start_worker.assert_not_called()

    def test_translated_settings_fit_the_sidebar_after_pre_show_language_change(self):
        frame = self.frame()
        frame.SetSize((1500, 1050))
        frame.language_choice.SetSelection(1)
        frame.change_language()
        frame.sidebar_notebook.SetSelection(1)
        frame.Show()
        wx.Yield()
        page = frame.setting_controls['fr4_k'].GetParent()
        width = page.GetClientSize().width
        self.assertGreater(width, 250)
        for key, control in frame.setting_controls.items():
            self.assertLessEqual(control.GetRect().right, width, key)
        self.assertLessEqual(frame.material_hint.GetBestSize().width, width)


if __name__ == '__main__':
    unittest.main()
