"""Cheap terminal identity checks, independent of GUI and mesh resolution."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import conflicting_terminal_ids


class TerminalValidationTests(unittest.TestCase):
    def test_same_source_and_load_pad_is_rejected(self):
        self.assertEqual(conflicting_terminal_ids([
            dict(kind='source', pad_ids=['J8.2']),
            dict(kind='load', pad_ids=['J8.2'])]), {'J8.2'})

    def test_reverse_capture_order_is_also_rejected(self):
        self.assertEqual(conflicting_terminal_ids([
            dict(kind='load', pad_ids=['J8.2']),
            dict(kind='source', pad_ids=['J8.2'])]), {'J8.2'})

    def test_partial_group_overlap_is_rejected(self):
        self.assertEqual(conflicting_terminal_ids([
            dict(kind='source', pad_ids=['a', 'b']),
            dict(kind='load', pad_ids=['b', 'c'])]), {'b'})

    def test_different_contacts_and_optional_heat_are_allowed(self):
        self.assertFalse(conflicting_terminal_ids([
            dict(kind='source', pad_ids=['J8.2']),
            dict(kind='load', pad_ids=['U1.5', 'U1.6', 'U1.7', 'U1.8']),
            dict(kind='heat', pad_ids=['J8.2', 'U1.5'])]))


if __name__ == '__main__':
    unittest.main()
