"""Тесты сброса и перезапуска этапов."""

import pytest

from src.domain.enums import PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.cleanup_review_service import (
    approve_cleanup_review,
    cleanup_review_approved,
    create_pending_cleanup_review,
    save_manual_cleanup_edits,
)
from src.services.stage_reset_service import (
    RERUN_LABEL,
    RERUN_LABELS,
    reopen_cleanup_for_edit,
    reset_stage_for_rerun,
    stage_ui_actions,
    update_pipeline_state_after_clear,
)


@pytest.fixture
def registry_with_full_pipeline(tmp_path):
    job_dir = tmp_path / "job_full"
    job_dir.mkdir()
    registry = ArtifactRegistry(job_dir)

    registry.save_json("transcript.json", {"segments": [{"segment_id": "seg_001", "text": "test"}]})
    registry.save_json(
        "clean_transcript.json",
        {
            "job_id": "job_full", "stage": "speech_cleanup", "version": "1.0.0",
            "created_at": "2026-10-06T00:00:00Z", "source_artifacts": ["transcript.json"],
            "status": "completed", "language": "ru", "duration_seconds": 5.0,
            "segments": [
                {
                    "segment_id": "seg_001",
                    "start": 0.0,
                    "end": 5.0,
                    "text": "Открываем документ",
                }
            ]
        },
    )
    registry.save_json("edits_map.json", {"edits": []})
    create_pending_cleanup_review(registry, "job_full")
    approve_cleanup_review(registry, "job_full")

    registry.save_json("timing_decisions.json", {"decisions": []})
    registry.save_json("timeline_map.json", {"segments": []})
    (job_dir / "edited_video.mp4").write_bytes(b"fake-video")
    (job_dir / "voiceover.wav").write_bytes(b"fake-audio")
    registry.save_json("voiceover_segments.json", {"segments": []})

    registry.save_json(
        "pipeline_state.json",
        {
            "status": "completed",
            "stages_completed": [
                PipelineStage.TRANSCRIPTION.value,
                PipelineStage.SPEECH_CLEANUP.value,
                PipelineStage.TIMELINE_MAP.value,
                PipelineStage.VIDEO_EDIT.value,
                PipelineStage.TTS.value,
            ],
        },
    )
    return registry


def test_reopen_cleanup_clears_downstream_and_unapproves(registry_with_full_pipeline):
    registry = registry_with_full_pipeline
    assert cleanup_review_approved(registry, "job_full")
    assert registry.exists("voiceover.wav")

    payload = reopen_cleanup_for_edit(registry, "job_full")

    assert payload["review_status"] == "pending"
    assert not cleanup_review_approved(registry, "job_full")
    assert registry.exists("clean_transcript.json")
    assert not registry.exists("voiceover.wav")
    assert not registry.exists("timeline_map.json")
    assert not registry.exists("edited_video.mp4")


def test_reset_cleanup_preserves_manual_text(registry_with_full_pipeline):
    registry = registry_with_full_pipeline
    save_manual_cleanup_edits(
        registry,
        "job_full",
        [{"segment_id": "seg_001", "text": "Saved user edit"}],
    )
    approve_cleanup_review(registry, "job_full")

    reset_stage_for_rerun(registry, "job_full", "cleanup")

    saved = registry.load_json("clean_transcript.json")
    assert saved["segments"][0]["text"] == "Saved user edit"
    assert not cleanup_review_approved(registry, "job_full")


def test_reset_tts_only_clears_voiceover(registry_with_full_pipeline):
    registry = registry_with_full_pipeline
    removed = reset_stage_for_rerun(registry, "job_full", "tts")

    assert "voiceover.wav" in removed
    assert not registry.exists("edited_video.mp4")
    assert not registry.exists("voiceover.wav")


def test_stage_ui_actions_shows_rerun_on_needs_review_annotations(tmp_path):
    job_dir = tmp_path / "job_ann_ui"
    job_dir.mkdir()
    registry = ArtifactRegistry(job_dir)
    registry.save_json("annotation_suggestions.json", {"suggestions": [{"annotation_id": "ann_001"}]})
    registry.save_json("annotation_review.json", {"status": "pending", "blocks": []})
    (job_dir / "annotation_preview.mp4").write_bytes(b"fake")

    actions = stage_ui_actions(registry, "annotations", "job_ann_ui", "needs_review")
    rerun = [a for a in actions if a.get("mode") == "rerun"]
    assert rerun and rerun[0]["label"] == RERUN_LABELS["annotations"]


def test_update_pipeline_state_removes_stages(registry_with_full_pipeline):
    registry = registry_with_full_pipeline
    state = update_pipeline_state_after_clear(registry, "tts", include_self=True)

    completed = set(state.get("stages_completed", []))
    assert PipelineStage.TIMELINE_MAP.value not in completed
    assert PipelineStage.VIDEO_EDIT.value not in completed
    assert PipelineStage.TTS.value not in completed
    assert PipelineStage.SPEECH_CLEANUP.value in completed
