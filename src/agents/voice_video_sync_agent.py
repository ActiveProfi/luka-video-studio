"""Voice/Video Sync Agent — шаг 8: синхронизация озвучки с видео."""

from __future__ import annotations

import logging
from typing import Any

from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.ffmpeg_service import get_media_duration_seconds
from src.services.media_paths import resolve_edited_video_path
from src.services.sync_render_service import SYNC_PREVIEW_FILENAME, render_sync_preview
from src.services.sync_review_service import create_pending_sync_review, sync_review_approved
from src.services.sync_service import build_sync_blocks, global_audio_offset

logger = logging.getLogger(__name__)

PLAN_FILENAME = "sync_plan.json"


def run_voice_video_sync(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
) -> dict[str, Any]:
    if sync_review_approved(registry, job_id):
        logger.info("Синхронизация уже подтверждена, пропуск")
        return registry.load_json(PLAN_FILENAME)

    for required in ("edited_video.mp4", "voiceover.wav", "voiceover_segments.json"):
        if not registry.exists(required):
            raise FileNotFoundError(f"Нужен {required} — выполните предыдущие шаги")

    if registry.exists("approved_sync.json"):
        registry.artifact_path("approved_sync.json").unlink(missing_ok=True)

    voiceover = registry.load_json("voiceover_segments.json")
    segments = voiceover.get("segments", [])
    if not segments:
        raise ValueError("voiceover_segments.json пуст")

    edited_path = resolve_edited_video_path(registry)
    voiceover_path = registry.job_dir / "voiceover.wav"
    video_duration = get_media_duration_seconds(edited_path, settings)
    audio_duration = get_media_duration_seconds(voiceover_path, settings)

    blocks = build_sync_blocks(segments)
    offset = global_audio_offset(blocks)
    duration_delta = round(audio_duration - video_duration, 3)

    warnings: list[str] = []
    if abs(duration_delta) > 0.5:
        warnings.append(
            f"Длительность озвучки ({audio_duration:.1f} с) и видео ({video_duration:.1f} с) "
            f"различаются на {abs(duration_delta):.1f} с — проверьте синхронизацию по блокам."
        )

    plan_doc = {
        "job_id": job_id,
        "stage": PipelineStage.VOICE_VIDEO_SYNC.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["edited_video.mp4", "voiceover.wav", "voiceover_segments.json"],
        "status": ArtifactStatus.NEEDS_REVIEW.value,
        "video_duration_seconds": round(video_duration, 3),
        "voiceover_duration_seconds": round(audio_duration, 3),
        "duration_delta_seconds": duration_delta,
        "global_audio_offset_seconds": offset,
        "warnings": warnings,
        "errors": [],
        "blocks": blocks,
        "preview_video": SYNC_PREVIEW_FILENAME,
    }
    registry.save_json(PLAN_FILENAME, plan_doc, "sync_plan.schema.json")

    render_sync_preview(
        edited_path,
        voiceover_path,
        registry.job_dir / SYNC_PREVIEW_FILENAME,
        audio_offset_seconds=offset,
        settings=settings,
    )
    create_pending_sync_review(registry, job_id)

    logger.info(
        "Этап синхронизации: блоков=%s, сдвиг=%.3f с — ожидает проверки",
        len(blocks),
        offset,
    )
    return plan_doc
