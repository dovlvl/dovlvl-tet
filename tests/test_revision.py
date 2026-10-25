import copy
import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from helpers import C,Game,FakeBackend,synthetic_tick
from recognition import Recognizer
from controller import AutoController
from input_win import KeyPulse
from planner import plan


class RevisionTests(unittest.TestCase):
    def test_pc_pruning_preserves_empty_gaps_between_occupied_rows(self):
        b=[[0]*10 for _ in range(20)]
        b[17]=[1]*6+[0]*4;b[19]=[1]*6+[0]*4
        from planner import pc_row_bound
        # This passes a necessary condition; it is not a claimed PC solution.
        self.assertTrue(pc_row_bound(b,2))

    def test_automatic_preview_confirmation_requires_three_frames(self):
        c=copy.deepcopy(C);c['preview_verified']=False
        r=Recognizer();g=Game();ctl=AutoController(KeyPulse(FakeBackend()),c)
        for i in range(3):
            o=r.process(g.image(),(0,0,340,400),c,i,time.monotonic())
            self.assertEqual(o.hold_stable,i+1)
            self.assertEqual(o.next_stable,i+1)
            self.assertEqual(ctl.hold_clear(o),i==2)
        g.hold='I'
        o=r.process(g.image(),(0,0,340,400),c,3,time.monotonic())
        self.assertEqual(o.hold_stable,1);self.assertFalse(ctl.hold_clear(o))

    def test_stale_search_is_not_an_input_failure(self):
        ctl=AutoController(KeyPulse(FakeBackend()),C)
        ctl.start(99,time.monotonic())
        for _ in range(12):ctl.replan('stale search',count_failure=False)
        self.assertTrue(ctl.running)
        self.assertEqual(ctl.failures,0)
        ctl.stop()

    def test_filled_hold_does_not_require_unneeded_next(self):
        from model import Reading
        r=Recognizer();g=Game();g.hold='O'
        o=r.process(g.image(),(0,0,340,400),C,0,time.monotonic())
        o.nexts=[Reading(None,0,0,False)]
        ctl=AutoController(KeyPulse(FakeBackend()),C)
        self.assertTrue(ctl.hold_clear(o))
        o.hold=Reading(None,.97,0,True,state='empty')
        self.assertFalse(ctl.hold_clear(o))

    def test_same_kind_filled_hold_is_dominated(self):
        b=[[0]*10 for _ in range(20)]
        p=plan(b,'O',(3,0,0),'O',[],True,max_depth=1,budget_ms=300)
        self.assertFalse(p['result']['hold'])
        self.assertEqual(p['hold_candidates'],0)

    def test_hold_confirmation_keeps_target_without_second_search(self):
        g=Game();g.kind='T';g.hold='I'
        g.board=[[0]*10 for _ in range(16)]+[[1]*9+[0] for _ in range(4)]
        r=Recognizer();ctl=AutoController(KeyPulse(FakeBackend(g.input)),copy.deepcopy(C))
        now=time.monotonic();ctl.start(99,now);submitted=0
        for i in range(300):
            t=now+i*.02;o=r.process(g.image(),(0,0,340,400),C,i,t)
            if o.valid and not ctl.plan and not ctl.wait:
                if submitted:break
                p=plan(o.fixed,o.active.kind,o.active.state,'I',[],True,budget_ms=300)
                self.assertTrue(p['result']['hold'])
                p['key']=(o.board_key,o.active.kind,False);ctl.accept_plan(p,o);submitted+=1
            synthetic_tick(ctl,o,t)
            if ctl.blocks:break
        self.assertEqual(ctl.blocks,1,ctl.reason)
        self.assertEqual(submitted,1)
        self.assertFalse(any(map(any,g.board)))
        ctl.stop()


if __name__=='__main__':unittest.main()
