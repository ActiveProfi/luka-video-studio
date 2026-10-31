"""Тесты: сохранённый текст на шаге 3 не затирается при повторной загрузке."""

from pathlib import Path

from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.cleanup_review_service import get_cleanup_edit_payload, save_manual_cleanup_edits


def _seed_job(job_dir: Path) -> ArtifactRegistry:
    registry = ArtifactRegistry(job_dir)
    registry.save_json(
        "transcript.json",
        {
            "job_id": "job_save",
            "segments": [
                {
                    "segment_id": "seg_001",
                    "start": 0.0,
                    "end": 25.0,
                    "text": "Исходный длинный текст из распознавания речи для первого блока",
                }
            ],
        },
    )
    registry.save_json(
        "clean_transcript.json",
        {
            "job_id": "job_save",
            "stage": "speech_cleanup",
            "version": "1.0.0",
            "created_at": "2026-01-01T00:00:00Z",
            "source_artifacts": ["transcript.json"],
            "status": "completed",
            "language": "ru",
            "duration_seconds": 25.0,
            "timing_aligned": True,
            "segments": [
                {
                    "segment_id": "seg_001",
                    "start": 0.0,
                    "end": 25.0,
                    "text": "Мой сохранённый текст",
                    "original_text": "Исходный длинный текст из распознавания речи для первого блока",
                    "confidence": 1.0,
                }
            ],
        },
    )
    registry.save_json("edits_map.json", {"job_id": "job_save", "edits": []})
    registry.save_json(
        "cleanup_review.json",
        {
            "job_id": "job_save",
            "stage": "speech_cleanup_review",
            "version": "1.0.0",
            "created_at": "2026-01-01T00:00:00Z",
            "status": "pending",
            "approved_at": None,
            "approved_by": None,
            "manual_edits_count": 2,
            "last_saved_at": "2026-01-02T00:00:00Z",
        },
        "cleanup_review.schema.json",
    )
    return registry


def test_get_cleanup_edit_returns_saved_text_not_transcript(tmp_path: Path) -> None:
    registry = _seed_job(tmp_path / "job_save")
    payload = get_cleanup_edit_payload(registry, "job_save")
    assert payload["segments"][0]["text"] == "Мой сохранённый текст"
    assert "Исходный длинный текст" not in payload["segments"][0]["text"]


def test_save_persists_after_edit(tmp_path: Path) -> None:
    registry = _seed_job(tmp_path / "job_save2")
    save_manual_cleanup_edits(
        registry,
        "job_save",
        [{"segment_id": "seg_001", "text": "Новая правка пользователя"}],
    )
    clean = registry.load_json("clean_transcript.json")
    assert clean["segments"][0]["text"] == "Новая правка пользователя"
    payload = get_cleanup_edit_payload(registry, "job_save")
    assert payload["segments"][0]["text"] == "Новая правка пользователя"
