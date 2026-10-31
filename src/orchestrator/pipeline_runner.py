"""Запуск этапов pipeline."""

from __future__ import annotations

import logging
import traceback

from src.agents.speech_cleanup_agent import run_speech_cleanup
from src.agents.speech_recognition_agent import run_speech_recognition
from src.agents.annotation_suggestion_agent import run_annotation_suggestions
from src.agents.lesson_assembly_agent import run_lesson_assembly
from src.agents.voice_video_sync_agent import run_voice_video_sync
from src.agents.subtitle_alignment_agent import run_subtitle_alignment
from src.agents.timing_decision_agent import run_timing_decision
from src.agents.tts_generation_agent import (
    VOICEOVER_SEGMENTS,
    VOICEOVER_WAV,
    current_tts_text_hash,
    run_tts_generation,
)
from src.agents.video_edit_agent import run_video_edit
from src.config import get_settings
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.orchestrator.pipeline_state import PipelineState
from src.services.cleanup_review_service import cleanup_review_approved, ensure_speech_script_prepared
from src.services.timing_review_service import timing_stage_completed
from src.services.annotation_review_service import annotation_review_approved
from src.services.sync_review_service import sync_review_approved

logger = logging.getLogger(__name__)


def run_transcription_stage(job_id: str) -> PipelineState:
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)

    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus(state_data.get("status", "pending")),
        stages_completed=state_data.get("stages_completed", []),
    )

    if registry.exists("transcript.json"):
        if PipelineStage.TRANSCRIPTION.value not in state.stages_completed:
            state.mark_stage_done(PipelineStage.TRANSCRIPTION)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
        registry.save_json("pipeline_state.json", state.to_dict())
        return state

    state.mark_running(PipelineStage.TRANSCRIPTION)
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        run_speech_recognition(registry, settings, job_id)
        state.mark_stage_done(PipelineStage.TRANSCRIPTION)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
    except Exception as exc:
        logger.exception("Ошибка этапа STT job_id=%s", job_id)
        state.mark_failed(str(exc))
        registry.save_json(
            "pipeline_state.json",
            {**state.to_dict(), "traceback": traceback.format_exc()[-2000:]},
        )
        raise

    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def run_cleanup_stage(job_id: str) -> PipelineState:
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)

    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus(state_data.get("status", "pending")),
        stages_completed=state_data.get("stages_completed", []),
    )

    if not registry.exists("transcript.json"):
        raise FileNotFoundError("Сначала выполните распознавание речи (transcript.json)")

    if registry.exists("clean_transcript.json") and registry.exists("edits_map.json"):
        if PipelineStage.SPEECH_CLEANUP.value not in state.stages_completed:
            state.mark_stage_done(PipelineStage.SPEECH_CLEANUP)
        try:
            ensure_speech_script_prepared(registry, job_id, settings=settings)
        except Exception as exc:
            logger.exception("Ошибка автоподготовки Speech Script job_id=%s", job_id)
            state.mark_failed(str(exc))
            registry.save_json(
                "pipeline_state.json",
                {**state.to_dict(), "traceback": traceback.format_exc()[-2000:]},
            )
            raise
        state.status = ArtifactStatus.COMPLETED
        state.error = None
        registry.save_json("pipeline_state.json", state.to_dict())
        return state

    state.mark_running(PipelineStage.SPEECH_CLEANUP)
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        run_speech_cleanup(registry, settings, job_id)
        ensure_speech_script_prepared(registry, job_id, settings=settings)
        state.mark_stage_done(PipelineStage.SPEECH_CLEANUP)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
    except Exception as exc:
        logger.exception("Ошибка подготовки сценария озвучки job_id=%s", job_id)
        state.mark_failed(str(exc))
        registry.save_json(
            "pipeline_state.json",
            {**state.to_dict(), "traceback": traceback.format_exc()[-2000:]},
        )
        raise

    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def run_timing_stage(job_id: str) -> PipelineState:
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)

    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus(state_data.get("status", "pending")),
        stages_completed=state_data.get("stages_completed", []),
    )

    if not cleanup_review_approved(registry, job_id):
        raise ValueError("Сначала подтвердите текст на этапе «Редактирование текста»")

    if registry.exists("timing_decisions.json") and registry.exists("timeline_map.json"):
        for stage in (
            PipelineStage.TIMING_PAUSE_CANDIDATES,
            PipelineStage.TIMING_VISUAL_ACTIVITY,
            PipelineStage.TIMING_SEMANTIC_ACTION,
            PipelineStage.TIMING_POLICY,
            PipelineStage.TIMELINE_MAP,
        ):
            if stage.value not in state.stages_completed:
                state.mark_stage_done(stage)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
        registry.save_json("pipeline_state.json", state.to_dict())
        return state

    state.mark_running(PipelineStage.TIMING_POLICY)
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        run_timing_decision(registry, settings, job_id)
        for stage in (
            PipelineStage.TIMING_PAUSE_CANDIDATES,
            PipelineStage.TIMING_VISUAL_ACTIVITY,
            PipelineStage.TIMING_SEMANTIC_ACTION,
            PipelineStage.TIMING_POLICY,
            PipelineStage.TIMELINE_MAP,
        ):
            state.mark_stage_done(stage)
        timing = registry.load_json("timing_decisions.json")
        if timing.get("status") == ArtifactStatus.NEEDS_REVIEW.value:
            state.status = ArtifactStatus.NEEDS_REVIEW
        else:
            state.status = ArtifactStatus.COMPLETED
        state.error = None
    except Exception as exc:
        logger.exception("Ошибка этапа тайминга job_id=%s", job_id)
        state.mark_failed(str(exc))
        registry.save_json(
            "pipeline_state.json",
            {**state.to_dict(), "traceback": traceback.format_exc()[-2000:]},
        )
        raise

    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def run_video_edit_stage(job_id: str) -> PipelineState:
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)

    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus(state_data.get("status", "pending")),
        stages_completed=state_data.get("stages_completed", []),
    )

    if not registry.exists("voiceover.wav"):
        raise ValueError("Сначала выполните AI-озвучку (шаг 4)")

    if registry.exists("edited_video.mp4"):
        if PipelineStage.VIDEO_EDIT.value not in state.stages_completed:
            state.mark_stage_done(PipelineStage.VIDEO_EDIT)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
        registry.save_json("pipeline_state.json", state.to_dict())
        return state

    state.mark_running(PipelineStage.VIDEO_EDIT)
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        run_video_edit(registry, settings, job_id)
        state.mark_stage_done(PipelineStage.VIDEO_EDIT)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
    except Exception as exc:
        logger.exception("Ошибка этапа монтажа job_id=%s", job_id)
        state.mark_failed(str(exc))
        registry.save_json(
            "pipeline_state.json",
            {**state.to_dict(), "traceback": traceback.format_exc()[-2000:]},
        )
        raise

    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def run_tts_stage(job_id: str) -> PipelineState:
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)

    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus(state_data.get("status", "pending")),
        stages_completed=state_data.get("stages_completed", []),
    )

    if not cleanup_review_approved(registry, job_id):
        raise ValueError("Сначала подтвердите текст на этапе «Редактирование текста»")

    if _voiceover_matches_current_cleanup(registry):
        if PipelineStage.TTS.value not in state.stages_completed:
            state.mark_stage_done(PipelineStage.TTS)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
        registry.save_json("pipeline_state.json", state.to_dict())
        return state

    state.mark_running(PipelineStage.TTS)
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        run_tts_generation(registry, settings, job_id)
        state.mark_stage_done(PipelineStage.TTS)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
    except Exception as exc:
        logger.exception("Ошибка этапа TTS job_id=%s", job_id)
        state.mark_failed(str(exc))
        registry.save_json(
            "pipeline_state.json",
            {**state.to_dict(), "traceback": traceback.format_exc()[-2000:]},
        )
        raise

    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def _voiceover_matches_current_cleanup(registry: ArtifactRegistry) -> bool:
    if not (
        registry.exists("clean_transcript.json")
        and registry.exists(VOICEOVER_WAV)
        and registry.exists(VOICEOVER_SEGMENTS)
    ):
        return False
    voiceover = registry.load_json(VOICEOVER_SEGMENTS)
    current_hash = current_tts_text_hash(registry)
    return voiceover.get("cleanup_text_hash") == current_hash


def run_subtitles_stage(job_id: str) -> PipelineState:
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)

    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus(state_data.get("status", "pending")),
        stages_completed=state_data.get("stages_completed", []),
    )

    if not registry.exists("edited_video.mp4"):
        raise ValueError("Нужен edited_video.mp4")

    if registry.exists("subtitles.srt") and registry.exists("subtitle_timing.json"):
        if PipelineStage.SUBTITLES.value not in state.stages_completed:
            state.mark_stage_done(PipelineStage.SUBTITLES)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
        registry.save_json("pipeline_state.json", state.to_dict())
        return state

    state.mark_running(PipelineStage.SUBTITLES)
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        run_subtitle_alignment(registry, settings, job_id)
        state.mark_stage_done(PipelineStage.SUBTITLES)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
    except Exception as exc:
        logger.exception("Ошибка этапа субтитров job_id=%s", job_id)
        state.mark_failed(str(exc))
        registry.save_json(
            "pipeline_state.json",
            {**state.to_dict(), "traceback": traceback.format_exc()[-2000:]},
        )
        raise

    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def run_sync_stage(job_id: str) -> PipelineState:
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)

    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus(state_data.get("status", "pending")),
        stages_completed=state_data.get("stages_completed", []),
    )

    if not registry.exists("subtitles.srt"):
        raise ValueError("Сначала выполните субтитры (шаг 6)")

    if sync_review_approved(registry, job_id):
        if PipelineStage.VOICE_VIDEO_SYNC.value not in state.stages_completed:
            state.mark_stage_done(PipelineStage.VOICE_VIDEO_SYNC)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
        registry.save_json("pipeline_state.json", state.to_dict())
        return state

    state.mark_running(PipelineStage.VOICE_VIDEO_SYNC)
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        run_voice_video_sync(registry, settings, job_id)
        if PipelineStage.VOICE_VIDEO_SYNC.value not in state.stages_completed:
            state.mark_stage_done(PipelineStage.VOICE_VIDEO_SYNC)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
    except Exception as exc:
        logger.exception("Ошибка этапа синхронизации job_id=%s", job_id)
        state.mark_failed(str(exc))
        registry.save_json(
            "pipeline_state.json",
            {**state.to_dict(), "traceback": traceback.format_exc()[-2000:]},
        )
        raise

    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def run_assembly_stage(job_id: str) -> PipelineState:
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)

    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus(state_data.get("status", "pending")),
        stages_completed=state_data.get("stages_completed", []),
    )

    if not registry.exists("subtitles.srt") and not registry.exists("subtitle_timing.json"):
        raise ValueError("Сначала сохраните субтитры")

    if not registry.exists("approved_annotations.json"):
        raise ValueError("Сначала подтвердите аннотации")

    # Старый финал остаётся доступен, пока новая сборка не завершена.
    registry.save_json("render_pending.json", {"reason": "assembly"})

    state.mark_running(PipelineStage.ASSEMBLY)
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        run_lesson_assembly(registry, settings, job_id, force=True)
        state.mark_stage_done(PipelineStage.ASSEMBLY)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
    except Exception as exc:
        logger.exception("Ошибка сборки урока job_id=%s", job_id)
        state.mark_failed(str(exc))
        registry.save_json(
            "pipeline_state.json",
            {**state.to_dict(), "traceback": traceback.format_exc()[-2000:]},
        )
        raise

    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def run_annotations_stage(job_id: str) -> PipelineState:
    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)

    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus(state_data.get("status", "pending")),
        stages_completed=state_data.get("stages_completed", []),
    )

    if not registry.exists("edited_video.mp4"):
        raise ValueError("Сначала выполните монтаж видео (шаг 5)")

    if not registry.exists("subtitles.srt") or not registry.exists("subtitle_timing.json"):
        raise ValueError("Сначала выполните субтитры (шаг 6)")

    if annotation_review_approved(registry, job_id):
        if PipelineStage.ANNOTATIONS.value not in state.stages_completed:
            state.mark_stage_done(PipelineStage.ANNOTATIONS)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
        registry.save_json("pipeline_state.json", state.to_dict())
        return state

    state.mark_running(PipelineStage.ANNOTATIONS)
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        run_annotation_suggestions(registry, settings, job_id)
        state.mark_stage_done(PipelineStage.ANNOTATIONS)
        state.status = ArtifactStatus.COMPLETED
        state.error = None
    except Exception as exc:
        logger.exception("Ошибка этапа аннотаций job_id=%s", job_id)
        state.mark_failed(str(exc))
        registry.save_json(
            "pipeline_state.json",
            {**state.to_dict(), "traceback": traceback.format_exc()[-2000:]},
        )
        raise

    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def run_single_ui_stage(job_id: str, ui_stage_id: str) -> PipelineState:
    """Выполнить один UI-этап без автоматического запуска следующих."""
    from src.services.early_subtitle_blocks_service import run_early_subtitle_blocks_stage
    from src.services.final_voiceover_stage import run_final_voiceover_stage
    from src.services.pipeline_v3_stages import (
        run_auto_voiceover_stage,
        run_export_stage,
        run_subtitle_capture_stage,
        run_video_analysis_stage,
    )
    from src.services.voiceover_script_service import run_voiceover_script_stage

    runners = {
        # v3 — пять этапов пользователя
        "upload": run_video_analysis_stage,
        "subtitle_capture": run_subtitle_capture_stage,
        "voiceover": run_auto_voiceover_stage,
        "export": run_export_stage,
        "stt": run_transcription_stage,
        "cleanup": run_cleanup_stage,
        # v2 — сохранено как внутренние сервисы
        "subtitle_blocks": run_early_subtitle_blocks_stage,
        "voiceover_script": run_voiceover_script_stage,
        "final_voiceover": run_final_voiceover_stage,
        # legacy runners — сохранены
        "tts": run_tts_stage,
        "edit": run_video_edit_stage,
        "annotations": run_annotations_stage,
        "subtitles": run_subtitles_stage,
        "assembly": run_assembly_stage,
    }
    runner = runners.get(ui_stage_id)
    if runner is None:
        raise ValueError(f"Этап «{ui_stage_id}» пока не реализован")
    return runner(job_id)


IMPLEMENTED_UI_STAGES: frozenset[str] = frozenset(
    {
        "upload",
        "subtitle_capture",
        "voiceover",
        "export",
        "stt",
        "cleanup",
        "subtitle_blocks",
        "voiceover_script",
        "final_voiceover",
        "tts",
        "edit",
        "annotations",
        "subtitles",
        "assembly",
    }
)


def run_pending_stages(job_id: str) -> PipelineState:
    """Выполнить доступные этапы: STT → подготовка текста к ручному редактированию."""
    state = run_transcription_stage(job_id)
    if state.status == ArtifactStatus.FAILED:
        return state
    state = run_cleanup_stage(job_id)
    return state
