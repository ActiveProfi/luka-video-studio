"""Тесты сохранения текста субтитров без изменения озвучки."""

from pathlib import Path

from src.orchestrator.artifact_registry import ArtifactRegistry
from src.services.subtitle_review_service import save_subtitle_cue_texts, save_subtitle_layout


def test_save_subtitle_cue_texts_updates_srt_only(tmp_path: Path) -> None:
    job_dir = tmp_path / "job_test"
    registry = ArtifactRegistry(job_dir)

    registry.save_json(
        "subtitle_timing.json",
        {
            "job_id": "job_test",
            "stage": "subtitles",
            "version": "1.0.0",
            "created_at": "2026-01-01T00:00:00Z",
            "source_artifacts": ["voiceover.wav"],
            "status": "completed",
            "language": "ru",
            "total_duration_seconds": 10.0,
            "cue_count": 1,
            "cues": [
                {
                    "cue_id": "cue_0001",
                    "start": 0.0,
                    "end": 5.0,
                    "text": "Старый текст",
                }
            ],
        },
    )
    registry.artifact_path("subtitles.srt").write_text("old", encoding="utf-8")
    registry.artifact_path("voiceover.wav").write_bytes(b"audio")
    registry.artifact_path("edited_video.mp4").write_bytes(b"video")

    save_subtitle_cue_texts(
        registry,
        "job_test",
        [{"cue_id": "cue_0001", "text": "Новый текст на экране"}],
    )

    timing = registry.load_json("subtitle_timing.json")
    assert timing["cues"][0]["text"] == "Новый текст на экране"
    assert timing.get("voiceover_unchanged") is True
    srt = registry.artifact_path("subtitles.srt").read_text(encoding="utf-8")
    assert "Новый текст на экране" in srt
    assert registry.artifact_path("voiceover.wav").read_bytes() == b"audio"


def test_save_subtitle_layout_stores_per_cue_boxes(tmp_path: Path) -> None:
    job_dir = tmp_path / "job_layout"
    registry = ArtifactRegistry(job_dir)

    registry.save_json(
        "subtitle_timing.json",
        {
            "job_id": "job_layout",
            "cue_count": 2,
            "cues": [
                {"cue_id": "cue_0001", "start": 0.0, "end": 3.0, "text": "Первая"},
                {"cue_id": "cue_0002", "start": 3.0, "end": 6.0, "text": "Вторая"},
            ],
        },
    )
    registry.artifact_path("edited_video.mp4").write_bytes(b"video")
    registry.artifact_path("subtitles.srt").write_text("old", encoding="utf-8")
    registry.save_json("subtitle_layout.json", {"x": 0.06, "y": 0.82, "width": 0.88, "height": 0.12})

    save_subtitle_layout(
        registry,
        "job_layout",
        {
            "x": 0.06,
            "y": 0.82,
            "width": 0.88,
            "height": 0.12,
            "cue_layouts": {
                "cue_0002": {"x": 0.1, "y": 0.7, "width": 0.8, "height": 0.15},
            },
        },
    )

    layout = registry.load_json("subtitle_layout.json")
    assert layout["cue_layouts"]["cue_0002"]["y"] == 0.7
    payload = registry.load_json("subtitle_layout.json")
    assert "cue_0001" not in payload.get("cue_layouts", {})


def test_save_subtitle_cue_texts_with_duplicate_ids_uses_segment_and_time(tmp_path: Path) -> None:
    job_dir = tmp_path / "job_dup"
    registry = ArtifactRegistry(job_dir)

    registry.save_json(
        "subtitle_timing.json",
        {
            "job_id": "job_dup",
            "stage": "subtitles",
            "version": "1.0.0",
            "created_at": "2026-01-01T00:00:00Z",
            "source_artifacts": ["voiceover.wav"],
            "status": "completed",
            "language": "ru",
            "total_duration_seconds": 30.0,
            "cue_count": 2,
            "cues": [
                {
                    "cue_id": "cue_0001",
                    "source_segment_id": "tts_001",
                    "start": 0.0,
                    "end": 5.0,
                    "text": "Первая",
                },
                {
                    "cue_id": "cue_0001",
                    "source_segment_id": "tts_002",
                    "start": 25.0,
                    "end": 28.0,
                    "text": "Вторая",
                },
            ],
        },
    )
    registry.artifact_path("subtitles.srt").write_text("old", encoding="utf-8")
    registry.artifact_path("voiceover.wav").write_bytes(b"audio")
    registry.artifact_path("edited_video.mp4").write_bytes(b"video")

    save_subtitle_cue_texts(
        registry,
        "job_dup",
        [
            {
                "cue_id": "cue_0001",
                "source_segment_id": "tts_002",
                "start": 25.0,
                "end": 28.0,
                "text": "Исправленная вторая",
            }
        ],
    )

    timing = registry.load_json("subtitle_timing.json")
    by_start = {float(c["start"]): c for c in timing["cues"]}
    assert by_start[0.0]["text"] == "Первая"
    assert by_start[25.0]["text"] == "Исправленная вторая"
    # После сохранения дубликаты cue_id разводятся, паузы могут закрыться пустыми блоками.
    texts = [c["text"] for c in timing["cues"]]
    assert "Первая" in texts
    assert "Исправленная вторая" in texts
