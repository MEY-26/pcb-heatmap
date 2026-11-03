"""Electrical assignments require explicit values and board-independent help."""
from dataclasses import asdict
import unittest

from pcb_heatmap.i18n import TEXT
from pcb_heatmap.model import Load, Source


class GenericInputsTests(unittest.TestCase):
    def test_new_source_requires_explicit_voltage(self):
        with self.assertRaises(TypeError):
            Source(['input'])
        self.assertEqual(asdict(Source(['input'], 0)),
                         {'pad_ids': ['input'], 'voltage_v': 0})
        self.assertEqual(Source(['input'], -2.5).voltage_v, -2.5)

    def test_new_load_requires_explicit_current(self):
        with self.assertRaises(TypeError):
            Load(['output'])
        self.assertEqual(asdict(Load(['output'], .25)),
                         {'pad_ids': ['output'], 'current_a': .25})
        self.assertEqual(Load(['return'], -.25).current_a, -.25)

    def test_help_has_no_board_specific_values_or_examples(self):
        text = '\n'.join(value for pair in TEXT.values() for value in pair).casefold()
        for literal in ('33.6', '33,6', '80 a', '8s', 'vbat', 'mosfet', 'battery', 'batarya'):
            with self.subTest(literal=literal):
                self.assertNotIn(literal, text)
        self.assertIn('new value fields are empty', TEXT['usage_text'][0].lower())
        self.assertIn('yeni değer alanları boştur', TEXT['usage_text'][1].lower())


if __name__ == '__main__':
    unittest.main()
