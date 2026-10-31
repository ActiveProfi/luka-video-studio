"""Save local QA frames for the automatically confirmed annotations."""

import json
from pathlib import Path

import cv2

from src.services.annotation_render_service import _paint_frame
from src.tools.annotation_toolkit.opencv_tools import extract_frame

job = Path("output/job_20261006_065154")
doc = json.loads((job / "grounded_analysis_progress.json").read_text(encoding="utf-8"))
out = job / "annotation_qa"
out.mkdir(exist_ok=True)
for ann in doc["items"]:
    if not ann.get("placement_confirmed"):
        continue
    time = (ann["target_start"] + ann["target_end"]) / 2
    frame = extract_frame(job / "edited_video_with_subtitles.mp4", time)
    h, w = frame.shape[:2]
    result = _paint_frame(frame, [ann], time, w, h)
    cv2.imwrite(str(out / (ann["annotation_id"] + ".jpg")), result)
print("Saved confirmed annotation QA frames")
