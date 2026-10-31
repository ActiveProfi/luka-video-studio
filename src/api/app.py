"""FastAPI — загрузка видео, этапы pipeline, human review."""

from __future__ import annotations

import json
import shutil
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agents.input_ingestion_agent import run_input_ingestion
from src.agents.tts_generation_agent import cleanup_text_hash_for_segments, current_tts_text_hash
from src.api.pipeline_catalog import DECISION_LABELS, UI_STAGES
from src.config import get_settings
from src.services import job_execution
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.orchestrator.pipeline_state import PipelineState
from src.orchestrator.pipeline_runner import run_pending_stages, run_single_ui_stage, IMPLEMENTED_UI_STAGES
from src.orchestrator.run_pipeline import new_job_id
from src.services.cleanup_review_service import (
    REVIEW_FILENAME,
    approve_cleanup_review,
    cleanup_artifacts_ready,
    cleanup_review_approved,
    fit_speech_script_timing_with_ai,
    get_cleanup_edit_payload,
    improve_all_cleanup_segments_with_ai,
    improve_cleanup_segment_with_ai,
    improve_full_text_with_ai,
    load_cleanup_review,
    save_full_text_cleanup_edits,
    save_manual_cleanup_edits,
    save_speech_script_edits,
)
from src.services.annotation_placement_service import (
    re_render_annotation_preview,
    save_annotation_placement,
    save_annotation_studio,
)
from src.services.annotation_review_service import (
    annotation_review_approved,
    approve_annotation_review,
    get_annotation_edit_payload,
    reopen_annotation_review,
    save_annotation_review_comments,
)
from src.services.sync_review_service import (
    approve_sync_review,
    get_sync_edit_payload,
    reopen_sync_review,
    save_sync_review_edits,
    sync_review_approved,
)
from src.services.subtitle_review_service import (
    get_subtitle_edit_payload,
    save_subtitle_edits,
    save_subtitle_layout,
)
from src.services.subtitle_capture_service import (
    finalize_subtitles,
    get_capture_payload,
    merge_block_with_next,
    rebuild_blocks,
    save_layout,
    save_subtitle_blocks,
    split_block,
)
from src.services.timing_review_service import (
    refresh_timeline_after_review,
    timing_artifacts_ready,
    timing_pending_review_count,
    timing_stage_completed,
)
from src.services.stage_reset_service import (
    EXECUTABLE_UI_STAGES,
    RERUNNABLE_UI_STAGES,
    clear_from_ui_stage,
    reopen_cleanup_for_edit,
    reset_stage_for_rerun,
    stage_ui_actions,
    update_pipeline_state_after_clear,
    validate_stage_execute,
)

@asynccontextmanager
async def app_lifespan(app):
    # BackgroundTasks cannot survive a server restart. Preserve artifacts and
    # report the interruption honestly instead of leaving an infinite spinner.
    for path in get_settings().output_dir.glob("*/pipeline_state.json"):
        registry = ArtifactRegistry(path.parent)
        try:
            state = registry.load_json(path.name)
            if state.get("status") == "running":
                state.update(status="failed", error="Обработка прервана перезапуском приложения. Сохранённые результаты доступны; продолжите обработку.")
                registry.save_json(path.name, state)
        except (OSError, ValueError):
            continue
    yield


app = FastAPI(title="Video Instruction Studio", version="0.3.0", lifespan=app_lifespan)
from src.api.shorts import router as shorts_router
app.include_router(shorts_router)
_mutation_locks: dict[str, asyncio.Lock] = {}


@app.middleware("http")
async def serialize_job_changes(request, call_next):
    parts = request.url.path.strip("/").split("/")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and len(parts) >= 2 and parts[0] == "jobs":
        job_id = parts[1]
        async with _mutation_locks.setdefault(job_id, asyncio.Lock()):
            if job_execution.is_active(job_id):
                return JSONResponse(status_code=409, content={"detail": "Сейчас идёт обработка проекта. Дождитесь завершения."})
            return await call_next(request)
    return await call_next(request)


def _run_pipeline_background(job_id: str) -> None:
    import logging

    try:
        run_pending_stages(job_id)
    except Exception as exc:
        logging.getLogger(__name__).error("Фоновая обработка job %s: %s", job_id, exc)


def _run_single_stage_background(job_id: str, ui_stage_id: str) -> None:
    import logging

    logger = logging.getLogger(__name__)
    try:
        run_single_ui_stage(job_id, ui_stage_id)
        if ui_stage_id == "annotations":
            _finish_automatic_lesson(_registry(job_id), get_settings(), job_id)
        _auto_chain_ui_stages(job_id, ui_stage_id)
    except Exception as exc:
        logger.error("Перезапуск этапа %s job %s: %s", ui_stage_id, job_id, exc)
    finally:
        job_execution.release(job_id)


# v3: после озвучки сразу генерируем предложения аннотаций (подтверждение — вручную).
# Экспорт остаётся по кнопке пользователя.
AUTO_CHAIN_UI: dict[str, str] = {
    "upload": "subtitle_capture",
    "subtitle_capture": "voiceover",
    "voiceover": "annotations",
}


def _pipeline_to_ui(pipeline_stage: str) -> str | None:
    cs = _LEGACY_STAGE_ALIASES.get(pipeline_stage, pipeline_stage)
    for ui_id, pipe_stage in UI_STAGE_TO_PIPELINE.items():
        if pipe_stage == cs:
            return ui_id
    return None


def _auto_chain_ui_stages(job_id: str, completed_ui_stage: str) -> None:
    """После успешного шага запустить следующий автоматический этап."""
    import logging

    logger = logging.getLogger(__name__)
    next_ui = AUTO_CHAIN_UI.get(completed_ui_stage)
    while next_ui:
        settings = get_settings()
        registry = ArtifactRegistry(settings.job_output_dir(job_id))
        state_data = (
            registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
        )
        state_data = _reconcile_stale_running(registry, state_data)
        if state_data.get("status") == "failed":
            break
        if state_data.get("status") == "running":
            break
        from src.services.lesson_options_service import load_options

        if completed_ui_stage in {"upload", "subtitle_capture"} and not load_options(registry, settings).automatic:
            break
        try:
            validate_stage_execute(registry, job_id, next_ui)
        except ValueError:
            break
        if next_ui not in IMPLEMENTED_UI_STAGES:
            break
        logger.info("Авто-запуск следующего этапа %s для job %s", next_ui, job_id)
        try:
            run_single_ui_stage(job_id, next_ui)
        except Exception as exc:
            logger.exception("Авто-этап %s не выполнен job %s: %s", next_ui, job_id, exc)
            break
        if next_ui == "annotations":
            _finish_automatic_lesson(registry, settings, job_id)
            break
        completed_ui_stage = next_ui
        next_ui = AUTO_CHAIN_UI.get(next_ui)


def _finish_automatic_lesson(registry: ArtifactRegistry, settings, job_id: str) -> None:
    from src.services.lesson_options_service import load_options

    if not load_options(registry, settings).automatic:
        return
    state = registry.load_json("pipeline_state.json")
    if state.get("status") == "failed":
        return
    suggestions = registry.load_json("annotation_suggestions.json").get("suggestions", [])
    if any(not a.get("placement_confirmed") and not a.get("skipped") for a in suggestions):
        return
    approve_annotation_review(registry, job_id, approved_by="automatic")
    run_single_ui_stage(job_id, "export")


@app.get("/voices")
def available_voices() -> dict:
    from src.services.lesson_options_service import voice_catalog

    settings = get_settings()
    enabled = {"yandex": bool((settings.yandex_api_key or settings.yandex_gpt_api_key)
                              and (settings.yandex_folder_id or settings.yandex_gpt_folder_id)),
               "openai": bool(settings.openai_api_key), "elevenlabs": bool(settings.elevenlabs_api_key), "edge": True}
    return {"voices": [{"provider": provider, "id": voice, "label": label,
                         "available": enabled[provider]} for provider, voices in voice_catalog(settings).items()
                        for voice, label in voices.items()],
            "screen_analysis_available": bool(settings.openai_api_key)}


@app.post("/voices/preview")
async def preview_voice(payload: dict) -> FileResponse:
    import hashlib
    from src.services.lesson_options_service import LessonOptions
    from src.providers.tts.base import TTSChunk
    from src.providers.tts.runner import synthesize_with_fallback

    try:
        options = LessonOptions.model_validate(payload)
        options.validate_voice()
    except ValueError as exc:
        raise HTTPException(400, "Неверные настройки голоса") from exc
    settings = get_settings().model_copy(update={"tts_fallback_order": options.provider,
        "yandex_tts_voice": options.voice, "openai_tts_voice": options.voice,
        "yandex_tts_speed": options.speed, "openai_tts_speed": options.speed,
        "elevenlabs_voice_id": options.voice, "elevenlabs_speed": options.speed,
        "edge_tts_voice": options.voice, "edge_tts_speed": options.speed})
    text = "Открываем нужный раздел программы. Выбираем документ и нажимаем кнопку Создать."
    key = hashlib.sha256(f"{options.provider}|{options.voice}|{options.speed}".encode()).hexdigest()[:24]
    output = settings.output_dir / "_voice_samples" / f"{key}.wav"
    try:
        if not output.exists():
            await synthesize_with_fallback(TTSChunk(text=text, output_path=output, language="ru"), settings)
    except Exception as exc:
        raise HTTPException(502, "Не удалось прослушать выбранный голос. Проверьте доступность сервиса озвучки.") from exc
    return FileResponse(output, media_type="audio/wav")


@app.get("/jobs/{job_id}/options")
def get_lesson_options(job_id: str) -> dict:
    from src.services.lesson_options_service import load_options

    registry = _registry(job_id)
    result = load_options(registry, get_settings()).model_dump()
    logo = registry.artifact_path("company_logo.png")
    result["logo_url"] = f"/jobs/{job_id}/artifacts/company_logo.png?v={logo.stat().st_mtime_ns}" if logo.exists() else None
    for key,name in (("intro_preview_url","brand_intro.png"),("outro_preview_url","brand_outro.png")):
        image = registry.artifact_path(name)
        result[key] = f"/jobs/{job_id}/artifacts/{name}?v={image.stat().st_mtime_ns}" if image.exists() else None
    return result


@app.post("/branding/references")
async def upload_branding_reference(video: UploadFile = File(...)):
    from src.services.branding_reference_service import upload_reference
    try:
        return await upload_reference(video, get_settings())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/branding/references/{reference_id}")
def get_branding_reference(reference_id: str):
    from src.services.branding_reference_service import load_reference
    try:
        return load_reference(get_settings(), reference_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/branding/references/{reference_id}/preview")
def preview_branding_reference(reference_id: str):
    from src.services.branding_reference_service import load_reference, reference_directory
    try:
        load_reference(get_settings(), reference_id)
        return FileResponse(reference_directory(get_settings(), reference_id) / 'preview.mp4', media_type='video/mp4')
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


def _invalidate_brand_export(registry):
    registry.save_json("render_pending.json", {"reason": "branding"})
    update_pipeline_state_after_clear(registry, "export", include_self=True)
    for name in ("brand_intro.png", "brand_outro.png"):
        registry.artifact_path(name).unlink(missing_ok=True)


@app.post("/jobs/{job_id}/logo")
async def upload_company_logo(job_id: str, logo: UploadFile = File(...)):
    from src.services.brand_design_service import MAX_LOGO_BYTES, store_logo
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        store_logo(registry, await logo.read(MAX_LOGO_BYTES + 1))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _invalidate_brand_export(registry)
    return get_lesson_options(job_id)


@app.delete("/jobs/{job_id}/logo")
def delete_company_logo(job_id: str):
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    registry.artifact_path("company_logo.png").unlink(missing_ok=True)
    _invalidate_brand_export(registry)
    return get_lesson_options(job_id)


@app.post("/jobs/{job_id}/branding/preview")
def preview_lesson_branding(job_id: str):
    from src.services.lesson_options_service import load_options
    from src.services.lesson_title_service import render_title_previews
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    report = render_title_previews(registry, load_options(registry,get_settings()), get_settings())
    version = registry.artifact_path('brand_intro.png').stat().st_mtime_ns
    return {**report, "intro_url":f"/jobs/{job_id}/artifacts/brand_intro.png?v={version}",
            "outro_url":f"/jobs/{job_id}/artifacts/brand_outro.png?v={version}"}


@app.put("/jobs/{job_id}/options")
def save_lesson_options(job_id: str, payload: dict) -> dict:
    from src.services.lesson_options_service import LessonOptions, OPTIONS_FILE, load_options
    from src.services.stage_reset_service import clear_from_ui_stage

    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        options = LessonOptions.model_validate(payload)
        options.validate_voice()
    except ValueError as exc:
        raise HTTPException(400, "Неверные настройки урока") from exc
    previous = load_options(registry, get_settings())
    changed_voice = any(getattr(previous, key) != getattr(options, key) for key in ("provider", "voice", "speed"))
    if changed_voice:
        clear_from_ui_stage(registry, "voiceover", include_self=True)
        update_pipeline_state_after_clear(registry, "voiceover", include_self=True)
    else:
        from src.services.brand_design_service import BRAND_FIELDS
        if any(getattr(previous, key) != getattr(options, key) for key in BRAND_FIELDS):
            _invalidate_brand_export(registry)
    registry.save_json(OPTIONS_FILE, options.model_dump())
    return {"ok": True, "options": options.model_dump(), "voiceover_invalidated": changed_voice}


@app.post("/jobs/{job_id}/automatic")
def start_automatic_lesson(job_id: str, background_tasks: BackgroundTasks, payload: dict) -> dict:
    from src.services.timeblock_service import subtitles_saved
    from src.services.auto_voiceover_service import auto_voiceover_matches_subtitles, auto_voiceover_ready

    save_lesson_options(job_id, {**payload, "automatic": True})
    registry = _registry(job_id)
    if not registry.exists("video_meta.json") or not registry.exists("time_blocks.json"):
        stage = "upload"
    elif not subtitles_saved(registry):
        stage = "subtitle_capture"
    elif not auto_voiceover_ready(registry) or not auto_voiceover_matches_subtitles(registry):
        stage = "voiceover"
    elif annotation_review_approved(registry, job_id):
        stage = "export"
    else:
        stage = "annotations"
    started = _schedule_ui_stage(job_id, stage, background_tasks)
    return {"ok": started, "message": "Автоматическая обработка исходной записи запущена. Сохранённые правки текста сохраняются."}


RERUN_UI_TO_PIPELINE: dict[str, PipelineStage] = {
    "stt": PipelineStage.TRANSCRIPTION,
    "cleanup": PipelineStage.SPEECH_CLEANUP,
    "tts": PipelineStage.TTS,
    "edit": PipelineStage.VIDEO_EDIT,
    "annotations": PipelineStage.ANNOTATIONS,
    "subtitles": PipelineStage.SUBTITLES,
    "assembly": PipelineStage.ASSEMBLY,
}


def _current_stage_name_for_ui(stage_id: str) -> str:
    """Имя current_stage в pipeline_state (v2-этапы без enum — строкой)."""
    if stage_id in RERUN_UI_TO_PIPELINE:
        return RERUN_UI_TO_PIPELINE[stage_id].value
    return {
        "upload": "upload",
        "subtitle_capture": "subtitle_capture",
        "voiceover": "voiceover",
        "export": "assembly",
        "subtitle_blocks": "subtitle_blocks",
        "voiceover_script": "voiceover_script",
        "final_voiceover": "final_voiceover",
    }.get(stage_id, stage_id)

STAGE_RUN_LABELS: dict[str, str] = {
    "upload": "Анализ видео",
    "subtitle_capture": "Создание субтитров",
    "voiceover": "Озвучка",
    "export": "Экспорт",
    "stt": "Распознавание речи",
    "cleanup": "Подготовка сценария (тайминг 3.2)",
    "subtitle_blocks": "Разбивка на блоки (субтитры)",
    "voiceover_script": "Текст для озвучки",
    "final_voiceover": "Финальная озвучка",
    "timing": "Решения по таймингу",
    "edit": "Монтаж видео",
    "tts": "AI-озвучка",
    "subtitles": "Субтитры",
    "sync": "Синхронизация озвучки",
    "assembly": "Сборка урока",
    "annotations": "Аннотации",
}


def _ensure_pipeline_not_running(registry: ArtifactRegistry) -> dict[str, Any]:
    if job_execution.is_active(registry.job_dir.name):
        raise HTTPException(409, "Сейчас идёт обработка. Дождитесь завершения.")
    state_data = (
        registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    )
    state_data = _reconcile_stale_running(registry, state_data)
    if state_data.get("status") == "running":
        raise HTTPException(
            409,
            "Сейчас идёт обработка. Дождитесь завершения или обновите страницу.",
        )
    return state_data


def _schedule_ui_stage(job_id: str, ui_stage_id: str, background_tasks: BackgroundTasks) -> bool:
    """Поставить UI-этап в фон. True — задача поставлена."""
    registry = ArtifactRegistry(get_settings().job_output_dir(job_id))
    state_data = (
        registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    )
    state_data = _reconcile_stale_running(registry, state_data)
    if state_data.get("status") == "running":
        return False
    try:
        validate_stage_execute(registry, job_id, ui_stage_id)
    except ValueError:
        return False
    if ui_stage_id not in IMPLEMENTED_UI_STAGES:
        return False
    pipeline_stage = _current_stage_name_for_ui(ui_stage_id)
    state = PipelineState(
        job_id=job_id,
        output_dir=str(registry.job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=list(state_data.get("stages_completed") or []),
        current_stage=pipeline_stage,
    )
    if not job_execution.reserve(job_id):
        return False
    try:
        registry.save_json("pipeline_state.json", state.to_dict())
        background_tasks.add_task(_run_single_stage_background, job_id, ui_stage_id)
    except Exception:
        job_execution.release(job_id)
        raise
    return True


def _schedule_processing(job_id: str, background_tasks: BackgroundTasks) -> None:
    """v3: сразу после загрузки — анализ ролика и авторазбиение на тайм-блоки."""
    _schedule_ui_stage(job_id, "upload", background_tasks)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReviewResolutionItem(BaseModel):
    review_id: str
    final_decision: str
    approved_by: str = "user"
    custom_parameters: dict | None = None


class ReviewResolutionPayload(BaseModel):
    resolutions: list[ReviewResolutionItem]


class SingleReviewAction(BaseModel):
    final_decision: str
    approved_by: str = "user"


class CleanupSegmentEdit(BaseModel):
    segment_id: str
    text: str


class CleanupEditPayload(BaseModel):
    segments: list[CleanupSegmentEdit] | None = None
    full_text: str | None = None
    speech_script_text: str | None = None
    saved_by: str = "user"


class CleanupImproveFullPayload(BaseModel):
    full_text: str | None = None


class CleanupApprovePayload(BaseModel):
    segments: list[CleanupSegmentEdit] | None = None
    full_text: str | None = None
    speech_script_text: str | None = None
    approved_by: str = "user"


class AnnotationBlockComment(BaseModel):
    block_id: str
    user_comment: str = ""


class AnnotationEditPayload(BaseModel):
    blocks: list[AnnotationBlockComment]
    saved_by: str = "user"


class AnnotationApprovePayload(BaseModel):
    blocks: list[AnnotationBlockComment] | None = None
    approved_by: str = "user"


class AnnotationPlacementPayload(BaseModel):
    type: str = "arrow"
    x: float = 0.0
    y: float = 0.0
    width: float | None = None
    height: float | None = None
    arrow_direction: str | None = "left"
    arrow_length_ratio: float | None = 0.08
    target_start: float | None = None
    target_end: float | None = None
    skipped: bool = False
    saved_by: str = "user"


class AnnotationStudioItemPayload(BaseModel):
    annotation_id: str | None = None
    type: str = "highlight_rect"
    text: str = ""
    target_start: float = 0.0
    target_end: float = 3.0
    x: float = 0.5
    y: float = 0.5
    width: float | None = 0.18
    height: float | None = 0.1
    arrow_direction: str | None = "left"
    arrow_length_ratio: float | None = 0.08
    skipped: bool = False


class AnnotationStudioSavePayload(BaseModel):
    items: list[AnnotationStudioItemPayload]
    replace_all: bool = True
    saved_by: str = "user"


class SubtitleCueTextUpdate(BaseModel):
    cue_id: str
    text: str
    source_segment_id: str | None = None
    start: float | None = None
    end: float | None = None


class SubtitleEditSavePayload(BaseModel):
    """Сохранение оформления и/или текста субтитров (озвучка не меняется)."""
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    font_size_px: int | None = None
    alignment: str | None = None
    font_color: str | None = None
    background_color: str | None = None
    background_opacity: float | None = None
    font_bold: bool | None = None
    font_italic: bool | None = None
    cues: list[SubtitleCueTextUpdate] | None = None
    saved_by: str = "user"


class SyncBlockEdit(BaseModel):
    block_id: str
    offset_adjustment_seconds: float = 0.0
    user_comment: str = ""


class SyncEditPayload(BaseModel):
    blocks: list[SyncBlockEdit]
    saved_by: str = "user"


class SyncApprovePayload(BaseModel):
    blocks: list[SyncBlockEdit] | None = None
    approved_by: str = "user"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/pipeline/steps")
def pipeline_steps() -> dict:
    return {
        "steps": [
            {
                "id": s.id,
                "order": s.order,
                "title": s.title,
                "description": s.description,
            }
            for s in UI_STAGES
        ]
    }


@app.get("/jobs")
def list_jobs() -> dict:
    settings = get_settings()
    jobs = []
    if settings.output_dir.exists():
        for d in sorted(settings.output_dir.iterdir(), reverse=True):
            if d.is_dir() and not (d / "input_manifest.json").exists() and not (d / "pipeline_state.json").exists():
                continue
            if not d.is_dir():
                continue
            registry = ArtifactRegistry(d)
            manifest_name = ""
            if registry.exists("input_manifest.json"):
                manifest = registry.load_json("input_manifest.json")
                manifest_name = Path(manifest.get("raw_video_path", "")).name
            state_data = (
                registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
            )
            state_data = _reconcile_stale_running(registry, state_data)
            progress = _job_progress(registry, state_data)
            jobs.append(
                {
                    "job_id": d.name,
                    "path": str(d),
                    "display_name": (registry.load_json("lesson_options.json").get("title", "").strip() if registry.exists("lesson_options.json") else "") or manifest_name or d.name,
                    "stages_done": progress["stages_done"],
                    "has_transcript": progress["has_transcript"],
                    "has_cleanup": progress["has_cleanup"],
                    "has_cleanup_approved": progress["has_cleanup_approved"],
                    "has_timing": progress["has_timing"],
                    "has_timing_completed": progress["has_timing_completed"],
                    "has_edited_video": progress["has_edited_video"],
                    "has_voiceover": progress["has_voiceover"],
                    "has_subtitles": progress["has_subtitles"],
                    "has_sync": progress["has_sync"],
                    "has_assembly": progress["has_assembly"],
                    "has_annotations": progress["has_annotations"],
                    "pipeline_status": progress["pipeline_status"],
                }
            )
    jobs.sort(key=lambda j: (j["stages_done"], j["job_id"]), reverse=True)
    return {"jobs": jobs}


@app.post("/jobs/from-fixtures")
def create_job_from_fixtures(background_tasks: BackgroundTasks) -> dict:
    """Быстрый старт с тестовым видео из папки fixtures (без повторной загрузки)."""
    settings = get_settings()
    raw = settings.fixtures_dir / "raw_video.mp4"
    if not raw.exists():
        raise HTTPException(404, "Файл fixtures/raw_video.mp4 не найден")

    ref = settings.fixtures_dir / "reference_final.mp4"
    ref_path = ref if ref.exists() else None

    job_id = new_job_id()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)
    state = PipelineState(job_id=job_id, output_dir=str(job_dir))
    state.mark_running(PipelineStage.INPUT)
    run_input_ingestion(registry, settings, job_id, raw, ref_path)
    state.mark_stage_done(PipelineStage.INPUT)
    state.status = ArtifactStatus.COMPLETED
    registry.save_json("pipeline_state.json", state.to_dict())
    _schedule_processing(job_id, background_tasks)

    return {
        "job_id": job_id,
        "message": "Тестовое видео подключено. Идёт разбивка на тайм-блоки.",
        "stages": _build_stages(registry, state),
    }


@app.post("/jobs/upload")
async def upload_job(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    reference: UploadFile | None = File(None),
    options: str | None = Form(None),
    company_logo: UploadFile | None = File(None),
) -> dict:
    if not video.filename or not video.filename.lower().endswith((".mp4", ".mov", ".webm")):
        raise HTTPException(400, "Загрузите видеофайл (.mp4, .mov или .webm)")

    settings = get_settings()
    from src.services.lesson_options_service import LessonOptions, OPTIONS_FILE
    try:
        lesson_options = LessonOptions.model_validate_json(options) if options else LessonOptions()
        lesson_options.validate_voice()
    except ValueError as exc:
        raise HTTPException(400, "Неверные настройки голоса или урока") from exc
    job_id = new_job_id()
    job_dir = settings.job_output_dir(job_id)
    upload_dir = job_dir / "_upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    registry = ArtifactRegistry(job_dir)
    if company_logo:
        from src.services.brand_design_service import MAX_LOGO_BYTES, store_logo
        try:
            store_logo(registry, await company_logo.read(MAX_LOGO_BYTES + 1))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    raw_path = upload_dir / "raw_video.mp4"
    with raw_path.open("wb") as f:
        shutil.copyfileobj(video.file, f)

    ref_path: Path | None = None
    if reference and reference.filename:
        ref_path = upload_dir / "reference_final.mp4"
        with ref_path.open("wb") as f:
            shutil.copyfileobj(reference.file, f)

    registry = ArtifactRegistry(job_dir)
    registry.save_json(OPTIONS_FILE, lesson_options.model_dump())
    state = PipelineState(job_id=job_id, output_dir=str(job_dir))
    state.mark_running(PipelineStage.INPUT)
    run_input_ingestion(registry, settings, job_id, raw_path, ref_path)
    state.mark_stage_done(PipelineStage.INPUT)
    state.status = ArtifactStatus.COMPLETED
    registry.save_json("pipeline_state.json", state.to_dict())
    _schedule_processing(job_id, background_tasks)

    return {
        "job_id": job_id,
        "message": "Исходная запись загружена. Идёт подготовка сценария, чистой озвучки и аннотаций. Спорные фрагменты появятся для проверки.",
        "stages": _build_stages(registry, state),
    }


@app.post("/jobs/{job_id}/run")
def run_job(job_id: str, background_tasks: BackgroundTasks) -> dict:
    """Запуск обработки: STT → подготовка текста к ручному редактированию."""
    registry = _registry(job_id)
    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state_data = _reconcile_stale_running(registry, state_data)

    if registry.exists("clean_transcript.json") and registry.exists("edits_map.json"):
        if not cleanup_review_approved(registry, job_id):
            review = load_cleanup_review(registry, job_id)
            if review.get("status") != "approved":
                state = _state_from_data(job_id, registry, state_data)
                return {
                    "job_id": job_id,
                    "status": "needs_review",
                    "message": "Текст распознан и готов к редактированию. Проверьте его и нажмите «Подтвердить».",
                    "stages": _build_stages(registry, state),
                }

    if cleanup_review_approved(registry, job_id):
        if registry.exists("final_lesson.mp4"):
            state = _state_from_data(job_id, registry, state_data)
            return {
                "job_id": job_id,
                "status": "completed",
                "message": "Урок собран. Можно скачать final_lesson.mp4.",
                "stages": _build_stages(registry, state),
            }

    if state_data.get("status") == "running":
        if registry.exists("raw_audio.ogg") and not registry.exists("transcript.json"):
            return {
                "job_id": job_id,
                "status": "running",
                "message": "Распознавание речи выполняется. Подождите 5–15 минут для длинного видео.",
                "stages": _build_stages(registry, _state_from_data(job_id, registry, state_data)),
            }
        if registry.exists("transcript.json") and not cleanup_artifacts_ready(registry):
            return {
                "job_id": job_id,
                "status": "running",
                "message": "Текст готовится к редактированию. Подождите несколько секунд.",
                "stages": _build_stages(registry, _state_from_data(job_id, registry, state_data)),
            }
        if cleanup_review_approved(registry, job_id) and not registry.exists("voiceover.wav"):
            return {
                "job_id": job_id,
                "status": "running",
                "message": "AI-озвучка выполняется. Подождите 2–5 минут.",
                "stages": _build_stages(registry, _state_from_data(job_id, registry, state_data)),
            }
        if registry.exists("voiceover.wav") and not registry.exists("edited_video.mp4"):
            return {
                "job_id": job_id,
                "status": "running",
                "message": "Монтаж видео выполняется. Подождите 1–3 минуты.",
                "stages": _build_stages(registry, _state_from_data(job_id, registry, state_data)),
            }
        if registry.exists("edited_video.mp4") and not registry.exists("subtitles.srt"):
            return {
                "job_id": job_id,
                "status": "running",
                "message": "Субтитры формируются. Подождите несколько секунд.",
                "stages": _build_stages(registry, _state_from_data(job_id, registry, state_data)),
            }
        if (
            registry.exists("subtitles.srt")
            and not registry.exists("annotation_suggestions.json")
        ):
            return {
                "job_id": job_id,
                "status": "running",
                "message": "Аннотации формируются. Подождите 1–2 минуты.",
                "stages": _build_stages(registry, _state_from_data(job_id, registry, state_data)),
            }

    next_stage = _next_pipeline_stage(registry, job_id)
    if next_stage is None:
        state = _state_from_data(job_id, registry, state_data)
        return {
            "job_id": job_id,
            "status": "completed",
            "message": "Все доступные этапы уже выполнены.",
            "stages": _build_stages(registry, state),
        }

    state = PipelineState(
        job_id=job_id,
        output_dir=str(registry.job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=state_data.get("stages_completed", []),
        current_stage=next_stage.value,
    )
    registry.save_json("pipeline_state.json", state.to_dict())
    background_tasks.add_task(_run_pipeline_background, job_id)

    if next_stage == PipelineStage.SUBTITLES:
        message = "Субтитры запущены. Обновите страницу через несколько секунд."
        next_label = "Субтитры"
    elif next_stage == PipelineStage.TTS:
        message = "AI-озвучка запущена. Обновите страницу через 2–5 минут."
        next_label = "AI-озвучка"
    elif next_stage == PipelineStage.VIDEO_EDIT:
        message = "Монтаж видео запущен. Обновите страницу через 2–5 минут."
        next_label = "Монтаж видео"
    elif next_stage == PipelineStage.TIMING_POLICY:
        message = "Решения по таймингу запущены. Обновите страницу через 1–2 минуты."
        next_label = "Решения по таймингу"
    elif next_stage == PipelineStage.SPEECH_CLEANUP:
        message = "Подготовка текста к редактированию запущена. Обновите страницу через несколько секунд."
        next_label = "Редактирование текста"
    else:
        message = "Распознавание речи запущено. Обновите страницу через несколько минут."
        next_label = "Распознавание речи"

    return {
        "job_id": job_id,
        "status": "started",
        "message": message,
        "next_stage": next_label,
        "stages": _build_stages(registry, state),
    }


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    registry = _registry(job_id)
    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    state_data = _reconcile_stale_running(registry, state_data)
    return {
        "job_id": job_id,
        "artifacts": registry.list_artifacts(),
        "state": state_data,
        "stages": _build_stages(registry, _state_from_data(job_id, registry, state_data)),
    }


@app.get("/jobs/{job_id}/stages")
def get_job_stages(job_id: str) -> dict:
    registry = _registry(job_id)
    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    return {"job_id": job_id, "stages": _build_stages(registry, _state_from_data(job_id, registry, state_data))}


@app.get("/jobs/{job_id}/artifacts/{filename}")
def get_artifact(job_id: str, filename: str, download: bool = False):
    registry = _registry(job_id)
    path = registry.artifact_path(filename)
    if not path.exists():
        raise HTTPException(404, f"Файл {filename} не найден")

    suffix = path.suffix.lower()
    if suffix == ".mp4":
        if download:
            return FileResponse(
                path,
                media_type="video/mp4",
                filename=f"{job_id}_{filename}",
            )
        return FileResponse(path, media_type="video/mp4")
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        media = "image/png" if suffix == ".png" else "image/jpeg"
        return FileResponse(path, media_type=media)
    if suffix == ".wav":
        return FileResponse(path, media_type="audio/wav")
    if suffix in {".json", ".srt", ".txt"}:
        content = path.read_text(encoding="utf-8")
        if suffix == ".json":
            return JSONResponse(json.loads(content))
        return JSONResponse({"content": content, "filename": filename})
    return FileResponse(path)


@app.get("/jobs/{job_id}/cleanup/edit")
def get_cleanup_edit(job_id: str) -> dict:
    registry = _registry(job_id)
    try:
        return get_cleanup_edit_payload(registry, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


def _start_pipeline_after_cleanup(
    job_id: str,
    registry: ArtifactRegistry,
    cleanup_data: dict[str, Any],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    clear_from_ui_stage(registry, "tts", include_self=True)
    state_data = update_pipeline_state_after_clear(registry, "tts", include_self=True)
    state = PipelineState(
        job_id=job_id,
        output_dir=str(registry.job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=state_data.get("stages_completed", []),
        current_stage=PipelineStage.TTS.value,
    )
    registry.save_json("pipeline_state.json", state.to_dict())
    background_tasks.add_task(_run_single_stage_background, job_id, "tts")
    return {
        "ok": True,
        "message": (
            "Текст подтверждён. Запускаем шаг 4 — AI-озвучка "
            "(именно сохранённый вами текст), затем шаг 5 (монтаж) и шаг 6 (субтитры)."
        ),
        "cleanup": cleanup_data,
        "stages": _build_stages(registry, state),
    }


@app.put("/jobs/{job_id}/cleanup/edit")
def save_cleanup_edit(job_id: str, payload: CleanupEditPayload) -> dict:
    """Только сохранить правки текста — без запуска озвучки."""
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        old_hash = current_tts_text_hash(registry) if registry.exists("clean_transcript.json") else None
        if payload.speech_script_text is not None:
            data = save_speech_script_edits(
                registry, job_id, payload.speech_script_text, saved_by=payload.saved_by
            )
        elif payload.full_text is not None:
            data = save_full_text_cleanup_edits(
                registry, job_id, payload.full_text, saved_by=payload.saved_by
            )
        elif payload.segments:
            segments = [s.model_dump() for s in payload.segments]
            data = save_manual_cleanup_edits(registry, job_id, segments, saved_by=payload.saved_by)
        else:
            raise HTTPException(400, "Передайте speech_script_text, full_text или segments")
        new_hash = current_tts_text_hash(registry) if registry.exists("clean_transcript.json") else None
        if old_hash != new_hash:
            clear_from_ui_stage(registry, "tts", include_self=True)
            update_pipeline_state_after_clear(registry, "tts", include_self=True)
        return data
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/cleanup/improve-full")
def improve_cleanup_full_text(job_id: str, payload: CleanupImproveFullPayload | None = None) -> dict:
    """Подшаг 3.1: подготовка Speech Script (технический конвейер)."""
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    payload = payload or CleanupImproveFullPayload()
    try:
        return improve_full_text_with_ai(registry, job_id, full_text=payload.full_text)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/jobs/{job_id}/cleanup/fit-timing")
def fit_cleanup_speech_script_timing(
    job_id: str, payload: CleanupImproveFullPayload | None = None
) -> dict:
    """Подшаг 3.2: ИИ-помощник подгоняет Speech Script под тайминг озвучки."""
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    payload = payload or CleanupImproveFullPayload()
    try:
        return fit_speech_script_timing_with_ai(registry, job_id, full_text=payload.full_text)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/jobs/{job_id}/cleanup/improve/{segment_id}")
def improve_cleanup_segment(job_id: str, segment_id: str) -> dict:
    """ИИ-улучшение одного блока (не сохраняет — только предложение текста)."""
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        return improve_cleanup_segment_with_ai(registry, job_id, segment_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/jobs/{job_id}/cleanup/improve-all")
def improve_all_cleanup_segments(job_id: str) -> dict:
    """ИИ-улучшение всех блоков по очереди (не сохраняет автоматически)."""
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        return improve_all_cleanup_segments_with_ai(registry, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/jobs/{job_id}/cleanup/approve")
def approve_cleanup_edit(
    job_id: str,
    background_tasks: BackgroundTasks,
    payload: CleanupApprovePayload | None = None,
) -> dict:
    registry = _registry(job_id)
    payload = payload or CleanupApprovePayload()
    try:
        if payload.speech_script_text is not None:
            save_speech_script_edits(
                registry, job_id, payload.speech_script_text, saved_by=payload.approved_by
            )
            data = approve_cleanup_review(registry, job_id, approved_by=payload.approved_by)
        elif payload.full_text is not None:
            data = approve_cleanup_review(
                registry, job_id, full_text=payload.full_text, approved_by=payload.approved_by
            )
        else:
            segments = [s.model_dump() for s in payload.segments] if payload.segments else None
            data = approve_cleanup_review(registry, job_id, segments, approved_by=payload.approved_by)
        return _start_pipeline_after_cleanup(job_id, registry, data, background_tasks)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/jobs/{job_id}/sync/edit")
def get_sync_edit(job_id: str) -> dict:
    registry = _registry(job_id)
    try:
        return get_sync_edit_payload(registry, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/jobs/{job_id}/sync/edit")
def save_sync_edit(job_id: str, payload: SyncEditPayload) -> dict:
    registry = _registry(job_id)
    try:
        blocks = [b.model_dump() for b in payload.blocks]
        return save_sync_review_edits(registry, job_id, blocks, saved_by=payload.saved_by)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/sync/approve")
def approve_sync_edit(job_id: str, payload: SyncApprovePayload | None = None) -> dict:
    registry = _registry(job_id)
    payload = payload or SyncApprovePayload()
    try:
        blocks = [b.model_dump() for b in payload.blocks] if payload.blocks else None
        data = approve_sync_review(registry, job_id, blocks, approved_by=payload.approved_by)
        state_data = (
            registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
        )
        state = _state_from_data(job_id, registry, state_data)
        if PipelineStage.VOICE_VIDEO_SYNC.value not in state.stages_completed:
            state.mark_stage_done(PipelineStage.VOICE_VIDEO_SYNC)
        state.status = ArtifactStatus.COMPLETED
        registry.save_json("pipeline_state.json", state.to_dict())
        return {
            "ok": True,
            "message": "Синхронизация подтверждена. Можно переходить к шагу 9 — сборка урока.",
            "sync": data,
            "stages": _build_stages(registry, state),
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/sync/reopen")
def reopen_sync_edit(job_id: str) -> dict:
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        data = reopen_sync_review(registry, job_id)
        removed = clear_from_ui_stage(registry, "assembly", include_self=True)
        update_pipeline_state_after_clear(registry, "assembly", include_self=True)
        state_data = (
            registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
        )
        state = _state_from_data(job_id, registry, state_data)
        return {
            "ok": True,
            "message": "Синхронизация снова доступна для правки. Шаги 9+ сброшены.",
            "sync": data,
            "removed_artifacts": removed,
            "stages": _build_stages(registry, state),
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/jobs/{job_id}/annotations/edit")
def get_annotation_edit(job_id: str) -> dict:
    registry = _registry(job_id)
    try:
        return get_annotation_edit_payload(registry, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/jobs/{job_id}/annotations/edit")
def save_annotation_edit(job_id: str, payload: AnnotationEditPayload) -> dict:
    registry = _registry(job_id)
    try:
        blocks = [b.model_dump() for b in payload.blocks]
        return save_annotation_review_comments(registry, job_id, blocks, saved_by=payload.saved_by)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/annotations/approve")
def approve_annotation_edit(job_id: str, payload: AnnotationApprovePayload | None = None) -> dict:
    registry = _registry(job_id)
    payload = payload or AnnotationApprovePayload()
    try:
        blocks = [b.model_dump() for b in payload.blocks] if payload.blocks else None
        data = approve_annotation_review(registry, job_id, blocks, approved_by=payload.approved_by)
        state_data = (
            registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
        )
        state = _state_from_data(job_id, registry, state_data)
        if PipelineStage.ANNOTATIONS.value not in state.stages_completed:
            state.mark_stage_done(PipelineStage.ANNOTATIONS)

        # Шаг «Экспорт» убран: сразу собираем финальный файл для скачивания
        download_url: str | None = None
        assembly_error: str | None = None
        try:
            from src.agents.lesson_assembly_agent import run_lesson_assembly
            from src.config import get_settings
            from src.services.subtitle_burn_service import ensure_subtitled_studio_video

            settings = get_settings()
            ensure_subtitled_studio_video(registry, settings, force=True)
            run_lesson_assembly(registry, settings, job_id, force=True)
            if PipelineStage.ASSEMBLY.value not in state.stages_completed:
                state.mark_stage_done(PipelineStage.ASSEMBLY)
            download_url = f"/jobs/{job_id}/artifacts/final_lesson.mp4?download=1"
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("Сборка после подтверждения аннотаций не удалась")
            assembly_error = str(exc)

        state.status = ArtifactStatus.COMPLETED
        registry.save_json("pipeline_state.json", state.to_dict())
        if download_url:
            message = "Готово! Скачайте урок — в нём озвучка, ваши субтитры (как настроили) и аннотации."
        elif assembly_error:
            message = (
                "Аннотации подтверждены, но сборка файла не удалась. "
                f"Причина: {assembly_error}"
            )
        else:
            message = "Аннотации подтверждены."
        return {
            "ok": True,
            "message": message,
            "download_url": download_url,
            "final_ready": bool(download_url),
            "annotations": data,
            "stages": _build_stages(registry, state),
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/annotations/reopen")
def reopen_annotation_edit(job_id: str) -> dict:
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        data = reopen_annotation_review(registry, job_id)
        state_data = (
            registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
        )
        state = _state_from_data(job_id, registry, state_data)
        return {
            "ok": True,
            "message": "Аннотации снова доступны для проверки и комментариев.",
            "annotations": data,
            "stages": _build_stages(registry, state),
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/jobs/{job_id}/annotations/studio")
def save_annotation_studio_endpoint(job_id: str, payload: AnnotationStudioSavePayload) -> dict:
    """Студия аннотаций: рамка/стрелка на кадре + длительность на дорожке."""
    registry = _registry(job_id)
    try:
        data = save_annotation_studio(
            registry,
            job_id,
            [item.model_dump() for item in payload.items],
            saved_by=payload.saved_by,
            replace_all=payload.replace_all,
        )
        return {
            "ok": True,
            "message": "Аннотации студии сохранены. Превью обновлено.",
            "annotations": data,
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/jobs/{job_id}/annotations/{annotation_id}/placement")
def save_annotation_placement_endpoint(
    job_id: str,
    annotation_id: str,
    payload: AnnotationPlacementPayload,
) -> dict:
    registry = _registry(job_id)
    try:
        data = save_annotation_placement(
            registry,
            job_id,
            annotation_id,
            payload.model_dump(),
            saved_by=payload.saved_by,
        )
        return {
            "ok": True,
            "message": "Координаты сохранены. Превью видео обновлено.",
            **data,
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/annotations/render-preview")
def render_annotation_preview_endpoint(job_id: str) -> dict:
    registry = _registry(job_id)
    try:
        re_render_annotation_preview(registry, job_id)
        return {
            "ok": True,
            "message": "Превью аннотаций пересобрано.",
            "preview_video_url": f"/jobs/{job_id}/artifacts/annotation_preview.mp4",
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


# --- Этап 2 (v3): субтитры прямо на видео ---


class CaptureBlockPayload(BaseModel):
    id: int
    subtitle: str = ""


class CaptureSavePayload(BaseModel):
    blocks: list[CaptureBlockPayload] = []
    saved_by: str = "user"


class CaptureSplitPayload(BaseModel):
    block_id: int
    at_seconds: float


class CaptureMergePayload(BaseModel):
    block_id: int


class CaptureLayoutPayload(BaseModel):
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    font_size_px: int | None = None
    alignment: str | None = None
    font_color: str | None = None
    background_color: str | None = None
    background_opacity: float | None = None
    font_bold: bool | None = None
    font_italic: bool | None = None


@app.get("/jobs/{job_id}/capture")
def get_capture(job_id: str) -> dict:
    """Данные основного экрана: видео, тайм-блоки и оформление субтитра."""
    registry = _registry(job_id)
    try:
        return get_capture_payload(registry, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.put("/jobs/{job_id}/capture")
def save_capture(job_id: str, payload: CaptureSavePayload) -> dict:
    """Промежуточное сохранение текста субтитров."""
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        data = save_subtitle_blocks(
            registry, job_id, [b.model_dump() for b in payload.blocks]
        )
        return {"ok": True, "message": "Черновик субтитров сохранён.", "capture": data}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/capture/save")
def finalize_capture(
    job_id: str,
    background_tasks: BackgroundTasks,
    payload: CaptureSavePayload | None = None,
) -> dict:
    """Кнопка «Сохранить»: субтитры → источник данных, затем автоозвучка в фоне."""
    registry = _registry(job_id)
    payload = payload or CaptureSavePayload()
    try:
        _ensure_pipeline_not_running(registry)
        blocks = [b.model_dump() for b in payload.blocks] if payload.blocks else None
        data = finalize_subtitles(registry, job_id, blocks)

        from src.services.auto_voiceover_service import (
            auto_voiceover_matches_subtitles,
            auto_voiceover_ready,
        )

        message = "Субтитры сохранены."
        started = False
        if auto_voiceover_ready(registry) and auto_voiceover_matches_subtitles(registry):
            message = "Субтитры сохранены. Озвучка уже соответствует тексту."
        else:
            started = _schedule_ui_stage(job_id, "voiceover", background_tasks)
            message = (
                "Субтитры сохранены. Запускаю озвучку…"
                if started
                else "Субтитры сохранены. Озвучку можно запустить кнопкой на этапе 3."
            )

        state_data = (
            registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
        )
        state = _state_from_data(job_id, registry, state_data)
        return {
            "ok": True,
            "message": message,
            "voiceover_started": started,
            "capture": data,
            "stages": _build_stages(registry, state),
        }
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/capture/split")
def split_capture_block(job_id: str, payload: CaptureSplitPayload) -> dict:
    registry = _registry(job_id)
    try:
        data = split_block(registry, job_id, payload.block_id, payload.at_seconds)
        return {"ok": True, "message": "Блок разделён.", "capture": data}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/capture/merge")
def merge_capture_block(job_id: str, payload: CaptureMergePayload) -> dict:
    registry = _registry(job_id)
    try:
        data = merge_block_with_next(registry, job_id, payload.block_id)
        return {"ok": True, "message": "Блоки склеены.", "capture": data}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/capture/rebuild")
def rebuild_capture_blocks(job_id: str) -> dict:
    """Пересобрать разбиение автоматически (введённый текст сохраняется)."""
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        data = rebuild_blocks(registry, job_id)
        return {"ok": True, "message": "Разбивка пересобрана.", "capture": data}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.put("/jobs/{job_id}/capture/layout")
def save_capture_layout(job_id: str, payload: CaptureLayoutPayload, background_tasks: BackgroundTasks) -> dict:
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        data = save_layout(registry, job_id, payload.model_dump(exclude_none=True))
        started = False
        if registry.exists("render_pending.json") and registry.exists("approved_annotations.json"):
            from src.services.auto_voiceover_service import auto_voiceover_matches_subtitles, auto_voiceover_ready

            if auto_voiceover_ready(registry) and auto_voiceover_matches_subtitles(registry):
                started = _schedule_ui_stage(job_id, "export", background_tasks)
        state = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
        message = "Оформление сохранено и будет применено при сборке видео."
        if started:
            message = "Обновляю только оформление видео. Текст, озвучка и аннотации сохранены."
        elif registry.exists("final_lesson.mp4") and not registry.exists("render_pending.json"):
            message = "Это оформление уже применено. Готовый ролик и все этапы сохранены."
        return {
            "ok": True,
            "message": message,
            "capture": data,
            "stages": _build_stages(registry, _state_from_data(job_id, registry, state)),
        }
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/jobs/{job_id}/subtitles/edit")
def get_subtitle_edit(job_id: str) -> dict:
    registry = _registry(job_id)
    try:
        return get_subtitle_edit_payload(registry, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/jobs/{job_id}/subtitles/edit")
def save_subtitle_edit(job_id: str, payload: SubtitleEditSavePayload) -> dict:
    registry = _registry(job_id)
    try:
        raw = payload.model_dump(exclude={"saved_by", "cues"}, exclude_none=True)
        layout = raw if raw else None
        cues = [c.model_dump() for c in payload.cues] if payload.cues else None
        data = save_subtitle_edits(
            registry,
            job_id,
            layout=layout,
            cues=cues,
            saved_by=payload.saved_by,
        )
        parts: list[str] = []
        if layout:
            parts.append("оформление")
        if cues:
            parts.append("текст субтитров")
        message = f"Сохранено: {', '.join(parts)}. Озвучка не изменена."
        return {
            "ok": True,
            "message": message,
            "subtitles": data,
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/jobs/{job_id}/voiceover-script/edit")
def get_voiceover_script_edit(job_id: str) -> dict:
    """Шаг 5: dual-редактор — субтитры + текст озвучки."""
    from src.services.voiceover_script_service import get_voiceover_script_edit_payload

    registry = _registry(job_id)
    try:
        return get_voiceover_script_edit_payload(registry, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class VoiceoverScriptSavePayload(BaseModel):
    blocks: list[dict]


@app.put("/jobs/{job_id}/voiceover-script/edit")
def save_voiceover_script_edit(job_id: str, payload: VoiceoverScriptSavePayload) -> dict:
    from src.services.voiceover_script_service import save_voiceover_script_edits

    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        data = save_voiceover_script_edits(registry, job_id, payload.blocks)
        return {
            "ok": True,
            "message": "Тексты сохранены. Утвердите субтитры и озвучку отдельно.",
            "voiceover_script": data,
            "stages": _build_stages(registry, _state_from_data(job_id, registry, registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {})),
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class VoiceoverScriptApprovePayload(BaseModel):
    part: str  # subtitles | voiceover


@app.post("/jobs/{job_id}/voiceover-script/approve")
def approve_voiceover_script(job_id: str, payload: VoiceoverScriptApprovePayload) -> dict:
    from src.services.voiceover_script_service import approve_voiceover_script_part

    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        data = approve_voiceover_script_part(registry, job_id, part=payload.part)
        label = "субтитры" if payload.part == "subtitles" else "текст озвучки"
        return {
            "ok": True,
            "message": f"Утверждено: {label}.",
            "voiceover_script": data,
            "stages": _build_stages(registry, _state_from_data(job_id, registry, registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {})),
        }
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/jobs/{job_id}/subtitles/final-voiceover")
def run_subtitle_final_voiceover(job_id: str, background_tasks: BackgroundTasks) -> dict:
    """Legacy/подшаг: финальная AI-озвучка (также шаг 6 v2 через stage runner)."""
    registry = _registry(job_id)
    state_data = _ensure_pipeline_not_running(registry)
    if not registry.exists("subtitle_timing.json"):
        raise HTTPException(400, "Сначала сохраните субтитры")

    state = PipelineState(
        job_id=job_id,
        output_dir=str(registry.job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=state_data.get("stages_completed", []),
        current_stage="final_voiceover",
    )
    registry.save_json("pipeline_state.json", state.to_dict())
    background_tasks.add_task(_run_final_voiceover_background, job_id)
    return {
        "ok": True,
        "job_id": job_id,
        "message": "Финальная озвучка запущена. Страница обновится.",
        "stages": _build_stages(registry, state),
    }


def _run_final_voiceover_background(job_id: str) -> None:
    import logging

    from src.services.final_voiceover_from_subtitles import run_final_voiceover_from_subtitles

    logger = logging.getLogger(__name__)
    settings = get_settings()
    registry = ArtifactRegistry(settings.job_output_dir(job_id))
    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    completed = list(state_data.get("stages_completed") or [])
    try:
        result = run_final_voiceover_from_subtitles(registry, settings, job_id, force=True)
        state = PipelineState(
            job_id=job_id,
            output_dir=str(registry.job_dir),
            status=ArtifactStatus.COMPLETED,
            stages_completed=completed,
            current_stage=None,
            error=None,
        )
        registry.save_json("pipeline_state.json", state.to_dict())
        registry.save_json(
            "final_voiceover_report.json",
            {
                "job_id": job_id,
                "created_at": utc_now_iso(),
                "ok": True,
                "message": result.get("message"),
                "segment_count": result.get("segment_count"),
                "warnings": result.get("warnings") or [],
            },
        )
        logger.info("Подшаг 6.1 завершён job_id=%s", job_id)
    except Exception as exc:
        logger.exception("Подшаг 6.1 ошибка job_id=%s", job_id)
        state = PipelineState(
            job_id=job_id,
            output_dir=str(registry.job_dir),
            status=ArtifactStatus.FAILED,
            stages_completed=completed,
            current_stage=None,
            error=str(exc),
        )
        registry.save_json("pipeline_state.json", state.to_dict())
        registry.save_json(
            "final_voiceover_report.json",
            {
                "job_id": job_id,
                "created_at": utc_now_iso(),
                "ok": False,
                "message": str(exc),
            },
        )


@app.post("/jobs/{job_id}/cleanup/reopen")
def reopen_cleanup_text(job_id: str) -> dict:
    """Вернуться к правке текста (шаг 3) — сбрасывает подтверждение и шаги 4+."""
    registry = _registry(job_id)
    _ensure_pipeline_not_running(registry)
    try:
        cleanup = reopen_cleanup_for_edit(registry, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    state_data = (
        registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    )
    state = _state_from_data(job_id, registry, state_data)
    return {
        "ok": True,
        "message": (
            "Текст снова доступен для правки. После сохранения подтвердите его — "
            "затем заново пройдите шаги 4–7."
        ),
        "cleanup": cleanup,
        "stages": _build_stages(registry, state),
    }


@app.post("/jobs/{job_id}/stages/{stage_id}/rerun")
def rerun_ui_stage(job_id: str, stage_id: str, background_tasks: BackgroundTasks) -> dict:
    """Сбросить артефакты этапа и выполнить его заново (без прохождения с шага 1)."""
    if stage_id not in RERUNNABLE_UI_STAGES:
        raise HTTPException(400, f"Этап «{stage_id}» нельзя перезапустить")

    registry = _registry(job_id)
    state_data = _ensure_pipeline_not_running(registry)

    try:
        removed = reset_stage_for_rerun(registry, job_id, stage_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    pipeline_stage = _current_stage_name_for_ui(stage_id)
    state = PipelineState(
        job_id=job_id,
        output_dir=str(registry.job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=state_data.get("stages_completed", []),
        current_stage=pipeline_stage,
    )
    registry.save_json("pipeline_state.json", state.to_dict())
    if not job_execution.reserve(job_id):
        raise HTTPException(409, "Проект уже обрабатывается")
    background_tasks.add_task(_run_single_stage_background, job_id, stage_id)

    labels = STAGE_RUN_LABELS
    return {
        "ok": True,
        "job_id": job_id,
        "stage_id": stage_id,
        "removed_artifacts": removed,
        "message": f"{labels.get(stage_id, stage_id)} запущен заново. Страница обновится автоматически.",
        "stages": _build_stages(registry, state),
    }


@app.post("/jobs/{job_id}/stages/{stage_id}/execute")
def execute_ui_stage(job_id: str, stage_id: str, background_tasks: BackgroundTasks) -> dict:
    """Выполнить один UI-этап (без сброса артефактов)."""
    if stage_id not in EXECUTABLE_UI_STAGES:
        raise HTTPException(400, f"Этап «{stage_id}» пока нельзя запустить")

    registry = _registry(job_id)
    state_data = _ensure_pipeline_not_running(registry)

    try:
        validate_stage_execute(registry, job_id, stage_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if stage_id not in IMPLEMENTED_UI_STAGES:
        raise HTTPException(400, f"Этап «{STAGE_RUN_LABELS.get(stage_id, stage_id)}» пока в разработке")

    pipeline_stage = _current_stage_name_for_ui(stage_id)
    state = PipelineState(
        job_id=job_id,
        output_dir=str(registry.job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=state_data.get("stages_completed", []),
        current_stage=pipeline_stage,
    )
    registry.save_json("pipeline_state.json", state.to_dict())
    if not job_execution.reserve(job_id):
        raise HTTPException(409, "Проект уже обрабатывается")
    background_tasks.add_task(_run_single_stage_background, job_id, stage_id)

    label = STAGE_RUN_LABELS.get(stage_id, stage_id)
    return {
        "ok": True,
        "job_id": job_id,
        "stage_id": stage_id,
        "message": f"{label} запущен. Страница обновится автоматически.",
        "stages": _build_stages(registry, state),
    }


@app.get("/jobs/{job_id}/review")
def get_review_bundle(job_id: str) -> dict:
    registry = _registry(job_id)
    if registry.exists("review_bundle.json"):
        bundle = registry.load_json("review_bundle.json")
        items = bundle.get("items", [])
    else:
        items = _review_items_from_timing(registry)

    resolved_ids: set[str] = set()
    if registry.exists("review_resolution.json"):
        res = registry.load_json("review_resolution.json")
        resolved_ids = {r["review_id"] for r in res.get("resolutions", [])}

    enriched = []
    for item in items:
        enriched.append(
            {
                **item,
                "proposed_label": DECISION_LABELS.get(item.get("proposed_decision", ""), item.get("proposed_decision")),
                "time_label": _format_time_range(item.get("video_excerpt_start"), item.get("video_excerpt_end")),
                "resolved": item.get("review_id") in resolved_ids,
            }
        )

    return {
        "job_id": job_id,
        "items": enriched,
        "total": len(enriched),
        "pending": sum(1 for i in enriched if not i["resolved"]),
    }


@app.post("/jobs/{job_id}/review/{review_id}/approve")
def approve_review_item(job_id: str, review_id: str) -> dict:
    registry = _registry(job_id)
    bundle = _load_review_items(registry)
    item = next((i for i in bundle if i.get("review_id") == review_id), None)
    if not item:
        raise HTTPException(404, "Спорный фрагмент не найден")
    return _save_resolution(registry, job_id, review_id, item.get("proposed_decision", "keep_as_is"))


@app.post("/jobs/{job_id}/review/{review_id}/keep")
def keep_review_item(job_id: str, review_id: str) -> dict:
    return _save_resolution(_registry(job_id), job_id, review_id, "keep_as_is")


@app.post("/jobs/{job_id}/review/resolve")
def resolve_review(job_id: str, payload: ReviewResolutionPayload) -> dict:
    registry = _registry(job_id)
    for r in payload.resolutions:
        _save_resolution(registry, job_id, r.review_id, r.final_decision, r.approved_by, merge=True)
    return {"ok": True}


@app.get("/jobs/{job_id}/video/{filename}")
def get_video(job_id: str, filename: str):
    return get_artifact(job_id, filename)


def _registry(job_id: str) -> ArtifactRegistry:
    settings = get_settings()
    job_dir = settings.output_dir / job_id
    if not job_dir.exists():
        raise HTTPException(404, f"Job {job_id} не найден")
    return ArtifactRegistry(job_dir)


def _state_from_data(job_id: str, registry: ArtifactRegistry, data: dict) -> PipelineState:
    return PipelineState(
        job_id=job_id,
        output_dir=str(registry.job_dir),
        status=ArtifactStatus(data.get("status", "pending")),
        stages_completed=data.get("stages_completed", []),
        current_stage=data.get("current_stage"),
    )


UI_STAGE_TO_PIPELINE: dict[str, str] = {
    "upload": "upload",
    "subtitle_capture": "subtitle_capture",
    "voiceover": "voiceover",
    "export": "assembly",
    "stt": "transcription",
    "cleanup": "speech_cleanup",
    "subtitle_blocks": "subtitle_blocks",
    "voiceover_script": "voiceover_script",
    "final_voiceover": "final_voiceover",
    "timing": "timing_policy",
    "edit": "video_edit",
    "tts": "tts",
    "subtitles": "subtitles",
    "sync": "voice_video_sync",
    "assembly": "assembly",
    "annotations": "annotations",
    "qa": "qa",
}

# Устаревшие значения current_stage в старых job
_LEGACY_STAGE_ALIASES: dict[str, str] = {
    "stt": "transcription",
    "input": "input_ingestion",
}


def _next_pipeline_stage(registry: ArtifactRegistry, job_id: str) -> PipelineStage | None:
    if not registry.exists("transcript.json"):
        return PipelineStage.TRANSCRIPTION
    if not cleanup_artifacts_ready(registry):
        return PipelineStage.SPEECH_CLEANUP
    if not cleanup_review_approved(registry, job_id):
        return None
    if not registry.exists("voiceover.wav"):
        return PipelineStage.TTS
    if not registry.exists("edited_video.mp4"):
        return PipelineStage.VIDEO_EDIT
    if not registry.exists("subtitles.srt") or not registry.exists("subtitle_timing.json"):
        return PipelineStage.SUBTITLES
    if not annotation_review_approved(registry, job_id):
        if not registry.exists("annotation_suggestions.json"):
            return PipelineStage.ANNOTATIONS
        return None
    if not registry.exists("final_lesson.mp4"):
        return PipelineStage.ASSEMBLY
    return None


def _job_progress(registry: ArtifactRegistry, state_data: dict) -> dict:
    stages_done = len(state_data.get("stages_completed", []))
    has_transcript = registry.exists("transcript.json")
    has_cleanup = cleanup_artifacts_ready(registry)
    job_id = registry.job_dir.name
    has_cleanup_approved = cleanup_review_approved(registry, job_id) if has_cleanup else False
    has_voiceover = _voiceover_matches_current_cleanup(registry)
    has_edited_video = registry.exists("edited_video.mp4")
    has_annotations = annotation_review_approved(registry, job_id)
    has_subtitles = registry.exists("subtitles.srt") and registry.exists("subtitle_timing.json")
    has_assembly = registry.exists("final_lesson.mp4") and registry.exists("assembly_report.json")
    if has_transcript:
        stages_done = max(stages_done, 2)
    if has_cleanup_approved:
        stages_done = max(stages_done, 3)
    if has_voiceover:
        stages_done = max(stages_done, 4)
    if has_edited_video:
        stages_done = max(stages_done, 5)
    if has_subtitles:
        stages_done = max(stages_done, 6)
    if has_annotations:
        stages_done = max(stages_done, 7)
    if has_assembly:
        stages_done = max(stages_done, 8)
    return {
        "stages_done": stages_done,
        "has_transcript": has_transcript,
        "has_cleanup": has_cleanup,
        "has_cleanup_approved": has_cleanup_approved,
        "has_timing": False,
        "has_timing_completed": False,
        "has_edited_video": has_edited_video,
        "has_voiceover": has_voiceover,
        "has_subtitles": has_subtitles,
        "has_sync": False,
        "has_assembly": has_assembly,
        "has_annotations": has_annotations,
        "pipeline_status": state_data.get("status", "pending"),
    }


def _reconcile_stale_running(registry: ArtifactRegistry, state_data: dict) -> dict:
    """Сброс зависшего status=running, если артефакт этапа уже готов."""
    if job_execution.is_active(registry.job_dir.name):
        return state_data
    if state_data.get("status") != "running":
        return state_data

    job_id = str(state_data.get("job_id") or registry.job_dir.name)
    current = state_data.get("current_stage")
    if not current:
        state_data = {**state_data, "status": "completed", "current_stage": None, "error": None}
        registry.save_json("pipeline_state.json", state_data)
        return state_data

    from src.services.stage_reset_service import _stage_is_done

    cs = _LEGACY_STAGE_ALIASES.get(str(current), str(current))
    ui_stage = _pipeline_to_ui(cs)
    if ui_stage and _stage_is_done(registry, ui_stage, job_id):
        state_data = {**state_data, "status": "completed", "current_stage": None, "error": None}
        registry.save_json("pipeline_state.json", state_data)
        return state_data

    # Шаг 7: suggestions уже есть, а процесс умер (перезапуск API / зависание превью)
    if cs in ("annotations",) and registry.exists("annotation_suggestions.json"):
        import shutil

        from src.services.annotation_review_service import create_pending_annotation_review

        if not registry.exists("annotation_review.json"):
            create_pending_annotation_review(registry, job_id)
        if not registry.exists("annotation_preview.mp4") and registry.exists("edited_video.mp4"):
            shutil.copy2(
                registry.artifact_path("edited_video.mp4"),
                registry.artifact_path("annotation_preview.mp4"),
            )
        state_data = {**state_data, "status": "completed", "current_stage": None, "error": None}
        registry.save_json("pipeline_state.json", state_data)
        return state_data

    if cs in ("transcription", "stt") and not registry.exists("transcript.json"):
        if not registry.exists("raw_audio.ogg"):
            state_data = {
                **state_data,
                "status": "completed",
                "current_stage": None,
                "error": state_data.get("error"),
            }
            registry.save_json("pipeline_state.json", state_data)
    return state_data


def _stage_is_running(ui_stage_id: str, state: PipelineState) -> bool:
    if state.status != ArtifactStatus.RUNNING:
        return False
    cs = state.current_stage
    if not cs:
        return False
    cs_norm = _LEGACY_STAGE_ALIASES.get(cs, cs)
    if ui_stage_id == "annotations" and cs_norm == "assembly":
        return True
    expected = UI_STAGE_TO_PIPELINE.get(ui_stage_id, ui_stage_id)
    return cs_norm == expected or cs == ui_stage_id


def _subtitles_ready(registry: ArtifactRegistry) -> bool:
    return registry.exists("subtitles.srt") and registry.exists("subtitle_timing.json")


def _stage_completed(registry: ArtifactRegistry, stage, job_id: str) -> bool:
    # --- v3: пять этапов пользователя ---
    if stage.id == "upload":
        from src.services.timeblock_service import time_blocks_ready

        return registry.exists("video_meta.json") and time_blocks_ready(registry)
    if stage.id == "subtitle_capture":
        from src.services.timeblock_service import subtitles_saved

        return subtitles_saved(registry)
    if stage.id == "voiceover":
        from src.services.auto_voiceover_service import (
            auto_voiceover_matches_subtitles,
            auto_voiceover_ready,
        )

        return auto_voiceover_ready(registry) and auto_voiceover_matches_subtitles(registry)
    if stage.id == "annotations":
        from src.services.auto_voiceover_service import downstream_is_stale

        if downstream_is_stale(registry):
            return False
        # Готово только когда подтверждены аннотации и собран файл для скачивания
        return (
            annotation_review_approved(registry, job_id)
            and registry.exists("final_lesson.mp4")
            and registry.exists("assembly_report.json")
        )
    if stage.id == "export":
        from src.services.auto_voiceover_service import downstream_is_stale

        if downstream_is_stale(registry):
            return False
        return registry.exists("final_lesson.mp4") and registry.exists("assembly_report.json")

    if stage.id == "cleanup":
        return cleanup_artifacts_ready(registry) and cleanup_review_approved(registry, job_id)
    if stage.id == "subtitle_blocks":
        from src.services.early_subtitle_blocks_service import early_subtitles_ready

        return early_subtitles_ready(registry)
    if stage.id == "voiceover_script":
        from src.services.voiceover_script_service import voiceover_script_fully_approved

        return voiceover_script_fully_approved(registry)
    if stage.id == "final_voiceover":
        if not (
            registry.exists("voiceover.wav")
            and registry.exists("voiceover_segments.json")
            and registry.exists("edited_video.mp4")
        ):
            return False
        from src.services.final_voiceover_from_subtitles import final_voiceover_matches_script

        segs = registry.load_json("voiceover_segments.json")
        by_new_path = (
            segs.get("source") == "voiceover_script" or segs.get("text_source") == "voiceover_script"
        )
        # Правки в шаге 5 → шаг 6 снова требует запуска
        return by_new_path and final_voiceover_matches_script(registry)
    if stage.id == "tts":
        return _voiceover_matches_current_cleanup(registry)
    if stage.id == "subtitles":
        return _subtitles_ready(registry)
    return all(registry.exists(key) for key in stage.artifact_keys)


def _voiceover_matches_current_cleanup(registry: ArtifactRegistry) -> bool:
    if not (
        registry.exists("clean_transcript.json")
        and registry.exists("voiceover.wav")
        and registry.exists("voiceover_segments.json")
    ):
        return False
    voiceover = registry.load_json("voiceover_segments.json")
    # Подшаг 6.1: финальная озвучка по субтитрам — шаг TTS считается выполненным
    if voiceover.get("source") == "subtitles_final" and _subtitles_ready(registry):
        return True
    current_hash = current_tts_text_hash(registry)
    return voiceover.get("cleanup_text_hash") == current_hash


def _build_stages(registry: ArtifactRegistry, state: PipelineState) -> list[dict[str, Any]]:
    stages = []
    found_current = False
    for ui_stage in UI_STAGES:
        cleanup_needs_review = (
            ui_stage.id == "cleanup"
            and cleanup_artifacts_ready(registry)
            and not cleanup_review_approved(registry, state.job_id)
        )
        # v3: студия открывается, когда есть предложения и озвучка актуальна
        annotations_needs_review = False
        if ui_stage.id == "annotations" and registry.exists("annotation_suggestions.json"):
            from src.services.auto_voiceover_service import downstream_is_stale

            annotations_needs_review = (
                not downstream_is_stale(registry)
                and not annotation_review_approved(registry, state.job_id)
            )
        voiceover_script_needs_review = False
        if ui_stage.id == "voiceover_script" and registry.exists("voiceover_script.json"):
            from src.services.voiceover_script_service import voiceover_script_fully_approved

            voiceover_script_needs_review = not voiceover_script_fully_approved(registry)

        done = _stage_completed(registry, ui_stage, state.job_id)
        script_needs_review = (ui_stage.id == "subtitle_capture" and not done
                               and registry.exists("script_review_report.json"))

        if _stage_is_running(ui_stage.id, state):
            status = "running"
            found_current = True
        elif done:
            status = "completed"
        elif cleanup_needs_review or annotations_needs_review or voiceover_script_needs_review or script_needs_review:
            status = "needs_review"
            found_current = True
        elif not found_current:
            status = "current"
            found_current = True
        else:
            status = "pending"

        preview: dict[str, Any] | None = None
        show_preview = (
            (done or cleanup_needs_review or annotations_needs_review or voiceover_script_needs_review)
            and ui_stage.preview_key
        )
        preview_key = ui_stage.preview_key
        # Озвучка (v3): показываем видео с субтитрами на кадре
        if ui_stage.id == "voiceover":
            if registry.exists("edited_video_with_subtitles.mp4"):
                preview_key = "edited_video_with_subtitles.mp4"
            elif registry.exists("edited_video.mp4"):
                preview_key = "edited_video.mp4"
        if ui_stage.id == "final_voiceover":
            if registry.exists("edited_video_with_subtitles.mp4"):
                preview_key = "edited_video_with_subtitles.mp4"
            elif registry.exists("edited_video.mp4"):
                preview_key = "edited_video.mp4"
        # Аннотации: после подтверждения — финальный файл; иначе превью со субтитрами
        if ui_stage.id == "annotations":
            if registry.exists("final_lesson.mp4"):
                preview_key = "final_lesson.mp4"
            elif registry.exists("annotation_preview.mp4"):
                preview_key = "annotation_preview.mp4"
            elif registry.exists("edited_video_with_subtitles.mp4"):
                preview_key = "edited_video_with_subtitles.mp4"
            elif registry.exists("edited_video.mp4"):
                preview_key = "edited_video.mp4"
        if show_preview and preview_key and registry.exists(preview_key):
            preview = {
                "type": ui_stage.preview_type,
                "url": f"/jobs/{state.job_id}/artifacts/{preview_key}",
                "filename": preview_key,
            }
            if preview_key == 'final_lesson.mp4' and registry.exists('brand_intro.png'):
                poster_version = registry.artifact_path('brand_intro.png').stat().st_mtime_ns
                preview['poster_url'] = f'/jobs/{state.job_id}/artifacts/brand_intro.png?v={poster_version}'
            # Метка версии файла: без неё браузер отдаёт старое видео из кеша
            try:
                preview["version"] = str(
                    int(registry.artifact_path(preview_key).stat().st_mtime)
                )
            except Exception:
                preview["version"] = None
            if ui_stage.preview_type == "stub":
                try:
                    data = registry.load_json(preview_key)
                    preview["summary"] = str(data.get("message") or "Заглушка этапа")
                    preview["text_preview"] = str(data.get("note") or "")
                except Exception:
                    preview["summary"] = "Заглушка этапа выполнена."
            elif ui_stage.preview_type == "json":
                try:
                    data = registry.load_json(preview_key)
                    preview["summary"] = _summarize_json(
                        preview_key, data, registry
                    )
                    if preview_key in ("transcript.json", "clean_transcript.json"):
                        preview["segments"] = [
                            {
                                "start": s.get("start"),
                                "end": s.get("end"),
                                "text": s.get("text", ""),
                            }
                            for s in data.get("segments", [])[:8]
                        ]
                except Exception:
                    preview["summary"] = None
            elif ui_stage.preview_type == "text":
                try:
                    content = registry.artifact_path(preview_key).read_text(encoding="utf-8")
                    cue_count = content.count("-->")
                    text_lines = [
                        line.strip()
                        for line in content.splitlines()
                        if line.strip() and not line.strip().isdigit() and "-->" not in line
                    ]
                    preview["summary"] = (
                        f"Субтитров: {cue_count}. "
                        f"Начало: «{(text_lines[0][:100] + '…') if text_lines else '—'}»"
                    )
                    preview["text_preview"] = "\n".join(text_lines[:6])
                except Exception:
                    preview["summary"] = "Файл субтитров готов."

        stages.append(
            {
                "id": ui_stage.id,
                "order": ui_stage.order,
                "title": ui_stage.title,
                "description": _stage_description(registry, ui_stage.id, ui_stage.description),
                "status": status,
                "preview": preview,
                "is_stub": bool(getattr(ui_stage, "is_stub", False)),
                "actions": stage_ui_actions(registry, ui_stage.id, state.job_id, status),
                "notice": _stage_notice(registry, ui_stage.id),
            }
        )
    return stages


def _stage_description(registry: ArtifactRegistry, stage_id: str, default: str) -> str:
    if stage_id == "annotations" and registry.exists("render_pending.json"):
        return "Обновление оформления готового видео. Сохранённые текст, озвучка и аннотации используются повторно."
    if stage_id == "voiceover" and registry.exists("automatic_sync_report.json"):
        report = registry.load_json("automatic_sync_report.json")
        if report.get("status") != "completed":
            return default
        return (default + " Контроль синхронизации выполнен: "
                f"аудио {report['audio_duration_seconds']:.2f} с, "
                f"видео {report['video_duration_seconds']:.2f} с; "
                f"разница {abs(report['duration_delta_seconds']):.3f} с. "
                "Начало каждой фразы привязано к исходной записи; наложений речи нет.")
    return default


def _stage_notice(registry: ArtifactRegistry, ui_stage_id: str) -> str | None:
    """Сообщение пользователю там, где автоматика не справилась сама."""
    if ui_stage_id == "voiceover" and registry.exists("pipeline_state.json"):
        state = registry.load_json("pipeline_state.json")
        if state.get("status") == "running":
            return None
        if state.get("status") == "failed" and state.get("error"):
            message = str(state["error"])
            if "озвуч" in message.lower() or "тайминг" in message.lower():
                return message
    report_file = {"subtitle_capture": "script_review_report.json",
                   "annotations": "screen_analysis_report.json"}.get(ui_stage_id)
    if report_file and registry.exists(report_file):
        report = registry.load_json(report_file)
        count = report.get("review_count", 0)
        return (f"Проверьте спорные фрагменты: {count}. " if count else "") + " ".join(report.get("warnings", [])[:2]) or None
    if ui_stage_id == "voiceover" and registry.exists("voiceover_timing_report.json"):
        timing_report = registry.load_json("voiceover_timing_report.json")
        warnings = timing_report.get("warnings", []) if timing_report.get("status") == "needs_review" else []
        if warnings:
            return " ".join(warnings[:3])
    if ui_stage_id != "voiceover" or not registry.exists("voiceover_segments.json"):
        return None
    try:
        doc = registry.load_json("voiceover_segments.json")
    except Exception:
        return None
    warnings = [str(w) for w in (doc.get("warnings") or []) if str(w).strip()]
    if not warnings:
        return None
    return " ".join(warnings[:3])


def _summarize_json(filename: str, data: dict, registry: ArtifactRegistry | None = None) -> str:
    if filename == "transcript.json":
        segs = data.get("segments", [])
        provider = data.get("provider", "")
        preview = " ".join(s["text"] for s in segs[:2])[:120]
        return (
            f"Сегментов: {len(segs)}. Провайдер: {provider}. "
            f"Начало: «{preview}…»"
        )
    if filename == "clean_transcript.json":
        segs = data.get("segments", [])
        manual = 0
        if registry and registry.exists(REVIEW_FILENAME):
            manual = int(registry.load_json(REVIEW_FILENAME).get("manual_edits_count", 0))
        preview = " ".join(s["text"] for s in segs[:2])[:120]
        return (
            f"Сегментов: {len(segs)}. Сохранённых правок: {manual}. "
            f"Текст для озвучки: «{preview}…»"
        )
    if filename == "timing_decisions.json":
        decs = data.get("decisions", [])
        review = sum(1 for d in decs if d.get("requires_review"))
        return f"Решений: {len(decs)}. На согласование: {review}."
    if filename == "timeline_map.json":
        src = data.get("source_duration_seconds", 0)
        tgt = data.get("target_duration_seconds", 0)
        saved = max(0.0, float(src) - float(tgt))
        return (
            f"Сегментов карты: {len(data.get('segments', []))}. "
            f"Исходная длительность: {src:.1f} с → после монтажа: {tgt:.1f} с "
            f"(экономия ~{saved:.1f} с)."
        )
    if filename == "voiceover_segments.json":
        segs = data.get("segments", [])
        provider = data.get("provider", "")
        duration = data.get("total_duration_seconds", 0)
        return f"Фрагментов озвучки: {len(segs)}. Длительность: {duration:.1f} с. Провайдер: {provider}."
    if filename == "subtitle_timing.json":
        cues = data.get("cues", [])
        duration = data.get("total_duration_seconds", 0)
        return f"Субтитров: {len(cues)}. Длительность: {duration:.1f} с."
    if filename == "annotation_suggestions.json":
        items = data.get("suggestions", [])
        pending = data.get("pending_review_count", 0)
        types = ", ".join(sorted({str(i.get("type", "")) for i in items[:6] if i.get("type")}))
        return f"Предложений: {len(items)}. На проверку: {pending}. Типы: {types or '—'}."
    if filename == "approved_annotations.json":
        items = data.get("annotations", [])
        return f"Одобрено аннотаций: {len(items)}."
    if filename == "qa_report.json":
        return f"Статус QA: {data.get('status', 'unknown')}."
    return "Артефакт готов."


def _review_items_from_timing(registry: ArtifactRegistry) -> list[dict]:
    if not registry.exists("timing_decisions.json"):
        return []
    timing = registry.load_json("timing_decisions.json")
    items = []
    for idx, dec in enumerate(timing.get("decisions", [])):
        if not dec.get("requires_review"):
            continue
        items.append(
            {
                "review_id": f"rev_{idx + 1:03d}",
                "candidate_id": dec.get("candidate_id", f"cand_{idx + 1:03d}"),
                "video_excerpt_start": dec.get("target_start", 0),
                "video_excerpt_end": dec.get("target_end", 0),
                "proposed_decision": dec.get("decision", "needs_human_review"),
                "alternative_decisions": ["keep_as_is", "trim_soft", "speedup_video"],
                "confidence": dec.get("confidence", 0),
                "reason_for_review": dec.get("why", "Спорный интервал — требуется ваше решение"),
                "context_transcript": "",
                "evidence": dec.get("evidence", {}),
            }
        )
    return items


def _load_review_items(registry: ArtifactRegistry) -> list[dict]:
    if registry.exists("review_bundle.json"):
        return registry.load_json("review_bundle.json").get("items", [])
    return _review_items_from_timing(registry)


def _save_resolution(
    registry: ArtifactRegistry,
    job_id: str,
    review_id: str,
    decision: str,
    approved_by: str = "user",
    merge: bool = False,
) -> dict:
    existing: list[dict] = []
    if merge and registry.exists("review_resolution.json"):
        existing = registry.load_json("review_resolution.json").get("resolutions", [])
    else:
        if registry.exists("review_resolution.json"):
            existing = [
                r
                for r in registry.load_json("review_resolution.json").get("resolutions", [])
                if r.get("review_id") != review_id
            ]

    existing.append(
        {
            "review_id": review_id,
            "final_decision": decision,
            "approved_by": approved_by,
        }
    )

    data = {
        "job_id": job_id,
        "stage": "timing_review_resolution",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["review_bundle.json"],
        "status": ArtifactStatus.COMPLETED.value,
        "resolutions": existing,
    }
    registry.save_json("review_resolution.json", data)
    refresh_timeline_after_review(registry, job_id)
    bundle = get_review_bundle(job_id)
    return {"ok": True, "review_id": review_id, "decision": decision, "pending": bundle["pending"]}


def _format_time_range(start: float | None, end: float | None) -> str:
    if start is None or end is None:
        return "—"

    def fmt(sec: float) -> str:
        m = int(sec // 60)
        s = int(sec % 60)
        return f"{m}:{s:02d}"

    return f"{fmt(start)} – {fmt(end)}"


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REVIEW_UI_DIST = _PROJECT_ROOT / "review-ui" / "dist"


@app.get("/")
def serve_review_ui_root() -> FileResponse:
    """Главная страница — веб-интерфейс (не путать с API /jobs, /pipeline)."""
    index = _REVIEW_UI_DIST / "index.html"
    if not index.exists():
        raise HTTPException(
            503,
            "Интерфейс не собран. В папке review-ui выполните: npm install && npm run build",
        )
    return FileResponse(index)


if (_REVIEW_UI_DIST / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=_REVIEW_UI_DIST / "assets"),
        name="review-ui-assets",
    )
