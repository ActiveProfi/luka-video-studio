"""Human review для этапа тайминга."""

from __future__ import annotations

from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.timeline_map_service import rebuild_timeline_map


def timing_artifacts_ready(registry: ArtifactRegistry) -> bool:
    return registry.exists("timing_decisions.json") and registry.exists("timeline_map.json")


def timing_pending_review_count(registry: ArtifactRegistry) -> int:
    if not registry.exists("timing_decisions.json"):
        return 0
    timing = registry.load_json("timing_decisions.json")
    pending_ids = {
        item.get("review_id")
        for item in _review_items(registry)
        if item.get("review_id")
    }
    if not pending_ids:
        return sum(1 for d in timing.get("decisions", []) if d.get("requires_review"))
    resolved_ids: set[str] = set()
    if registry.exists("review_resolution.json"):
        resolved_ids = {
            r.get("review_id")
            for r in registry.load_json("review_resolution.json").get("resolutions", [])
            if r.get("review_id")
        }
    return len(pending_ids - resolved_ids)


def timing_stage_completed(registry: ArtifactRegistry) -> bool:
    if not timing_artifacts_ready(registry):
        return False
    return timing_pending_review_count(registry) == 0


def _review_items(registry: ArtifactRegistry) -> list[dict]:
    if registry.exists("review_bundle.json"):
        return registry.load_json("review_bundle.json").get("items", [])
    timing = registry.load_json("timing_decisions.json")
    items = []
    for idx, dec in enumerate(timing.get("decisions", [])):
        if not dec.get("requires_review"):
            continue
        items.append({"review_id": f"rev_{idx + 1:03d}", "candidate_id": dec.get("candidate_id")})
    return items


def refresh_timeline_after_review(registry: ArtifactRegistry, job_id: str) -> None:
    if not timing_artifacts_ready(registry):
        return
    duration = float(registry.load_json("clean_transcript.json").get("duration_seconds", 0))
    if registry.exists("timeline_map.json"):
        duration = max(duration, float(registry.load_json("timeline_map.json").get("source_duration_seconds", 0)))
    rebuild_timeline_map(registry, job_id, duration)
