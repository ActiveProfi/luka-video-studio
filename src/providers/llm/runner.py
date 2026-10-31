"""Запуск LLM с цепочкой fallback."""

from __future__ import annotations

import logging
from collections.abc import Callable

from src.config import Settings
from src.providers.llm.factory import build_llm_chain

logger = logging.getLogger(__name__)


async def complete_with_fallback(
    settings: Settings,
    system_prompt: str,
    user_prompt: str,
    *,
    validate_response: Callable[[str], object] | None = None,
) -> tuple[str, str]:
    """Вернуть (текст ответа, имя провайдера)."""
    providers = build_llm_chain(settings)
    if not providers:
        raise RuntimeError("Нет доступных LLM-провайдеров. Проверьте .env")

    last_error: Exception | None = None
    validation_failed = False
    for provider in providers:
        retry_prompt = user_prompt
        for attempt in range(2 if validate_response else 1):
            try:
                logger.info("LLM: пробуем %s, попытка %s", provider.name, attempt + 1)
                text = await provider.complete(system_prompt, retry_prompt)
                if validate_response:
                    try:
                        validate_response(text)
                    except (ValueError, KeyError, TypeError) as exc:
                        validation_failed = True
                        last_error = exc
                        retry_prompt = user_prompt + "\n\nИсправь формат нового ответа с учётом ошибки проверки предыдущего ответа: " + str(exc)[:1200]
                        logger.warning("LLM %s: ответ не прошёл проверку (%s)", provider.name, type(exc).__name__)
                        continue
                return text, provider.name
            except Exception as exc:
                last_error = exc
                logger.warning("LLM %s не сработал (%s)", provider.name, type(exc).__name__)

    if validation_failed:
        raise RuntimeError("ИИ ответил, но результат не прошёл автоматическую проверку формата или содержания. Повторите создание сценария; исходный урок сохранён.") from last_error
    raise RuntimeError(f"Все LLM-провайдеры недоступны. Последняя ошибка: {last_error}")
