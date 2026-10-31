"""Ручная проверка и правка текста после распознавания речи."""

from __future__ import annotations

import asyncio
from typing import Any

from src.config import Settings, get_settings

from src.domain.contracts import utc_now_iso
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.segment_timing_service import (
    count_timing_steps,
    join_segments_text,
    realign_clean_segments_preserving_edits,
    segments_from_full_text,
    segments_need_timing_realign,
    split_text_into_time_blocks,
)
from src.services.speech_timing_service import build_segment_timing_info
from src.services.text_improvement_service import improve_segment_text_async
from src.services.tts_preparation_pipeline import (
    SPEECH_SCRIPT_FILE,
    TTS_PREPARATION_REPORT,
    run_tts_preparation_pipeline_async,
)

REVIEW_FILENAME = "cleanup_review.json"


def cleanup_artifacts_ready(registry: ArtifactRegistry) -> bool:
    return registry.exists("clean_transcript.json") and registry.exists("edits_map.json")


def load_cleanup_review(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    if registry.exists(REVIEW_FILENAME):
        return registry.load_json(REVIEW_FILENAME)
    if cleanup_artifacts_ready(registry):
        return create_pending_cleanup_review(registry, job_id)
    return {
        "job_id": job_id,
        "stage": "speech_cleanup_review",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "status": "pending",
        "approved_at": None,
        "approved_by": None,
        "manual_edits_count": 0,
        "last_saved_at": None,
    }


def create_pending_cleanup_review(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    data = {
        "job_id": job_id,
        "stage": "speech_cleanup_review",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "status": "pending",
        "approved_at": None,
        "approved_by": None,
        "manual_edits_count": 0,
        "last_saved_at": None,
    }
    registry.save_json(REVIEW_FILENAME, data, "cleanup_review.schema.json")
    return data


def cleanup_review_approved(registry: ArtifactRegistry, job_id: str) -> bool:
    if not cleanup_artifacts_ready(registry):
        return False
    review = load_cleanup_review(registry, job_id)
    return review.get("status") == "approved"


def get_cleanup_edit_payload(registry: ArtifactRegistry, job_id: str) -> dict[str, Any]:
    if not cleanup_artifacts_ready(registry):
        raise FileNotFoundError("Сначала подготовьте текст для редактирования")

    clean = registry.load_json("clean_transcript.json")
    review = load_cleanup_review(registry, job_id)
    source_segments = list(clean.get("segments", []))
    duration = float(clean.get("duration_seconds") or 0.0)
    if not duration and source_segments:
        duration = max(float(seg.get("end", 0.0)) for seg in source_segments)

    should_realign = bool(source_segments) and (
        segments_need_timing_realign(source_segments, duration=duration)
        or (not clean.get("timing_aligned") and len(source_segments) >= 2)
    )
    if should_realign:
        source_segments = realign_clean_segments_preserving_edits(
            source_segments,
            duration=duration or None,
        )
        clean["segments"] = source_segments
        clean["timing_aligned"] = True
        realign_note = (
            "Блоки пересобраны по таймингу исходника (равное число шагов в блоках одной длины)."
        )
        warnings = list(clean.get("warnings") or [])
        if realign_note not in warnings:
            warnings.append(realign_note)
        clean["warnings"] = warnings
        registry.save_json("clean_transcript.json", clean, "clean_transcript.schema.json")

    segments = []
    for seg in source_segments:
        text = str(seg.get("text", ""))
        original = str(seg.get("original_text", "") or text)
        timing = build_segment_timing_info(
            float(seg["start"]),
            float(seg["end"]),
            text,
            original_text=original,
        )
        segments.append(
            {
                "segment_id": seg["segment_id"],
                "start": seg["start"],
                "end": seg["end"],
                "text": text,
                "original_text": original,
                **timing,
            }
        )
    full_text = join_segments_text(source_segments, "text")
    full_original = join_segments_text(source_segments, "original_text") or full_text
    total_budget = count_timing_steps(full_original or full_text)
    block_markers = [
        {
            "segment_id": seg["segment_id"],
            "start": seg["start"],
            "end": seg["end"],
            "budget_steps": max(
                1,
                count_timing_steps(str(seg.get("original_text") or seg.get("text", ""))),
            ),
        }
        for seg in segments
    ]
    speech_script_text: str | None = None
    speech_script_ready = False
    prep_status: str = "not_ready"
    text_before = full_original
    timing_fit_done = False
    timing_fit_report: dict[str, Any] | None = None
    if registry.exists(SPEECH_SCRIPT_FILE):
        script = registry.load_json(SPEECH_SCRIPT_FILE)
        speech_script_text = str(script.get("text_after") or script.get("text") or "").strip() or None
        speech_script_ready = bool(speech_script_text)
        prep_status = str(script.get("status") or "ok")
        if script.get("trust_level") == "needs_user_review" or prep_status == "needs_review":
            prep_status = "needs_review"
        text_before = str(script.get("text_before") or "").strip() or full_original
        timing_fit_done = bool(script.get("timing_fit_done"))
        if isinstance(script.get("timing_fit_report"), dict):
            timing_fit_report = script.get("timing_fit_report")
    editor_text = speech_script_text or full_text
    return {
        "job_id": job_id,
        "review_status": review.get("status", "pending"),
        "manual_edits_count": review.get("manual_edits_count", 0),
        "last_saved_at": review.get("last_saved_at"),
        "approved_at": review.get("approved_at"),
        "duration_seconds": duration,
        "full_text": full_text,
        "full_original_text": full_original,
        "text_before": text_before,
        "speech_script_text": speech_script_text,
        "speech_script_ready": speech_script_ready,
        "prep_status": prep_status,
        "timing_fit_done": timing_fit_done,
        "timing_fit_report": timing_fit_report,
        "editor_text": editor_text,
        "total_budget_steps": total_budget,
        "block_markers": block_markers,
        "segments": segments,
    }


def ensure_speech_script_prepared(
    registry: ArtifactRegistry,
    job_id: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Автоматически подготовить Speech Script после распознавания, если его ещё нет."""
    if not cleanup_artifacts_ready(registry):
        return None
    if registry.exists(SPEECH_SCRIPT_FILE):
        return None
    if cleanup_review_approved(registry, job_id):
        return None
    payload = get_cleanup_edit_payload(registry, job_id)
    full_text = str(payload.get("full_text") or "").strip()
    if not full_text:
        return None
    return improve_full_text_with_ai(registry, job_id, full_text=full_text, settings=settings)


def save_manual_cleanup_edits(
    registry: ArtifactRegistry,
    job_id: str,
    segments: list[dict[str, Any]],
    saved_by: str = "user",
) -> dict[str, Any]:
    if not cleanup_artifacts_ready(registry):
        raise FileNotFoundError("Текст для редактирования не найден")

    review = load_cleanup_review(registry, job_id)
    clean = registry.load_json("clean_transcript.json")
    clean_segments = clean.get("segments", [])
    by_id = {item["segment_id"]: item for item in segments if item.get("segment_id")}
    expected_ids = {seg["segment_id"] for seg in clean_segments}
    missing_ids = expected_ids - set(by_id.keys())
    if missing_ids:
        raise ValueError(
            f"Не переданы все блоки текста ({len(missing_ids)} пропущено). "
            "Обновите страницу и сохраните снова."
        )
    manual_changes = 0

    for seg in clean_segments:
        seg_id = seg["segment_id"]
        if seg_id not in by_id:
            continue
        new_text = str(by_id[seg_id].get("text", "")).strip()
        if not new_text:
            raise ValueError(f"Сегмент {seg_id}: текст не может быть пустым")
        if new_text != seg.get("text"):
            manual_changes += 1
        seg["text"] = new_text

    review["last_saved_at"] = utc_now_iso()
    if manual_changes:
        review["status"] = "pending"
        review["approved_at"] = None
        review["approved_by"] = None
        review["manual_edits_count"] = int(review.get("manual_edits_count", 0)) + manual_changes
        registry.artifact_path(TTS_PREPARATION_REPORT).unlink(missing_ok=True)
        registry.artifact_path(SPEECH_SCRIPT_FILE).unlink(missing_ok=True)

    registry.save_json("clean_transcript.json", clean, "clean_transcript.schema.json")
    registry.save_json(REVIEW_FILENAME, review, "cleanup_review.schema.json")
    clean["timing_aligned"] = True
    return get_cleanup_edit_payload(registry, job_id)


def save_full_text_cleanup_edits(
    registry: ArtifactRegistry,
    job_id: str,
    full_text: str,
    saved_by: str = "user",
) -> dict[str, Any]:
    """Сохранить единый текст: автоматически нарезать на тайм-блоки для озвучки."""
    if not cleanup_artifacts_ready(registry):
        raise FileNotFoundError("Текст для редактирования не найден")

    # Если Speech Script уже есть — правки идут только в него, clean_transcript не портим.
    if registry.exists(SPEECH_SCRIPT_FILE):
        return save_speech_script_edits(registry, job_id, full_text, saved_by=saved_by)

    review = load_cleanup_review(registry, job_id)
    clean = registry.load_json("clean_transcript.json")
    source_segments = list(clean.get("segments", []))
    duration = float(clean.get("duration_seconds") or 0.0)
    if not duration and source_segments:
        duration = max(float(seg.get("end", 0.0)) for seg in source_segments)
    if duration <= 0:
        raise ValueError("Неизвестна длительность урока")

    old_joined = join_segments_text(source_segments, "text")
    new_text = str(full_text or "").strip()
    if not new_text:
        raise ValueError("Текст урока не может быть пустым")

    new_segments = segments_from_full_text(new_text, source_segments, duration=duration)
    manual_changes = 1 if new_text != old_joined else 0

    clean["segments"] = new_segments
    clean["timing_aligned"] = True
    review["last_saved_at"] = utc_now_iso()
    if manual_changes:
        review["status"] = "pending"
        review["approved_at"] = None
        review["approved_by"] = None
        review["manual_edits_count"] = int(review.get("manual_edits_count", 0)) + manual_changes

    registry.save_json("clean_transcript.json", clean, "clean_transcript.schema.json")
    registry.save_json(REVIEW_FILENAME, review, "cleanup_review.schema.json")
    return get_cleanup_edit_payload(registry, job_id)


_TIMING_FIT_UNSET = object()


def _build_speech_script_document(
    registry: ArtifactRegistry,
    job_id: str,
    script_text: str,
    *,
    status: str = "ok",
    confidence: float = 0.9,
    trust_level: str = "manual_reviewed",
    changes_count: int | None = None,
    audit_result: dict[str, Any] | None = None,
    tts_provider: str | None = None,
    substep: str = "preparation",
    timing_fit_done: bool | object = _TIMING_FIT_UNSET,
    timing_fit_report: dict[str, Any] | None | object = _TIMING_FIT_UNSET,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Собрать Speech Script: text_before / text_after + блоки без разрезания слов."""
    payload = get_cleanup_edit_payload(registry, job_id)
    source_segments = list(payload.get("segments") or [])
    text_before = str(payload.get("full_original_text") or payload.get("full_text") or "").strip()
    text_before_from_clean = str(payload.get("full_text") or "").strip() or text_before
    prev_timing_fit = False
    prev_timing_report: dict[str, Any] | None = None
    # При повторном сохранении не теряем исходный «текст до».
    if registry.exists(SPEECH_SCRIPT_FILE):
        prev = registry.load_json(SPEECH_SCRIPT_FILE)
        prev_before = str(prev.get("text_before") or "").strip()
        if prev_before:
            text_before_from_clean = prev_before
        prev_timing_fit = bool(prev.get("timing_fit_done"))
        if isinstance(prev.get("timing_fit_report"), dict):
            prev_timing_report = prev.get("timing_fit_report")
    script_text = str(script_text or "").strip()
    if not script_text:
        raise ValueError("Speech Script не может быть пустым")

    script_segments = segments_from_full_text(
        script_text,
        source_segments,
        duration=float(payload.get("duration_seconds") or 0.0),
    )
    # На сегментах явно фиксируем до/после.
    for seg in script_segments:
        before = str(seg.get("text_before") or seg.get("original_text") or "").strip()
        after = str(seg.get("text_after") or seg.get("text") or "").strip()
        seg["text_before"] = before
        seg["text_after"] = after
        seg["original_text"] = before
        seg["text"] = after

    # None/False/True передаём явно; _UNSET — сохранить прошлое (ручное сохранение).
    final_timing_fit = prev_timing_fit if timing_fit_done is _TIMING_FIT_UNSET else bool(timing_fit_done)
    final_timing_report = (
        prev_timing_report if timing_fit_report is _TIMING_FIT_UNSET else timing_fit_report
    )

    doc: dict[str, Any] = {
        "job_id": job_id,
        "stage": "speech_script",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["clean_transcript.json", TTS_PREPARATION_REPORT],
        "status": status,
        "confidence": confidence,
        "trust_level": trust_level,
        "tts_provider": tts_provider or (get_settings()).tts_provider,
        "text_before": text_before_from_clean,
        "text_after": script_text,
        "text": script_text,
        "segments": script_segments,
        "changes_count": changes_count,
        "audit_result": audit_result or {},
        "substep": substep,
        "timing_fit_done": final_timing_fit,
        "timing_fit_report": final_timing_report,
    }
    if extra:
        doc.update(extra)
    return doc


def save_speech_script_edits(
    registry: ArtifactRegistry,
    job_id: str,
    speech_script_text: str,
    saved_by: str = "user",
) -> dict[str, Any]:
    """Сохранить финальный Speech Script без изменения clean_transcript."""
    if not cleanup_artifacts_ready(registry):
        raise FileNotFoundError("Текст для редактирования не найден")

    review = load_cleanup_review(registry, job_id)
    script_text = str(speech_script_text or "").strip()
    if not script_text:
        raise ValueError("Speech Script не может быть пустым")

    old_text = ""
    if registry.exists(SPEECH_SCRIPT_FILE):
        prev_script = registry.load_json(SPEECH_SCRIPT_FILE)
        old_text = str(prev_script.get("text_after") or prev_script.get("text") or "")

    speech_script = _build_speech_script_document(
        registry,
        job_id,
        script_text,
        status="ok",
        confidence=0.9,
        trust_level="manual_reviewed",
        audit_result={"approved": True, "notes": f"Сохранено вручную: {saved_by}"},
    )
    registry.save_json(SPEECH_SCRIPT_FILE, speech_script)

    review["last_saved_at"] = utc_now_iso()
    if script_text != old_text:
        review["status"] = "pending"
        review["approved_at"] = None
        review["approved_by"] = None
        review["manual_edits_count"] = int(review.get("manual_edits_count", 0)) + 1
    registry.save_json(REVIEW_FILENAME, review, "cleanup_review.schema.json")
    return get_cleanup_edit_payload(registry, job_id) | {
        "speech_script_text": script_text,
        "speech_script_ready": True,
        "editor_text": script_text,
    }


def improve_full_text_with_ai(
    registry: ArtifactRegistry,
    job_id: str,
    *,
    full_text: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Запустить техническую подготовку текста к озвучке (без автосохранения clean_transcript)."""
    payload = get_cleanup_edit_payload(registry, job_id)
    current = str(full_text if full_text is not None else payload.get("full_text", "")).strip()
    if not current:
        raise ValueError("Текст урока пустой")

    cfg = settings or get_settings()
    result = asyncio.run(
        run_tts_preparation_pipeline_async(
            cfg,
            job_id=job_id,
            full_text=current,
            full_original=str(payload.get("full_original_text") or ""),
        )
    )
    registry.save_json(TTS_PREPARATION_REPORT, result)
    script_text = str(result.get("full_text") or result.get("text") or "").strip()
    speech_script = _build_speech_script_document(
        registry,
        job_id,
        script_text,
        status=str(result.get("status") or "ok"),
        confidence=float(result.get("confidence") or 0.0),
        trust_level=str(result.get("trust_level") or "needs_user_review"),
        changes_count=len(result.get("changes") or []),
        audit_result=result.get("audit_result") or {},
        tts_provider=cfg.tts_provider,
        substep="preparation",
        timing_fit_done=False,
        timing_fit_report=None,
    )
    registry.save_json(SPEECH_SCRIPT_FILE, speech_script)

    # Фиксируем, что результат подготовки сохранён (иначе UI считает, что «не сохранено»).
    review = load_cleanup_review(registry, job_id)
    review["last_saved_at"] = utc_now_iso()
    if review.get("status") == "approved":
        review["status"] = "pending"
        review["approved_at"] = None
        review["approved_by"] = None
    registry.save_json(REVIEW_FILENAME, review, "cleanup_review.schema.json")

    improved_steps = count_timing_steps(script_text)
    return {
        "text": script_text,
        "full_text": script_text,
        "text_before": speech_script.get("text_before"),
        "text_after": script_text,
        "notes": result.get("notes", ""),
        "provider": result.get("provider"),
        "budget_steps": payload.get("total_budget_steps"),
        "improved_steps": improved_steps,
        "budget_matched": result.get("budget_matched", True),
        "budget_exceeded": result.get("budget_exceeded", False),
        "attempts": 0,
        "analysis_summary": result.get("audit_result", {}).get("notes", ""),
        "issues_found": result.get("issues_found", 0),
        "changes_applied": result.get("changes_applied", []),
        "changes": result.get("changes", []),
        "duration_report": result.get("duration_report", []),
        "audit_result": result.get("audit_result", {}),
        "status": result.get("status", "ok"),
        "confidence": result.get("confidence", 0.0),
        "trust_level": result.get("trust_level", "needs_user_review"),
        "agent": "tts_preparation_pipeline",
        "phases": result.get("phases"),
        "speech_script_ready": True,
        "timing_fit_done": False,
        "timing_fit_report": None,
        "substep": "preparation",
    }


def fit_speech_script_timing_with_ai(
    registry: ArtifactRegistry,
    job_id: str,
    *,
    full_text: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Подшаг 3.2: ИИ-помощник подгоняет уже готовый Speech Script под тайминг озвучки."""
    from src.agents.voiceover_text_rewrite_agent import fit_voiceover_timing

    if not cleanup_artifacts_ready(registry):
        raise FileNotFoundError("Сначала выполните подготовку текста")
    if not registry.exists(SPEECH_SCRIPT_FILE):
        raise FileNotFoundError("Сначала подготовьте Speech Script (подшаг 3.1)")

    payload = get_cleanup_edit_payload(registry, job_id)
    existing = registry.load_json(SPEECH_SCRIPT_FILE)
    draft = str(
        full_text
        if full_text is not None
        else existing.get("text_after") or existing.get("text") or payload.get("speech_script_text") or ""
    ).strip()
    if not draft:
        raise ValueError("Speech Script пустой — нечего подгонять под тайминг")

    original = str(
        existing.get("text_before")
        or payload.get("text_before")
        or payload.get("full_original_text")
        or payload.get("full_text")
        or ""
    ).strip()
    duration = float(payload.get("duration_seconds") or 0.0)
    budget_steps = int(payload.get("total_budget_steps") or count_timing_steps(original or draft))
    budget_steps = max(1, budget_steps)
    cfg = settings or get_settings()
    llm_cfg = cfg.model_copy(
        update={
            "llm_provider": cfg.cleanup_improve_llm_provider,
            "llm_fallback_order": cfg.cleanup_improve_llm_fallback_order,
            "openai_llm_model": cfg.cleanup_improve_openai_llm_model,
        }
    )

    timing, provider = asyncio.run(
        fit_voiceover_timing(
            llm_cfg,
            draft_text=draft,
            original_text=original,
            duration=duration,
            budget_steps=budget_steps,
            segments=list(payload.get("segments") or []),
        )
    )
    fitted_text = str(timing.get("text") or draft).strip()
    if not fitted_text:
        raise ValueError("ИИ-помощник вернул пустой Speech Script")

    # Страховка: снова применить правила озвучки (аббревиатуры/числа), затем добить точный бюджет.
    from src.services.speech_script_step_tuner import fine_tune_to_exact_steps
    from src.services.tts_normalization_rules import apply_tts_normalization_rules

    normalized, _norm_changes = apply_tts_normalization_rules(fitted_text, cfg)
    fitted_text = fine_tune_to_exact_steps(normalized or fitted_text, budget_steps)
    if count_timing_steps(fitted_text) != budget_steps:
        raise ValueError(
            f"После нормализации озвучки тайминг снова разъехался: "
            f"{count_timing_steps(fitted_text)} вместо {budget_steps}"
        )

    timing_report = {
        "budget_steps": budget_steps,
        "improved_steps": count_timing_steps(fitted_text),
        "budget_matched": True,
        "budget_exceeded": False,
        "attempts": timing.get("attempts", 0),
        "notes": timing.get("notes", ""),
        "provider": provider,
        "draft_steps": count_timing_steps(draft),
        "tts_normalization_reapplied": bool(_norm_changes),
    }
    speech_script = _build_speech_script_document(
        registry,
        job_id,
        fitted_text,
        status="ok" if timing_report["budget_matched"] else "needs_review",
        confidence=0.92 if timing_report["budget_matched"] else 0.7,
        trust_level="manual_reviewed" if timing_report["budget_matched"] else "needs_user_review",
        changes_count=1 if fitted_text != draft else 0,
        audit_result={
            "approved": True,
            "notes": "Подшаг 3.2: Speech Script подогнан под тайминг озвучки",
        },
        tts_provider=cfg.tts_provider,
        substep="timing_fit",
        timing_fit_done=True,
        timing_fit_report=timing_report,
    )
    registry.save_json(SPEECH_SCRIPT_FILE, speech_script)

    review = load_cleanup_review(registry, job_id)
    review["last_saved_at"] = utc_now_iso()
    if review.get("status") == "approved":
        review["status"] = "pending"
        review["approved_at"] = None
        review["approved_by"] = None
    registry.save_json(REVIEW_FILENAME, review, "cleanup_review.schema.json")

    return {
        "text": fitted_text,
        "full_text": fitted_text,
        "text_before": speech_script.get("text_before"),
        "text_after": fitted_text,
        "notes": timing_report.get("notes", ""),
        "provider": provider,
        "budget_steps": timing_report["budget_steps"],
        "improved_steps": timing_report["improved_steps"],
        "budget_matched": timing_report["budget_matched"],
        "budget_exceeded": timing_report["budget_exceeded"],
        "attempts": timing_report.get("attempts", 0),
        "status": speech_script["status"],
        "speech_script_ready": True,
        "timing_fit_done": True,
        "timing_fit_report": timing_report,
        "substep": "timing_fit",
        "agent": "speech_script_timing_assistant",
    }


def improve_cleanup_segment_with_ai(
    registry: ArtifactRegistry,
    job_id: str,
    segment_id: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Улучшить один блок текста через LLM (без сохранения в файл — только ответ для UI)."""
    payload = get_cleanup_edit_payload(registry, job_id)
    segment = next((item for item in payload["segments"] if item["segment_id"] == segment_id), None)
    if segment is None:
        raise ValueError(f"Блок {segment_id} не найден")

    cfg = settings or get_settings()
    result = asyncio.run(improve_segment_text_async(cfg, segment))
    return {
        "segment_id": segment_id,
        "text": result["text"],
        "notes": result.get("notes", ""),
        "provider": result.get("provider"),
        "budget_steps": result.get("budget_steps"),
        "improved_steps": result.get("improved_steps"),
        "budget_matched": result.get("budget_matched", True),
        "budget_exceeded": result.get("budget_exceeded", False),
        "attempts": result.get("attempts"),
    }


def improve_all_cleanup_segments_with_ai(
    registry: ArtifactRegistry,
    job_id: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Улучшить все блоки по очереди (ответ для UI, без автосохранения)."""
    payload = get_cleanup_edit_payload(registry, job_id)
    cfg = settings or get_settings()
    improved: list[dict[str, Any]] = []
    for segment in payload["segments"]:
        seg_id = segment["segment_id"]
        try:
            result = asyncio.run(improve_segment_text_async(cfg, segment))
            improved.append(
                {
                    "segment_id": seg_id,
                    "text": result["text"],
                    "notes": result.get("notes", ""),
                    "provider": result.get("provider"),
                    "budget_steps": result.get("budget_steps"),
                    "improved_steps": result.get("improved_steps"),
                    "budget_matched": result.get("budget_matched", True),
                    "budget_exceeded": result.get("budget_exceeded", False),
                    "attempts": result.get("attempts"),
                }
            )
        except Exception as exc:
            improved.append(
                {
                    "segment_id": seg_id,
                    "error": str(exc),
                    "text": segment.get("text", ""),
                }
            )
    return {"segments": improved}


def approve_cleanup_review(
    registry: ArtifactRegistry,
    job_id: str,
    segments: list[dict[str, Any]] | None = None,
    *,
    full_text: str | None = None,
    approved_by: str = "user",
) -> dict[str, Any]:
    if full_text is not None:
        save_full_text_cleanup_edits(registry, job_id, full_text, saved_by=approved_by)
    elif segments:
        save_manual_cleanup_edits(registry, job_id, segments, saved_by=approved_by)

    if not cleanup_artifacts_ready(registry):
        raise FileNotFoundError("Текст для редактирования не найден")

    review = load_cleanup_review(registry, job_id)
    review["status"] = "approved"
    review["approved_at"] = utc_now_iso()
    review["approved_by"] = approved_by
    registry.save_json(REVIEW_FILENAME, review, "cleanup_review.schema.json")
    return get_cleanup_edit_payload(registry, job_id)
