"""Проверка синхронизации озвучки и видео (Human Review Gate)."""

from __future__ import annotations

from typing import Any

from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.sync_render_service import SYNC_PREVIEW_FILENAME, render_sync_preview
from src.services.sync_service import build_sync_blocks, global_audio_offset

REVIEW_FILENAME = "sync_review.json"
PLAN_FILENAME = "sync_plan.json"
APPROVED_FILENAME = "approved_sync.json"


def sync_plan_ready(registry: ArtifactRegistry) -> bool:
    return registry.exists(PLAN_FILENAME)


def sync_artifacts_ready(registry: ArtifactRegistry) -> bool:
    return (
        registry.exists(PLAN_FILENAME)
        and registry.exists(SYNC_PREVIEW_FILENAME)
        and registry.exists(REVIEW_FILENAME)
    )


def load_sync_review(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    if registry.exists(REVIEW_FILENAME):
        return registry.load_json(REVIEW_FILENAME)
    if sync_plan_ready(registry):
        return create_pending_sync_review(registry, job_id)
    return {
        "job_id": job_id,
        "stage": "sync_review",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "status": "pending",
        "blocks": [],
    }


def create_pending_sync_review(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    plan = registry.load_json(PLAN_FILENAME)
    data = {
        "job_id": job_id,
        "stage": "sync_review",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "status": "pending",
        "approved_at": None,
        "approved_by": None,
        "last_saved_at": None,
        "preview_video": SYNC_PREVIEW_FILENAME,
        "global_audio_offset_seconds": plan.get("global_audio_offset_seconds", 0),
        "blocks": plan.get("blocks", []),
    }
    registry.save_json(REVIEW_FILENAME, data, "sync_review.schema.json")
    return data


def sync_review_approved(registry: ArtifactRegistry, job_id: str) -> bool:
    if not sync_artifacts_ready(registry):
        return False
    review = load_sync_review(registry, job_id)
    return review.get("status") == "approved" and registry.exists(APPROVED_FILENAME)


def get_sync_edit_payload(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    if not sync_plan_ready(registry):
        raise FileNotFoundError("Сначала выполните этап «Синхронизация озвучки»")

    _ensure_sync_preview(registry, job_id)
    review = load_sync_review(registry, job_id)
    plan = registry.load_json(PLAN_FILENAME)
    return {
        "job_id": job_id,
        "review_status": review.get("status", "pending"),
        "last_saved_at": review.get("last_saved_at"),
        "approved_at": review.get("approved_at"),
        "preview_video_url": f"/jobs/{job_id}/artifacts/{SYNC_PREVIEW_FILENAME}",
        "preview_video": SYNC_PREVIEW_FILENAME,
        "global_audio_offset_seconds": review.get(
            "global_audio_offset_seconds", plan.get("global_audio_offset_seconds", 0)
        ),
        "video_duration_seconds": plan.get("video_duration_seconds", 0),
        "voiceover_duration_seconds": plan.get("voiceover_duration_seconds", 0),
        "blocks": review.get("blocks", []),
    }


def save_sync_review_edits(
    registry: ArtifactRegistry,
    job_id: str,
    blocks: list[dict[str, Any]],
    saved_by: str = "user",
) -> dict[str, Any]:
    if not sync_plan_ready(registry):
        raise FileNotFoundError("sync_plan.json не найден")

    review = load_sync_review(registry, job_id)
    if review.get("status") == "approved":
        raise ValueError(
            "Синхронизация уже подтверждена. Нажмите «Редактировать синхронизацию» на шаге 8."
        )

    by_id = {item["block_id"]: item for item in blocks if item.get("block_id")}
    for block in review.get("blocks", []):
        block_id = block.get("block_id")
        if block_id not in by_id:
            continue
        item = by_id[block_id]
        block["offset_adjustment_seconds"] = round(
            float(item.get("offset_adjustment_seconds", block.get("offset_adjustment_seconds", 0))),
            3,
        )
        block["user_comment"] = str(item.get("user_comment", "")).strip()

    review["global_audio_offset_seconds"] = global_audio_offset(review.get("blocks", []))
    review["last_saved_at"] = utc_now_iso()
    review["status"] = "pending"
    registry.save_json(REVIEW_FILENAME, review, "sync_review.schema.json")

    _render_preview_from_review(registry, job_id, review)
    return get_sync_edit_payload(registry, job_id)


def approve_sync_review(
    registry: ArtifactRegistry,
    job_id: str,
    blocks: list[dict[str, Any]] | None = None,
    approved_by: str = "user",
) -> dict[str, Any]:
    if blocks:
        save_sync_review_edits(registry, job_id, blocks, saved_by=approved_by)

    review = load_sync_review(registry, job_id)
    offset = float(review.get("global_audio_offset_seconds", 0))

    review["status"] = "approved"
    review["approved_at"] = utc_now_iso()
    review["approved_by"] = approved_by
    registry.save_json(REVIEW_FILENAME, review, "sync_review.schema.json")

    approved_doc = {
        "job_id": job_id,
        "stage": "voice_video_sync",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [PLAN_FILENAME, REVIEW_FILENAME, SYNC_PREVIEW_FILENAME],
        "status": "completed",
        "approved_at": utc_now_iso(),
        "approved_by": approved_by,
        "global_audio_offset_seconds": offset,
        "blocks": review.get("blocks", []),
    }
    registry.save_json(APPROVED_FILENAME, approved_doc, "approved_sync.schema.json")
    return get_sync_edit_payload(registry, job_id)


def reopen_sync_review(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    if not sync_plan_ready(registry):
        raise FileNotFoundError("Сначала выполните этап «Синхронизация озвучки»")

    review = load_sync_review(registry, job_id)
    review["status"] = "pending"
    review["approved_at"] = None
    review["approved_by"] = None
    registry.save_json(REVIEW_FILENAME, review, "sync_review.schema.json")

    if registry.exists(APPROVED_FILENAME):
        registry.artifact_path(APPROVED_FILENAME).unlink(missing_ok=True)

    return get_sync_edit_payload(registry, job_id)


def _ensure_sync_preview(registry: ArtifactRegistry, job_id: str) -> None:
    if registry.exists(SYNC_PREVIEW_FILENAME) and registry.exists(REVIEW_FILENAME):
        return
    review = load_sync_review(registry, job_id) if registry.exists(REVIEW_FILENAME) else None
    if review is None:
        create_pending_sync_review(registry, job_id)
        review = registry.load_json(REVIEW_FILENAME)
    _render_preview_from_review(registry, job_id, review)


def _render_preview_from_review(registry: ArtifactRegistry, job_id: str, review: dict[str, Any]) -> None:
    from src.config import get_settings
    from src.services.media_paths import resolve_edited_video_path

    edited = resolve_edited_video_path(registry)
    voiceover = registry.job_dir / "voiceover.wav"
    offset = float(review.get("global_audio_offset_seconds", 0))
    render_sync_preview(
        edited,
        voiceover,
        registry.job_dir / SYNC_PREVIEW_FILENAME,
        audio_offset_seconds=offset,
        settings=get_settings(),
    )
