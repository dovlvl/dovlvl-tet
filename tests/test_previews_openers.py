import sys,unittest,time,copy,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw
from recognition import PreviewCache,Recognizer,PALETTE
from legacy_preview_reference import PreviewCache as OldPreview
from geometry import orientations,settle
from planner import route_to
from openers import load_book,compile_book,opener_plan,mirrored_variant
from controller import AutoController
from input_win import KeyPulse
from helpers import C,Game,FakeBackend,synthetic_tick,scene

ROOT=Path(__file__).resolve().parents[1]
def icon(kind,size=17,offset=(25,18),rotation=0,dim=1,gray=False):
    im=Image.new('RGB',(160,110),'#101010');d=ImageDraw.Draw(im);p=orientations(kind)[rotation];px=min(x for x,y in p);py=min(y for x,y in p)
    color=tuple(int(PALETTE[kind][i:i+2],16)*dim for i in (1,3,5));color=tuple(round(v) for v in color)
    if gray:color=(90,90,90)
    for x,y in p:
        xx=offset[0]+(x-px)*size;yy=offset[1]+(y-py)*size;d.rectangle((xx,yy,xx+size-2,yy+size-2),fill=color)
    return np.asarray(im)

class PreviewFixTests(unittest.TestCase):
    def test_seven_kinds_offsets_sizes_rotations(self):
        for k in PALETTE:
            for size,offset in ((9,(37,25)),(17,(20,18)),(25,(30,7))):
                for r in range(4):
                    out=PreviewCache.classify(icon(k,size,offset,r),0,.28,.28)
                    self.assertTrue(out.valid,(k,size,r,out));self.assertEqual(out.kind,k)
    def test_empty_dim_gray_and_unknown_are_distinct(self):
        empty=PreviewCache.classify(np.full((100,140,3),16,np.uint8),0,.28,.28)
        dim=PreviewCache.classify(icon('T',dim=.25),0,.28,.28)
        gray=PreviewCache.classify(icon('L',gray=True),0,.28,.28)
        white=PreviewCache.classify(np.full((100,140,3),255,np.uint8),0,.28,.28)
        self.assertEqual(empty.state,'empty');self.assertTrue(empty.valid)
        self.assertEqual(dim.kind,'T');self.assertEqual(dim.state,'disabled');self.assertFalse(dim.available)
        self.assertEqual(gray.state,'disabled');self.assertFalse(white.valid)
        old=OldPreview.classify(icon('T',dim=.25),0,.28,.28)
        self.assertIsNone(old.kind) # Old code conflated a dim held piece with empty.
    def test_clipped_piece_is_not_guessed(self):
        out=PreviewCache.classify(icon('I',offset=(0,20)),0,.28,.28)
        self.assertFalse(out.valid);self.assertIn('경계',out.reason)
    def test_failure_not_permanently_cached(self):
        cache=PreviewCache();image=np.full((80,100,3),255,np.uint8)
        cache.read('hold',image,0,.28,.28);cache.read('hold',image,.2,.28,.28)
        self.assertEqual(cache.reclassifications,2)
    def test_queue_shift_and_hold_change_reclassified(self):
        cache=PreviewCache();first=[cache.read('next'+str(i),icon(k),0,.28,.28).kind for i,k in enumerate('ILO')]
        second=[cache.read('next'+str(i),icon(k),.05,.28,.28).kind for i,k in enumerate('LOS')]
        self.assertEqual(first,list('ILO'));self.assertEqual(second,list('LOS'))
        cache.read('hold',icon('I'),.06,.28,.28);self.assertEqual(cache.read('hold',icon('T'),.07,.28,.28).kind,'T')
    def test_next_empty_not_reported_as_known_future(self):
        r=PreviewCache().read('next0',np.full((80,100,3),16,np.uint8),0,.28,.28)
        self.assertFalse(r.valid);self.assertIsNone(r.kind)

class ContinuousRecognitionTests(unittest.TestCase):
    def test_same_color_spawn_touching_new_lock_uses_pixel_checked_hypothesis(self):
        # New I at y=1 touches just-locked I at y=2. A connected-component-only
        # spawn detector sees eight cyan cells and cannot classify four minos.
        b=[[0]*10 for _ in range(20)]
        for y in range(3,20):b[y][3:7]=[1]*4
        r=Recognizer();now=time.monotonic();r.process(scene(b,kind='I'),(0,0,340,400),C,1,now)
        expected=copy.deepcopy(b);expected[2][3:7]=[1]*4
        after=Image.fromarray(scene(expected,kind='I'));d=ImageDraw.Draw(after)
        for x in range(3,7):d.rectangle((x*20+1,41,x*20+18,58),fill=PALETTE['I'])
        rgb=np.asarray(after);o=r.process(rgb,(0,0,340,400),C,2,now+.02,expected_fixed=expected)
        self.assertIsNotNone(o.active);self.assertEqual(o.active.kind,'I');self.assertEqual(o.fixed,expected)
        # A prediction inconsistent with pixels must not produce invented occupancy.
        wrong=copy.deepcopy(expected);wrong[0][0]=1;r2=Recognizer()
        o2=r2.process(rgb,(0,0,340,400),C,3,now+.03,expected_fixed=wrong)
        self.assertIsNone(o2.active)

class OpenerTests(unittest.TestCase):
    def setUp(self):self.book=load_book(ROOT/'data/openers/TKI_Fonzie.json')
    def test_all_seven_source_targets_reachable_and_line_clear(self):
        b=[[0]*10 for _ in range(20)];lines=0
        for step in self.book['variants'][0]['steps']:
            self.assertIsNotNone(route_to(b,step['kind'],(3,0,0),step['cells']))
            x,y,r=step['state'];b,n=settle(b,orientations(step['kind'])[r],x,y);lines+=n
            self.assertEqual(tuple(map(tuple,b)),tuple(map(tuple,step['expected_after'])))
        self.assertEqual(lines,2)
    def test_mirror_is_explicitly_derived_and_model_checked(self):
        data=copy.deepcopy(self.book);data['variants']=[mirrored_variant(data['variants'][0])]
        self.assertTrue(compile_book(data)['variants'][0]['model_verified'])
    def test_incomplete_order_rejected(self):
        data=copy.deepcopy(self.book);data['variants'][0]['order_status']='unknown'
        with self.assertRaises(ValueError):compile_book(data)
    def test_wrong_board_stops_instead_of_forcing_build(self):
        b=[[0]*10 for _ in range(20)];b[19][0]=1
        p=opener_plan(self.book,0,None,b,'I',(3,0,0),None,['L'],False,True,True)
        self.assertIsNone(p['result']);self.assertIn('CONDITION',p['reason'])
    def test_visible_hold_only_and_single_hold_limit(self):
        b=[[0]*10 for _ in range(20)]
        ok=opener_plan(self.book,0,None,b,'T',(3,0,0),'I',['L'],False,True,True)
        self.assertTrue(ok['result']['hold'])
        for used,available in ((True,True),(False,False)):
            self.assertIsNone(opener_plan(self.book,0,None,b,'T',(3,0,0),'I',['L'],used,available,True)['result'])
        self.assertIsNone(opener_plan(self.book,0,None,b,'T',(3,0,0),None,['?'],False,True,True)['result'])
    def test_tki_closed_loop_seven_simulated_placements(self):
        c=copy.deepcopy(C);c['auto_mode']='continuous';g=Game();steps=self.book['variants'][0]['steps'];g.kind=steps[0]['kind'];g.queue=[s['kind'] for s in steps[1:]]+list('ILOSZJT')*10
        r=Recognizer();b=FakeBackend(g.input);ctl=AutoController(KeyPulse(b),c);base=time.monotonic();ctl.start(99,base)
        for i in range(2500):
            now=base+i*.025;o=r.process(g.image(),(0,0,340,400),c,i,now)
            if ctl.running and o.valid and not ctl.plan and not ctl.wait:
                packet=opener_plan(self.book,ctl.blocks,ctl.opener_variant,o.fixed,o.active.kind,o.active.state,o.hold.kind,list(o.queue),ctl.hold_used,True,True);packet['key']=(o.board_key,o.active.kind,ctl.hold_used);ctl.accept_plan(packet,o)
            synthetic_tick(ctl,o,now)
            if not ctl.running:break
        self.assertEqual(ctl.blocks,7,ctl.reason);self.assertIn('OPENER_COMPLETE',ctl.reason);self.assertFalse(ctl.pulse.pressed)

    def test_opener_runtime_pipeline_seven_simulated_blocks(self):
        from runtime import Session
        from test_session import Source
        c=copy.deepcopy(C);c.update(opener_enabled=True,basic_auto_verified=True,opener_file=str(ROOT/'data/openers/TKI_Fonzie.json'),auto_mode='continuous')
        g=Game();steps=self.book['variants'][0]['steps'];g.kind=steps[0]['kind'];g.queue=[v['kind'] for v in steps[1:]]+list('ILOSZJT')*10;Source.game=g
        ctl=AutoController(KeyPulse(FakeBackend(g.input)),c);session=Session(c,ctl,None,Source);begin=time.monotonic()
        try:
            session.start();session.request_toggle(99);deadline=begin+12
            while time.monotonic()<deadline and not session.error and 'OPENER_COMPLETE' not in ctl.reason:time.sleep(.02)
            self.assertFalse(session.error,session.error);self.assertEqual(ctl.blocks,7,ctl.reason);self.assertIn('OPENER_COMPLETE',ctl.reason)
            print(f'OPENER_PIPELINE_SIMULATION seconds={time.monotonic()-begin:.3f} drops={g.drops} confirmed={ctl.blocks} real_game=False')
        finally:session.stop()
    def test_execution_gates_and_no_javascript_eval(self):
        from config import DEFAULT,validate
        from blox_import import import_variation
        c=copy.deepcopy(DEFAULT);c['opener_enabled']=True
        with self.assertRaises(ValueError):validate(c)
        with self.assertRaises(ValueError):import_variation('TKI:{Fonzie:{pieces:[alert(1)],seed:"x"}}','TKI','Fonzie','test://fixture')
