"""Базовый интерфейс LLM-провайдеров."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Вернуть текст ответа модели."""
