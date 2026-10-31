"""Проверка и правка аннотаций по блокам (как cleanup_review для шага 3)."""

from __future__ import annotations

from typing import Any

from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.annotation_service import confirmed_suggestions
from src.services.annotation_render_service import PREVIEW_FILENAME, annotation_type_label
from src.services.annotation_service import build_lesson_moments

REVIEW_FILENAME = "annotation_review.json"
SUGGESTIONS_FILE = "annotation_suggestions.json"
APPROVED_FILE = "approved_annotations.json"


def annotation_suggestions_ready(registry: ArtifactRegistry) -> bool:
    return registry.exists(SUGGESTIONS_FILE)


def annotation_preview_ready(registry: ArtifactRegistry) -> bool:
    return registry.exists(PREVIEW_FILENAME)


def annotation_artifacts_ready(registry: ArtifactRegistry) -> bool:
    return (
        registry.exists(SUGGESTIONS_FILE)
        and registry.exists(PREVIEW_FILENAME)
        and registry.exists(REVIEW_FILENAME)
    )


def load_annotation_review(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    if registry.exists(REVIEW_FILENAME):
        return registry.load_json(REVIEW_FILENAME)
    if annotation_suggestions_ready(registry):
        return create_pending_annotation_review(registry, job_id)
    return {
        "job_id": job_id,
        "stage": "annotations_review",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "status": "pending",
        "approved_at": None,
        "approved_by": None,
        "last_saved_at": None,
        "blocks": [],
        "preview_video": PREVIEW_FILENAME,
    }


def create_pending_annotation_review(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    blocks = _build_blocks_from_job(registry)
    data = {
        "job_id": job_id,
        "stage": "annotations_review",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "status": "pending",
        "approved_at": None,
        "approved_by": None,
        "last_saved_at": None,
        "preview_video": PREVIEW_FILENAME,
        "blocks": blocks,
    }
    registry.save_json(REVIEW_FILENAME, data, "annotation_review.schema.json")
    return data


def annotation_review_approved(registry: ArtifactRegistry, job_id: str) -> bool:
    # Changing subtitle appearance invalidates the rendered preview, not the
    # verified objects or their times. Export recreates the preview automatically.
    if not (registry.exists(SUGGESTIONS_FILE) and registry.exists(REVIEW_FILENAME)):
        return False
    review = load_annotation_review(registry, job_id)
    return review.get("status") == "approved" and registry.exists(APPROVED_FILE)


def _build_blocks_from_job(registry: ArtifactRegistry) -> list[dict[str, Any]]:
    suggestions_doc = registry.load_json(SUGGESTIONS_FILE)
    suggestions = suggestions_doc.get("suggestions", [])
    moments = _load_moments(registry)

    by_segment: dict[str, list[dict]] = {}
    for ann in suggestions:
        seg_id = str(ann.get("linked_segment_id") or "")
        by_segment.setdefault(seg_id, []).append(ann)

    blocks: list[dict[str, Any]] = []
    used_ann_ids: set[str] = set()

    for idx, moment in enumerate(moments, start=1):
        seg_id = moment["segment_id"]
        block_anns = by_segment.get(seg_id, [])
        for ann in block_anns:
            used_ann_ids.add(str(ann.get("annotation_id", "")))
        blocks.append(
            {
                "block_id": seg_id,
                "block_index": idx,
                "segment_id": seg_id,
                "target_start": moment["target_start"],
                "target_end": moment["target_end"],
                "text": moment["text"],
                "annotations": [
                    {
                        "annotation_id": ann["annotation_id"],
                        "type": ann["type"],
                        "type_label": annotation_type_label(str(ann["type"])),
                        "label": ann.get("label", ""),
                        "target_start": ann.get("target_start"),
                        "target_end": ann.get("target_end"),
                        "style": ann.get("style", ""),
                    }
                    for ann in block_anns
                ],
                "user_comment": "",
            }
        )

    orphan = [a for a in suggestions if str(a.get("annotation_id", "")) not in used_ann_ids]
    if orphan:
        start = float(orphan[0].get("target_start", 0))
        end = max(float(a.get("target_end", start)) for a in orphan)
        blocks.append(
            {
                "block_id": "block_misc",
                "block_index": len(blocks) + 1,
                "segment_id": "",
                "target_start": round(start, 3),
                "target_end": round(end, 3),
                "text": "Прочие аннотации",
                "annotations": [
                    {
                        "annotation_id": ann["annotation_id"],
                        "type": ann["type"],
                        "type_label": annotation_type_label(str(ann["type"])),
                        "label": ann.get("label", ""),
                        "target_start": ann.get("target_start"),
                        "target_end": ann.get("target_end"),
                        "style": ann.get("style", ""),
                    }
                    for ann in orphan
                ],
                "user_comment": "",
            }
        )

    return blocks


def _load_moments(registry: ArtifactRegistry) -> list[dict[str, Any]]:
    clean = registry.load_json("clean_transcript.json")
    voiceover = registry.load_json("voiceover_segments.json")
    timeline_segments: list[dict] = []
    if registry.exists("timeline_map.json"):
        timeline_segments = registry.load_json("timeline_map.json").get("segments", [])
    return build_lesson_moments(
        clean.get("segments", []),
        voiceover.get("segments", []),
        timeline_segments,
    )


def _suggestion_to_edit_item(job_id: str, ann: dict[str, Any]) -> dict[str, Any]:
    frame_file = ann.get("frame_file")
    frame_url = f"/jobs/{job_id}/artifacts/{frame_file}" if frame_file else None
    ann_type = str(ann.get("type", "arrow"))
    return {
        "annotation_id": ann.get("annotation_id"),
        "target_start": ann.get("target_start"),
        "target_end": ann.get("target_end"),
        "text": ann.get("label", ""),
        "suggested_type": ann_type,
        "type_label": annotation_type_label(ann_type),
        "frame_url": frame_url,
        "frame_file": frame_file,
        "placement_confirmed": bool(ann.get("placement_confirmed")),
        "skipped": bool(ann.get("skipped")),
        "anchor": ann.get("anchor"),
        "arrow_direction": ann.get("arrow_direction") or "left",
        "arrow_length_ratio": ann.get("arrow_length_ratio") or 0.08,
        "reason": ann.get("reason", ""),
    }


def get_annotation_edit_payload(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    if not annotation_suggestions_ready(registry):
        raise FileNotFoundError("Сначала выполните этап «Аннотации»")

    # Reading UI state must never start a second render or alter placements.
    # Preview preparation belongs to the processing/approval actions.
    review = load_annotation_review(registry, job_id)
    suggestions_doc = registry.load_json(SUGGESTIONS_FILE)
    suggestions = suggestions_doc.get("suggestions", [])
    items = [_suggestion_to_edit_item(job_id, ann) for ann in suggestions]
    confirmed = sum(1 for i in items if i["placement_confirmed"])
    pending = sum(1 for i in items if not i["placement_confirmed"] and not i["skipped"])

    from src.services.ffmpeg_service import get_media_duration_seconds
    from src.services.media_paths import resolve_edited_video_path
    from src.services.subtitle_review_service import get_subtitle_edit_payload, subtitles_edit_ready
    from src.config import get_settings

    settings = get_settings()
    duration = 0.0
    # Шаг 4 обязан показывать субтитры: берём видео с прожигом, не «голое» edited_video
    from src.services.subtitle_burn_service import ensure_subtitled_studio_video

    studio_video = ensure_subtitled_studio_video(registry, settings, force=False)
    video_version = None
    try:
        studio_path = registry.artifact_path(studio_video)
        if not studio_path.exists():
            studio_path = resolve_edited_video_path(registry)
            studio_video = studio_path.name
        duration = float(get_media_duration_seconds(studio_path, settings) or 0.0)
        video_version = str(int(studio_path.stat().st_mtime))
    except Exception:
        studio_video = PREVIEW_FILENAME if registry.exists(PREVIEW_FILENAME) else "edited_video.mp4"
        preview_path = registry.artifact_path(studio_video)
        if preview_path.exists():
            video_version = str(int(preview_path.stat().st_mtime))

    subtitle_layout = None
    subtitle_cues: list[dict[str, Any]] = []
    if subtitles_edit_ready(registry):
        try:
            sub = get_subtitle_edit_payload(registry, job_id)
            subtitle_layout = sub.get("layout")
            subtitle_cues = list(sub.get("cues") or [])
        except Exception:
            subtitle_layout = None
            subtitle_cues = []

    return {
        "job_id": job_id,
        "review_status": review.get("status", "pending"),
        "last_saved_at": review.get("last_saved_at"),
        "approved_at": review.get("approved_at"),
        "preview_video_url": f"/jobs/{job_id}/artifacts/{PREVIEW_FILENAME}",
        "preview_video": PREVIEW_FILENAME,
        "studio_video_url": f"/jobs/{job_id}/artifacts/{studio_video}",
        "studio_video": studio_video,
        "video_version": video_version,
        "video_duration_seconds": duration,
        "suggestion_count": len(suggestions),
        "confirmed_count": confirmed,
        "pending_count": pending,
        "items": items,
        "blocks": review.get("blocks", []),
        "subtitle_layout": subtitle_layout,
        "subtitle_cues": subtitle_cues,
        # Прожиг уже в файле — оверлей в UI не дублируем
        "studio_has_subtitles": studio_video == "edited_video_with_subtitles.mp4"
        or bool(subtitle_cues),
        "studio_subtitles_burned": studio_video == "edited_video_with_subtitles.mp4",
    }


def save_annotation_review_comments(
    registry: ArtifactRegistry,
    job_id: str,
    blocks: list[dict[str, Any]],
    saved_by: str = "user",
) -> dict[str, Any]:
    if not annotation_suggestions_ready(registry):
        raise FileNotFoundError("annotation_suggestions.json не найден")

    review = load_annotation_review(registry, job_id)
    if review.get("status") == "approved":
        raise ValueError(
            "Аннотации уже подтверждены. Нажмите «Редактировать аннотации» на шаге 8."
        )

    by_id = {item["block_id"]: item for item in blocks if item.get("block_id")}
    updated = 0
    for block in review.get("blocks", []):
        block_id = block.get("block_id")
        if block_id not in by_id:
            continue
        new_comment = str(by_id[block_id].get("user_comment", "")).strip()
        if new_comment != block.get("user_comment", ""):
            updated += 1
        block["user_comment"] = new_comment

    review["last_saved_at"] = utc_now_iso()
    review["status"] = "pending"
    registry.save_json(REVIEW_FILENAME, review, "annotation_review.schema.json")
    payload = get_annotation_edit_payload(registry, job_id)
    payload["comments_updated"] = updated
    return payload


def approve_annotation_review(
    registry: ArtifactRegistry,
    job_id: str,
    blocks: list[dict[str, Any]] | None = None,
    approved_by: str = "user",
) -> dict[str, Any]:
    if blocks:
        save_annotation_review_comments(registry, job_id, blocks, saved_by=approved_by)

    if not annotation_suggestions_ready(registry):
        raise FileNotFoundError("annotation_suggestions.json не найден")

    # Prepare missing thumbnails before approval: loading the edit payload may
    # otherwise invalidate the approval we have just saved.
    _ensure_preview_and_review(registry, job_id)
    review = load_annotation_review(registry, job_id)
    suggestions_doc = registry.load_json(SUGGESTIONS_FILE)
    suggestions = suggestions_doc.get("suggestions", [])
    placed = confirmed_suggestions(suggestions)
    if any(not a.get("placement_confirmed") and not a.get("skipped") for a in suggestions):
        raise ValueError("Проверьте оставшиеся предложения: укажите объект или пропустите аннотацию.")
    if not placed and any(not a.get("skipped") for a in suggestions):
        raise ValueError(
            "Укажите координаты хотя бы для одной аннотации на стоп-кадре, затем подтвердите."
        )

    comments_by_block = {
        str(b.get("block_id", "")): str(b.get("user_comment", "")).strip()
        for b in review.get("blocks", [])
    }

    approved_items = []
    for ann in placed:
        seg_id = str(ann.get("linked_segment_id", ""))
        comment = comments_by_block.get(seg_id) or comments_by_block.get("block_misc", "")
        approved_items.append(
            {
                **ann,
                "approved": True,
                "block_comment": comment,
            }
        )

    review["status"] = "approved"
    review["approved_at"] = utc_now_iso()
    review["approved_by"] = approved_by
    registry.save_json(REVIEW_FILENAME, review, "annotation_review.schema.json")

    approved_doc = {
        "job_id": job_id,
        "stage": "annotations",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [SUGGESTIONS_FILE, REVIEW_FILENAME, PREVIEW_FILENAME],
        "status": "completed",
        "approved_at": utc_now_iso(),
        "approved_by": approved_by,
        "annotations": approved_items,
        "auto_approved_count": len(approved_items) if approved_by == "automatic" else 0,
        "pending_review_count": 0,
        "user_comments_count": sum(1 for c in comments_by_block.values() if c),
    }
    registry.save_json(APPROVED_FILE, approved_doc, "approved_annotations.schema.json")
    return get_annotation_edit_payload(registry, job_id)


def reopen_annotation_review(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    if not annotation_suggestions_ready(registry):
        raise FileNotFoundError("Сначала выполните этап «Аннотации»")

    review = load_annotation_review(registry, job_id)
    review["status"] = "pending"
    review["approved_at"] = None
    review["approved_by"] = None
    registry.save_json(REVIEW_FILENAME, review, "annotation_review.schema.json")

    if registry.exists(APPROVED_FILE):
        registry.artifact_path(APPROVED_FILE).unlink(missing_ok=True)

    return get_annotation_edit_payload(registry, job_id)


def _ensure_preview_and_review(registry: ArtifactRegistry, job_id: str) -> None:
    """Для старых job: дорисовать превью, кадры и блоки проверки."""
    from src.config import get_settings
    from src.services.annotation_frame_service import attach_frames_to_suggestions
    from src.services.annotation_render_service import render_annotation_preview
    from src.services.media_paths import resolve_edited_video_path

    suggestions_doc = registry.load_json(SUGGESTIONS_FILE)
    suggestions = list(suggestions_doc.get("suggestions", []))
    if not suggestions:
        raise FileNotFoundError("annotation_suggestions.json пуст")

    lesson_path = resolve_edited_video_path(registry)
    needs_frames = any(not s.get("frame_file") for s in suggestions)
    if needs_frames:
        suggestions = attach_frames_to_suggestions(lesson_path, registry.job_dir, suggestions)
        for item in suggestions:
            item.setdefault("placement_confirmed", False)
            if not item.get("placement_confirmed"):
                item["anchor"] = None
        suggestions_doc["suggestions"] = suggestions
        registry.save_json(SUGGESTIONS_FILE, suggestions_doc, "annotation_suggestions.schema.json")

    if not registry.exists(PREVIEW_FILENAME):
        render_annotation_preview(
            lesson_path,
            confirmed_suggestions(suggestions),
            registry.job_dir / PREVIEW_FILENAME,
            settings=get_settings(),
            refine_anchors=False,
        )

    if not registry.exists(REVIEW_FILENAME):
        create_pending_annotation_review(registry, job_id)

    # Подтверждение сбрасываем только если кадры пересобраны заново (координаты обнулены).
    # Иначе простое чтение данных шага 7 отменяло бы уже сделанное подтверждение.
    if not needs_frames:
        return

    if registry.exists(APPROVED_FILE):
        registry.artifact_path(APPROVED_FILE).unlink(missing_ok=True)

    review = registry.load_json(REVIEW_FILENAME)
    if review.get("status") == "approved":
        review["status"] = "pending"
        review["approved_at"] = None
        review["approved_by"] = None
        registry.save_json(REVIEW_FILENAME, review, "annotation_review.schema.json")
