"""Text Editing Prep Agent — этап 3: подготовка STT-текста к ручной правке."""

from __future__ import annotations

import logging
from typing import Any

from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.cleanup_review_service import create_pending_cleanup_review
from src.services.segment_timing_service import merge_stt_segments_with_timing

logger = logging.getLogger(__name__)


def run_speech_cleanup(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
) -> dict[str, Any]:
    if registry.exists("clean_transcript.json") and registry.exists("edits_map.json"):
        logger.info("clean_transcript.json уже существует, пропуск")
        return registry.load_json("clean_transcript.json")

    if not registry.exists("transcript.json"):
        raise FileNotFoundError("Нужен transcript.json — сначала выполните распознавание речи")

    transcript = registry.load_json("transcript.json")
    segments = transcript.get("segments", [])
    if not segments:
        raise ValueError("transcript.json не содержит сегментов")

    logger.info("Этап 3: подготовка текста к ручной правке, %s сегментов", len(segments))
    warnings: list[str] = [
        "Текст разбит на блоки по таймингу исходника: в каждый блок попадает только та часть речи, "
        "которая укладывается в его временной интервал."
    ]
    clean_segments = merge_stt_segments_with_timing(segments)
    edits: list[dict[str, Any]] = []
    confidence_summary = 1.0

    edits_map = {
        "job_id": job_id,
        "stage": PipelineStage.SPEECH_CLEANUP.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["transcript.json"],
        "status": ArtifactStatus.COMPLETED.value,
        "confidence_summary": round(confidence_summary, 3),
        "warnings": warnings,
        "errors": [],
        "edits": edits,
        "mode": "manual_text_edit",
    }

    clean_transcript = {
        "job_id": job_id,
        "stage": PipelineStage.SPEECH_CLEANUP.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["transcript.json", "edits_map.json"],
        "status": ArtifactStatus.COMPLETED.value,
        "confidence_summary": round(confidence_summary, 3),
        "warnings": warnings,
        "errors": [],
        "language": transcript.get("language", settings.default_language),
        "duration_seconds": transcript.get("duration_seconds", 0),
        "provider": "manual_text_edit",
        "mode": "manual_text_edit",
        "timing_aligned": True,
        "segments": clean_segments,
    }

    registry.save_json("edits_map.json", edits_map, "edits_map.schema.json")
    registry.save_json("clean_transcript.json", clean_transcript, "clean_transcript.schema.json")
    create_pending_cleanup_review(registry, job_id)
    logger.info(
        "Этап 3 готов: %s блоков для ручной правки, режим=%s",
        len(clean_segments),
        "manual_text_edit",
    )
    return clean_transcript
