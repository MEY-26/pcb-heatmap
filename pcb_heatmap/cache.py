"""Reusable rasterised boards, keyed by board hash and meshing settings.

Rasterising the saved board is the largest single cost of an analysis (it reads
pcbnew geometry and samples polygons).  The result is only a function of the
board file and a handful of settings, so it is cached as JSON plus a compressed
NumPy archive rather than pickled: a tampered cache can at worst be ignored, and
it never executes code.

A missing, stale or damaged entry is treated as a cache miss; analyses never fail
because of the cache.  Entries are pruned by age and total size.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import time

import numpy as np

from . import paths
from .model import Layer, Pad, RasterBoard, Via

CACHE_VERSION = 1
MAX_ENTRIES = 8
MAX_BYTES = 512 * 1024 * 1024
ARRAYS = 'arrays.npz'
DESCRIPTOR = 'board.json'


def cache_directory():
    return paths.state_root() / 'pcb_heatmap' / 'cache'


def cache_key(sha256, cell_mm, max_cells, via_plating_um, nets):
    """Stable key for everything the raster depends on."""
    payload = json.dumps({'version': CACHE_VERSION, 'sha256': sha256,
                          'cell_mm': round(float(cell_mm), 6),
                          'max_cells': int(max_cells),
                          'via_plating_um': round(float(via_plating_um), 6),
                          'nets': sorted(nets)},
                         sort_keys=True)
    import hashlib
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]


def _archive(board):
    arrays = {'board_mask': np.asarray(board.board_mask),
              'copper': np.asarray(board.copper)}
    mapping = {}
    for index, (net, coverage) in enumerate(board.net_copper.items()):
        name = f'net_{index}'
        arrays[name] = np.asarray(coverage)
        mapping[net] = name
    metadata = dict(board.metadata)
    if 'via_cells' in metadata:
        # JSON object keys are strings; restore integer layer keys on read.
        metadata['via_cells'] = [{str(layer): [list(cell) for cell in cells]
                                  for layer, cells in contacts.items()}
                                 for contacts in metadata['via_cells']]
    if 'board_coverage' in metadata:
        arrays['board_coverage'] = np.asarray(metadata.pop('board_coverage'))
    edges = metadata.pop('copper_edges', None)
    if edges:
        metadata['copper_edges_axes'] = sorted(edges)
        for axis in metadata['copper_edges_axes']:
            arrays[f'copper_edges_{axis}'] = np.asarray(edges[axis])
    net_edges = metadata.pop('net_edges', None)
    if net_edges:
        index_map = {}
        for number, (net, per_axis) in enumerate(net_edges.items()):
            index_map[net] = {}
            for axis, grid in per_axis.items():
                name = f'net_edges_{number}_{axis}'
                arrays[name] = np.asarray(grid)
                index_map[net][axis] = name
        metadata['net_edges_index'] = index_map
    document = {
        'version': CACHE_VERSION,
        'origin_x_mm': board.origin_x_mm, 'origin_y_mm': board.origin_y_mm,
        'cell_mm': board.cell_mm,
        'layers': [{'name': layer.name, 'thickness_mm': layer.thickness_mm,
                    'z_mm': layer.z_mm} for layer in board.layers],
        'vias': [{'x_mm': via.x_mm, 'y_mm': via.y_mm, 'drill_mm': via.drill_mm,
                  'diameter_mm': via.diameter_mm, 'start_layer': via.start_layer,
                  'end_layer': via.end_layer, 'net': via.net,
                  'plating_um': via.plating_um, 'identifier': via.identifier}
                 for via in board.vias],
        'pads': {identifier: {'label': pad.label, 'net': pad.net, 'x_mm': pad.x_mm,
                              'y_mm': pad.y_mm, 'layers': list(pad.layers)}
                 for identifier, pad in board.pads.items()},
        'pad_cells': {identifier: [list(cell) for cell in cells]
                      for identifier, cells in board.pad_cells.items()},
        'warnings': list(board.warnings),
        'metadata': metadata,
        'nets': mapping,
    }
    return document, arrays


def save_board(board, directory):
    """Persist one raster; returns the entry path or ``None`` on failure."""
    directory = Path(directory)
    temporary = Path(tempfile.mkdtemp(prefix='.entry-', dir=directory.parent))
    try:
        document, arrays = _archive(board)
        np.savez_compressed(temporary / ARRAYS, **arrays)
        (temporary / DESCRIPTOR).write_text(json.dumps(document), encoding='utf-8')
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        os.replace(temporary, directory)
        return directory
    except (OSError, ValueError, TypeError):
        shutil.rmtree(temporary, ignore_errors=True)
        return None


def load_board(directory):
    """Rebuild a raster, or ``None`` when the entry is missing or unusable."""
    directory = Path(directory)
    try:
        document = json.loads((directory / DESCRIPTOR).read_text(encoding='utf-8'))
        if document.get('version') != CACHE_VERSION:
            return None
        with np.load(directory / ARRAYS, allow_pickle=False) as loaded:
            arrays = {name: np.array(loaded[name], copy=True) for name in loaded.files}
        nets = {net: arrays.pop(name) for net, name in document['nets'].items()}
        metadata = dict(document.get('metadata', {}))
        if 'via_cells' in metadata:
            metadata['via_cells'] = [{int(layer): [tuple(int(part) for part in cell)
                                                  for cell in cells]
                                      for layer, cells in contacts.items()}
                                     for contacts in metadata['via_cells']]
        if 'board_coverage' in arrays:
            metadata['board_coverage'] = arrays.pop('board_coverage')
        axes = metadata.pop('copper_edges_axes', [])
        if axes:
            metadata['copper_edges'] = {axis: arrays.pop(f'copper_edges_{axis}')
                                        for axis in axes}
        index_map = metadata.pop('net_edges_index', {})
        if index_map:
            metadata['net_edges'] = {net: {axis: arrays.pop(name)
                                           for axis, name in per_axis.items()}
                                     for net, per_axis in index_map.items()}
        pads = {identifier: Pad(identifier=identifier, label=value['label'],
                                net=value['net'], x_mm=float(value['x_mm']),
                                y_mm=float(value['y_mm']),
                                layers=tuple(int(layer) for layer in value['layers']))
                for identifier, value in document['pads'].items()}
        vias = [Via(x_mm=float(v['x_mm']), y_mm=float(v['y_mm']),
                    drill_mm=float(v['drill_mm']), diameter_mm=float(v['diameter_mm']),
                    start_layer=int(v['start_layer']), end_layer=int(v['end_layer']),
                    net=v['net'], plating_um=float(v['plating_um']),
                    identifier=v.get('identifier', ''))
                for v in document['vias']]
        return RasterBoard(
            origin_x_mm=float(document['origin_x_mm']),
            origin_y_mm=float(document['origin_y_mm']),
            cell_mm=float(document['cell_mm']),
            board_mask=arrays['board_mask'],
            copper=arrays['copper'],
            net_copper=nets,
            layers=[Layer(layer['name'], float(layer['thickness_mm']),
                          float(layer['z_mm'])) for layer in document['layers']],
            vias=vias, pads=pads,
            pad_cells={identifier: [tuple(int(part) for part in cell) for cell in cells]
                       for identifier, cells in document['pad_cells'].items()},
            warnings=list(document.get('warnings', [])),
            metadata=metadata,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError, EOFError):
        return None


def entry_path(key):
    return cache_directory() / key


def fetch(key):
    """Load a cached raster for ``key``, discarding damaged entries."""
    path = entry_path(key)
    if not path.is_dir():
        return None
    board = load_board(path)
    if board is None:
        shutil.rmtree(path, ignore_errors=True)
        return None
    try:
        os.utime(path, None)
    except OSError:
        pass
    return board


def store(key, board):
    """Save a raster, then prune old entries. Never raises."""
    directory = cache_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    path = entry_path(key)
    saved = save_board(board, path)
    prune()
    return saved


def _entries():
    directory = cache_directory()
    try:
        return [entry for entry in directory.iterdir() if entry.is_dir()
                and (entry / DESCRIPTOR).is_file()]
    except OSError:
        return []


def _size(entry):
    total = 0
    for name in (ARRAYS, DESCRIPTOR):
        try:
            total += (entry / name).stat().st_size
        except OSError:
            pass
    return total


def prune(max_entries=MAX_ENTRIES, max_bytes=MAX_BYTES):
    """Keep the most recently used entries within count and size budgets."""
    entries = sorted(_entries(), key=lambda entry: entry.stat().st_mtime, reverse=True)
    total = 0
    for index, entry in enumerate(entries):
        total += _size(entry)
        if index >= max_entries or total > max_bytes:
            shutil.rmtree(entry, ignore_errors=True)


def clear():
    for entry in _entries():
        shutil.rmtree(entry, ignore_errors=True)


def describe():
    entries = _entries()
    return {'entries': len(entries), 'bytes': sum(_size(entry) for entry in entries),
            'directory': str(cache_directory()), 'now': time.time()}
