"""Reuse individually verified targets only when lesson text and new spoken cues agree."""
import json
import shutil
from datetime import datetime

from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.annotation_review_service import create_pending_annotation_review, approve_annotation_review
from src.services.annotation_render_service import render_annotation_preview
from src.services.voice_word_timing import bind_spoken_cues, save_annotation_timing_report
from src.services.subtitle_burn_service import ensure_subtitled_studio_video
from src.services.pipeline_v3_stages import run_export_stage

s = get_settings()
r = ArtifactRegistry(s.job_output_dir('job_20261006_065154'))
assert r.load_json('pipeline_state.json')['status'] != 'running'
old = r.job_dir/'before_general_pronunciation_20261007_101543'
read = lambda name: json.loads((old/name).read_text(encoding='utf-8'))
before = read('annotation_action_analysis.json')
after = r.load_json('annotation_action_analysis.json')
assert [(m['segment_id'],m['text']) for m in before['moments']] == [(m['segment_id'],m['text']) for m in after['moments']]
doc = read('annotation_suggestions.json')
items = bind_spoken_cues(doc['suggestions'], r.load_json('voiceover_word_timing.json'))
for ann in items:
    if ann.get('skipped'):
        continue
    assert ann.get('placement_confirmed') and ann['speech_cue']
    assert -.001 <= ann['target_start']-ann['speech_cue']['start'] <= .35
    assert ann['target_end'] <= ann['speech_cue']['end'] + .35
    ann['frame_file'] = None  # Recreate thumbnails for these individual targets.
    ann['verification_reuse'] = 'Same original recording and lesson text; checked against new speech times'
backup = r.job_dir/('before_restore_verified_annotations_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
backup.mkdir()
state = r.load_json('pipeline_state.json')
state.update(status='running',current_stage='annotations',error=None)
r.save_json('pipeline_state.json',state)
for name in ('annotation_suggestions.json','screen_analysis_report.json','annotation_action_analysis.json'):
    if r.exists(name): shutil.copy2(r.artifact_path(name),backup/name)
doc.update(suggestions=items,pending_review_count=0,warnings=[])
r.save_json('annotation_suggestions.json',doc)
r.save_json('screen_analysis_report.json',{'items':items,'method':'verified_targets_rebound_to_final_speech',
    'automatic_count':12,'review_count':0,'skipped_count':1,'warnings':[]})
report = save_annotation_timing_report(r,items)
assert report['aligned_count'] == 12 and not report['unresolved_count']
create_pending_annotation_review(r,r.job_dir.name)
base = ensure_subtitled_studio_video(r,s)
render_annotation_preview(r.artifact_path(base),[a for a in items if a.get('placement_confirmed')],
    r.artifact_path('annotation_preview.mp4'),s,refine_anchors=False)
approve_annotation_review(r,r.job_dir.name,approved_by='automatic')
print(run_export_stage(r.job_dir.name).to_dict(),flush=True)
