"""Внутренний анализ загруженного ролика (этап 1 архитектуры v3).

Пользователь этот процесс не видит: длительность, FPS, разрешение, наличие аудио.
Результат — video_meta.json, на него опираются авторазбиение и озвучка.
"""

from __future__ import annotations

import json
import logging
import subprocess

from src.config import Settings, get_settings
from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.ffmpeg_service import _ffprobe_bin
from src.services.media_paths import resolve_raw_video_path

logger = logging.getLogger(__name__)

VIDEO_META_FILE = "video_meta.json"


def _parse_fps(raw: str | None) -> float:
    """ffprobe отдаёт кадры как дробь вида «30000/1001»."""
    if not raw:
        return 0.0
    raw = raw.strip()
    try:
        if "/" in raw:
            num, den = raw.split("/", 1)
            den_value = float(den)
            if den_value == 0:
                return 0.0
            return round(float(num) / den_value, 3)
        return round(float(raw), 3)
    except (TypeError, ValueError):
        return 0.0


def probe_video(video_path, settings: Settings | None = None) -> dict:
    """Собрать характеристики ролика одним вызовом ffprobe."""
    cmd = [
        _ffprobe_bin(settings),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = 0.0
    for candidate in (fmt.get("duration"), (video_stream or {}).get("duration")):
        try:
            duration = float(candidate)
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue

    fps = _parse_fps((video_stream or {}).get("avg_frame_rate")) or _parse_fps(
        (video_stream or {}).get("r_frame_rate")
    )

    return {
        "duration_seconds": round(duration, 3),
        "fps": fps,
        "width": int((video_stream or {}).get("width") or 0),
        "height": int((video_stream or {}).get("height") or 0),
        "has_audio": audio_stream is not None,
        "video_codec": str((video_stream or {}).get("codec_name") or ""),
        "audio_codec": str((audio_stream or {}).get("codec_name") or ""),
        "size_bytes": int(fmt.get("size") or 0),
    }


def build_video_meta(
    registry: ArtifactRegistry,
    job_id: str,
    settings: Settings | None = None,
    *,
    force: bool = False,
) -> dict:
    """Создать (или переиспользовать) video_meta.json для job."""
    settings = settings or get_settings()
    if registry.exists(VIDEO_META_FILE) and not force:
        return registry.load_json(VIDEO_META_FILE)

    video_path = resolve_raw_video_path(registry)
    info = probe_video(video_path, settings)
    doc = {
        "job_id": job_id,
        "stage": "video_probe",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_file": video_path.name,
        **info,
    }
    registry.save_json(VIDEO_META_FILE, doc)
    logger.info(
        "Видео проанализировано: %.1f с, %sx%s, %.2f fps, аудио=%s",
        doc["duration_seconds"],
        doc["width"],
        doc["height"],
        doc["fps"],
        doc["has_audio"],
    )
    return doc


def get_video_meta(registry: ArtifactRegistry, job_id: str) -> dict:
    if registry.exists(VIDEO_META_FILE):
        return registry.load_json(VIDEO_META_FILE)
    return build_video_meta(registry, job_id)
