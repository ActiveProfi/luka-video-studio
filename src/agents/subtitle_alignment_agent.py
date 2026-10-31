"""Subtitle Alignment Agent — этап 6: субтитры по таймингу озвучки."""

from __future__ import annotations

import logging
from typing import Any

from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.subtitle_service import (
    SUBTITLE_LAYOUT,
    build_srt_content,
    cues_from_voiceover_segments,
    default_subtitle_layout,
    fill_cue_timeline_gaps,
)

logger = logging.getLogger(__name__)

SUBTITLES_SRT = "subtitles.srt"
SUBTITLE_TIMING = "subtitle_timing.json"
VOICEOVER_SEGMENTS = "voiceover_segments.json"


def run_subtitle_alignment(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
) -> dict[str, Any]:
    if registry.exists(SUBTITLES_SRT) and registry.exists(SUBTITLE_TIMING):
        _ensure_subtitle_layout(registry)
        timing = registry.load_json(SUBTITLE_TIMING)
        cues = list(timing.get("cues") or [])
        total_duration = float(timing.get("total_duration_seconds") or 0)
        from src.services.subtitle_service import timeline_has_gaps

        if cues and total_duration > 0 and timeline_has_gaps(cues, total_duration):
            filled = fill_cue_timeline_gaps(cues, total_duration)
            timing["cues"] = filled
            timing["cue_count"] = len(filled)
            registry.save_json(SUBTITLE_TIMING, timing, "subtitle_timing.schema.json")
            registry.artifact_path(SUBTITLES_SRT).write_text(
                build_srt_content(filled), encoding="utf-8"
            )
            logger.info("Субтитры уже есть: закрыты паузы пустыми блоками (%s)", len(filled))
            return timing
        logger.info("Субтитры уже существуют, пропуск")
        return timing

    if not registry.exists(VOICEOVER_SEGMENTS):
        raise FileNotFoundError("Нужен voiceover_segments.json — сначала выполните AI-озвучку")
    if not registry.exists("voiceover.wav"):
        raise FileNotFoundError("Нужен voiceover.wav — сначала выполните AI-озвучку")

    voiceover = registry.load_json(VOICEOVER_SEGMENTS)
    segments = voiceover.get("segments", [])
    if not segments:
        raise ValueError("voiceover_segments.json пуст — нечего субтитрировать")

    cues = cues_from_voiceover_segments(segments)
    if not cues:
        raise ValueError("Не удалось построить субтитры из озвучки")

    total_duration = float(voiceover.get("total_duration_seconds") or 0)
    if total_duration <= 0 and cues:
        total_duration = float(cues[-1]["end"])
    cues = fill_cue_timeline_gaps(cues, total_duration)

    srt_content = build_srt_content(cues)
    registry.artifact_path(SUBTITLES_SRT).write_text(srt_content, encoding="utf-8")

    warnings: list[str] = []
    for cue in cues:
        if cue["end"] - cue["start"] < 0.8 and str(cue.get("text") or "").strip():
            warnings.append(f"Короткий cue {cue['cue_id']}: {cue['end'] - cue['start']:.2f} с")
    empty_count = sum(1 for c in cues if not str(c.get("text") or "").strip())
    if empty_count:
        warnings.append(
            f"Добавлено пустых блоков на паузы: {empty_count}. Можно вписать текст вручную на шаге 6."
        )

    doc = {
        "job_id": job_id,
        "stage": PipelineStage.SUBTITLES.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [VOICEOVER_SEGMENTS, "voiceover.wav"],
        "status": ArtifactStatus.COMPLETED.value,
        "language": voiceover.get("language", settings.default_language),
        "total_duration_seconds": round(total_duration, 3),
        "cue_count": len(cues),
        "confidence_summary": 0.9 if not warnings else 0.8,
        "warnings": warnings,
        "errors": [],
        "cues": cues,
    }
    registry.save_json(SUBTITLE_TIMING, doc, "subtitle_timing.schema.json")
    _ensure_subtitle_layout(registry)
    try:
        from src.services.subtitle_burn_service import ensure_subtitled_studio_video

        ensure_subtitled_studio_video(registry, settings, force=True)
    except Exception as exc:
        logger.warning("Прожиг субтитров после шага 6 не удался: %s", exc)
    logger.info("Субтитры готовы: subtitles.srt, cues=%s", len(cues))
    return doc


def _ensure_subtitle_layout(registry: ArtifactRegistry) -> None:
    if registry.exists(SUBTITLE_LAYOUT):
        return
    registry.save_json(SUBTITLE_LAYOUT, default_subtitle_layout())
