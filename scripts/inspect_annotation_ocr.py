import json
from pathlib import Path
import cv2
from src.services.grounded_screen_annotations import read_boxes, _reader
from src.tools.annotation_toolkit.opencv_tools import extract_frame

p = Path('output/job_20261006_065154')
output = {}
for t in [21.305, 105.69, 90.55, 61.805, 51.33]:
    frame = extract_frame(p/'raw_video.mp4', t)
    boxes = read_boxes(frame, p/'_ocr_cache')
    output[str(t)] = boxes
    if t == 90.55:
        cv2.imwrite(str(p/'amount_crop.png'), frame[263:311,350:528])
        output['amount_crop_read'] = [
            {'text': text, 'confidence': float(conf)}
            for _,text,conf in _reader().readtext(cv2.resize(frame[263:311,350:528],None,fx=3,fy=3),
                                               allowlist='0123456789., ')
        ]
(p/'ocr_diagnostic.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
print('Local OCR diagnostics saved')
