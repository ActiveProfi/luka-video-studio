"""Тесты Timing Decision Agent."""

import pytest

from src.agents.timing_decision_agent import run_timing_decision
from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry


@pytest.fixture
def timing_job(tmp_path):
    job_dir = tmp_path / "job_timing"
    job_dir.mkdir()
    registry = ArtifactRegistry(job_dir)

    registry.save_json(
        "cleanup_review.json",
        {
            "job_id": "job_timing",
            "stage": "speech_cleanup_review",
            "version": "1.0.0",
            "created_at": "2026-06-20T10:00:00Z",
            "status": "approved",
            "approved_at": "2026-06-20T10:01:00Z",
            "approved_by": "user",
            "manual_edits_count": 0,
            "last_saved_at": "2026-06-20T10:01:00Z",
        },
        "cleanup_review.schema.json",
    )
    registry.save_json(
        "clean_transcript.json",
        {
            "job_id": "job_timing",
            "stage": "speech_cleanup",
            "version": "1.0.0",
            "created_at": "2026-06-20T10:00:00Z",
            "source_artifacts": ["transcript.json"],
            "status": "completed",
            "language": "ru",
            "duration_seconds": 62.0,
            "segments": [
                {
                    "segment_id": "seg_001",
                    "start": 0.0,
                    "end": 25.0,
                    "text": "Открываем главное меню и переходим в отчёты.",
                    "original_text": "Открываем главное меню",
                    "edit_ids": [],
                },
                {
                    "segment_id": "seg_002",
                    "start": 28.5,
                    "end": 55.0,
                    "text": "Проверяем доходы компании за полугодие.",
                    "original_text": "Проверяем доходы",
                    "edit_ids": [],
                },
            ],
        },
        "clean_transcript.schema.json",
    )
    registry.save_json(
        "edits_map.json",
        {
            "job_id": "job_timing",
            "stage": "speech_cleanup",
            "version": "1.0.0",
            "created_at": "2026-06-20T10:00:00Z",
            "source_artifacts": ["transcript.json"],
            "status": "completed",
            "edits": [],
        },
        "edits_map.schema.json",
    )

    settings = Settings(output_dir=tmp_path)
    return registry, settings, "job_timing"


def test_timing_decision_creates_artifacts(timing_job):
    registry, settings, job_id = timing_job
    result = run_timing_decision(registry, settings, job_id)

    assert registry.exists("pause_candidates.json")
    assert registry.exists("visual_activity_map.json")
    assert registry.exists("semantic_action_map.json")
    assert registry.exists("timing_decisions.json")
    assert registry.exists("timeline_map.json")
    assert "decisions" in result

    candidates = registry.load_json("pause_candidates.json")["candidates"]
    assert len(candidates) >= 1
    assert candidates[0]["start"] == pytest.approx(25.0)
    assert candidates[0]["end"] == pytest.approx(28.5)

    timeline = registry.load_json("timeline_map.json")
    assert timeline["source_duration_seconds"] == pytest.approx(62.0)
    assert timeline["target_duration_seconds"] <= timeline["source_duration_seconds"]
