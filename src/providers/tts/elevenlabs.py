"""ElevenLabs speech synthesis using the explicitly selected voice."""
import subprocess
import tempfile
from pathlib import Path

import httpx

from src.config import Settings
from src.providers.tts.base import TTSChunk, TTSProvider, TTSResult
from src.services.ffmpeg_service import _ffmpeg_bin, get_media_duration_seconds


class ElevenLabsTTSProvider(TTSProvider):
    name = "elevenlabs"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def synthesize(self, chunk: TTSChunk) -> TTSResult:
        s = self.settings
        if not s.elevenlabs_api_key or not s.elevenlabs_voice_id:
            raise RuntimeError("ElevenLabs: настройте API-ключ и выберите голос.")
        if not chunk.text.strip():
            raise ValueError("Пустой текст для озвучки")
        from src.services.tts_normalization_rules import prepare_provider_speech_text
        payload = {
            "text": prepare_provider_speech_text(chunk.text.strip(), s, "elevenlabs"),
            "model_id": s.elevenlabs_model,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.75,
                               "style": 0, "use_speaker_boost": True, "speed": s.elevenlabs_speed},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{s.elevenlabs_voice_id}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": s.elevenlabs_api_key}, json=payload)
        if response.status_code != 200:
            try:
                detail = response.json().get("detail", {})
            except ValueError:
                detail = {}
            if isinstance(detail, dict) and detail.get("status") == "quota_exceeded":
                raise RuntimeError("В ElevenLabs закончились доступные кредиты для этой фразы. Пополните лимит или выберите другой сервис озвучки. Сценарий сохранён.")
            raise RuntimeError(f"ElevenLabs: ошибка {response.status_code}. Проверьте доступ к голосу, права ключа и остаток кредитов. Сценарий сохранён.")
        if not response.content:
            raise RuntimeError("ElevenLabs вернул пустую аудиозапись.")
        chunk.output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="elevenlabs-") as folder:
            source = Path(folder) / "speech.mp3"
            wav = Path(folder) / "speech.wav"
            source.write_bytes(response.content)
            subprocess.run([_ffmpeg_bin(s), "-nostdin", "-y", "-v", "error", "-i", str(source),
                            "-ar", "48000", "-ac", "1", str(wav)], check=True, capture_output=True)
            duration = get_media_duration_seconds(wav, s)
            if duration <= 0:
                raise RuntimeError("ElevenLabs: аудиозапись не содержит звука.")
            chunk.output_path.write_bytes(wav.read_bytes())
        return TTSResult(chunk.output_path, self.name, duration)
