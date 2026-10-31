"""Запуск TTS с цепочкой fallback."""

from __future__ import annotations

import logging

from src.config import Settings
from src.providers.tts.base import TTSChunk, TTSResult
from src.providers.tts.factory import build_tts_chain

logger = logging.getLogger(__name__)


async def synthesize_with_fallback(chunk: TTSChunk, settings: Settings) -> TTSResult:
    providers = build_tts_chain(settings)
    if not providers:
        raise RuntimeError("Нет доступных TTS-провайдеров. Проверьте .env (YANDEX_API_KEY или OPENAI_API_KEY)")

    last_error: Exception | None = None
    for provider in providers:
        try:
            logger.info("TTS: пробуем %s", provider.name)
            return await provider.synthesize(chunk)
        except Exception as exc:
            last_error = exc
            logger.warning("TTS %s не сработал: %s", provider.name, exc)

    if len(providers) == 1:
        raise RuntimeError(f"Не удалось создать озвучку через {providers[0].name}. {last_error}") from last_error
    raise RuntimeError(f"Озвучка не создана. Проверены сервисы: {', '.join(p.name for p in providers)}. Последняя ошибка: {last_error}") from last_error
