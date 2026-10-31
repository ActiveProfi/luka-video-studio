"""Просмотр и настройка области субтитров на видео."""

from __future__ import annotations

from typing import Any

from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.subtitle_service import (
    SUBTITLE_LAYOUT,
    assign_global_cue_ids,
    build_srt_content,
    default_subtitle_layout,
    fill_cue_timeline_gaps,
    has_duplicate_cue_ids,
    timeline_has_gaps,
)

SUBTITLE_TIMING = "subtitle_timing.json"
SUBTITLES_SRT = "subtitles.srt"

FONT_SIZE_MIN = 8
FONT_SIZE_MAX = 14


def _normalize_cue_layouts(raw: Any) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, float]] = {}
    for cue_id, box in raw.items():
        if not isinstance(box, dict):
            continue
        try:
            result[str(cue_id)] = {
                "x": round(max(0.0, min(1.0, float(box.get("x", 0)))), 4),
                "y": round(max(0.0, min(1.0, float(box.get("y", 0)))), 4),
                "width": round(max(0.05, min(1.0, float(box.get("width", 0.2)))), 4),
                "height": round(max(0.04, min(1.0, float(box.get("height", 0.1)))), 4),
            }
        except (TypeError, ValueError):
            continue
    return result


def _normalize_hex_color(value: Any, default: str) -> str:
    raw = str(value or default).strip().lower()
    if not raw.startswith("#"):
        raw = f"#{raw}"
    if len(raw) == 7 and all(c in "0123456789abcdef#" for c in raw):
        return raw
    return default.lower()


def _style_fields(raw: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    font = int(raw.get("font_size_px", base["font_size_px"]))
    font = max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, font))
    opacity = float(raw.get("background_opacity", base.get("background_opacity", 0.72)))
    opacity = max(0.0, min(1.0, opacity))
    return {
        "font_size_px": font,
        "alignment": str(raw.get("alignment", base["alignment"])),
        "font_color": _normalize_hex_color(raw.get("font_color"), base["font_color"]),
        "background_color": _normalize_hex_color(
            raw.get("background_color"), base["background_color"]
        ),
        "background_opacity": round(opacity, 2),
        "font_bold": bool(raw.get("font_bold", base.get("font_bold", False))),
        "font_italic": bool(raw.get("font_italic", base.get("font_italic", False))),
        "cue_layouts": _normalize_cue_layouts(raw.get("cue_layouts", base.get("cue_layouts", {}))),
    }


def _normalize_layout(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Привести layout к нормализованной рамке x/y/width/height (0..1)."""
    base = default_subtitle_layout()
    if not raw:
        return base
    if all(key in raw for key in ("x", "y", "width", "height")):
        return {
            **base,
            **{k: float(raw[k]) for k in ("x", "y", "width", "height")},
            **_style_fields(raw, base),
        }
    width = float(raw.get("max_width_ratio", raw.get("width", base["width"])))
    height = float(raw.get("height", base["height"]))
    x = (1.0 - width) / 2.0
    margin = float(raw.get("margin_bottom_px", 48)) / 1080.0
    if str(raw.get("position", "bottom")) == "bottom":
        y = max(0.05, 1.0 - height - margin)
    else:
        y = 0.08
    return {
        "x": round(x, 4),
        "y": round(y, 4),
        "width": round(width, 4),
        "height": round(height, 4),
        **_style_fields(raw, base),
    }


def subtitles_edit_ready(registry: ArtifactRegistry) -> bool:
    return registry.exists(SUBTITLES_SRT) and registry.exists(SUBTITLE_TIMING)


def get_subtitle_edit_payload(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    if not subtitles_edit_ready(registry):
        raise FileNotFoundError("Сначала выполните шаг 6 — субтитры")

    timing = registry.load_json(SUBTITLE_TIMING)
    layout_raw = registry.load_json(SUBTITLE_LAYOUT) if registry.exists(SUBTITLE_LAYOUT) else None
    layout = _normalize_layout(layout_raw)

    raw_cues = list(timing.get("cues", []))
    if has_duplicate_cue_ids(raw_cues):
        raw_cues = assign_global_cue_ids(raw_cues)

    total_duration = float(timing.get("total_duration_seconds") or 0)
    if total_duration <= 0 and raw_cues:
        total_duration = max(float(c.get("end", 0) or 0) for c in raw_cues)

    if raw_cues and total_duration > 0 and timeline_has_gaps(raw_cues, total_duration):
        raw_cues = fill_cue_timeline_gaps(raw_cues, total_duration)
        timing["cues"] = raw_cues
        timing["cue_count"] = len(raw_cues)
        timing["total_duration_seconds"] = round(total_duration, 3)
        registry.save_json(SUBTITLE_TIMING, timing, "subtitle_timing.schema.json")
        registry.artifact_path(SUBTITLES_SRT).write_text(
            build_srt_content(raw_cues), encoding="utf-8"
        )

    cues = [
        {
            "cue_id": str(c.get("cue_id", "")),
            "source_segment_id": str(c.get("source_segment_id", "")),
            "start": float(c.get("start", 0)),
            "end": float(c.get("end", 0)),
            "text": str(c.get("text", "")),
        }
        for c in raw_cues
    ]

    video_path = "edited_video.mp4" if registry.exists("edited_video.mp4") else "raw_video.mp4"
    if not registry.exists(video_path):
        raise FileNotFoundError("Нужен edited_video.mp4 или raw_video.mp4")

    video_file = registry.artifact_path(video_path)
    video_version = str(int(video_file.stat().st_mtime)) if video_file.exists() else None

    final_voiceover = None
    if registry.exists("final_voiceover_report.json"):
        report = registry.load_json("final_voiceover_report.json")
        final_voiceover = {
            "ok": bool(report.get("ok")),
            "message": report.get("message"),
            "segment_count": report.get("segment_count"),
            "created_at": report.get("created_at"),
            "warnings": list(report.get("warnings") or []),
        }

    return {
        "job_id": job_id,
        "video_url": f"/jobs/{job_id}/artifacts/{video_path}",
        "video_filename": video_path,
        "video_version": video_version,
        "cue_count": len(cues),
        "total_duration_seconds": total_duration,
        "layout": layout,
        "cues": cues,
        "last_saved_at": layout_raw.get("updated_at") if isinstance(layout_raw, dict) else None,
        "final_voiceover": final_voiceover,
    }


def save_subtitle_layout(
    registry: ArtifactRegistry,
    job_id: str,
    layout: dict[str, Any],
    *,
    saved_by: str = "user",
) -> dict[str, Any]:
    if not subtitles_edit_ready(registry):
        raise FileNotFoundError("Сначала выполните шаг 6 — субтитры")

    normalized = _normalize_layout(layout)
    payload = {
        **normalized,
        "job_id": job_id,
        "updated_at": utc_now_iso(),
        "saved_by": saved_by,
    }
    registry.save_json(SUBTITLE_LAYOUT, payload)
    return get_subtitle_edit_payload(registry, job_id)


def save_subtitle_cue_texts(
    registry: ArtifactRegistry,
    job_id: str,
    cue_updates: list[dict[str, Any]],
    *,
    saved_by: str = "user",
) -> dict[str, Any]:
    """Сохранить текст и/или полный список блоков (можно добавлять пустые на паузы)."""
    if not subtitles_edit_ready(registry):
        raise FileNotFoundError("Сначала выполните шаг 6 — субтитры")

    timing = registry.load_json(SUBTITLE_TIMING)
    total_duration = float(timing.get("total_duration_seconds") or 0)
    existing = list(timing.get("cues") or [])

    has_bounds = bool(cue_updates) and all(
        item.get("start") is not None and item.get("end") is not None for item in cue_updates
    )
    existing_spans = {
        (round(float(c.get("start", 0)), 3), round(float(c.get("end", 0)), 3)) for c in existing
    }
    update_spans = {
        (round(float(c["start"]), 3), round(float(c["end"]), 3)) for c in cue_updates
    } if has_bounds else set()
    # Полный список с новой сеткой (добавление/разрез). Частичный апдейт текста — старый путь.
    full_replace = (
        has_bounds
        and len(cue_updates) >= max(1, len(existing))
        and (len(cue_updates) != len(existing) or update_spans != existing_spans)
    )

    if full_replace:
        updated_cues: list[dict[str, Any]] = []
        for item in cue_updates:
            start = max(0.0, float(item["start"]))
            end = max(start + 0.05, float(item["end"]))
            updated_cues.append(
                {
                    "cue_id": str(item.get("cue_id") or ""),
                    "source_segment_id": str(item.get("source_segment_id") or ""),
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": str(item.get("text") or ""),
                }
            )
        updated_cues.sort(key=lambda c: (c["start"], c["end"]))
        if total_duration <= 0 and updated_cues:
            total_duration = float(updated_cues[-1]["end"])
        updated_cues = fill_cue_timeline_gaps(updated_cues, total_duration)
        changed = len(updated_cues)
    else:
        by_composite: dict[tuple[str, str], str] = {}
        by_time: dict[tuple[float, float], str] = {}
        by_id: dict[str, str] = {}
        for item in cue_updates:
            text = str(item.get("text", "")).strip()
            cue_id = str(item.get("cue_id", ""))
            seg_id = str(item.get("source_segment_id", ""))
            if seg_id and cue_id:
                by_composite[(seg_id, cue_id)] = text
            if item.get("start") is not None and item.get("end") is not None:
                by_time[(round(float(item["start"]), 3), round(float(item["end"]), 3))] = text
            elif cue_id:
                by_id[cue_id] = text
        if not (by_composite or by_time or by_id):
            raise ValueError("Нет данных для сохранения текста субтитров")

        def _resolve_new_text(cue: dict[str, Any]) -> str | None:
            seg_id = str(cue.get("source_segment_id", ""))
            cue_id = str(cue.get("cue_id", ""))
            start = round(float(cue.get("start", 0)), 3)
            end = round(float(cue.get("end", 0)), 3)
            if seg_id and cue_id and (seg_id, cue_id) in by_composite:
                return by_composite[(seg_id, cue_id)]
            if (start, end) in by_time:
                return by_time[(start, end)]
            if cue_id in by_id:
                return by_id[cue_id]
            return None

        updated_cues = []
        changed = 0
        for cue in timing.get("cues", []):
            new_text = _resolve_new_text(cue)
            if new_text is not None:
                if str(cue.get("text", "")).strip() != new_text:
                    changed += 1
                updated_cues.append({**cue, "text": new_text})
            else:
                updated_cues.append(cue)
        if has_duplicate_cue_ids(updated_cues):
            updated_cues = assign_global_cue_ids(updated_cues)

    timing["cues"] = updated_cues
    timing["cue_count"] = len(updated_cues)
    if total_duration > 0:
        timing["total_duration_seconds"] = round(total_duration, 3)
    timing["text_edited_at"] = utc_now_iso()
    timing["text_edited_by"] = saved_by
    timing["voiceover_unchanged"] = True
    registry.save_json(SUBTITLE_TIMING, timing, "subtitle_timing.schema.json")

    srt_content = build_srt_content(updated_cues)
    registry.artifact_path(SUBTITLES_SRT).write_text(srt_content, encoding="utf-8")

    payload = get_subtitle_edit_payload(registry, job_id)
    payload["text_changes_saved"] = changed
    return payload


def save_subtitle_edits(
    registry: ArtifactRegistry,
    job_id: str,
    *,
    layout: dict[str, Any] | None = None,
    cues: list[dict[str, Any]] | None = None,
    saved_by: str = "user",
) -> dict[str, Any]:
    if layout:
        save_subtitle_layout(registry, job_id, layout, saved_by=saved_by)
    if cues:
        save_subtitle_cue_texts(registry, job_id, cues, saved_by=saved_by)
    if not layout and not cues:
        raise ValueError("Нечего сохранять")

    # Видео с прожитыми субтитрами для шага 7 (студия аннотаций).
    from src.services.subtitle_burn_service import ensure_subtitled_studio_video

    ensure_subtitled_studio_video(registry, force=True)

    return get_subtitle_edit_payload(registry, job_id)
