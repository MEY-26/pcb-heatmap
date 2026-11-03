"""Read-only visual terminal records attached to an in-memory analysis mesh.

These are numerical contacts, not KiCad pads. Nothing in this module reads or
writes native PCB objects or files. A point is never snapped to nearby copper:
the clicked cell must contain its selected net on its selected layer.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
from numbers import Integral, Real

try:
    from .model import AnalysisError, Pad
except ImportError:
    from model import AnalysisError, Pad


def _record_list(records):
    if isinstance(records, Mapping):
        records = list(records.values())
    if not isinstance(records, (list, tuple)):
        raise AnalysisError('Visual contacts must be a list of point records.')
    return records


def _known_pad_ids(pads):
    if isinstance(pads, Mapping):
        return set(pads)
    return {pad.get('identifier') for pad in pads if isinstance(pad, Mapping)}


def _known_nets(info):
    if 'nets' in info:
        nets = info['nets']
        if isinstance(nets, Mapping):
            return {name for name in nets if isinstance(name, str) and name}
        if not isinstance(nets, (list, tuple, set)):
            raise AnalysisError('Board net information is invalid.')
        result = set()
        for item in nets:
            name = item.get('name') if isinstance(item, Mapping) else item
            if isinstance(name, str) and name:
                result.add(name)
        return result
    pads = info.get('pads', [])
    pads = pads.values() if isinstance(pads, Mapping) else pads
    result = set()
    for pad in pads:
        net = pad.get('net') if isinstance(pad, Mapping) else getattr(pad, 'net', '')
        if isinstance(net, str) and net:
            result.add(net)
    return result


def _coordinate(value, key):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise AnalysisError(f'Visual contact {key} must be a finite number in millimetres.')
    return float(value)


def validate_contacts(records, info):
    """Return new normalized records keyed by ID; leave caller data untouched.

    ``info`` is the saved-board inspection dictionary. Empty net names are
    accepted for heat-only points. Electrical source/load validation must still
    require a named net when constructing the scenario.
    """
    if not isinstance(info, Mapping):
        raise AnalysisError('Board information is missing for visual contacts.')
    layers = info.get('layers', [])
    if not isinstance(layers, (list, tuple)) or not layers:
        raise AnalysisError('Board copper layers are missing for visual contacts.')
    pad_ids = _known_pad_ids(info.get('pads', []))
    known_nets = _known_nets(info)
    result = {}
    required = {'identifier', 'net', 'layer', 'x_mm', 'y_mm'}
    for record in _record_list(records):
        if not isinstance(record, Mapping) or not required.issubset(record):
            raise AnalysisError('A visual contact requires identifier, net, layer, x_mm and y_mm.')
        identifier = record['identifier']
        if not isinstance(identifier, str) or not identifier.startswith('point:') or not identifier[6:].strip():
            raise AnalysisError('A visual contact identifier must start with point: and have a unique suffix.')
        if identifier in result or identifier in pad_ids:
            raise AnalysisError(f'Duplicate visual contact identifier {identifier!r}.')
        net = record['net']
        if not isinstance(net, str) or (net and net not in known_nets):
            raise AnalysisError(f'Visual contact {identifier!r} refers to an unknown net {net!r}.')
        layer = record['layer']
        if isinstance(layer, bool) or not isinstance(layer, Integral) or not 0 <= layer < len(layers):
            raise AnalysisError(f'Visual contact {identifier!r} has an invalid copper layer index.')
        result[identifier] = {
            'identifier': identifier, 'net': net, 'layer': int(layer),
            'x_mm': _coordinate(record['x_mm'], 'x_mm'),
            'y_mm': _coordinate(record['y_mm'], 'y_mm'),
        }
    return result


def attach_contacts(raster, records):
    """Attach validated point contacts to ``raster`` only and return new records.

    All checks finish before changing the in-memory pad collections, so one bad
    point cannot leave a partially attached scenario. A contact occupies exactly
    one cell of one layer. Fine features must be resolved rather than bridged or
    moved to a different layer/net to make a scenario solve.
    """
    info = {'layers': raster.layers, 'pads': raster.pads,
            'nets': set(raster.net_copper) | {pad.net for pad in raster.pads.values()}}
    normalized = validate_contacts(records, info)
    if not math.isfinite(raster.cell_mm) or raster.cell_mm <= 0:
        raise AnalysisError('Visual contacts require a positive, finite mesh cell size.')
    if not math.isfinite(raster.origin_x_mm) or not math.isfinite(raster.origin_y_mm):
        raise AnalysisError('Visual contacts require a finite mesh origin.')
    prepared = []
    for record in normalized.values():
        layer, x, y = record['layer'], record['x_mm'], record['y_mm']
        row = math.floor((y - raster.origin_y_mm) / raster.cell_mm)
        column = math.floor((x - raster.origin_x_mm) / raster.cell_mm)
        height, width = raster.board_mask.shape
        if not (0 <= row < height and 0 <= column < width) or not raster.board_mask[row, column]:
            raise AnalysisError(f'Visual contact at X {x:g}, Y {y:g} mm is outside the board or in a cutout.')
        net = record['net']
        if net:
            coverage = raster.net_copper.get(net)
            cell = (layer, row, column)
            if coverage is None or not math.isfinite(float(coverage[cell])) or coverage[cell] <= 0:
                raise AnalysisError(
                    f'Visual contact at X {x:g}, Y {y:g} mm has no resolved copper '
                    f'on {raster.layers[layer].name} for net {net!r}. '
                    'Refine the grid or choose copper on this layer; contacts are not snapped.')
        label = f'X {x:.3f} mm, Y {y:.3f} mm ({raster.layers[layer].name})'
        pad = Pad(record['identifier'], label, net, x, y, (layer,))
        prepared.append((pad, [(layer, row, column)]))
    for pad, cells in prepared:
        raster.pads[pad.identifier] = pad
        raster.pad_cells[pad.identifier] = cells
    if prepared:
        warning = ('Visual point contacts are ideal terminals over one mesh cell '
                   f'({raster.cell_mm:g} mm); local current density and temperature '
                   'near each contact depend on mesh resolution and contact area.')
        if warning not in raster.warnings:
            raster.warnings.append(warning)
    return normalized
