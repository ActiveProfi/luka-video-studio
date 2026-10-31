"""OpenAI TTS (резервный провайдер)."""

from __future__ import annotations

import logging

from openai import OpenAI

from src.config import Settings, get_settings
from src.providers.tts.base import TTSChunk, TTSProvider, TTSResult
from src.services.ffmpeg_service import get_media_duration_seconds

logger = logging.getLogger(__name__)


class OpenAITTSProvider(TTSProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "tts-1-hd",
        voice: str = "nova",
        settings: Settings | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.settings = settings or get_settings()

    async def synthesize(self, chunk: TTSChunk) -> TTSResult:
        if not self.api_key:
            raise RuntimeError("OpenAI TTS: задайте OPENAI_API_KEY в .env")
        if not chunk.text.strip():
            raise ValueError("Пустой текст для озвучки")

        client = OpenAI(api_key=self.api_key)
        from src.services.tts_normalization_rules import prepare_provider_speech_text

        chunk.output_path.parent.mkdir(parents=True, exist_ok=True)
        response = client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=prepare_provider_speech_text(chunk.text.strip(), self.settings, "openai"),
            response_format="wav",
            speed=self.settings.openai_tts_speed,
        )
        response.stream_to_file(str(chunk.output_path))
        duration = get_media_duration_seconds(chunk.output_path, self.settings)
        logger.info("OpenAI TTS: %.1f с", duration)
        return TTSResult(
            output_path=chunk.output_path, provider=self.name, duration_seconds=duration
        )
