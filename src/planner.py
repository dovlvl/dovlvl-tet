"""Small reachable-state beam: current placement + one NEXT, no long opener search."""
from collections import deque
from functools import lru_cache
from time import perf_counter
from geometry import orientations,advance,fits,settle,evaluate
from recognition import cellset

def landings(board,kind,start=(3,0,0),rotation=True):
    if not fits(board,orientations(kind)[start[2]],*start[:2]):return []
    queue=deque([(start,())]);seen={start};result={}
    while queue and len(seen)<400:
        state,path=queue.popleft();x,y,r=state;p=orientations(kind)[r];drop_y=y
        while fits(board,p,x,drop_y+1):drop_y+=1
        cells=cellset(kind,(x,drop_y,r));b,lines=settle(board,p,x,drop_y)
        item=dict(kind=kind,x=x,y=drop_y,r=r,cells=sorted(cells),board=b,lines=lines,path=path+('drop',),score=evaluate(b,lines))
        if cells not in result or len(path)<len(result[cells]['path']):result[cells]=item
        for key in (('left','right','up') if rotation else ('left','right')):
            new=advance(board,kind,state,key)
            if new is not None and new not in seen:seen.add(new);queue.append((new,path+(key,)))
    return list(result.values())

def route_to(board,kind,start,target,rotation=True):
    dest=frozenset(map(tuple,target))
    direct=next((a['path'] for a in landings(board,kind,start,rotation) if frozenset(a['cells'])==dest),None)
    if direct is not None:return direct
    # Explicit targets may require a tuck: descend and rotate using the same SRS.
    q=deque([(start,())]);seen={start}
    while q and len(seen)<2000:
        state,path=q.popleft();x,y,r=state;p=orientations(kind)[r];dy=y
        while fits(board,p,x,dy+1):dy+=1
        if cellset(kind,(x,dy,r))==dest:return path+('drop',)
        for action in (('left','right','down','up') if rotation else ('left','right','down')):
            new=advance(board,kind,state,action)
            if new is not None and new not in seen:seen.add(new);q.append((new,path+(action,)))
    return None

def plan(board,kind,start,held,nexts,use_hold,allow_hold=True,rotation=True):
    begin=perf_counter();choices=[(kind,False,start,list(nexts))]
    if use_hold and allow_hold and (held or nexts) and held!=kind:choices.append((held or nexts[0],True,(3,0,0),list(nexts) if held else list(nexts[1:])))
    best=None;nodes=0
    for k,hold,s,future in choices:
        options=landings(board,k,s,rotation)
        nodes+=len(options)
        for a in sorted(options,key=lambda item:item['score'],reverse=True)[:4]:
            a=dict(a);a['hold']=hold;a['next_hint']=None;a['depth']=1
            if future and future[0] in 'IJLOSTZ':
                follow=landings(a['board'],future[0],rotation=rotation);nodes+=len(follow)
                if follow:
                    nxt=max(follow,key=lambda item:item['score']);a['score']+=.6*nxt['score'];a['depth']=2
                    a['next_hint']={'kind':future[0],'cells':nxt['cells'],'hold':False}
            if best is None or a['score']>best['score']:best=a
    return dict(result=best,search_ms=(perf_counter()-begin)*1000,nodes=nodes)
