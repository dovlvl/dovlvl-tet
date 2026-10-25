"""Reproducible source-vs-source benchmarks; synthetic frames, no real input.

Run each version in a fresh subprocess with --source to avoid module pollution.
Same external budget is reported for both; the old planner cannot enforce it.
"""
import argparse,sys,time,json,copy,platform,statistics,inspect,threading,zlib
from pathlib import Path


class Source:
    game=None
    lock=threading.RLock()
    truth={}
    def grab(self,box):
        import numpy as np
        from recognition import cellset
        with self.lock:
            rgb=self.game.image()[:box['height'],:box['width']]
            self.truth[zlib.adler32(rgb.tobytes())]=(tuple(map(tuple,self.game.board)),self.game.kind,cellset(self.game.kind,self.game.state))
            if len(self.truth)>512:self.truth.pop(next(iter(self.truth)))
        a=np.zeros((rgb.shape[0],rgb.shape[1],4),np.uint8);a[:,:,:3]=rgb[:,:,::-1];return a
    def close(self):pass


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',default='src');parser.add_argument('--out',required=True)
    parser.add_argument('--blocks',type=int,default=20);parser.add_argument('--repeats',type=int,default=10)
    parser.add_argument('--press-ms',type=int,default=35);parser.add_argument('--gap-ms',type=int,default=35)
    parser.add_argument('--budget-ms',type=int,default=160)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root/'tests'));sys.path.insert(0,str((root/args.source).resolve()))
    from planner import plan,route_to
    from strategy import position_score
    from geometry import fits,orientations,settle
    from recognition import Recognizer
    from helpers import C,Game,FakeBackend
    from controller import AutoController
    from input_win import KeyPulse
    from runtime import Session
    def stats(v):
        if not v:return {'n':0}
        v=sorted(v);return dict(n=len(v),mean=statistics.mean(v),p50=v[len(v)//2],p95=v[min(len(v)-1,int(len(v)*.95))],max=max(v))
    empty=[[0]*10 for _ in range(20)]
    cases=[('rotate_pc',[[0]*10 for _ in range(16)]+[[1]*9+[0] for _ in range(4)],'I',None,[]),
           ('hold_pc',[[0]*10 for _ in range(16)]+[[1]*9+[0] for _ in range(4)],'O','I',['L','T']),
           ('two_o_held',[[0]*10 for _ in range(18)]+[[1]*6+[0]*4 for _ in range(2)],'T','O',['O']),
           ('two_o_empty',[[0]*10 for _ in range(18)]+[[1]*6+[0]*4 for _ in range(2)],'T',None,['O','O']),
           ('repeat_queue',empty,'T',None,['T','T','T']),
           ('high_survival',[[0]*10 for _ in range(6)]+[[1]*8+[0,0] for _ in range(14)],'O','I',['T','S','Z'])]
    report={'source':args.source,'environment':{'platform':platform.platform(),'python':sys.version,'processor':platform.processor()},
            'external_budget_ms':160,'kind':'synthetic_and_mock_only','real_game':{'tested':False,'points':None,'pps':None},'cases':[]}
    bounded='budget_ms' in inspect.signature(plan).parameters
    for name,b,k,h,q in cases:
        timings=[];routes=[];success=0;pc=0;over=0;packet=None
        for _ in range(args.repeats):
            t=time.perf_counter();packet=plan(copy.deepcopy(b),k,(3,0,0),h,q,True,scorer=position_score,**({'budget_ms':args.budget_ms} if bounded else {}))
            elapsed=(time.perf_counter()-t)*1000;timings.append(elapsed);over+=elapsed>165
            a=packet['result']
            if not a:continue
            piece=a['kind'];t=time.perf_counter();path=route_to(b,piece,(3,0,0),a['cells']);routes.append((time.perf_counter()-t)*1000)
            if path is not None:success+=1
            pc+=bool(a['lines'] and not any(map(any,a['board']))) or packet.get('pc_status')=='found_confirmed_queue'
        report['cases'].append(dict(name=name,board=b,current=k,hold=h,next=q,search_ms=stats(timings),route_ms=stats(routes),
                                   route_success=success,attempts=args.repeats,pc_paths=pc,over_budget_5ms_tolerance=over,
                                   predicted_game_points=None,simulated_game_points=None,predicted_utility=packet['result']['score'],
                                   pc_status=packet.get('pc_status','not_implemented'),chosen=packet['result']))
    pipelines=[]
    for scenario in ('continuous','two_o_pc'):
        game=Game();game.queue=list('ILOSZJTTIO')*30
        if scenario=='two_o_pc':game.board=copy.deepcopy(cases[2][1]);game.kind='T';game.hold='O';game.queue=['O']+game.queue
        target=args.blocks if scenario=='continuous' else 2
        Source.game=game;Source.truth={};c=copy.deepcopy(C);c.update(basic_auto_verified=True,preview_verified=True,opener_enabled=False,press_ms=args.press_ms,gap_ms=args.gap_ms,search_budget_ms=args.budget_ms)
        report['pipeline_config']={k:c[k] for k in ('press_ms','gap_ms','capture_fps','vision_fps','search_budget_ms','search_depth')}
        def input_key(vk):
            with Source.lock:game.input(vk)
        backend=FakeBackend(input_key);ctl=AutoController(KeyPulse(backend),c);session=Session(c,ctl,None,Source)
        recognized_valid=0;valid_wrong=0;recognized_total=0
        original_process=Recognizer.process
        def recognize(recognizer,rgb,*a,**kw):
            nonlocal recognized_valid,valid_wrong,recognized_total
            o=original_process(recognizer,rgb,*a,**kw);recognized_total+=1
            with Source.lock:truth=Source.truth.get(zlib.adler32(rgb.tobytes()))
            if o.valid and truth:
                recognized_valid+=1
                valid_wrong+=(o.board_key,o.active.kind,o.active.cells)!=truth
            return o
        Recognizer.process=recognize
        cap=[];vision=[];search=[];acks=[];block=[];ages=[];route_ok=[];line_matches=[];pc_hits=[];invalid=0;seen=0;lastseq=-1;lastblock=0;start=0
        orig_emit=ctl.emit;orig_verify=ctl.verify
        def emit(action,obs,now):
            previous=ctl.wait;orig_emit(action,obs,now)
            if action=='drop' and previous is None and ctl.wait:
                x,y,r=obs.active.state;p=orientations(obs.active.kind)[r]
                while fits(obs.fixed,p,x,y+1):y+=1
                from recognition import cellset
                route_ok.append(ctl.plan is None or cellset(obs.active.kind,(x,y,r))==frozenset(map(tuple,ctl.plan['cells'])))
                expected,lines=settle(obs.fixed,p,x,y)
                line_matches.append(expected==game.board)
                pc_hits.append(lines>0 and not any(map(any,game.board)))
        def verify(obs,now):
            nonlocal lastblock
            w=ctl.wait;orig_verify(obs,now)
            if w and ctl.wait is None:
                acks.append((now-w['sent'])*1000)
                if w['action']=='drop':block.append((now-lastblock)*1000);lastblock=now
        ctl.emit=emit;ctl.verify=verify
        try:
            session.start();start=time.monotonic();lastblock=start;session.request_toggle(99)
            deadline=start+max(20,target*2)
            while time.monotonic()<deadline and not session.error and ctl.blocks<target:
                o=session.observations.get()
                if o and o.seq!=lastseq:
                    lastseq=o.seq;seen+=1;invalid+=not o.valid;cap.append(o.capture_ms);vision.append(o.vision_ms);ages.append((time.monotonic()-o.captured)*1000)
                if not ctl.running and ctl.blocks:break
                time.sleep(.002)
            elapsed=time.monotonic()-start
            final=dict(scenario=scenario,target_blocks=target,confirmed=ctl.blocks,drops=game.drops,seconds=elapsed,pps=ctl.blocks/max(.001,elapsed),
                       capture_ms=stats(cap),recognition_ms=stats(vision),input_ack_ms=stats(acks),block_ms=stats(block),frame_age_ms=stats(ages),
                       target_success=sum(route_ok),target_attempts=len(route_ok),predicted_board_matches=sum(line_matches),
                       pc_success=sum(pc_hits),pc_eligible_attempts=1 if scenario=='two_o_pc' else None,
                       observed_frames=seen,invalid_frames=invalid,invalid_includes_startup=True,topout=not fits(game.board,orientations(game.kind)[game.state[2]],*game.state[:2]),
                       recognition_ground_truth={'valid':recognized_valid,'wrong_valid':valid_wrong,'total':recognized_total},
                       error=session.error,reason=ctl.reason,predicted_game_points=None,simulated_game_points=None,real_game_points=None)
            if hasattr(session,'telemetry'):final['telemetry']=session.telemetry.snapshot()
            pipelines.append(final)
        finally:
            session.stop();Recognizer.process=original_process
    report['pipelines']=pipelines
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'output':args.out,'pipelines':[{k:p[k] for k in ('scenario','confirmed','seconds','pps','target_success','pc_success','error')} for p in pipelines]}))


if __name__=='__main__':main()
