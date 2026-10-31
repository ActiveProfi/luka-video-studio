import json
import tempfile
from pathlib import Path

import pytest

from src.orchestrator.artifact_registry import ArtifactRegistry


def test_save_and_load_json():
    with tempfile.TemporaryDirectory() as tmp:
        registry = ArtifactRegistry(Path(tmp))
        data = {"job_id": "job_test", "stage": "test", "value": 1}
        registry.save_json("test.json", data)
        loaded = registry.load_json("test.json")
        assert loaded["job_id"] == "job_test"


def test_validate_transcript_schema():
    with tempfile.TemporaryDirectory() as tmp:
        registry = ArtifactRegistry(Path(tmp))
        data = {
            "job_id": "j1",
            "stage": "transcription",
            "version": "1.0.0",
            "created_at": "2026-06-16T12:00:00Z",
            "source_artifacts": [],
            "status": "completed",
            "language": "ru",
            "duration_seconds": 10.0,
            "segments": [
                {
                    "segment_id": "seg_001",
                    "start": 0.0,
                    "end": 2.0,
                    "text": "Тест",
                }
            ],
        }
        registry.save_json("transcript.json", data, "transcript.schema.json")
        assert registry.exists("transcript.json")
