"""Read-only, directly interactive PCB canvas.

The canvas consumes plain, already transformed geometry exported by the worker;
it never imports pcbnew or changes a board. All coordinates remain millimetres
in board coordinates, including sample points and heatmap pixels.
"""
from __future__ import annotations

import math
import uuid

import numpy as np
import wx


BACKGROUND = '#15202d'
BOARD = '#253c3c'
OUTLINE = '#a5b9c5'
LAYER_COLORS = ('#ef7373', '#71c28b', '#d49c5c', '#6ec5c8',
                '#bf94d5', '#cbcb69', '#7fa1eb', '#759df3')
KIND_COLORS = {'source': '#45dca3', 'load': '#ffb34c', 'heat': '#ff6c7d',
               'V': '#45dca3', 'A': '#ffb34c', 'W': '#ff6c7d'}


def _contours(polygon):
    """Accept the exporter contour representation, with a simple-ring fallback."""
    if not polygon:
        return []
    first = polygon[0]
    if first and isinstance(first[0], (int, float)):
        return [polygon]
    return polygon


def point_in_contour(x, y, contour):
    """Boundary-inclusive ray crossing, also used for precise copper picking."""
    if len(contour) < 3:
        return False
    inside = False
    ax, ay = contour[-1][:2]
    for point in contour:
        bx, by = point[:2]
        dx, dy = bx - ax, by - ay
        if abs(dx * (y - ay) - dy * (x - ax)) <= 1e-9 * max(1., abs(dx), abs(dy)):
            if min(ax, bx) - 1e-9 <= x <= max(ax, bx) + 1e-9 and min(ay, by) - 1e-9 <= y <= max(ay, by) + 1e-9:
                return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
        ax, ay = bx, by
    return inside


def point_in_polygons(x, y, polygons):
    """Union of polygons; contours within one polygon use even-odd holes."""
    for polygon in polygons or []:
        count = sum(point_in_contour(x, y, ring) for ring in _contours(polygon))
        if count % 2:
            return True
    return False


def _bbox(polygons):
    points = [p for poly in polygons or [] for ring in _contours(poly) for p in ring]
    if not points:
        return (0., 0., 0., 0.)
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def _near_box(x, y, box, margin=0.):
    return box[0] - margin <= x <= box[2] + margin and box[1] - margin <= y <= box[3] + margin


def _pen(color, width=1):
    # wx.Pen accepts integer logical-pixel widths on bundled wxPython.
    return wx.Pen(color, max(1, round(width)))


class BoardCanvas(wx.Panel):
    """PCB graphics, direct terminal picking, markers and result overlay."""

    def __init__(self, parent, on_pick=None, on_marker=None, language=lambda: 'en'):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self._heatmap_role = 'board'
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetOwnBackgroundColour(BACKGROUND)
        self.SetOwnForegroundColour('#e6eef5')
        self.layout = None
        self.layer = -1
        self.mode = 'select'
        self.on_pick = on_pick
        self.on_marker = on_marker
        self.language = language
        self.scale = 8.
        self.offset = [30., 30.]
        self.show_references = True
        self.show_pad_numbers = True
        self.show_drawings = True
        self.show_tracks = True
        self.show_zones = True
        self.show_vias = True
        self.preferred_net = ''
        self.selected = []
        self.markers = []
        self._pad_by_id = {}
        self._pad_boxes = {}
        self._pads_by_reference = {}
        self._copper = []
        self._bitmap = None
        self._cache_key = None
        self._revision = 0
        self._drag = None
        self._tooltip_text = ''
        self._overlay = None
        self._overlay_bitmap = None
        self._marker_hits = []
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_SIZE, self._size)
        self.Bind(wx.EVT_MOUSEWHEEL, self._wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self._click)
        self.Bind(wx.EVT_MIDDLE_DOWN, self._pan_start)
        self.Bind(wx.EVT_RIGHT_DOWN, self._pan_start)
        self.Bind(wx.EVT_MIDDLE_UP, self._pan_end)
        self.Bind(wx.EVT_RIGHT_UP, self._pan_end)
        self.Bind(wx.EVT_MOTION, self._motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._capture_lost)
        self.Bind(wx.EVT_LEFT_DCLICK, lambda event: self.fit_board())
        self.Bind(wx.EVT_KEY_DOWN, self._key)

    def _tr(self, english, turkish):
        return turkish if self.language() == 'tr' else english

    def set_layout(self, layout):
        self.layout = layout
        self.preferred_net = ''
        if layout is None:
            self._pad_by_id = {}
            self._pad_boxes = {}
            self._pads_by_reference = {}
            self._copper = []
            self.selected = []
            self._revision += 1
            self.clear_overlay()
            return
        self._pad_by_id = {str(p['identifier']): p for p in layout.get('pads', [])}
        self._pad_boxes = {pid: _bbox([poly for shapes in pad.get('polygons_by_layer', {}).values()
                                     for poly in shapes]) for pid, pad in self._pad_by_id.items()}
        self._pads_by_reference = {}
        for pid, pad in self._pad_by_id.items():
            self._pads_by_reference.setdefault(str(pad.get('reference', '')), []).append(pid)
        self._copper = []
        layers = layout.get('copper_by_layer', [])
        if isinstance(layers, dict):
            layers = [layers.get(str(i), layers.get(i, [])) for i in range(len(layout.get('layers', [])))]
        for index, items in enumerate(layers):
            # Coarse boxes only accelerate precise polygon tests; never select
            # by bounding box, which would incorrectly select holes or cutouts.
            self._copper.append([(item, _bbox(item.get('polygons', []))) for item in items])
        self.selected = []
        self._revision += 1
        self.clear_overlay()
        self.fit_board()

    def set_layer(self, index):
        self.layer = int(index)
        self.Refresh(False)

    def set_mode(self, mode):
        if mode not in ('select', 'source', 'load', 'heat'):
            raise ValueError('Unknown PCB picking mode: ' + str(mode))
        self.mode = mode
        self.SetCursor(wx.Cursor(wx.CURSOR_ARROW if mode == 'select' else wx.CURSOR_CROSS))
        self.Refresh(False)

    def get_selection(self):
        return list(self.selected)

    def set_selection(self, pad_ids):
        self.selected = list(dict.fromkeys(str(pid) for pid in pad_ids if str(pid) in self._pad_by_id))
        self.Refresh(False)

    def clear_selection(self):
        self.selected = []
        self.Refresh(False)

    def set_markers(self, markers):
        self.markers = list(markers)
        self.Refresh(False)

    def set_show_references(self, show):
        self.set_visibility(references=show)

    def set_visibility(self, **flags):
        """Change drawing aids only; the exported/numerical PCB stays intact."""
        allowed = ('references', 'pad_numbers', 'drawings', 'tracks', 'zones', 'vias')
        unknown = set(flags) - set(allowed)
        if unknown:
            raise ValueError('Unknown PCB visibility option: ' + ', '.join(sorted(unknown)))
        for key, value in flags.items():
            setattr(self, 'show_' + key, bool(value))
        self._cache_key = None
        self.Refresh(False)

    def get_visibility(self):
        return {key: bool(getattr(self, 'show_' + key))
                for key in ('references', 'pad_numbers', 'drawings', 'tracks', 'zones', 'vias')}

    def set_preferred_net(self, net):
        """Enable source-net pad grouping on a component body; empty disables it."""
        self.preferred_net = str(net or '')
        self.Refresh(False)

    def focus_reference(self, reference):
        if not self.layout:
            return False
        footprints = [fp for fp in self.layout.get('footprints', [])
                      if str(fp.get('reference', '')).casefold() == str(reference).casefold()]
        if not footprints:
            return False
        fp = footprints[0]
        box = fp.get('box_mm')
        if box and len(box) == 4:
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            w, h = self.GetClientSize()
            self.scale = max(self.scale, min(w / max(box[2] - box[0] + 8, 8), h / max(box[3] - box[1] + 8, 8)))
        else:
            cx, cy = fp.get('x_mm', 0), fp.get('y_mm', 0)
            w, h = self.GetClientSize()
        self.offset = [w / 2 - cx * self.scale, h / 2 - cy * self.scale]
        self.Refresh(False)
        return True

    def fit_board(self):
        if not self.layout:
            self.Refresh(False)
            return
        box = self.layout.get('bounds_mm') or _bbox(self.layout.get('outline', []))
        # Connector lands can extend beyond Edge.Cuts. Include their actual
        # copper extents so fitting the PCB never clips selectable terminals.
        boxes = [box] + [bounds for bounds in self._pad_boxes.values() if bounds]
        xmin, ymin = min(b[0] for b in boxes), min(b[1] for b in boxes)
        xmax, ymax = max(b[2] for b in boxes), max(b[3] for b in boxes)
        w, h = self.GetClientSize()
        w, h = max(w, 100), max(h, 100)
        self.scale = max(.05, min((w - 64) / max(xmax - xmin, .1), (h - 64) / max(ymax - ymin, .1)))
        self.offset = [(w - (xmax - xmin) * self.scale) / 2 - xmin * self.scale,
                       (h - (ymax - ymin) * self.scale) / 2 - ymin * self.scale]
        self.Refresh(False)

    def world_to_screen(self, x, y):
        return x * self.scale + self.offset[0], y * self.scale + self.offset[1]

    def screen_to_world(self, x, y):
        return (x - self.offset[0]) / self.scale, (y - self.offset[1]) / self.scale

    def zoom_at(self, screen_x, screen_y, multiplier):
        x, y = self.screen_to_world(screen_x, screen_y)
        self.scale = min(5000., max(.05, self.scale * multiplier))
        self.offset = [screen_x - x * self.scale, screen_y - y * self.scale]
        self.Refresh(False)

    def set_overlay(self, values2D, valid2D, units, origin, cell, scale=None, opacity=.65):
        values = np.asarray(values2D, dtype=float)
        valid = np.asarray(valid2D, dtype=bool) & np.isfinite(values)
        if values.ndim != 2 or valid.shape != values.shape:
            raise ValueError('Overlay values and validity must be equally sized 2D arrays.')
        if not math.isfinite(float(cell)) or float(cell) <= 0:
            raise ValueError('Heatmap cell size must be positive.')
        finite = values[valid]
        low, high = (tuple(float(v) for v in scale) if scale is not None else
                     (float(finite.min()), float(finite.max())) if finite.size else (0., 1.))
        stops = np.asarray([[22, 42, 88], [30, 104, 207], [26, 190, 205],
                            [86, 209, 116], [246, 224, 66], [245, 128, 32], [198, 34, 36]], dtype=float)
        normalized = np.clip((np.nan_to_num(values, nan=low) - low) / max(high - low, 1e-12), 0., 1.)
        positions = normalized * (len(stops) - 1)
        idx = np.minimum(positions.astype(int), len(stops) - 2)
        weight = (positions - idx)[..., None]
        rgb = np.ascontiguousarray(stops[idx] * (1 - weight) + stops[idx + 1] * weight, dtype=np.uint8)
        alpha = np.ascontiguousarray(valid * round(255 * max(0., min(1., opacity))), dtype=np.uint8)
        image = wx.Image(values.shape[1], values.shape[0])
        image.SetData(rgb.tobytes())
        image.SetAlpha(alpha.tobytes())
        self._overlay_bitmap = wx.Bitmap(image)
        self._overlay = {'values': values.copy(), 'valid': valid.copy(), 'units': units,
                         'origin': tuple(origin), 'cell': float(cell), 'scale': (low, high)}
        self.Refresh(False)

    def clear_overlay(self):
        self._overlay = None
        self._overlay_bitmap = None
        self.Refresh(False)

    def clear(self):
        """Reset layout/results without emitting a selection callback."""
        self.set_layout(None)

    def overlay_value(self, x, y):
        if not self._overlay:
            return None
        info = self._overlay
        col = math.floor((x - info['origin'][0]) / info['cell'])
        row = math.floor((y - info['origin'][1]) / info['cell'])
        values = info['values']
        if 0 <= row < values.shape[0] and 0 <= col < values.shape[1] and info['valid'][row, col]:
            return float(values[row, col]), info['units']
        return None

    def _visible_layers(self):
        if not self.layout:
            return []
        return list(range(len(self.layout.get('layers', [])))) if self.layer < 0 else [self.layer]

    def _pad_shapes(self, pad):
        shapes = pad.get('polygons_by_layer', {})
        return [poly for layer in self._visible_layers() for poly in shapes.get(str(layer), shapes.get(layer, []))]

    def _footprint_hit(self, x, y):
        """Prefer the smallest visible body under the pointer, never its neighbours."""
        if not self.preferred_net:
            return None
        last = len(self.layout.get('layers', [])) - 1
        # Component bodies live on outer layers. In an internal copper view a
        # broad footprint box must not steal clicks from an exposed trace/zone.
        if self.layer not in (-1, 0, last):
            return None
        candidates = []
        for fp in self.layout.get('footprints', []):
            side = int(fp.get('layer_index', 0))
            if self.layer >= 0 and side != self.layer:
                continue
            box = fp.get('box_mm')
            if not box or len(box) != 4 or not _near_box(x, y, box):
                continue
            area = max(0., box[2] - box[0]) * max(0., box[3] - box[1])
            candidates.append((area, side, str(fp.get('reference', '')), fp))
        if not candidates:
            return None
        _, _, reference, fp = min(candidates, key=lambda item: item[:3])
        pad_ids = [pid for pid in self._pads_by_reference.get(reference, [])
                   if self._pad_by_id[pid].get('net') == self.preferred_net
                   and self._pad_shapes(self._pad_by_id[pid])]
        return {'type': 'footprint', 'reference': reference, 'net': self.preferred_net,
                'pad_ids': pad_ids, 'x_mm': x, 'y_mm': y}

    def hit_test(self, x, y, heat=False):
        """Return a pad or a physically valid copper/board point, without mutation."""
        if not self.layout:
            return None
        candidates = self._pad_by_id.items()
        if self.layer < 0:
            candidates = sorted(candidates, key=lambda item: min(item[1].get('layers') or [999]))
        for pid, pad in candidates:
            shapes = self._pad_shapes(pad)
            # A plated pad is a logical terminal, including its displayed drill
            # centre. The solver uses its actual annular copper cells, not the
            # drill position. NPTH holes have no selectable pad record.
            if shapes and _near_box(x, y, self._pad_boxes[pid]) and (
                    point_in_polygons(x, y, shapes) or point_in_polygons(x, y, pad.get('hole_polygons', []))):
                return {'type': 'pad', 'pad': pad, 'pad_ids': [pid], 'x_mm': x, 'y_mm': y}
        if not heat:
            footprint = self._footprint_hit(x, y)
            if footprint is not None:
                return footprint
        visible = self._visible_layers()
        for via in self.layout.get('vias', []) if self.show_vias else []:
            layers = [int(v) for v in via.get('layers', []) if int(v) in visible]
            if not layers:
                continue
            dx, dy = x - via['x_mm'], y - via['y_mm']
            radius, hole = float(via.get('diameter_mm', 0)) / 2, float(via.get('drill_mm', 0)) / 2
            if dx * dx + dy * dy <= radius * radius:
                # A click in a displayed drill hole is anchored to the actual
                # plated annulus, never to a non-conductive centre grid cell.
                distance = math.hypot(dx, dy)
                if distance <= hole + 1e-9:
                    angle = math.atan2(dy, dx) if distance else 0.
                    anchor = (hole + radius) / 2
                    x, y = via['x_mm'] + anchor * math.cos(angle), via['y_mm'] + anchor * math.sin(angle)
                return {'type': 'point', 'net': via.get('net', ''), 'layer': layers[0],
                        'x_mm': x, 'y_mm': y, 'via': via}
        if point_in_polygons(x, y, self.layout.get('holes', [])):
            return None
        for layer in visible:
            if layer >= len(self._copper):
                continue
            for item, box in reversed(self._copper[layer]):
                if (item.get('kind') in ('zone', 'zone_outline') and not self.show_zones
                        or item.get('kind', 'track') not in ('zone', 'zone_outline') and not self.show_tracks):
                    continue
                if item.get('net') and _near_box(x, y, box) and point_in_polygons(x, y, item.get('polygons', [])):
                    return {'type': 'point', 'net': item['net'], 'layer': layer, 'x_mm': x, 'y_mm': y}
        if heat and point_in_polygons(x, y, self.layout.get('outline', [])):
            return {'type': 'point', 'net': '', 'layer': max(0, self.layer), 'x_mm': x, 'y_mm': y}
        return None

    def _make_point(self, hit):
        return {'identifier': 'point:' + uuid.uuid4().hex, 'net': hit.get('net', ''),
                'layer': hit.get('layer', max(0, self.layer)), 'x_mm': hit['x_mm'], 'y_mm': hit['y_mm']}

    def _click(self, event):
        self.SetFocus()
        sx, sy = event.GetPosition()
        if self.on_marker and not event.ControlDown():
            for mx, my, marker in reversed(self._marker_hits):
                if math.hypot(sx - mx, sy - my) < 11:
                    self.on_marker(marker.get('id'))
                    return
        x, y = self.screen_to_world(sx, sy)
        hit = self.hit_test(x, y, heat=self.mode == 'heat')
        points = []
        if hit and hit['type'] in ('pad', 'footprint'):
            pad_ids = hit['pad_ids']
            if event.ControlDown():
                # A component body adds/removes its matching pads as one group.
                # Direct pad clicks still toggle exactly the clicked terminal.
                if pad_ids and all(pid in self.selected for pid in pad_ids):
                    self.selected = [pid for pid in self.selected if pid not in pad_ids]
                else:
                    self.selected.extend(pid for pid in pad_ids if pid not in self.selected)
            else:
                self.selected = list(pad_ids)
        elif event.ControlDown():
            # Empty space, copper and drill clicks are not pad group edits.
            # In particular do not replace an accumulated selection with a
            # newly created point terminal on an accidental Ctrl-click.
            return
        elif hit:
            self.selected = []
            points = [self._make_point(hit)]
        elif not event.ControlDown():
            self.selected = []
        self.Refresh(False)
        if self.on_pick:
            self.on_pick({'pad_ids': list(self.selected), 'points': points,
                          'kind': 'select' if event.ControlDown() else self.mode,
                          'reference': hit.get('reference') if hit else None,
                          'auto_matched': bool(hit and hit['type'] == 'footprint'),
                          'x_mm': x, 'y_mm': y})

    def _wheel(self, event):
        sx, sy = event.GetPosition()
        self.zoom_at(sx, sy, 1.22 ** (event.GetWheelRotation() / max(event.GetWheelDelta(), 1)))

    def _pan_start(self, event):
        self.SetFocus()
        self._drag = tuple(event.GetPosition())
        if not self.HasCapture():
            self.CaptureMouse()
        self.SetCursor(wx.Cursor(wx.CURSOR_SIZING))

    def _pan_end(self, event):
        self._drag = None
        if self.HasCapture():
            self.ReleaseMouse()
        self.SetCursor(wx.Cursor(wx.CURSOR_ARROW if self.mode == 'select' else wx.CURSOR_CROSS))

    def _capture_lost(self, event):
        self._drag = None

    def _motion(self, event):
        sx, sy = event.GetPosition()
        if self._drag is not None:
            self.offset[0] += sx - self._drag[0]
            self.offset[1] += sy - self._drag[1]
            self._drag = (sx, sy)
            self.Refresh(False)
            return
        x, y = self.screen_to_world(sx, sy)
        hit = self.hit_test(x, y)
        text = f'X {x:.3f} mm   Y {y:.3f} mm'
        if hit and hit['type'] == 'pad':
            pad = hit['pad']
            text = f"{pad.get('label', pad['identifier'])}   {pad.get('net') or self._tr('No net', 'Ağ yok')}\n" + text
        elif hit:
            if hit['type'] == 'footprint':
                group = self._tr('matching pads', 'eşleşen pad')
                text = f"{hit['reference']} · {len(hit['pad_ids'])} {group} · {hit['net']}\n" + text
            else:
                text = f"{hit.get('net', '')}\n" + text
        value = self.overlay_value(x, y)
        if value:
            text += f'\n{value[0]:.4g} {value[1]}'
        if text != self._tooltip_text:
            self.SetToolTip(text)
            self._tooltip_text = text

    def _key(self, event):
        if event.GetKeyCode() in (ord('F'), wx.WXK_HOME):
            self.fit_board()
        elif event.GetKeyCode() == wx.WXK_ESCAPE:
            self.clear_selection()
            self.set_mode('select')
            if self.on_pick:
                self.on_pick({'pad_ids': [], 'points': [], 'kind': 'select', 'cancel_tool': True})
        else:
            event.Skip()

    def _size(self, event):
        self._cache_key = None
        self.Refresh(False)
        event.Skip()

    def _path(self, gc, polygons):
        path = gc.CreatePath()
        for polygon in polygons or []:
            for ring in _contours(polygon):
                if len(ring) < 3:
                    continue
                x, y = self.world_to_screen(*ring[0][:2])
                path.MoveToPoint(x, y)
                for point in ring[1:]:
                    x, y = self.world_to_screen(*point[:2])
                    path.AddLineToPoint(x, y)
                path.CloseSubpath()
        return path

    def _draw_polygons(self, gc, polygons, fill, stroke=None, width=.5):
        if not polygons:
            return
        if fill:
            gc.SetBrush(wx.Brush(fill))
        if stroke:
            gc.SetPen(_pen(stroke, width))
        # Holes use even/odd *within* each polygon; overlapping polygons are a
        # union. In particular a PTH pad repeated on eight layers must not
        # disappear by cancelling eight identical contours in all-layer view.
        for polygon in polygons:
            path = self._path(gc, [polygon])
            if fill:
                gc.FillPath(path, wx.ODDEVEN_RULE)
            if stroke:
                gc.StrokePath(path)

    def _draw_base(self, gc):
        if not self.layout:
            return
        self._draw_polygons(gc, self.layout.get('outline', []), wx.Colour(BOARD), wx.Colour(OUTLINE), 1.2)
        visible = self._visible_layers()
        for kind in ('zone', 'track'):
            if kind == 'zone' and not self.show_zones or kind == 'track' and not self.show_tracks:
                continue
            for layer in reversed(visible):
                if layer >= len(self._copper):
                    continue
                # Layer red/green must not resemble numerical hot/cold values
                # on copper outside the active result mask.
                c = wx.Colour('#687680' if self._overlay else LAYER_COLORS[layer % len(LAYER_COLORS)])
                c.Set(c.Red(), c.Green(), c.Blue(), (85 if self.layer < 0 else 130) if kind == 'zone' else 230)
                for item, box in self._copper[layer]:
                    if (item.get('kind', 'track') in ('zone', 'zone_outline')) != (kind == 'zone'):
                        continue
                    self._draw_polygons(gc, item.get('polygons', []), c)
        for pad in self._pad_by_id.values():
            shapes = self._pad_shapes(pad)
            if shapes:
                self._draw_polygons(gc, shapes, wx.Colour('#89969c' if self._overlay else '#b6c5ad'),
                                    wx.Colour('#bec8cd' if self._overlay else '#e2dab0'), .4)
        drawings = self.layout.get('drawings_by_layer', {}) if self.show_drawings else {}
        for layer in visible:
            shapes = drawings.get(str(layer), drawings.get(layer, [])) if isinstance(drawings, dict) else (drawings[layer] if layer < len(drawings) else [])
            if shapes:
                if isinstance(shapes[0], dict):
                    for item in shapes:
                        self._draw_polygons(gc, item.get('polygons', []), None, wx.Colour('#b5c6d0'), .8)
                else:
                    self._draw_polygons(gc, shapes, None, wx.Colour('#b5c6d0'), .8)
        # Vias are kept as real holes above copper rather than painted as solid
        # discs, retaining visible annuli on every connected layer.
        for via in self.layout.get('vias', []) if self.show_vias else []:
            if not any(int(layer) in visible for layer in via.get('layers', [])):
                continue
            x, y = self.world_to_screen(via['x_mm'], via['y_mm'])
            diameter = max(1., via.get('diameter_mm', 0) * self.scale)
            drill = max(.6, via.get('drill_mm', 0) * self.scale)
            gc.SetPen(_pen('#d0d6bc', .6))
            gc.SetBrush(wx.Brush('#89969c' if self._overlay else '#8cae96'))
            gc.DrawEllipse(x - diameter / 2, y - diameter / 2, diameter, diameter)
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.SetBrush(wx.Brush(BACKGROUND))
            gc.DrawEllipse(x - drill / 2, y - drill / 2, drill, drill)
        self._draw_polygons(gc, self.layout.get('holes', []), wx.Colour(BACKGROUND))

    def _draw_top(self, gc):
        if not self.layout:
            return
        # Outlines and pad outlines stay visible above numerical results.
        self._draw_polygons(gc, self.layout.get('outline', []), None, wx.Colour(OUTLINE), 1.2)
        self._draw_polygons(gc, self.layout.get('holes', []), wx.Colour(BACKGROUND), wx.Colour(OUTLINE), .7)
        visible = self._visible_layers()
        for via in self.layout.get('vias', []) if self.show_vias else []:
            if not any(int(layer) in visible for layer in via.get('layers', [])):
                continue
            x, y = self.world_to_screen(via['x_mm'], via['y_mm'])
            drill = max(.6, via.get('drill_mm', 0) * self.scale)
            gc.SetBrush(wx.Brush(BACKGROUND))
            gc.SetPen(_pen('#a8bbae', .6))
            gc.DrawEllipse(x - drill / 2, y - drill / 2, drill, drill)
        for pid, pad in self._pad_by_id.items():
            if pid in self.selected or self._overlay:
                self._draw_polygons(gc, self._pad_shapes(pad), None,
                                    wx.Colour('#f6e56f' if pid in self.selected else '#dce4d5'),
                                    2.2 if pid in self.selected else .5)
            if self.show_pad_numbers and self.scale >= 22 and self._pad_shapes(pad):
                number = str(pad.get('number', ''))
                if number:
                    in_hole = point_in_polygons(pad['x_mm'], pad['y_mm'], pad.get('hole_polygons', []))
                    gc.SetFont(wx.Font(7, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD),
                               wx.Colour('#f2f6ef' if in_hole else '#10202b'))
                    x, y = self.world_to_screen(pad['x_mm'], pad['y_mm'])
                    tw, th = gc.GetTextExtent(number)
                    gc.DrawText(number, x - tw / 2, y - th / 2)
        if self.show_references:
            gc.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour('#f0f3ee'))
            for fp in self.layout.get('footprints', []):
                if self.layer in (0, len(self.layout.get('layers', [])) - 1) and fp.get('layer_index', 0) != self.layer:
                    continue
                x, y = self.world_to_screen(fp.get('x_mm', 0), fp.get('y_mm', 0))
                gc.DrawText(fp.get('reference', ''), x + 3, y + 3)
        self._marker_hits = []
        for marker in self.markers:
            positions = []
            for pid in marker.get('pad_ids', []):
                pad = self._pad_by_id.get(pid)
                if pad and (self.layer < 0 or self.layer in pad.get('layers', [])):
                    positions.append((pad['x_mm'], pad['y_mm']))
            for point in marker.get('points', []):
                if self.layer < 0 or int(point.get('layer', 0)) == self.layer:
                    positions.append((point['x_mm'], point['y_mm']))
            if not positions and 'x_mm' in marker:
                positions = [(marker['x_mm'], marker['y_mm'])]
            color = KIND_COLORS.get(marker.get('kind'), '#ffffff')
            for index, position in enumerate(positions):
                x, y = self.world_to_screen(*position)
                if marker.get('selected'):
                    gc.SetPen(_pen('#f6e56f', 2))
                    gc.SetBrush(wx.TRANSPARENT_BRUSH)
                    gc.DrawEllipse(x - 10, y - 10, 20, 20)
                gc.SetPen(_pen(BACKGROUND, 2.5))
                gc.SetBrush(wx.Brush(color))
                gc.DrawEllipse(x - 7, y - 7, 14, 14)
                gc.SetPen(_pen('#ffffff', 1.2))
                gc.StrokeLine(x - 4, y, x + 4, y)
                if marker.get('kind') in ('source', 'V', 'heat', 'W'):
                    gc.StrokeLine(x, y - 4, x, y + 4)
                self._marker_hits.append((x, y, marker))
                if index == 0:
                    label = str(marker.get('label') or marker.get('value') or '')
                    if label:
                        gc.SetFont(wx.Font(10, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour(color))
                        tw, th = gc.GetTextExtent(label)
                        gc.SetPen(wx.TRANSPARENT_PEN)
                        gc.SetBrush(wx.Brush(wx.Colour(16, 27, 39, 225)))
                        gc.DrawRoundedRectangle(x + 10, y - th / 2 - 3, tw + 10, th + 6, 3)
                        gc.DrawText(label, x + 15, y - th / 2)

    def _draw_legend(self, gc, width):
        if not self._overlay:
            return
        info = self._overlay
        low, high = info['scale']
        x, y = width - 118, 18
        gc.SetBrush(wx.Brush(wx.Colour(16, 27, 39, 230)))
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.DrawRoundedRectangle(x - 10, y - 7, 116, 178, 5)
        gc.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD), wx.Colour('#e7eff6'))
        gc.DrawText(str(info['units']), x, y)
        colors = ['#c62224', '#f58020', '#f6e042', '#56d174', '#1abecd', '#1e68cf', '#162a58']
        for index, color in enumerate(colors):
            gc.SetBrush(wx.Brush(color))
            gc.DrawRectangle(x, y + 24 + index * 17, 14, 18)
        gc.DrawText(f'{high:.4g}', x + 23, y + 24)
        gc.DrawText(f'{low:.4g}', x + 23, y + 128)

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(BACKGROUND))
        dc.Clear()
        w, h = self.GetClientSize()
        if w < 2 or h < 2:
            return
        gc = wx.GraphicsContext.Create(dc)
        if not gc:
            return
        if not self.layout:
            gc.SetFont(wx.Font(13, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour('#bfd0de'))
            message = self._tr('Open a saved PCB to place sources and loads directly on the board.',
                               'Kaynak ve yükleri kart üzerinde yerleştirmek için kayıtlı PCB aç.')
            tw, th = gc.GetTextExtent(message)
            gc.DrawText(message, max(18, (w - tw) / 2), h / 2)
            return
        key = (self._revision, self.layer, bool(self._overlay), w, h, self.scale, *self.offset)
        if self._cache_key != key or self._bitmap is None:
            bitmap = wx.Bitmap(w, h, 32)
            memory = wx.MemoryDC(bitmap)
            memory.SetBackground(wx.Brush(BACKGROUND))
            memory.Clear()
            base_gc = wx.GraphicsContext.Create(memory)
            self._draw_base(base_gc)
            del base_gc
            memory.SelectObject(wx.NullBitmap)
            self._bitmap = bitmap
            self._cache_key = key
        gc.DrawBitmap(self._bitmap, 0, 0, w, h)
        if self._overlay and self._overlay_bitmap:
            info = self._overlay
            x, y = self.world_to_screen(*info['origin'])
            rows, cols = info['values'].shape
            gc.SetInterpolationQuality(wx.INTERPOLATION_NONE)
            gc.DrawBitmap(self._overlay_bitmap, x, y, cols * info['cell'] * self.scale, rows * info['cell'] * self.scale)
        self._draw_top(gc)
        self._draw_legend(gc, w)
        gc.SetFont(wx.Font(9, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), wx.Colour('#b7c9d6'))
        controls = self._tr('Wheel: zoom · Middle/right drag: pan · F: fit · Ctrl+click: select pads',
                            'Tekerlek: yakınlaştır · Orta/sağ sürükle: kaydır · F: sığdır · Ctrl+tıkla: pad seç')
        gc.DrawText(controls, 12, h - 22)
        # Native dark KiCad themes may otherwise stroke transparent controls
        # over our explicit bitmap surface; our own border is always visible.
        gc.SetPen(_pen('#3d5264', 1))
        # Avoid shared stock transparent brushes in KiCad's embedded wx.
        # Explicit strokes cannot fill over the PCB/heatmap bitmap.
        gc.StrokeLine(.5, .5, w - .5, .5)
        gc.StrokeLine(w - .5, .5, w - .5, h - .5)
        gc.StrokeLine(w - .5, h - .5, .5, h - .5)
        gc.StrokeLine(.5, h - .5, .5, .5)
