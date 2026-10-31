"""Selected multilingual Edge TTS voices, without a silent voice fallback."""
import asyncio
import subprocess
import tempfile
from pathlib import Path

from src.config import Settings
from src.providers.tts.base import TTSChunk, TTSProvider, TTSResult
from src.services.ffmpeg_service import _ffmpeg_bin, get_media_duration_seconds


class EdgeTTSProvider(TTSProvider):
    name = "edge"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def synthesize(self, chunk: TTSChunk) -> TTSResult:
        import edge_tts
        from src.services.tts_normalization_rules import prepare_provider_speech_text
        if not chunk.text.strip():
            raise ValueError("Пустой текст для озвучки")
        s = self.settings
        text = prepare_provider_speech_text(chunk.text.strip(), s, "edge")
        rate = f"{round((s.edge_tts_speed - 1) * 100):+d}%"
        with tempfile.TemporaryDirectory(prefix="edge-tts-") as folder:
            source, wav = Path(folder) / "speech.mp3", Path(folder) / "speech.wav"
            for attempt in range(3):
                try:
                    await asyncio.wait_for(edge_tts.Communicate(text, s.edge_tts_voice, rate=rate).save(str(source)), timeout=120)
                    break
                except Exception as exc:
                    if attempt == 2:
                        raise RuntimeError("Edge TTS не выдал звук. Сценарий сохранён; повторите озвучку позже.") from exc
                    await asyncio.sleep(2 ** attempt)
            subprocess.run([_ffmpeg_bin(s), "-nostdin", "-y", "-v", "error", "-i", str(source),
                            "-ar", "48000", "-ac", "1", str(wav)], check=True, capture_output=True)
            duration = get_media_duration_seconds(wav, s)
            if duration <= 0:
                raise RuntimeError("Edge TTS вернул пустую аудиозапись.")
            chunk.output_path.parent.mkdir(parents=True, exist_ok=True)
            chunk.output_path.write_bytes(wav.read_bytes())
        return TTSResult(chunk.output_path, self.name, duration)
