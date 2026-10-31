"""Локальный STT через faster-whisper (модель medium и др.)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.providers.stt.base import STTProvider, STTResult, TranscriptSegment, WordTimestamp

logger = logging.getLogger(__name__)


class FasterWhisperSTTProvider(STTProvider):
    name = "faster_whisper"

    def __init__(
        self,
        model: str = "medium",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model = model
        self.device = device
        self.compute_type = compute_type

    async def transcribe(self, audio_path: Path, language: str = "ru") -> STTResult:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language)

    def _transcribe_sync(self, audio_path: Path, language: str) -> STTResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper не установлен. В папке проекта выполните: "
                "pip install faster-whisper"
            ) from exc

        if not audio_path.exists():
            raise FileNotFoundError(f"Аудиофайл не найден: {audio_path}")

        logger.info(
            "faster-whisper: модель=%s device=%s file=%s",
            self.model,
            self.device,
            audio_path.name,
        )
        model = WhisperModel(
            self.model,
            device=self.device,
            compute_type=self.compute_type,
        )
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language[:2] if language else "ru",
            vad_filter=True,
            word_timestamps=True,
        )

        segments: list[TranscriptSegment] = []
        for idx, seg in enumerate(segments_iter):
            text = str(seg.text or "").strip()
            if not text:
                continue
            conf = None
            if seg.avg_logprob is not None:
                # avg_logprob обычно от -1 до 0 → грубая оценка 0..1
                conf = max(0.0, min(1.0, 1.0 + float(seg.avg_logprob)))
            segments.append(
                TranscriptSegment(
                    segment_id=f"seg_{idx + 1:03d}",
                    start=float(seg.start),
                    end=float(seg.end),
                    text=text,
                    confidence=conf if conf is not None else 0.8,
                    words=[WordTimestamp(word=w.word.strip(), start=float(w.start),
                                         end=float(w.end), confidence=float(w.probability))
                           for w in (seg.words or [])],
                )
            )

        if not segments:
            raise RuntimeError("faster-whisper: не удалось распознать речь (пустой результат)")

        duration = float(getattr(info, "duration", 0) or segments[-1].end)
        return STTResult(
            language=language,
            duration_seconds=duration,
            segments=segments,
            provider=self.name,
        )
