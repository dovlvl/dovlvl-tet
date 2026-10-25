"""OpenCV visual detector; window titles are never detection evidence."""
import cv2,numpy as np
from recognition import labels

def components(rgb):
    # Limit setup cost on large multi-monitor images. All returned coords are physical pixels.
    factor=max(1,rgb.shape[1]/1400);im=cv2.resize(rgb,(round(rgb.shape[1]/factor),round(rgb.shape[0]/factor))) if factor>1 else rgb
    hi=im.max(-1);lo=im.min(-1);mask=((hi<58)&((hi.astype(int)-lo)<24)).astype(np.uint8)
    count,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
    return [(float(area*factor*factor),[round(x*factor),round(y*factor),round((x+w)*factor),round((y+h)*factor)]) for x,y,w,h,area in stats[1:] if area>100]

def profile_fit(profile,count,ref_pad):
    n=len(profile);best=None
    for pad in range(max(0,round(n*.005)),max(2,round(n*.05))):
        cell=(n-2*pad)/count
        if cell<7:continue
        contrasts=[]
        for i in range(1,count):
            p=round(pad+i*cell);c=round(pad+(i-.5)*cell);band=max(1,round(cell*.07))
            contrasts.append(float(profile[max(0,p-band):min(n,p+band+1)].max()-np.median(profile[max(0,c-band):min(n,c+band+1)])))
        a=np.asarray(contrasts);fraction=float((a>2).mean());score=fraction+.3*min(1,float(np.maximum(a,0).mean())/25)-abs(pad-ref_pad)*.001
        if best is None or score>best[0]:best=(score,pad,fraction)
    return best

def fit_grid(rgb,box):
    x,y,r,b=box;crop=rgb[y:b,x:r];gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY).astype(np.float32)
    if min(gray.shape)<60:return None
    v=profile_fit(np.median(gray,axis=0),10,(r-x)*.02);h=profile_fit(np.median(gray,axis=1),20,(b-y)*.01)
    if not v or not h or v[2]<.65 or h[2]<.6:return None
    out=[x+v[1],y+h[1],r-v[1],b-h[1]]
    if not .46<=(out[2]-out[0])/(out[3]-out[1])<=.54:return None
    return (v[0]+h[0])/2,out

def split_next(rgb,box,default_count=1):
    x,y,r,b=box;crop=rgb[y:b,x:r];lab,_,_=labels(crop);rows=(lab>0).sum(1)>max(3,(r-x)*.03)
    # Close tiny mino-border gaps, not the gap between preview slots.
    kernel=np.ones((max(1,round((r-x)*.025)),1),np.uint8)
    rows=cv2.morphologyEx(rows.astype(np.uint8)[:,None],cv2.MORPH_CLOSE,kernel)[:,0]
    groups=[];start=None
    for i,v in enumerate(np.r_[rows,0]):
        if v and start is None:start=i
        if not v and start is not None:
            if i-start>=max(5,(r-x)*.07):groups.append((start,i))
            start=None
    inferred=not(1<=len(groups)<=6)
    if inferred:n=default_count;edges=[round((b-y)*i/n) for i in range(n+1)]
    else:
        centers=[(a+c)/2 for a,c in groups];edges=[0]+[round((a+c)/2) for a,c in zip(centers,centers[1:])]+[b-y]
    # Detect all boundaries before limiting: dividing a whole panel into one
    # requested slot would merge every visible piece into a single reading.
    return [[x,y+a,r,y+c] for a,c in zip(edges,edges[1:])][:default_count],inferred

def adjacent_panels(regions,board):
    x,y,r,b=board;bh=b-y;bw=r-x;left=[];right=[]
    for area,box in regions:
        a,c,d,e=box;w=d-a;h=e-c
        if w<20 or h<20 or area/(w*h)<.5:continue
        if d<=x and x-d<bw*1.1 and y<=c<y+bh*.35 and e<y+bh*.5:left.append((area,box))
        if a>=r and a-r<bw*1.1 and y<=c<y+bh*.4 and h<bh*.75:right.append((area,box))
    return left,right

def detect(rgb,origin=(0,0),default_count=1):
    regions=components(rgb);candidates=[]
    for area,box in regions:
        x,y,r,b=box;w=r-x;h=b-y
        if w<75 or h<160 or not .43<w/h<.57 or area/(w*h)<.5:continue
        fit=fit_grid(rgb,box)
        if fit:candidates.append((fit[0],area,fit[1],False))
        else:
            # A menu can hide every grid line. Keep geometry only when both
            # independent side panels anchor a plausible central 1:2 rectangle.
            left,right=adjacent_panels(regions,box)
            if left and right and .48<w/h<.52:
                l=max(left)[1];n=max(right)[1]
                if abs(l[1]-n[1])<h*.06 and abs((l[2]-l[0])-(n[2]-n[0]))<w*.25:
                    px=max(2,round(w*.02));py=max(2,round(h*.01))
                    candidates.append((.1,area,[x+px,y+py,r-px,b-py],True))
    result={'board':None,'hold':None,'next_slots':[],'confidence':{},'reasons':{},'next_count_inferred':False}
    if not candidates:result['reasons']['board']='10×20 격자/테두리 검증 실패: 가림·팝업·크기 또는 다른 화면';return result
    _,_,board,geometry_only=max(candidates);result['board']=board;result['geometry_only']=geometry_only;result['confidence']['board']=.65 if geometry_only else .9
    if geometry_only:result['reasons']['board']='구역 위치 확인: 메뉴/격자 가림. 실제 블록 판독 대기'
    left,right=adjacent_panels(regions,board)
    if left:
        a,c,d,e=max(left)[1];pad=max(2,round(min(d-a,e-c)*.04))
        result['hold']=[a+pad,c+pad,d-pad,e-pad];result['confidence']['hold']=.8
    else:result['reasons']['hold']='HOLD 내부 패널 미탐지: 해당 영역만 수동 지정 가능'
    if right:
        slots,inferred=split_next(rgb,max(right)[1],default_count);result['next_slots']=slots;result['next_count_inferred']=inferred;result['confidence']['next']=.65 if inferred else .85
    else:result['reasons']['next']='NEXT 패널/슬롯 미탐지: 해당 영역만 수동 지정 가능'
    dx,dy=origin
    def shift(box):return [box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy] if box else None
    result['board']=shift(result['board']);result['hold']=shift(result['hold']);result['next_slots']=[shift(z) for z in result['next_slots']]
    return result

def panel_occluded(rgb):
    step=max(1,(max(rgb.shape[:2])+299)//300);rgb=rgb[::step,::step]
    hi=rgb.max(-1);lo=rgb.min(-1);mask=((hi>=32)&(hi<200)&(hi.astype(int)-lo<15)).astype(np.uint8)
    _,_,stats,_=cv2.connectedComponentsWithStats(mask,8);height,width=rgb.shape[:2]
    return any(area>height*width*.12 and w>width*.45 and h>height*.15 for x,y,w,h,area in stats[1:])

def refine_saved_regions(rgb,origin,config):
    """Recover nearby panel interiors from saved rectangles including borders."""
    found=detect(rgb,origin,config.get('next_default_count',1))
    if found.get('geometry_only'):return {}
    old=config['board'];new=found['board']
    if not old or not new:return {}
    # Never switch to another board elsewhere in the captured image.
    tolerance=(old[2]-old[0])*.10
    if max(abs(a-b) for a,b in zip(old,new))>tolerance:return {}
    result={'board':new}
    for name in ('hold','next_slots'):
        if found[name]:result[name]=found[name]
    return result
