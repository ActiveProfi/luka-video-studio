"""Тесты Speech Recognition Agent."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.speech_recognition_agent import run_speech_recognition
from src.config import Settings
from src.domain.enums import PipelineStage
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.providers.stt.base import STTResult, TranscriptSegment


@pytest.fixture
def job_setup(tmp_path):
    job_dir = tmp_path / "job_test"
    job_dir.mkdir()
    registry = ArtifactRegistry(job_dir)

    video = job_dir / "raw_video.mp4"
    video.write_bytes(b"\x00" * 100)

    registry.save_json(
        "input_manifest.json",
        {
            "job_id": "job_test",
            "stage": "input_ingestion",
            "raw_video_path": str(video),
            "language": "ru",
        },
    )
    settings = Settings(
        yandex_api_key="test-key",
        yandex_folder_id="test-folder",
        output_dir=tmp_path,
    )
    return registry, settings, "job_test"


def test_speech_recognition_creates_transcript(job_setup):
    registry, settings, job_id = job_setup

    mock_result = STTResult(
        language="ru",
        duration_seconds=30.0,
        provider="yandex",
        segments=[
            TranscriptSegment(
                segment_id="seg_001",
                start=0.0,
                end=5.0,
                text="Сегодня разберём месяц применения НДС",
                confidence=0.92,
            ),
            TranscriptSegment(
                segment_id="seg_002",
                start=5.0,
                end=10.0,
                text="Открываем документ в 1С",
                confidence=0.88,
            ),
        ],
    )

    with (
        patch("src.agents.speech_recognition_agent.extract_audio_ogg") as mock_extract,
        patch("src.agents.speech_recognition_agent.get_media_duration_seconds", return_value=120.0),
        patch(
            "src.agents.speech_recognition_agent.transcribe_with_fallback",
            new=AsyncMock(return_value=mock_result),
        ),
    ):
        mock_extract.return_value = registry.job_dir / "raw_audio.ogg"
        transcript = run_speech_recognition(registry, settings, job_id)

    assert transcript["stage"] == PipelineStage.TRANSCRIPTION.value
    assert len(transcript["segments"]) == 2
    assert registry.exists("transcript.json")

    saved = registry.load_json("transcript.json")
    registry.validate(saved, "transcript.schema.json")
