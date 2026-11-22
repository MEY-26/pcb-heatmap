"""Per-user directory resolution: Windows conventions and XDG fallbacks."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcb_heatmap import paths


class DirectoryTests(unittest.TestCase):
    def test_xdg_variables_win_on_posix(self):
        with patch.dict(os.environ, dict(XDG_CONFIG_HOME='/tmp/cfg', XDG_STATE_HOME='/tmp/state',
                                        XDG_DATA_HOME='/tmp/data'), clear=False):
            self.assertEqual(paths.config_root(), Path('/tmp/cfg'))
            self.assertEqual(paths.state_root(), Path('/tmp/state'))
            self.assertEqual(paths.data_root(), Path('/tmp/data'))

    def test_posix_fallbacks_are_xdg_documented(self):
        environment = {key: '' for key in ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME')}
        with patch.dict(os.environ, environment, clear=False):
            self.assertEqual(paths.config_root(), paths.home() / '.config')
            self.assertEqual(paths.state_root(), paths.home() / '.local' / 'state')
            self.assertEqual(paths.data_root(), paths.home() / '.local' / 'share')

    def test_windows_uses_appdata_and_localappdata(self):
        with patch.object(paths, '_WINDOWS', True), \
                patch.dict(os.environ, dict(APPDATA='/win/roaming',
                                            LOCALAPPDATA='/win/local'), clear=False):
            self.assertEqual(paths.config_root(), Path('/win/roaming'))
            self.assertEqual(paths.state_root(), Path('/win/local'))
            self.assertEqual(paths.settings_directory(), Path('/win/roaming/kicad/pcb_heatmap'))

    def test_settings_and_runs_never_land_in_home_root(self):
        with patch.dict(os.environ, dict(XDG_CONFIG_HOME='/tmp/cfg', XDG_STATE_HOME='/tmp/state')):
            self.assertEqual(paths.calculation_settings_path(),
                             Path('/tmp/cfg/kicad/pcb_heatmap/calculation-settings.json'))
            self.assertEqual(paths.ui_state_path(),
                             Path('/tmp/cfg/kicad/pcb_heatmap/ui-state.json'))
            self.assertEqual(paths.runs_root(), Path('/tmp/state/pcb_heatmap/runs'))

    def test_new_run_directory_is_created_and_unique(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, dict(XDG_STATE_HOME=directory)):
            first = paths.new_run_directory(timestamp='20260101-120000')
            second = paths.new_run_directory(timestamp='20260101-120000')
            self.assertTrue(first.is_dir())
            self.assertTrue(second.is_dir())
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, Path(directory) / 'pcb_heatmap' / 'runs')

    def test_kicad_config_override_and_flatpak_candidate(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, dict(KICAD_CONFIG_HOME=directory)):
            candidates = paths.kicad_config_directories()
            self.assertEqual(candidates[0], Path(directory))
            self.assertEqual(candidates[1], Path(directory) / '10.0')
            self.assertIn(paths.home() / '.var' / 'app' / paths.FLATPAK_ID / 'config' / 'kicad' / '10.0',
                          candidates)
            self.assertEqual(len(candidates), len(set(candidates)))

