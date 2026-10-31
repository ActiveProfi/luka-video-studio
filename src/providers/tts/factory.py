"""Фабрика TTS с цепочкой fallback."""

from src.config import Settings
from src.providers.tts.base import TTSProvider
from src.providers.tts.openai_provider import OpenAITTSProvider
from src.providers.tts.yandex import YandexTTSProvider
from src.providers.tts.elevenlabs import ElevenLabsTTSProvider
from src.providers.tts.edge import EdgeTTSProvider


def build_tts_chain(settings: Settings) -> list[TTSProvider]:
    providers: list[TTSProvider] = []
    for name in settings.tts_fallbacks:
        if name == "edge":
            providers.append(EdgeTTSProvider(settings))
        if name == "elevenlabs" and settings.elevenlabs_api_key and settings.elevenlabs_voice_id:
            providers.append(ElevenLabsTTSProvider(settings))
        if name == "yandex":
            api_key = settings.yandex_api_key or settings.yandex_gpt_api_key
            folder_id = settings.yandex_folder_id or settings.yandex_gpt_folder_id
            if api_key and folder_id:
                providers.append(
                    YandexTTSProvider(
                        api_key=api_key,
                        folder_id=folder_id,
                        voice=settings.yandex_tts_voice,
                        emotion=settings.yandex_tts_emotion,
                        speed=settings.yandex_tts_speed,
                        settings=settings,
                    )
                )
        elif name == "openai":
            if settings.openai_api_key:
                providers.append(
                    OpenAITTSProvider(
                        api_key=settings.openai_api_key,
                        model=settings.openai_tts_model,
                        voice=settings.openai_tts_voice,
                        settings=settings,
                    )
                )
    return providers
