"""Сборка voiceover.wav из фрагментов TTS."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.config import Settings
from src.services.ffmpeg_service import (
    concat_wav_files,
    generate_silence_wav,
    get_media_duration_seconds,
    pad_wav_to_duration,
)

logger = logging.getLogger(__name__)


@dataclass
class VoiceoverPart:
    wav_path: Path
    target_start: float
    audio_duration: float


def assemble_voiceover(
    parts: list[VoiceoverPart],
    output_path: Path,
    total_duration: float,
    settings: Settings | None = None,
) -> float:
    """Разложить фрагменты по целевой шкале времени и склеить в один WAV."""
    if not parts:
        raise ValueError("Нет фрагментов озвучки для сборки")

    work_dir = output_path.parent / "_tts_build"
    work_dir.mkdir(parents=True, exist_ok=True)

    ordered = sorted(parts, key=lambda p: p.target_start)
    timeline_files: list[Path] = []
    cursor = 0.0

    for idx, part in enumerate(ordered):
        gap = part.target_start - cursor
        if gap < -0.01:
            raise ValueError("Фрагменты озвучки перекрываются: проверьте тайминг")
        if gap >= 0.001:
            silence = work_dir / f"gap_{idx:03d}.wav"
            generate_silence_wav(gap, silence, settings=settings)
            timeline_files.append(silence)
            cursor += gap
        timeline_files.append(part.wav_path)
        cursor += part.audio_duration

    if total_duration > cursor + 0.05:
        tail = work_dir / "tail_silence.wav"
        generate_silence_wav(total_duration - cursor, tail, settings=settings)
        timeline_files.append(tail)

    merged = work_dir / "merged.wav"
    concat_wav_files(timeline_files, merged, settings=settings)
    pad_wav_to_duration(merged, output_path, total_duration, settings=settings)
    duration = get_media_duration_seconds(output_path, settings)
    logger.info("Voiceover собран: %.1f с (цель %.1f с)", duration, total_duration)
    return duration
