"""Рендер превью синхронизации: видео + озвучка без графики."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.config import Settings, get_settings
from src.services.ffmpeg_service import _ffmpeg_bin, get_media_duration_seconds

logger = logging.getLogger(__name__)

SYNC_PREVIEW_FILENAME = "sync_preview.mp4"


def render_sync_preview(
    edited_video: Path,
    voiceover_wav: Path,
    output_path: Path,
    audio_offset_seconds: float = 0.0,
    settings: Settings | None = None,
) -> Path:
    """Склеить смонтированное видео с озвучкой (без стрелок и рамок)."""
    settings = settings or get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not edited_video.exists():
        raise FileNotFoundError(f"Нет видео: {edited_video}")
    if not voiceover_wav.exists():
        raise FileNotFoundError(f"Нет озвучки: {voiceover_wav}")

    ffmpeg = _ffmpeg_bin(settings)
    offset = float(audio_offset_seconds)

    if offset >= 0:
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(edited_video),
            "-itsoffset",
            f"{offset:.3f}",
            "-i",
            str(voiceover_wav),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(output_path),
        ]
    else:
        trim = abs(offset)
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(edited_video),
            "-ss",
            f"{trim:.3f}",
            "-i",
            str(voiceover_wav),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(output_path),
        ]

    logger.info("Рендер sync_preview, сдвиг аудио %.3f с", offset)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = (result.stderr or "")[-2500:]
        raise RuntimeError(f"ffmpeg sync preview failed: {tail}")

    duration = get_media_duration_seconds(output_path, settings)
    logger.info("sync_preview готов: %.1f с", duration)
    return output_path
