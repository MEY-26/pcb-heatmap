"""Read-only KiCad 10 copper extraction for the PCB Heatmap prototype.

All coordinates come from native, already transformed PCB geometry.  This module
never saves, refills, or changes a board.  Four-by-four area sampling is an
explicit numerical approximation, not a manufacturing or FEM certification.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
import numpy as np
import pcbnew as p

from .model import AnalysisError, Layer, Pad, RasterBoard, Via

_SAMPLES = 4
_IU = 1_000_000.0


def _parse(text):
    """Small data-only s-expression parser; does not evaluate board contents."""
    tokens = re.finditer(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+', text)
    stack, root = [], None
    for match in tokens:
        token = match.group()
        if token == '(':
            node = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
            if root is None:
                root = node
        elif token == ')':
            if not stack:
                raise AnalysisError('Invalid KiCad file: unmatched closing parenthesis.')
            stack.pop()
        else:
            if token.startswith('"'):
                token = re.sub(r'\\([\\"])', r'\1', token[1:-1])
            if not stack:
                raise AnalysisError('Invalid KiCad file.')
            stack[-1].append(token)
    if stack or not root or root[0] != 'kicad_pcb':
        raise AnalysisError('Not a complete .kicad_pcb file.')
    return root


def _child(node, key):
    return next((x for x in node if isinstance(x, list) and x and x[0] == key), None)


def _number(node, key, default=None):
    found = _child(node or [], key)
    return float(found[1]) if found and len(found) > 1 else default


def _read_stackup(path, board):
    tree = _parse(Path(path).read_text(encoding='utf-8-sig'))
    native_ids = list(board.GetEnabledLayers().CuStack())
    names = [board.GetLayerName(i) for i in native_ids]
    general = _child(tree, 'general')
    nominal = _number(general, 'thickness', 1.6)
    setup = _child(tree, 'setup')
    stack = _child(setup or [], 'stackup')
    copper = []
    z = 0.0
    warnings = []
    if stack:
        for item in stack[1:]:
            if not isinstance(item, list) or not item or item[0] != 'layer':
                continue
            name = item[1]
            if name in names:
                thickness = _number(item, 'thickness')
                if thickness is None or thickness <= 0:
                    raise AnalysisError(f'Missing copper thickness in stackup: {name}.')
                copper.append(Layer(name, thickness, z + thickness / 2))
                z += thickness
            elif str(name).lower().startswith('dielectric '):
                # KiCad can store multiple dielectric sublayers within one item.
                thicknesses = [float(c[1]) for c in item[2:] if isinstance(c, list)
                               and c and c[0] == 'thickness']
                if not thicknesses or any(t <= 0 for t in thicknesses):
                    raise AnalysisError(f'Missing dielectric thickness: {name}.')
                z += sum(thicknesses)
        if [x.name for x in copper] != names:
            raise AnalysisError('Physical stackup does not match the enabled copper-layer order.')
        # Mask is excluded from the FR4/copper heat-conduction slab.
        if abs(z - nominal) > max(.05, nominal * .05):
            warnings.append(f'Copper/dielectric stackup is {z:.4g} mm; nominal board thickness '
                            f'is {nominal:.4g} mm. The physical stackup is used.')
    else:
        # Inspect may still be useful, but analysis must not invent foil thickness.
        warnings.append('No explicit physical stackup. Set copper and dielectric thicknesses in Board Setup.')
        copper = [Layer(name, 0.0, nominal * (i + .5) / len(names)) for i, name in enumerate(names)]
        z = nominal
    return native_ids, copper, z, warnings


def _uuid(item):
    return item.m_Uuid.AsString()


def _zone_status(board):
    issues = []
    for zone in _all_zones(board):
        if zone.GetIsRuleArea():
            continue
        if not any(zone.IsOnLayer(i) for i in board.GetEnabledLayers().CuStack()):
            continue
        if zone.NeedRefill() or not zone.IsFilled():
            issues.append(f'Zone {_uuid(zone)} ({zone.GetNetname() or "no net"}) is unfilled or requires refill.')
    return issues


def _all_zones(board):
    return list(board.Zones()) + [z for fp in board.GetFootprints() for z in fp.Zones()]


def _load(path):
    path = Path(path).resolve()
    if path.suffix.lower() != '.kicad_pcb' or not path.is_file():
        raise AnalysisError('Choose an existing saved .kicad_pcb file.')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    board = p.LoadBoard(str(path))
    if board is None:
        raise AnalysisError('KiCad could not open the saved PCB.')
    board.BuildConnectivity()
    ids, layers, thickness, warnings = _read_stackup(path, board)
    warnings += _zone_status(board)
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    if before != after:
        raise AnalysisError('The PCB changed while reading. Save it and retry.')
    return path, before, board, ids, layers, thickness, warnings


def inspect_board(board_path):
    path, sha, board, ids, layers, thickness, warnings = _load(board_path)
    pad_list = []
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            physical_layers = [k for k, i in enumerate(ids) if pad.IsOnLayer(i) and pad.FlashLayer(i)
                               and pad.GetAttribute() != p.PAD_ATTRIB_NPTH]
            if not physical_layers:
                continue
            pos = pad.GetPosition()
            pad_list.append(dict(identifier=_uuid(pad), label=f'{footprint.GetReference()}.{pad.GetNumber()}',
                                 net=str(pad.GetNetname()), x_mm=pos.x / _IU, y_mm=pos.y / _IU,
                                 layers=physical_layers, reference=str(footprint.GetReference()),
                                 footprint=str(footprint.GetFPID().GetLibItemName()),
                                 description=str(footprint.GetLibDescription())))
    items = list(board.GetTracks())
    copper_zones = [zone for zone in _all_zones(board) if not zone.GetIsRuleArea()
                    and any(zone.IsOnLayer(i) for i in ids)]
    return dict(board_path=str(path), sha256=sha,
                layers=[dict(name=l.name, thickness_mm=l.thickness_mm, z_mm=l.z_mm) for l in layers],
                pads=pad_list, warnings=warnings, board_thickness_mm=thickness,
                nets=sorted(str(name) for name in board.GetNetsByName() if str(name)),
                stats=dict(footprints=len(list(board.GetFootprints())), pads=len(pad_list),
                           tracks=sum(not isinstance(t, p.PCB_VIA) for t in items),
                           vias=sum(isinstance(t, p.PCB_VIA) for t in items),
                           copper_zones=len(copper_zones),
                           filled_copper_zones=sum(zone.IsFilled() and not zone.NeedRefill()
                                                   for zone in copper_zones)))


def _polygon(item, layer, error):
    poly = p.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(poly, layer, 0, error, p.ERROR_INSIDE)
    return poly


def _circle(x, y, radius, error):
    # Native SHAPE_CIRCLE gives KiCad's polygon approximation in board units.
    poly = p.SHAPE_POLY_SET()
    p.SHAPE_CIRCLE(p.VECTOR2I(round(x), round(y)), round(radius)).TransformToPolygon(poly, error, p.ERROR_INSIDE)
    return poly


def _poly_arrays(poly):
    polygons = []
    for i in range(poly.OutlineCount()):
        contour_list = [poly.Outline(i)] + [poly.Hole(i, h) for h in range(poly.HoleCount(i))]
        contours = []
        for chain in contour_list:
            a = np.array([(chain.CPoint(j).x / _IU, chain.CPoint(j).y / _IU)
                          for j in range(chain.PointCount())], dtype=np.float64)
            if len(a) >= 3:
                contours.append(a)
        if contours:
            polygons.append(contours)
    return polygons


def _scanline_intervals(edges, y):
    a, b = edges
    crossing = ((a[:, 1] <= y) & (b[:, 1] > y)) | ((b[:, 1] <= y) & (a[:, 1] > y))
    aa, bb = a[crossing], b[crossing]
    xs = aa[:, 0] + (y-aa[:, 1])*(bb[:, 0]-aa[:, 0])/(bb[:, 1]-aa[:, 1])
    xs.sort()
    return zip(xs[::2], xs[1::2])


def _sample_polygons(polygons, origin, cell, h, w, axis='area', collision_check=False):
    """Area coverage and physical shared-face coverage via polygon scanlines.

    Separate native islands in one selected-net cell are refused: the network
    cannot honestly represent two independent potentials in a single cell.
    """
    s = _SAMPLES
    # Sample centers never lie on a cell boundary. For face grids x/y below,
    # one coordinate is the exact boundary shared by adjacent physical cells.
    if axis == 'area':
        sh, sw = h * s, w * s
        x0, y0, dx, dy = origin[0] + cell / (2*s), origin[1] + cell / (2*s), cell/s, cell/s
    elif axis == 'x':
        sh, sw = h * s, max(0, w-1)
        x0, y0, dx, dy = origin[0] + cell, origin[1] + cell / (2*s), cell, cell/s
    else:
        # Horizontal faces via transposed geometry, keeping one scanline routine.
        swapped = [[a[:, ::-1] for a in cont] for cont in polygons]
        return _sample_polygons(swapped, origin[::-1], cell, w, h, axis='x').T
    hi = np.zeros((sh, sw), dtype=np.bool_)
    owners = np.zeros((h, w), np.int32) if collision_check else None
    for island, contours in enumerate(polygons, 1):
        edges=(np.concatenate(contours), np.concatenate([np.roll(a,-1,axis=0) for a in contours]))
        ymin = min(a[:, 1].min() for a in contours)
        ymax = max(a[:, 1].max() for a in contours)
        r0 = max(0, int(math.ceil((ymin-y0)/dy)))
        r1 = min(sh, int(math.ceil((ymax-y0)/dy)))
        touched = set() if owners is not None else None
        for row in range(r0, r1):
            for left, right in _scanline_intervals(edges, y0+row*dy):
                start = max(0, int(math.ceil((left-x0)/dx)))
                stop = min(sw, int(math.ceil((right-x0)/dx)))
                if stop > start:
                    hi[row, start:stop] = True
                    if touched is not None:
                        touched.update((row//s, c) for c in range(start//s, (stop-1)//s+1))
        if touched:
            rr, cc = np.array(list(touched), dtype=int).T
            if np.any(owners[rr, cc] != 0):
                raise AnalysisError('The mesh combines disconnected copper islands on the same net. '
                                    'Choose a smaller cell size; no artificial electrical bridge was created.')
            owners[rr, cc] = island
    if axis == 'area':
        return hi.reshape(h, s, w, s).mean(axis=(1, 3)).astype(np.float32)
    return hi.reshape(h, s, sw).mean(axis=1).astype(np.float32)


def rasterize(board_path, net_names, cell_mm=.25, via_plating_um=25.0,
              progress=None, cancel=None, max_cells=500000):
    def tick(message, fraction):
        if cancel and cancel():
            raise AnalysisError('Analysis cancelled.')
        if progress:
            progress(message, fraction)

    if not math.isfinite(cell_mm) or not .01 <= cell_mm <= 5:
        raise AnalysisError('Cell size must be between 0.01 and 5 mm.')
    if not math.isfinite(via_plating_um) or not 1 <= via_plating_um <= 200:
        raise AnalysisError('Via plating must be between 1 and 200 micrometres.')
    tick('Reading native PCB geometry', 0)
    path, sha, board, ids, layers, thickness, warnings = _load(board_path)
    if any(l.thickness_mm <= 0 for l in layers):
        raise AnalysisError('Set an explicit physical stackup before thermal analysis.')
    stale = _zone_status(board)
    if stale:
        raise AnalysisError('Refill copper zones in KiCad, save, then retry. ' + stale[0])
    selected = set(net_names)
    known = {str(name) for name in board.GetNetsByName() if str(name)}
    if selected-known:
        raise AnalysisError('Select existing, nonempty PCB net names.')
    if '' in selected:
        raise AnalysisError('Unassigned pads cannot define an electrical network.')
    outline = p.SHAPE_POLY_SET()
    # InferOutline=False prevents silently using a bounding rectangle as board.
    if not board.GetBoardPolygonOutlines(outline, False, None, False, True) or outline.IsEmpty():
        raise AnalysisError('Board Edge.Cuts must be closed; no board outline was inferred.')
    if outline.OutlineCount() != 1:
        raise AnalysisError('Multiple disconnected board outlines are not supported; analyse one PCB at a time.')
    box = outline.BBox()
    ox = math.floor((box.GetX()/_IU)/cell_mm)*cell_mm
    oy = math.floor((box.GetY()/_IU)/cell_mm)*cell_mm
    w = max(1, math.ceil((box.GetRight()/_IU-ox)/cell_mm))
    h = max(1, math.ceil((box.GetBottom()/_IU-oy)/cell_mm))
    physical_cells = h*w*len(ids)
    if physical_cells > max_cells:
        raise AnalysisError(f'Mesh needs {physical_cells:,} layer cells; limit is {max_cells:,}. '
                            'Choose a larger cell size. Resolution was not changed automatically.')
    origin = (ox, oy)
    board_coverage = _sample_polygons(_poly_arrays(outline), origin, cell_mm, h, w)
    board_mask = board_coverage > 0
    # Native curve approximation much finer than raster samples, minimum 1 um.
    error = max(1000, round(cell_mm*_IU/40))
    all_polys = [p.SHAPE_POLY_SET() for _ in ids]
    net_polys = {net: [p.SHAPE_POLY_SET() for _ in ids] for net in selected}
    pads, pad_polys, vias, via_polys = {}, {}, [], []
    holes = [p.SHAPE_POLY_SET() for _ in ids]
    hole_records = []
    track_min = float('inf')

    def add(poly, k, net):
        if poly.IsEmpty():
            return
        # Append cheaply, then one native union per layer. Repeated union of
        # thousands of overlapping tracks/vias is unnecessarily quadratic.
        all_polys[k].Append(poly)
        if net in selected:
            net_polys[net][k].Append(poly)

    for fp in board.GetFootprints():
        tick('Extracting physical pads and holes', .05)
        for pad in fp.Pads():
            hole = pad.GetEffectiveHoleShape()
            if hole and pad.GetDrillSize().x > 0:
                ph = p.SHAPE_POLY_SET()
                hole.TransformToPolygon(ph, error, p.ERROR_INSIDE)
                for layer_holes in holes:
                    layer_holes.Append(ph)
                hole_records.append((ph,tuple(range(len(ids)))))
            if pad.GetAttribute() == p.PAD_ATTRIB_NPTH:
                continue
            ks = tuple(k for k, i in enumerate(ids) if pad.IsOnLayer(i) and pad.FlashLayer(i))
            if not ks:
                continue
            pos, identifier = pad.GetPosition(), _uuid(pad)
            net = pad.GetNetname()
            pads[identifier] = Pad(identifier, f'{fp.GetReference()}.{pad.GetNumber()}', net,
                                   pos.x/_IU, pos.y/_IU, ks)
            pp = {}
            for k in ks:
                poly = _polygon(pad, ids[k], error)
                add(poly, k, net)
                pp[k] = poly
            pad_polys[identifier] = pp
            if pad.GetAttribute() == p.PAD_ATTRIB_PTH and pad.GetDrillSize().x > 0:
                drill = pad.GetDrillSize()
                # Circular barrels only: oblong slots need a perimeter model.
                if drill.x != drill.y:
                    warnings.append(f'{pads[identifier].label}: plated slot barrel omitted; circular vias remain supported.')
                elif len(ks) > 1:
                    size = pad.GetSize()
                    vias.append(Via(pos.x/_IU, pos.y/_IU, drill.x/_IU, min(size.x, size.y)/_IU,
                                    0, len(ids)-1, net, via_plating_um, identifier))
                    via_polys.append(pp)
    for item in board.GetTracks():
        tick('Extracting tracks, arcs and vias', .15)
        net = item.GetNetname()
        if isinstance(item, p.PCB_VIA):
            span = [k for k, i in enumerate(ids) if item.IsOnLayer(i)]
            if not span:
                continue
            # TopLayer/BottomLayer must be real enabled copper layers.
            if item.TopLayer() not in ids or item.BottomLayer() not in ids:
                raise AnalysisError(f'Via {_uuid(item)} has an unsupported layer span.')
            start, end = sorted((ids.index(item.TopLayer()), ids.index(item.BottomLayer())))
            pos = item.GetPosition()
            drill = item.GetDrillValue()
            hole_poly = _circle(pos.x, pos.y, drill/2, error)
            for k in range(start, end+1):
                holes[k].Append(hole_poly)
            hole_records.append((hole_poly,tuple(range(start,end+1))))
            pp = {}
            for k in range(start, end+1):
                if not item.FlashLayer(ids[k]):
                    continue
                # Per-layer annular diameter is respected (KiCad padstack).
                poly = _circle(pos.x, pos.y, item.GetWidth(ids[k])/2, error)
                add(poly, k, net)
                pp[k] = poly
            vias.append(Via(pos.x/_IU, pos.y/_IU, drill/_IU, item.GetWidth(ids[start])/_IU,
                            start, end, net, via_plating_um, _uuid(item)))
            via_polys.append(pp)
        else:
            if item.GetLayer() in ids:
                k = ids.index(item.GetLayer())
                track_min = min(track_min, item.GetWidth()/_IU)
                add(_polygon(item, ids[k], error), k, net)
    # Graphic copper belongs to the thermal slab even when electrically unassigned.
    graphics=list(board.GetDrawings())
    for fp in board.GetFootprints():
        graphics.extend(fp.GraphicalItems())
        graphics.extend(field for field in fp.GetFields() if field.IsVisible())
    for item in graphics:
        if item.GetLayer() in ids and hasattr(item, 'TransformShapeToPolygon'):
            add(_polygon(item, item.GetLayer(), error), ids.index(item.GetLayer()),
                item.GetNetname() if hasattr(item, 'GetNetname') else '')
    for zone in _all_zones(board):
        if zone.GetIsRuleArea():
            continue
        for k, layer in enumerate(ids):
            if zone.IsOnLayer(layer) and zone.HasFilledPolysForLayer(layer):
                add(zone.GetFilledPolysList(layer), k, zone.GetNetname())
    if track_min < cell_mm:
        warnings.append(f'Smallest track {track_min:.4g} mm is narrower than mesh {cell_mm:.4g} mm. '
                        'Area/face sampling approximates it; compare against a finer mesh.')
    warnings.append('Saved filled zones are used verbatim. Save after KiCad refill; external stale edits '
                    'cannot always be detected from file flags.')
    warnings.append('Native curves are polygonized and foil areas use 4×4 subcell sampling. '
                    'Clearance slots and fine thermal spokes need mesh convergence checks.')
    copper = np.zeros((len(ids), h, w), np.float32)
    nets = {net: np.zeros_like(copper) for net in selected}
    copper_edges = dict(x=np.zeros((len(ids), h, max(0,w-1)), np.float32),
                        y=np.zeros((len(ids), max(0,h-1), w), np.float32))
    net_edges = {net: {key: np.zeros_like(value) for key, value in copper_edges.items()} for net in selected}
    for k in range(len(ids)):
        tick(f'Rasterizing {layers[k].name}', .25+.60*k/len(ids))
        holes[k].Simplify()
        all_polys[k].Simplify()
        all_polys[k].BooleanSubtract(holes[k])
        all_polys[k].BooleanIntersection(outline)
        arrays = _poly_arrays(all_polys[k])
        copper[k] = _sample_polygons(arrays, origin, cell_mm, h, w)
        for axis in ('x', 'y'):
            copper_edges[axis][k] = _sample_polygons(arrays, origin, cell_mm, h, w, axis)
        for net in selected:
            poly = net_polys[net][k]
            poly.Simplify()
            poly.BooleanSubtract(holes[k])
            poly.BooleanIntersection(outline)
            arrays = _poly_arrays(poly)
            try:
                nets[net][k] = _sample_polygons(arrays, origin, cell_mm, h, w, collision_check=True)
            except AnalysisError as exc:
                raise AnalysisError(f'{layers[k].name} / {net}: {exc}',
                                    code=exc.code, details={**exc.details, 'layer': layers[k].name, 'net': net}) from exc
            for axis in ('x', 'y'):
                net_edges[net][axis][k] = _sample_polygons(arrays, origin, cell_mm, h, w, axis)
    # A source/load contact must intersect actual pad copper; no nearest-pad relocation.
    # Local drill indexing avoids clipping every tiny via against thousands of
    # holes on a dense power PCB. The resulting hole subtraction is identical.
    hole_bounds=[]
    for hp,span in hole_records:
        hb=hp.BBox()
        hole_bounds.append((hb.GetX(),hb.GetY(),hb.GetRight(),hb.GetBottom()))
    hole_bounds=np.asarray(hole_bounds,dtype=float).reshape((-1,4))
    def contact_cells(original, k, net=None):
        poly = p.SHAPE_POLY_SET(original)
        ob=original.BBox()
        nearby=np.nonzero((hole_bounds[:,0]<=ob.GetRight()) & (hole_bounds[:,2]>=ob.GetX()) &
                          (hole_bounds[:,1]<=ob.GetBottom()) & (hole_bounds[:,3]>=ob.GetY()))[0]
        local_holes=p.SHAPE_POLY_SET()
        for j in nearby:
            hp,span=hole_records[j]
            if k in span:
                local_holes.Append(hp)
        if not local_holes.IsEmpty():
            local_holes.Simplify()
            poly.BooleanSubtract(local_holes)
        poly.BooleanIntersection(outline)
        if poly.IsEmpty():
            return []
        bounds = poly.BBox()
        c0=max(0, math.floor((bounds.GetX()/_IU-ox)/cell_mm))
        r0=max(0, math.floor((bounds.GetY()/_IU-oy)/cell_mm))
        c1=min(w, math.ceil((bounds.GetRight()/_IU-ox)/cell_mm))
        r1=min(h, math.ceil((bounds.GetBottom()/_IU-oy)/cell_mm))
        if r1<=r0 or c1<=c0:
            return []
        area = _sample_polygons(_poly_arrays(poly), (ox+c0*cell_mm,oy+r0*cell_mm),
                                cell_mm, r1-r0,c1-c0)
        occupied=area>0
        if net is not None:
            occupied &= nets[net][k,r0:r1,c0:c1]>0
        rr, cc = np.nonzero(occupied)
        return [(int(r)+r0,int(c)+c0) for r,c in zip(rr,cc)]

    tick('Resolving physical pad and via contacts', .9)
    pad_cells = {}
    for identifier, pad in pads.items():
        cells = []
        for k, original in pad_polys[identifier].items():
            # Component heaters also need actual pad areas when their net is
            # not selected for an electrical solve. Do not create a fictitious
            # electrical network merely to place a thermal boundary condition.
            cells.extend((k,r,c) for r,c in contact_cells(
                original,k,pad.net if pad.net in selected else None))
        pad_cells[identifier] = cells
        if not cells and pad.net in selected:
            raise AnalysisError(f'{pad.label}: no physical copper contact resolves at this mesh. '
                                'Choose a smaller cell size; the terminal was not moved.')
    via_cells = []
    for via, pp in zip(vias, via_polys):
        contacts = {}
        for k, original in pp.items():
            contacts[k] = contact_cells(original,k,via.net if via.net in selected else None)
        via_cells.append(contacts)
        if via.net in selected and any(not c for c in contacts.values()):
            raise AnalysisError(f'Via {via.identifier}: annular copper does not resolve on its layer span. '
                                'Choose a finer mesh.')
    tick('Geometry ready', 1.0)
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise AnalysisError('The PCB changed during extraction. Save and retry.')
    return RasterBoard(ox, oy, cell_mm, board_mask, copper, nets, layers, vias, pads, pad_cells,
                       warnings, dict(board_path=str(path), sha256=sha, board_thickness_mm=thickness,
                                      physical_cells=physical_cells, board_coverage=board_coverage,
                                      net_edges=net_edges, copper_edges=copper_edges, via_cells=via_cells,
                                      sampling=4, native_version=p.GetBuildVersion()))
