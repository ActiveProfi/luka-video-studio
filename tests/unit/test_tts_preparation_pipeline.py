"""Тесты конвейера подготовки текста к TTS (без LLM-переписывания)."""

import pytest

from src.config import Settings
from src.services.tts_preparation_pipeline import run_tts_preparation_pipeline_async


@pytest.mark.asyncio
async def test_tts_preparation_pipeline_rules_only_keeps_wording() -> None:
    settings = Settings()
    result = await run_tts_preparation_pipeline_async(
        settings,
        job_id="job_test",
        full_text="эээ ну открываем ндс в 1С",
        full_original="эээ ну открываем ндс в 1С",
    )

    assert result["provider"] == "rules_only"
    assert result["audit_result"]["approved"] is True
    # Мусор убран, аббревиатуры подготовлены к озвучке, смысл фразы сохранён.
    assert "открываем" in result["full_text"].casefold()
    assert "эн дэ эс" in result["full_text"].casefold() or "ндс" not in result["full_text"].casefold()
    assert [phase["id"] for phase in result["phases"]][:4] == ["3.1", "3.2", "3.3", "3.4"]
    assert result["phases"][2].get("skipped") is True
