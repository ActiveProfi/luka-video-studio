"""Поиск исходных медиафайлов job."""

from __future__ import annotations

from pathlib import Path

from src.orchestrator.artifact_registry import ArtifactRegistry


def resolve_raw_video_path(registry: ArtifactRegistry) -> Path:
    candidates: list[Path] = []

    if registry.exists("input_manifest.json"):
        manifest = registry.load_json("input_manifest.json")
        raw_path = Path(str(manifest.get("raw_video_path", "")))
        if raw_path.exists():
            candidates.append(raw_path)

    candidates.extend(
        [
            registry.job_dir / "raw_video.mp4",
            registry.job_dir / "_upload" / "raw_video.mp4",
        ]
    )

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError(
        "Исходное видео не найдено. Загрузите raw_video.mp4 или выполните этап загрузки заново."
    )


def resolve_edited_video_path(registry: ArtifactRegistry) -> Path:
    """Путь к смонтированному видео job."""
    path = registry.job_dir / "edited_video.mp4"
    if path.exists():
        return path
    raise FileNotFoundError(
        "Смонтированное видео edited_video.mp4 не найдено. Сначала выполните монтаж (шаг 5)."
    )


def resolve_final_lesson_path(registry: ArtifactRegistry) -> Path:
    """Путь к собранному уроку после синхронизации и сборки."""
    path = registry.job_dir / "final_lesson.mp4"
    if path.exists():
        return path
    raise FileNotFoundError(
        "final_lesson.mp4 не найден. Сначала выполните синхронизацию (шаг 8) и сборку (шаг 9)."
    )
