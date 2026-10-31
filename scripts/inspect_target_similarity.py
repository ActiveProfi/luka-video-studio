import json
from pathlib import Path
import cv2
from src.tools.annotation_toolkit.opencv_tools import extract_frame
p=Path('output/job_20261006_065154')
backup=sorted(p.glob('before_word_sync_*'))[-1]
old=json.loads((backup/'annotation_suggestions.json').read_text(encoding='utf-8'))['suggestions']
current=json.loads((p/'annotation_suggestions.json').read_text(encoding='utf-8'))['suggestions']
for ann in current:
    if ann['annotation_id'] not in ('ann_001','ann_005','ann_011'):
        continue
    prior=next(a for a in old if a['annotation_id']==ann['annotation_id'])
    b=prior['visual_evidence'][0]['anchor']
    def crop(t):
        f=extract_frame(p/'raw_video.mp4',t); h,w=f.shape[:2]
        return f[int(b['y']*h):int((b['y']+b['height'])*h),int(b['x']*w):int((b['x']+b['width'])*w)]
    a=crop(prior['target_start']); ae=cv2.Canny(cv2.cvtColor(a,cv2.COLOR_BGR2GRAY),70,150)>0
    rows=[]
    for offset in (.05,.2,.4,.6,.8):
        t=ann['speech_cue']['start']+offset
        c=crop(t); ce=cv2.Canny(cv2.cvtColor(c,cv2.COLOR_BGR2GRAY),70,150)>0
        rows.append([t,float(cv2.matchTemplate(c,a,cv2.TM_CCOEFF_NORMED)[0,0]),float(2*(ae&ce).sum()/max(1,ae.sum()+ce.sum()))])
    print(ann['annotation_id'],rows,flush=True)
