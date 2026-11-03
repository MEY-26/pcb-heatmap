"""User calculation preferences survive sessions without saving PCB data."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pcb_heatmap.preferences import (
    MAX_PREFERENCES_BYTES, calculation_settings_path, load_calculation_settings,
    save_calculation_settings, validate_calculation_settings,
)


class CalculationPreferencesTests(unittest.TestCase):
    def test_roundtrip_values_and_material_without_electrical_assignments(self):
        settings = dict(ambient_c=32, convection_top=0, convection_bottom=30,
                        via_plating_um=35, cell_mm=.05, fr4_k=170,
                        copper_k=390, max_temperature_c=105, max_delta_v=.2,
                        node_budget=700000, substrate_material='metal_core',
                        substrate_k_z=1.2,
                        sources=[{'voltage_v': 33.6}], current_a=80,
                        board_path='live.kicad_pcb', language='tr')
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'nested' / 'preferences.json'
            self.assertTrue(save_calculation_settings(settings, target))
            loaded = load_calculation_settings(target)
            self.assertEqual(loaded, {key: value for key, value in settings.items()
                                     if key not in ('sources', 'current_a', 'board_path', 'language')})
            document = json.loads(target.read_text(encoding='utf8'))
            self.assertEqual(document['version'], 1)
            self.assertEqual(document['settings'], loaded)
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_alias_preserves_existing_fr4_contract(self):
        self.assertEqual(validate_calculation_settings({'dielectric_k': 20}), {'fr4_k': 20.0})
        self.assertEqual(validate_calculation_settings({'dielectric_k': 20, 'fr4_k': .6}), {'fr4_k': .6})

    def test_bounds_finite_values_and_types_are_checked(self):
        self.assertEqual(validate_calculation_settings(dict(
            ambient_c=True, convection_top=-1, convection_bottom=float('nan'),
            cell_mm='0.25', via_plating_um=float('inf'), fr4_k=0,
            copper_k=99, max_delta_v=101, max_temperature_c=401,
            node_budget=10000.5, substrate_material='../../project',
            substrate_k_z=-1)), {})
        self.assertEqual(validate_calculation_settings({'fr4_k': 10**1000}), {})
        self.assertEqual(validate_calculation_settings({'node_budget': 2000000}),
                         {'node_budget': 2000000})
        self.assertEqual(validate_calculation_settings([]), {})

    def test_isotropic_none_and_known_materials_survive_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'settings.json'
            self.assertTrue(save_calculation_settings(dict(
                fr4_k=.3, substrate_k_z=None, substrate_material='custom'), target))
            self.assertEqual(load_calculation_settings(target), dict(
                fr4_k=.3, substrate_k_z=None, substrate_material='custom'))
        for material in ('custom', 'fr4', 'ceramic', 'metal_core'):
            self.assertEqual(validate_calculation_settings({'substrate_material': material}),
                             {'substrate_material': material})
        self.assertEqual(validate_calculation_settings({'substrate_material': 'aluminum'}), {})
        self.assertEqual(validate_calculation_settings({'fr4_k': 1000, 'substrate_k_z': .01}),
                         {'fr4_k': 1000., 'substrate_k_z': .01})

    def test_missing_malformed_or_other_version_keeps_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'settings.json'
            self.assertEqual(load_calculation_settings(target), {})
            for content in (b'{', b'\xff', b'[]', b'null',
                            b'{"version":2,"settings":{"ambient_c":30}}',
                            b'{"version":true,"settings":{"ambient_c":30}}',
                            b'{"version":1,"settings":[]}',
                            b' ' * (MAX_PREFERENCES_BYTES + 1)):
                with self.subTest(content=content[:80]):
                    target.write_bytes(content)
                    self.assertEqual(load_calculation_settings(target), {})

    def test_invalid_individual_value_does_not_discard_other_preferences(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'settings.json'
            target.write_text('{"version":1,"settings":{"ambient_c":30,"fr4_k":NaN}}', encoding='utf8')
            self.assertEqual(load_calculation_settings(target), {'ambient_c': 30.0})

    def test_failed_atomic_replace_preserves_old_preferences(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'settings.json'
            self.assertTrue(save_calculation_settings({'ambient_c': 27}, target))
            original = target.read_bytes()
            with patch('pcb_heatmap.preferences.os.replace', side_effect=PermissionError('locked')):
                self.assertFalse(save_calculation_settings({'ambient_c': 40}, target))
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_unavailable_directory_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as temp:
            blocker = Path(temp) / 'not-a-folder'
            blocker.write_text('existing user file', encoding='utf8')
            self.assertFalse(save_calculation_settings({'ambient_c': 30}, blocker / 'settings.json'))
            self.assertEqual(blocker.read_text(encoding='utf8'), 'existing user file')

    def test_platform_configuration_path_is_separate_from_board_files(self):
        with patch.dict(os.environ, {'APPDATA': 'C:/user/config'}):
            self.assertEqual(calculation_settings_path(),
                             Path('C:/user/config/kicad/pcb_heatmap/calculation-settings.json'))
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': '/user/config'}, clear=True):
            self.assertEqual(calculation_settings_path(),
                             Path('/user/config/kicad/pcb_heatmap/calculation-settings.json'))


if __name__ == '__main__':
    unittest.main()
