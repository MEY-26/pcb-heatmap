"""Reusable raster cache: keys, round-trip, corruption and pruning."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from pcb_heatmap import cache
from pcb_heatmap.model import Layer, Pad, RasterBoard, Via


def make_board(seed=0, layers=2):
    shape = (layers, 4, 5)
    copper = np.zeros(shape, dtype=np.float32)
    copper[:, 1:3, 1:4] = 1.0
    net = {'N': copper.copy()}
    return RasterBoard(
        origin_x_mm=1.0, origin_y_mm=2.0, cell_mm=0.5,
        board_mask=np.ones((4, 5), bool), copper=copper, net_copper=net,
        layers=[Layer(f'L{i}', 0.035 + i * 0.01, 0.1 * (i + 1)) for i in range(layers)],
        vias=[Via(0.5, 1.0, 0.3, 0.6, 0, layers - 1, 'N', 25.0, f'V{seed}')],
        pads={'P1': Pad('P1', 'J1.1', 'N', 1.0, 2.0, (0,))},
        pad_cells={'P1': [(0, 1, 1), (0, 1, 2)]},
        warnings=['note'], metadata={
            'board_path': '/tmp/board.kicad_pcb', 'sha256': 'abc', 'board_thickness_mm': 1.6,
            'physical_cells': 12, 'sampling': 4, 'native_version': '10',
            'board_coverage': np.full((4, 5), 0.5, dtype=np.float32),
            'copper_edges': {'x': np.full(shape, 0.25, dtype=np.float32),
                             'y': np.full(shape, 0.75, dtype=np.float32)},
            'net_edges': {'N': {'x': np.full(shape, 0.1, dtype=np.float32)}},
            'via_cells': [{0: [(1, 1)]}],
        })


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'XDG_STATE_HOME': self.directory.name})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def test_key_is_stable_and_setting_sensitive(self):
        base = cache.cache_key('abc', 0.25, 500000, 25.0, {'B', 'A'})
        self.assertEqual(base, cache.cache_key('abc', 0.25, 500000, 25.0, ['A', 'B']))
        for changed in (dict(cell_mm=0.5), dict(max_cells=400000),
                        dict(via_plating_um=30.0), dict(nets={'A'}),
                        dict(sha256='def')):
            arguments = dict(sha256='abc', cell_mm=0.25, max_cells=500000,
                             via_plating_um=25.0, nets={'A', 'B'})
            arguments.update(changed)
            self.assertNotEqual(base, cache.cache_key(**arguments))

    def test_round_trip_preserves_arrays_and_metadata(self):
        board = make_board()
        key = cache.cache_key('abc', 0.5, 500000, 25.0, {'N'})
        self.assertIsNotNone(cache.store(key, board))
        restored = cache.fetch(key)
        self.assertIsNotNone(restored)
        np.testing.assert_array_equal(restored.copper, board.copper)
        np.testing.assert_array_equal(restored.net_copper['N'], board.net_copper['N'])
        np.testing.assert_array_equal(restored.metadata['board_coverage'],
                                      board.metadata['board_coverage'])
        np.testing.assert_array_equal(restored.metadata['net_edges']['N']['x'],
                                      board.metadata['net_edges']['N']['x'])
        self.assertEqual(restored.metadata['via_cells'], board.metadata['via_cells'])
        self.assertEqual(restored.pad_cells['P1'], [(0, 1, 1), (0, 1, 2)])
        self.assertEqual(restored.vias[0].net, 'N')
        self.assertEqual(restored.layers[1].name, 'L1')

    def test_corrupt_entries_are_discarded(self):
        key = cache.cache_key('abc', 0.5, 500000, 25.0, {'N'})
        cache.store(key, make_board())
        (cache.entry_path(key) / 'board.json').write_text('{oops', encoding='utf-8')
        self.assertIsNone(cache.fetch(key))
        self.assertFalse(cache.entry_path(key).exists())

    def test_missing_entry_is_a_miss(self):
        self.assertIsNone(cache.fetch('nonexistent-key'))

    def test_pruning_keeps_the_newest_entries(self):
        for index in range(4):
            board = make_board(seed=index)
            key = cache.cache_key(f'sha{index}', 0.5, 500000, 25.0, {'N'})
            cache.store(key, board)
            os.utime(cache.entry_path(key), (1000 + index, 1000 + index))
        cache.prune(max_entries=2)
        self.assertEqual(len(cache._entries()), 2)
        remaining = {entry.name for entry in cache._entries()}
        self.assertIn(cache.cache_key('sha3', 0.5, 500000, 25.0, {'N'}), remaining)

    def test_unwritable_cache_directory_is_not_fatal(self):
        with patch.object(cache, 'cache_directory', return_value=Path('/proc/nope')):
            key = cache.cache_key('abc', 0.5, 500000, 25.0, {'N'})
            self.assertIsNone(cache.store(key, make_board()))
            self.assertIsNone(cache.fetch(key))
