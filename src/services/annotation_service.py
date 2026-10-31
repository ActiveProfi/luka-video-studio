"""Подготовка предложений по аннотациям (стрелки, рамки, zoom)."""

from __future__ import annotations

import re
from typing import Any

ANNOTATION_TYPES = frozenset({"arrow", "highlight_rect", "zoom", "callout", "frame"})
SUGGESTED_TYPE_MAP = {
    "arrow": "arrow",
    "frame": "highlight_rect",
    "highlight_rect": "highlight_rect",
    "zoom": "zoom",
    "callout": "callout",
    "увеличение": "zoom",
    "рамка": "highlight_rect",
    "стрелка": "arrow",
}

ACTION_KEYWORDS = (
    "открываем",
    "находим",
    "нажимаем",
    "выбираем",
    "переходим",
    "сформируем",
    "проверяем",
    "ставим",
    "галочк",
    "отчёт",
    "отчет",
    "ндс",
    "доход",
    "лимит",
    "меню",
    "главное",
)

DEFAULT_STYLE = {
    "arrow": "red_arrow",
    "highlight_rect": "yellow_box",
    "zoom": "soft_zoom",
    "callout": "text_callout",
}


def build_lesson_moments(
    clean_segments: list[dict],
    voiceover_segments: list[dict],
    timeline_segments: list[dict],
) -> list[dict[str, Any]]:
    """Сопоставить текст урока с таймингом смонтированного видео."""
    # V3 synthesizes complete phrases spanning several subtitle blocks. These
    # phrases, rather than the split captions, are the authoritative speech clock.
    if voiceover_segments and all(v.get("source_block_ids") for v in voiceover_segments):
        return [
            {
                "segment_id": v["transcript_segment_id"],
                "target_start": float(v["audio_start"]),
                "target_end": max(
                    float(v["audio_end"]), float(v.get("target_end", v["audio_end"]))
                ),
                "text": str(v.get("subtitle_text") or v["text"]),
            }
            for v in voiceover_segments
        ]
    voice_by_transcript = {
        str(v.get("transcript_segment_id", "")): v
        for v in voiceover_segments
        if v.get("transcript_segment_id")
    }
    moments: list[dict[str, Any]] = []

    for seg in clean_segments:
        seg_id = str(seg.get("segment_id", ""))
        voice = voice_by_transcript.get(seg_id)
        if voice:
            target_start = float(voice.get("audio_start", voice.get("target_start", 0)))
            target_end = float(voice.get("audio_end", voice.get("target_end", target_start + 1)))
        else:
            target_start, target_end, _ = _map_interval(seg, timeline_segments)

        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        moments.append(
            {
                "segment_id": seg_id,
                "target_start": round(target_start, 3),
                "target_end": round(max(target_start + 0.5, target_end), 3),
                "text": text,
            }
        )
    return moments


def _map_interval(seg: dict, timeline_segments: list[dict]) -> tuple[float, float, float]:
    from src.services.timeline_mapping_service import map_source_interval_to_target

    return map_source_interval_to_target(
        float(seg.get("start", 0)),
        float(seg.get("end", 0)),
        timeline_segments,
    )


def scene_changes_near_moments(
    scene_times: list[float],
    moments: list[dict[str, Any]],
    window: float = 4.0,
) -> list[dict[str, Any]]:
    """Привязать смены кадра к ближайшим фрагментам речи."""
    anchors: list[dict[str, Any]] = []
    for moment in moments:
        start = float(moment["target_start"])
        end = float(moment["target_end"])
        nearby = [t for t in scene_times if start - window <= t <= end + window]
        if nearby:
            anchors.append(
                {
                    "segment_id": moment["segment_id"],
                    "scene_time": round(nearby[0], 3),
                    "text": moment["text"][:120],
                }
            )
    return anchors


def rule_based_suggestions(moments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Резервные аннотации без LLM — по ключевым действиям в тексте."""
    suggestions: list[dict[str, Any]] = []
    ann_idx = 1

    for moment in moments:
        text_lower = moment["text"].lower()
        if not any(word in text_lower for word in ACTION_KEYWORDS):
            continue

        start = float(moment["target_start"])
        end = min(float(moment["target_end"]), start + 5.0)
        ann_type = (
            "zoom"
            if any(w in text_lower for w in ("миллион", "лимит", "доход", "сумм"))
            else "arrow"
        )
        label = _short_label(moment["text"])

        suggestions.append(
            _normalize_annotation(
                {
                    "annotation_id": f"ann_{ann_idx:03d}",
                    "type": ann_type,
                    "target_start": start,
                    "target_end": end,
                    "label": label,
                    "style": DEFAULT_STYLE.get(ann_type, DEFAULT_STYLE["arrow"]),
                    "linked_segment_id": moment["segment_id"],
                    "confidence": 0.72,
                    "requires_review": True,
                    "reason": "Предложение по ключевому действию в тексте (координаты — вручную)",
                    "placement_confirmed": False,
                    "anchor": None,
                }
            )
        )
        ann_idx += 1

    return suggestions


def parse_llm_suggestions(raw: str, moments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    import json

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM вернул не объект JSON")

    items = data.get("suggestions") or data.get("annotations") or []
    if not isinstance(items, list):
        raise ValueError("LLM JSON без списка suggestions")

    moment_by_id = {m["segment_id"]: m for m in moments}
    parsed: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        linked = str(item.get("linked_segment_id") or item.get("segment_id") or "")
        moment = moment_by_id.get(linked)
        if moment is None:
            continue
        start = float(item.get("target_start", moment["target_start"] if moment else 0))
        end = float(item.get("target_end", start + 4.0))
        start = max(float(moment["target_start"]), start)
        end = min(float(moment["target_end"]), end)
        if end - start < 0.3:
            continue
        ann_type = str(item.get("type") or item.get("suggested_type") or "arrow").strip().lower()
        ann_type = SUGGESTED_TYPE_MAP.get(ann_type, ann_type)
        if ann_type not in ANNOTATION_TYPES:
            ann_type = "arrow"
        confidence = float(item.get("confidence", 0.8))
        parsed.append(
            _normalize_annotation(
                {
                    "annotation_id": f"ann_{idx:03d}",
                    "type": ann_type,
                    "target_start": start,
                    "target_end": end,
                    "label": str(item.get("label") or item.get("text") or "Элемент 1С")[:120],
                    "style": str(item.get("style") or DEFAULT_STYLE.get(ann_type, "red_arrow")),
                    "linked_segment_id": linked or (moment["segment_id"] if moment else ""),
                    "speech_context": moment["text"],
                    "confidence": confidence,
                    "requires_review": True,
                    "reason": str(
                        item.get("reason") or "Предложение AI — укажите координаты вручную"
                    )[:240],
                    "placement_confirmed": False,
                    "anchor": None,
                }
            )
        )
    return parsed


def auto_approve(
    suggestions: list[dict[str, Any]], threshold: float = 0.85
) -> tuple[list[dict], list[dict]]:
    approved: list[dict] = []
    pending: list[dict] = []
    for item in suggestions:
        if item.get("requires_review") or float(item.get("confidence", 0)) < threshold:
            pending.append(item)
        else:
            approved.append({**item, "approved": True})
    if not approved and suggestions:
        approved = [{**suggestions[0], "approved": True}]
    return approved, pending


def _short_label(text: str, max_len: int = 80) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def _default_anchor(ann_type: str) -> dict[str, float]:
    if ann_type == "zoom":
        return {"x": 0.35, "y": 0.35, "width": 0.3, "height": 0.25}
    if ann_type == "highlight_rect":
        return {"x": 0.12, "y": 0.12, "width": 0.35, "height": 0.08}
    if ann_type == "callout":
        return {"x": 0.55, "y": 0.2, "width": 0.35, "height": 0.1}
    return {"x": 0.18, "y": 0.15, "width": 0.2, "height": 0.05}


def _normalize_annotation(item: dict[str, Any]) -> dict[str, Any]:
    start = max(0.0, float(item["target_start"]))
    end = max(start + 0.3, float(item["target_end"]))
    ann_type = str(item.get("type", "arrow")).lower()
    ann_type = SUGGESTED_TYPE_MAP.get(ann_type, ann_type)
    if ann_type not in ANNOTATION_TYPES:
        ann_type = "arrow"
    if ann_type == "frame":
        ann_type = "highlight_rect"

    placement_confirmed = bool(item.get("placement_confirmed", False))
    anchor_raw = item.get("anchor")
    normalized_anchor: dict[str, float] | None = None
    if isinstance(anchor_raw, dict) and placement_confirmed:
        normalized_anchor = {
            "x": _clamp01(float(anchor_raw.get("x", 0.2))),
            "y": _clamp01(float(anchor_raw.get("y", 0.2))),
            "width": _clamp01(float(anchor_raw.get("width", 0.2)), 0.0, 1.0),
            "height": _clamp01(float(anchor_raw.get("height", 0.08)), 0.0, 1.0),
        }

    out: dict[str, Any] = {
        "annotation_id": str(item.get("annotation_id", "ann_001")),
        "type": ann_type,
        "target_start": round(start, 3),
        "target_end": round(end, 3),
        "label": str(item.get("label", "")).strip()[:120],
        "speech_context": str(item.get("speech_context", "")),
        "style": str(item.get("style") or DEFAULT_STYLE.get(ann_type, "red_arrow")),
        "linked_segment_id": str(item.get("linked_segment_id", "")),
        "confidence": round(_clamp01(float(item.get("confidence", 0.8)), 0.0, 1.0), 3),
        "requires_review": bool(item.get("requires_review", True)),
        "reason": str(item.get("reason", ""))[:240],
        "placement_confirmed": placement_confirmed,
        "skipped": bool(item.get("skipped", False)),
    }
    # Не пишем null в JSON — схема не принимает null для number/object.
    if normalized_anchor is not None:
        out["anchor"] = normalized_anchor
    if ann_type == "arrow":
        direction = str(item.get("arrow_direction") or "left").lower()
        if direction not in {"top", "bottom", "left", "right"}:
            direction = "left"
        out["arrow_direction"] = direction
        ratio_raw = item.get("arrow_length_ratio")
        try:
            ratio = float(ratio_raw) if ratio_raw is not None else 0.08
        except (TypeError, ValueError):
            ratio = 0.08
        out["arrow_length_ratio"] = round(_clamp01(ratio, 0.01, 0.5), 4)
    frame_file = item.get("frame_file")
    if frame_file:
        out["frame_file"] = frame_file
    frame_error = item.get("frame_error")
    if frame_error:
        out["frame_error"] = str(frame_error)
    return out


def confirmed_suggestions(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in suggestions if s.get("placement_confirmed") and not s.get("skipped")]


def _clamp01(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
