"""Scenario-list editing on real local wx controls, without reading a PCB."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import wx

os.environ['PCB_HEATMAP_HEADLESS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pcb_heatmap.visual_gui import VisualFrame


class EntryDialog:
    """An explicit user reply without showing or styling an OS dialog."""

    def __init__(self, value='', result=wx.ID_OK):
        self.value, self.result = value, result
        self.buttons = {wx.ID_OK: Mock(), wx.ID_CANCEL: Mock()}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def FindWindow(self, identifier):
        return self.buttons[identifier]

    def ShowModal(self):
        return self.result

    def GetValue(self):
        return self.value


def terminal(identifier, kind, *pad_ids, value=1):
    return dict(identifier=identifier, kind=kind, pad_ids=list(pad_ids), value=value)


class VisualEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.frame = VisualFrame()
        self.frame.error = Mock()
        self.frame.pad_by_id = {
            name: dict(identifier=name, label=name, net='POWER', layers=[0],
                       reference=name.split('.')[0], x_mm=index, y_mm=0)
            for index, name in enumerate(('J1.1', 'U1.1', 'U2.1', 'U3.1', 'U4.1'))
        }
        # Supply only selection metadata to the actual canvas. No worker or
        # native PCB object is created by these editing tests.
        self.frame.canvas._pad_by_id = dict(self.frame.pad_by_id)

    def tearDown(self):
        self.frame.process = None
        self.frame.Destroy()
        wx.Yield()

    def rows(self, *records):
        self.frame.rows = list(records)
        self.frame.refresh_rows()

    def select(self, *indices):
        for index in range(self.frame.terminals.GetItemCount()):
            self.frame.terminals.Select(index, False)
        for index in indices:
            self.frame.terminals.Select(index)

    def selected_identifiers(self):
        return [self.frame.rows[index]['identifier']
                for index in self.frame.selected_row_indices()]

    def point(self, identifier):
        record = dict(identifier=identifier, net='', layer=0, x_mm=1, y_mm=1)
        self.frame.point_contacts[identifier] = record
        self.frame.pad_by_id[identifier] = self.frame.point_metadata(record)
        return record

    def prompt(self, kind, reply='', result=wx.ID_OK, current=None):
        dialog = EntryDialog(reply, result)
        with patch('pcb_heatmap.visual_gui.LightTextEntryDialog', return_value=dialog) as factory, \
                patch('pcb_heatmap.visual_gui.apply_light_palette'):
            answer = self.frame.ask_value(kind, 'Synthetic contact', current)
        return answer, factory

    def test_native_list_accepts_several_rows_and_enumerates_them_in_order(self):
        self.rows(terminal('a', 'heat', 'U1.1'), terminal('b', 'heat', 'U2.1'),
                  terminal('c', 'heat', 'U3.1'), terminal('d', 'heat', 'U4.1'))
        self.assertFalse(self.frame.terminals._body.GetWindowStyle() & wx.LC_SINGLE_SEL)
        self.select(3, 0, 2)
        self.assertEqual(self.frame.selected_row_indices(), [0, 2, 3])

    def test_refresh_preserves_selected_row_identity_after_reordering_and_translation(self):
        self.rows(terminal('a', 'heat', 'U1.1'), terminal('b', 'heat', 'U2.1'),
                  terminal('c', 'heat', 'U3.1'), terminal('d', 'heat', 'U4.1'))
        self.select(1, 3)
        original = list(self.frame.rows)
        self.frame.rows = [original[3], original[0], original[2], original[1]]
        self.frame.refresh_rows()
        self.assertEqual(self.selected_identifiers(), ['d', 'b'])
        self.frame.language_choice.SetSelection(1)
        self.frame.change_language()
        self.assertEqual(self.selected_identifiers(), ['d', 'b'])
        self.frame.refresh_rows()
        self.assertEqual(self.selected_identifiers(), ['d', 'b'])

    def test_batch_remove_keeps_unselected_rows_and_only_prunes_orphan_points(self):
        shared = self.point('point:shared')
        orphan = self.point('point:orphan')
        kept = self.point('point:kept')
        self.rows(terminal('a', 'heat', 'point:shared', 'point:orphan'),
                  terminal('b', 'heat', 'point:shared', 'U1.1'),
                  terminal('c', 'load', 'U2.1'),
                  terminal('d', 'heat', 'point:kept'))
        self.select(0, 2)
        self.frame.remove_group()
        self.assertEqual([row['identifier'] for row in self.frame.rows], ['b', 'd'])
        self.assertEqual(set(self.frame.point_contacts), {'point:shared', 'point:kept'})
        self.assertIs(self.frame.point_contacts['point:shared'], shared)
        self.assertIs(self.frame.point_contacts['point:kept'], kept)
        self.assertNotIn(orphan['identifier'], self.frame.pad_by_id)
        self.assertIn('U2.1', self.frame.pad_by_id, 'Deleting a row must not remove native pad metadata.')
        self.assertEqual([m['identifier'] for m in self.frame.canvas.markers], ['b', 'd'])

    def test_same_kind_batch_value_applies_to_each_group_once(self):
        self.rows(terminal('a', 'heat', 'U1.1', value=2),
                  terminal('b', 'heat', 'U2.1', 'U3.1', value=3),
                  terminal('c', 'heat', 'U4.1', value=4))
        self.select(0, 1)
        before = copy.deepcopy(self.frame.rows)

        def user_reply(kind, label, current=None):
            self.assertEqual(kind, 'heat')
            self.assertEqual(self.frame.rows, before, 'Do not partially edit a batch before the reply.')
            return 7.25

        self.frame.ask_value = Mock(side_effect=user_reply)
        self.frame.edit_selected()
        self.frame.ask_value.assert_called_once()
        self.assertEqual([r['value'] for r in self.frame.rows], [7.25, 7.25, 4])
        self.assertEqual([r['pad_ids'] for r in self.frame.rows], [r['pad_ids'] for r in before])
        self.assertEqual(self.selected_identifiers(), ['a', 'b'])

    def test_mixed_kind_batch_is_rejected_without_prompt_or_changes(self):
        self.rows(terminal('a', 'source', 'J1.1', value=12),
                  terminal('b', 'load', 'U1.1', value=2))
        self.select(0, 1)
        before = copy.deepcopy(self.frame.rows)
        self.frame.ask_value = Mock(return_value=9)
        self.frame.edit_selected()
        self.frame.ask_value.assert_not_called()
        self.frame.error.assert_called_once()
        self.assertEqual(self.frame.rows, before)
        self.assertEqual(self.selected_identifiers(), ['a', 'b'])

    def test_cancelled_batch_keeps_values_and_selection(self):
        self.rows(terminal('a', 'load', 'U1.1', value=2),
                  terminal('b', 'load', 'U2.1', value=3))
        self.select(0, 1)
        before = copy.deepcopy(self.frame.rows)
        self.frame.ask_value = Mock(return_value=None)
        self.frame.edit_selected()
        self.assertEqual(self.frame.rows, before)
        self.assertEqual(self.selected_identifiers(), ['a', 'b'])

    def test_marker_activation_edits_only_that_marker_despite_list_multiselection(self):
        self.rows(terminal('a', 'heat', 'U1.1', value=1),
                  terminal('b', 'heat', 'U2.1', value=2),
                  terminal('c', 'heat', 'U3.1', value=3))
        self.select(0, 1)
        self.frame.ask_value = Mock(return_value=9)
        self.frame.marker_pick(dict(identifier='c'))
        self.frame.ask_value.assert_called_once()
        self.assertEqual(self.frame.ask_value.call_args.args[0], 'heat')
        self.assertIn('U3.1', self.frame.ask_value.call_args.args[1])
        self.assertEqual([r['value'] for r in self.frame.rows], [1, 2, 9])

    def test_running_analysis_blocks_edit_remove_and_clear_even_when_called_directly(self):
        self.point('point:heat')
        self.rows(terminal('a', 'heat', 'point:heat', value=2),
                  terminal('b', 'heat', 'U1.1', value=3))
        self.select(0, 1)
        before = copy.deepcopy((self.frame.rows, self.frame.point_contacts, self.frame.pad_by_id))
        self.frame.process = object()
        self.frame.ask_value = Mock(return_value=9)
        for action in (self.frame.edit_selected, self.frame.remove_group, self.frame.clear_groups,
                       lambda: self.frame.edit_row(0), lambda: self.frame.marker_pick('a')):
            action()
            self.assertEqual((self.frame.rows, self.frame.point_contacts, self.frame.pad_by_id), before)
        self.frame.ask_value.assert_not_called()

    def test_new_source_load_and_heat_dialogs_start_empty(self):
        for kind in ('source', 'load', 'heat'):
            with self.subTest(kind=kind):
                answer, factory = self.prompt(kind, result=wx.ID_CANCEL)
                self.assertIsNone(answer)
                self.assertEqual(factory.call_args.args[3], '')
        self.frame.error.assert_not_called()

    def test_editing_zero_volt_source_preserves_zero_in_prompt(self):
        answer, factory = self.prompt('source', reply='0', current=0)
        self.assertEqual(factory.call_args.args[3], '0')
        self.assertEqual(answer, 0)
        self.frame.error.assert_not_called()

    def test_blank_and_nonfinite_values_are_rejected_without_mutating_scenario(self):
        self.rows(terminal('a', 'load', 'U1.1', value=2))
        before = copy.deepcopy(self.frame.rows)
        for kind in ('source', 'load', 'heat'):
            for text in ('', '   ', 'NaN', 'inf', '-inf'):
                with self.subTest(kind=kind, reply=text):
                    self.frame.error.reset_mock()
                    answer, _ = self.prompt(kind, reply=text)
                    self.assertIsNone(answer)
                    self.frame.error.assert_called_once()
                    self.assertEqual(self.frame.rows, before)

    def test_locale_decimal_comma_and_signed_return_current_are_accepted(self):
        for kind, reply, expected in (('source', ' 12,75 ', 12.75),
                                      ('load', '-2,5', -2.5), ('heat', '0,125', .125)):
            with self.subTest(kind=kind):
                answer, _ = self.prompt(kind, reply=reply)
                self.assertEqual(answer, expected)
        self.frame.error.assert_not_called()


if __name__ == '__main__':
    unittest.main()
