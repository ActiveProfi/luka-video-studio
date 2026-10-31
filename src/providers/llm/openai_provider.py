"""OpenAI Chat Completions — резервный LLM."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from src.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAILLMProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self.api_key = api_key
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key) if api_key else None

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        if not self.api_key or self._client is None:
            raise RuntimeError("OpenAI LLM: задайте OPENAI_API_KEY в .env")

        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        logger.info("OpenAI LLM ответ: %s символов", len(text))
        return text.strip()
