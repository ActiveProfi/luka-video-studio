"""OpenCV: кадры, стрелки, рамки, template matching по элементам UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("Установите: pip install -e \".[annotations]\"") from exc


def extract_frame(video_path: Path | str, time_sec: float) -> np.ndarray:
    """Взять один кадр видео в заданную секунду (BGR)."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Не удалось открыть видео: {video_path}")
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, time_sec) * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise ValueError(f"Кадр на t={time_sec}s не прочитан")
        return frame
    finally:
        cap.release()


def video_size(video_path: Path | str) -> tuple[int, int]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(str(video_path))
    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return w, h
    finally:
        cap.release()


def norm_to_pixels(
    x: float,
    y: float,
    width: float,
    height: float,
    frame_w: int,
    frame_h: int,
) -> tuple[int, int, int, int]:
    """Нормализованные 0..1 координаты → пиксели (x1, y1, x2, y2)."""
    x1 = int(round(x * frame_w))
    y1 = int(round(y * frame_h))
    x2 = int(round((x + width) * frame_w))
    y2 = int(round((y + height) * frame_h))
    return x1, y1, max(x1 + 2, x2), max(y1 + 2, y2)


def draw_highlight_rect(
    frame: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    color_bgr: tuple[int, int, int] = (0, 220, 255),
    thickness: int = 3,
) -> np.ndarray:
    """Жёлтая рамка без заливки — не перекрывает текст."""
    out = frame.copy()
    cv2.rectangle(out, (x1, y1), (x2, y2), color_bgr, thickness, lineType=cv2.LINE_AA)
    return out


def draw_arrow(
    frame: np.ndarray,
    tip_x: int,
    tip_y: int,
    tail_x: int,
    tail_y: int,
    *,
    color_bgr: tuple[int, int, int] = (0, 0, 255),
    thickness: int = 3,
) -> np.ndarray:
    """Стрелка к элементу (не прямоугольник-заглушка)."""
    out = frame.copy()
    cv2.arrowedLine(
        out,
        (tail_x, tail_y),
        (tip_x, tip_y),
        color_bgr,
        thickness,
        tipLength=0.25,
        line_type=cv2.LINE_AA,
    )
    return out


def match_template(
    frame: np.ndarray,
    template: np.ndarray,
    *,
    threshold: float = 0.82,
) -> list[dict[str, Any]]:
    """
    Найти элемент интерфейса на кадре (иконка, кнопка).
    Возвращает список совпадений с bbox в пикселях и score.
    """
    if template.ndim == 3:
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_tpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    else:
        gray_frame, gray_tpl = frame, template

    result = cv2.matchTemplate(gray_frame, gray_tpl, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= threshold)
    h, w = gray_tpl.shape[:2]
    matches: list[dict[str, Any]] = []
    for y, x in zip(ys.tolist(), xs.tolist(), strict=False):
        matches.append(
            {
                "x": int(x),
                "y": int(y),
                "width": int(w),
                "height": int(h),
                "score": float(result[y, x]),
            }
        )
    return matches
