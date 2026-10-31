"""Retry saved annotation targets using local high-resolution OCR."""

from src.services.annotation_recovery import recover_annotations
from src.services.annotation_render_service import render_annotation_preview
from src.services.annotation_review_service import create_pending_annotation_review
from src.services.annotation_service import parse_llm_suggestions
from src.services.pipeline_v3_stages import _run_stage


def action(registry, settings):
    analysis = registry.load_json("annotation_action_analysis.json")
    suggestions = parse_llm_suggestions(analysis["response"], analysis["moments"])
    items = recover_annotations(registry.job_dir / "raw_video.mp4", suggestions, registry, settings)
    registry.save_json("annotation_recovery_result.json", {"items": items})
    pending = sum(not a.get("placement_confirmed") and not a.get("skipped") for a in items)
    report = {
        "items": items,
        "automatic_count": sum(a.get("placement_confirmed", False) for a in items),
        "review_count": pending,
        "skipped_count": sum(a.get("skipped", False) for a in items),
        "method": "local_ocr_verified",
        "warnings": [],
    }
    registry.save_json("screen_analysis_report.json", report)
    registry.save_json("grounded_analysis_progress.json", {"items": items})
    doc = registry.load_json("annotation_suggestions.json")
    doc.update(
        suggestions=items,
        pending_review_count=pending,
        warnings=[f"Не определены уверенно: {pending}"] if pending else [],
    )
    registry.save_json("annotation_suggestions.json", doc)
    create_pending_annotation_review(registry, registry.job_dir.name)
    render_annotation_preview(
        registry.job_dir / "edited_video_with_subtitles.mp4",
        [a for a in items if a.get("placement_confirmed")],
        registry.job_dir / "annotation_preview.mp4",
        settings,
        refine_anchors=False,
    )
    print({"placed": sum(a["placement_confirmed"] for a in items), "total": len(items)})


print(_run_stage("job_20261006_065154", "annotations", action).to_dict())
