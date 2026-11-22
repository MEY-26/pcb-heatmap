"""Raster coverage from board polygons, without importing pcbnew.

The sampling is the same 4×4 area / shared-face approximation used by the
extractor, but the scanline fill is vectorised: crossings for a block of sample
rows are computed at once, intervals are accumulated into a difference array and
one cumulative sum fills the block.  This replaces one Python call per scanline
(100k calls on a dense board) with a handful of NumPy operations per polygon.
"""
from __future__ import annotations

import math

import numpy as np

from .model import AnalysisError

SAMPLES = 4

#: Rows processed per NumPy block, bounding the (rows × edges) working array.
ROW_BLOCK = 48


def _edges(contours):
    starts = np.concatenate(contours)
    ends = np.concatenate([np.roll(contour, -1, axis=0) for contour in contours])
    return starts, ends


def _fill_block(target, first_row, x0, y0, dx, dy, starts, ends):
    """Mark covered sample columns in ``target`` for its own block of rows."""
    rows = np.arange(first_row, first_row + target.shape[0])
    sample_y = y0 + rows * dy
    ax, ay = starts[:, 0], starts[:, 1]
    bx, by = ends[:, 0], ends[:, 1]
    crossing = ((ay[None, :] <= sample_y[:, None]) & (by[None, :] > sample_y[:, None])) | \
               ((by[None, :] <= sample_y[:, None]) & (ay[None, :] > sample_y[:, None]))
    slope = np.divide(bx - ax, by - ay, out=np.zeros_like(bx), where=(by - ay) != 0)
    xs = np.where(crossing, ax[None, :] + (sample_y[:, None] - ay[None, :]) * slope[None, :],
                  np.inf)
    xs.sort(axis=1)
    counts = crossing.sum(axis=1)
    pairs = xs.shape[1] // 2
    if pairs == 0:
        return
    left = xs[:, 0:2 * pairs:2]
    right = xs[:, 1:2 * pairs:2]
    valid = np.arange(pairs)[None, :] < ((counts[:, None] + 1) // 2)
    left = np.where(valid, left, x0)
    right = np.where(valid, right, x0)
    start = np.ceil((left - x0) / dx).astype(np.int64)
    stop = np.ceil((right - x0) / dx).astype(np.int64)
    np.clip(start, 0, target.shape[1], out=start)
    np.clip(stop, 0, target.shape[1], out=stop)
    valid &= stop > start
    if not valid.any():
        return
    diff = np.zeros((target.shape[0], target.shape[1] + 1), dtype=np.int32)
    row_index, pair_index = np.nonzero(valid)
    np.add.at(diff, (row_index, start[row_index, pair_index]), 1)
    np.add.at(diff, (row_index, stop[row_index, pair_index]), -1)
    target |= np.cumsum(diff[:, :target.shape[1]], axis=1) > 0


def sample_polygons(polygons, origin, cell, h, w, axis='area', collision_check=False):
    """Area coverage and physical shared-face coverage via polygon scanlines.

    Separate native islands in one selected-net cell are refused: the network
    cannot honestly represent two independent potentials in a single cell.
    """
    s = SAMPLES
    if axis == 'area':
        sh, sw = h * s, w * s
        x0, y0, dx, dy = origin[0] + cell / (2 * s), origin[1] + cell / (2 * s), cell / s, cell / s
    elif axis == 'x':
        sh, sw = h * s, max(0, w - 1)
        x0, y0, dx, dy = origin[0] + cell, origin[1] + cell / (2 * s), cell, cell / s
    else:
        # Horizontal faces via transposed geometry, keeping one raster routine.
        swapped = [[contour[:, ::-1] for contour in island] for island in polygons]
        return sample_polygons(swapped, origin[::-1], cell, w, h, axis='x').T

    hi = np.zeros((sh, sw), dtype=np.bool_)
    owners = np.zeros((h, w), np.int32) if collision_check else None
    for island, contours in enumerate(polygons, 1):
        contours = [np.asarray(contour, dtype=np.float64) for contour in contours
                    if len(contour) >= 3]
        if not contours:
            continue
        starts, ends = _edges(contours)
        ymin = float(min(contour[:, 1].min() for contour in contours))
        ymax = float(max(contour[:, 1].max() for contour in contours))
        first = max(0, int(math.ceil((ymin - y0) / dy)))
        last = min(sh, int(math.ceil((ymax - y0) / dy)))
        if last <= first:
            continue
        island_hit = np.zeros((last - first, sw), dtype=np.bool_)
        for block in range(first, last, ROW_BLOCK):
            size = min(ROW_BLOCK, last - block)
            _fill_block(island_hit[block - first:block - first + size], block,
                        x0, y0, dx, dy, starts, ends)
        hi[first:last] |= island_hit
        if owners is not None:
            rows, column = np.nonzero(island_hit)
            if len(rows):
                pairs = np.unique(np.stack([(rows + first) // s, column // s], axis=1), axis=0)
                rr, cc = pairs[:, 0], pairs[:, 1]
                if np.any(owners[rr, cc] != 0):
                    raise AnalysisError('The mesh combines disconnected copper islands on the same net. '
                                        'Choose a smaller cell size; no artificial electrical bridge was created.')
                owners[rr, cc] = island
    if axis == 'area':
        return hi.reshape(h, s, w, s).mean(axis=(1, 3)).astype(np.float32)
    return hi.reshape(h, s, sw).mean(axis=1).astype(np.float32)
