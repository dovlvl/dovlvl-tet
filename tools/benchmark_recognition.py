"""Prepared identical RGB corpus; excludes renderer and import/startup cost."""
import argparse,sys,time,json,statistics
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True);args=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str((root/args.source).resolve()),str(root/'tests')]
    from helpers import Game,C
    from recognition import Recognizer,cellset
    game=Game();images=[];truth=[]
    for i in range(240):
        game.state=(3,(i//3)%12,0);images.append(game.image());truth.append(cellset(game.kind,game.state))
    r=Recognizer()
    for i in range(2):r.process(images[0],(0,0,340,400),C,i,time.monotonic())
    times=[];valid=wrong=0
    for i,(image,expected) in enumerate(zip(images,truth),2):
        begin=time.perf_counter();o=r.process(image,(0,0,340,400),C,i,time.monotonic());times.append((time.perf_counter()-begin)*1000)
        valid+=o.valid;wrong+=bool(o.valid and (o.active.kind!='T' or o.active.cells!=expected or any(map(any,o.fixed))))
    times.sort()
    report=dict(source=args.source,kind='prepared_synthetic_rgb',frames=len(images),valid=valid,wrong_valid=wrong,
                mean_ms=statistics.mean(times),p50_ms=times[len(times)//2],p95_ms=times[int(.95*len(times))],
                rendered_before_timer=True,real_game=False)
    (root/args.out).write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':main()
