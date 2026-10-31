"""Шаг 5 (v2): текст для озвучки параллельно субтитрам.

Два потока текста с одними таймингами:
- subtitle_text — для субтитров (из subtitle_timing)
- voiceover_text — только для TTS

Старый speech_script / cleanup не удаляются.
"""

from __future__ import annotations

import logging
from typing import Any

from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.orchestrator.pipeline_state import PipelineState

logger = logging.getLogger(__name__)

VOICEOVER_SCRIPT_FILE = "voiceover_script.json"
SUBTITLE_TIMING = "subtitle_timing.json"


def voiceover_script_ready(registry: ArtifactRegistry) -> bool:
    return registry.exists(VOICEOVER_SCRIPT_FILE)


def voiceover_script_fully_approved(registry: ArtifactRegistry) -> bool:
    if not voiceover_script_ready(registry):
        return False
    doc = registry.load_json(VOICEOVER_SCRIPT_FILE)
    return bool(doc.get("approved_subtitles")) and bool(doc.get("approved_voiceover"))


def voiceover_script_voiceover_approved(registry: ArtifactRegistry) -> bool:
    """Для шага 6 достаточно утверждённого текста озвучки (субтитры отдельно)."""
    if not voiceover_script_ready(registry):
        return False
    doc = registry.load_json(VOICEOVER_SCRIPT_FILE)
    return bool(doc.get("approved_voiceover"))


def run_voiceover_script_stage(job_id: str) -> PipelineState:
    """Подготовить dual-файл из субтитров (если ещё нет)."""
    from src.config import get_settings

    settings = get_settings()
    job_dir = settings.job_output_dir(job_id)
    registry = ArtifactRegistry(job_dir)
    state_data = registry.load_json("pipeline_state.json") if registry.exists("pipeline_state.json") else {}
    completed = list(state_data.get("stages_completed") or [])

    state = PipelineState(
        job_id=job_id,
        output_dir=str(job_dir),
        status=ArtifactStatus.RUNNING,
        stages_completed=completed,
        current_stage="voiceover_script",
        error=None,
    )
    registry.save_json("pipeline_state.json", state.to_dict())

    try:
        ensure_voiceover_script_from_subtitles(registry, job_id)
        # Этап «готов к правке», но completed в UI — когда оба утверждения
        if voiceover_script_fully_approved(registry) and "voiceover_script" not in completed:
            completed.append("voiceover_script")
        status = ArtifactStatus.COMPLETED if voiceover_script_fully_approved(registry) else ArtifactStatus.COMPLETED
        # needs_review через _stage_completed: not fully approved → not done → current/needs_review
        # Keep pipeline not-running so UI can edit
        if "voiceover_script" in completed and not voiceover_script_fully_approved(registry):
            completed = [s for s in completed if s != "voiceover_script"]
        state = PipelineState(
            job_id=job_id,
            output_dir=str(job_dir),
            status=ArtifactStatus.COMPLETED,
            stages_completed=completed,
            current_stage=None,
            error=None,
        )
        # Mark as needs human review via not being in completed until approvals
        _ = status
    except Exception as exc:
        logger.exception("Шаг 5 voiceover_script ошибка job=%s", job_id)
        state = PipelineState(
            job_id=job_id,
            output_dir=str(job_dir),
            status=ArtifactStatus.FAILED,
            stages_completed=completed,
            current_stage=None,
            error=str(exc),
        )
    registry.save_json("pipeline_state.json", state.to_dict())
    return state


def ensure_voiceover_script_from_subtitles(
    registry: ArtifactRegistry,
    job_id: str,
    *,
    force_resync: bool = False,
) -> dict[str, Any]:
    if not registry.exists(SUBTITLE_TIMING):
        raise FileNotFoundError("Сначала выполните шаг 4 — субтитры/блоки")

    timing = registry.load_json(SUBTITLE_TIMING)
    cues = list(timing.get("cues") or [])
    if voiceover_script_ready(registry) and not force_resync:
        doc = registry.load_json(VOICEOVER_SCRIPT_FILE)
        # подтянуть новые cue_id, сохранив voiceover_text где возможно
        by_id = {str(b.get("cue_id")): b for b in (doc.get("blocks") or [])}
        blocks = []
        structure_changed = False
        for cue in cues:
            cid = str(cue.get("cue_id") or "")
            prev = by_id.get(cid) or {}
            sub_text = str(cue.get("text") or "")
            vo_text = str(
                prev.get("voiceover_text") if prev.get("voiceover_text") is not None else sub_text
            )
            start = float(cue.get("start", 0))
            end = float(cue.get("end", 0))
            if (
                not prev
                or str(prev.get("subtitle_text") or "") != sub_text
                or float(prev.get("start", -1)) != start
                or float(prev.get("end", -1)) != end
            ):
                structure_changed = True
            blocks.append(
                {
                    "cue_id": cid,
                    "start": start,
                    "end": end,
                    "subtitle_text": sub_text,
                    "voiceover_text": vo_text,
                }
            )
        if len(blocks) != len(by_id):
            structure_changed = True
        doc["blocks"] = blocks
        # Не перезаписываем файл при каждом открытии редактора — только если блоки/тайминг изменились
        if structure_changed or force_resync:
            doc["updated_at"] = utc_now_iso()
            registry.save_json(VOICEOVER_SCRIPT_FILE, doc)
        return doc

    blocks = [
        {
            "cue_id": str(cue.get("cue_id") or ""),
            "start": float(cue.get("start", 0)),
            "end": float(cue.get("end", 0)),
            "subtitle_text": str(cue.get("text") or ""),
            "voiceover_text": str(cue.get("text") or ""),
        }
        for cue in cues
    ]
    doc = {
        "job_id": job_id,
        "version": "2.0.0",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "approved_subtitles": False,
        "approved_voiceover": False,
        "approved_subtitles_at": None,
        "approved_voiceover_at": None,
        "blocks": blocks,
        "note": "subtitle_text — для субтитров; voiceover_text — только для озвучки.",
    }
    registry.save_json(VOICEOVER_SCRIPT_FILE, doc)
    return doc


def get_voiceover_script_edit_payload(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    doc = ensure_voiceover_script_from_subtitles(registry, job_id)
    video = "edited_video.mp4" if registry.exists("edited_video.mp4") else "raw_video.mp4"
    if not registry.exists(video):
        raise FileNotFoundError("Нужно видео raw_video или edited_video")
    return {
        "job_id": job_id,
        "video_url": f"/jobs/{job_id}/artifacts/{video}",
        "video_filename": video,
        "approved_subtitles": bool(doc.get("approved_subtitles")),
        "approved_voiceover": bool(doc.get("approved_voiceover")),
        "blocks": doc.get("blocks") or [],
        "updated_at": doc.get("updated_at"),
        "fully_approved": voiceover_script_fully_approved(registry),
    }


def save_voiceover_script_edits(
    registry: ArtifactRegistry,
    job_id: str,
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    doc = ensure_voiceover_script_from_subtitles(registry, job_id)
    old_by_id = {str(b.get("cue_id")): b for b in (doc.get("blocks") or [])}
    by_id = {str(b.get("cue_id")): b for b in blocks if b.get("cue_id")}
    new_blocks = []
    subtitles_changed = False
    voiceover_changed = False
    for block in doc.get("blocks") or []:
        cid = str(block.get("cue_id") or "")
        incoming = by_id.get(cid) or {}
        old = old_by_id.get(cid) or {}
        sub = incoming.get("subtitle_text")
        vo = incoming.get("voiceover_text")
        new_sub = str(sub if sub is not None else block.get("subtitle_text") or "")
        new_vo = str(vo if vo is not None else block.get("voiceover_text") or "")
        if new_sub != str(old.get("subtitle_text") or ""):
            subtitles_changed = True
        if new_vo != str(old.get("voiceover_text") or ""):
            voiceover_changed = True
        new_blocks.append(
            {
                **block,
                "subtitle_text": new_sub,
                "voiceover_text": new_vo,
            }
        )
    doc["blocks"] = new_blocks
    doc["updated_at"] = utc_now_iso()
    # Снимаем утверждение только у той колонки, где реально изменили текст
    if subtitles_changed:
        doc["approved_subtitles"] = False
        doc["approved_subtitles_at"] = None
    if voiceover_changed:
        doc["approved_voiceover"] = False
        doc["approved_voiceover_at"] = None
    registry.save_json(VOICEOVER_SCRIPT_FILE, doc)

    # Синхронизировать текст субтитров в subtitle_timing (озвучка не трогает timing text при TTS из voiceover_script)
    if registry.exists(SUBTITLE_TIMING):
        timing = registry.load_json(SUBTITLE_TIMING)
        text_by_id = {str(b["cue_id"]): b["subtitle_text"] for b in new_blocks}
        for cue in timing.get("cues") or []:
            cid = str(cue.get("cue_id") or "")
            if cid in text_by_id:
                cue["text"] = text_by_id[cid]
        from src.services.subtitle_service import build_srt_content

        registry.save_json(SUBTITLE_TIMING, timing, "subtitle_timing.schema.json")
        registry.artifact_path("subtitles.srt").write_text(
            build_srt_content(list(timing.get("cues") or [])),
            encoding="utf-8",
        )

    _sync_pipeline_completion(registry, job_id)
    return get_voiceover_script_edit_payload(registry, job_id)


def approve_voiceover_script_part(
    registry: ArtifactRegistry,
    job_id: str,
    *,
    part: str,
) -> dict[str, Any]:
    if part not in ("subtitles", "voiceover"):
        raise ValueError("part должен быть subtitles или voiceover")
    doc = ensure_voiceover_script_from_subtitles(registry, job_id)
    now = utc_now_iso()
    if part == "subtitles":
        doc["approved_subtitles"] = True
        doc["approved_subtitles_at"] = now
    else:
        doc["approved_voiceover"] = True
        doc["approved_voiceover_at"] = now
    doc["updated_at"] = now
    registry.save_json(VOICEOVER_SCRIPT_FILE, doc)
    _sync_pipeline_completion(registry, job_id)
    return get_voiceover_script_edit_payload(registry, job_id)


def _sync_pipeline_completion(registry: ArtifactRegistry, job_id: str) -> None:
    if not registry.exists("pipeline_state.json"):
        return
    state = registry.load_json("pipeline_state.json")
    completed = list(state.get("stages_completed") or [])
    if voiceover_script_fully_approved(registry):
        if "voiceover_script" not in completed:
            completed.append("voiceover_script")
    else:
        completed = [s for s in completed if s != "voiceover_script"]
    state["stages_completed"] = completed
    registry.save_json("pipeline_state.json", state)
