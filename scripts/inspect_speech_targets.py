import json
from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.grounded_screen_annotations import read_boxes
from src.services.annotation_target_matching import candidates
from src.tools.annotation_toolkit.opencv_tools import extract_frame

r = ArtifactRegistry(get_settings().job_output_dir('job_20261006_065154'))
for ann in r.load_json('annotation_suggestions.json')['suggestions']:
    if ann['annotation_id'] not in ('ann_001', 'ann_002', 'ann_005', 'ann_006', 'ann_011'):
        continue
    t = ann['speech_cue']['start'] + .05
    frame = extract_frame(r.artifact_path('raw_video.mp4'), t)
    boxes = read_boxes(frame, r.job_dir / '_ocr_cache')
    found = candidates(frame, boxes, ann, r.job_dir / '_ocr_roi_cache')
    print(json.dumps({'id': ann['annotation_id'], 'found': found,
          'text': [b['text'] for b in boxes]}, ensure_ascii=False), flush=True)
