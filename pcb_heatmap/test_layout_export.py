"""Synthetic native fixtures for the read-only interactive PCB view."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pcbnew as p

from .layout_export import export_layout
from .test_extractor_native import make_fixture


def _point_in_contour(point, contour):
    x, y = point
    inside = False
    previous = contour[-1]
    for current in contour:
        ax, ay = previous
        bx, by = current
        if ((ay > y) != (by > y)) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            inside = not inside
        previous = current
    return inside


def _contains(point, polygons):
    return any(sum(_point_in_contour(point, c) for c in polygon) % 2
               for polygon in polygons)


class LayoutExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'vector-fixture.kicad_pcb'

    def tearDown(self):
        self.temp.cleanup()

    def test_four_layers_outline_cutout_native_pads_tracks_vias_and_no_write(self):
        make_fixture(self.path, layers=4)
        before = self.path.read_bytes()
        ticks = []
        layout = export_layout(self.path, lambda message, fraction: ticks.append(fraction))
        json.dumps(layout, allow_nan=False)
        self.assertEqual(layout['schema_version'], 1)
        self.assertEqual(layout['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(layout['bounds_mm'], [0, 0, 12, 8])
        self.assertEqual([layer['name'] for layer in layout['layers']],
                         ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'])
        self.assertTrue(_contains((1, 1), layout['outline']))
        self.assertFalse(_contains((6, 6), layout['outline']))
        self.assertEqual({pad['label'] for pad in layout['pads']}, {'J1.1', 'J2.1'})
        self.assertTrue(all(pad['layers'] == [0] for pad in layout['pads']))
        self.assertTrue(all(pad['polygons_by_layer']['0'] for pad in layout['pads']))
        self.assertEqual([len(items) for items in layout['copper_by_layer']], [1, 1, 1, 1])
        self.assertTrue(all(items[0]['kind'] == 'track' for items in layout['copper_by_layer']))
        self.assertEqual(len(layout['vias']), 2)
        self.assertTrue(all(via['layers'] == [0, 1, 2, 3] for via in layout['vias']))
        self.assertAlmostEqual(layout['vias'][0]['drill_mm'], .3)
        self.assertEqual(layout['nets'], ['POWER'])
        self.assertEqual(ticks[-1], 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_saved_filled_zone_keeps_cutouts_and_is_not_a_zone_outline(self):
        make_fixture(self.path, layers=4, zone=True)
        board = p.LoadBoard(str(self.path))
        p.ZONE_FILLER(board).Fill(board.Zones())
        p.SaveBoard(str(self.path), board)
        before = self.path.read_bytes()
        layout = export_layout(self.path)
        zones = [item for item in layout['copper_by_layer'][0] if item['kind'] == 'zone']
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]['net'], 'GND')
        self.assertTrue(_contains((2, 4.5), zones[0]['polygons']))
        self.assertFalse(_contains((6, 6), zones[0]['polygons']))
        self.assertEqual(layout['stats']['filled_copper_zones'], 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unfilled_zone_stays_visible_as_outline_without_filling_or_saving(self):
        make_fixture(self.path, layers=4, zone=True)
        before = self.path.read_bytes()
        layout = export_layout(self.path)
        self.assertTrue(any(item['kind'] == 'zone_outline' for item in layout['copper_by_layer'][0]))
        self.assertEqual(layout['stats']['filled_copper_zones'], 0)
        self.assertTrue(any('unfilled' in warning for warning in layout['warnings']))
        self.assertEqual(self.path.read_bytes(), before)

    def test_pad_rotation_flip_native_holes_and_blind_via_span(self):
        make_fixture(self.path, layers=4, via=False)
        board = p.LoadBoard(str(self.path))
        fp = next(fp for fp in board.GetFootprints() if fp.GetReference() == 'J1')
        pad = next(iter(fp.Pads()))
        pad.SetSize(p.VECTOR2I(2500000, 500000))
        fp.SetOrientation(p.EDA_ANGLE(90, p.DEGREES_T))
        fp.Flip(fp.GetPosition(), False)
        fp.SetValue('USB-C')
        via = p.PCB_VIA(board)
        via.SetPosition(p.VECTOR2I(3000000, 3000000))
        via.SetWidth(600000)
        via.SetDrill(300000)
        via.SetViaType(p.VIATYPE_BLIND)
        ids = list(board.GetEnabledLayers().CuStack())
        via.SetLayerPair(ids[0], ids[1])
        via.SetNet(pad.GetNet())
        board.Add(via)
        hole = p.PAD(fp)
        hole.SetNumber('')
        hole.SetPosition(p.VECTOR2I(4000000, 1000000))
        hole.SetSize(p.VECTOR2I(600000, 600000))
        hole.SetDrillSize(p.VECTOR2I(600000, 600000))
        hole.SetAttribute(p.PAD_ATTRIB_NPTH)
        hole.SetShape(p.PAD_SHAPE_CIRCLE)
        hole.SetLayerSet(p.LSET.AllCuMask())
        fp.Add(hole)
        p.SaveBoard(str(self.path), board)
        before = self.path.read_bytes()
        layout = export_layout(self.path)
        record = next(item for item in layout['pads'] if item['label'] == 'J1.1')
        self.assertEqual(record['layers'], [3])
        points = record['polygons_by_layer']['3'][0][0]
        self.assertGreater(max(y for x, y in points)-min(y for x, y in points),
                           max(x for x, y in points)-min(x for x, y in points))
        self.assertEqual(layout['vias'][0]['layers'], [0, 1])
        self.assertEqual(next(f for f in layout['footprints'] if f['reference'] == 'J1')['layer_index'], 3)
        self.assertTrue(layout['holes'])
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
