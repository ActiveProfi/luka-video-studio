"""Тайм-блоки — основа архитектуры v3.

Блоки создаются автоматически сразу после загрузки (пользователь процесса не видит):
паузы в звуке + смена картинки на экране + ограничение максимальной длительности.
Дальше пользователь только вписывает субтитр в каждый блок.
"""

from __future__ import annotations

import logging
import re
import subprocess

from src.config import Settings, get_settings
from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.ffmpeg_service import _ffmpeg_bin
from src.services.media_paths import resolve_raw_video_path
from src.services.video_probe_service import get_video_meta

logger = logging.getLogger(__name__)

TIME_BLOCKS_FILE = "time_blocks.json"

STATUS_EMPTY = "empty"
STATUS_EDITED = "edited"
STATUS_SAVED = "saved"

_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")
_SCENE_PTS_RE = re.compile(r"pts_time:([0-9.]+)")


def _run_ffmpeg_analysis(args: list[str], timeout: int = 900) -> str:
    """ffmpeg пишет результаты фильтров в stderr."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Анализ видео превысил таймаут, используем упрощённое разбиение")
        return ""
    return (result.stderr or "") + (result.stdout or "")


def detect_silence_points(
    video_path,
    settings: Settings | None = None,
) -> list[float]:
    """Середины тишины — естественные границы блоков."""
    settings = settings or get_settings()
    args = [
        _ffmpeg_bin(settings),
        "-hide_banner",
        "-nostats",
        "-i",
        str(video_path),
        "-af",
        (
            f"silencedetect=noise={settings.block_silence_noise_db}dB:"
            f"d={settings.block_silence_min_seconds}"
        ),
        "-f",
        "null",
        "-",
    ]
    output = _run_ffmpeg_analysis(args)
    starts = [float(m) for m in _SILENCE_START_RE.findall(output)]
    ends = [float(m) for m in _SILENCE_END_RE.findall(output)]
    points: list[float] = []
    for idx, start in enumerate(starts):
        end = ends[idx] if idx < len(ends) else None
        points.append(round((start + end) / 2, 3) if end is not None else round(start, 3))
    return points


def detect_scene_points(
    video_path,
    settings: Settings | None = None,
) -> list[float]:
    """Резкая смена картинки: новое окно 1С, переход к другому документу."""
    settings = settings or get_settings()
    args = [
        _ffmpeg_bin(settings),
        "-hide_banner",
        "-nostats",
        "-i",
        str(video_path),
        "-filter:v",
        f"select='gt(scene,{settings.block_scene_threshold})',showinfo",
        "-f",
        "null",
        "-",
    ]
    output = _run_ffmpeg_analysis(args)
    return [round(float(m), 3) for m in _SCENE_PTS_RE.findall(output)]


def _merge_cut_points(
    raw_points: list[float],
    duration: float,
    settings: Settings,
) -> list[float]:
    """Оставить точки, которые дают блоки не короче минимума."""
    min_len = max(0.5, float(settings.block_min_seconds))
    points = sorted({round(p, 3) for p in raw_points if 0 < p < duration})
    result: list[float] = []
    last = 0.0
    for point in points:
        if point - last < min_len:
            continue
        if duration - point < min_len:
            continue
        result.append(point)
        last = point
    return result


def _split_long_blocks(
    bounds: list[tuple[float, float]],
    settings: Settings,
) -> list[tuple[float, float]]:
    """Длинный блок делим на равные части — субтитр не должен быть простыней."""
    max_len = max(2.0, float(settings.block_max_seconds))
    target = max(2.0, float(settings.block_target_seconds))
    result: list[tuple[float, float]] = []
    for start, end in bounds:
        span = end - start
        if span <= max_len:
            result.append((start, end))
            continue
        parts = max(2, int(round(span / target)))
        step = span / parts
        for i in range(parts):
            piece_start = start + step * i
            piece_end = end if i == parts - 1 else start + step * (i + 1)
            result.append((round(piece_start, 3), round(piece_end, 3)))
    return result


def build_time_blocks_bounds(
    video_path,
    duration: float,
    has_audio: bool,
    settings: Settings | None = None,
) -> list[tuple[float, float]]:
    settings = settings or get_settings()
    if duration <= 0:
        return []

    raw_points: list[float] = []
    if has_audio:
        try:
            raw_points.extend(detect_silence_points(video_path, settings))
        except Exception:
            logger.exception("Анализ пауз не удался, продолжаем без него")
    try:
        raw_points.extend(detect_scene_points(video_path, settings))
    except Exception:
        logger.exception("Анализ смены картинки не удался, продолжаем без него")

    cut_points = _merge_cut_points(raw_points, duration, settings)
    bounds: list[tuple[float, float]] = []
    prev = 0.0
    for point in cut_points:
        bounds.append((round(prev, 3), round(point, 3)))
        prev = point
    bounds.append((round(prev, 3), round(duration, 3)))
    bounds = [b for b in bounds if b[1] - b[0] > 0.2]
    return _split_long_blocks(bounds, settings)


def build_time_blocks(
    registry: ArtifactRegistry,
    job_id: str,
    settings: Settings | None = None,
    *,
    force: bool = False,
) -> dict:
    """Создать time_blocks.json автоматически. Введённые субтитры сохраняются."""
    settings = settings or get_settings()
    if registry.exists(TIME_BLOCKS_FILE) and not force:
        return registry.load_json(TIME_BLOCKS_FILE)

    previous_text: dict[str, str] = {}
    if registry.exists(TIME_BLOCKS_FILE):
        old = registry.load_json(TIME_BLOCKS_FILE)
        for block in old.get("blocks") or []:
            text = str(block.get("subtitle") or "").strip()
            if text:
                previous_text[str(block.get("id"))] = text

    meta = get_video_meta(registry, job_id)
    video_path = resolve_raw_video_path(registry)
    bounds = build_time_blocks_bounds(
        video_path,
        float(meta.get("duration_seconds") or 0.0),
        bool(meta.get("has_audio")),
        settings,
    )
    if not bounds:
        raise ValueError("Не удалось определить длительность видео для разбиения на блоки")

    blocks = []
    for idx, (start, end) in enumerate(bounds, start=1):
        text = previous_text.get(str(idx), "")
        blocks.append(
            {
                "id": idx,
                "start": round(float(start), 3),
                "end": round(float(end), 3),
                "subtitle": text,
                "status": STATUS_EDITED if text else STATUS_EMPTY,
            }
        )

    doc = {
        "job_id": job_id,
        "stage": "time_blocks",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "saved_at": None,
        "source": "auto_split",
        "duration_seconds": round(float(meta.get("duration_seconds") or 0.0), 3),
        "fps": meta.get("fps"),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "has_audio": bool(meta.get("has_audio")),
        "blocks": blocks,
    }
    registry.save_json(TIME_BLOCKS_FILE, doc)
    logger.info("Ролик разбит на %s тайм-блоков", len(blocks))
    return doc


def load_time_blocks(registry: ArtifactRegistry, job_id: str) -> dict:
    if registry.exists(TIME_BLOCKS_FILE):
        return registry.load_json(TIME_BLOCKS_FILE)
    return build_time_blocks(registry, job_id)


def time_blocks_ready(registry: ArtifactRegistry) -> bool:
    return registry.exists(TIME_BLOCKS_FILE)


def subtitles_saved(registry: ArtifactRegistry) -> bool:
    """Пользователь нажал «Сохранить» и текст стал источником для озвучки."""
    if not registry.exists(TIME_BLOCKS_FILE):
        return False
    doc = registry.load_json(TIME_BLOCKS_FILE)
    if not doc.get("saved_at"):
        return False
    return any(str(b.get("subtitle") or "").strip() for b in doc.get("blocks") or [])


def filled_block_count(doc: dict) -> int:
    return sum(1 for b in doc.get("blocks") or [] if str(b.get("subtitle") or "").strip())
