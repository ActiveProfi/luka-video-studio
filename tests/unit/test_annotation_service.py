"""Тесты сервиса аннотаций."""

from src.services.annotation_service import (
    auto_approve,
    build_lesson_moments,
    parse_llm_suggestions,
    rule_based_suggestions,
)


def test_build_lesson_moments_uses_voiceover_timing():
    clean = [
        {"segment_id": "seg_001", "text": "Открываем меню НДС.", "start": 0, "end": 5},
        {"segment_id": "seg_002", "text": "Проверяем отчёт.", "start": 5, "end": 10},
    ]
    voiceover = [
        {
            "segment_id": "tts_001",
            "transcript_segment_id": "seg_001",
            "audio_start": 1.0,
            "audio_end": 4.0,
        }
    ]
    moments = build_lesson_moments(clean, voiceover, [])
    assert len(moments) == 2
    assert moments[0]["target_start"] == 1.0
    assert moments[0]["target_end"] == 4.0


def test_rule_based_suggestions_for_action_text():
    moments = [
        {
            "segment_id": "seg_001",
            "target_start": 10.0,
            "target_end": 14.0,
            "text": "Открываем раздел «Налоги и отчёты» и находим отчёт по НДС.",
        }
    ]
    items = rule_based_suggestions(moments)
    assert len(items) == 1
    assert items[0]["type"] in {"arrow", "highlight_rect", "zoom", "callout"}
    assert items[0]["target_start"] == 10.0


def test_grouped_voice_phrase_is_not_split_back_into_stale_subtitle_times():
    clean = [
        {"segment_id": "block_1", "text": "Открываем", "start": 1, "end": 2},
        {"segment_id": "block_2", "text": "Налоги и отчеты", "start": 2, "end": 7},
    ]
    voice = [
        {
            "transcript_segment_id": "block_1",
            "source_block_ids": [1, 2],
            "audio_start": 1,
            "audio_end": 4,
            "text": "Открываем Налоги и отчеты",
        }
    ]
    moments = build_lesson_moments(clean, voice, [])
    assert len(moments) == 1
    assert moments[0]["text"] == voice[0]["text"]
    assert moments[0]["target_end"] == 4


def test_parse_llm_suggestions():
    moments = [
        {
            "segment_id": "seg_001",
            "target_start": 5.0,
            "target_end": 9.0,
            "text": "Тест",
        }
    ]
    raw = """
    {
      "suggestions": [
        {
          "annotation_id": "ann_001",
          "type": "arrow",
          "target_start": 5.5,
          "target_end": 8.0,
          "label": "Меню 1С",
          "linked_segment_id": "seg_001",
          "confidence": 0.92
        }
      ]
    }
    """
    items = parse_llm_suggestions(raw, moments)
    assert len(items) == 1
    assert items[0]["label"] == "Меню 1С"
    assert items[0].get("anchor") is None
    assert items[0]["placement_confirmed"] is False
    assert items[0].get("arrow_length_ratio") == 0.08


def test_auto_approve_splits_by_confidence():
    suggestions = [
        {"confidence": 0.9, "requires_review": False},
        {"confidence": 0.7, "requires_review": True},
    ]
    approved, pending = auto_approve(suggestions)
    assert len(approved) == 1
    assert len(pending) == 1
