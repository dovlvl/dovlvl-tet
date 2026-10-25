"""Same boards, queue, budget and rule checker for old/new policy processes."""
import argparse,sys,json,time,inspect,statistics
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str((root/args.source).resolve()),str(root/'src')]
    from strategy import auto_plan,metrics
    from geometry import advance,orientations,fits,settle,IKICKS,JLSTZ
    from scoring import award,tspin,ScoreState
    steps=json.loads((root/'data/openers/TKI_Fonzie.json').read_text(encoding='utf-8'))['variants'][0]['steps']
    slot=steps[-1]['expected_before']
    no_clear=[row[:] for row in slot]
    no_clear[18][9]=0;no_clear[19][9]=0
    low=[[0]*10 for _ in range(20)]
    for y in range(8,20):low[y][5]=1
    low[19]=[1]*8+[0,0]
    cases=[
      ('rotate_tetris_pc',[[0]*10 for _ in range(16)]+[[1]*9+[0] for _ in range(4)],'I',(3,0,0),None,[]),
      ('hold_tetris_pc',[[0]*10 for _ in range(16)]+[[1]*9+[0] for _ in range(4)],'O',(3,0,0),'I',['L','T']),
      ('tspin_double',slot,'T',(3,0,0),'I',['O']),
      ('tspin_without_clear',no_clear,'T',(3,0,0),'I',['O']),
      ('low_same_kind_hold',low,'O',(0,16,0),'O',[]),
      ('unknown_future',[[0]*10 for _ in range(18)]+[[1]*6+[0]*4 for _ in range(2)],'T',(3,0,0),'O',['?','O']),
      ('plain_flat',[[0]*10 for _ in range(20)],'L',(3,0,0),None,['T','O']),
    ]
    results=[]
    for name,board,kind,start,held,queue in cases:
        times=[];packet=None
        for _ in range(3):
            t=time.perf_counter()
            kwargs=dict(opening=False,budget_ms=200,max_depth=2,counterclockwise=True)
            if 'score_state' in inspect.signature(auto_plan).parameters:kwargs['score_state']=ScoreState(back_to_back=True,combo=1)
            packet=auto_plan(board,kind,start,held,queue,True,**kwargs)
            times.append((time.perf_counter()-t)*1000)
        a=packet['result'];event=None;legal=False
        if a:
            piece=a.get('kind',held if a['hold'] else kind);state=(3,0,0) if a['hold'] else start
            rotation=(False,0);soft=0
            for action in a['path'][:-1]:
                previous=state;state=advance(board,piece,state,action)
                if state is None:break
                if action in ('up','z'):
                    offsets=((0,0),) if piece=='O' else (IKICKS if piece=='I' else JLSTZ)[previous[2],state[2]]
                    kick=next((i for i,(dx,dy) in enumerate(offsets) if (previous[0]+dx,previous[1]-dy)==state[:2]),0)
                    rotation=(True,kick)
                else:rotation=(False,0)
                soft+=action=='down'
            if state is not None:
                x,y,r=state;drop=0
                while fits(board,orientations(piece)[r],x,y+drop+1):drop+=1
                after,lines=settle(board,orientations(piece)[r],x,y+drop)
                legal=set((x+dx,y+drop+dy) for dx,dy in orientations(piece)[r])==set(map(tuple,a['cells']))
                spin=tspin(board,piece,(x,y+drop,r),*rotation,drop_distance=drop)
                event=award(lines,spin,not any(map(any,after)),drop,soft,ScoreState(back_to_back=True,combo=1))
                event.pop('score_state')
        results.append(dict(name=name,board=board,current=kind,start=start,hold=held,next=queue,
                            search_mean_ms=statistics.mean(times),chosen=a,route_replayed=legal,
                            independent_model_projection=event,actual_site_score=None,
                            holes_after=metrics(a['board'])[1] if a else None,
                            future_status=packet.get('pc_future','no unobserved guarantee')))
    out=dict(source=args.source,budget_ms=200,depth=2,back_to_back_assumption=True,combo_assumption=1,
             rules='published site table; spin model, live judgment unverified; unpublished combo/PC bonuses zero',
             real_game_tested=False,cases=results)
    (root/args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps([dict(name=r['name'],lines=(r['chosen'] or {}).get('lines'),spin=(r['independent_model_projection'] or {}).get('spin'),points=(r['independent_model_projection'] or {}).get('expected_points'),legal=r['route_replayed']) for r in results]))

if __name__=='__main__':main()
