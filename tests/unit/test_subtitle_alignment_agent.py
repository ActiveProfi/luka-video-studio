"""Тесты генерации субтитров."""

import pytest

from src.agents.subtitle_alignment_agent import run_subtitle_alignment
from src.config import get_settings
from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.subtitle_service import build_srt_content, cues_from_voiceover_segments, format_srt_timestamp


def test_format_srt_timestamp():
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(65.5) == "00:01:05,500"


def test_build_srt_from_voiceover_segments():
    segments = [
        {
            "segment_id": "tts_001",
            "text": "Открываем документ. Проверяем отчёт.",
            "audio_start": 0.0,
            "audio_end": 4.0,
        }
    ]
    cues = cues_from_voiceover_segments(segments)
    assert len(cues) >= 1
    srt = build_srt_content(cues)
    assert "00:00:00,000 -->" in srt
    assert "Открываем документ" in srt


def test_cues_from_voiceover_segments_have_global_unique_ids():
    segments = [
        {
            "segment_id": "tts_001",
            "text": "Первая фраза.",
            "audio_start": 0.0,
            "audio_end": 3.0,
        },
        {
            "segment_id": "tts_002",
            "text": "Вторая фраза.",
            "audio_start": 25.0,
            "audio_end": 28.0,
        },
    ]
    cues = cues_from_voiceover_segments(segments)
    cue_ids = [c["cue_id"] for c in cues]
    assert len(cue_ids) == len(set(cue_ids))
    assert cue_ids[0] == "cue_0001"
    assert cues[1]["cue_id"] == "cue_0002"
    assert cues[0]["source_segment_id"] == "tts_001"
    assert cues[1]["source_segment_id"] == "tts_002"


@pytest.fixture
def registry_with_voiceover(tmp_path):
    job_dir = tmp_path / "job_subs"
    job_dir.mkdir()
    registry = ArtifactRegistry(job_dir)
    (job_dir / "voiceover.wav").write_bytes(b"fake")
    registry.save_json(
        "voiceover_segments.json",
        {
            "job_id": "job_subs",
            "stage": "tts",
            "version": "1.0.0",
            "created_at": "2026-06-21T10:00:00Z",
            "source_artifacts": [],
            "status": "completed",
            "language": "ru",
            "total_duration_seconds": 10.0,
            "segments": [
                {
                    "segment_id": "tts_001",
                    "transcript_segment_id": "seg_001",
                    "text": "Первый субтитр для теста.",
                    "target_start": 0.0,
                    "target_end": 5.0,
                    "audio_start": 0.0,
                    "audio_end": 4.5,
                }
            ],
        },
    )
    return registry


def test_run_subtitle_alignment(registry_with_voiceover):
    registry = registry_with_voiceover
    settings = get_settings()
    doc = run_subtitle_alignment(registry, settings, "job_subs")
    assert registry.exists("subtitles.srt")
    assert registry.exists("subtitle_timing.json")
    assert registry.exists("subtitle_layout.json")
    assert doc["cue_count"] >= 1
    srt = registry.artifact_path("subtitles.srt").read_text(encoding="utf-8")
    assert "Первый субтитр" in srt
