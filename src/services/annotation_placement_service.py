"""Сохранение координат аннотаций, подтверждённых пользователем."""

from __future__ import annotations

from typing import Any

from src.config import get_settings
from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.annotation_service import confirmed_suggestions
from src.services.annotation_render_service import PREVIEW_FILENAME, render_annotation_preview
from src.services.media_paths import resolve_edited_video_path

SUGGESTIONS_FILE = "annotation_suggestions.json"

ARROW_DIRECTIONS = frozenset({"top", "bottom", "left", "right"})
RECT_TYPES = frozenset({"highlight_rect", "frame", "zoom"})


def _clamp01(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def normalize_placement_payload(raw: dict[str, Any]) -> dict[str, Any]:
    ann_type = str(raw.get("type", "arrow")).strip()
    if ann_type == "frame":
        ann_type = "highlight_rect"

    skipped = bool(raw.get("skipped", False))
    if skipped:
        return {"skipped": True, "placement_confirmed": False, "type": ann_type}

    x = _clamp01(float(raw.get("x", 0)))
    y = _clamp01(float(raw.get("y", 0)))

    if ann_type == "arrow":
        direction = str(raw.get("arrow_direction", "left")).strip().lower()
        if direction not in ARROW_DIRECTIONS:
            direction = "left"
        length = _clamp01(float(raw.get("arrow_length_ratio", 0.08)), 0.03, 0.25)
        return {
            "type": "arrow",
            "placement_confirmed": True,
            "skipped": False,
            "anchor": {"x": round(x, 5), "y": round(y, 5), "width": 0.0, "height": 0.0},
            "arrow_direction": direction,
            "arrow_length_ratio": round(length, 4),
        }

    width = _clamp01(float(raw.get("width", 0.15)), 0.02, 1.0)
    height = _clamp01(float(raw.get("height", 0.08)), 0.02, 1.0)
    if x + width > 1.0:
        width = max(0.02, 1.0 - x)
    if y + height > 1.0:
        height = max(0.02, 1.0 - y)

    return {
        "type": ann_type,
        "placement_confirmed": True,
        "skipped": False,
        "anchor": {
            "x": round(x, 5),
            "y": round(y, 5),
            "width": round(width, 5),
            "height": round(height, 5),
        },
    }


from src.services.annotation_service import confirmed_suggestions


def save_annotation_placement(
    registry: ArtifactRegistry,
    job_id: str,
    annotation_id: str,
    placement: dict[str, Any],
    *,
    saved_by: str = "user",
) -> dict[str, Any]:
    if not registry.exists(SUGGESTIONS_FILE):
        raise FileNotFoundError("annotation_suggestions.json не найден")

    from src.services.annotation_review_service import load_annotation_review

    review = load_annotation_review(registry, job_id)
    if review.get("status") == "approved":
        raise ValueError("Аннотации уже подтверждены. Нажмите «Редактировать аннотации».")

    normalized = normalize_placement_payload(placement)
    doc = registry.load_json(SUGGESTIONS_FILE)
    found = False
    for item in doc.get("suggestions", []):
        if str(item.get("annotation_id")) != annotation_id:
            continue
        found = True
        item["type"] = normalized.get("type", item.get("type", "arrow"))
        item["placement_confirmed"] = normalized.get("placement_confirmed", False)
        item["skipped"] = normalized.get("skipped", False)
        item["anchor"] = normalized.get("anchor")
        item["arrow_direction"] = normalized.get("arrow_direction")
        item["arrow_length_ratio"] = normalized.get("arrow_length_ratio")
        if placement.get("target_start") is not None:
            start = max(0.0, float(placement["target_start"]))
            end_raw = placement.get("target_end")
            end = max(start + 0.5, float(end_raw if end_raw is not None else start + 3.0))
            item["target_start"] = round(start, 3)
            item["target_end"] = round(end, 3)
        item["placed_at"] = utc_now_iso()
        item["placed_by"] = saved_by
        item.pop("anchor_track", None)
        item["requires_review"] = False
        break

    if not found:
        raise ValueError(f"Аннотация {annotation_id} не найдена")

    doc["last_placement_at"] = utc_now_iso()
    registry.save_json(SUGGESTIONS_FILE, doc, "annotation_suggestions.schema.json")
    re_render_annotation_preview(registry, job_id)
    return _placement_summary(registry, job_id, annotation_id)


def save_annotation_studio(
    registry: ArtifactRegistry,
    job_id: str,
    items: list[dict[str, Any]],
    *,
    saved_by: str = "user",
    replace_all: bool = False,
) -> dict[str, Any]:
    """Пакетное сохранение студии: рамки/стрелки + тайминг на дорожке."""
    if not registry.exists(SUGGESTIONS_FILE):
        raise FileNotFoundError("annotation_suggestions.json не найден")

    from src.services.annotation_review_service import get_annotation_edit_payload, load_annotation_review

    review = load_annotation_review(registry, job_id)
    if review.get("status") == "approved":
        raise ValueError("Аннотации уже подтверждены. Нажмите «Редактировать аннотации».")

    doc = registry.load_json(SUGGESTIONS_FILE)
    suggestions: list[dict[str, Any]] = list(doc.get("suggestions") or [])
    by_id = {str(item.get("annotation_id")): item for item in suggestions}
    keep_ids: set[str] = set()
    next_idx = 1
    for item in suggestions:
        raw = str(item.get("annotation_id") or "")
        if raw.startswith("ann_"):
            try:
                next_idx = max(next_idx, int(raw.split("_")[-1]) + 1)
            except ValueError:
                pass

    for raw in items:
        ann_type = str(raw.get("type") or raw.get("suggested_type") or "highlight_rect").strip()
        if ann_type == "frame":
            ann_type = "highlight_rect"
        skipped = bool(raw.get("skipped", False))
        annotation_id = str(raw.get("annotation_id") or "").strip()
        if not annotation_id or annotation_id not in by_id:
            annotation_id = f"ann_{next_idx:03d}"
            next_idx += 1
            entry: dict[str, Any] = {
                "annotation_id": annotation_id,
                "type": ann_type,
                "label": str(raw.get("text") or raw.get("label") or "").strip(),
                "reason": "Добавлено вручную в студии аннотаций",
                "linked_segment_id": raw.get("linked_segment_id") or "",
                "style": "yellow_outline" if ann_type != "arrow" else "red_arrow",
                "confidence": 1.0,
                "placement_confirmed": False,
                "skipped": False,
                "anchor": None,
            }
            suggestions.append(entry)
            by_id[annotation_id] = entry
        keep_ids.add(annotation_id)
        entry = by_id[annotation_id]
        previous_anchor = entry.get("anchor")
        previous_type = entry.get("type")
        previous_interval = (entry.get("target_start"), entry.get("target_end"))
        start = max(0.0, float(raw.get("target_start", entry.get("target_start") or 0.0)))
        end_raw = raw.get("target_end", entry.get("target_end"))
        end = max(start + 0.5, float(end_raw if end_raw is not None else start + 3.0))
        entry["target_start"] = round(start, 3)
        entry["target_end"] = round(end, 3)
        entry["type"] = ann_type
        if raw.get("text") is not None or raw.get("label") is not None:
            entry["label"] = str(raw.get("text") or raw.get("label") or "").strip()

        if skipped:
            entry["skipped"] = True
            entry["placement_confirmed"] = False
            entry["anchor"] = None
            continue

        normalized = normalize_placement_payload(
            {
                "type": ann_type,
                "x": raw.get("x", (raw.get("anchor") or {}).get("x", 0.5)),
                "y": raw.get("y", (raw.get("anchor") or {}).get("y", 0.5)),
                "width": raw.get("width", (raw.get("anchor") or {}).get("width")),
                "height": raw.get("height", (raw.get("anchor") or {}).get("height")),
                "arrow_direction": raw.get("arrow_direction", "left"),
                "arrow_length_ratio": raw.get("arrow_length_ratio", 0.08),
            }
        )
        entry["type"] = normalized.get("type", ann_type)
        entry["placement_confirmed"] = True
        entry["skipped"] = False
        entry["anchor"] = normalized.get("anchor")
        entry["arrow_direction"] = normalized.get("arrow_direction")
        entry["arrow_length_ratio"] = normalized.get("arrow_length_ratio")
        entry["placed_at"] = utc_now_iso()
        if (previous_anchor != entry.get("anchor") or previous_type != entry.get("type")
                or previous_interval != (entry.get("target_start"), entry.get("target_end"))):
            entry.pop("anchor_track", None)
        entry["requires_review"] = False
        entry["placed_by"] = saved_by

    if replace_all:
        # Preserve unresolved automatic suggestions that are absent from the drawing canvas.
        suggestions = [item for item in suggestions if str(item.get("annotation_id")) in keep_ids
                       or (not item.get("placement_confirmed") and not item.get("skipped"))]

    doc["suggestions"] = suggestions
    doc["last_placement_at"] = utc_now_iso()
    registry.save_json(SUGGESTIONS_FILE, doc, "annotation_suggestions.schema.json")
    review["last_saved_at"] = utc_now_iso()
    review["status"] = "pending"
    registry.save_json("annotation_review.json", review, "annotation_review.schema.json")
    re_render_annotation_preview(registry, job_id)
    return get_annotation_edit_payload(registry, job_id)


def re_render_annotation_preview(registry: ArtifactRegistry, job_id: str) -> None:
    doc = registry.load_json(SUGGESTIONS_FILE)
    placed = confirmed_suggestions(doc.get("suggestions", []))
    # База — видео с озвучкой и субтитрами, чтобы на шаге аннотаций не пропадало сделанное раньше
    from src.services.subtitle_burn_service import ensure_subtitled_studio_video

    settings = get_settings()
    video_name = ensure_subtitled_studio_video(registry, settings, force=False)
    lesson_path = registry.artifact_path(video_name)
    if not lesson_path.exists():
        lesson_path = resolve_edited_video_path(registry)
    render_annotation_preview(
        lesson_path,
        placed,
        registry.job_dir / PREVIEW_FILENAME,
        settings=settings,
        refine_anchors=False,
    )


def _placement_summary(registry: ArtifactRegistry, job_id: str, annotation_id: str) -> dict[str, Any]:
    from src.services.annotation_review_service import get_annotation_edit_payload

    payload = get_annotation_edit_payload(registry, job_id)
    item = next((i for i in payload.get("items", []) if i["annotation_id"] == annotation_id), None)
    return {
        "ok": True,
        "annotation_id": annotation_id,
        "item": item,
        "confirmed_count": payload.get("confirmed_count", 0),
        "pending_count": payload.get("pending_count", 0),
        "annotations": payload,
    }
