"""Offline before/after report for an unannotated RGB screenshot + capture JSON.
Usage: python preview_compare.py shot_raw.png shot.json --output comparison
Metadata: {capture_box:[left,top,right,bottom], config:{hold:...,next_slots:...}}
"""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image
from recognition import PreviewCache
from recognition_before_preview_fix import PreviewCache as Before

def compare(image,metadata,output):
    out=Path(output);out.mkdir(parents=True,exist_ok=True);rgb=np.asarray(Image.open(image).convert('RGB'));meta=json.loads(Path(metadata).read_text(encoding='utf-8-sig'));c=meta['config'];origin=meta.get('capture_box',[0,0,rgb.shape[1],rgb.shape[0]]);results=[]
    for name,box in [('hold',c['hold'])]+[(f'next{i}',b) for i,b in enumerate(c['next_slots'])]:
        item={'slot':name,'roi':box,'input_image':str(image),'input_provenance':meta.get('provenance','provided file; authenticity not verified')}
        if box is None:item['error']='unconfigured';results.append(item);continue
        x,y,r,b=box;x-=origin[0];r-=origin[0];y-=origin[1];b-=origin[1]
        if x<0 or y<0 or r>rgb.shape[1] or b>rgb.shape[0] or r<=x or b<=y:item['error']='ROI clipped/outside capture';results.append(item);continue
        crop=rgb[y:b,x:r];old=Before.classify(crop,0,c.get('min_s',.28),c.get('min_v',.28));new,debug=PreviewCache.analyze(crop,0,c.get('min_s',.28),c.get('min_v',.28))
        item.update(before=old.__dict__,after=new.__dict__,bbox=debug['bbox'],raw_shape=list(crop.shape))
        Image.fromarray(crop).save(out/(name+'_raw.png'))
        for key in ('mask','normalized'):Image.fromarray(debug[key]).save(out/(name+'_'+key+'.png'))
        results.append(item)
    (out/'comparison.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');return results
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('image');p.add_argument('metadata');p.add_argument('--output',default='preview_comparison');a=p.parse_args();print(json.dumps(compare(a.image,a.metadata,a.output),ensure_ascii=False,indent=2))
