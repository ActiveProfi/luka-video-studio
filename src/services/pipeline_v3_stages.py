"""Раннеры этапов архитектуры v3 (пять этапов для пользователя).

1 загрузка → 2 субтитры → 3 озвучка → 4 аннотации → 5 экспорт.
Всё, что было между ними (распознавание речи, подготовка текста, Speech Script),
осталось внутренними сервисами и в интерфейсе не показывается.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from src.config import get_settings
from src.domain.enums import ArtifactStatus
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.orchestrator.pipeline_state import PipelineState

logger = logging.getLogger(__name__)


def _run_stage(job_id: str, stage_id: str, action: Callable[[ArtifactRegistry, object], None]) -> PipelineState:
    """Общая обвязка: пометить running, выполнить, записать результат."""
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)
    state_data = (
        registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    )
    completed = list(state_data.get("stages_completed") or [])

    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=completed,
        current_stage=stage_id,
    )
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        action(registry, settings)
        if stage_id not in completed:
            completed.append(stage_id)
        state = PipelineState(
            job_id=job_id,
            output_dir=str(job_dir),
            status=ArtifactStatus.COMPLETED,
            stages_completed=completed,
            current_stage=None,
            error=None,
        )
    except Exception as exc:
        logger.exception("Этап %s не выполнен job=%s", stage_id, job_id)
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


def run_video_analysis_stage(job_id: str) -> PipelineState:
    """Этап 1: характеристики ролика и автоматическое разбиение на тайм-блоки."""

    def action(registry: ArtifactRegistry, settings) -> None:
        from src.services.timeblock_service import build_time_blocks
        from src.services.video_probe_service import build_video_meta

        build_video_meta(registry, job_id, settings, force=True)
        build_time_blocks(registry, job_id, settings, force=True)

    return _run_stage(job_id, "upload", action)


def run_subtitle_capture_stage(job_id: str) -> PipelineState:
    """Этап 2: подготовить блоки под ввод субтитров (текст пишет пользователь)."""

    def action(registry: ArtifactRegistry, settings) -> None:
        from src.services.timeblock_service import build_time_blocks

        build_time_blocks(registry, job_id, settings)
        from src.services.automatic_script_service import generate_instruction_script

        generate_instruction_script(registry, settings, job_id)

    return _run_stage(job_id, "subtitle_capture", action)


def run_auto_voiceover_stage(job_id: str) -> PipelineState:
    """Этап 3: Speech Script и озвучка целиком автоматически."""

    def action(registry: ArtifactRegistry, settings) -> None:
        from src.services.auto_voiceover_service import run_auto_voiceover

        run_auto_voiceover(registry, settings, job_id)

    return _run_stage(job_id, "voiceover", action)


def run_export_stage(job_id: str) -> PipelineState:
    """Этап 5: сборка готового ролика (видео + озвучка + субтитры + аннотации)."""
    from src.orchestrator.pipeline_runner import run_assembly_stage

    return run_assembly_stage(job_id)
