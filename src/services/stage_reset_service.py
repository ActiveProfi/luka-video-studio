"""Сброс и перезапуск отдельных этапов pipeline."""

from __future__ import annotations

import shutil
from typing import Any

from src.domain.enums import PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.cleanup_review_service import (
    REVIEW_FILENAME,
    cleanup_artifacts_ready,
    get_cleanup_edit_payload,
    load_cleanup_review,
)

# Пять этапов, которые видит пользователь (архитектура v3)
UI_STAGE_ORDER: tuple[str, ...] = (
    "upload",
    "subtitle_capture",
    "voiceover",
    "annotations",
    "export",
)

# Порядок для очистки «с этого этапа дальше» (внутренние и legacy этапы в цепочке)
UI_STAGE_ORDER_FOR_CLEAR: tuple[str, ...] = (
    "upload",
    "stt",
    "cleanup",
    "subtitle_capture",
    "subtitle_blocks",
    "voiceover_script",
    "tts",
    "edit",
    "subtitles",
    "final_voiceover",
    "voiceover",
    "annotations",
    "assembly",
    "export",
)

# Внутренние и старые этапы — код и артефакты сохранены, в основном UI-порядке не участвуют
LEGACY_UI_STAGE_ORDER: tuple[str, ...] = (
    "stt",
    "cleanup",
    "subtitle_blocks",
    "voiceover_script",
    "final_voiceover",
    "tts",
    "edit",
    "subtitles",
    "assembly",
)

RERUNNABLE_UI_STAGES: frozenset[str] = frozenset(
    {
        "subtitle_capture",
        "voiceover",
        "annotations",
        "export",
        # внутренние и legacy — можно вызвать API напрямую
        "stt",
        "cleanup",
        "subtitle_blocks",
        "voiceover_script",
        "final_voiceover",
        "tts",
        "edit",
        "subtitles",
        "assembly",
    }
)
# Кнопку «Выполнить» показываем только там, где запуск действительно нужен:
# субтитры пишет пользователь в редакторе, а не кнопкой этапа.
RUN_UI_STAGES: frozenset[str] = frozenset({"voiceover", "annotations", "export"})
EXECUTABLE_UI_STAGES: frozenset[str] = (
    RUN_UI_STAGES
    | frozenset(LEGACY_UI_STAGE_ORDER)
    | frozenset({"upload", "subtitle_capture"})
)

STAGE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    # v3: время-блоки не удаляем автоматически — в них лежит текст пользователя
    "upload": ("video_meta.json",),
    "subtitle_capture": (
        "subtitles.srt",
        "subtitle_timing.json",
        "subtitle_layout.json",
        "clean_transcript.json",
    ),
    "voiceover": (
        "voiceover.wav",
        "voiceover_segments.json",
        "speech_script_auto.json",
        "edited_video.mp4",
        "edited_video_with_subtitles.mp4",
        "_subtitle_burn.ass",
        "voiceover_timing_report.json",
        "automatic_sync_report.json",
    ),
    "export": ("final_lesson.mp4", "assembly_report.json"),
    "stt": ("transcript.json", "raw_audio.ogg"),
    "cleanup": (
        "clean_transcript.json",
        "edits_map.json",
        REVIEW_FILENAME,
        "tts_preparation_report.json",
        "speech_script.json",
    ),
    "subtitle_blocks": ("subtitles.srt", "subtitle_timing.json", "subtitle_layout.json"),
    "voiceover_script": ("voiceover_script.json",),
    "final_voiceover": ("voiceover.wav", "voiceover_segments.json", "edited_video.mp4"),
    "tts": ("voiceover.wav", "voiceover_segments.json"),
    "edit": ("edited_video.mp4", "video_edit_report.json"),
    "annotations": (
        "annotation_suggestions.json",
        "annotation_review.json",
        "annotation_preview.mp4",
        "approved_annotations.json",
        "screen_analysis_report.json",
    ),
    "subtitles": (
        "subtitles.srt",
        "subtitle_timing.json",
        "subtitle_layout.json",
        "edited_video_with_subtitles.mp4",
        "_subtitle_burn.ass",
    ),
    "assembly": ("final_lesson.mp4", "assembly_report.json"),
}

# Устаревшие артефакты старого pipeline (вырезание пауз / sync)
LEGACY_ARTIFACTS: tuple[str, ...] = (
    "pause_candidates.json",
    "visual_activity_map.json",
    "semantic_action_map.json",
    "timing_decisions.json",
    "timeline_map.json",
    "review_bundle.json",
    "review_resolution.json",
    "sync_plan.json",
    "sync_review.json",
    "sync_preview.mp4",
    "approved_sync.json",
    "qa_report.json",
)

LEGACY_PIPELINE_STAGES: frozenset[str] = frozenset(
    {
        PipelineStage.TIMING_PAUSE_CANDIDATES.value,
        PipelineStage.TIMING_VISUAL_ACTIVITY.value,
        PipelineStage.TIMING_SEMANTIC_ACTION.value,
        PipelineStage.TIMING_POLICY.value,
        PipelineStage.TIMELINE_MAP.value,
        PipelineStage.VOICE_VIDEO_SYNC.value,
        PipelineStage.QA.value,
    }
)

STAGE_DIRS: dict[str, tuple[str, ...]] = {
    "stt": ("_stt_chunks",),
    "tts": ("_tts_chunks", "_tts_build"),
    "voiceover": ("_tts_auto", "_tts_build"),
}

UI_TO_PIPELINE_STAGES: dict[str, tuple[str, ...]] = {
    "upload": (),
    "subtitle_capture": (PipelineStage.SUBTITLES.value,),
    "voiceover": (PipelineStage.TTS.value,),
    "export": (PipelineStage.ASSEMBLY.value,),
    "stt": (PipelineStage.TRANSCRIPTION.value,),
    "cleanup": (PipelineStage.SPEECH_CLEANUP.value,),
    "subtitle_blocks": (),
    "voiceover_script": (),
    "final_voiceover": (),
    "tts": (PipelineStage.TTS.value,),
    "edit": (PipelineStage.VIDEO_EDIT.value,),
    "annotations": (PipelineStage.ANNOTATIONS.value,),
    "subtitles": (PipelineStage.SUBTITLES.value,),
    "assembly": (PipelineStage.ASSEMBLY.value,),
}

EXECUTE_LABEL = "Выполнить"
RERUN_LABEL = "Выполнить заново"

# Понятные подписи кнопок для пяти этапов v3
EXECUTE_LABELS: dict[str, str] = {
    "voiceover": "Озвучить",
    "annotations": "Подобрать аннотации",
    "export": "Собрать готовый ролик",
}
RERUN_LABELS: dict[str, str] = {
    "voiceover": "Озвучить заново",
    "annotations": "Подобрать заново",
    "export": "Собрать заново",
}


def _stage_index(ui_stage_id: str) -> int:
    try:
        return UI_STAGE_ORDER_FOR_CLEAR.index(ui_stage_id)
    except ValueError as exc:
        raise ValueError(f"Неизвестный этап: {ui_stage_id}") from exc


def _collect_artifacts_from(ui_stage_id: str, include_self: bool) -> tuple[list[str], list[str]]:
    start_idx = _stage_index(ui_stage_id) if include_self else _stage_index(ui_stage_id) + 1
    files: list[str] = []
    dirs: list[str] = []
    for stage_id in UI_STAGE_ORDER_FOR_CLEAR[start_idx:]:
        files.extend(STAGE_ARTIFACTS.get(stage_id, ()))
        dirs.extend(STAGE_DIRS.get(stage_id, ()))
    if ui_stage_id in {"cleanup", "tts"} and include_self:
        files.extend(LEGACY_ARTIFACTS)
    return files, dirs


def _delete_path(registry: ArtifactRegistry, relative: str) -> None:
    path = registry.job_dir / relative
    if path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def clear_from_ui_stage(
    registry: ArtifactRegistry,
    from_ui_stage_id: str,
    *,
    include_self: bool = True,
) -> list[str]:
    files, dirs = _collect_artifacts_from(from_ui_stage_id, include_self)
    removed: list[str] = []
    for name in files:
        if registry.exists(name):
            _delete_path(registry, name)
            removed.append(name)
    for name in dirs:
        path = registry.job_dir / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            removed.append(f"{name}/")
    return removed


def _pipeline_stages_from(ui_stage_id: str, include_self: bool) -> set[str]:
    start_idx = _stage_index(ui_stage_id) if include_self else _stage_index(ui_stage_id) + 1
    result: set[str] = set()
    for stage_id in UI_STAGE_ORDER_FOR_CLEAR[start_idx:]:
        result.update(UI_TO_PIPELINE_STAGES.get(stage_id, ()))
    if ui_stage_id in {"cleanup", "tts"} and include_self:
        result.update(LEGACY_PIPELINE_STAGES)
    return result


def update_pipeline_state_after_clear(
    registry: ArtifactRegistry,
    from_ui_stage_id: str,
    *,
    include_self: bool = True,
) -> dict[str, Any]:
    to_remove = _pipeline_stages_from(from_ui_stage_id, include_self)
    state_data = (
        registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    )
    completed = [s for s in state_data.get("stages_completed", []) if s not in to_remove]
    state_data = {
        **state_data,
        "status": "completed",
        "current_stage": None,
        "stages_completed": completed,
        "error": None,
    }
    state_data.pop("traceback", None)
    registry.save_json("pipeline_state.json", state_data)
    return state_data


def validate_stage_rerun(registry: ArtifactRegistry, job_id: str, ui_stage_id: str) -> None:
    validate_stage_execute(registry, job_id, ui_stage_id)


def validate_stage_execute(registry: ArtifactRegistry, job_id: str, ui_stage_id: str) -> None:
    if ui_stage_id not in EXECUTABLE_UI_STAGES:
        raise ValueError(f"Этап «{ui_stage_id}» пока нельзя запустить через API")

    # --- v3 ---
    if ui_stage_id == "upload":
        if not registry.exists("raw_video.mp4") and not registry.exists("input_manifest.json"):
            raise ValueError("Сначала загрузите видео")
        return

    if ui_stage_id == "subtitle_capture":
        if not registry.exists("raw_video.mp4") and not registry.exists("input_manifest.json"):
            raise ValueError("Сначала загрузите видео")
        return

    if ui_stage_id == "voiceover":
        from src.services.timeblock_service import subtitles_saved

        if not subtitles_saved(registry):
            raise ValueError("Сначала напишите субтитры и нажмите «Сохранить»")
        return

    if ui_stage_id == "export":
        if not registry.exists("approved_annotations.json"):
            raise ValueError("Сначала подтвердите аннотации")
        return

    if ui_stage_id == "stt":
        if not registry.exists("raw_video.mp4") and not registry.exists("input_manifest.json"):
            raise ValueError("Исходное видео не найдено")
        return

    if ui_stage_id == "cleanup":
        if not registry.exists("transcript.json"):
            raise ValueError("Сначала выполните распознавание речи (шаг 2)")
        return

    if ui_stage_id == "tts":
        from src.services.cleanup_review_service import cleanup_review_approved

        if not cleanup_review_approved(registry, job_id):
            raise ValueError("Сначала подтвердите текст на шаге 3")
        return

    if ui_stage_id == "edit":
        if not registry.exists("voiceover.wav"):
            raise ValueError("Сначала выполните AI-озвучку (legacy)")
        return

    if ui_stage_id == "subtitles":
        if not registry.exists("edited_video.mp4"):
            raise ValueError("Сначала выполните монтаж видео (legacy)")
        return

    if ui_stage_id == "subtitle_blocks":
        from src.services.cleanup_review_service import cleanup_review_approved

        if not cleanup_review_approved(registry, job_id):
            raise ValueError("Сначала завершите шаг 3 (тайминг / сценарий)")
        return

    if ui_stage_id == "voiceover_script":
        if not registry.exists("subtitle_timing.json"):
            raise ValueError("Сначала выполните шаг 4 (разбивка на блоки / субтитры)")
        return

    if ui_stage_id == "final_voiceover":
        from src.services.voiceover_script_service import voiceover_script_voiceover_approved

        if not registry.exists("subtitle_timing.json"):
            raise ValueError("Сначала выполните шаг 4 (субтитры/блоки)")
        if not registry.exists("voiceover_script.json"):
            raise ValueError("Сначала выполните шаг 5 (текст для озвучки)")
        if not voiceover_script_voiceover_approved(registry):
            raise ValueError("Сначала утвердите текст озвучки на шаге 5")
        return

    if ui_stage_id == "annotations":
        if not (
            registry.exists("edited_video.mp4")
            or registry.exists("voiceover.wav")
            or registry.exists("final_voiceover_stub.json")
        ):
            raise ValueError("Сначала дождитесь озвучки")
        return

    if ui_stage_id == "assembly":
        if not registry.exists("approved_annotations.json"):
            raise ValueError("Сначала подтвердите аннотации (шаг 7)")
        return


def _stage_is_done(registry: ArtifactRegistry, ui_stage_id: str, job_id: str) -> bool:
    from src.services.annotation_review_service import annotation_review_approved
    from src.services.cleanup_review_service import cleanup_review_approved

    # --- v3 ---
    if ui_stage_id == "upload":
        from src.services.timeblock_service import time_blocks_ready

        return registry.exists("video_meta.json") and time_blocks_ready(registry)
    if ui_stage_id == "subtitle_capture":
        from src.services.timeblock_service import subtitles_saved

        return subtitles_saved(registry)
    if ui_stage_id == "voiceover":
        from src.services.auto_voiceover_service import (
            auto_voiceover_matches_subtitles,
            auto_voiceover_ready,
        )

        return auto_voiceover_ready(registry) and auto_voiceover_matches_subtitles(registry)
    if ui_stage_id == "export":
        from src.services.auto_voiceover_service import downstream_is_stale

        if downstream_is_stale(registry) or registry.exists("render_pending.json"):
            return False
        return registry.exists("final_lesson.mp4") and registry.exists("assembly_report.json")

    if ui_stage_id == "stt":
        return registry.exists("transcript.json")
    if ui_stage_id == "cleanup":
        return cleanup_artifacts_ready(registry) and cleanup_review_approved(registry, job_id)
    if ui_stage_id == "tts":
        from src.agents.tts_generation_agent import (
            VOICEOVER_SEGMENTS,
            VOICEOVER_WAV,
            current_tts_text_hash,
        )

        if not (
            registry.exists("clean_transcript.json")
            and registry.exists(VOICEOVER_WAV)
            and registry.exists(VOICEOVER_SEGMENTS)
        ):
            return False
        voiceover = registry.load_json(VOICEOVER_SEGMENTS)
        current_hash = current_tts_text_hash(registry)
        return voiceover.get("cleanup_text_hash") == current_hash
    if ui_stage_id == "edit":
        return registry.exists("edited_video.mp4")
    if ui_stage_id == "annotations":
        from src.services.auto_voiceover_service import downstream_is_stale

        if downstream_is_stale(registry):
            return False
        return annotation_review_approved(registry, job_id)
    if ui_stage_id == "subtitles":
        return registry.exists("subtitles.srt") and registry.exists("subtitle_timing.json")
    if ui_stage_id == "subtitle_blocks":
        from src.services.early_subtitle_blocks_service import early_subtitles_ready

        return early_subtitles_ready(registry)
    if ui_stage_id == "voiceover_script":
        from src.services.voiceover_script_service import voiceover_script_fully_approved

        return voiceover_script_fully_approved(registry)
    if ui_stage_id == "final_voiceover":
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
        return by_new_path and final_voiceover_matches_script(registry)
    if ui_stage_id == "assembly":
        return registry.exists("final_lesson.mp4") and registry.exists("assembly_report.json")
    return False


def _has_saved_manual_edits(registry: ArtifactRegistry) -> bool:
    if not registry.exists("clean_transcript.json"):
        return False
    if registry.exists(REVIEW_FILENAME):
        review = registry.load_json(REVIEW_FILENAME)
        if int(review.get("manual_edits_count", 0)) > 0:
            return True
        if review.get("last_saved_at"):
            return True
    clean = registry.load_json("clean_transcript.json")
    for seg in clean.get("segments", []):
        current = str(seg.get("text", "")).strip()
        original = str(seg.get("original_text", "") or "").strip()
        if current and original and current != original:
            return True
    return False


def reset_stage_for_rerun(registry: ArtifactRegistry, job_id: str, ui_stage_id: str) -> list[str]:
    validate_stage_rerun(registry, job_id, ui_stage_id)
    if ui_stage_id == "cleanup" and _has_saved_manual_edits(registry):
        removed = clear_from_ui_stage(registry, "tts", include_self=True)
        update_pipeline_state_after_clear(registry, "tts", include_self=True)
        review = load_cleanup_review(registry, job_id)
        review["status"] = "pending"
        review["approved_at"] = None
        review["approved_by"] = None
        registry.save_json(REVIEW_FILENAME, review, "cleanup_review.schema.json")
        return removed
    removed = clear_from_ui_stage(registry, ui_stage_id, include_self=True)
    update_pipeline_state_after_clear(registry, ui_stage_id, include_self=True)
    return removed


def reopen_cleanup_for_edit(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    if not cleanup_artifacts_ready(registry):
        raise FileNotFoundError("Сначала подготовьте текст к редактированию")

    removed = clear_from_ui_stage(registry, "tts", include_self=True)
    update_pipeline_state_after_clear(registry, "tts", include_self=True)

    review = load_cleanup_review(registry, job_id)
    review["status"] = "pending"
    review["approved_at"] = None
    review["approved_by"] = None
    registry.save_json(REVIEW_FILENAME, review, "cleanup_review.schema.json")

    payload = get_cleanup_edit_payload(registry, job_id)
    payload["removed_artifacts"] = removed
    return payload


def stage_ui_actions(
    registry: ArtifactRegistry,
    ui_stage_id: str,
    job_id: str,
    status: str,
) -> list[dict[str, str]]:
    from src.services.cleanup_review_service import cleanup_review_approved

    actions: list[dict[str, str]] = []

    if ui_stage_id == "cleanup" and cleanup_artifacts_ready(registry) and cleanup_review_approved(registry, job_id):
        actions.append({"id": "reopen_text", "label": "Редактировать текст"})

    if ui_stage_id == "upload":
        if status == "completed":
            # Перезагрузить исходник можно только новым файлом — ведём к форме загрузки
            actions.append({"id": "new_upload", "label": "Загрузить другое видео"})
        elif registry.exists("raw_video.mp4") or registry.exists("input_manifest.json"):
            actions.append(
                {"id": "run", "label": "Разбить на тайм-блоки", "mode": "execute"}
            )
        return actions

    if ui_stage_id not in RUN_UI_STAGES or status == "running":
        return actions

    execute_label = EXECUTE_LABELS.get(ui_stage_id, EXECUTE_LABEL)
    rerun_label = RERUN_LABELS.get(ui_stage_id, RERUN_LABEL)

    if status == "current":
        actions.append({"id": "run", "label": execute_label, "mode": "execute"})
    elif status == "needs_review" and _stage_has_output_artifacts(registry, ui_stage_id):
        actions.append({"id": "run", "label": rerun_label, "mode": "rerun"})
    elif status == "completed":
        actions.append({"id": "run", "label": rerun_label, "mode": "rerun"})

    return actions


def _stage_has_output_artifacts(registry: ArtifactRegistry, ui_stage_id: str) -> bool:
    """Есть ли уже результат этапа — можно перегенерировать («Выполнить заново»)."""
    keys = STAGE_ARTIFACTS.get(ui_stage_id, ())
    if not keys:
        return False
    return any(registry.exists(name) for name in keys)
