"""Тесты построения timeline_map."""

from src.services.timeline_map_service import build_timeline_map


def test_build_timeline_with_removal():
    decisions = [
        {
            "candidate_id": "cand_001",
            "decision": "remove_audio_video",
            "target_start": 10.0,
            "target_end": 15.0,
            "requires_review": False,
        }
    ]
    timeline = build_timeline_map("job_x", 30.0, decisions)
    assert timeline["source_duration_seconds"] == 30.0
    assert timeline["target_duration_seconds"] == 25.0
    transforms = [s["transform"] for s in timeline["segments"]]
    assert "removed" in transforms
    assert "keep" in transforms
