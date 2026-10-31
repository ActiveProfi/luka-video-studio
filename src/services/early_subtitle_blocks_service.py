"""Шаг 4 (v2): разбивка на блоки / субтитры ДО озвучки.

Старый путь (субтитры после voiceover) не удаляется — см. subtitle_alignment_agent.
"""

from __future__ import annotations

import logging
from typing import Any

from src.config import Settings, get_settings
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.orchestrator.pipeline_state import PipelineState
from src.services.ffmpeg_service import get_media_duration_seconds
from src.services.media_paths import resolve_raw_video_path
from src.services.subtitle_service import (
    SUBTITLE_LAYOUT,
    assign_global_cue_ids,
    build_srt_content,
    default_subtitle_layout,
    fill_cue_timeline_gaps,
)

logger = logging.getLogger(__name__)

SUBTITLES_SRT = "subtitles.srt"
SUBTITLE_TIMING = "subtitle_timing.json"


def early_subtitles_ready(registry: ArtifactRegistry) -> bool:
    return registry.exists(SUBTITLES_SRT) and registry.exists(SUBTITLE_TIMING)


def run_early_subtitle_blocks_stage(job_id: str) -> PipelineState:
    """Собрать блоки субтитров из clean_transcript (или transcript) по таймингу видео."""
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)
    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    completed = list(state_data.get("stages_completed") or [])

    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=completed,
        current_stage="subtitle_blocks",
    )
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        build_early_subtitle_blocks(registry, settings, job_id)
        if "subtitle_blocks" not in completed:
            completed.append("subtitle_blocks")
        state = PipelineState(
            job_id=job_id,
            output_dir=str(job_dir),
            status=ArtifactStatus.COMPLETED,
            stages_completed=completed,
            current_stage=None,
            error=None,
        )
    except Exception as exc:
        logger.exception("Шаг 4 subtitle_blocks ошибка job=%s", job_id)
        state = PipelineState(
            job_id=job_id,
            output_dir=str(job_dir),
            status=ArtifactStatus.FAILED,
            stages_completed=completed,
            current_stage=None,
            error=str(exc),
        )
    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def build_early_subtitle_blocks(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    if early_subtitles_ready(registry) and not force:
        _ensure_layout(registry)
        return registry.load_json(SUBTITLE_TIMING)

    segments = _source_segments(registry)
    if not segments:
        raise ValueError("Нет текста для блоков — сначала шаги 2–3")

    total_duration = 0.0
    try:
        total_duration = float(
            get_media_duration_seconds(resolve_raw_video_path(registry), settings) or 0
        )
    except Exception:
        total_duration = 0.0
    if total_duration <= 0:
        total_duration = max(float(s.get("end", 0) or 0) for s in segments)

    cues: list[dict[str, Any]] = []
    for idx, seg in enumerate(segments, start=1):
        start = float(seg.get("start", 0) or 0)
        end = float(seg.get("end", start + 1) or (start + 1))
        text = str(seg.get("text") or "").strip()
        cues.append(
            {
                "cue_id": f"cue_{idx:04d}",
                "source_segment_id": str(seg.get("segment_id") or seg.get("id") or f"seg_{idx}"),
                "start": round(start, 3),
                "end": round(max(end, start + 0.3), 3),
                "text": text,
            }
        )
    cues = assign_global_cue_ids(cues)
    cues = fill_cue_timeline_gaps(cues, total_duration)

    timing = {
        "job_id": job_id,
        "stage": "subtitle_blocks",
        "version": "2.0.0",
        "created_at": utc_now_iso(),
        "source": "early_from_transcript",
        "total_duration_seconds": round(total_duration, 3),
        "cue_count": len(cues),
        "cues": cues,
        "language": str(
            (registry.load_json("clean_transcript.json") if registry.exists("clean_transcript.json") else {}).get(
                "language"
            )
            or settings.default_language
        ),
    }
    registry.save_json(SUBTITLE_TIMING, timing, "subtitle_timing.schema.json")
    registry.artifact_path(SUBTITLES_SRT).write_text(build_srt_content(cues), encoding="utf-8")
    _ensure_layout(registry)
    logger.info("Шаг 4: блоков субтитров %s, длительность %.1f с", len(cues), total_duration)
    return timing


def _source_segments(registry: ArtifactRegistry) -> list[dict[str, Any]]:
    if registry.exists("clean_transcript.json"):
        return list(registry.load_json("clean_transcript.json").get("segments") or [])
    if registry.exists("transcript.json"):
        return list(registry.load_json("transcript.json").get("segments") or [])
    return []


def _ensure_layout(registry: ArtifactRegistry) -> None:
    if registry.exists(SUBTITLE_LAYOUT):
        return
    registry.save_json(SUBTITLE_LAYOUT, default_subtitle_layout())
