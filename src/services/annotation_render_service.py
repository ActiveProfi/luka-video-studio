"""Рендер превью урока с аннотациями через OpenCV + ffmpeg (без drawbox)."""

from __future__ import annotations

import logging
import subprocess
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.config import Settings, get_settings
from src.services.annotation_anchor_service import refine_annotation_anchors
from src.services.ffmpeg_service import _ffmpeg_bin, get_media_duration_seconds
from src.tools.annotation_toolkit.opencv_tools import draw_arrow, draw_highlight_rect, norm_to_pixels

logger = logging.getLogger(__name__)

PREVIEW_FILENAME = "annotation_preview.mp4"

_TYPE_LABELS = {
    "arrow": "стрелка",
    "highlight_rect": "рамка",
    "zoom": "увеличение",
    "callout": "подпись",
}

# BGR
_COLOR_YELLOW = (0, 210, 255)
_COLOR_RED = (40, 40, 220)
_COLOR_WHITE = (255, 255, 255)


def render_annotation_preview(
    lesson_video: Path,
    annotations: list[dict[str, Any]],
    output_path: Path,
    settings: Settings | None = None,
    *,
    refine_anchors: bool = True,
) -> Path:
    """Наложить стрелки/рамки на видео урока. Рамки — контур, без заливки поверх текста."""
    import shutil

    settings = settings or get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not lesson_video.exists():
        raise FileNotFoundError(f"Нет видео урока: {lesson_video}")

    items = annotations
    # Пустой список: не гоняем OpenCV по всему ролику (это «вешает» шаг 7 на длинных видео)
    if not items:
        if lesson_video.resolve() != output_path.resolve():
            shutil.copy2(lesson_video, output_path)
        logger.info("Превью аннотаций: копирование без наложений → %s", output_path.name)
        return output_path

    if refine_anchors:
        items = refine_annotation_anchors(lesson_video, items, settings=settings)

    temp_noaudio = output_path.with_name(f"{output_path.stem}.{uuid.uuid4().hex}.noaudio{output_path.suffix}")
    try:
        _render_video_opencv(lesson_video, items, temp_noaudio, settings)
        _mux_original_audio(temp_noaudio, lesson_video, output_path, settings)
    finally:
        try:
            temp_noaudio.unlink(missing_ok=True)
        except OSError:
            logger.warning("Не удалось убрать временный файл %s", temp_noaudio.name)

    duration = get_media_duration_seconds(output_path, settings)
    logger.info(
        "Превью аннотаций (OpenCV): %s элементов, %.1f с → %s",
        len(items),
        duration,
        output_path.name,
    )
    return output_path


def _render_video_opencv(
    source: Path,
    annotations: list[dict[str, Any]],
    output_path: Path,
    settings: Settings,
) -> None:
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV не открыл видео: {source}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    if fps <= 0:
        fps = 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError(f"Некорректный размер видео: {width}x{height}")

    ffmpeg = _ffmpeg_bin(settings)
    cmd = [
        ffmpeg,
        "-loglevel",
        "error",
        "-nostats",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-s",
        f"{width}x{height}",
        "-pix_fmt",
        "bgr24",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None

    frame_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            time_sec = frame_idx / fps
            painted = _paint_frame(frame, annotations, time_sec, width, height)
            proc.stdin.write(painted.tobytes())
            frame_idx += 1
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            stderr = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", errors="replace")
            code = proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if proc.stderr:
                proc.stderr.close()
        if code != 0:
            raise RuntimeError(f"ffmpeg rawvideo encode failed: {stderr[-2500:]}")

    if frame_idx == 0:
        raise RuntimeError("Видео не содержит кадров")


def _paint_frame(
    frame: np.ndarray,
    annotations: list[dict[str, Any]],
    time_sec: float,
    frame_w: int,
    frame_h: int,
) -> np.ndarray:
    out = frame.copy()
    for ann in annotations:
        if not ann.get("placement_confirmed"):
            continue
        anchor = ann.get("anchor")
        if not isinstance(anchor, dict):
            continue
        start = float(ann.get("target_start", 0))
        end = max(start + 0.2, float(ann.get("target_end", start + 1)))
        if not (start <= time_sec <= end):
            continue
        alpha = _fade_alpha(time_sec, start, end)
        tracked = _tracked_annotation(ann, time_sec)
        _draw_annotation(out, tracked, frame_w, frame_h, alpha=alpha)
    return out


def _tracked_annotation(ann: dict, time_sec: float) -> dict:
    track = ann.get("anchor_track") or []
    if not track:
        return ann
    for left, right in zip(track, track[1:]):
        if left["time"] <= time_sec <= right["time"]:
            ratio = (time_sec - left["time"]) / max(0.001, right["time"] - left["time"])
            anchor = {key: left["anchor"][key] + ratio * (right["anchor"][key] - left["anchor"][key])
                      for key in ("x", "y", "width", "height")}
            return {**ann, "anchor": anchor}
    return {**ann, "anchor": track[0 if time_sec < track[0]["time"] else -1]["anchor"]}


def _fade_alpha(time_sec: float, start: float, end: float) -> float:
    """Плавное появление и исчезновение (0..1)."""
    duration = max(0.3, end - start)
    fade = min(0.35, duration * 0.25)
    if time_sec < start + fade:
        return max(0.0, (time_sec - start) / fade)
    if time_sec > end - fade:
        return max(0.0, (end - time_sec) / fade)
    return 1.0


def _blend_overlay(base: np.ndarray, overlay: np.ndarray, alpha: float) -> None:
    if alpha >= 0.999:
        np.copyto(base, overlay)
        return
    cv2.addWeighted(overlay, alpha, base, 1.0 - alpha, 0, dst=base)


def _draw_annotation(
    frame: np.ndarray,
    ann: dict[str, Any],
    frame_w: int,
    frame_h: int,
    *,
    alpha: float = 1.0,
) -> None:
    anchor = ann.get("anchor") or {}
    ann_type = str(ann.get("type", "highlight_rect"))

    if ann_type == "arrow":
        tip_x = int(round(float(anchor.get("x", 0.5)) * frame_w))
        tip_y = int(round(float(anchor.get("y", 0.5)) * frame_h))
        length_ratio = float(ann.get("arrow_length_ratio") or 0.08)
        length_px = int(min(frame_w, frame_h) * length_ratio)
        direction = str(ann.get("arrow_direction") or "left").lower()
        tail_x, tail_y = _arrow_tail(tip_x, tip_y, direction, length_px)
        painted = draw_arrow(
            frame,
            tip_x,
            tip_y,
            tail_x,
            tail_y,
            color_bgr=_COLOR_RED,
            thickness=3,
        )
        _blend_overlay(frame, painted, alpha)
        return

    x = float(anchor.get("x", 0.2))
    y = float(anchor.get("y", 0.2))
    w = max(0.001, float(anchor.get("width", 0.12)))
    h = max(0.001, float(anchor.get("height", 0.05)))
    x1, y1, x2, y2 = norm_to_pixels(x, y, w, h, frame_w, frame_h)

    if ann_type in {"highlight_rect", "zoom"}:
        color = _COLOR_RED if ann_type == "zoom" else _COLOR_YELLOW
        thickness = 4 if ann_type == "zoom" else 3
        painted = draw_highlight_rect(frame, x1, y1, x2, y2, color_bgr=color, thickness=thickness)
        _blend_overlay(frame, painted, alpha)
        return

    if ann_type == "callout":
        label = _safe_label(str(ann.get("label", "")))
        box_h = max(28, int(frame_h * 0.045))
        box_y2 = max(8, y1 - 6)
        box_y1 = max(4, box_y2 - box_h)
        painted = draw_highlight_rect(
            frame,
            x1,
            box_y1,
            min(frame_w - 4, x2),
            box_y2,
            color_bgr=_COLOR_YELLOW,
            thickness=2,
        )
        if label:
            cv2.putText(
                painted,
                label,
                (x1 + 6, max(box_y1 + box_h - 8, 16)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                _COLOR_WHITE,
                2,
                cv2.LINE_AA,
            )
        _blend_overlay(frame, painted, alpha)


def _arrow_tail(tip_x: int, tip_y: int, direction: str, length_px: int) -> tuple[int, int]:
    if direction == "right":
        return tip_x - length_px, tip_y
    if direction == "top":
        return tip_x, tip_y + length_px
    if direction == "bottom":
        return tip_x, tip_y - length_px
    return tip_x + length_px, tip_y


def _mux_original_audio(
    video_only: Path,
    source_with_audio: Path,
    output_path: Path,
    settings: Settings,
) -> None:
    ffmpeg = _ffmpeg_bin(settings)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_only),
        "-i",
        str(source_with_audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = (result.stderr or "")[-2500:]
        raise RuntimeError(f"ffmpeg mux audio failed: {tail}")


def _safe_label(text: str, max_len: int = 48) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1] + "…"
    return cleaned


def annotation_type_label(ann_type: str) -> str:
    return _TYPE_LABELS.get(ann_type, ann_type)
