"""Versioned interface state: defaults, validation, atomic persistence."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pcb_heatmap import ui_state


class UiStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'ui-state.json'

    def tearDown(self):
        self.directory.cleanup()

    def test_missing_file_returns_defaults(self):
        self.assertEqual(ui_state.load_ui_state(self.path), ui_state.DEFAULTS)

    def test_corrupt_or_wrong_version_falls_back(self):
        self.path.write_text('{not json', encoding='utf-8')
        self.assertEqual(ui_state.load_ui_state(self.path), ui_state.DEFAULTS)
        self.path.write_text(json.dumps({'version': 99, 'appearance': 'dark'}), encoding='utf-8')
        self.assertEqual(ui_state.load_ui_state(self.path), ui_state.DEFAULTS)
        self.path.write_text(json.dumps([1, 2, 3]), encoding='utf-8')
        self.assertEqual(ui_state.load_ui_state(self.path), ui_state.DEFAULTS)

    def test_round_trip_keeps_valid_fields(self):
        state = dict(ui_state.DEFAULTS, appearance='dark', section='results',
                     splitter=420, opacity=80, ramp='viridis', width=1600, height=1000)
        self.assertTrue(ui_state.save_ui_state(state, self.path))
        loaded = ui_state.load_ui_state(self.path)
        for key in ('appearance', 'section', 'splitter', 'opacity', 'ramp', 'width', 'height'):
            self.assertEqual(loaded[key], state[key])

    def test_invalid_values_are_clamped_or_rejected(self):
        self.assertTrue(ui_state.save_ui_state({
            'version': 1, 'appearance': 'sepia', 'section': 'nope', 'ramp': 'neon',
            'splitter': 5, 'opacity': 400, 'width': 10, 'height': 90000}, self.path))
        loaded = ui_state.load_ui_state(self.path)
        self.assertEqual(loaded['appearance'], 'auto')
        self.assertEqual(loaded['section'], 'inputs')
        self.assertEqual(loaded['ramp'], 'rainbow')
        self.assertEqual(loaded['splitter'], 260)
        self.assertEqual(loaded['opacity'], 95)
        self.assertEqual(loaded['width'], 1024)
        self.assertEqual(loaded['height'], 8000)
        loaded = ui_state.validate_ui_state({'splitter': '460', 'opacity': True,
                                             'width': 1500.5})
        self.assertEqual(loaded['splitter'], ui_state.DEFAULTS['splitter'])
        self.assertEqual(loaded['opacity'], ui_state.DEFAULTS['opacity'])
        self.assertEqual(loaded['width'], ui_state.DEFAULTS['width'])

    def test_save_is_atomic_and_leaves_no_temporary_file(self):
        self.assertTrue(ui_state.save_ui_state(dict(ui_state.DEFAULTS), self.path))
        leftovers = [path.name for path in self.path.parent.iterdir()
                     if path.name.startswith('.ui-state-')]
        self.assertEqual(leftovers, [])
        document = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(document['version'], ui_state.UI_STATE_VERSION)

    def test_unwritable_location_reports_failure_instead_of_raising(self):
        blocker = Path(self.directory.name) / 'blocked'
        blocker.write_text('', encoding='utf-8')
        self.assertFalse(ui_state.save_ui_state(dict(ui_state.DEFAULTS), blocker / 'ui-state.json'))
