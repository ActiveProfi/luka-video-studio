import json
import cv2
from pathlib import Path
from src.tools.annotation_toolkit.opencv_tools import extract_frame
from src.services.grounded_screen_annotations import read_boxes
from src.services.annotation_target_matching import normalize_label

p=Path('output/job_20261006_065154')
f=extract_frame(p/'raw_video.mp4',18.95)
b=next(b['bbox'] for b in read_boxes(f,p/'_ocr_cache') if normalize_label(b['text'])=='главное')
h,w=f.shape[:2]
x,y=int(b['x']*w),int(b['y']*h)
r,d=int((b['x']+b['width'])*w),int((b['y']+b['height'])*h)
a=f[y:d,x:r]
ae=cv2.Canny(cv2.cvtColor(a,cv2.COLOR_BGR2GRAY),70,150)>0
rows=[]
for t in [18.91,18.95,19.1,19.3,19.5,19.7,20.0]:
    f=extract_frame(p/'raw_video.mp4',t)
    c=f[y:d,x:r]
    ce=cv2.Canny(cv2.cvtColor(c,cv2.COLOR_BGR2GRAY),70,150)>0
    rows.append({'t':t,'correlation':float(cv2.matchTemplate(c,a,cv2.TM_CCOEFF_NORMED)[0,0]),
                 'edges':float(2*(ae&ce).sum()/max(1,ae.sum()+ce.sum()))})
print(json.dumps(rows))
