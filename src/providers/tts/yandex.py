"""Yandex SpeechKit TTS."""

from __future__ import annotations

import logging
import asyncio

import httpx

from src.config import Settings, get_settings
from src.providers.tts.base import TTSChunk, TTSProvider, TTSResult
from src.services.ffmpeg_service import get_media_duration_seconds, lpcm_bytes_to_wav

logger = logging.getLogger(__name__)

TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
SAMPLE_RATE = 48000


class YandexTTSProvider(TTSProvider):
    name = "yandex"

    def __init__(
        self,
        api_key: str,
        folder_id: str,
        voice: str = "alena",
        emotion: str = "neutral",
        speed: float = 1.0,
        settings: Settings | None = None,
    ) -> None:
        self.api_key = api_key
        self.folder_id = folder_id
        self.voice = voice
        self.emotion = emotion
        self.speed = speed
        self.settings = settings or get_settings()

    async def synthesize(self, chunk: TTSChunk) -> TTSResult:
        if not self.api_key:
            raise RuntimeError("Yandex TTS: задайте YANDEX_API_KEY в .env")
        if not self.folder_id:
            raise RuntimeError("Yandex TTS: задайте YANDEX_FOLDER_ID в .env")
        if not chunk.text.strip():
            raise ValueError("Пустой текст для озвучки")

        lang = "ru-RU" if chunk.language.startswith("ru") else chunk.language
        from src.services.tts_normalization_rules import prepare_provider_speech_text

        # A small explicit boundary keeps the final letter from merging with
        # the following word ("эс мы" must not sound like a single token).
        spoken = prepare_provider_speech_text(chunk.text.strip(), self.settings, "yandex")
        data = {
            "text": spoken,
            "lang": lang,
            "voice": self.voice,
            "folderId": self.folder_id,
            "format": "lpcm",
            "sampleRateHertz": str(SAMPLE_RATE),
            "emotion": self.emotion,
            "speed": str(self.speed),
        }
        headers = {"Authorization": f"Api-Key {self.api_key}"}

        async with httpx.AsyncClient(timeout=120.0) as client:
            for attempt in range(3):
                response = await client.post(TTS_URL, data=data, headers=headers)
                if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                    break
                logger.warning("Yandex TTS: HTTP %s, повтор %s/2", response.status_code, attempt + 1)
                await asyncio.sleep(2 ** attempt)
            if response.status_code != 200:
                logger.warning("Yandex TTS response: %s %s", response.status_code, response.text[:300])
                raise RuntimeError(
                    f"Yandex TTS вернул ошибку {response.status_code}. "
                    "Озвучка не создана. Сценарий сохранён. "
                    "Повторите озвучку позже или выберите другой сервис в оформлении видео."
                )
            audio_bytes = response.content

        chunk.output_path.parent.mkdir(parents=True, exist_ok=True)
        lpcm_bytes_to_wav(
            audio_bytes, chunk.output_path, sample_rate=SAMPLE_RATE, settings=self.settings
        )
        duration = get_media_duration_seconds(chunk.output_path, self.settings)
        logger.info("Yandex TTS: %.1f с, %s символов", duration, len(chunk.text))
        return TTSResult(
            output_path=chunk.output_path, provider=self.name, duration_seconds=duration
        )
