"""Retry screen grounding from saved actions, reusing local OCR caches."""

from openai import OpenAI

from src.services.annotation_render_service import render_annotation_preview
from src.services.annotation_review_service import create_pending_annotation_review
from src.services.annotation_service import parse_llm_suggestions
from src.services.grounded_screen_annotations import locate_grounded
from src.services.pipeline_v3_stages import _run_stage


def action(registry, settings):
    analysis = registry.load_json("annotation_action_analysis.json")
    suggestions = parse_llm_suggestions(analysis["response"], analysis["moments"])
    client = OpenAI(api_key=settings.openai_api_key, timeout=90, max_retries=5)
    items = locate_grounded(
        registry.job_dir / "raw_video.mp4", suggestions, registry, settings, client
    )
    report = registry.load_json("screen_analysis_report.json")
    report.update(
        items=items,
        automatic_count=sum(a["placement_confirmed"] for a in items),
        review_count=sum(not a["placement_confirmed"] for a in items),
        method="ocr_grounded",
    )
    registry.save_json("screen_analysis_report.json", report)
    doc = registry.load_json("annotation_suggestions.json")
    doc.update(
        suggestions=items,
        pending_review_count=report["review_count"],
        warnings=[f"Не определены уверенно: {report['review_count']} аннотаций"]
        if report["review_count"]
        else [],
    )
    registry.save_json("annotation_suggestions.json", doc)
    create_pending_annotation_review(registry, registry.job_dir.name)
    render_annotation_preview(
        registry.job_dir / "edited_video_with_subtitles.mp4",
        [a for a in items if a["placement_confirmed"]],
        registry.job_dir / "annotation_preview.mp4",
        settings,
        refine_anchors=False,
    )


print(_run_stage("job_20261006_065154", "annotations", action).to_dict())
