"""Read-only native vector geometry for the interactive PCB canvas.

This is a view of the saved PCB, not the numerical mesh.  Filled-zone polygons
are exported verbatim, including their holes and thermal-relief cutouts.  No
board Save/Fill or live-editor operation is performed here.
"""
from __future__ import annotations

import hashlib

import pcbnew as p

from .extractor import _IU, _all_zones, _load, _poly_arrays, _polygon, _uuid
from .model import AnalysisError


def _arrays(poly):
    """Keep the nested polygon/outer-and-hole-contour structure JSON safe."""
    return [[contour.tolist() for contour in polygon] for polygon in _poly_arrays(poly)]


def _box_mm(box):
    return [box.GetX() / _IU, box.GetY() / _IU,
            box.GetRight() / _IU, box.GetBottom() / _IU]


def export_layout(board_path, progress=None):
    """Return a JSON-serializable, absolute-mm snapshot of all PCB copper.

    Copper-layer indices follow the physical front-to-back stackup.  Silkscreen
    belongs to the corresponding outer copper-layer entry for view filtering.
    Electrical pads remain explicit selectable items; tracks/zones are separate
    visual items and never cause a selection to expand automatically.
    """
    def tick(message, fraction):
        if progress:
            progress(message, fraction)

    tick('Reading saved PCB for the interactive view', 0.0)
    path, sha, board, ids, layers, thickness, warnings = _load(board_path)
    error = 10000  # 0.01 mm native curve approximation, independent of mesh size.
    native_outline = p.SHAPE_POLY_SET()
    valid_outline = board.GetBoardPolygonOutlines(native_outline, False, None, False, True)
    outline = _arrays(native_outline) if valid_outline else []
    if outline:
        bounds = _box_mm(native_outline.BBox())
    else:
        bounds = _box_mm(board.ComputeBoundingBox(False))
        warnings.append('Closed Edge.Cuts outline unavailable; the view uses the PCB item bounds. '
                        'Thermal analysis still requires a closed board outline.')

    copper = [[] for _ in ids]
    drawings = [[] for _ in ids]
    pads, vias, footprints, holes = [], [], [], []
    nets = set()
    items = list(board.GetTracks())
    native_footprints = list(board.GetFootprints())
    silk_layers = {p.F_SilkS: 0, p.B_SilkS: len(ids) - 1}

    for n, fp in enumerate(native_footprints):
        tick('Preparing selectable pads and footprints', .05 + .25 * n / max(1, len(native_footprints)))
        pos = fp.GetPosition()
        reference = str(fp.GetReference())
        footprints.append(dict(reference=reference, value=str(fp.GetValue()),
                               x_mm=pos.x / _IU, y_mm=pos.y / _IU,
                               angle_deg=fp.GetOrientationDegrees(),
                               layer_index=len(ids) - 1 if fp.IsFlipped() else 0,
                               box_mm=_box_mm(fp.GetBoundingBox(False, False))))
        for pad in fp.Pads():
            hole_poly = p.SHAPE_POLY_SET()
            if pad.GetDrillSize().x > 0:
                hole = pad.GetEffectiveHoleShape()
                if hole:
                    hole.TransformToPolygon(hole_poly, error, p.ERROR_INSIDE)
                    holes.extend(_arrays(hole_poly))
            if pad.GetAttribute() == p.PAD_ATTRIB_NPTH:
                continue
            ks = [k for k, layer in enumerate(ids) if pad.IsOnLayer(layer) and pad.FlashLayer(layer)]
            if not ks:
                continue
            polygons = {}
            for k in ks:
                poly = _polygon(pad, ids[k], error)
                if not hole_poly.IsEmpty():
                    poly.BooleanSubtract(hole_poly)
                polygons[str(k)] = _arrays(poly)
            padpos = pad.GetPosition()
            net = str(pad.GetNetname())
            if net:
                nets.add(net)
            pads.append(dict(identifier=str(_uuid(pad)), label=f'{reference}.{pad.GetNumber()}',
                             number=str(pad.GetNumber()), net=net, reference=reference,
                             footprint=str(fp.GetFPID().GetLibItemName()),
                             description=str(fp.GetLibDescription()),
                             x_mm=padpos.x / _IU, y_mm=padpos.y / _IU, layers=ks,
                             polygons_by_layer=polygons,
                             hole_polygons=[] if hole_poly.IsEmpty() else _arrays(hole_poly)))

    for n, item in enumerate(items):
        if n % 100 == 0:
            tick('Preparing tracks and vias', .3 + .25 * n / max(1, len(items)))
        net = str(item.GetNetname())
        if net:
            nets.add(net)
        if isinstance(item, p.PCB_VIA):
            ks = [k for k, layer in enumerate(ids) if item.IsOnLayer(layer)]
            if not ks:
                continue
            pos = item.GetPosition()
            flashed = [k for k in ks if item.FlashLayer(ids[k])]
            widths = {str(k): item.GetWidth(ids[k]) / _IU for k in flashed}
            vias.append(dict(identifier=str(_uuid(item)), net=net,
                             x_mm=pos.x / _IU, y_mm=pos.y / _IU,
                             diameter_mm=max(widths.values()) if widths else item.GetWidth() / _IU,
                             drill_mm=item.GetDrillValue() / _IU, layers=ks,
                             flashed_layers=flashed, diameters_by_layer=widths))
        elif item.GetLayer() in ids:
            k = ids.index(item.GetLayer())
            polygons = _arrays(_polygon(item, item.GetLayer(), error))
            if polygons:
                copper[k].append(dict(net=net, kind='track', identifier=str(_uuid(item)), polygons=polygons))

    copper_zones = [z for z in _all_zones(board) if not z.GetIsRuleArea()
                    and any(z.IsOnLayer(layer) for layer in ids)]
    filled_zones = 0
    for n, zone in enumerate(copper_zones):
        tick('Preparing saved filled copper zones', .55 + .25 * n / max(1, len(copper_zones)))
        net = str(zone.GetNetname())
        if net:
            nets.add(net)
        if zone.IsFilled() and not zone.NeedRefill():
            filled_zones += 1
        for k, layer in enumerate(ids):
            if not zone.IsOnLayer(layer):
                continue
            polygons = (_arrays(zone.GetFilledPolysList(layer))
                        if zone.HasFilledPolysForLayer(layer) else [])
            kind = 'zone'
            if not polygons and not zone.IsFilled():
                polygons = _arrays(zone.Outline())
                kind = 'zone_outline'
            if polygons:
                copper[k].append(dict(net=net, kind=kind, identifier=str(_uuid(zone)), polygons=polygons))

    graphics = list(board.GetDrawings())
    for fp in native_footprints:
        graphics.extend(fp.GraphicalItems())
        # Reference labels are drawn legibly by the canvas, not duplicated in
        # native text polygons. Other visible silk fields retain their shape.
        graphics.extend(field for field in fp.GetFields()
                        if field.IsVisible() and field.GetName() != 'Reference')
    for n, item in enumerate(graphics):
        if n % 100 == 0:
            tick('Preparing PCB silkscreen', .8 + .15 * n / max(1, len(graphics)))
        layer = item.GetLayer()
        if layer not in silk_layers or not hasattr(item, 'TransformShapeToPolygon'):
            continue
        try:
            polygons = _arrays(_polygon(item, layer, error))
        except (TypeError, RuntimeError):
            warnings.append('A silkscreen graphic could not be polygonized; copper remains complete.')
            continue
        if polygons:
            drawings[silk_layers[layer]].append(dict(polygons=polygons, kind='silk'))

    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise AnalysisError('The PCB changed while preparing the view. Save it and retry.')
    tick('Interactive PCB view ready', 1.0)
    return dict(schema_version=1, board_path=str(path), sha256=sha, bounds_mm=bounds,
                outline=outline, layers=[dict(name=l.name, thickness_mm=l.thickness_mm, z_mm=l.z_mm)
                                         for l in layers],
                board_thickness_mm=thickness, pads=pads, copper_by_layer=copper,
                vias=vias, footprints=footprints, holes=holes, drawings_by_layer=drawings,
                warnings=list(dict.fromkeys(warnings)), nets=sorted(nets),
                stats=dict(footprints=len(footprints), pads=len(pads),
                           tracks=sum(not isinstance(t, p.PCB_VIA) for t in items),
                           vias=len(vias), copper_zones=len(copper_zones),
                           filled_copper_zones=filled_zones))
