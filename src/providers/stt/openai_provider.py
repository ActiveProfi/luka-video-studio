"""OpenAI Whisper STT (резервный провайдер)."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI

from src.config import Settings
from src.providers.stt.base import STTProvider, STTResult, TranscriptSegment
from src.providers.stt.faster_whisper_provider import FasterWhisperSTTProvider
from src.services.ffmpeg_service import _ffmpeg_bin
from src.services.speech_units import group_speech_units
from src.services.transcript_alignment import align_transcript

logger = logging.getLogger(__name__)


def merge_short_units(units: list[dict]) -> list[dict]:
    result = []
    index = 0
    while index < len(units):
        unit = dict(units[index])
        while (
            unit["end"] - unit["start"] < 8
            and index + 1 < len(units)
            and units[index + 1]["start"] - unit["end"] < 0.7
            and units[index + 1]["end"] - unit["start"] <= 24
        ):
            unit["end"] = units[index + 1]["end"]
            index += 1
        result.append(unit)
        index += 1
    return result


def valid_transcription(text: str, context: str, seconds: float) -> bool:
    normalized = " ".join(text.casefold().split()).strip(" .")
    prompt = " ".join(context.casefold().split())
    # Reject impossible speaking rates and long verbatim copies of the prompt.
    return (
        bool(normalized)
        and len(text.split()) <= max(8, seconds * 7)
        and not (len(normalized) >= 45 and normalized[:45] in prompt)
    )


class OpenAISTTProvider(STTProvider):
    name = "openai"

    def __init__(
        self, api_key: str, model: str = "whisper-1", *, settings: Settings | None = None
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.settings = settings or Settings(_env_file=None)

    async def _contextual_transcribe(self, audio_path: Path, language: str) -> STTResult:
        cfg = self.settings
        anchors = await FasterWhisperSTTProvider(
            cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute_type
        ).transcribe(audio_path, language)
        batches: list[list[TranscriptSegment]] = []
        for segment in anchors.segments:
            if not batches or segment.end - batches[-1][0].start > 600:
                batches.append([])
            batches[-1].append(segment)
        recognized = []
        with OpenAI(api_key=self.api_key) as client, tempfile.TemporaryDirectory() as work:
            for index, batch in enumerate(batches):
                start, end = batch[0].start, batch[-1].end
                clip = Path(work) / f"context_{index}.wav"
                subprocess.run(
                    [
                        _ffmpeg_bin(cfg),
                        "-y",
                        "-i",
                        str(audio_path),
                        "-ss",
                        str(start),
                        "-t",
                        str(end - start),
                        "-ar",
                        "16000",
                        "-ac",
                        "1",
                        str(clip),
                    ],
                    capture_output=True,
                    check=True,
                )
                kwargs = {"model": self.model, "response_format": "json", "prompt": cfg.stt_context}
                if self.model == "gpt-transcribe":
                    kwargs["extra_body"] = {
                        "languages": [language[:2]],
                        "keywords": cfg.stt_keywords.split(","),
                    }
                else:
                    kwargs["language"] = language[:2]
                with clip.open("rb") as audio:
                    response = client.audio.transcriptions.create(file=audio, **kwargs)
                text = str(response.text or "").strip()
                if not valid_transcription(text, cfg.stt_context, end - start):
                    raise ValueError("Invalid context transcription")
                recognized.extend(align_transcript(text, batch))
        return STTResult(language, anchors.duration_seconds, recognized, self.name)

    async def _chunked_contextual_transcribe(self, audio_path: Path, language: str) -> STTResult:
        # These models return text, not word timestamps. Local recognition supplies
        # acoustic phrase boundaries only; its words are never used as the new text.
        cfg = self.settings
        anchors = await FasterWhisperSTTProvider(
            cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute_type
        ).transcribe(audio_path, language)
        units = group_speech_units(
            [
                {"segment_id": s.segment_id, "start": s.start, "end": s.end, "text": s.text}
                for s in anchors.segments
            ]
        )
        units = merge_short_units(units)
        segments = []
        keywords = [s.strip() for s in cfg.stt_keywords.split(",") if s.strip()]
        with OpenAI(api_key=self.api_key) as client, tempfile.TemporaryDirectory() as work:
            for index, unit in enumerate(units):
                clip = Path(work) / f"phrase_{index:04}.wav"
                start, end = float(unit["start"]), float(unit["end"])
                subprocess.run(
                    [
                        _ffmpeg_bin(cfg),
                        "-y",
                        "-ss",
                        str(start),
                        "-i",
                        str(audio_path),
                        "-t",
                        str(end - start),
                        "-ar",
                        "16000",
                        "-ac",
                        "1",
                        str(clip),
                    ],
                    capture_output=True,
                    check=True,
                )
                prompt = cfg.stt_context
                kwargs = {"model": self.model, "response_format": "json", "prompt": prompt}
                if self.model == "gpt-transcribe":
                    kwargs["extra_body"] = {"languages": [language[:2]], "keywords": keywords}
                else:
                    kwargs["language"] = language[:2]
                    kwargs["prompt"] += "\nТермины: " + ", ".join(keywords)
                text = ""
                for attempt in range(3):
                    request = dict(kwargs)
                    if attempt:
                        request["prompt"] = cfg.stt_context
                    if attempt == 2 and self.model == "gpt-transcribe":
                        request.pop("extra_body", None)
                        request.update(model="gpt-4o-transcribe", language=language[:2])
                    with clip.open("rb") as audio:
                        response = client.audio.transcriptions.create(file=audio, **request)
                    text = str(response.text or "").strip()
                    if valid_transcription(text, prompt, end - start):
                        break
                    text = ""
                if not text:
                    raise ValueError(f"Пустая транскрибация фразы {index + 1}")
                logger.info("Context STT: phrase %s/%s ready", index + 1, len(units))
                segments.append(
                    TranscriptSegment(
                        segment_id=f"seg_{index + 1:03d}",
                        start=start,
                        end=end,
                        text=text,
                        confidence=None,
                    )
                )
        return STTResult(language, anchors.duration_seconds, segments, self.name)

    async def transcribe(self, audio_path: Path, language: str = "ru") -> STTResult:
        if not self.api_key:
            raise RuntimeError("OpenAI STT: задайте OPENAI_API_KEY в .env")

        if self.model != "whisper-1":
            return await self._contextual_transcribe(audio_path, language)

        client = OpenAI(api_key=self.api_key)
        logger.info("OpenAI Whisper: %s", audio_path.name)

        with audio_path.open("rb") as f:
            result = client.audio.transcriptions.create(
                model=self.model,
                file=f,
                language=language[:2],
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        segments: list[TranscriptSegment] = []
        raw_segments = getattr(result, "segments", None) or []
        for idx, seg in enumerate(raw_segments):
            segments.append(
                TranscriptSegment(
                    segment_id=f"seg_{idx + 1:03d}",
                    start=float(seg.start),
                    end=float(seg.end),
                    text=str(seg.text).strip(),
                    confidence=0.85,
                )
            )

        if not segments and result.text:
            segments.append(
                TranscriptSegment(
                    segment_id="seg_001",
                    start=0.0,
                    end=float(getattr(result, "duration", 0) or 0),
                    text=result.text.strip(),
                    confidence=0.85,
                )
            )

        duration = float(getattr(result, "duration", 0) or (segments[-1].end if segments else 0))
        return STTResult(
            language=language,
            duration_seconds=duration,
            segments=segments,
            provider=self.name,
        )
