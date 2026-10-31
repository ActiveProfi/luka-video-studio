"""Recheck existing screen targets inside measured spoken intervals and render."""
from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.annotation_service import parse_llm_suggestions
from src.services.annotation_recovery import recover_annotations
from src.services.annotation_render_service import render_annotation_preview
from src.services.annotation_review_service import create_pending_annotation_review, approve_annotation_review
from src.services.voice_word_timing import bind_spoken_cues, ensure_voice_word_timing, save_annotation_timing_report

settings = get_settings()
r = ArtifactRegistry(settings.job_output_dir("job_20261006_065154"))
timing = ensure_voice_word_timing(r, settings)
plan = r.load_json("annotation_action_analysis.json")
suggestions = bind_spoken_cues(parse_llm_suggestions(plan["response"], plan["moments"]), timing)
for ann in suggestions:
    print(ann["annotation_id"], ann["label"], ann["speech_cue"], flush=True)
old_items = {a['annotation_id']: a for a in r.load_json('annotation_suggestions.json')['suggestions']}
results = []
for ann in suggestions:
    old = old_items.get(ann['annotation_id'], {})
    if old.get('skipped') or (old.get('placement_confirmed') and old.get('speech_cue') == ann.get('speech_cue')):
        results.append(old)
    else:
        results.extend(recover_annotations(r.artifact_path("raw_video.mp4"), [ann], r, settings))
save_annotation_timing_report(r, results)
pending = sum(not a.get("placement_confirmed") and not a.get("skipped") for a in results)
doc = r.load_json("annotation_suggestions.json")
doc.update(suggestions=results, pending_review_count=pending,
           warnings=[] if not pending else ["Не все объекты совпали с моментом речи"])
r.save_json("annotation_suggestions.json", doc)
r.save_json("grounded_analysis_progress.json", {"items": results})
r.save_json("screen_analysis_report.json", {"items": results, "method": "ocr_and_measured_speech",
    "automatic_count": sum(a.get("placement_confirmed", False) for a in results),
    "review_count": pending, "skipped_count": sum(a.get("skipped", False) for a in results)})
create_pending_annotation_review(r, r.job_dir.name)
render_annotation_preview(r.artifact_path("edited_video_with_subtitles.mp4"),
    [a for a in results if a.get("placement_confirmed")], r.artifact_path("annotation_preview.mp4"),
    settings, refine_anchors=False)
if not pending:
    approve_annotation_review(r, r.job_dir.name, approved_by="automatic")
print({"pending": pending, "placed": sum(a.get("placement_confirmed", False) for a in results)}, flush=True)
