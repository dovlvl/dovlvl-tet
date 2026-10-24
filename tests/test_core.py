import unittest,time,copy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from helpers import *
from recognition import Recognizer,PreviewCache,sample_board
from input_win import KeyPulse,VK
from controller import AutoController
from planner import plan,landings,route_to
from geometry import rotate
from config import validate,save,load
class RecognitionTests(unittest.TestCase):
    def setUp(self):self.r=Recognizer();self.board=[[0]*10 for _ in range(20)];self.seq=0
    def read(self,**kw):
        self.seq+=1;return self.r.process(scene(self.board,**kw),(0,0,340,400),C,self.seq,time.monotonic())
    def test_order_and_empty_hold(self):
        o=self.read();self.assertTrue(o.hold.valid);self.assertIsNone(o.hold.kind);self.assertEqual(o.queue,('I','L','O'))
    def test_preview_aspect_preserved_when_resizing(self):
        from PIL import Image
        rgb=scene(self.board)
        for factor in (.7,1.3,1.8):
            big=np.array(Image.fromarray(rgb).resize((round(340*factor),round(400*factor))))
            c=dict(C)
            c['board']=[round(v*factor) for v in C['board']];c['hold']=[round(v*factor) for v in C['hold']];c['next_slots']=[[round(v*factor) for v in b] for b in C['next_slots']]
            o=Recognizer().process(big,(0,0,big.shape[1],big.shape[0]),c,1,time.monotonic())
            self.assertEqual(o.queue,('I','L','O'))
    def test_all_previews(self):
        for k in 'IJLOSTZ':
            o=self.read(held=k,nexts=(k,k,k));self.assertEqual(o.hold.kind,k);self.assertEqual(o.queue,(k,k,k))
    def test_ghost_excluded(self):
        o=self.read(ghost=True);self.assertTrue(o.ghost);self.assertEqual(sum(map(sum,o.fixed)),0)
    def test_active_excluded(self):
        o=self.read();self.assertEqual(len(o.active.cells),4);self.assertEqual(sum(map(sum,o.fixed)),0)
    def test_hold_exchange(self):
        self.read(kind='T',held='I');o=self.read(kind='I',held='T');self.assertEqual(o.active.kind,'I');self.assertEqual(o.hold.kind,'T');self.assertFalse(any(map(any,o.fixed)))
    def test_lock_and_new_spawn(self):
        self.read(kind='T');self.board[19][0:4]=[1]*4
        o=self.read(kind='I');self.assertEqual(o.active.kind,'I');self.assertEqual(sum(map(sum,o.fixed)),4)
    def test_empty_ready_but_no_active(self):
        o=self.read(kind=None);self.assertIsNone(o.active);self.assertEqual(sum(map(sum,o.fixed)),0);self.assertGreater(o.fixed_confidence,.9)
    def test_uncertain_never_guesses_preview(self):
        rgb=scene(self.board);rgb[0:80,220:320]=255
        o=self.r.process(rgb,(0,0,340,400),C,1,time.monotonic());self.assertFalse(o.hold.valid);self.assertIsNone(o.hold.kind)
    def test_preview_cache_timestamp(self):
        a=self.read();time.sleep(.002);b=self.read();self.assertEqual(a.hold.updated,b.hold.updated);self.assertGreater(b.hold.seen,a.hold.seen)
    def test_mixed_preview_rejected(self):
        rgb=scene(self.board);rgb[130:145,280:295]=(220,0,20)
        o=self.r.process(rgb,(0,0,340,400),C,1,time.monotonic());self.assertFalse(o.nexts[0].valid)
    def test_stability_two_frames(self):
        self.assertFalse(self.read().valid);self.assertTrue(self.read().valid)
class InputTests(unittest.TestCase):
    def setUp(self):self.b=FakeBackend();self.p=KeyPulse(self.b);self.p.arm(99)
    def test_all_actions_key_down_up(self):
        for i,k in enumerate(C['keys'].values()):
            self.assertTrue(self.p.press(k,i,35,35));self.p.tick(i+.04)
        self.assertEqual(len(self.b.events),14);self.assertFalse(self.p.pressed)
    def test_focus_loss_releases(self):
        self.p.press('LEFT',0,100,35);self.b.focus=2
        with self.assertRaises(RuntimeError):self.p.tick(.01)
        self.assertEqual(self.b.events[-1],(VK['LEFT'],False));self.assertFalse(self.p.pressed)
    def test_cancel_blocks_new_input(self):
        self.p.press('Z',0,100,35);self.p.cancel()
        with self.assertRaises(RuntimeError):self.p.press('C',1,35,35)
        self.assertFalse(self.p.pressed)
    def test_focus_before_press(self):
        self.b.focus=2
        with self.assertRaises(RuntimeError):self.p.press('LEFT',0,35,35)
        self.assertFalse(self.b.events)
    def test_backend_failure_releases(self):
        class Broken(FakeBackend):
            def key(self,vk,down):
                super().key(vk,down)
                if down:raise OSError('injected')
        b=Broken();p=KeyPulse(b);p.arm(99)
        with self.assertRaises(OSError):p.press('RIGHT',0,35,35)
        self.assertFalse(p.pressed);self.assertFalse(b.events[-1][1])
class PlannerTests(unittest.TestCase):
    def test_four_lines(self):
        b=[[0]*10 for _ in range(16)]+[[1]*9+[0] for _ in range(4)]
        a=plan(b,'I',(3,0,0),None,[],False)['result'];self.assertEqual(a['lines'],4)
    def test_all_reachable_paths(self):
        b=[[0]*10 for _ in range(20)]
        for kind in 'IJLOSTZ':
            for a in landings(b,kind):
                st=(3,0,0)
                for k in a['path'][:-1]:st=advance(b,kind,st,k);self.assertIsNotNone(st)
                x,y,r=st
                while fits(b,orientations(kind)[r],x,y+1):y+=1
                self.assertEqual(cellset(kind,(x,y,r)),frozenset(a['cells']))
    def test_hold_chosen_for_well(self):
        b=[[0]*10 for _ in range(16)]+[[1]*9+[0] for _ in range(4)]
        a=plan(b,'O',(3,0,0),'I',[],True)['result'];self.assertTrue(a['hold']);self.assertEqual(a['lines'],4)
    def test_srs_floor_kick(self):
        st,kick=rotate([[0]*10 for _ in range(20)],'T',(3,18,0));self.assertEqual(st,(2,17,1));self.assertEqual(kick,2)
    def test_srs_inverse_turn(self):
        b=[[0]*10 for _ in range(20)]
        for k in 'IJLSTZ':
            for r in range(4):
                st=(3,5,r);out=rotate(b,k,st)[0];self.assertEqual(rotate(b,k,out,-1)[0],st)

class ControlTests(unittest.TestCase):
    def make_obs(self,game,seq,now):return self.r.process(game.image(),(0,0,340,400),C,seq,now)
    def setUp(self):self.r=Recognizer()
    def test_closed_loop_15_drops(self):
        game=Game();b=FakeBackend(game.input);ctl=AutoController(KeyPulse(b),C);base=time.monotonic();ctl.start(99,base)
        for i in range(1600):
            now=base+i*.02;o=self.make_obs(game,i,now)
            if o.valid and ctl.running and not ctl.plan and not ctl.wait:
                packet=plan(o.fixed,o.active.kind,o.active.state,o.hold.kind,list(o.queue),True,not ctl.hold_used)
                packet['key']=(o.board_key,o.active.kind,ctl.hold_used);ctl.accept_plan(packet,o)
            synthetic_tick(ctl,o,now)
            if game.drops>=15 and ctl.wait is None:break
        self.assertTrue(ctl.running,ctl.reason);self.assertGreaterEqual(game.drops,15);ctl.stop();self.assertFalse(ctl.pulse.pressed)
    def test_failed_move_not_acknowledged(self):
        g=Game();b=FakeBackend();ctl=AutoController(KeyPulse(b),C);t=time.monotonic();ctl.start(99,t)
        o=self.make_obs(g,1,t);o=self.make_obs(g,2,t+.01);synthetic_emit(ctl,'left',o,t+.02)
        later=self.make_obs(g,3,t+.4);synthetic_tick(ctl,later,t+.4)
        self.assertEqual(ctl.failures,1);self.assertIsNone(ctl.plan);self.assertIsNone(ctl.wait)
    def test_drop_waits_for_visible_transition(self):
        g=Game();ctl=AutoController(KeyPulse(FakeBackend()),C);t=time.monotonic();ctl.start(99,t)
        o=self.make_obs(g,1,t);o=self.make_obs(g,2,t+.01);synthetic_emit(ctl,'drop',o,t+.02)
        for i in range(3,10):synthetic_tick(ctl,self.make_obs(g,i,t+i*.03),t+i*.03)
        self.assertEqual(ctl.phase,'WAIT_DROP');self.assertIsNotNone(ctl.wait)
        synthetic_tick(ctl,self.make_obs(g,11,t+3),t+3);self.assertFalse(ctl.running)
    def test_uncertainty_timeout(self):
        ctl=AutoController(KeyPulse(FakeBackend()),C);t=time.monotonic();ctl.start(99,t);synthetic_tick(ctl,None,t+4);self.assertFalse(ctl.running)
    def test_own_window_rejected(self):
        ctl=AutoController(KeyPulse(FakeBackend()),C)
        with self.assertRaises(ValueError):ctl.start(1,time.monotonic())
class ConfigTests(unittest.TestCase):
    def test_independent_regions_and_order(self):validate(C,True)
    def test_overlap_rejected(self):
        c=copy.deepcopy(C);c['hold']=c['board']
        with self.assertRaises(ValueError):validate(c,True)
    def test_reversed_next_rejected(self):
        c=copy.deepcopy(C);c['next_slots'].reverse()
        with self.assertRaises(ValueError):validate(c,True)
    def test_save_empty_screen_config(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json';save(C,p);self.assertEqual(load(p)['next_slots'],C['next_slots'])

class NativeInputEncodingTests(unittest.TestCase):
    def test_extended_arrow_and_release_flags(self):
        from input_win import keyboard_event
        down=keyboard_event(VK['LEFT'],True,0x4b);up=keyboard_event(VK['LEFT'],False,0x4b)
        self.assertEqual(down.type,1);self.assertEqual(down.ki.dwFlags,0x9);self.assertEqual(up.ki.dwFlags,0xb)
        self.assertEqual(up.ki.wScan,0x4b)
    def test_letter_scancode(self):
        from input_win import keyboard_event
        event=keyboard_event(VK['Z'],True,0x2c);self.assertEqual(event.ki.dwFlags,8)
    @unittest.skipUnless(sys.platform=='win32','Windows ABI only; Linux mock tests are not a native ABI check')
    def test_windows_input_struct_size(self):
        import ctypes
        from input_win import INPUT
        self.assertEqual(ctypes.sizeof(INPUT),40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)

class TransitionRegressionTests(unittest.TestCase):
    def test_hold_ack_requires_observation(self):
        r=Recognizer();g=Game();g.hold='I';b=FakeBackend(g.input);ctl=AutoController(KeyPulse(b),C);t=time.monotonic();ctl.start(99,t)
        for i in range(2):o=r.process(g.image(),(0,0,340,400),C,i,t+i*.01)
        synthetic_emit(ctl,'hold',o,t+.03)
        self.assertFalse(ctl.hold_used)
        for i in range(2,6):
            now=t+i*.05;o=r.process(g.image(),(0,0,340,400),C,i,now);synthetic_tick(ctl,o,now)
        self.assertTrue(ctl.hold_used);self.assertEqual(g.kind,'I');self.assertEqual(g.hold,'T');self.assertIsNone(ctl.wait)
    def test_same_kind_drop_and_queue_advance(self):
        r=Recognizer();g=Game();g.queue=['T','I','L','O'];b=FakeBackend(g.input);ctl=AutoController(KeyPulse(b),C);t=time.monotonic();ctl.start(99,t)
        for i in range(2):o=r.process(g.image(),(0,0,340,400),C,i,t+i*.01)
        synthetic_emit(ctl,'drop',o,t+.03)
        self.assertEqual(ctl.phase,'WAIT_DROP')
        for i in range(2,6):
            now=t+i*.05;o=r.process(g.image(),(0,0,340,400),C,i,now);synthetic_tick(ctl,o,now)
        self.assertTrue(ctl.running);self.assertIsNone(ctl.wait);self.assertEqual(g.kind,'T')
    def test_gravity_does_not_invalidate_target_signature(self):
        from runtime import Session
        g=Game();r=Recognizer();a=r.process(g.image(),(0,0,340,400),C,1,time.monotonic());g.state=(3,1,0);b=r.process(g.image(),(0,0,340,400),C,2,time.monotonic())
        p=Session(C,None);self.assertEqual(p.signature(a,False),p.signature(b,False))

if __name__=='__main__':unittest.main()
