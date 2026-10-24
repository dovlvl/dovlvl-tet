"""Import one explicit Piece-array variation from a user-supplied Blox module.
Never eval JavaScript. Dynamic SuperShape / DPC / inferred orders are unsupported.
"""
import argparse,re,json,hashlib
from pathlib import Path
from geometry import orientations,fits,settle
from recognition import cellset
from openers import compile_book
COLORS={'teal':'I','yellow':'O','purple':'T','blue':'J','orange':'L','red':'Z','green':'S'}
BASE={'J':[(-1,-1),(-1,0),(0,0),(1,0)],'L':[(1,-1),(-1,0),(0,0),(1,0)],'S':[(1,-1),(-1,0),(0,0),(0,-1)],'Z':[(-1,-1),(1,0),(0,0),(0,-1)],'O':[(-.5,-.5),(-.5,.5),(.5,.5),(.5,-.5)],'I':[(-1.5,-.5),(-.5,-.5),(.5,-.5),(1.5,-.5)],'T':[(-1,0),(1,0),(0,0),(0,-1)]}
def import_variation(source,name,variation,url):
    # Explicit narrow subset. Reject instead of guessing at new bundle syntax.
    key=lambda value:r'(?:'+re.escape(json.dumps(value))+'|'+re.escape(value)+r')'
    m=re.search(key(name)+r':\{',source)
    if not m:raise ValueError('오프너를 찾지 못했습니다.')
    # Next opener cannot be crossed: named variation must begin in this object.
    start=m.end();depth=1;quoted=False;escaped=False;end=start
    for end in range(start,len(source)):
        char=source[end]
        if quoted:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char=='"':quoted=False
        elif char=='"':quoted=True
        elif char=='{':depth+=1
        elif char=='}':
            depth-=1
            if depth==0:break
    block=source[start:end]
    m=re.search(key(variation)+r':\{pieces:\[(.*?)\],seed:"([^"]*)"',block,re.S)
    if not m:raise ValueError('명시적 pieces+seed 변형이 아닙니다. SuperShape/분기 자료는 지원하지 않습니다.')
    arr=m[1];pattern=r'new Piece\((-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),"([a-z]+)"(?:,(\d))?\)'
    pieces=list(re.finditer(pattern,arr))
    if re.sub(pattern,'',arr).strip(' ,\n\r\t'):raise ValueError('미지원 생성자 또는 동적 데이터: 실행 거부')
    board=[[0]*10 for _ in range(20)];cleared=0;steps=[]
    for p in pieces:
        x,y=float(p[1]),float(p[2]);kind=COLORS[p[3]];r=int(p[4] or 0);half=-.5 if kind in 'IO' else 0;cells=[]
        for dx,dy in BASE[kind]:
            a,b=((dx,dy),(dy,-dx),(-dx,-dy),(-dy,dx))[r]
            cx,cy=x+a+half,y+b+half+cleared
            if not cx.is_integer() or not cy.is_integer():raise ValueError('정수 셀로 변환 불가')
            cells.append([int(cx),int(cy)])
        match=None
        for rr,shape in enumerate(orientations(kind)):
            xx=min(a for a,b in cells)-min(a for a,b in shape);yy=min(b for a,b in cells)-min(b for a,b in shape)
            if cellset(kind,(xx,yy,rr))==frozenset(map(tuple,cells)) and fits(board,shape,xx,yy):match=(xx,yy,rr);break
        if match is None:raise ValueError('원본 좌표 변환/겹침 검증 실패')
        xx,yy,rr=match;board,lines=settle(board,orientations(kind)[rr],xx,yy);cleared+=lines
        steps.append({'kind':kind,'cells':cells})
    data={'schema':'tetris-opener-v1','coordinates':'visible-10x20-x-right-y-down','name':name,'source':url,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'license_status':'No explicit redistribution license confirmed; public reference, not a license grant','support':'One explicit ordered placement array; not all bag orders; seed is reference only','source_seed':m[2],'variants':[{'name':variation,'order_status':'explicit','hold_policy':'visible-only-single-hold','source_hold_conditions':'Not enumerated by source; only immediate visible legal swap supported','steps':steps}]}
    data.update(rotation_system='SRS; execution r=clockwise, absolute target cells',completion='All explicit steps confirmed against expected_after; last TKI stage clears 2 lines',failure_conditions=['uncertain preview','fixed board mismatch','visible queue/hold mismatch','unreachable target','unconfirmed input'],source_reference='https://harddrop.com/wiki/TKI_3_Opening (listed by Blox; original page fetch timed out)')
    return compile_book(data)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('output');p.add_argument('--name',default='TKI');p.add_argument('--variation',default='Fonzie');p.add_argument('--url',required=True);a=p.parse_args()
    book=import_variation(Path(a.source).read_text(encoding='utf-8'),a.name,a.variation,a.url)
    Path(a.output).write_text(json.dumps(book,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'name':book['name'],'variants':len(book['variants']),'steps':len(book['variants'][0]['steps']),'real_game_verified':False},ensure_ascii=False))
