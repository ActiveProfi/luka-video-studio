"""Yandex SpeechKit STT (синхронное распознавание по фрагментам)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from src.providers.stt.base import STTProvider, STTResult, TranscriptSegment
from src.services.ffmpeg_service import get_media_duration_seconds, split_audio_segments

logger = logging.getLogger(__name__)

STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
MAX_CHUNK_BYTES = 900_000  # ~30 сек OggOpus, лимит API ~1 МБ
SEGMENT_SECONDS = 25


class YandexSTTProvider(STTProvider):
    name = "yandex"

    def __init__(self, api_key: str, folder_id: str, model: str = "general") -> None:
        self.api_key = api_key
        self.folder_id = folder_id
        self.model = model

    async def transcribe(self, audio_path: Path, language: str = "ru") -> STTResult:
        if not self.api_key:
            raise RuntimeError("Yandex STT: задайте YANDEX_API_KEY в .env")
        if not self.folder_id:
            raise RuntimeError("Yandex STT: задайте YANDEX_FOLDER_ID в .env")

        lang = "ru-RU" if language.startswith("ru") else language
        chunks_dir = audio_path.parent / "_stt_chunks"
        chunks = self._prepare_chunks(audio_path, chunks_dir)

        segments: list[TranscriptSegment] = []
        async with httpx.AsyncClient(timeout=120.0) as client:
            for idx, (chunk_path, offset) in enumerate(chunks):
                text = await self._recognize_chunk(client, chunk_path, lang)
                if not text.strip():
                    continue
                chunk_duration = get_media_duration_seconds(chunk_path)
                if chunk_duration <= 0:
                    chunk_duration = float(SEGMENT_SECONDS)
                seg = TranscriptSegment(
                    segment_id=f"seg_{idx + 1:03d}",
                    start=float(offset),
                    end=float(offset + chunk_duration),
                    text=text.strip(),
                    confidence=0.9,
                )
                segments.append(seg)
                logger.info("STT фрагмент %s/%s: %s...", idx + 1, len(chunks), text[:40])

        if not segments:
            raise RuntimeError("Yandex STT: не удалось распознать речь (пустой результат)")

        duration = segments[-1].end
        return STTResult(
            language=language,
            duration_seconds=duration,
            segments=segments,
            provider=self.name,
        )

    def _prepare_chunks(self, audio_path: Path, chunks_dir: Path) -> list[tuple[Path, float]]:
        size = audio_path.stat().st_size
        if size <= MAX_CHUNK_BYTES:
            return [(audio_path, 0.0)]
        return split_audio_segments(audio_path, chunks_dir, SEGMENT_SECONDS)

    async def _recognize_chunk(self, client: httpx.AsyncClient, path: Path, lang: str) -> str:
        params = {
            "lang": lang,
            "folderId": self.folder_id,
            "topic": self.model,
            "format": "oggopus",
        }
        headers = {"Authorization": f"Api-Key {self.api_key}"}
        data = path.read_bytes()

        response = await client.post(STT_URL, params=params, headers=headers, content=data)
        if response.status_code != 200:
            raise RuntimeError(f"Yandex STT ошибка {response.status_code}: {response.text[:300]}")

        body = response.text.strip()
        if not body:
            return ""
        try:
            parsed = json.loads(body)
            return str(parsed.get("result", ""))
        except json.JSONDecodeError:
            return body
