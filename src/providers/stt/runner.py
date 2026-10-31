"""Запуск STT с цепочкой fallback."""

from __future__ import annotations

import logging
from pathlib import Path

from src.config import Settings
from src.providers.stt.base import STTResult
from src.providers.stt.factory import build_stt_chain

logger = logging.getLogger(__name__)


async def transcribe_with_fallback(
    audio_path: Path,
    settings: Settings,
    language: str = "ru",
) -> STTResult:
    providers = build_stt_chain(settings)
    if not providers:
        raise RuntimeError("Нет доступных STT-провайдеров. Проверьте .env")

    last_error: Exception | None = None
    for provider in providers:
        try:
            logger.info("STT: пробуем %s", provider.name)
            return await provider.transcribe(audio_path, language)
        except Exception as exc:
            last_error = exc
            logger.warning("STT %s не сработал: %s", provider.name, exc)

    raise RuntimeError(f"Все STT-провайдеры недоступны. Последняя ошибка: {last_error}")
