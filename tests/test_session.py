import sys,time,copy,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from helpers import Game,FakeBackend,C
from controller import AutoController
from input_win import KeyPulse
from runtime import Session
class Source:
    game=None
    def grab(self,box):
        rgb=self.game.image()[:box['height'],:box['width']];a=np.zeros((rgb.shape[0],rgb.shape[1],4),np.uint8);a[:,:,:3]=rgb[:,:,::-1];return a
    def close(self):pass
class PipelineTests(unittest.TestCase):
    def test_board_only_pipeline_places_five_simulated_blocks(self):
        g=Game();Source.game=g;c=copy.deepcopy(C);c['hold']=None;c['next_slots']=[None];b=FakeBackend(g.input);ctl=AutoController(KeyPulse(b),c);s=Session(c,ctl,None,Source)
        try:
            s.start()
            with s.lock:ctl.start(99,time.monotonic())
            deadline=time.monotonic()+9
            while time.monotonic()<deadline and not s.error and ctl.running and ctl.blocks<5:time.sleep(.02)
            self.assertFalse(s.error,s.error);self.assertGreaterEqual(g.drops,5,ctl.reason);self.assertTrue(b.events)
            print(f'PIPELINE_SIMULATION seconds={time.monotonic()-(deadline-9):.3f} drops={g.drops} confirmed={ctl.blocks}')
            self.assertGreaterEqual(ctl.blocks,5);self.assertIsNotNone(s.observations.get());self.assertFalse(s.observations.get().hold.valid)
        finally:s.stop()
if __name__=='__main__':unittest.main()
