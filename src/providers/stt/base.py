"""Базовые интерфейсы STT-провайдеров."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WordTimestamp:
    word: str
    start: float
    end: float
    confidence: float | None = None


@dataclass
class TranscriptSegment:
    segment_id: str
    start: float
    end: float
    text: str
    confidence: float | None = None
    words: list[WordTimestamp] = field(default_factory=list)


@dataclass
class STTResult:
    language: str
    duration_seconds: float
    segments: list[TranscriptSegment]
    provider: str


class STTProvider(ABC):
    name: str

    @abstractmethod
    async def transcribe(self, audio_path: Path, language: str = "ru") -> STTResult:
        ...
