"""Фабрика LLM с цепочкой fallback."""

from src.config import Settings
from src.providers.llm.base import LLMProvider
from src.providers.llm.openai_provider import OpenAILLMProvider
from src.providers.llm.yandex import YandexGPTProvider


def build_llm_chain(settings: Settings) -> list[LLMProvider]:
    providers: list[LLMProvider] = []
    for name in settings.llm_fallbacks:
        if name == "yandex":
            providers.append(
                YandexGPTProvider(
                    api_key=settings.yandex_gpt_api_key or settings.yandex_api_key,
                    folder_id=settings.yandex_gpt_folder_id or settings.yandex_folder_id,
                    model=settings.yandex_gpt_model,
                )
            )
        elif name == "openai":
            providers.append(OpenAILLMProvider(settings.openai_api_key, settings.openai_llm_model))
    return providers
