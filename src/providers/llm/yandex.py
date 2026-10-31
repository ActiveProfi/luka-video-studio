"""Yandex GPT (Foundation Models API)."""

from __future__ import annotations

import logging

import httpx

from src.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


class YandexGPTProvider(LLMProvider):
    name = "yandex"

    def __init__(self, api_key: str, folder_id: str, model: str = "yandexgpt-lite") -> None:
        self.api_key = api_key
        self.folder_id = folder_id
        self.model = model

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("Yandex GPT: задайте YANDEX_GPT_API_KEY в .env")
        if not self.folder_id:
            raise RuntimeError("Yandex GPT: задайте YANDEX_GPT_FOLDER_ID в .env")

        model_uri = f"gpt://{self.folder_id}/{self.model}/latest"
        payload = {
            "modelUri": model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.2,
                "maxTokens": 8000,
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_prompt},
            ],
        }
        headers = {"Authorization": f"Api-Key {self.api_key}"}

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(COMPLETION_URL, headers=headers, json=payload)
            if response.status_code != 200:
                raise RuntimeError(f"Yandex GPT ошибка {response.status_code}: {response.text[:400]}")

            body = response.json()
            try:
                text = body["result"]["alternatives"][0]["message"]["text"]
            except (KeyError, IndexError) as exc:
                raise RuntimeError(f"Yandex GPT: неожиданный ответ: {body}") from exc

            logger.info("Yandex GPT ответ: %s символов", len(text))
            return text.strip()
