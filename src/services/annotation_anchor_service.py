"""Привязка аннотаций к элементам UI через OCR на кадре видео."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from src.config import Settings, get_settings
from src.tools.annotation_toolkit.opencv_tools import extract_frame, video_size

logger = logging.getLogger(__name__)

_OCR_QUERY_STOPWORDS = frozenset(
    {
        "этот",
        "этого",
        "когда",
        "котор",
        "будет",
        "нужно",
        "теперь",
        "далее",
        "следующ",
        "уроке",
        "элемент",
    }
)


def refine_annotation_anchors(
    video_path: Path | str,
    annotations: list[dict[str, Any]],
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """
    Уточнить anchor каждой аннотации по тексту на экране в момент показа.
    Если OCR не нашёл — оставляет исходный anchor.
    """
    settings = settings or get_settings()
    video_path = Path(video_path)
    if not video_path.exists() or not annotations:
        return annotations

    try:
        frame_w, frame_h = video_size(video_path)
    except Exception as exc:
        logger.warning("OCR anchor: не удалось прочитать видео %s: %s", video_path, exc)
        return [_with_anchor_source(ann, "fallback") for ann in annotations]

    ocr_fn = _pick_ocr_engine(settings)
    if ocr_fn is None:
        logger.info("OCR не установлен — аннотации с исходными координатами")
        return [_with_anchor_source(ann, "model") for ann in annotations]

    refined: list[dict[str, Any]] = []
    for ann in annotations:
        refined.append(_refine_one(video_path, ann, frame_w, frame_h, ocr_fn, settings))
    ocr_hits = sum(1 for a in refined if a.get("anchor_source") == "ocr")
    logger.info("OCR anchor: уточнено %s из %s аннотаций", ocr_hits, len(refined))
    return refined


def _refine_one(
    video_path: Path,
    ann: dict[str, Any],
    frame_w: int,
    frame_h: int,
    ocr_fn,
    settings: Settings,
) -> dict[str, Any]:
    start = float(ann.get("target_start", 0))
    end = float(ann.get("target_end", start + 1))
    sample_time = start + (end - start) * 0.35
    label = str(ann.get("label", "")).strip()

    try:
        frame = extract_frame(video_path, sample_time)
    except Exception as exc:
        logger.debug("OCR anchor %s: кадр не прочитан: %s", ann.get("annotation_id"), exc)
        return _with_anchor_source(ann, "model")

    best_hit: dict[str, Any] | None = None
    for query in _label_queries(label):
        try:
            hits = ocr_fn(frame, query)
        except ImportError as exc:
            logger.warning("OCR недоступен — координаты модели: %s", exc)
            return _with_anchor_source(ann, "model")
        except Exception as exc:
            logger.debug("OCR anchor %s: ошибка поиска «%s»: %s", ann.get("annotation_id"), query, exc)
            hits = []
        if hits:
            best_hit = max(hits, key=lambda item: float(item.get("confidence", 0)))
            break

    if not best_hit:
        return _with_anchor_source(ann, "model")

    pad_x = max(4, int(frame_w * 0.004))
    pad_y = max(3, int(frame_h * 0.006))
    x = max(0, int(best_hit["x"]) - pad_x)
    y = max(0, int(best_hit["y"]) - pad_y)
    w = min(frame_w - x, int(best_hit["width"]) + pad_x * 2)
    h = min(frame_h - y, int(best_hit["height"]) + pad_y * 2)

    anchor = {
        "x": round(x / frame_w, 4),
        "y": round(y / frame_h, 4),
        "width": round(w / frame_w, 4),
        "height": round(h / frame_h, 4),
    }
    return {
        **ann,
        "anchor": anchor,
        "anchor_source": "ocr",
        "ocr_text": str(best_hit.get("text", "")),
        "ocr_engine": str(best_hit.get("engine", "ocr")),
    }


def _label_queries(label: str) -> list[str]:
    cleaned = " ".join(label.split()).strip()
    queries: list[str] = []
    if cleaned:
        queries.append(cleaned)

    for match in re.findall(r"«([^»]+)»", cleaned):
        if match.strip():
            queries.append(match.strip())

    words = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", cleaned.lower())
    for word in words:
        if len(word) < 3 or word in _OCR_QUERY_STOPWORDS:
            continue
        if word not in queries:
            queries.append(word)

    compact = cleaned.replace(" ", "").lower()
    for token in ("ндс", "эндэс", "1с", "отчет", "отчёт", "главное", "налоги"):
        if token in compact and token not in queries:
            queries.append(token.replace("эндэс", "ндс"))

    return queries[:8]


def _pick_ocr_engine(settings: Settings):
    engine = str(getattr(settings, "annotation_ocr_engine", "auto") or "auto").lower()
    if engine in {"off", "none", "false", "0"}:
        return None

    if engine in {"easyocr", "easy"}:
        return _easyocr_fn_or_none()

    if engine in {"tesseract", "pytesseract"}:
        return _tesseract_fn_or_none()

    return _tesseract_fn_or_none() or _easyocr_fn_or_none()


def _tesseract_fn_or_none():
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return None
    from src.tools.annotation_toolkit.ocr_tools import find_text_boxes_pytesseract

    return find_text_boxes_pytesseract


def _easyocr_fn_or_none():
    try:
        import easyocr  # noqa: F401
    except ImportError:
        return None
    from src.tools.annotation_toolkit.ocr_tools import find_text_boxes_easyocr

    return find_text_boxes_easyocr


def _with_anchor_source(ann: dict[str, Any], source: str) -> dict[str, Any]:
    return {**ann, "anchor_source": source}
