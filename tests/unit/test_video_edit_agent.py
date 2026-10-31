"""Тесты Video Edit Agent."""

import shutil
import subprocess

import pytest

from src.agents.video_edit_agent import run_video_edit
from src.config import Settings
from src.orchestrator.artifact_registry import ArtifactRegistry


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture
def edit_job(tmp_path):
    if not _ffmpeg_available():
        pytest.skip("ffmpeg не установлен")

    job_dir = tmp_path / "job_edit"
    job_dir.mkdir()
    registry = ArtifactRegistry(job_dir)

    raw = job_dir / "raw_video.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
            "-t",
            "6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(raw),
        ],
        capture_output=True,
        check=True,
    )

    registry.save_json(
        "timing_decisions.json",
        {
            "job_id": "job_edit",
            "stage": "timing_policy",
            "version": "1.0.0",
            "created_at": "2026-06-20T12:00:00Z",
            "source_artifacts": ["timeline_map.json"],
            "status": "completed",
            "decisions": [],
        },
        "timing_decisions.schema.json",
    )
    registry.save_json(
        "timeline_map.json",
        {
            "job_id": "job_edit",
            "stage": "timeline_map",
            "version": "1.0.0",
            "created_at": "2026-06-20T12:00:00Z",
            "source_artifacts": ["timing_decisions.json"],
            "status": "completed",
            "source_duration_seconds": 6.0,
            "target_duration_seconds": 4.0,
            "segments": [
                {
                    "segment_index": 0,
                    "source_start": 0.0,
                    "source_end": 2.0,
                    "target_start": 0.0,
                    "target_end": 2.0,
                    "transform": "keep",
                    "speed_factor": 1.0,
                    "trim_removed_seconds": 0.0,
                },
                {
                    "segment_index": 1,
                    "source_start": 2.0,
                    "source_end": 4.0,
                    "target_start": 2.0,
                    "target_end": 2.0,
                    "transform": "removed",
                    "speed_factor": None,
                    "trim_removed_seconds": 0.0,
                },
                {
                    "segment_index": 2,
                    "source_start": 4.0,
                    "source_end": 6.0,
                    "target_start": 2.0,
                    "target_end": 4.0,
                    "transform": "keep",
                    "speed_factor": 1.0,
                    "trim_removed_seconds": 0.0,
                },
            ],
        },
        "timeline_map.schema.json",
    )

    settings = Settings(output_dir=tmp_path)
    return registry, settings, "job_edit"


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg не установлен")
def test_video_edit_creates_output(edit_job):
    registry, settings, job_id = edit_job
    subprocess.run([shutil.which("ffmpeg"), "-y", "-f", "lavfi", "-i",
                    "sine=frequency=880:duration=6", "-ar", "48000", "-ac", "1",
                    str(registry.artifact_path("voiceover.wav"))], capture_output=True, check=True)
    report = run_video_edit(registry, settings, job_id)

    assert registry.exists("edited_video.mp4")
    assert registry.exists("video_edit_report.json")
    assert report["pauses_removed"] is False
    assert report["output_duration_seconds"] == pytest.approx(6.0, abs=0.1)
