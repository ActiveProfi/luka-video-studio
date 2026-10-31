"""Тесты заполнения пауз пустыми cue-блоками."""

from src.services.subtitle_service import fill_cue_timeline_gaps, timeline_has_gaps


def test_fill_gaps_covers_full_duration():
    cues = [
        {"cue_id": "cue_0001", "start": 0.0, "end": 2.0, "text": "A", "source_segment_id": "s1"},
        {"cue_id": "cue_0002", "start": 5.0, "end": 7.0, "text": "B", "source_segment_id": "s2"},
    ]
    assert timeline_has_gaps(cues, 10.0) is True
    filled = fill_cue_timeline_gaps(cues, 10.0)
    assert timeline_has_gaps(filled, 10.0) is False
    assert filled[0]["start"] == 0.0
    assert abs(filled[-1]["end"] - 10.0) < 0.001
    empties = [c for c in filled if not c["text"].strip()]
    assert len(empties) >= 2  # 2..5 и 7..10
    assert all(c["cue_id"].startswith("cue_") for c in filled)


def test_fill_leading_gap():
    cues = [{"cue_id": "x", "start": 1.5, "end": 3.0, "text": "hi", "source_segment_id": ""}]
    filled = fill_cue_timeline_gaps(cues, 3.0)
    assert filled[0]["start"] == 0.0
    assert filled[0]["text"] == ""
    assert filled[1]["text"] == "hi"
