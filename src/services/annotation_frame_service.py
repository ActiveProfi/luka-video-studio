"""Извлечение стоп-кадров для ручной расстановки аннотаций."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2

logger = logging.getLogger(__name__)

FRAMES_SUBDIR = "annotation_frames"


def frames_dir_for_job(job_dir: Path) -> Path:
    path = job_dir / FRAMES_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def frame_artifact_name(annotation_id: str) -> str:
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in annotation_id)
    return f"{FRAMES_SUBDIR}/frame_{safe_id}.png"


def extract_frame_to_file(video_path: Path, time_sec: float, output_path: Path) -> Path:
    """Сохранить один кадр видео в PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Не удалось открыть видео: {video_path}")
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(time_sec)) * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise ValueError(f"Кадр на t={time_sec:.2f}s не прочитан")
        if not cv2.imwrite(str(output_path), frame):
            raise RuntimeError(f"Не удалось сохранить кадр: {output_path}")
        return output_path
    finally:
        cap.release()


def attach_frames_to_suggestions(
    video_path: Path,
    job_dir: Path,
    suggestions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Для каждого предложения — стоп-кадр в момент действия."""
    frames_dir_for_job(job_dir)
    updated: list[dict[str, Any]] = []
    for item in suggestions:
        ann_id = str(item.get("annotation_id", "ann"))
        time_sec = float(item.get("target_start", 0))
        frame_rel = frame_artifact_name(ann_id)
        frame_path = job_dir / frame_rel
        try:
            extract_frame_to_file(video_path, time_sec, frame_path)
            item = {**item, "frame_file": frame_rel}
        except Exception as exc:
            logger.warning("Кадр %s не извлечён: %s", ann_id, exc)
            item = {**item, "frame_file": None, "frame_error": str(exc)[:200]}
        updated.append(item)
    return updated
