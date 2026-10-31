"""Video Edit Agent — монтаж: исходное видео (с паузами) + AI-озвучка."""

from __future__ import annotations

import logging
from typing import Any

from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.ffmpeg_service import get_media_duration_seconds, mux_video_with_voiceover
from src.services.media_paths import resolve_raw_video_path

logger = logging.getLogger(__name__)

EDITED_VIDEO_NAME = "edited_video.mp4"
REPORT_NAME = "video_edit_report.json"
VOICEOVER_WAV = "voiceover.wav"


def run_video_edit(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
) -> dict[str, Any]:
    if registry.exists(EDITED_VIDEO_NAME):
        logger.info("%s уже существует, пропуск", EDITED_VIDEO_NAME)
        if registry.exists(REPORT_NAME):
            return registry.load_json(REPORT_NAME)
        return _build_report_from_output(registry, job_id, settings)

    if not registry.exists(VOICEOVER_WAV):
        raise FileNotFoundError("Нужен voiceover.wav — сначала выполните AI-озвучку (шаг 4)")

    source_video = resolve_raw_video_path(registry)
    voiceover_path = registry.artifact_path(VOICEOVER_WAV)
    output_path = registry.artifact_path(EDITED_VIDEO_NAME)

    logger.info("Монтаж: исходное видео + озвучка job_id=%s", job_id)
    source_duration = get_media_duration_seconds(source_video, settings)
    output_duration = mux_video_with_voiceover(
        source_video,
        voiceover_path,
        output_path,
        settings,
    )

    warnings: list[str] = []
    duration_delta = abs(output_duration - source_duration)
    if duration_delta > 1.5:
        warnings.append(
            f"Длительность результата ({output_duration:.1f} с) отличается от исходника "
            f"({source_duration:.1f} с) на {duration_delta:.1f} с"
        )

    report = {
        "job_id": job_id,
        "stage": PipelineStage.VIDEO_EDIT.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [str(source_video.name), VOICEOVER_WAV],
        "status": ArtifactStatus.COMPLETED.value,
        "montage_mode": "preserve_pauses_mux_voiceover",
        "confidence_summary": 1.0,
        "warnings": warnings,
        "errors": [],
        "output_artifact": EDITED_VIDEO_NAME,
        "source_video": str(source_video),
        "source_duration_seconds": round(source_duration, 3),
        "output_duration_seconds": round(output_duration, 3),
        "pauses_removed": False,
    }
    registry.save_json(REPORT_NAME, report)
    logger.info(
        "Монтаж завершён: %s → %.1f с (исходник %.1f с, паузы сохранены)",
        EDITED_VIDEO_NAME,
        output_duration,
        source_duration,
    )
    return report


def _build_report_from_output(
    registry: ArtifactRegistry,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    output_path = registry.artifact_path(EDITED_VIDEO_NAME)
    duration = get_media_duration_seconds(output_path, settings)
    return {
        "job_id": job_id,
        "stage": PipelineStage.VIDEO_EDIT.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [VOICEOVER_WAV],
        "status": ArtifactStatus.COMPLETED.value,
        "montage_mode": "preserve_pauses_mux_voiceover",
        "output_artifact": EDITED_VIDEO_NAME,
        "output_duration_seconds": round(duration, 3),
        "pauses_removed": False,
        "warnings": [],
        "errors": [],
    }
