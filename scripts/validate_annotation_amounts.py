"""Revalidate numeric annotations against neighboring OCR headings locally."""

from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.annotation_render_service import render_annotation_preview
from src.services.annotation_review_service import create_pending_annotation_review
from src.services.grounded_screen_annotations import (
    disambiguate_amount,
    read_boxes,
    verify_local_hold,
)
from src.services.screen_annotation_service import accept_observations
from src.tools.annotation_toolkit.opencv_tools import extract_frame

settings = get_settings()
registry = ArtifactRegistry(settings.job_output_dir("job_20261006_065154"))
video = registry.job_dir / "raw_video.mp4"
doc = registry.load_json("annotation_suggestions.json")
for ann in doc["suggestions"]:
    context = str(ann.get("speech_context") or "")
    if "доход" not in context.lower():
        continue
    observations = ann.get("analysis_observations", [])
    start, end = min(o["time"] for o in observations), max(o["time"] for o in observations)
    resolved = {**ann, "placement_confirmed": False, "requires_review": True, "anchor": None}
    for obs in observations:
        if (
            not obs["visible"]
            or obs.get("confidence", 0) < settings.screen_annotation_auto_confidence
        ):
            continue
        boxes = read_boxes(extract_frame(video, obs["time"]), registry.job_dir / "_ocr_cache")
        original = next((b for b in boxes if b["bbox"] == obs["bbox"]), None)
        corrected = disambiguate_amount(original, boxes, context)
        if not corrected:
            continue
        witness = {**obs, "bbox": corrected["bbox"], "ocr_text": corrected["text"]}
        hold = verify_local_hold(video, witness, start, end)
        if hold:
            trial = accept_observations(
                ann, hold, [o["time"] for o in hold], settings.screen_annotation_auto_confidence
            )
            if trial["placement_confirmed"]:
                resolved = {**trial, "anchor_source": "vision_ocr_template"}
                break
    ann.update(resolved)
pending = sum(not a["placement_confirmed"] for a in doc["suggestions"])
doc.update(
    pending_review_count=pending,
    warnings=[f"Не определены уверенно: {pending} аннотаций"] if pending else [],
)
registry.save_json("annotation_suggestions.json", doc)
report = registry.load_json("screen_analysis_report.json")
report.update(
    items=doc["suggestions"],
    automatic_count=len(doc["suggestions"]) - pending,
    review_count=pending,
)
registry.save_json("screen_analysis_report.json", report)
registry.save_json("grounded_analysis_progress.json", {"items": doc["suggestions"]})
create_pending_annotation_review(registry, registry.job_dir.name)
render_annotation_preview(
    registry.job_dir / "edited_video_with_subtitles.mp4",
    [a for a in doc["suggestions"] if a["placement_confirmed"]],
    registry.job_dir / "annotation_preview.mp4",
    settings,
    refine_anchors=False,
)
print({"automatic_count": report["automatic_count"], "review_count": pending})
