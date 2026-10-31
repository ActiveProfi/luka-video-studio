"""Тесты парсинга ответа ИИ-улучшения текста."""

import pytest

from src.services.text_improvement_service import (
    _retry_hint,
    build_segment_improvement_context,
    parse_improvement_response,
)
from src.services.segment_timing_service import count_timing_steps


def test_parse_improvement_response_exact_budget() -> None:
    text = "мы открываем"
    budget = count_timing_steps(text)
    raw = f'{{"text": "{text}", "steps": {budget}, "notes": "ok"}}'
    parsed = parse_improvement_response(raw, budget_steps=budget)
    assert parsed["text"] == text


def test_parse_improvement_response_rejects_wrong_steps() -> None:
    text = "короткий текст"
    budget = count_timing_steps(text) + 5
    raw = f'{{"text": "{text}", "steps": {budget}, "notes": "bad"}}'
    with pytest.raises(ValueError, match="ИИ вернул"):
        parse_improvement_response(raw, budget_steps=budget)


def test_build_segment_improvement_context_budget() -> None:
    ctx = build_segment_improvement_context(
        {
            "start": 0.0,
            "end": 25.0,
            "text": "НДС в 1С",
            "original_text": "ндс в 1 с мы смотрим отчеты дальше по тексту блока",
        }
    )
    assert ctx["budget_steps"] >= 10
    assert ctx["slot_seconds"] == 25.0


def test_retry_hint_directions() -> None:
    assert "Сократи" in _retry_hint(100, 110)
    assert "Добавь" in _retry_hint(100, 90)
