"""Annotation Suggestion Agent — этап 7: стрелки, рамки, zoom на смонтированном видео."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.providers.llm.runner import complete_with_fallback
from src.services.annotation_frame_service import attach_frames_to_suggestions
from src.services.annotation_render_service import PREVIEW_FILENAME, render_annotation_preview
from src.services.annotation_review_service import (
    annotation_review_approved,
    create_pending_annotation_review,
)
from src.services.annotation_service import (
    build_lesson_moments,
    parse_llm_suggestions,
    rule_based_suggestions,
    scene_changes_near_moments,
)
from src.services.media_paths import resolve_edited_video_path
from src.services.video_analysis_service import detect_scene_change_times

logger = logging.getLogger(__name__)

SUGGESTIONS_FILE = "annotation_suggestions.json"

SYSTEM_PROMPT = """Ты аналитик видеоинструкций по любым программам.
Найди в тексте инструкции действия пользователя в любой программе: нажатия кнопок, открытие документов, переходы в меню.
НЕ указывай координаты на экране — только текст действия, время и тип аннотации.
Ответ — ТОЛЬКО валидный JSON без markdown."""

USER_PROMPT_TEMPLATE = """Длительность смонтированного видео: {target_duration:.1f} с.

Фрагменты урока (target-тайминг, секунды edited_video):
{moments_json}

Смены кадра (секунды target):
{scene_json}

Найди важные действия пользователя в интерфейсе программы. Не добавляй действия ради количества.
Одно предложение может содержать несколько действий: создай отдельную аннотацию
на каждый конкретный объект, с коротким названием этого объекта в text.
Включай названные пункты меню, поля, кнопки и суммы на экране.
linked_segment_id копируй ТОЧНО из фрагментов; не придумывай seg_001.
Для каждого укажи suggested_type:
- arrow — нажатие кнопки, пункт меню
- frame — выделить область (поле, таблица, блок формы)
- zoom — увеличить фрагмент (сумма, лимит, важная цифра)

Верни JSON:
{{
  "suggestions": [
    {{
      "annotation_id": "ann_001",
      "linked_segment_id": "seg_001",
      "target_start": 12.0,
      "target_end": 16.0,
      "text": "Нажимаем кнопку Создать",
      "suggested_type": "arrow",
      "reason": "Создание документа"
    }}
  ]
}}

Запрещено: anchor, x, y, width, height, координаты."""


def run_annotation_suggestions(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
) -> dict[str, Any]:
    if (
        registry.exists(SUGGESTIONS_FILE)
        and registry.exists(PREVIEW_FILENAME)
        and annotation_review_approved(registry, job_id)
    ):
        logger.info("Аннотации уже проверены, пропуск")
        return registry.load_json(SUGGESTIONS_FILE)

    if registry.exists("approved_annotations.json"):
        registry.artifact_path("approved_annotations.json").unlink(missing_ok=True)

    for required in ("clean_transcript.json", "voiceover_segments.json", "edited_video.mp4"):
        if not registry.exists(required):
            raise FileNotFoundError(f"Нужен {required} — выполните монтаж видео (шаг 5)")

    clean = registry.load_json("clean_transcript.json")
    voiceover = registry.load_json("voiceover_segments.json")
    timeline_segments: list[dict] = []
    if registry.exists("timeline_map.json"):
        timeline_segments = registry.load_json("timeline_map.json").get("segments", [])
    moments = build_lesson_moments(
        clean.get("segments", []),
        voiceover.get("segments", []),
        timeline_segments,
    )
    if not moments:
        raise ValueError("Не удалось построить фрагменты урока для аннотаций")

    lesson_path = resolve_edited_video_path(registry)
    # Превью шага аннотаций — сразу с субтитрами, иначе пользователь снова видит «голое» видео
    try:
        from src.services.subtitle_burn_service import ensure_subtitled_studio_video

        subtitled_name = ensure_subtitled_studio_video(registry, settings, force=False)
        subtitled_path = registry.artifact_path(subtitled_name)
        if subtitled_path.exists():
            lesson_path = subtitled_path
    except Exception:
        logger.exception("Не удалось подготовить видео с субтитрами для превью аннотаций")
    scene_times = detect_scene_change_times(lesson_path, settings=settings)
    scene_anchors = scene_changes_near_moments(scene_times, moments)
    target_duration = float(voiceover.get("total_duration_seconds") or 0)
    if target_duration <= 0 and registry.exists("video_edit_report.json"):
        target_duration = float(
            registry.load_json("video_edit_report.json").get("output_duration_seconds", 0)
        )

    reference_note = _reference_style_note(registry)
    warnings: list[str] = []
    provider = settings.llm_provider
    suggestions: list[dict[str, Any]]

    try:
        raw, provider = asyncio.run(
            complete_with_fallback(
                settings.model_copy(
                    update={
                        "llm_provider": "openai",
                        "llm_fallback_order": "openai,yandex",
                        "openai_llm_model": settings.screen_analysis_model,
                    }
                ),
                SYSTEM_PROMPT,
                USER_PROMPT_TEMPLATE.format(
                    target_duration=target_duration,
                    moments_json=json.dumps(moments, ensure_ascii=False, indent=2),
                    scene_json=json.dumps(scene_anchors[:20], ensure_ascii=False, indent=2),
                )
                + reference_note,
            )
        )
        registry.save_json(
            "annotation_action_analysis.json",
            {"provider": provider, "response": raw, "moments": moments},
        )
        suggestions = parse_llm_suggestions(raw, moments)
    except Exception as exc:
        logger.warning("LLM аннотации недоступен (%s), rule-based fallback", exc)
        warnings.append(f"LLM недоступен: {exc}. Использованы правила по тексту урока.")
        suggestions = rule_based_suggestions(moments)

    if not suggestions:
        suggestions = rule_based_suggestions(moments)
        warnings.append("LLM не вернул аннотации — применены правила по тексту.")

    suggestions = attach_frames_to_suggestions(lesson_path, registry.job_dir, suggestions)
    from src.services.media_paths import resolve_raw_video_path
    from src.services.screen_annotation_service import locate_screen_annotations

    try:
        original_path = resolve_raw_video_path(registry)
    except FileNotFoundError:
        # Legacy jobs may contain only the processed video; do not invent coordinates.
        original_path = None
    if original_path is not None:
        suggestions = locate_screen_annotations(
            original_path, suggestions, registry, settings, scene_times
        )
    else:
        registry.save_json(
            "screen_analysis_report.json",
            {
                "review_count": len(suggestions),
                "automatic_count": 0,
                "warnings": ["Исходная запись отсутствует: автоматическое размещение недоступно."],
            },
        )
    screen_report = registry.load_json("screen_analysis_report.json")
    warnings.extend(screen_report.get("warnings", []))
    pending_count = sum(not s.get("placement_confirmed") and not s.get('skipped') for s in suggestions)
    if pending_count:
        warnings.append(
            f"Проверьте {pending_count} аннотаций: объект не определён достаточно уверенно."
        )

    suggestions_doc = {
        "job_id": job_id,
        "stage": PipelineStage.ANNOTATIONS.value,
        "version": "2.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [
            "clean_transcript.json",
            "voiceover_segments.json",
            "edited_video.mp4",
        ],
        "status": ArtifactStatus.NEEDS_REVIEW.value,
        "provider": provider,
        "target_duration_seconds": round(target_duration, 3),
        "confidence_summary": round(
            sum(s["confidence"] for s in suggestions) / max(1, len(suggestions)),
            3,
        ),
        "warnings": warnings,
        "errors": [],
        "reference_style": "Автоматические рамки и стрелки по речи, кадрам исходного видео и видимому курсору",
        "suggestions": suggestions,
        "pending_review_count": pending_count,
        "preview_video": PREVIEW_FILENAME,
    }
    registry.save_json(SUGGESTIONS_FILE, suggestions_doc, "annotation_suggestions.schema.json")

    # Сначала review — студия доступна даже если превью ещё строится
    create_pending_annotation_review(registry, job_id)

    preview_path = registry.job_dir / PREVIEW_FILENAME
    render_annotation_preview(
        lesson_path,
        [s for s in suggestions if s.get("placement_confirmed")],
        preview_path,
        settings=settings,
        refine_anchors=False,
    )

    logger.info(
        "Этап 8: предложений=%s, превью=%s — ожидает проверки пользователя",
        len(suggestions),
        PREVIEW_FILENAME,
    )
    return suggestions_doc


def _reference_style_note(registry: ArtifactRegistry) -> str:
    ref_path = ""
    if registry.exists("input_manifest.json"):
        ref_path = str(registry.load_json("input_manifest.json").get("reference_video_path") or "")
    if ref_path and Path(ref_path).exists():
        return (
            "\n\nСтиль как в reference_final.mp4 (готовый урок про НДС/УСН): "
            "подчёркивай меню 1С, отчёты, суммы доходов и момент превышения лимита."
        )
    return "\n\nСтиль: стрелки на элементы интерфейса и рамки на важных значениях. Учитывай программу и тему текущего урока."
