"""Сборка финального урока: видео + озвучка + субтитры + аннотации.

Важно: результат должен содержать всё, что пользователь уже сделал на прошлых шагах.
Нельзя отдавать «голую» копию edited_video без субтитров и рамок.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.annotation_render_service import render_annotation_preview
from src.services.subtitle_burn_service import burn_subtitles_into_video

logger = logging.getLogger(__name__)

FINAL_LESSON = "final_lesson.mp4"
ASSEMBLY_REPORT = "assembly_report.json"
TEMP_WITH_SUBS = "_assembly_with_subtitles.mp4"


def run_lesson_assembly(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
    *,
    force: bool = True,
) -> dict[str, Any]:
    """Собрать final_lesson.mp4 = озвученное видео + субтитры + утверждённые аннотации."""
    if not registry.exists("subtitles.srt") and not registry.exists("subtitle_timing.json"):
        raise FileNotFoundError("Сначала сохраните субтитры")
    if not registry.exists("approved_annotations.json"):
        raise FileNotFoundError("Сначала подтвердите аннотации")
    if not registry.exists("edited_video.mp4") and not registry.exists("voiceover.wav"):
        raise FileNotFoundError("Сначала дождитесь озвучки")

    if (
        not force
        and not registry.exists("render_pending.json")
        and registry.exists(FINAL_LESSON)
        and registry.exists(ASSEMBLY_REPORT)
    ):
        report = registry.load_json(ASSEMBLY_REPORT)
        if (
            report.get("status") == ArtifactStatus.COMPLETED.value
            and report.get("version") == "3.0.0"
            and report.get("includes_subtitles")
            and report.get("includes_annotations")
        ):
            logger.info("final_lesson.mp4 уже собран полностью, пропуск")
            return report

    approved = registry.load_json("approved_annotations.json")
    annotations = [
        a
        for a in (approved.get("annotations") or [])
        if a.get("placement_confirmed") and not a.get("skipped") and a.get("anchor")
    ]

    temp_subs = registry.job_dir / TEMP_WITH_SUBS
    output = registry.job_dir / "_assembly_pending.mp4"
    warnings: list[str] = []

    # 1) Прожигаем субтитры на видео с озвучкой
    try:
        subtitled = burn_subtitles_into_video(registry, settings)
        if subtitled.resolve() != temp_subs.resolve():
            shutil.copy2(subtitled, temp_subs)
        base_for_annotations = temp_subs if temp_subs.exists() else subtitled
        includes_subtitles = True
    except Exception as exc:
        logger.exception("Прожиг субтитров при сборке не удался")
        raise RuntimeError("Не удалось добавить субтитры; финальная сборка остановлена") from exc

    # 2) Накладываем утверждённые аннотации
    includes_annotations = False
    try:
        if annotations:
            render_annotation_preview(
                Path(base_for_annotations),
                annotations,
                output,
                settings=settings,
                refine_anchors=False,
            )
            includes_annotations = True
        else:
            shutil.copy2(base_for_annotations, output)
            warnings.append("Утверждённых аннотаций с координатами нет — в ролике только субтитры.")
    except Exception as exc:
        logger.exception("Наложение аннотаций при сборке не удалось")
        output.unlink(missing_ok=True)
        raise RuntimeError("Не удалось добавить аннотации; финальная сборка остановлена") from exc

    if not output.exists():
        raise RuntimeError("Сборка не создала final_lesson.mp4")

    # Keep the automatic annotation preview current after subtitle-style changes;
    # opening a manual editor must not be necessary to recreate this artifact.
    shutil.copy2(output, registry.artifact_path("annotation_preview.mp4"))

    from src.services.lesson_options_service import load_options
    from src.services.lesson_title_service import add_title_cards

    options = load_options(registry, settings)
    title_output = registry.job_dir / "_lesson_with_titles.mp4"
    try:
        title_report = add_title_cards(output, title_output, options, settings)
        if title_output.exists():
            title_output.replace(output)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    finally:
        title_output.unlink(missing_ok=True)

    report = {
        "job_id": job_id,
        "stage": PipelineStage.ASSEMBLY.value,
        "version": "3.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [
            "edited_video.mp4",
            "voiceover.wav",
            "subtitles.srt",
            "subtitle_timing.json",
            "subtitle_layout.json",
            "approved_annotations.json",
        ],
        "status": ArtifactStatus.COMPLETED.value,
        "output_file": FINAL_LESSON,
        "includes_voiceover": registry.exists("voiceover.wav"),
        "includes_subtitles": includes_subtitles,
        "includes_annotations": includes_annotations,
        "annotation_count": len(annotations),
        "intro_outro": title_report,
        "original_recording_used": True,
        "original_audio_replaced": True,
        "warnings": warnings,
        "errors": [],
    }
    registry.save_json(ASSEMBLY_REPORT, report, "assembly_report.schema.json")
    output.replace(registry.artifact_path(FINAL_LESSON))
    registry.artifact_path("render_pending.json").unlink(missing_ok=True)
    # временный файл можно оставить для отладки, но лучше не засорять
    temp_subs.unlink(missing_ok=True)
    logger.info(
        "Сборка урока готова: %s (субтитры=%s, аннотации=%s/%s)",
        FINAL_LESSON,
        includes_subtitles,
        includes_annotations,
        len(annotations),
    )
    return report
