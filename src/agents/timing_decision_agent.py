"""Timing Decision Agent — этап 4: решения по таймингу (MVP)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, ConfidenceRouting, PipelineStage, TimingDecisionType
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.cleanup_review_service import cleanup_review_approved
from src.services.timeline_map_service import build_timeline_map
from src.services.video_analysis_service import (
    count_scene_changes_in_interval,
    detect_scene_change_times,
    detect_silence_intervals,
    resolve_media_for_analysis,
)

logger = logging.getLogger(__name__)

MIN_PAUSE_SECONDS = 1.0
MERGE_GAP_SECONDS = 0.4

ACTION_KEYWORDS = (
    "нажима",
    "открыва",
    "переход",
    "выбира",
    "ставим",
    "заполня",
    "провод",
    "смотрим",
    "проверя",
    "формир",
    "находим",
    "возвраща",
    "клика",
    "выбираем",
    "созда",
)


def run_timing_decision(
    registry: ArtifactRegistry,
    settings: Settings,
    job_id: str,
) -> dict[str, Any]:
    if registry.exists("timing_decisions.json") and registry.exists("timeline_map.json"):
        logger.info("timing_decisions.json уже существует, пропуск")
        return registry.load_json("timing_decisions.json")

    if not cleanup_review_approved(registry, job_id):
        raise ValueError("Сначала подтвердите текст на этапе «Редактирование текста»")

    if not registry.exists("clean_transcript.json"):
        raise FileNotFoundError("Нужен clean_transcript.json")

    clean = registry.load_json("clean_transcript.json")
    edits_map = registry.load_json("edits_map.json") if registry.exists("edits_map.json") else {"edits": []}
    segments = clean.get("segments", [])
    duration = float(clean.get("duration_seconds") or 0)

    media_path, media_duration = _resolve_media(registry, duration)
    if media_duration > duration:
        duration = media_duration

    warnings: list[str] = []
    if media_path is None:
        warnings.append("Видео/аудио для анализа не найдено — решения только по тексту транскрипта.")

    silence_intervals: list[tuple[float, float]] = []
    scene_times: list[float] = []
    if media_path:
        silence_intervals = detect_silence_intervals(media_path)
        if media_path.suffix.lower() in {".mp4", ".mov", ".webm"}:
            scene_times = detect_scene_change_times(media_path)
        logger.info(
            "Анализ медиа: тишина=%s интервалов, смен сцен=%s",
            len(silence_intervals),
            len(scene_times),
        )

    candidates = _build_pause_candidates(job_id, segments, edits_map, silence_intervals, duration, warnings)
    visual_items = _build_visual_activity(candidates, scene_times, media_path is not None, warnings)
    semantic_items = _build_semantic_actions(candidates, segments)
    decisions, review_items = _build_policy_decisions(
        candidates,
        visual_items,
        semantic_items,
        segments,
        settings,
    )

    confidences = [d["confidence"] for d in decisions if d.get("confidence") is not None]
    confidence_summary = round(sum(confidences) / len(confidences), 3) if confidences else 0.85
    needs_review_count = sum(1 for d in decisions if d.get("requires_review"))

    timing_status = (
        ArtifactStatus.NEEDS_REVIEW.value
        if needs_review_count
        else ArtifactStatus.COMPLETED.value
    )

    pause_candidates_doc = {
        "job_id": job_id,
        "stage": PipelineStage.TIMING_PAUSE_CANDIDATES.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["clean_transcript.json", "edits_map.json"],
        "status": ArtifactStatus.COMPLETED.value,
        "confidence_summary": confidence_summary,
        "warnings": warnings,
        "errors": [],
        "candidates": candidates,
    }
    visual_doc = {
        "job_id": job_id,
        "stage": PipelineStage.TIMING_VISUAL_ACTIVITY.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["pause_candidates.json"],
        "status": ArtifactStatus.COMPLETED.value,
        "confidence_summary": confidence_summary,
        "warnings": warnings,
        "errors": [],
        "items": visual_items,
    }
    semantic_doc = {
        "job_id": job_id,
        "stage": PipelineStage.TIMING_SEMANTIC_ACTION.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["pause_candidates.json", "clean_transcript.json"],
        "status": ArtifactStatus.COMPLETED.value,
        "confidence_summary": confidence_summary,
        "warnings": warnings,
        "errors": [],
        "items": semantic_items,
    }
    timing_decisions = {
        "job_id": job_id,
        "stage": PipelineStage.TIMING_POLICY.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": [
            "pause_candidates.json",
            "visual_activity_map.json",
            "semantic_action_map.json",
            "edits_map.json",
        ],
        "status": timing_status,
        "confidence_summary": confidence_summary,
        "warnings": warnings + ([f"{needs_review_count} intervals flagged for human review"] if needs_review_count else []),
        "errors": [],
        "decisions": decisions,
    }

    registry.save_json("pause_candidates.json", pause_candidates_doc)
    registry.save_json("visual_activity_map.json", visual_doc)
    registry.save_json("semantic_action_map.json", semantic_doc)
    registry.save_json("timing_decisions.json", timing_decisions, "timing_decisions.schema.json")

    review_id_by_candidate: dict[str, str] = {}
    if review_items:
        bundle = {
            "job_id": job_id,
            "stage": PipelineStage.TIMING_REVIEW_BUNDLE.value,
            "version": "1.0.0",
            "created_at": utc_now_iso(),
            "source_artifacts": ["timing_decisions.json"],
            "status": ArtifactStatus.PENDING.value,
            "confidence_summary": None,
            "warnings": [],
            "errors": [],
            "items": review_items,
        }
        registry.save_json("review_bundle.json", bundle, "review_bundle.schema.json")
        for item in review_items:
            review_id_by_candidate[item["candidate_id"]] = item["review_id"]

    timeline = build_timeline_map(job_id, duration, decisions, review_id_by_candidate, {})
    registry.save_json("timeline_map.json", timeline, "timeline_map.schema.json")

    logger.info(
        "Этап 4 завершён: кандидатов=%s, решений=%s, на согласование=%s",
        len(candidates),
        len(decisions),
        needs_review_count,
    )
    return timing_decisions


def _resolve_media(registry: ArtifactRegistry, fallback_duration: float) -> tuple[Path | None, float]:
    job_dir = registry.job_dir
    if registry.exists("raw_video.mp4"):
        path = registry.artifact_path("raw_video.mp4")
        _, dur = resolve_media_for_analysis(job_dir, registry.exists)
        return path, dur or fallback_duration
    upload = job_dir / "_upload" / "raw_video.mp4"
    if upload.exists():
        _, dur = resolve_media_for_analysis(job_dir, registry.exists)
        return upload, dur or fallback_duration
    if registry.exists("input_manifest.json"):
        manifest = registry.load_json("input_manifest.json")
        raw_path = Path(str(manifest.get("raw_video_path", "")))
        if raw_path.exists():
            _, dur = resolve_media_for_analysis(job_dir, registry.exists)
            return raw_path, dur or fallback_duration
    media_path, dur = resolve_media_for_analysis(job_dir, registry.exists)
    return media_path, dur or fallback_duration


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_intervals[0]]
    for start, end in sorted_intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + MERGE_GAP_SECONDS:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _build_pause_candidates(
    job_id: str,
    segments: list[dict],
    edits_map: dict[str, Any],
    silence_intervals: list[tuple[float, float]],
    duration: float,
    warnings: list[str],
) -> list[dict[str, Any]]:
    raw_intervals: list[tuple[float, float, str, list[str]]] = []

    for idx in range(len(segments) - 1):
        gap_start = float(segments[idx]["end"])
        gap_end = float(segments[idx + 1]["start"])
        if gap_end - gap_start >= MIN_PAUSE_SECONDS:
            linked = [segments[idx]["segment_id"], segments[idx + 1]["segment_id"]]
            raw_intervals.append((gap_start, gap_end, "segment_gap", linked))

    for edit in edits_map.get("edits", []):
        if edit.get("problem_type") == "long_pause":
            start = float(edit.get("source_start", 0))
            end = float(edit.get("source_end", start))
            if end - start >= MIN_PAUSE_SECONDS:
                raw_intervals.append(
                    (
                        start,
                        end,
                        "cleanup_long_pause",
                        edit.get("segment_ids", []),
                    )
                )

    for start, end in silence_intervals:
        if end - start >= MIN_PAUSE_SECONDS:
            linked = _segments_for_interval(segments, start, end)
            raw_intervals.append((start, end, "audio_silence", linked))

    if duration > 0 and segments:
        tail_start = float(segments[-1]["end"])
        if duration - tail_start >= MIN_PAUSE_SECONDS:
            raw_intervals.append(
                (
                    tail_start,
                    duration,
                    "tail_silence",
                    [segments[-1]["segment_id"]],
                )
            )

    merged = _merge_intervals([(s, e) for s, e, _, _ in raw_intervals])
    candidates: list[dict[str, Any]] = []
    for idx, (start, end) in enumerate(merged, start=1):
        sources = [reason for s, e, reason, _ in raw_intervals if not (e < start or s > end)]
        linked: list[str] = []
        for _, _, _, seg_ids in raw_intervals:
            if not (float(end) < start or float(start) > end):
                linked.extend(seg_ids)
        candidates.append(
            {
                "candidate_id": f"cand_{idx:03d}",
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
                "source": "+".join(sorted(set(sources))) or "heuristic",
                "reason": _primary_reason(sources),
                "linked_transcript_segments": sorted(set(linked)),
            }
        )

    if not candidates:
        warnings.append("Явные паузы не найдены — этап завершён с базовой картой времени.")
    return candidates


def _primary_reason(sources: list[str]) -> str:
    if any("silence" in s for s in sources):
        return "long_pause"
    if any("gap" in s for s in sources):
        return "segment_gap"
    if any("cleanup" in s for s in sources):
        return "cleanup_pause"
    return "long_pause"


def _segments_for_interval(segments: list[dict], start: float, end: float) -> list[str]:
    """Привязать паузу только к релевантным фрагментам речи."""
    linked: list[str] = []
    for idx, seg in enumerate(segments):
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        if seg_start <= start < seg_end or seg_start < end <= seg_end or (start <= seg_start and end >= seg_end):
            linked.append(seg["segment_id"])
            continue
        if idx + 1 < len(segments):
            gap_start = seg_end
            gap_end = float(segments[idx + 1]["start"])
            if end > gap_start and start < gap_end:
                linked.extend([seg["segment_id"], segments[idx + 1]["segment_id"]])
    return sorted(set(linked))


def _segments_overlapping(segments: list[dict], start: float, end: float) -> list[str]:
    return _segments_for_interval(segments, start, end)


def _build_visual_activity(
    candidates: list[dict],
    scene_times: list[float],
    has_video: bool,
    warnings: list[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for cand in candidates:
        start = float(cand["start"])
        end = float(cand["end"])
        duration = max(0.001, end - start)
        scene_count = count_scene_changes_in_interval(scene_times, start, end) if has_video else 0
        ui_change_score = min(1.0, scene_count / max(1.0, duration / 2.0))
        cursor_motion_score = min(1.0, scene_count / max(1.0, duration / 3.0))

        if not has_video:
            screen_state = "unknown"
            visual_event_type = "unknown_no_video"
            confidence = 0.55
        elif ui_change_score >= 0.35:
            screen_state = "active"
            visual_event_type = "ui_change"
            confidence = 0.82
        elif cursor_motion_score >= 0.2:
            screen_state = "cursor_motion"
            visual_event_type = "cursor_movement"
            confidence = 0.78
        else:
            screen_state = "mostly_static"
            visual_event_type = "no_meaningful_change"
            confidence = 0.91

        items.append(
            {
                "candidate_id": cand["candidate_id"],
                "screen_state": screen_state,
                "cursor_motion_score": round(cursor_motion_score, 3),
                "ui_change_score": round(ui_change_score, 3),
                "visual_event_type": visual_event_type,
                "confidence": confidence,
            }
        )

    if not has_video:
        warnings.append("Визуальный анализ пропущен — видеофайл недоступен.")
    return items


def _build_semantic_actions(
    candidates: list[dict],
    segments: list[dict],
) -> list[dict[str, Any]]:
    seg_by_id = {s["segment_id"]: s for s in segments}
    items: list[dict[str, Any]] = []

    for cand in candidates:
        linked_ids = cand.get("linked_transcript_segments", [])
        combined = _context_text_near_pause(cand, linked_ids, seg_by_id).lower()
        action_hits = [kw for kw in ACTION_KEYWORDS if kw in combined]
        position = _pause_position(cand, linked_ids, seg_by_id)
        critical = position in {"head", "tail"} and any(
            k in combined for k in ("нажима", "открыва", "созда", "провод", "ставим")
        )

        if action_hits and critical:
            relation = "pre_action_transition"
            related = "user_action"
            confidence = 0.72
        elif action_hits and position == "middle":
            relation = "between_actions"
            related = "navigation"
            confidence = 0.86
        elif action_hits:
            relation = "during_instruction"
            related = "navigation"
            confidence = 0.8
        else:
            relation = "between_actions"
            related = "none"
            confidence = 0.88

        domain_terms = _extract_domain_terms(combined)
        items.append(
            {
                "candidate_id": cand["candidate_id"],
                "instruction_relation": relation,
                "related_action_type": related,
                "critical_for_learning": critical,
                "domain_terms": domain_terms,
                "confidence": confidence,
            }
        )
    return items


def _extract_domain_terms(text: str) -> list[str]:
    terms = []
    for token in ("ндс", "1с", "отчёт", "отчет", "документ", "лимит", "доход"):
        if token in text and token not in terms:
            terms.append(token)
    return terms[:5]


def _build_policy_decisions(
    candidates: list[dict],
    visual_items: list[dict],
    semantic_items: list[dict],
    segments: list[dict],
    settings: Settings,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    visual_by_id = {item["candidate_id"]: item for item in visual_items}
    semantic_by_id = {item["candidate_id"]: item for item in semantic_items}
    seg_by_id = {s["segment_id"]: s for s in segments}

    decisions: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []

    for idx, cand in enumerate(candidates):
        visual = visual_by_id.get(cand["candidate_id"], {})
        semantic = semantic_by_id.get(cand["candidate_id"], {})
        duration = float(cand.get("duration", 0))

        decision, confidence, why, requires_review, routing, risk = _decide_single(
            cand,
            visual,
            semantic,
            duration,
            settings,
        )

        context = _context_transcript(cand, seg_by_id)
        evidence = {
            "visual_event_type": visual.get("visual_event_type", "unknown"),
            "instruction_relation": semantic.get("instruction_relation", "between_actions"),
            "critical_for_learning": bool(semantic.get("critical_for_learning")),
            "cursor_motion_score": visual.get("cursor_motion_score"),
            "ui_change_score": visual.get("ui_change_score"),
        }

        decisions.append(
            {
                "candidate_id": cand["candidate_id"],
                "decision": decision,
                "target_start": cand["start"],
                "target_end": cand["end"],
                "confidence": round(confidence, 3),
                "risk_level": risk,
                "routing": routing,
                "why": why,
                "requires_review": requires_review,
                "evidence": evidence,
            }
        )

        if requires_review:
            review_id = f"rev_{len(review_items) + 1:03d}"
            proposed = (
                TimingDecisionType.TRIM_SOFT.value
                if decision == TimingDecisionType.NEEDS_HUMAN_REVIEW.value
                else decision
            )
            review_items.append(
                {
                    "review_id": review_id,
                    "candidate_id": cand["candidate_id"],
                    "video_excerpt_start": max(0.0, float(cand["start"]) - 2.0),
                    "video_excerpt_end": float(cand["end"]) + 2.0,
                    "proposed_decision": proposed,
                    "alternative_decisions": [
                        TimingDecisionType.KEEP_AS_IS.value,
                        TimingDecisionType.TRIM_SOFT.value,
                        TimingDecisionType.SPEEDUP_VIDEO.value,
                    ],
                    "confidence": round(confidence, 3),
                    "routing": routing,
                    "reason_for_review": why,
                    "evidence": evidence,
                    "context_transcript": context,
                }
            )

    return decisions, review_items


def _decide_single(
    cand: dict,
    visual: dict,
    semantic: dict,
    duration: float,
    settings: Settings,
) -> tuple[str, float, str, bool, str, str]:
    visual_type = visual.get("visual_event_type", "unknown")
    critical = bool(semantic.get("critical_for_learning"))
    relation = semantic.get("instruction_relation", "between_actions")
    ui_score = float(visual.get("ui_change_score") or 0)
    cursor_score = float(visual.get("cursor_motion_score") or 0)

    if duration < 0.5:
        return (
            TimingDecisionType.KEEP_AS_IS.value,
            0.95,
            "Слишком короткий интервал — безопаснее оставить",
            False,
            ConfidenceRouting.AUTO_APPROVE.value,
            "low",
        )

    if visual_type == "no_meaningful_change" and relation == "between_actions":
        confidence = 0.93 if duration >= 1.2 else 0.88
        return (
            TimingDecisionType.REMOVE_AUDIO_VIDEO.value,
            confidence,
            "Пауза без значимых изменений на экране",
            False,
            ConfidenceRouting.AUTO_APPROVE.value,
            "low",
        )

    if visual_type == "no_meaningful_change" and duration >= 2.0 and not critical:
        return (
            TimingDecisionType.REMOVE_AUDIO_VIDEO.value,
            0.9,
            "Длинная статичная пауза — безопасно сократить",
            False,
            ConfidenceRouting.AUTO_APPROVE.value,
            "low",
        )

    if visual_type in {"ui_change", "cursor_movement"} or (critical and ui_score >= 0.2):
        confidence = 0.61 if ui_score >= 0.35 or critical else 0.68
        routing = ConfidenceRouting.REQUIRED_REVIEW.value
        if confidence >= settings.confidence_standard_review and not critical:
            routing = ConfidenceRouting.STANDARD_REVIEW.value
        return (
            TimingDecisionType.NEEDS_HUMAN_REVIEW.value,
            confidence,
            "Возможная связь паузы с действием на экране 1С — нужна проверка",
            True,
            routing,
            "medium" if not critical else "high",
        )

    if duration >= 2.5 and visual_type in {"unknown", "unknown_no_video"}:
        confidence = 0.76
        requires_review = confidence < settings.confidence_auto_approve
        routing = (
            ConfidenceRouting.STANDARD_REVIEW.value
            if requires_review
            else ConfidenceRouting.AUTO_APPROVE.value
        )
        return (
            TimingDecisionType.TRIM_SOFT.value,
            confidence,
            "Длинная пауза — мягкое сокращение (видео недоступно для точного анализа)",
            requires_review,
            routing,
            "medium",
        )

    confidence = 0.84
    return (
        TimingDecisionType.KEEP_AS_IS.value,
        confidence,
        "Пауза может быть частью демонстрации — оставляем",
        False,
        ConfidenceRouting.AUTO_APPROVE.value,
        "low",
    )


def _pause_position(
    cand: dict,
    linked_ids: list[str],
    seg_by_id: dict[str, dict],
) -> str:
    start = float(cand.get("start", 0))
    end = float(cand.get("end", 0))
    mid = (start + end) / 2.0
    for sid in linked_ids:
        seg = seg_by_id.get(sid)
        if not seg:
            continue
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        if seg_start <= mid <= seg_end:
            seg_len = max(0.001, seg_end - seg_start)
            rel = (mid - seg_start) / seg_len
            if rel >= 0.85:
                return "tail"
            if rel <= 0.15:
                return "head"
            return "middle"
    return "middle"


def _context_text_near_pause(
    cand: dict,
    linked_ids: list[str],
    seg_by_id: dict[str, dict],
) -> str:
    start = float(cand.get("start", 0))
    end = float(cand.get("end", 0))
    parts: list[str] = []
    for sid in linked_ids:
        seg = seg_by_id.get(sid)
        if not seg:
            continue
        text = str(seg["text"])
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        if end <= seg_start or start >= seg_end:
            parts.append(text[:120])
        elif start >= seg_start:
            parts.append(text[-120:])
        else:
            parts.append(text[:120])
    return " ".join(parts).strip()


def _context_transcript(cand: dict, seg_by_id: dict[str, dict]) -> str:
    text = _context_text_near_pause(cand, cand.get("linked_transcript_segments", []), seg_by_id)
    return text[:240]
