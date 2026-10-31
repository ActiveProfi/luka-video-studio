"""Тесты агента переписывания текста под озвучку."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.voiceover_text_rewrite_agent import (
    parse_analysis_response,
    parse_rewrite_response,
    run_voiceover_text_rewrite_async,
)
from src.config import Settings
from src.services.segment_timing_service import count_timing_steps
from src.services.voiceover_text_rules import strip_fillers, texts_are_unchanged


def test_parse_analysis_response() -> None:
    raw = """{
      "issues": [
        {"type": "stt_error", "fragment": "эн дэ эс", "problem": "ошибка", "suggested_fix": "НДС"}
      ],
      "summary": "1 ошибка STT"
    }"""
    parsed = parse_analysis_response(raw)
    assert len(parsed["issues"]) == 1
    assert "1 ошибка" in parsed["summary"]


def test_parse_rewrite_response() -> None:
    raw = '{"text": "Открываем документ эн дэ эс.", "changes_applied": ["расшифровка НДС"]}'
    parsed = parse_rewrite_response(raw)
    assert "эн дэ эс" in parsed["text"]
    assert parsed["changes_applied"] == ["расшифровка НДС"]


def test_strip_fillers() -> None:
    assert "открываем" in strip_fillers("э-э ну открываем документ").lower()


def test_texts_are_unchanged() -> None:
    assert texts_are_unchanged("Привет мир", "  привет   мир ")
    assert not texts_are_unchanged("Привет", "Пока")


@pytest.mark.asyncio
async def test_run_voiceover_text_rewrite_async_pipeline() -> None:
    original = "э-э открываем документ НДС в один эс"
    draft = "Открываем документ эн дэ эс в один эс."
    budget = count_timing_steps(original)
    final = draft if count_timing_steps(draft) == budget else original

    settings = Settings()

    with patch(
        "src.agents.voiceover_text_rewrite_agent.analyze_voiceover_text",
        new=AsyncMock(
            return_value=(
                {"issues": [{"type": "filler"}], "summary": "Найдено 1 проблема"},
                "mock",
            )
        ),
    ), patch(
        "src.agents.voiceover_text_rewrite_agent.rewrite_for_voiceover",
        new=AsyncMock(
            return_value=(
                {"text": draft, "changes_applied": ["убраны паразиты", "расшифрован НДС"]},
                "mock",
            )
        ),
    ), patch(
        "src.agents.voiceover_text_rewrite_agent.fit_voiceover_timing",
        new=AsyncMock(
            return_value=(
                {
                    "text": final,
                    "notes": "ok",
                    "budget_steps": budget,
                    "improved_steps": count_timing_steps(final),
                    "attempts": 1,
                },
                "mock",
            )
        ),
    ):
        result = await run_voiceover_text_rewrite_async(
            settings,
            full_text=original,
            full_original=original,
            duration=25.0,
            segments=[{"segment_id": "seg_001", "start": 0, "end": 25, "original_text": original}],
        )

    assert result["agent"] == "voiceover_text_rewrite"
    assert result["issues_found"] == 1
    assert len(result["changes_applied"]) == 2
    assert result["text"] == final
