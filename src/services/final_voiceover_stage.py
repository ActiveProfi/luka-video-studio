"""Шаг 6 (v2): финальная озвучка — обёртка над final_voiceover_from_subtitles."""

from __future__ import annotations

import logging

from src.config import get_settings
from src.domain.enums import ArtifactStatus
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.orchestrator.pipeline_state import PipelineState
from src.services.final_voiceover_from_subtitles import run_final_voiceover_from_subtitles
from src.services.voiceover_script_service import voiceover_script_voiceover_approved

logger = logging.getLogger(__name__)


def run_final_voiceover_stage(job_id: str) -> PipelineState:
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)
    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    completed = list(state_data.get("stages_completed") or [])

    if not registry.exists("subtitle_timing.json"):
        raise ValueError("Сначала выполните шаг 4 (субтитры/блоки)")
    if not registry.exists("voiceover_script.json"):
        raise ValueError("Сначала выполните шаг 5 (текст для озвучки)")
    if not voiceover_script_voiceover_approved(registry):
        raise ValueError("Сначала нажмите «Утвердить текст озвучки» на шаге 5")

    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=completed,
        current_stage="final_voiceover",
    )
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        run_final_voiceover_from_subtitles(registry, settings, job_id, force=True)
        if "final_voiceover" not in completed:
            completed.append("final_voiceover")
        # убрать stub-маркер если был
        registry.artifact_path("final_voiceover_stub.json").unlink(missing_ok=True)
        state = PipelineState(
            job_id=job_id,
            output_dir=str(job_dir),
            status=ArtifactStatus.COMPLETED,
            stages_completed=completed,
            current_stage=None,
            error=None,
        )
        logger.info("Шаг 6 финальная озвучка готова job=%s", job_id)
    except Exception as exc:
        logger.exception("Шаг 6 ошибка job=%s", job_id)
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
