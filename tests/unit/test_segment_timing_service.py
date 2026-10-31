"""Тесты посимвольной разбивки текста по тайм-блокам."""

from src.services.segment_timing_service import (
    count_timing_steps,
    realign_transcript_segments,
    redistribute_words_to_segments,
    segments_from_full_text,
    segments_need_timing_realign,
    split_text_into_time_blocks,
)


def test_split_text_respects_time_budget_per_block() -> None:
    text = "абвгд" * 20  # 100 символов, без пробелов -> 100 шагов
    blocks = split_text_into_time_blocks(text, duration=100.0, block_seconds=25.0)
    assert len(blocks) == 4
    assert all(block["end"] - block["start"] == 25.0 for block in blocks[:3])
    assert sum(len(block["text"]) for block in blocks) == len(text)


def test_realign_splits_long_stt_chunk_text() -> None:
    long_text = "слово " * 200
    segments = [
        {
            "segment_id": "seg_001",
            "start": 0.0,
            "end": 25.0,
            "text": long_text.strip(),
        },
        {
            "segment_id": "seg_002",
            "start": 25.0,
            "end": 50.0,
            "text": "вторая часть текста для проверки",
        },
    ]
    aligned = realign_transcript_segments(segments, block_seconds=25.0)
    assert len(aligned) == 2
    assert aligned[0]["start"] == 0.0
    assert aligned[0]["end"] == 25.0
    assert aligned[1]["start"] == 25.0
    assert len(aligned[0]["text"]) < len(long_text.strip())


def test_equal_duration_blocks_have_similar_step_budgets() -> None:
    segments = [
        {"segment_id": "seg_001", "start": 0.0, "end": 25.0, "text": "a" * 249},
        {"segment_id": "seg_002", "start": 25.0, "end": 50.0, "text": "b" * 203},
    ]
    assert segments_need_timing_realign(segments, duration=50.0) is True

    aligned = realign_transcript_segments(
        [
            {"segment_id": "seg_001", "start": 0.0, "end": 25.0, "text": "a" * 249},
            {"segment_id": "seg_002", "start": 25.0, "end": 50.0, "text": "b" * 203},
        ],
        block_seconds=25.0,
    )
    budgets = [count_timing_steps(block["text"]) for block in aligned[:2]]
    assert abs(budgets[0] - budgets[1]) <= 2


def test_segments_from_full_text_keeps_bounds_and_whole_words() -> None:
    source = [
        {
            "segment_id": "seg_001",
            "start": 0.0,
            "end": 25.0,
            "text": "один два три четыре",
            "original_text": "один два три четыре",
        },
        {
            "segment_id": "seg_002",
            "start": 25.0,
            "end": 50.0,
            "text": "пять шесть семь восемь",
            "original_text": "пять шесть семь восемь",
        },
    ]
    full = "Альфа бета гамма дельта эпсилон дзета эта тета"
    result = segments_from_full_text(full, source, duration=50.0)
    assert [seg["start"] for seg in result] == [0.0, 25.0]
    assert [seg["end"] for seg in result] == [25.0, 50.0]
    assert " ".join(seg["text"] for seg in result) == full
    # никакой кусок не является обломком слова из середины
    for seg in result:
        assert seg["text"] == " ".join(seg["text"].split())
        assert seg["text_before"] == seg["original_text"]
        assert seg["text_after"] == seg["text"]


def test_redistribute_words_never_cuts_tokens() -> None:
    source = [
        {"segment_id": "seg_001", "start": 0.0, "end": 10.0, "text": "aaa"},
        {"segment_id": "seg_002", "start": 10.0, "end": 20.0, "text": "bbb"},
        {"segment_id": "seg_003", "start": 20.0, "end": 30.0, "text": "ccc"},
    ]
    parts = redistribute_words_to_segments("один два три четыре пять шесть", source)
    assert len(parts) == 3
    assert " ".join(parts) == "один два три четыре пять шесть"
    assert all(part == " ".join(part.split()) for part in parts)
