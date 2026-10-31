"""Recheck out-of-order action groups, then render and update the review artifacts."""
from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.annotation_service import parse_llm_suggestions
from src.services.annotation_recovery import recover_annotations
from src.services.annotation_render_service import render_annotation_preview
from src.services.annotation_review_service import create_pending_annotation_review

settings=get_settings()
registry=ArtifactRegistry(settings.job_output_dir('job_20261006_065154'))
doc=registry.load_json('annotation_suggestions.json')
items=doc['suggestions']
groups={}
for a in items:
    groups.setdefault(a['linked_segment_id'],[]).append(a)
bad=set()
for key,group in groups.items():
    active=[a for a in group if a.get('placement_confirmed')]
    if any(a['target_end'] > b['target_start']+.05 for a,b in zip(active,active[1:])):
        bad.add(key)
analysis=registry.load_json('annotation_action_analysis.json')
original=parse_llm_suggestions(analysis['response'],analysis['moments'])
retry=[a for a in original if a['linked_segment_id'] in bad]
if retry:
    updated=recover_annotations(registry.job_dir/'raw_video.mp4',retry,registry,settings)
    by_id={a['annotation_id']:a for a in updated}
    items=[by_id.get(a['annotation_id'],a) for a in items]
pending=sum(not a.get('placement_confirmed') and not a.get('skipped') for a in items)
doc.update(suggestions=items,pending_review_count=pending,warnings=[] if not pending else ['Не все объекты подтверждены'])
registry.save_json('annotation_suggestions.json',doc)
registry.save_json('grounded_analysis_progress.json',{'items':items})
registry.save_json('screen_analysis_report.json',{
    'items':items,'automatic_count':sum(a.get('placement_confirmed',False) for a in items),
    'skipped_count':sum(a.get('skipped',False) for a in items),'review_count':pending,
    'method':'local_ocr_verified','warnings':[]})
create_pending_annotation_review(registry,registry.job_dir.name)
render_annotation_preview(registry.job_dir/'edited_video_with_subtitles.mp4',
                          [a for a in items if a.get('placement_confirmed')],
                          registry.job_dir/'annotation_preview.mp4',settings,refine_anchors=False)
print({'retimed_groups':len(bad),'pending':pending})
