"""Тесты ручной проверки текста после очистки речи."""

import pytest

from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.cleanup_review_service import (
    approve_cleanup_review,
    cleanup_review_approved,
    create_pending_cleanup_review,
    get_cleanup_edit_payload,
    save_manual_cleanup_edits,
)


@pytest.fixture
def registry_with_cleanup(tmp_path):
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()
    registry = ArtifactRegistry(job_dir)
    registry.save_json(
        "clean_transcript.json",
        {
            "job_id": "job_test",
            "stage": "speech_cleanup",
            "version": "1.0.0",
            "created_at": "2026-06-20T10:00:00Z",
            "source_artifacts": ["transcript.json"],
            "status": "completed",
            "language": "ru",
            "duration_seconds": 30.0,
            "segments": [
                {
                    "segment_id": "seg_001",
                    "start": 0.0,
                    "end": 10.0,
                    "text": "Э-э, открываем документ НДС",
                    "original_text": "Э-э, ну, открываем документ НДС",
                }
            ],
        },
        "clean_transcript.schema.json",
    )
    registry.save_json(
        "edits_map.json",
        {
            "job_id": "job_test",
            "stage": "speech_cleanup",
            "version": "1.0.0",
            "created_at": "2026-06-20T10:00:00Z",
            "source_artifacts": ["transcript.json"],
            "status": "completed",
            "edits": [],
        },
        "edits_map.schema.json",
    )
    create_pending_cleanup_review(registry, "job_test")
    return registry


def test_manual_edit_and_approve(registry_with_cleanup):
    registry = registry_with_cleanup
    assert not cleanup_review_approved(registry, "job_test")

    save_manual_cleanup_edits(
        registry,
        "job_test",
        [{"segment_id": "seg_001", "text": "Открываем документ НДС в 1С"}],
    )
    payload = get_cleanup_edit_payload(registry, "job_test")
    assert payload["segments"][0]["text"] == "Открываем документ НДС в 1С"
    assert payload["review_status"] == "pending"

    approve_cleanup_review(registry, "job_test")
    assert cleanup_review_approved(registry, "job_test")
    approved = get_cleanup_edit_payload(registry, "job_test")
    assert approved["review_status"] == "approved"


def test_save_resets_approval(registry_with_cleanup):
    registry = registry_with_cleanup
    approve_cleanup_review(registry, "job_test")
    assert cleanup_review_approved(registry, "job_test")

    save_manual_cleanup_edits(
        registry,
        "job_test",
        [{"segment_id": "seg_001", "text": "Новая версия текста"}],
    )
    payload = get_cleanup_edit_payload(registry, "job_test")
    assert payload["review_status"] == "pending"
    assert payload["segments"][0]["text"] == "Новая версия текста"
    assert not cleanup_review_approved(registry, "job_test")


def test_save_without_changes_keeps_approval(registry_with_cleanup):
    registry = registry_with_cleanup
    approve_cleanup_review(registry, "job_test")
    assert cleanup_review_approved(registry, "job_test")

    save_manual_cleanup_edits(
        registry,
        "job_test",
        [{"segment_id": "seg_001", "text": "Э-э, открываем документ НДС"}],
    )
    payload = get_cleanup_edit_payload(registry, "job_test")
    assert payload["review_status"] == "approved"
    assert cleanup_review_approved(registry, "job_test")


def test_save_requires_all_segments(registry_with_cleanup):
    registry = registry_with_cleanup
    with pytest.raises(ValueError, match="Не переданы все блоки"):
        save_manual_cleanup_edits(registry, "job_test", [])
