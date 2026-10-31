"""Тесты TTS Generation Agent."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.tts_generation_agent import run_tts_generation
from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.providers.tts.base import TTSResult


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _make_wav(path: Path, duration: float = 1.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=" + str(duration),
            "-ar",
            "48000",
            "-ac",
            "1",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


@pytest.fixture
def tts_job(tmp_path):
    if not _ffmpeg_available():
        pytest.skip("ffmpeg не установлен")

    job_dir = tmp_path / "job_tts"
    job_dir.mkdir()
    registry = ArtifactRegistry(job_dir)

    raw_video = job_dir / "raw_video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=25",
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(raw_video),
        ],
        capture_output=True,
        check=True,
    )

    registry.save_json(
        "clean_transcript.json",
        {
            "job_id": "job_tts",
            "stage": "speech_cleanup",
            "version": "1.0.0",
            "created_at": "2026-06-20T12:00:00Z",
            "source_artifacts": [],
            "status": "completed",
            "language": "ru",
            "duration_seconds": 4.0,
            "segments": [
                {
                    "segment_id": "seg_001",
                    "start": 0.0,
                    "end": 2.0,
                    "text": "Первый фрагмент урока",
                    "edit_ids": [],
                },
                {
                    "segment_id": "seg_002",
                    "start": 2.0,
                    "end": 4.0,
                    "text": "Второй фрагмент урока",
                    "edit_ids": [],
                },
            ],
        },
        "clean_transcript.schema.json",
    )
    registry.save_json(
        "timeline_map.json",
        {
            "job_id": "job_tts",
            "stage": "timeline_map",
            "version": "1.0.0",
            "created_at": "2026-06-20T12:00:00Z",
            "source_artifacts": [],
            "status": "completed",
            "source_duration_seconds": 4.0,
            "target_duration_seconds": 4.0,
            "segments": [
                {
                    "segment_index": 0,
                    "source_start": 0.0,
                    "source_end": 4.0,
                    "target_start": 0.0,
                    "target_end": 4.0,
                    "transform": "keep",
                    "speed_factor": 1.0,
                    "trim_removed_seconds": 0.0,
                }
            ],
        },
        "timeline_map.schema.json",
    )

    settings = Settings(output_dir=tmp_path, yandex_api_key="test", yandex_folder_id="test")
    return registry, settings, "job_tts"


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg не установлен")
def test_tts_generation_with_mock_provider(tts_job, tmp_path):
    registry, settings, job_id = tts_job
    chunk_dir = registry.job_dir / "_tts_chunks"
    chunk_dir.mkdir(exist_ok=True)

    async def fake_synthesize(chunk, _settings):
        _make_wav(chunk.output_path, duration=0.8)
        return TTSResult(output_path=chunk.output_path, provider="mock", duration_seconds=0.8)

    with patch("src.agents.tts_generation_agent.synthesize_with_fallback", new=AsyncMock(side_effect=fake_synthesize)):
        doc = run_tts_generation(registry, settings, job_id)

    assert registry.exists("voiceover.wav")
    assert registry.exists("voiceover_segments.json")
    assert len(doc["segments"]) == 2
    assert doc["provider"] == "mock"


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg не установлен")
def test_tts_generation_uses_speech_script_when_available(tts_job):
    registry, settings, job_id = tts_job
    registry.save_json(
        "speech_script.json",
        {
            "job_id": job_id,
            "stage": "speech_script",
            "version": "1.0.0",
            "created_at": "2026-06-20T12:00:00Z",
            "source_artifacts": ["clean_transcript.json"],
            "status": "ok",
            "confidence": 0.95,
            "trust_level": "auto",
            "tts_provider": "mock",
            "text": "Speech script only",
            "segments": [
                {
                    "segment_id": "seg_001",
                    "start": 0.0,
                    "end": 2.0,
                    "text": "Speech script first",
                    "original_text": "Первый фрагмент урока",
                },
                {
                    "segment_id": "seg_002",
                    "start": 2.0,
                    "end": 4.0,
                    "text": "Speech script second",
                    "original_text": "Второй фрагмент урока",
                },
            ],
        },
    )
    seen_texts: list[str] = []

    async def fake_synthesize(chunk, _settings):
        seen_texts.append(chunk.text)
        _make_wav(chunk.output_path, duration=0.8)
        return TTSResult(output_path=chunk.output_path, provider="mock", duration_seconds=0.8)

    with patch("src.agents.tts_generation_agent.synthesize_with_fallback", new=AsyncMock(side_effect=fake_synthesize)):
        doc = run_tts_generation(registry, settings, job_id)

    assert seen_texts == ["Speech script first", "Speech script second"]
    assert doc["speech_script_used"] is True
