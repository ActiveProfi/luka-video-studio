"""Построение timeline_map.json из решений по таймингу."""

from __future__ import annotations

from typing import Any

from src.domain.contracts import utc_now_iso
from src.domain.enums import ArtifactStatus, PipelineStage


def load_review_resolutions(registry) -> dict[str, str]:
    if not registry.exists("review_resolution.json"):
        return {}
    data = registry.load_json("review_resolution.json")
    return {
        item["review_id"]: item["final_decision"]
        for item in data.get("resolutions", [])
        if item.get("review_id") and item.get("final_decision")
    }


def effective_decision(
    decision: dict[str, Any],
    review_id: str | None,
    resolutions: dict[str, str],
) -> str:
    if review_id and review_id in resolutions:
        resolved = resolutions[review_id]
        if resolved == "keep_as_is":
            return "keep_as_is"
        return resolved
    return str(decision.get("decision", "keep_as_is"))


def build_timeline_map(
    job_id: str,
    duration: float,
    decisions: list[dict[str, Any]],
    review_id_by_candidate: dict[str, str] | None = None,
    resolutions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Собрать timeline_map с полным покрытием исходного видео."""
    review_id_by_candidate = review_id_by_candidate or {}
    resolutions = resolutions or {}

    remove_intervals: list[tuple[float, float, str, float | None]] = []
    for idx, decision in enumerate(decisions):
        candidate_id = decision.get("candidate_id", f"cand_{idx + 1:03d}")
        review_id = review_id_by_candidate.get(candidate_id)
        final = effective_decision(decision, review_id, resolutions)
        start = float(decision.get("target_start", 0))
        end = float(decision.get("target_end", 0))
        if end <= start:
            continue
        if final == "remove_audio_video":
            remove_intervals.append((start, end, "removed", None))
        elif final == "trim_soft":
            trim_amount = min(1.5, (end - start) * 0.3)
            remove_intervals.append((start, end, "trim_soft", trim_amount))
        elif final == "speedup_video":
            remove_intervals.append((start, end, "speedup_video", 2.0))

    remove_intervals.sort(key=lambda x: x[0])

    segments: list[dict[str, Any]] = []
    target_time = 0.0
    source_cursor = 0.0
    segment_index = 0

    def append_segment(
        source_start: float,
        source_end: float,
        transform: str,
        speed_factor: float | None = 1.0,
        trim_removed_seconds: float = 0.0,
    ) -> None:
        nonlocal segment_index, target_time
        if source_end <= source_start:
            return
        source_len = source_end - source_start
        if transform == "removed":
            target_end = target_time
            speed = None
        elif transform == "trim_soft":
            target_end = target_time + max(0.0, source_len - trim_removed_seconds)
            speed = 1.0
        elif transform == "speedup_video" and speed_factor:
            target_end = target_time + source_len / speed_factor
            speed = speed_factor
        else:
            target_end = target_time + source_len
            speed = 1.0

        segments.append(
            {
                "segment_index": segment_index,
                "source_start": round(source_start, 3),
                "source_end": round(source_end, 3),
                "target_start": round(target_time, 3),
                "target_end": round(target_end, 3),
                "transform": transform,
                "speed_factor": speed,
                "trim_removed_seconds": round(trim_removed_seconds, 3),
            }
        )
        segment_index += 1
        target_time = target_end

    for start, end, transform, param in remove_intervals:
        if source_cursor < start:
            append_segment(source_cursor, start, "keep")
        if transform == "removed":
            append_segment(start, end, "removed")
        elif transform == "trim_soft":
            append_segment(start, end, "trim_soft", trim_removed_seconds=float(param or 0))
        elif transform == "speedup_video":
            append_segment(start, end, "speedup_video", speed_factor=float(param or 2.0))
        source_cursor = max(source_cursor, end)

    if source_cursor < duration:
        append_segment(source_cursor, duration, "keep")

    if not segments:
        append_segment(0.0, duration, "keep")

    target_duration = segments[-1]["target_end"] if segments else duration
    return {
        "job_id": job_id,
        "stage": PipelineStage.TIMELINE_MAP.value,
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "source_artifacts": ["timing_decisions.json", "review_resolution.json"],
        "status": ArtifactStatus.COMPLETED.value,
        "confidence_summary": 1.0,
        "warnings": [],
        "errors": [],
        "source_duration_seconds": round(duration, 3),
        "target_duration_seconds": round(target_duration, 3),
        "segments": segments,
    }


def rebuild_timeline_map(registry, job_id: str, duration: float) -> dict[str, Any]:
    decisions = registry.load_json("timing_decisions.json").get("decisions", [])
    review_id_by_candidate: dict[str, str] = {}
    if registry.exists("review_bundle.json"):
        for item in registry.load_json("review_bundle.json").get("items", []):
            cid = item.get("candidate_id")
            rid = item.get("review_id")
            if cid and rid:
                review_id_by_candidate[cid] = rid
    resolutions = load_review_resolutions(registry)
    timeline = build_timeline_map(job_id, duration, decisions, review_id_by_candidate, resolutions)
    registry.save_json("timeline_map.json", timeline, "timeline_map.schema.json")
    return timeline
