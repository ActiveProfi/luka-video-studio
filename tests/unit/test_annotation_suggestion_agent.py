"""Тесты этапа аннотаций."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.annotation_suggestion_agent import run_annotation_suggestions
from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry


@pytest.fixture
def registry_for_annotations(tmp_path):
    job_dir = tmp_path / "job_ann"
    job_dir.mkdir()
    registry = ArtifactRegistry(job_dir)
    (job_dir / "edited_video.mp4").write_bytes(b"fake")
    (job_dir / "edited_video.mp4").write_bytes(b"fake")
    (job_dir / "voiceover.wav").write_bytes(b"fake")
    (job_dir / "subtitles.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8")

    registry.save_json(
        "clean_transcript.json",
        {
            "job_id": "job_ann",
            "stage": "speech_cleanup",
            "version": "1.0.0",
            "created_at": "2026-06-21T10:00:00Z",
            "source_artifacts": [],
            "status": "completed",
            "segments": [
                {
                    "segment_id": "seg_001",
                    "text": "Открываем меню и находим отчёт по НДС.",
                    "start": 0,
                    "end": 8,
                }
            ],
        },
    )
    registry.save_json(
        "timeline_map.json",
        {
            "job_id": "job_ann",
            "stage": "video_edit",
            "version": "1.0.0",
            "created_at": "2026-06-21T10:00:00Z",
            "source_artifacts": [],
            "status": "completed",
            "target_duration_seconds": 20.0,
            "segments": [],
        },
    )
    registry.save_json(
        "voiceover_segments.json",
        {
            "job_id": "job_ann",
            "stage": "tts",
            "version": "1.0.0",
            "created_at": "2026-06-21T10:00:00Z",
            "source_artifacts": [],
            "status": "completed",
            "language": "ru",
            "total_duration_seconds": 20.0,
            "segments": [
                {
                    "segment_id": "tts_001",
                    "transcript_segment_id": "seg_001",
                    "text": "Открываем меню и находим отчёт по НДС.",
                    "target_start": 0.0,
                    "target_end": 8.0,
                    "audio_start": 0.0,
                    "audio_end": 7.5,
                }
            ],
        },
    )
    return registry


def test_run_annotation_suggestions_rule_based(registry_for_annotations):
    registry = registry_for_annotations
    settings = get_settings()

    with patch("src.agents.annotation_suggestion_agent.complete_with_fallback", new=AsyncMock(side_effect=RuntimeError("no llm"))):
        with patch("src.agents.annotation_suggestion_agent.detect_scene_change_times", return_value=[1.0, 5.0]):
            with patch("src.agents.annotation_suggestion_agent.render_annotation_preview") as render_mock:
                render_mock.return_value = registry.job_dir / "annotation_preview.mp4"
                (registry.job_dir / "annotation_preview.mp4").write_bytes(b"fake")
                doc = run_annotation_suggestions(registry, settings, "job_ann")

    assert registry.exists("annotation_suggestions.json")
    assert registry.exists("annotation_review.json")
    assert not registry.exists("approved_annotations.json")
    assert len(doc["suggestions"]) >= 1
    review = registry.load_json("annotation_review.json")
    assert review["status"] == "pending"
    assert len(review["blocks"]) >= 1
