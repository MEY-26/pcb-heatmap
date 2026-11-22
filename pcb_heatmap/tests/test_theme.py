"""Palette resolution: colour parsing, KiCad themes, desktop accent, contrast."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from pcb_heatmap import theme


class ColorParsingTests(unittest.TestCase):
    def test_accepted_spellings(self):
        self.assertEqual(theme.rgb_tuple('#0a1b2c'), (10, 27, 44))
        self.assertEqual(theme.rgb_tuple('#abc'), (170, 187, 204))
        self.assertEqual(theme.rgb_tuple('rgb(200, 52, 52)'), (200, 52, 52))
        self.assertEqual(theme.rgb_tuple('rgba(2, 255, 238, 0.4)'), (2, 255, 238))
        self.assertEqual(theme.rgb_tuple('rgb(50% 0% 100%)'), (128, 0, 255))
        self.assertIsNone(theme.rgb_tuple('chartreuse'))
        self.assertIsNone(theme.rgb_tuple(None))
        self.assertEqual(theme.hex_color('rgb(1,2,3)'), '#010203')
        self.assertEqual(theme.hex_color('nope', '#123456'), '#123456')

    def test_blend_and_luminance(self):
        self.assertEqual(theme.blend('#000000', '#ffffff', 0.5), '#808080')
        self.assertEqual(theme.blend('#000000', '#ffffff', 5), '#ffffff')
        self.assertLess(theme.luminance('#000000'), theme.luminance('#ffffff'))
        self.assertTrue(theme.is_dark('#101010'))
        self.assertFalse(theme.is_dark('#fafafa'))

    def test_readable_text_prefers_contrast(self):
        self.assertEqual(theme.readable_text('#000000'), '#ffffff')
        self.assertEqual(theme.readable_text('#ffffff'), '#101418')


class KiCadThemeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / 'colors').mkdir()

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, payload):
        (self.root / name).write_text(json.dumps(payload), encoding='utf-8')

    def test_active_theme_is_read_and_matched(self):
        self.write('pcbnew.json', {'appearance': {'color_theme': str(self.root / 'wdark.json')}})
        self.write('wdark.json', {
            'meta': {'name': 'wDark', 'filename': 'wdark'},
            'board': {
                'background': 'rgb(0, 16, 35)',
                'copper': {'f': 'rgb(200, 52, 52)', 'b': 'rgb(77, 127, 196)',
                            'in1': 'rgb(127, 200, 127)'},
                'f_silks': 'rgb(242, 237, 161)',
                'edge_cuts': 'rgb(208, 210, 205)',
                'pad_plated_hole': 'rgb(194, 194, 0)',
                'via_hole': 'rgb(227, 183, 46)',
                'grid': 'rgb(132, 132, 132)',
            },
        })
        colours, name = theme.read_kicad_theme([self.root])
        self.assertEqual(name, 'wDark')
        self.assertEqual(colours['canvas_bg'], '#001023')
        self.assertEqual(colours['copper'], ('#c83434', '#4d7fc4', '#7fc87f'))
        self.assertEqual(colours['silk'], '#f2eda1')
        self.assertEqual(colours['edge'], '#d0d2cd')
        self.assertEqual(colours['canvas_grid'], '#848484')

    def test_user_overrides_are_merged_over_the_theme(self):
        self.write('pcbnew.json', {'appearance': {'color_theme': 'custom.json'}})
        self.write('colors/custom.json', {'meta': {'name': 'Custom base'},
                                          'board': {'background': 'rgb(0,0,0)',
                                                    'copper': {'f': 'rgb(255,0,0)'}}})
        self.write('colors/user.json', {'board': {'background': 'rgb(9, 9, 9)'}})
        colours, name = theme.read_kicad_theme([self.root])
        self.assertEqual(name, 'Custom base')
        self.assertEqual(colours['canvas_bg'], '#090909')

    def test_relative_theme_names_resolve_under_the_colors_folder(self):
        self.write('pcbnew.json', {'appearance': {'color_theme': 'mine.json'}})
        self.write('colors/mine.json', {'meta': {'name': 'Mine'},
                                        'board': {'background': 'rgb(1, 2, 3)'}})
        colours, name = theme.read_kicad_theme([self.root])
        self.assertEqual(name, 'Mine')
        self.assertEqual(colours['canvas_bg'], '#010203')

    def test_builtin_default_and_damaged_themes_degrade(self):
        self.write('pcbnew.json', {'appearance': {'color_theme': '_builtin_default'}})
        self.assertEqual(theme.read_kicad_theme([self.root]), ({}, 'KiCad default'))
        self.write('pcbnew.json', {'appearance': {'color_theme': str(self.root / 'missing.json')}})
        self.assertEqual(theme.read_kicad_theme([self.root]), ({}, 'KiCad default'))
        (self.root / 'broken.json').write_text('{oops', encoding='utf-8')
        self.write('pcbnew.json', {'appearance': {'color_theme': str(self.root / 'broken.json')}})
        self.assertEqual(theme.read_kicad_theme([self.root]), ({}, 'KiCad default'))
        self.assertEqual(theme.read_kicad_theme([self.root / 'absent']), ({}, 'KiCad default'))

    def test_desktop_accent_is_read_from_kdeglobals(self):
        (self.root / 'kdeglobals').write_text(
            '[Colors:Selection]\nBackgroundNormal=134,88,161\n\n'
            '[General]\nAccentColor=184,117,220\n', encoding='utf-8')
        self.assertEqual(theme.read_kde_accent([self.root]), '#b875dc')
        (self.root / 'kdeglobals').write_text('[Colors:Window]\n', encoding='utf-8')
        self.assertIsNone(theme.read_kde_accent([self.root]))
        self.assertIsNone(theme.read_kde_accent([self.root / 'missing']))


class PaletteCompositionTests(unittest.TestCase):
    kicad = {'canvas_bg': '#001023', 'copper': ('#c83434', '#4d7fc4'),
             'silk': '#f2eda1', 'via_hole': '#e3b72e', 'canvas_grid': '#848484'}

    def test_dark_palette_uses_accent_and_kicad_canvas(self):
        palette = theme.load_palette('dark', accent='#b875dc', kicad=self.kicad,
                                     theme_name='wDark')
        self.assertTrue(palette.dark)
        self.assertEqual(palette.accent, '#b875dc')
        self.assertEqual(palette.accent_text, '#ffffff')
        self.assertEqual(palette.canvas_bg, '#001023')
        self.assertEqual(palette.layer_color(1), '#4d7fc4')
        self.assertEqual(palette.layer_color(7), '#4d7fc4')
        self.assertEqual(palette.marker_color('source'), palette.source)
        self.assertEqual(palette.marker_color('A'), palette.load)
        self.assertIn('wDark', palette.name)
        self.assertNotEqual(palette.panel, '#ffffff')
        self.assertLess(theme.luminance(palette.bg), 0.2)
        self.assertGreater(theme.luminance(palette.text), 0.7)

    def test_light_palette_is_light_everywhere_it_matters(self):
        palette = theme.load_palette('light', accent='#b875dc', kicad=self.kicad)
        self.assertFalse(palette.dark)
        self.assertGreater(theme.luminance(palette.panel), 0.9)
        self.assertLess(theme.luminance(palette.text), 0.2)
        self.assertEqual(palette.canvas_bg, '#001023')

    def test_auto_mode_honours_an_explicit_signal(self):
        self.assertTrue(theme.load_palette('auto', dark=True, accent='#b875dc').dark)
        self.assertFalse(theme.load_palette('auto', dark=False, accent='#b875dc').dark)
        self.assertTrue(theme.load_palette('nonsense', dark=True).dark)

    def test_empty_theme_still_yields_a_complete_palette(self):
        palette = theme.load_palette('dark', accent=None, kicad={}, theme_name='')
        self.assertEqual(palette.canvas_bg, theme.FALLBACK_CANVAS)
        self.assertTrue(palette.copper)
        self.assertTrue(palette.layer_color(0).startswith('#'))
        self.assertTrue(palette.surface('header').startswith('#'))
        self.assertTrue(palette.surface('card').startswith('#'))
        self.assertEqual(palette.ramp, 'rainbow')
