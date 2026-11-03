"""Native-geometry regression tests; fixtures contain no user project data."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pcbnew as p
from .extractor import inspect_board, rasterize, _sample_polygons
from .model import AnalysisError


def make_fixture(path, layers=2, via=True, cutout=True, zone=False):
    board = p.BOARD()
    board.SetCopperLayerCount(layers)
    ids = list(board.GetEnabledLayers().CuStack())
    net = p.NETINFO_ITEM(board, 'POWER')
    other = p.NETINFO_ITEM(board, 'GND')
    board.Add(net)
    board.Add(other)
    for a, b in [((0,0),(12,0)),((12,0),(12,8)),((12,8),(0,8)),((0,8),(0,0))]:
        edge = p.PCB_SHAPE(board)
        edge.SetShape(p.SHAPE_T_SEGMENT)
        edge.SetStart(p.VECTOR2I(round(a[0]*1e6), round(a[1]*1e6)))
        edge.SetEnd(p.VECTOR2I(round(b[0]*1e6), round(b[1]*1e6)))
        edge.SetLayer(p.Edge_Cuts)
        edge.SetWidth(50000)
        board.Add(edge)
    if cutout:
        for a, b in [((5,5),(7,5)),((7,5),(7,7)),((7,7),(5,7)),((5,7),(5,5))]:
            edge = p.PCB_SHAPE(board)
            edge.SetShape(p.SHAPE_T_SEGMENT)
            edge.SetStart(p.VECTOR2I(round(a[0]*1e6), round(a[1]*1e6)))
            edge.SetEnd(p.VECTOR2I(round(b[0]*1e6), round(b[1]*1e6)))
            edge.SetLayer(p.Edge_Cuts)
            edge.SetWidth(50000)
            board.Add(edge)
    for ref, x in [('J1',2),('J2',10)]:
        fp = p.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(p.VECTOR2I(x*1000000, 3000000))
        board.Add(fp)
        pad = p.PAD(fp)
        pad.SetNumber('1')
        pad.SetSize(p.VECTOR2I(1500000,1500000))
        pad.SetShape(p.PAD_SHAPE_RECT)
        pad.SetAttribute(p.PAD_ATTRIB_SMD)
        ls = p.LSET()
        ls.AddLayer(p.F_Cu)
        pad.SetLayerSet(ls)
        pad.SetPosition(fp.GetPosition())
        pad.SetNet(net)
        fp.Add(pad)
    for layer in ids:
        track = p.PCB_TRACK(board)
        track.SetStart(p.VECTOR2I(2000000,3000000))
        track.SetEnd(p.VECTOR2I(10000000,3000000))
        track.SetWidth(1000000)
        track.SetLayer(layer)
        track.SetNet(net)
        board.Add(track)
    if via:
        for x in (3,9):
            item = p.PCB_VIA(board)
            item.SetPosition(p.VECTOR2I(x*1000000,3000000))
            item.SetWidth(600000)
            item.SetDrill(300000)
            item.SetLayerPair(ids[0],ids[-1])
            item.SetNet(net)
            board.Add(item)
    if zone:
        z = p.ZONE(board)
        z.SetLayer(p.F_Cu)
        z.SetNet(other)
        shape = z.Outline()
        shape.NewOutline()
        for x,y in [(1,4),(11,4),(11,7.5),(1,7.5)]:
            shape.Append(round(x*1e6), round(y*1e6))
        board.Add(z)
    # SaveBoard is confined to synthetic test fixtures, never the analysed PCB.
    p.SaveBoard(str(path), board)
    text = Path(path).read_text(encoding='utf-8')
    foil=.035
    gap=(1.6-foil*layers)/(layers-1)
    entries=[]
    for k, layer in enumerate(ids):
        entries.append(f'(layer "{board.GetLayerName(layer)}" (type "copper") (thickness {foil}))')
        if k<layers-1:
            entries.append(f'(layer "dielectric {k+1}" (type "core") (thickness {gap:.12f}) (material "FR4"))')
    text=text.replace('(setup', '(setup\n(stackup '+''.join(entries)+')',1)
    Path(path).write_text(text,encoding='utf-8')
    return path


class ExtractorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'synthetic.kicad_pcb'
    def tearDown(self):
        self.temp.cleanup()
    def test_native_copper_cutout_vias_and_source_unchanged(self):
        make_fixture(self.path)
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        info=inspect_board(self.path)
        json.dumps(info)
        self.assertEqual([l['name'] for l in info['layers']],['F.Cu','B.Cu'])
        self.assertEqual({x['label'] for x in info['pads']},{'J1.1','J2.1'})
        b=rasterize(self.path,['POWER'],cell_mm=.25)
        self.assertEqual(b.copper.shape,(2,32,48))
        self.assertFalse(b.board_mask[24,24])
        self.assertGreater(b.copper[:,12,20].min(),.9)
        self.assertEqual(len(b.vias),2)
        self.assertTrue(all(b.pad_cells[x['identifier']] for x in info['pads']))
        self.assertTrue(all(c[0] and c[1] for c in b.metadata['via_cells']))
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
    def test_eight_layer_stackup_order_and_centers(self):
        make_fixture(self.path,layers=8,via=False)
        info=inspect_board(self.path)
        self.assertEqual([l['name'] for l in info['layers']],
                         ['F.Cu']+[f'In{i}.Cu' for i in range(1,7)]+['B.Cu'])
        z=np.array([l['z_mm'] for l in info['layers']])
        self.assertTrue(np.all(np.diff(z)>0))
        self.assertAlmostEqual(info['board_thickness_mm'],1.6,places=8)
        self.assertAlmostEqual(z[0],.0175)
        self.assertAlmostEqual(z[-1],1.5825,places=8)
    def test_budget_refuses_without_coarsening(self):
        make_fixture(self.path)
        with self.assertRaisesRegex(AnalysisError,'limit'):
            rasterize(self.path,['POWER'],.1,max_cells=100)
    def test_unfilled_zone_refused_not_silently_refilled(self):
        make_fixture(self.path,zone=True)
        before=self.path.read_bytes()
        info=inspect_board(self.path)
        self.assertEqual(info['stats']['copper_zones'],1)
        self.assertEqual(info['stats']['filled_copper_zones'],0)
        with self.assertRaisesRegex(AnalysisError,'Refill'):
            rasterize(self.path,['POWER'])
        self.assertEqual(before,self.path.read_bytes())
    def test_raster_does_not_bridge_disconnected_same_net_islands(self):
        a=np.array([[0,0],[.09,0],[.09,1],[0,1]])
        b=np.array([[.16,0],[.25,0],[.25,1],[.16,1]])
        with self.assertRaisesRegex(AnalysisError,'disconnected'):
            _sample_polygons([[a],[b]],(0,0),.25,4,1,collision_check=True)
    def test_pad_barrel_contacts_do_not_fill_via_hole(self):
        make_fixture(self.path)
        b=rasterize(self.path,['POWER'],cell_mm=.1)
        for via, contacts in zip(b.vias,b.metadata['via_cells']):
            r=int((via.y_mm-b.origin_y_mm)/b.cell_mm)
            c=int((via.x_mm-b.origin_x_mm)/b.cell_mm)
            self.assertEqual(b.net_copper['POWER'][0,r,c],0)
            self.assertTrue(contacts[0])
            self.assertTrue(contacts[1])
    def test_saved_filled_zone_copper_and_hole_are_preserved(self):
        make_fixture(self.path,zone=True)
        board=p.LoadBoard(str(self.path))
        p.ZONE_FILLER(board).Fill(board.Zones())
        p.SaveBoard(str(self.path),board)
        before=self.path.read_bytes()
        info=inspect_board(self.path)
        self.assertEqual(info['stats']['copper_zones'],1)
        self.assertEqual(info['stats']['filled_copper_zones'],1)
        b=rasterize(self.path,['POWER'],cell_mm=.25)
        # GND zone is inactive electrically but still part of thermal copper.
        self.assertGreater(b.copper[0,18,8],.9)
        self.assertEqual(b.net_copper['POWER'][0,18,8],0)
        self.assertEqual(b.copper[:,24,24].sum(),0)
        self.assertEqual(before,self.path.read_bytes())
    def test_filled_zone_is_part_of_the_selected_electrical_net(self):
        make_fixture(self.path,zone=True)
        board=p.LoadBoard(str(self.path))
        power_pad=next(iter(board.GetFootprints())).Pads()[0]
        next(iter(board.Zones())).SetNet(power_pad.GetNet())
        p.ZONE_FILLER(board).Fill(board.Zones())
        p.SaveBoard(str(self.path),board)
        before=self.path.read_bytes()
        b=rasterize(self.path,['POWER'],cell_mm=.25)
        # This cell is inside the zone, away from all fixture pads/tracks.
        self.assertGreater(b.net_copper['POWER'][0,18,8],.9)
        self.assertGreater(b.copper[0,18,8],.9)
        self.assertEqual(before,self.path.read_bytes())
    def test_native_rotated_and_flipped_pad_contact(self):
        make_fixture(self.path,via=False)
        board=p.LoadBoard(str(self.path))
        fp=next(fp for fp in board.GetFootprints() if fp.GetReference()=='J1')
        pad=next(iter(fp.Pads()))
        pad.SetSize(p.VECTOR2I(2500000,500000))
        fp.SetOrientation(p.EDA_ANGLE(90,p.DEGREES_T))
        fp.Flip(fp.GetPosition(),False)
        p.SaveBoard(str(self.path),board)
        info=inspect_board(self.path)
        record=next(pd for pd in info['pads'] if pd['label']=='J1.1')
        self.assertEqual(record['layers'],[1])
        b=rasterize(self.path,['POWER'],cell_mm=.25)
        cells=b.pad_cells[record['identifier']]
        self.assertTrue(cells)
        self.assertTrue(all(k==1 for k,r,c in cells))
        self.assertGreater(len({r for k,r,c in cells}),len({c for k,r,c in cells}))
    def test_blind_via_does_not_drill_or_link_outside_span(self):
        make_fixture(self.path,layers=8,via=False)
        board=p.LoadBoard(str(self.path))
        ids=list(board.GetEnabledLayers().CuStack())
        via=p.PCB_VIA(board)
        via.SetPosition(p.VECTOR2I(3000000,3000000))
        via.SetWidth(600000)
        via.SetDrill(300000)
        via.SetViaType(p.VIATYPE_BLIND)
        via.SetLayerPair(ids[0],ids[2])
        via.SetNet(next(iter(board.GetFootprints())).Pads()[0].GetNet())
        board.Add(via)
        p.SaveBoard(str(self.path),board)
        b=rasterize(self.path,['POWER'],cell_mm=.1)
        self.assertEqual(len(b.vias),1)
        self.assertEqual((b.vias[0].start_layer,b.vias[0].end_layer),(0,2))
        self.assertEqual(set(b.metadata['via_cells'][0]),{0,1,2})
        self.assertEqual(b.copper[0,30,30],0)
        self.assertGreater(b.copper[3,30,30],.9)


if __name__=='__main__':
    unittest.main()
