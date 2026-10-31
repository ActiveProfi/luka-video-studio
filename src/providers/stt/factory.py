"""Фабрика STT с цепочкой fallback."""

from src.config import Settings
from src.providers.stt.base import STTProvider
from src.providers.stt.faster_whisper_provider import FasterWhisperSTTProvider
from src.providers.stt.openai_provider import OpenAISTTProvider
from src.providers.stt.yandex import YandexSTTProvider


def build_stt_chain(settings: Settings) -> list[STTProvider]:
    providers: list[STTProvider] = []
    for name in settings.stt_fallbacks:
        if name == "yandex":
            providers.append(
                YandexSTTProvider(
                    api_key=settings.yandex_api_key or settings.yandex_gpt_api_key,
                    folder_id=settings.yandex_folder_id or settings.yandex_gpt_folder_id,
                    model=settings.yandex_stt_model,
                )
            )
        elif name == "openai":
            providers.append(
                OpenAISTTProvider(
                    settings.openai_api_key, settings.openai_stt_model, settings=settings
                )
            )
        elif name == "faster_whisper":
            providers.append(
                FasterWhisperSTTProvider(
                    model=settings.whisper_model,
                    device=settings.whisper_device,
                    compute_type=settings.whisper_compute_type,
                )
            )
    return providers
