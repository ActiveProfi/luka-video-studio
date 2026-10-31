"""Этап 2 архитектуры v3: пользователь пишет субтитры прямо на видео.

Единственный источник текста для всех следующих этапов — эти субтитры.
Никаких отдельных окон редактирования текста и никакой транскрибации здесь нет.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from src.config import Settings, get_settings
from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.media_paths import resolve_raw_video_path
from src.services.subtitle_service import (
    SUBTITLE_LAYOUT,
    build_srt_content,
    default_subtitle_layout,
)
from src.services.timeblock_service import (
    STATUS_EDITED,
    STATUS_EMPTY,
    STATUS_SAVED,
    TIME_BLOCKS_FILE,
    build_time_blocks,
    filled_block_count,
    load_time_blocks,
)
from src.services.video_probe_service import get_video_meta

logger = logging.getLogger(__name__)

SUBTITLES_SRT = "subtitles.srt"
SUBTITLE_TIMING = "subtitle_timing.json"


def cue_id_for_block(block_id: Any) -> str:
    try:
        return f"cue_{int(block_id):04d}"
    except (TypeError, ValueError):
        return f"cue_{str(block_id)}"


def subtitles_text_hash(registry: ArtifactRegistry) -> str | None:
    """Хеш субтитров — по нему видно, устарела ли озвучка."""
    if not registry.exists(TIME_BLOCKS_FILE):
        return None
    doc = registry.load_json(TIME_BLOCKS_FILE)
    payload = "\n".join(
        f"{b.get('id')}|{b.get('start')}|{b.get('end')}|{str(b.get('subtitle') or '').strip()}"
        for b in doc.get("blocks") or []
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _video_version(registry: ArtifactRegistry) -> str | None:
    try:
        path = resolve_raw_video_path(registry)
        return str(int(path.stat().st_mtime))
    except Exception:
        return None


def get_capture_payload(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    """Данные для основного экрана: видео + блоки + оформление субтитра."""
    doc = load_time_blocks(registry, job_id)
    meta = get_video_meta(registry, job_id)
    layout = (
        registry.load_json(SUBTITLE_LAYOUT)
        if registry.exists(SUBTITLE_LAYOUT)
        else default_subtitle_layout()
    )
    video_name = resolve_raw_video_path(registry).name
    blocks = [
        {
            "id": b.get("id"),
            "start": float(b.get("start") or 0.0),
            "end": float(b.get("end") or 0.0),
            "subtitle": str(b.get("subtitle") or ""),
            "status": str(b.get("status") or STATUS_EMPTY),
            "needs_review": bool(b.get("needs_review")),
            "review_reason": b.get("review_reason", ""),
        }
        for b in doc.get("blocks") or []
    ]
    return {
        "job_id": job_id,
        "video_url": f"/jobs/{job_id}/artifacts/{video_name}",
        "video_filename": video_name,
        "video_version": _video_version(registry),
        "duration_seconds": float(doc.get("duration_seconds") or meta.get("duration_seconds") or 0.0),
        "fps": meta.get("fps"),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "has_audio": bool(meta.get("has_audio")),
        "layout": layout,
        "blocks": blocks,
        "block_count": len(blocks),
        "filled_count": filled_block_count(doc),
        "saved_at": doc.get("saved_at"),
        "updated_at": doc.get("updated_at"),
        "script_review": registry.load_json("script_review_report.json") if registry.exists("script_review_report.json") else None,
    }


def _store(registry: ArtifactRegistry, doc: dict[str, Any]) -> None:
    doc["updated_at"] = utc_now_iso()
    registry.save_json(TIME_BLOCKS_FILE, doc)


def save_subtitle_blocks(
    registry: ArtifactRegistry,
    job_id: str,
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Промежуточное сохранение текста без завершения этапа."""
    doc = load_time_blocks(registry, job_id)
    incoming = {str(b.get("id")): str(b.get("subtitle") or "") for b in blocks}
    changed = 0
    for block in doc.get("blocks") or []:
        key = str(block.get("id"))
        if key not in incoming:
            continue
        new_text = incoming[key].strip()
        if new_text != str(block.get("subtitle") or "").strip():
            changed += 1
            block["needs_review"] = False
            block["review_reason"] = ""
        block["subtitle"] = new_text
        block["status"] = STATUS_EDITED if new_text else STATUS_EMPTY

    if changed:
        # Текст изменился — прежнее «Сохранить» больше не действует, озвучку надо пересобрать
        doc["saved_at"] = None
        from src.services.stage_reset_service import clear_from_ui_stage, update_pipeline_state_after_clear

        clear_from_ui_stage(registry, "voiceover", include_self=True)
        update_pipeline_state_after_clear(registry, "voiceover", include_self=True)
    _store(registry, doc)
    payload = get_capture_payload(registry, job_id)
    payload["changed_count"] = changed
    return payload


def split_block(
    registry: ArtifactRegistry,
    job_id: str,
    block_id: int,
    at_seconds: float,
) -> dict[str, Any]:
    """Разделить блок в указанной секунде — если текст не помещается в один субтитр."""
    doc = load_time_blocks(registry, job_id)
    blocks = list(doc.get("blocks") or [])
    target = next((b for b in blocks if str(b.get("id")) == str(block_id)), None)
    if target is None:
        raise ValueError(f"Блок {block_id} не найден")

    start = float(target.get("start") or 0.0)
    end = float(target.get("end") or 0.0)
    cut = float(at_seconds)
    if not (start + 0.4 <= cut <= end - 0.4):
        raise ValueError("Точка разделения должна быть внутри блока (не ближе 0.4 с к краям)")

    text = str(target.get("subtitle") or "").strip()
    target["end"] = round(cut, 3)
    target["subtitle"] = text
    target["status"] = STATUS_EDITED if text else STATUS_EMPTY
    new_block = {
        "id": 0,
        "start": round(cut, 3),
        "end": round(end, 3),
        "subtitle": "",
        "status": STATUS_EMPTY,
    }
    index = blocks.index(target)
    blocks.insert(index + 1, new_block)
    doc["blocks"] = _renumber(blocks)
    doc["saved_at"] = None
    doc["source"] = "auto_split+manual"
    _store(registry, doc)
    return get_capture_payload(registry, job_id)


def merge_block_with_next(
    registry: ArtifactRegistry,
    job_id: str,
    block_id: int,
) -> dict[str, Any]:
    """Склеить блок со следующим — если фраза оказалась разорванной."""
    doc = load_time_blocks(registry, job_id)
    blocks = list(doc.get("blocks") or [])
    target = next((b for b in blocks if str(b.get("id")) == str(block_id)), None)
    if target is None:
        raise ValueError(f"Блок {block_id} не найден")
    index = blocks.index(target)
    if index + 1 >= len(blocks):
        raise ValueError("Это последний блок — склеивать не с чем")

    nxt = blocks[index + 1]
    texts = [
        str(target.get("subtitle") or "").strip(),
        str(nxt.get("subtitle") or "").strip(),
    ]
    merged_text = " ".join(t for t in texts if t)
    target["end"] = round(float(nxt.get("end") or 0.0), 3)
    target["subtitle"] = merged_text
    target["status"] = STATUS_EDITED if merged_text else STATUS_EMPTY
    blocks.pop(index + 1)
    doc["blocks"] = _renumber(blocks)
    doc["saved_at"] = None
    doc["source"] = "auto_split+manual"
    _store(registry, doc)
    return get_capture_payload(registry, job_id)


def _renumber(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(blocks, key=lambda b: float(b.get("start") or 0.0))
    for idx, block in enumerate(ordered, start=1):
        block["id"] = idx
    return ordered


def rebuild_blocks(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    """Пересобрать разбиение заново (текст блоков по возможности сохраняется)."""
    build_time_blocks(registry, job_id, force=True)
    return get_capture_payload(registry, job_id)


def finalize_subtitles(
    registry: ArtifactRegistry,
    job_id: str,
    blocks: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
    approved_by: str = "user",
) -> dict[str, Any]:
    """Кнопка «Сохранить»: текст становится источником для озвучки и аннотаций."""
    settings = settings or get_settings()
    current = load_time_blocks(registry, job_id)
    existing = {str(b.get("id")): str(b.get("subtitle") or "").strip()
                for b in current.get("blocks") or []}
    unchanged = not blocks or all(
        existing.get(str(b.get("id"))) == str(b.get("subtitle") or "").strip()
        for b in blocks
    )
    if current.get("saved_at") and unchanged and registry.exists(SUBTITLE_TIMING) and registry.exists(SUBTITLES_SRT):
        return get_capture_payload(registry, job_id)
    if blocks:
        save_subtitle_blocks(registry, job_id, blocks)

    doc = load_time_blocks(registry, job_id)
    filled = [b for b in doc.get("blocks") or [] if str(b.get("subtitle") or "").strip()]
    if not filled:
        raise ValueError("Впишите текст хотя бы в один блок — иначе озвучивать нечего")

    for block in doc.get("blocks") or []:
        if str(block.get("subtitle") or "").strip():
            block["status"] = STATUS_SAVED
        else:
            block["status"] = STATUS_EMPTY
    doc["saved_at"] = utc_now_iso()
    _store(registry, doc)

    _export_internal_subtitles(registry, job_id, doc, settings)
    if registry.exists("script_review_report.json"):
        report = registry.load_json("script_review_report.json")
        report["status"] = "approved"
        report["approved_by"] = approved_by
        report["approved_at"] = utc_now_iso()
        report["review_count"] = 0
        registry.save_json("script_review_report.json", report)
    payload = get_capture_payload(registry, job_id)
    payload["filled_count"] = len(filled)
    logger.info("Субтитры сохранены: %s блоков с текстом из %s", len(filled), len(doc.get("blocks") or []))
    return payload


def _export_internal_subtitles(
    registry: ArtifactRegistry,
    job_id: str,
    doc: dict[str, Any],
    settings: Settings,
) -> None:
    """Внутренние артефакты (srt + тайминг) для прожига, озвучки и аннотаций."""
    total_duration = float(doc.get("duration_seconds") or 0.0)
    cues: list[dict[str, Any]] = []
    for block in doc.get("blocks") or []:
        cues.append(
            {
                "cue_id": cue_id_for_block(block.get("id")),
                "source_segment_id": f"block_{block.get('id')}",
                "start": round(float(block.get("start") or 0.0), 3),
                "end": round(float(block.get("end") or 0.0), 3),
                "text": str(block.get("subtitle") or "").strip(),
            }
        )
    if total_duration <= 0 and cues:
        total_duration = max(c["end"] for c in cues)

    timing = {
        "job_id": job_id,
        "stage": "subtitles",
        "version": "3.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [TIME_BLOCKS_FILE],
        "status": "completed",
        "source": "user_subtitles",
        "language": settings.default_language,
        "total_duration_seconds": round(total_duration, 3),
        "cue_count": len(cues),
        "cues": cues,
        "warnings": [],
        "errors": [],
    }
    registry.save_json(SUBTITLE_TIMING, timing)
    registry.artifact_path(SUBTITLES_SRT).write_text(build_srt_content(cues), encoding="utf-8")
    if not registry.exists(SUBTITLE_LAYOUT):
        registry.save_json(SUBTITLE_LAYOUT, default_subtitle_layout())

    # Совместимость: аннотации и сборка урока читают clean_transcript.json.
    # Текста от распознавания речи больше нет — источником служат субтитры.
    segments = [
        {
            "segment_id": f"block_{b.get('id')}",
            "start": round(float(b.get("start") or 0.0), 3),
            "end": round(float(b.get("end") or 0.0), 3),
            "text": str(b.get("subtitle") or "").strip(),
            "original_text": str(b.get("subtitle") or "").strip(),
            "confidence": 1.0,
        }
        for b in doc.get("blocks") or []
        if str(b.get("subtitle") or "").strip()
    ]
    registry.save_json(
        "clean_transcript.json",
        {
            "job_id": job_id,
            "stage": "speech_cleanup",
            "version": "3.0.0",
            "created_at": utc_now_iso(),
            "source_artifacts": [TIME_BLOCKS_FILE],
            "status": "completed",
            "language": settings.default_language,
            "duration_seconds": round(total_duration, 3),
            "provider": "user_subtitles",
            "segments": segments,
        },
        "clean_transcript.schema.json",
    )


def save_layout(
    registry: ArtifactRegistry,
    job_id: str,
    layout: dict[str, Any],
) -> dict[str, Any]:
    """Оформление субтитра (размер, положение, цвет) — то же поле, что видит пользователь."""
    current = (
        registry.load_json(SUBTITLE_LAYOUT)
        if registry.exists(SUBTITLE_LAYOUT)
        else default_subtitle_layout()
    )
    changes = {k: v for k, v in layout.items() if v is not None}
    if all(current.get(k) == v for k, v in changes.items()):
        return get_capture_payload(registry, job_id)
    current.update(changes)
    registry.save_json(SUBTITLE_LAYOUT, current)
    # Оформление влияет только на рендер. Последний успешный ролик сохраняем.
    registry.save_json("render_pending.json", {"reason": "subtitle_style"})
    return get_capture_payload(registry, job_id)
