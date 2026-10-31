"""Тесты подготовки текста к ручному редактированию."""

import pytest

from src.agents.speech_cleanup_agent import run_speech_cleanup
from src.config import Settings
from src.domain.enums import PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry


@pytest.fixture
def job_setup(tmp_path):
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()
    registry = ArtifactRegistry(job_dir)

    registry.save_json(
        "transcript.json",
        {
            "job_id": "job_test",
            "stage": "transcription",
            "version": "1.0.0",
            "created_at": "2026-06-19T10:00:00Z",
            "source_artifacts": ["raw_video.mp4"],
            "status": "completed",
            "language": "ru",
            "duration_seconds": 30.0,
            "segments": [
                {
                    "segment_id": "seg_001",
                    "start": 0.0,
                    "end": 10.0,
                    "text": "Э-э, ну, открываем документ НДС в 1С",
                    "confidence": 0.9,
                },
                {
                    "segment_id": "seg_002",
                    "start": 10.0,
                    "end": 20.0,
                    "text": "Проверяем месяц применения НДС",
                    "confidence": 0.88,
                },
            ],
        },
        "transcript.schema.json",
    )

    settings = Settings(
        yandex_gpt_api_key="test-key",
        yandex_gpt_folder_id="test-folder",
        output_dir=tmp_path,
        domain_glossary_path=tmp_path / "glossary.txt",
    )
    return registry, settings, "job_test"


def test_text_edit_prep_copies_stt_blocks_without_changes(job_setup):
    registry, settings, job_id = job_setup

    result = run_speech_cleanup(registry, settings, job_id)

    assert result["stage"] == PipelineStage.SPEECH_CLEANUP.value
    assert registry.exists("clean_transcript.json")
    assert registry.exists("edits_map.json")
    assert registry.exists("cleanup_review.json")

    clean = registry.load_json("clean_transcript.json")
    edits = registry.load_json("edits_map.json")
    registry.validate(clean, "clean_transcript.schema.json")
    registry.validate(edits, "edits_map.schema.json")

    assert clean["provider"] == "manual_text_edit"
    assert clean["mode"] == "manual_text_edit"
    assert clean.get("timing_aligned") is True
    assert len(clean["segments"]) == 1
    assert "открываем документ" in clean["segments"][0]["text"]
    assert "Проверяем месяц" in clean["segments"][0]["text"]
    assert clean["segments"][0]["original_text"] == clean["segments"][0]["text"]
    assert len(edits["edits"]) == 0


def test_text_edit_prep_reuses_existing_artifacts(job_setup):
    registry, settings, job_id = job_setup

    first = run_speech_cleanup(registry, settings, job_id)
    second = run_speech_cleanup(registry, settings, job_id)

    assert second == first
    assert registry.exists("edits_map.json")
