"""Replay recorded RGB frames without input. No claims about unavailable truth."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from PIL import Image
from recognition import Recognizer
from timing import MotionTracker

def replay(folder):
    r=Recognizer();m=MotionTracker();results=[]
    for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines():
        event=json.loads(line)
        if event['event']!='recorded_frame' or 'image_file' not in event:continue
        rgb=np.asarray(Image.open(folder/event['image_file']).convert('RGB'))
        o=r.process(rgb,event['box'],event['config'],event['seq'],event['captured'])
        m.update(o,event.get('controlled_action'))
        results.append(dict(seq=o.seq,captured=o.captured,generation=o.generation,valid=o.valid,
                            state=o.active.state if o.active else None,kind=o.active.kind if o.active else None,
                            reason=o.reason,gravity_cps=o.gravity_cps))
    return dict(frames=len(results),invalid=sum(not x['valid'] for x in results),
                truth_available=False,results=results)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    report=replay(a.folder);a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'}))
