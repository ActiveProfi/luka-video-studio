"""OCR: привязка рамки к реальному тексту на экране («НДС», «Главное» и т.д.)."""

from __future__ import annotations

from typing import Any

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("Установите: pip install -e \".[annotations]\"") from exc


def find_text_boxes_pytesseract(frame_bgr: np.ndarray, query: str) -> list[dict[str, Any]]:
    """Найти bbox текста через Tesseract (нужен установленный Tesseract-OCR)."""
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover
        raise ImportError("pip install -e \".[annotations-ocr]\"") from exc

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    data = pytesseract.image_to_data(rgb, lang="rus+eng", output_type=pytesseract.Output.DICT)
    q = query.strip().lower()
    hits: list[dict[str, Any]] = []
    n = len(data["text"])
    for i in range(n):
        word = str(data["text"][i] or "").strip()
        if not word:
            continue
        if q not in word.lower() and word.lower() not in q:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        hits.append(
            {
                "text": word,
                "x": int(x),
                "y": int(y),
                "width": int(w),
                "height": int(h),
                "confidence": float(data["conf"][i]) if str(data["conf"][i]).isdigit() else 0.0,
                "engine": "pytesseract",
            }
        )
    return hits


def find_text_boxes_easyocr(frame_bgr: np.ndarray, query: str) -> list[dict[str, Any]]:
    """Найти bbox через EasyOCR (медленнее, но лучше на скриншотах 1С)."""
    try:
        import easyocr
    except ImportError as exc:  # pragma: no cover
        raise ImportError("pip install -e \".[annotations-ocr]\"") from exc

    reader = easyocr.Reader(["ru", "en"], gpu=False)
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    q = query.strip().lower()
    hits: list[dict[str, Any]] = []
    for bbox, text, conf in reader.readtext(rgb):
        t = str(text).strip()
        if not t:
            continue
        if q not in t.lower() and t.lower() not in q:
            continue
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
        hits.append(
            {
                "text": t,
                "x": x1,
                "y": y1,
                "width": max(2, x2 - x1),
                "height": max(2, y2 - y1),
                "confidence": float(conf),
                "engine": "easyocr",
            }
        )
    return hits


def pixels_to_norm(
    x: int,
    y: int,
    width: int,
    height: int,
    frame_w: int,
    frame_h: int,
) -> dict[str, float]:
    """Пиксели → anchor для annotation_suggestions.json."""
    return {
        "x": round(x / frame_w, 4),
        "y": round(y / frame_h, 4),
        "width": round(width / frame_w, 4),
        "height": round(height / frame_h, 4),
    }
