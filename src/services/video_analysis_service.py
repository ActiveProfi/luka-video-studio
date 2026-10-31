"""Анализ видео/аудио через ffmpeg для этапа тайминга."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from src.config import Settings, get_settings
from src.services.ffmpeg_service import _ffmpeg_bin, get_media_duration_seconds

logger = logging.getLogger(__name__)

_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")
_SCENE_TIME_RE = re.compile(r"pts_time:([0-9.]+)")


def detect_silence_intervals(
    media_path: Path,
    noise_db: int = -35,
    min_duration: float = 0.8,
    settings: Settings | None = None,
) -> list[tuple[float, float]]:
    """Найти интервалы тишины (silencedetect)."""
    if not media_path.exists():
        return []

    cmd = [
        _ffmpeg_bin(settings),
        "-hide_banner",
        "-i",
        str(media_path),
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        logger.warning("silencedetect не выполнен: %s", exc)
        return []

    intervals: list[tuple[float, float]] = []
    current_start: float | None = None
    for line in result.stderr.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            current_start = float(start_match.group(1))
            continue
        end_match = _SILENCE_END_RE.search(line)
        if end_match and current_start is not None:
            end = float(end_match.group(1))
            if end > current_start:
                intervals.append((round(current_start, 3), round(end, 3)))
            current_start = None
    return intervals


def detect_scene_change_times(
    video_path: Path,
    threshold: float = 0.02,
    settings: Settings | None = None,
) -> list[float]:
    """Временные метки смены сцен (proxy визуальной активности)."""
    if not video_path.exists():
        return []

    cmd = [
        _ffmpeg_bin(settings),
        "-hide_banner",
        "-i",
        str(video_path),
        "-vf",
        f"select='gt(scene,{threshold})',metadata=print",
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        logger.warning("scene detect не выполнен: %s", exc)
        return []

    times = [float(m.group(1)) for m in _SCENE_TIME_RE.finditer(result.stderr)]
    return [round(t, 3) for t in sorted(set(times))]


def count_scene_changes_in_interval(
    scene_times: list[float],
    start: float,
    end: float,
) -> int:
    return sum(1 for t in scene_times if start <= t <= end)


def resolve_media_for_analysis(registry_job_dir: Path, registry_exists) -> tuple[Path | None, float]:
    """Выбрать файл для анализа и вернуть длительность."""
    settings = get_settings()
    candidates = [
        registry_job_dir / "raw_audio.ogg",
        registry_job_dir / "raw_video.mp4",
        registry_job_dir / "_upload" / "raw_video.mp4",
    ]
    for path in candidates:
        if path.exists():
            try:
                return path, get_media_duration_seconds(path, settings)
            except Exception:
                continue
    return None, 0.0
